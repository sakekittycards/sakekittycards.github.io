/**
 * sakekitty-social — the Sake Kitty Cards social content engine.
 *
 *   website events ──> ingest ──> opportunities ──> draft ──> APPROVAL ──> schedule ──> Instagram
 *   approved video ────────────────────────────────┘
 *
 * This worker is the system of record and the only thing that talks to
 * Instagram. Rendering happens locally (Pillow and ffmpeg do not run in a
 * Worker) and arrives here as finished bytes over the admin API, which also
 * means a graphic is stored and reviewable long before its publish time.
 *
 * Two rules are enforced here rather than trusted:
 *   - only an approved, unchanged video can become or remain a publishable reel
 *     (video.js, checked at draft creation and again at publish)
 *   - nothing publishes for real unless BOTH the deploy-time PUBLISH_MODE var
 *     and the runtime policy say 'live' (policy.effectiveMode)
 *
 * Everything is behind X-Sake-Admin-Token except `/health` and `/m/:token`,
 * which serves media to Instagram's fetcher.
 */
import { json, requireAdmin, CORS_HEADERS, nowMs, isoDate, easternToUtc, utcToEastern } from './util.js';
import { ensureSchema } from './schema.js';
import { getPolicy, setPolicy, effectiveMode, DEFAULT_POLICY } from './policy.js';
import { ingestEvents, humanDate } from './events.js';
import * as opps from './opportunities.js';
import * as video from './video.js';
import * as items from './items.js';
import * as mediaStore from './media.js';
import * as sched from './scheduler.js';
import * as pub from './publish.js';
import * as analytics from './analytics.js';
import * as ig from './instagram.js';
import { log, recent, notify } from './log.js';

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS_HEADERS });

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    // Media delivery: token in the path is the whole authorisation, because the
    // caller is Instagram's fetcher and cannot present a header.
    if (path.startsWith('/m/')) {
      await ensureSchema(env);
      return mediaStore.serveMedia(env, path.slice(3), request);
    }

    if (path === '/health') {
      await ensureSchema(env);
      const policy = await getPolicy(env);
      const health = await env.DB.prepare("SELECT v FROM meta WHERE k='token_health'").first();
      return json({
        ok: true,
        mode: effectiveMode(env, policy),
        deploy_mode: env.PUBLISH_MODE || 'dry',
        instagram_configured: Boolean(env.IG_ACCESS_TOKEN && env.IG_USER_ID),
        token_health: health ? JSON.parse(health.v) : { ok: null, note: 'never checked' },
      });
    }

    const denied = requireAdmin(request, env);
    if (denied) return denied;

    await ensureSchema(env);
    const at = nowMs();

    try {
      return await route(request, env, ctx, path, url, at);
    } catch (err) {
      console.error('social worker:', err && err.stack);
      const status = err instanceof video.NotApproved || err instanceof pub.PublishRefused ? 409 : 500;
      return json({ error: err.message || String(err), code: err.code || null }, status);
    }
  },

  /**
   * Every 15 minutes. The order is not arbitrary: opportunities are refreshed
   * before drafts are considered, and items are revalidated before anything is
   * published, so a change that landed since the last tick is caught before it
   * can go out rather than after.
   */
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      await ensureSchema(env);
      const at = nowMs();
      const policy = await getPolicy(env);
      try {
        await opps.refreshOpportunities(env, policy, { at });
        await items.revalidate(env, { at });
        await sched.reapStaleLeases(env, { at });

        const due = await sched.dueItems(env, { at, limit: 3 });
        for (const item of due) {
          await pub.publishItem(env, item.id, policy, { at });
        }

        // Hourly extras, keyed off the clock so they do not need their own cron.
        const hour = new Date(at).getUTCMinutes() < 15;
        if (hour) {
          if (env.IG_ACCESS_TOKEN && env.IG_USER_ID) await checkToken(env, at);
          await analytics.collect(env, { at }).catch(() => {});
        }
      } catch (e) {
        await log(env, 'error', 'cron', null, `Cron tick failed: ${e.message}`, null, at);
      }
    })());
  },
};

async function route(request, env, ctx, path, url, at) {
  const method = request.method;
  const body = method === 'POST' || method === 'PUT'
    ? await request.json().catch(() => ({}))
    : {};
  const policy = await getPolicy(env);

  // ── Events ────────────────────────────────────────────────────────────────
  if (path === '/events/ingest' && method === 'POST') {
    if (!Array.isArray(body.events)) return json({ error: 'events[] required' }, 400);
    const res = await ingestEvents(env, body.events, { at, source: body.source || 'events-data.js' });
    const oppRes = await opps.refreshOpportunities(env, policy, { at });
    return json({ ok: true, events: res, opportunities: oppRes });
  }

  if (path === '/events' && method === 'GET') {
    const from = url.searchParams.get('from') || isoDate(at);
    const rows = await env.DB.prepare(
      `SELECT * FROM events WHERE COALESCE(end_date, event_date) >= ? ORDER BY event_date LIMIT 300`
    ).bind(from).all();
    return json({ ok: true, events: rows.results || [] });
  }

  if (path === '/events/unpromoted' && method === 'GET') {
    return json({ ok: true, events: await opps.unpromotedEvents(env, { at }) });
  }

  // ── Opportunities ─────────────────────────────────────────────────────────
  if (path === '/opportunities/refresh' && method === 'POST') {
    return json({ ok: true, ...(await opps.refreshOpportunities(env, policy, { at })) });
  }

  if (path === '/opportunities' && method === 'GET') {
    const eventId = url.searchParams.get('event_id');
    if (eventId) return json({ ok: true, opportunities: await opps.ladderForEvent(env, eventId) });
    const rows = await env.DB.prepare(
      `SELECT o.*, e.title, e.event_date, e.city, e.state FROM opportunities o
         JOIN events e ON e.id = o.event_id ORDER BY e.event_date LIMIT 400`
    ).all();
    return json({ ok: true, opportunities: rows.results || [] });
  }

  /**
   * What does the local renderer need to build right now?
   *
   * The worker decides *what* is worth making; the local agent decides nothing
   * and only renders. That split is why a machine being off delays content
   * instead of losing it.
   */
  if (path === '/opportunities/due' && method === 'GET') {
    const due = await opps.dueOpportunities(env, policy, { at });
    const out = [];
    for (const o of due) {
      const ev = await env.DB.prepare('SELECT * FROM events WHERE id = ?').bind(o.event_id).first();
      out.push({ opportunity: o, event: ev });
    }
    return json({ ok: true, due: out, policy: { hashtags: policy.hashtags, services: policy.services } });
  }

  // ── Media ─────────────────────────────────────────────────────────────────
  if (path === '/media/upload' && method === 'POST') {
    const bytes = base64ToBytes(body.data_b64 || '');
    if (!bytes.byteLength) return json({ error: 'data_b64 required' }, 400);
    const media = await mediaStore.storeMedia(env, bytes, {
      kind: body.kind || 'image',
      contentType: body.content_type || 'image/jpeg',
      width: body.width ?? null,
      height: body.height ?? null,
      template: body.template ?? null,
      sourceKind: body.source_kind || 'generated',
      sourceUrl: body.source_url ?? null,
      sourceDomain: body.source_domain ?? null,
      acquisition: body.acquisition || 'rendered',
      originalName: body.original_name ?? null,
      retrievedAt: body.retrieved_at ?? null,
      provenance: body.provenance ?? null,
      at,
    });
    return json({ ok: true, media: { ...media, url: mediaStore.mediaUrl(env, media) } });
  }

  /**
   * Fetch a first-party flyer.
   *
   * The URL must be supplied by the caller and must come from the event's own
   * page or the organizer's site — this endpoint does not search for images, and
   * there is deliberately no path here that reaches an image search engine.
   */
  if (path === '/media/fetch-flyer' && method === 'POST') {
    if (!body.url) return json({ error: 'url required' }, 400);
    const cand = await mediaStore.fetchCandidate(env, body.url, { referer: body.referer || null, at });
    const media = await mediaStore.storeMedia(env, cand.bytes, {
      kind: 'image',
      contentType: cand.contentType === 'image/png' ? 'image/png' : 'image/jpeg',
      sourceKind: 'organizer-flyer',
      sourceUrl: cand.sourceUrl,
      sourceDomain: cand.sourceDomain,
      acquisition: body.acquisition || 'event-page',
      originalName: cand.originalName,
      retrievedAt: cand.retrievedAt,
      provenance: { requested: body.url, event_id: body.event_id || null, method: body.acquisition },
      at,
    });
    if (body.event_id) {
      await env.DB.prepare('UPDATE events SET flyer_url=?, updated_at=? WHERE id=?')
        .bind(cand.sourceUrl, at, body.event_id).run();
    }
    await log(env, 'info', 'media', body.event_id || media.id,
      `Official flyer found: ${cand.sourceUrl}`, { domain: cand.sourceDomain }, at);
    return json({ ok: true, media: { ...media, url: mediaStore.mediaUrl(env, media) }, source: cand.sourceUrl });
  }

  if (path === '/media' && method === 'GET') {
    const id = url.searchParams.get('id');
    const m = await mediaStore.getMedia(env, id);
    if (!m) return json({ error: 'not found' }, 404);
    return json({ ok: true, media: { ...m, url: mediaStore.mediaUrl(env, m) } });
  }

  // ── Video registry ────────────────────────────────────────────────────────
  if (path === '/video/register' && method === 'POST') {
    const res = await video.registerVideo(env, body.probe || body, { at, source: body.source || 'local-scan' });
    return json({ ok: true, ...res });
  }

  if (path === '/video/register-batch' && method === 'POST') {
    const out = [];
    for (const probe of body.videos || []) {
      out.push({ id: probe.id, ...(await video.registerVideo(env, probe, { at, source: body.source || 'local-scan' })) });
    }
    return json({ ok: true, results: out });
  }

  if (path === '/video' && method === 'GET') {
    const list = await video.listVideos(env, { state: url.searchParams.get('state') });
    return json({
      ok: true,
      videos: list.map((v) => ({ ...v, compatibility: video.compatibility(v) })),
    });
  }

  if (path === '/video/detail' && method === 'GET') {
    const v = await video.getVideo(env, url.searchParams.get('id'));
    if (!v) return json({ error: 'not found' }, 404);
    return json({
      ok: true, video: v,
      compatibility: video.compatibility(v),
      history: await video.videoHistory(env, v.id),
    });
  }

  if (path === '/video/approve' && method === 'POST') {
    const res = await video.approve(env, body.id, {
      by: body.by, source: body.source || 'console', note: body.note || null,
      expect_sha256: body.expect_sha256 || null, at,
    });
    return json({ ok: true, ...res });
  }

  if (path === '/video/reject' && method === 'POST') {
    return json({ ok: true, ...(await video.reject(env, body.id, { by: body.by, reason: body.reason, at })) });
  }

  if (path === '/video/revoke' && method === 'POST') {
    return json({ ok: true, ...(await video.revoke(env, body.id, { by: body.by, reason: body.reason, at })) });
  }

  /**
   * Attach the deliverable bytes to an approved video.
   *
   * Refuses unless the upload hashes to exactly what was approved — otherwise a
   * different cut could be delivered under an approved row, which is the whole
   * attack this system is built to prevent.
   */
  if (path === '/video/attach-media' && method === 'POST') {
    const v = await video.assertPublishable(env, body.id);
    const m = await mediaStore.getMedia(env, body.media_id);
    if (!m) return json({ error: 'media not found' }, 404);
    if (m.sha256 !== v.approved_sha256) {
      return json({
        error: 'uploaded video does not match the approved file',
        approved_sha256: v.approved_sha256, uploaded_sha256: m.sha256,
      }, 409);
    }
    await env.DB.prepare('UPDATE video_assets SET media_id=?, updated_at=? WHERE id=?')
      .bind(m.id, at, v.id).run();
    await video.advance(env, v.id, 'READY_FOR_INSTAGRAM', { source: 'local-agent', at }).catch(() => {});
    return json({ ok: true });
  }

  // ── Content items ─────────────────────────────────────────────────────────
  if (path === '/items/event' && method === 'POST') {
    const id = await items.createEventItem(env, {
      eventId: body.event_id, opportunityId: body.opportunity_id, kind: body.kind,
      caption: body.caption, hashtags: body.hashtags, mediaId: body.media_id,
      surface: body.surface || 'feed', warnings: body.warnings || [], at,
    });
    if (body.opportunity_id) await opps.markDrafted(env, body.opportunity_id, id, at);

    // Auto-approve and auto-schedule are policy, and both ship off.
    const auto = policy.automation.event_graphic;
    if (auto.auto_approve) {
      await items.approveItem(env, id, { by: 'policy:auto_approve', at });
      if (auto.auto_schedule) await autoSchedule(env, policy, id, body.target_at || at, at);
    }
    return json({ ok: true, id, auto_approved: Boolean(auto.auto_approve) });
  }

  if (path === '/items/reel' && method === 'POST') {
    // Throws NotApproved -> 409 if the video is not approved. This is the gate.
    const id = await items.createReelItem(env, {
      videoId: body.video_id, caption: body.caption,
      hashtags: body.hashtags, coverMediaId: body.cover_media_id || null, at,
    });
    return json({ ok: true, id });
  }

  if (path === '/items' && method === 'GET') {
    const list = await items.listItems(env, { status: url.searchParams.get('status') });
    return json({ ok: true, items: await decorate(env, list) });
  }

  if (path === '/items/detail' && method === 'GET') {
    const item = await items.getItem(env, url.searchParams.get('id'));
    if (!item) return json({ error: 'not found' }, 404);
    const [one] = await decorate(env, [item]);
    let preview = null;
    try {
      preview = await pub.buildPayload(env, item);
    } catch (e) {
      preview = { error: e.message, code: e.code || null };
    }
    const pubs = await env.DB.prepare(
      'SELECT * FROM publications WHERE item_id = ? ORDER BY at DESC LIMIT 40'
    ).bind(item.id).all();
    return json({ ok: true, item: one, preview, publications: pubs.results || [] });
  }

  if (path === '/items/approve' && method === 'POST') {
    await items.approveItem(env, body.id, { by: body.by || 'console', at });
    if (body.schedule_at || body.schedule) {
      const desired = body.schedule_at || at + 3600e3;
      const slot = await autoSchedule(env, policy, body.id, desired, at);
      return json({ ok: true, scheduled: slot });
    }
    return json({ ok: true });
  }

  if (path === '/items/schedule' && method === 'POST') {
    const desired = body.at || easternToUtc(body.date, body.time || '18:30');
    if (body.force) {
      await items.scheduleItem(env, body.id, desired, { by: body.by || 'console', at });
      return json({ ok: true, at: desired, forced: true });
    }
    const slot = await autoSchedule(env, policy, body.id, desired, at);
    return json({ ok: true, ...slot });
  }

  if (path === '/items/unschedule' && method === 'POST') {
    return json({ ok: true, ...(await items.unschedule(env, body.id, { at })) });
  }

  if (path === '/items/caption' && method === 'POST') {
    return json({ ok: true, ...(await items.editCaption(env, body.id, { caption: body.caption, hashtags: body.hashtags || null, at })) });
  }

  if (path === '/items/media' && method === 'POST') {
    return json({ ok: true, ...(await items.attachMedia(env, body.id, body.media_id, { at })) });
  }

  if (path === '/items/reject' && method === 'POST') {
    return json({ ok: true, ...(await items.rejectItem(env, body.id, { by: body.by, reason: body.reason, at })) });
  }

  if (path === '/items/archive' && method === 'POST') {
    return json({ ok: true, ...(await items.archiveItem(env, body.id, { at })) });
  }

  /**
   * Post now.
   *
   * Still goes through the full publisher — every check, the lease, the
   * container reuse. "Now" only changes the scheduled time.
   */
  if (path === '/items/publish-now' && method === 'POST') {
    const item = await items.getItem(env, body.id);
    if (!item) return json({ error: 'not found' }, 404);
    if (item.status === 'publishing') {
      // The scheduler is mid-flight on this exact item. The old code fell back
      // to an unconditional UPDATE that reset status to 'scheduled', stomping a
      // live publish's state while its lease was still held — a confusing
      // half-state for no benefit. Refusing is correct: it is already going out.
      return json({
        error: 'this post is being published right now by the scheduler — wait for it to finish',
        code: 'in_flight',
      }, 409);
    }
    if (!['approved', 'scheduled', 'failed'].includes(item.status)) {
      return json({ error: `item is ${item.status}` }, 409);
    }
    // Conditional: only moves the item if it is still in a state we may move.
    // If the scheduler claimed it between the check above and here, zero rows
    // change and publishItem's own claim() will decline, which is the outcome
    // we want.
    await env.DB.prepare(
      `UPDATE content_items SET status='scheduled', scheduled_for=?, next_retry_at=NULL, updated_at=?
        WHERE id=? AND status IN ('approved','scheduled','failed')`
    ).bind(at - 1000, at, body.id).run();
    const res = await pub.publishItem(env, body.id, policy, { at, force: Boolean(body.force_live) });
    return json({ ok: res.ok, ...res });
  }

  // ── Scheduler + dry run ───────────────────────────────────────────────────
  if (path === '/scheduler/tick' && method === 'POST') {
    await opps.refreshOpportunities(env, policy, { at });
    await items.revalidate(env, { at });
    await sched.reapStaleLeases(env, { at });
    const due = await sched.dueItems(env, { at, limit: body.limit || 5 });
    const results = [];
    for (const item of due) {
      results.push({ id: item.id, ...(await pub.publishItem(env, item.id, policy, { at })) });
    }
    return json({ ok: true, mode: effectiveMode(env, policy), processed: results });
  }

  if (path === '/dry-run' && method === 'GET') {
    return json({ ok: true, ...(await pub.dryRunReport(env, policy, { at })) });
  }

  if (path === '/queue' && method === 'GET') {
    return json({ ok: true, ...(await queueSummary(env, policy, at)) });
  }

  // ── Policy ────────────────────────────────────────────────────────────────
  if (path === '/policy' && method === 'GET') {
    return json({ ok: true, policy, defaults: DEFAULT_POLICY, effective_mode: effectiveMode(env, policy) });
  }

  if (path === '/policy' && method === 'POST') {
    const next = await setPolicy(env, body.patch || body, at);
    await log(env, 'warn', 'policy', null,
      `Policy changed by ${body.by || 'console'}`, { patch: body.patch || body }, at);
    return json({ ok: true, policy: next, effective_mode: effectiveMode(env, next) });
  }

  // ── Instagram account / token ─────────────────────────────────────────────
  if (path === '/ig/account' && method === 'GET') {
    const acct = await ig.account(env);
    const limit = await ig.publishingLimit(env).catch(() => null);
    return json({ ok: true, account: acct, publishing_limit: limit });
  }

  if (path === '/ig/check' && method === 'POST') {
    return json({ ok: true, ...(await checkToken(env, at)) });
  }

  if (path === '/ig/refresh-token' && method === 'POST') {
    const r = await ig.refreshToken(env);
    // The new token is returned once, for a human to store as a secret. Writing
    // it into the database would put a live publishing credential in a row that
    // every admin read returns.
    return json({
      ok: true,
      expires_in_days: Math.round((r.expiresIn || 0) / 86400),
      token_tail: r.token.slice(-6),
      note: 'Store this with: wrangler secret put IG_ACCESS_TOKEN — it is not saved here.',
      token: r.token,
    });
  }

  // ── Analytics + activity ──────────────────────────────────────────────────
  if (path === '/analytics/collect' && method === 'POST') {
    return json({ ok: true, ...(await analytics.collect(env, { at })) });
  }

  if (path === '/analytics' && method === 'GET') {
    return json({ ok: true, ...(await analytics.summary(env)) });
  }

  if (path === '/activity' && method === 'GET') {
    return json({
      ok: true,
      activity: await recent(env, {
        limit: Number(url.searchParams.get('limit') || 150),
        scope: url.searchParams.get('scope'),
        subject: url.searchParams.get('subject'),
      }),
    });
  }

  if (path === '/history' && method === 'GET') {
    const rows = await env.DB.prepare(
      `SELECT ci.*, e.title AS event_title, e.event_date FROM content_items ci
         LEFT JOIN events e ON e.id = ci.event_id
        WHERE ci.status IN ('published','failed') ORDER BY COALESCE(ci.published_at, ci.updated_at) DESC LIMIT 200`
    ).all();
    return json({ ok: true, history: rows.results || [] });
  }

  return json({ error: 'not found', path }, 404);
}

/** Apply the spacing rules, then commit the slot. */
async function autoSchedule(env, policy, itemId, desired, at) {
  const item = await items.getItem(env, itemId);
  const slot = await sched.proposeSlot(env, policy, {
    desired, type: item.type, eventId: item.event_id, ignoreItemId: itemId, now: at,
  });
  await items.scheduleItem(env, itemId, slot.at, { by: 'scheduler', at });
  if (slot.moved) {
    await log(env, 'info', 'scheduler', itemId,
      `Moved to ${utcToEastern(slot.at).label} — ${slot.reason}`, null, at);
  }
  return slot;
}

/** Join the rows the console needs so it makes one request, not five. */
async function decorate(env, list) {
  const out = [];
  for (const item of list) {
    const media = item.media_id ? await mediaStore.getMedia(env, item.media_id) : null;
    const ev = item.event_id
      ? await env.DB.prepare('SELECT title, event_date, venue, city, state, status FROM events WHERE id=?')
        .bind(item.event_id).first()
      : null;
    const vid = item.video_id
      ? await env.DB.prepare('SELECT title, state, approved_by, approved_at, approval_source, duration_s FROM video_assets WHERE id=?')
        .bind(item.video_id).first()
      : null;
    out.push({
      ...item,
      hashtags: safeParse(item.hashtags, []),
      warnings: safeParse(item.warnings, []),
      media_url: media ? mediaStore.mediaUrl(env, media) : null,
      media: media ? { width: media.width, height: media.height, kind: media.kind, source_kind: media.source_kind } : null,
      event: ev, video: vid,
      scheduled_local: item.scheduled_for ? utcToEastern(item.scheduled_for).label : null,
      published_local: item.published_at ? utcToEastern(item.published_at).label : null,
    });
  }
  return out;
}

function safeParse(s, fallback) {
  try { return JSON.parse(s || ''); } catch { return fallback; }
}

async function queueSummary(env, policy, at) {
  const counts = await env.DB.prepare(
    'SELECT status, COUNT(*) AS n FROM content_items GROUP BY status'
  ).all();
  const byStatus = Object.fromEntries((counts.results || []).map((r) => [r.status, r.n]));
  const vcounts = await env.DB.prepare(
    'SELECT state, COUNT(*) AS n FROM video_assets GROUP BY state'
  ).all();
  const next = await env.DB.prepare(
    `SELECT id, title, type, scheduled_for FROM content_items
      WHERE status='scheduled' ORDER BY scheduled_for LIMIT 5`
  ).all();
  const health = await env.DB.prepare("SELECT v FROM meta WHERE k='token_health'").first();
  return {
    mode: effectiveMode(env, policy),
    items: byStatus,
    videos: Object.fromEntries((vcounts.results || []).map((r) => [r.state, r.n])),
    unpromoted: (await opps.unpromotedEvents(env, { at })).length,
    next_up: (next.results || []).map((r) => ({ ...r, when: utcToEastern(r.scheduled_for).label })),
    token_health: health ? JSON.parse(health.v) : { ok: null },
  };
}

async function checkToken(env, at) {
  try {
    const acct = await ig.account(env);
    const limit = await ig.publishingLimit(env).catch(() => null);
    const v = { ok: true, at, username: acct.username, id: acct.id, limit };
    await env.DB.prepare("INSERT OR REPLACE INTO meta (k,v) VALUES ('token_health', ?)")
      .bind(JSON.stringify(v)).run();
    return v;
  } catch (e) {
    const v = { ok: false, at, error: String(e.message || e), kind: e.kind || 'unknown' };
    await env.DB.prepare("INSERT OR REPLACE INTO meta (k,v) VALUES ('token_health', ?)")
      .bind(JSON.stringify(v)).run();
    await log(env, 'error', 'instagram', null, `Token check failed: ${v.error}`, null, at);
    return v;
  }
}

function base64ToBytes(b64) {
  const bin = atob(String(b64 || ''));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
