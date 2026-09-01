/**
 * The video approval registry — and the one invariant this whole system exists
 * to guarantee:
 *
 *     AN UNAPPROVED VIDEO CAN NEVER REACH THE INSTAGRAM PUBLISH FUNCTION.
 *
 * ## Why this is a module and not a UI rule
 *
 * Today, approval of a Sake Kitty short is Nick watching it and saying "looks
 * good to push", after which a human writes a line of prose in a markdown
 * ledger and the file sits in a Dropbox folder. On 2026-08-31 the `_staging`
 * step was removed and builds started landing directly in `SHORT FORM FINAL`,
 * so the delivery folder now contains approved shorts, unreviewed shorts and
 * killed shorts side by side. A folder path, a filename, an export location and
 * a successful render are therefore all worthless as evidence, and any pipeline
 * that treats them as approval will publish something Nick rejected.
 *
 * ## How the guarantee is actually made
 *
 * Approval is a row transition plus a content hash, and both are checked twice:
 *
 *   1. `assertPublishable()` is the ONLY way a reel item is created, and the
 *      ONLY way one is published. Both call sites go through it.
 *   2. It requires `state ∈ PUBLISHABLE_STATES` — every one of which is reached
 *      only via `approve()` — AND `approved_sha256 === sha256`.
 *
 * That second condition is what makes the guarantee survive the realistic
 * failure: a short gets approved, then re-rendered in place with a different cut
 * under the same filename. The bytes change, the stored hash does not, and the
 * mismatch drops the asset back to REVIEW instead of publishing the new edit on
 * the old approval.
 *
 * There is no policy flag that auto-approves video. There is no "trusted
 * folder". There is no admin endpoint that sets `state` directly — `setState()`
 * is not exported, and every caller goes through a named transition that records
 * who did it.
 */
import { nowMs } from './util.js';
import { log } from './log.js';

/**
 * The lifecycle. Order matters: everything at or past APPROVED is downstream of
 * a human decision, and everything before it is not.
 */
export const STATES = [
  'RAW',
  'PROCESSING',
  'REVIEW',
  'APPROVED',
  'READY_FOR_INSTAGRAM',
  'SCHEDULED',
  'PUBLISHED',
  'REJECTED',
];

/** The only states from which Instagram ingestion is permitted. */
export const PUBLISHABLE_STATES = new Set([
  'APPROVED',
  'READY_FOR_INSTAGRAM',
  'SCHEDULED',
  'PUBLISHED',
]);

/** Transitions a machine may make on its own — note APPROVED is absent. */
const MACHINE_TRANSITIONS = {
  RAW: ['PROCESSING', 'REVIEW'],
  PROCESSING: ['REVIEW', 'RAW'],
  APPROVED: ['READY_FOR_INSTAGRAM'],
  READY_FOR_INSTAGRAM: ['SCHEDULED', 'APPROVED'],
  SCHEDULED: ['PUBLISHED', 'READY_FOR_INSTAGRAM'],
};

export class NotApproved extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'NotApproved';
    this.code = code;
  }
}

/**
 * THE GATE. Returns the video row, or throws.
 *
 * Call this immediately before doing anything that could put pixels in front of
 * the public. It deliberately takes `env` and an id rather than a row, so a
 * caller cannot hand it a stale object it fetched before an intervening
 * revocation.
 */
export async function assertPublishable(env, videoId) {
  if (!videoId) throw new NotApproved('no video asset referenced', 'missing');

  const v = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
  if (!v) throw new NotApproved(`video asset ${videoId} does not exist`, 'missing');

  if (!PUBLISHABLE_STATES.has(v.state)) {
    throw new NotApproved(
      `video "${v.title}" is ${v.state}, not approved — Instagram ingestion refused`,
      'unapproved'
    );
  }
  if (v.revoked_at) {
    throw new NotApproved(`approval for "${v.title}" was revoked: ${v.revoked_reason || 'no reason given'}`, 'revoked');
  }
  if (!v.approved_at || !v.approved_by) {
    // A row in a publishable state with no approval record means someone wrote
    // state directly. Refuse, loudly — this should be impossible.
    throw new NotApproved(
      `video "${v.title}" is ${v.state} but carries no approval record — refusing`,
      'no_record'
    );
  }
  if (!v.approved_sha256 || v.approved_sha256 !== v.sha256) {
    throw new NotApproved(
      `video "${v.title}" changed on disk after it was approved ` +
      `(approved ${short(v.approved_sha256)}, now ${short(v.sha256)}) — needs re-review`,
      'content_changed'
    );
  }
  return v;
}

function short(h) {
  return h ? String(h).slice(0, 12) : 'none';
}

/**
 * Register or refresh a video asset from a local probe.
 *
 * Import is always safe: a newly seen file lands in REVIEW, never APPROVED, no
 * matter where it came from. If a known file's bytes moved, any approval on it
 * is dropped on the spot — that is the in-place re-render case, and catching it
 * here means the console shows it as needing review before anyone tries to post.
 */
export async function registerVideo(env, probe, { at = nowMs(), source = 'local-scan' } = {}) {
  const required = ['id', 'title', 'source_path', 'sha256'];
  for (const f of required) {
    if (!probe[f]) throw new Error(`registerVideo: missing ${f}`);
  }

  const existing = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(probe.id).first();

  if (!existing) {
    await env.DB.prepare(
      `INSERT INTO video_assets (id, title, source_path, final_path, sha256, bytes, duration_s,
         width, height, fps, vcodec, acodec, container, has_audio, state, probe, created_at, updated_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
    ).bind(
      probe.id, probe.title, probe.source_path, probe.final_path || probe.source_path,
      probe.sha256, probe.bytes ?? null, probe.duration_s ?? null, probe.width ?? null,
      probe.height ?? null, probe.fps ?? null, probe.vcodec ?? null, probe.acodec ?? null,
      probe.container ?? null, probe.has_audio === false ? 0 : 1, 'REVIEW',
      JSON.stringify(probe), at, at
    ).run();
    await recordTransition(env, probe.id, null, 'REVIEW', source, 'imported', probe.sha256, at);
    await log(env, 'info', 'video', probe.id,
      `Video found and queued for review: ${probe.title}`,
      { path: probe.source_path, duration_s: probe.duration_s }, at);
    return { created: true, invalidated: false };
  }

  if (existing.sha256 === probe.sha256) {
    await env.DB.prepare(
      `UPDATE video_assets SET title=?, final_path=?, bytes=?, duration_s=?, width=?, height=?,
         fps=?, vcodec=?, acodec=?, container=?, has_audio=?, probe=?, updated_at=? WHERE id=?`
    ).bind(
      probe.title, probe.final_path || existing.final_path, probe.bytes ?? existing.bytes,
      probe.duration_s ?? existing.duration_s, probe.width ?? existing.width,
      probe.height ?? existing.height, probe.fps ?? existing.fps, probe.vcodec ?? existing.vcodec,
      probe.acodec ?? existing.acodec, probe.container ?? existing.container,
      probe.has_audio === false ? 0 : 1, JSON.stringify(probe), at, probe.id
    ).run();
    return { created: false, invalidated: false };
  }

  // Bytes changed. Whatever was approved is not what is on disk any more.
  const wasApproved = PUBLISHABLE_STATES.has(existing.state);
  await env.DB.prepare(
    `UPDATE video_assets SET sha256=?, bytes=?, duration_s=?, width=?, height=?, fps=?,
       vcodec=?, acodec=?, container=?, has_audio=?, probe=?, state='REVIEW',
       approved_at=NULL, approved_by=NULL, approval_source=NULL, approved_sha256=NULL,
       media_id=NULL, updated_at=? WHERE id=?`
  ).bind(
    probe.sha256, probe.bytes ?? null, probe.duration_s ?? null, probe.width ?? null,
    probe.height ?? null, probe.fps ?? null, probe.vcodec ?? null, probe.acodec ?? null,
    probe.container ?? null, probe.has_audio === false ? 0 : 1, JSON.stringify(probe), at, probe.id
  ).run();
  await recordTransition(env, probe.id, existing.state, 'REVIEW', source,
    'file changed on disk — approval dropped', probe.sha256, at);
  await log(env, wasApproved ? 'warn' : 'info', 'video', probe.id,
    wasApproved
      ? `Approved video "${existing.title}" changed on disk — approval revoked, back to review`
      : `Video "${existing.title}" re-rendered — probe updated`,
    { was: short(existing.sha256), now: short(probe.sha256) }, at);

  // Any queued reel built on the old bytes must not go out.
  if (wasApproved) await quarantineItems(env, probe.id, 'source video changed after approval', at);
  return { created: false, invalidated: wasApproved };
}

/**
 * The human gate. `approved_by` and `source` are required — an approval with no
 * name on it is not auditable, and an unauditable approval is not one.
 *
 * `expect_sha256` is how the console proves it approved the thing it displayed:
 * if the file changed between the page load and the click, the approval is
 * refused rather than silently applied to different bytes.
 */
export async function approve(env, videoId, { by, source, note = null, expect_sha256 = null, at = nowMs() }) {
  if (!by || !String(by).trim()) throw new Error('approve: approved_by is required');
  if (!source || !String(source).trim()) throw new Error('approve: approval source is required');

  const v = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
  if (!v) throw new Error(`approve: no such video ${videoId}`);
  if (v.state === 'REJECTED') throw new Error('approve: video was rejected — re-import it to reconsider');
  if (expect_sha256 && expect_sha256 !== v.sha256) {
    throw new Error('approve: the file changed since this page was loaded — reload and re-check it');
  }

  await env.DB.prepare(
    `UPDATE video_assets SET state='APPROVED', approved_at=?, approved_by=?, approval_source=?,
       approval_note=?, approved_sha256=?, revoked_at=NULL, revoked_reason=NULL, updated_at=?
     WHERE id=?`
  ).bind(at, String(by).trim(), String(source).trim(), note, v.sha256, at, videoId).run();

  await recordTransition(env, videoId, v.state, 'APPROVED', source, note, v.sha256, at);
  await log(env, 'info', 'video', videoId,
    `Approved by ${by}: ${v.title}`, { source, note, sha256: short(v.sha256) }, at);
  return { ok: true };
}

export async function reject(env, videoId, { by, reason = null, at = nowMs() }) {
  const v = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
  if (!v) throw new Error(`reject: no such video ${videoId}`);
  await env.DB.prepare(
    `UPDATE video_assets SET state='REJECTED', approved_at=NULL, approved_by=NULL,
       approved_sha256=NULL, revoked_at=?, revoked_reason=?, updated_at=? WHERE id=?`
  ).bind(at, reason, at, videoId).run();
  await recordTransition(env, videoId, v.state, 'REJECTED', 'console', reason, v.sha256, at);
  await quarantineItems(env, videoId, reason || 'video rejected', at);
  await log(env, 'warn', 'video', videoId, `Rejected by ${by || 'console'}: ${v.title}`, { reason }, at);
  return { ok: true };
}

/** Pull an approval back without rejecting the video outright. */
export async function revoke(env, videoId, { by, reason, at = nowMs() }) {
  const v = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
  if (!v) throw new Error(`revoke: no such video ${videoId}`);
  await env.DB.prepare(
    `UPDATE video_assets SET state='REVIEW', approved_at=NULL, approved_by=NULL,
       approved_sha256=NULL, revoked_at=?, revoked_reason=?, updated_at=? WHERE id=?`
  ).bind(at, reason || 'revoked', at, videoId).run();
  await recordTransition(env, videoId, v.state, 'REVIEW', 'console', reason, v.sha256, at);
  await quarantineItems(env, videoId, reason || 'approval revoked', at);
  await log(env, 'warn', 'video', videoId, `Approval revoked by ${by || 'console'}: ${v.title}`, { reason }, at);
  return { ok: true };
}

/**
 * Machine-driven advance. Refuses to invent an approval: APPROVED is not a
 * reachable target here, which is why the table has no edge into it.
 */
export async function advance(env, videoId, toState, { source = 'system', note = null, at = nowMs() } = {}) {
  const v = await env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
  if (!v) throw new Error(`advance: no such video ${videoId}`);
  const allowed = MACHINE_TRANSITIONS[v.state] || [];
  if (!allowed.includes(toState)) {
    throw new NotApproved(`illegal transition ${v.state} -> ${toState}`, 'illegal_transition');
  }
  await env.DB.prepare('UPDATE video_assets SET state=?, updated_at=? WHERE id=?')
    .bind(toState, at, videoId).run();
  await recordTransition(env, videoId, v.state, toState, source, note, v.sha256, at);
  return { ok: true, state: toState };
}

async function recordTransition(env, videoId, from, to, source, note, sha, at) {
  await env.DB.prepare(
    'INSERT INTO video_events (video_id, from_state, to_state, actor, source, note, sha256, at) VALUES (?,?,?,?,?,?,?,?)'
  ).bind(videoId, from, to, source, source, note, sha, at).run();
}

/**
 * Pull any queued reel built on this video off the calendar.
 *
 * Published items are left alone — that already happened, and rewriting history
 * would make the post log lie. Everything still in flight becomes `needs_review`
 * so it surfaces in the console instead of vanishing.
 */
async function quarantineItems(env, videoId, reason, at) {
  const res = await env.DB.prepare(
    `UPDATE content_items
        SET status='needs_review', failure_reason=?, scheduled_for=NULL, updated_at=?
      WHERE video_id=? AND status IN ('draft','needs_review','approved','scheduled','failed')`
  ).bind(reason, at, videoId).run();
  const n = res.meta ? res.meta.changes : 0;
  if (n) {
    await log(env, 'warn', 'video', videoId,
      `${n} queued post(s) pulled back for review: ${reason}`, null, at);
  }
  return n;
}

export async function getVideo(env, videoId) {
  return env.DB.prepare('SELECT * FROM video_assets WHERE id = ?').bind(videoId).first();
}

export async function listVideos(env, { state = null, limit = 200 } = {}) {
  const sql = state
    ? 'SELECT * FROM video_assets WHERE state = ? ORDER BY updated_at DESC LIMIT ?'
    : 'SELECT * FROM video_assets ORDER BY updated_at DESC LIMIT ?';
  const binds = state ? [state, limit] : [limit];
  const rows = await env.DB.prepare(sql).bind(...binds).all();
  return rows.results || [];
}

export async function videoHistory(env, videoId) {
  const rows = await env.DB.prepare(
    'SELECT * FROM video_events WHERE video_id = ? ORDER BY at'
  ).bind(videoId).all();
  return rows.results || [];
}

/**
 * Platform compatibility check.
 *
 * Reports rather than repairs. An approved cut is the thing Nick signed off; if
 * making it postable would change the edit, that is a decision for him, not a
 * silent transform. Only container/codec/loudness normalisation — which does not
 * change what is on screen — is ever done automatically, and even that happens
 * in the local prep step, not here.
 *
 * Limits are Instagram's published Reels constraints as of 2026: 3s–15min,
 * 9:16 preferred (0.01:1–10:1 accepted), MP4/MOV, H.264/HEVC + AAC.
 */
export function compatibility(v) {
  const warnings = [];
  const blockers = [];

  const dur = v.duration_s;
  if (dur == null) warnings.push('duration unknown — probe the file before scheduling');
  else if (dur < 3) blockers.push(`${dur.toFixed(1)}s is under Instagram's 3s minimum for Reels`);
  else if (dur > 900) blockers.push(`${(dur / 60).toFixed(1)}min is over the 15min Reels maximum`);
  else if (dur > 90) warnings.push(`${dur.toFixed(0)}s — over 90s Reels lose the audio-page treatment`);

  if (v.width && v.height) {
    const ar = v.width / v.height;
    if (Math.abs(ar - 9 / 16) > 0.02) {
      warnings.push(`${v.width}x${v.height} is ${ar.toFixed(3)}:1, not 9:16 — Instagram will letterbox or crop`);
    }
    if (v.width < 540) warnings.push(`${v.width}px wide is below the 540px recommended minimum`);
  } else {
    warnings.push('dimensions unknown');
  }

  const vc = String(v.vcodec || '').toLowerCase();
  if (vc && !['h264', 'avc1', 'hevc', 'h265', 'hvc1'].includes(vc)) {
    blockers.push(`video codec ${vc} is not accepted — needs H.264 or HEVC`);
  }
  const ac = String(v.acodec || '').toLowerCase();
  if (v.has_audio && ac && !['aac', 'mp4a'].includes(ac)) {
    blockers.push(`audio codec ${ac} is not accepted — needs AAC`);
  }
  if (!v.has_audio) warnings.push('no audio track — Reels without audio perform poorly');

  const ct = String(v.container || '').toLowerCase();
  if (ct && !ct.includes('mp4') && !ct.includes('mov')) {
    blockers.push(`container ${ct} is not accepted — needs MP4 or MOV`);
  }
  if (v.bytes && v.bytes > 1024 * 1024 * 1024) {
    blockers.push(`${(v.bytes / 1e9).toFixed(2)}GB is over Instagram's 1GB limit`);
  }

  return { ok: blockers.length === 0, blockers, warnings };
}
