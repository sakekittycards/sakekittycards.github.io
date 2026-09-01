/**
 * Content items — the unit that gets approved, scheduled and published.
 *
 * One item is one Instagram post. It carries the caption, points at its media,
 * and remembers which event or video it came from.
 *
 * The field doing the quiet work is `subject_fingerprint`: a snapshot of the
 * underlying truth at the moment a human approved. The publisher recomputes it
 * and refuses to send if it moved, which is how "the venue changed after Nick
 * approved the graphic" becomes a re-review instead of a wrong post.
 */
import { stableId, nowMs } from './util.js';
import { eventFingerprint } from './events.js';
import { assertPublishable } from './video.js';
import { log } from './log.js';

export const STATUSES = [
  'draft', 'needs_review', 'approved', 'scheduled',
  'publishing', 'published', 'failed', 'rejected', 'archived',
];

/** What the item's subject looks like right now. */
export async function computeSubjectFingerprint(env, item) {
  if (item.type === 'event') {
    const ev = await env.DB.prepare('SELECT * FROM events WHERE id = ?').bind(item.event_id).first();
    if (!ev) return 'missing';
    return ev.fingerprint;
  }
  if (item.type === 'reel') {
    const v = await env.DB.prepare('SELECT sha256, state FROM video_assets WHERE id = ?')
      .bind(item.video_id).first();
    if (!v) return 'missing';
    // The video's own bytes are the subject. State is deliberately excluded —
    // state changes are handled by the approval gate, and folding them in here
    // would flag an item every time it moved from APPROVED to SCHEDULED.
    return v.sha256;
  }
  return 'n/a';
}

export async function createEventItem(env, {
  eventId, opportunityId, kind, caption, hashtags, mediaId,
  surface = 'feed', warnings = [], at = nowMs(),
}) {
  const id = await stableId('itm', opportunityId || `${eventId}:${kind}`);
  const ev = await env.DB.prepare('SELECT * FROM events WHERE id = ?').bind(eventId).first();
  if (!ev) throw new Error(`createEventItem: no event ${eventId}`);
  if (ev.status !== 'scheduled') throw new Error(`createEventItem: event ${eventId} is ${ev.status}`);

  const fp = await eventFingerprint(ev);
  await env.DB.prepare(
    `INSERT INTO content_items (id, type, surface, status, event_id, opportunity_id, title,
       caption, hashtags, media_id, warnings, subject_fingerprint, created_at, updated_at)
     VALUES (?,?,?,'draft',?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET caption=excluded.caption, hashtags=excluded.hashtags,
       media_id=excluded.media_id, warnings=excluded.warnings,
       subject_fingerprint=excluded.subject_fingerprint, updated_at=excluded.updated_at
     WHERE content_items.status IN ('draft','needs_review')`
  ).bind(
    id, 'event', surface, eventId, opportunityId, `${ev.title} — ${kind}`,
    caption, JSON.stringify(hashtags || []), mediaId, JSON.stringify(warnings), fp, at, at
  ).run();

  await log(env, 'info', 'items', id,
    `Draft generated: ${ev.title} (${kind})`, { opportunity: opportunityId }, at);
  return id;
}

/**
 * Create a reel item.
 *
 * The FIRST of the two enforcement points for the video invariant. There is no
 * other code path that produces a `type='reel'` row, so an unapproved video
 * cannot become a content item at all — never mind reach the publisher.
 */
export async function createReelItem(env, { videoId, caption, hashtags, coverMediaId = null, at = nowMs() }) {
  const v = await assertPublishable(env, videoId);   // throws NotApproved

  const id = await stableId('itm', 'reel', videoId, v.approved_sha256);
  await env.DB.prepare(
    `INSERT INTO content_items (id, type, surface, status, video_id, title, caption, hashtags,
       media_id, cover_media_id, subject_fingerprint, created_at, updated_at)
     VALUES (?,?,?,'draft',?,?,?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET caption=excluded.caption, hashtags=excluded.hashtags,
       cover_media_id=excluded.cover_media_id, updated_at=excluded.updated_at
     WHERE content_items.status IN ('draft','needs_review')`
  ).bind(
    id, 'reel', 'reel', videoId, v.title, caption, JSON.stringify(hashtags || []),
    v.media_id, coverMediaId, v.sha256, at, at
  ).run();

  await log(env, 'info', 'items', id,
    `Reel draft created from approved video: ${v.title}`,
    { video: videoId, approved_by: v.approved_by, approved_at: v.approved_at }, at);
  return id;
}

export async function approveItem(env, itemId, { by, at = nowMs() }) {
  if (!by) throw new Error('approveItem: approved_by is required');
  const item = await getItem(env, itemId);
  if (!item) throw new Error(`approveItem: no item ${itemId}`);
  if (!['draft', 'needs_review'].includes(item.status)) {
    throw new Error(`approveItem: item is ${item.status}`);
  }
  if (!item.media_id && item.type === 'event') {
    throw new Error('approveItem: no graphic attached yet');
  }
  // A reel cannot be approved for social unless the video is still approved —
  // the second gate, independent of the first.
  if (item.type === 'reel') await assertPublishable(env, item.video_id);

  const fp = await computeSubjectFingerprint(env, item);
  await env.DB.prepare(
    `UPDATE content_items SET status='approved', approved_at=?, approved_by=?,
       subject_fingerprint=?, failure_reason=NULL, updated_at=? WHERE id=?`
  ).bind(at, by, fp, at, itemId).run();
  await log(env, 'info', 'items', itemId, `Approved by ${by}: ${item.title}`, null, at);
  return { ok: true };
}

export async function scheduleItem(env, itemId, whenMs, { by = 'console', at = nowMs() } = {}) {
  const item = await getItem(env, itemId);
  if (!item) throw new Error(`scheduleItem: no item ${itemId}`);
  if (item.status !== 'approved' && item.status !== 'scheduled') {
    throw new Error(`scheduleItem: item is ${item.status}, must be approved first`);
  }
  if (item.type === 'reel') await assertPublishable(env, item.video_id);

  await env.DB.prepare(
    `UPDATE content_items SET status='scheduled', scheduled_for=?, next_retry_at=NULL,
       failure_reason=NULL, updated_at=? WHERE id=?`
  ).bind(whenMs, at, itemId).run();
  if (item.opportunity_id) {
    await env.DB.prepare("UPDATE opportunities SET status='scheduled', updated_at=? WHERE id=?")
      .bind(at, item.opportunity_id).run();
  }
  await log(env, 'info', 'items', itemId,
    `Scheduled by ${by}: ${item.title}`, { scheduled_for: whenMs }, at);
  return { ok: true };
}

export async function unschedule(env, itemId, { at = nowMs() } = {}) {
  await env.DB.prepare(
    `UPDATE content_items SET status='approved', scheduled_for=NULL, lease_until=NULL,
       lease_token=NULL, updated_at=? WHERE id=? AND status='scheduled'`
  ).bind(at, itemId).run();
  return { ok: true };
}

export async function rejectItem(env, itemId, { by, reason = null, at = nowMs() }) {
  const item = await getItem(env, itemId);
  if (!item) throw new Error(`rejectItem: no item ${itemId}`);
  await env.DB.prepare(
    "UPDATE content_items SET status='rejected', failure_reason=?, scheduled_for=NULL, updated_at=? WHERE id=?"
  ).bind(reason, at, itemId).run();
  if (item.opportunity_id) {
    await env.DB.prepare("UPDATE opportunities SET status='skipped', reason=?, updated_at=? WHERE id=?")
      .bind(reason || 'rejected in console', at, item.opportunity_id).run();
  }
  await log(env, 'warn', 'items', itemId, `Rejected by ${by || 'console'}: ${item.title}`, { reason }, at);
  return { ok: true };
}

export async function archiveItem(env, itemId, { at = nowMs() } = {}) {
  await env.DB.prepare("UPDATE content_items SET status='archived', updated_at=? WHERE id=?")
    .bind(at, itemId).run();
  return { ok: true };
}

/**
 * Editing a caption after approval un-approves the item.
 *
 * Approval means "I read this and it can go out". Changing the words after the
 * fact would make that signature cover text nobody read.
 */
export async function editCaption(env, itemId, { caption, hashtags = null, at = nowMs() }) {
  const item = await getItem(env, itemId);
  if (!item) throw new Error(`editCaption: no item ${itemId}`);
  if (['published', 'publishing'].includes(item.status)) {
    throw new Error(`editCaption: item is ${item.status}`);
  }
  const reset = item.status === 'approved' || item.status === 'scheduled';
  await env.DB.prepare(
    `UPDATE content_items SET caption=?, hashtags=COALESCE(?, hashtags),
       status=CASE WHEN ? THEN 'needs_review' ELSE status END,
       approved_at=CASE WHEN ? THEN NULL ELSE approved_at END,
       approved_by=CASE WHEN ? THEN NULL ELSE approved_by END,
       scheduled_for=CASE WHEN ? THEN NULL ELSE scheduled_for END,
       updated_at=? WHERE id=?`
  ).bind(caption, hashtags ? JSON.stringify(hashtags) : null,
    reset ? 1 : 0, reset ? 1 : 0, reset ? 1 : 0, reset ? 1 : 0, at, itemId).run();
  if (reset) {
    await log(env, 'info', 'items', itemId,
      'Caption edited after approval — back to review', null, at);
  }
  return { ok: true, reset };
}

export async function attachMedia(env, itemId, mediaId, { at = nowMs() } = {}) {
  const item = await getItem(env, itemId);
  if (!item) throw new Error(`attachMedia: no item ${itemId}`);
  const reset = ['approved', 'scheduled'].includes(item.status);
  await env.DB.prepare(
    `UPDATE content_items SET media_id=?,
       status=CASE WHEN ? THEN 'needs_review' ELSE status END,
       approved_at=CASE WHEN ? THEN NULL ELSE approved_at END,
       scheduled_for=CASE WHEN ? THEN NULL ELSE scheduled_for END,
       updated_at=? WHERE id=?`
  ).bind(mediaId, reset ? 1 : 0, reset ? 1 : 0, reset ? 1 : 0, at, itemId).run();
  if (reset) {
    await log(env, 'info', 'items', itemId, 'Graphic replaced after approval — back to review', null, at);
  }
  return { ok: true, reset };
}

/**
 * Flag every approved-or-scheduled item whose subject moved.
 *
 * Runs on the cron and again immediately before publishing. Doing it on the cron
 * means the console shows the problem hours early instead of at post time.
 */
export async function revalidate(env, { at = nowMs() } = {}) {
  const rows = await env.DB.prepare(
    "SELECT * FROM content_items WHERE status IN ('approved','scheduled')"
  ).all();
  const flagged = [];
  for (const item of rows.results || []) {
    const fp = await computeSubjectFingerprint(env, item);
    if (fp === item.subject_fingerprint) continue;
    const why = fp === 'missing'
      ? 'the source event or video no longer exists'
      : 'the event details changed after approval';
    await env.DB.prepare(
      `UPDATE content_items SET status='needs_review', failure_reason=?, scheduled_for=NULL,
         updated_at=? WHERE id=?`
    ).bind(why, at, item.id).run();
    flagged.push({ id: item.id, why });
    await log(env, 'warn', 'items', item.id,
      `Pulled back for re-review: ${why} — ${item.title}`, null, at);
  }
  return flagged;
}

export async function getItem(env, id) {
  return env.DB.prepare('SELECT * FROM content_items WHERE id = ?').bind(id).first();
}

export async function listItems(env, { status = null, limit = 200 } = {}) {
  const sql = status
    ? `SELECT * FROM content_items WHERE status = ? ORDER BY COALESCE(scheduled_for, updated_at) DESC LIMIT ?`
    : `SELECT * FROM content_items ORDER BY COALESCE(scheduled_for, updated_at) DESC LIMIT ?`;
  const binds = status ? [status, limit] : [limit];
  const rows = await env.DB.prepare(sql).bind(...binds).all();
  return rows.results || [];
}

/** The caption exactly as it will be sent, hashtags folded in. */
export function renderCaption(item) {
  let tags = [];
  try { tags = JSON.parse(item.hashtags || '[]'); } catch { tags = []; }
  const body = String(item.caption || '').trim();
  if (!tags.length) return body;
  return `${body}\n\n${tags.join(' ')}`;
}
