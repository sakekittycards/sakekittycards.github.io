/**
 * The publisher — the last thing that runs before something is public.
 *
 * Everything that could make a post wrong is re-checked here, at the last
 * possible moment, on the assumption that any check made earlier is now stale:
 *
 *   1. the item is leased by us and nobody else                (scheduler.claim)
 *   2. a reel's video is STILL approved and unchanged          (assertPublishable)
 *   3. the subject has not moved since approval                (fingerprint)
 *   4. we are not about to re-publish something already out    (container reuse)
 *
 * Dry run is not a separate code path. The identical function builds the
 * identical payload and stops one line short of the call, which is the only
 * version of a dry run worth having — a mock pipeline proves nothing about the
 * real one.
 */
import { nowMs, stableId } from './util.js';
import { getItem, renderCaption, computeSubjectFingerprint } from './items.js';
import { assertPublishable, NotApproved, advance } from './video.js';
import { getMedia, mediaUrl } from './media.js';
import { claim, releaseLease, backoffMs, MAX_ATTEMPTS } from './scheduler.js';
import { effectiveMode } from './policy.js';
import * as ig from './instagram.js';
import { log, notify } from './log.js';

export class PublishRefused extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'PublishRefused';
    this.code = code;
  }
}

/**
 * Build exactly what would be sent to Instagram, with every safety check run.
 *
 * Pure and side-effect free, so it backs both the real publish and the dry-run
 * report. If this throws, publishing would have thrown too — which is the point.
 */
export async function buildPayload(env, item) {
  // Check 2 FIRST, before anything else can shadow it.
  //
  // Ordering is load-bearing. The fingerprint check below would also catch a
  // changed or deleted video, but it would report it as "the event details
  // changed" — which means the invariant's enforcement would quietly depend on
  // an unrelated check happening to run first. Running the approval gate at the
  // top makes it the reason a reel is refused, always, and keeps the fingerprint
  // check as a second, independent layer rather than the load-bearing one.
  const video = item.type === 'reel' ? await assertPublishable(env, item.video_id) : null;

  const caption = renderCaption(item);
  if (!caption.trim()) throw new PublishRefused('item has no caption', 'no_caption');
  if (caption.length > 2200) {
    throw new PublishRefused(`caption is ${caption.length} chars, over Instagram's 2200 limit`, 'caption_too_long');
  }

  // Check 3 — the subject must be what it was when a human said yes.
  const fp = await computeSubjectFingerprint(env, item);
  if (item.subject_fingerprint && fp !== item.subject_fingerprint) {
    throw new PublishRefused(
      fp === 'missing'
        ? 'the source event or video no longer exists'
        : 'the event details changed after approval — needs re-review',
      'stale_subject'
    );
  }

  if (item.type === 'reel') {
    // `video` was resolved by the approval gate at the top of this function —
    // the second of the two enforcement points; the first is items.createReelItem.
    const media = item.media_id ? await getMedia(env, item.media_id) : null;
    if (!media) {
      throw new PublishRefused('the approved video has not been uploaded for delivery yet', 'no_media');
    }
    if (media.sha256 !== video.approved_sha256) {
      throw new PublishRefused(
        'the uploaded video does not match the approved file — refusing',
        'media_mismatch'
      );
    }
    const cover = item.cover_media_id ? await getMedia(env, item.cover_media_id) : null;
    return {
      kind: 'reel',
      endpoint: `POST /${env.IG_USER_ID || '{ig-user-id}'}/media`,
      params: {
        media_type: 'REELS',
        video_url: mediaUrl(env, media),
        caption,
        share_to_feed: 'true',
        ...(cover ? { cover_url: mediaUrl(env, cover) } : {}),
      },
      approval: {
        video_id: video.id,
        approved_by: video.approved_by,
        approved_at: video.approved_at,
        approval_source: video.approval_source,
        sha256: video.approved_sha256,
      },
    };
  }

  if (item.type === 'event') {
    const media = item.media_id ? await getMedia(env, item.media_id) : null;
    if (!media) throw new PublishRefused('no graphic attached', 'no_media');
    if (item.surface === 'story') {
      return {
        kind: 'story',
        endpoint: `POST /${env.IG_USER_ID || '{ig-user-id}'}/media`,
        params: { media_type: 'STORIES', image_url: mediaUrl(env, media) },
        approval: null,
      };
    }
    return {
      kind: 'image',
      endpoint: `POST /${env.IG_USER_ID || '{ig-user-id}'}/media`,
      params: { image_url: mediaUrl(env, media), caption },
      approval: null,
    };
  }

  throw new PublishRefused(`unknown item type ${item.type}`, 'unknown_type');
}

/**
 * Publish one item.
 *
 * Ordering note that matters more than it looks: the container id is written to
 * the database BEFORE `media_publish` is called. If the publish call times out
 * after Instagram accepted it, the next attempt finds the container id, checks
 * whether it already became a post, and adopts it instead of creating a second.
 * Writing the id after the call would lose exactly the information needed to
 * avoid a double post.
 */
export async function publishItem(env, itemId, policy, { at = nowMs(), force = false } = {}) {
  const mode = effectiveMode(env, policy);

  const token = await claim(env, itemId, { at });
  if (!token) {
    return { ok: false, skipped: true, reason: 'another worker holds the lease, or the item is no longer scheduled' };
  }

  const item = await getItem(env, itemId);
  let payload;
  try {
    payload = await buildPayload(env, item);
  } catch (e) {
    const permanent = e instanceof PublishRefused || e instanceof NotApproved;
    await record(env, item, 'build', false, { error_kind: e.code || 'build', error: e.message }, mode, at);
    await releaseLease(env, itemId, token, permanent ? 'needs_review' : 'failed', {
      at, reason: e.message,
      nextRetryAt: permanent ? null : at + backoffMs(item.attempts),
    });
    await log(env, 'error', 'publish', itemId, `Refused to publish: ${e.message}`, null, at);
    return { ok: false, refused: true, reason: e.message, code: e.code };
  }

  if (mode === 'dry' && !force) {
    await record(env, item, 'dry-run', true, { payload }, mode, at);
    await releaseLease(env, itemId, token, 'scheduled', {
      at, reason: 'dry run — not published', nextRetryAt: at + 6 * 3600e3,
    });
    await log(env, 'info', 'publish', itemId,
      `DRY RUN — would publish "${item.title}" (${payload.kind})`,
      { endpoint: payload.endpoint, params: redact(payload.params) }, at);
    return { ok: true, dryRun: true, payload };
  }

  try {
    // If a previous attempt already produced a container, do not make another.
    let containerId = item.ig_creation_id;

    if (containerId) {
      const adopted = await adoptIfAlreadyPublished(env, item, payload, at);
      if (adopted) {
        await finish(env, item, token, adopted.id, adopted.permalink, at, mode, 'adopted');
        return { ok: true, adopted: true, mediaId: adopted.id };
      }
    }

    if (!containerId) {
      containerId = payload.kind === 'reel'
        ? await ig.createReelContainer(env, {
          videoUrl: payload.params.video_url,
          caption: payload.params.caption,
          coverUrl: payload.params.cover_url || null,
        })
        : payload.kind === 'story'
          ? await ig.createStoryContainer(env, { imageUrl: payload.params.image_url })
          : await ig.createImageContainer(env, {
            imageUrl: payload.params.image_url,
            caption: payload.params.caption,
          });

      // Persist before publishing. See the note above the function.
      await env.DB.prepare('UPDATE content_items SET ig_creation_id=?, updated_at=? WHERE id=?')
        .bind(containerId, at, itemId).run();
      await record(env, item, 'container', true, { ig_creation_id: containerId }, mode, at);
    }

    await ig.waitForContainer(env, containerId, {
      timeoutMs: payload.kind === 'reel' ? 120000 : 30000,
    });

    const mediaId = await ig.publishContainer(env, containerId);
    let permalink = null;
    try {
      const meta = await ig.mediaPermalink(env, mediaId);
      permalink = meta.permalink || null;
    } catch {
      // A missing permalink is cosmetic; the post is out.
    }

    await finish(env, item, token, mediaId, permalink, at, mode, 'published');
    return { ok: true, mediaId, permalink };
  } catch (e) {
    return handleFailure(env, item, token, e, mode, at);
  }
}

async function finish(env, item, token, mediaId, permalink, at, mode, phase) {
  await env.DB.prepare(
    `UPDATE content_items SET status='published', ig_media_id=?, permalink=?, published_at=?,
       lease_token=NULL, lease_until=NULL, failure_reason=NULL, next_retry_at=NULL, updated_at=?
     WHERE id=? AND lease_token=?`
  ).bind(mediaId, permalink, at, at, item.id, token).run();

  if (item.opportunity_id) {
    await env.DB.prepare("UPDATE opportunities SET status='published', updated_at=? WHERE id=?")
      .bind(at, item.opportunity_id).run();
  }
  if (item.video_id) {
    await advance(env, item.video_id, 'PUBLISHED', { source: 'publisher', note: mediaId, at })
      .catch(() => {});
  }
  await record(env, item, phase, true, { ig_media_id: mediaId, permalink }, mode, at);
  await log(env, 'info', 'publish', item.id,
    `Published successfully: ${item.title}`, { ig_media_id: mediaId, permalink }, at);
  await notify(env, `📸 Published: ${item.title}\n${permalink || `media ${mediaId}`}`);
}

async function handleFailure(env, item, token, e, mode, at) {
  const kind = e instanceof ig.IgError ? e.kind : 'transient';
  const permanent = kind === 'permanent' || e instanceof PublishRefused || e instanceof NotApproved;
  const attempts = (item.attempts || 0) + 1;
  const exhausted = attempts >= MAX_ATTEMPTS;

  await record(env, item, 'publish', false, {
    error_kind: kind, error: String(e.message || e), code: e.code ?? null,
  }, mode, at);

  if (kind === 'auth') {
    // Nothing else will publish either. Say so once, loudly, instead of letting
    // every queued item fail one at a time.
    await env.DB.prepare("INSERT OR REPLACE INTO meta (k,v) VALUES ('token_health', ?)")
      .bind(JSON.stringify({ ok: false, at, error: String(e.message || e) })).run();
    await log(env, 'error', 'publish', item.id,
      `Instagram rejected our token — publishing is paused until it is refreshed. (${e.message})`, null, at);
    await notify(env, `🔑 Instagram token failed — publishing paused. ${e.message}`);
  }

  const status = permanent || exhausted ? 'failed' : 'scheduled';
  const nextRetryAt = status === 'scheduled'
    ? at + (kind === 'rate_limit' ? 45 * 60e3 : backoffMs(attempts))
    : null;

  await releaseLease(env, item.id, token, status, {
    at, reason: `${kind}: ${e.message}`, nextRetryAt,
  });

  await log(env, 'error', 'publish', item.id,
    status === 'failed'
      ? `Publish FAILED (${kind}) after ${attempts} attempt(s): ${e.message}`
      : `Publish attempt ${attempts} failed (${kind}), retrying later: ${e.message}`,
    { code: e.code ?? null, next_retry_at: nextRetryAt }, at);

  return { ok: false, error: e.message, kind, willRetry: status === 'scheduled' };
}

/**
 * Did the container we already made turn into a post while we were not looking?
 *
 * Only ever asked when a container id survives from a previous attempt, which is
 * exactly the timed-out-publish case.
 */
async function adoptIfAlreadyPublished(env, item, payload, at) {
  try {
    const match = await ig.findRecentByCaption(env, payload.params.caption || '');
    if (match) {
      await log(env, 'warn', 'publish', item.id,
        `A previous attempt had already published this — adopting ${match.id} instead of posting again`,
        { permalink: match.permalink }, at);
      return match;
    }
  } catch {
    // If we cannot check, fall through: waitForContainer will report an EXPIRED
    // or already-published container rather than us guessing.
  }
  return null;
}

async function record(env, item, phase, ok, extra, mode, at) {
  const id = await stableId('pub', item.id, String(item.attempts || 0), phase, String(at));
  await env.DB.prepare(
    `INSERT OR IGNORE INTO publications (id, item_id, attempt, mode, phase, ok, ig_creation_id,
       ig_media_id, permalink, error_kind, error, payload, at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(
    id, item.id, item.attempts || 0, mode, phase, ok ? 1 : 0,
    extra.ig_creation_id || null, extra.ig_media_id || null, extra.permalink || null,
    extra.error_kind || null, extra.error || null,
    extra.payload ? JSON.stringify(extra.payload).slice(0, 6000) : null, at
  ).run();
}

/** URLs carry a capability token; keep them out of the activity log. */
function redact(params) {
  const out = { ...params };
  for (const k of ['image_url', 'video_url', 'cover_url']) {
    if (out[k]) out[k] = String(out[k]).replace(/\/m\/[0-9a-f]+/, '/m/…');
  }
  return out;
}

/**
 * The shadow-mode report: run every due item through the full pipeline and
 * collect what would have happened, without leasing or mutating anything.
 */
export async function dryRunReport(env, policy, { at = nowMs(), horizonHours = 24 * 14 } = {}) {
  const rows = await env.DB.prepare(
    `SELECT * FROM content_items
      WHERE status IN ('approved','scheduled') ORDER BY COALESCE(scheduled_for, updated_at)`
  ).all();

  const out = [];
  for (const item of rows.results || []) {
    if (item.scheduled_for && item.scheduled_for > at + horizonHours * 3600e3) continue;
    try {
      const payload = await buildPayload(env, item);
      out.push({
        item_id: item.id, title: item.title, type: item.type, status: item.status,
        scheduled_for: item.scheduled_for, would: 'publish',
        endpoint: payload.endpoint, params: redact(payload.params),
        approval: payload.approval,
      });
    } catch (e) {
      out.push({
        item_id: item.id, title: item.title, type: item.type, status: item.status,
        scheduled_for: item.scheduled_for, would: 'refuse',
        reason: e.message, code: e.code || null,
      });
    }
  }
  return { mode: effectiveMode(env, policy), generated_at: at, items: out };
}
