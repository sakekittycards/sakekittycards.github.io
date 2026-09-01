/**
 * Scheduling: when may this go out, and who is allowed to send it.
 *
 * Two separate jobs live here.
 *
 * `proposeSlot` answers "when should this post?" and is where the spacing rules
 * live — the ones that stop four show posts landing in one afternoon. It walks
 * forward from a desired time until it finds a slot that breaks nothing.
 *
 * `claim` answers "am I the one publishing this?" and is the reason a retry
 * cannot double-post. It is a conditional UPDATE that only one caller can win;
 * a second worker running the same tick finds zero rows changed and does
 * nothing. Cloudflare will happily run two overlapping cron invocations, and
 * "the retry published it twice" is the failure this system must never have.
 */
import { nowMs, utcToEastern, easternToUtc, isoDate } from './util.js';
import { log } from './log.js';

const HOUR = 3600e3;

/**
 * Find the first time at or after `desired` that satisfies every spacing rule.
 *
 * Returns `{ at, moved, reason }`. Deliberately never returns "no slot": pushing
 * a post later is always better than dropping it, and the console shows the
 * final time so a human can override.
 */
export async function proposeSlot(env, policy, { desired, type, eventId = null, ignoreItemId = null, now = nowMs() }) {
  const sp = policy.spacing;
  const taken = await scheduledTimeline(env, ignoreItemId);

  // `now` is passed in rather than read from the clock so that every decision in
  // one tick shares a single instant. A slot computed against a drifting clock is
  // not reproducible, and the lead-time floor silently stops applying.
  let at = Math.max(desired, now + policy.min_lead_hours * HOUR);
  let moved = false;
  let reason = null;

  for (let guard = 0; guard < 240; guard++) {
    const conflict = firstConflict(at, type, eventId, taken, sp, policy);
    if (!conflict) break;
    moved = true;
    reason = conflict.reason;
    at = conflict.retryAt;
  }

  at = shiftOutOfQuietHours(at, sp.quiet_hours_local);
  return { at, moved, reason };
}

function firstConflict(at, type, eventId, taken, sp, policy) {
  const day = utcToEastern(at).date;
  const sameDay = taken.filter((t) => utcToEastern(t.at).date === day);
  if (sameDay.length >= sp.max_per_day) {
    // Jump to the next morning rather than nudging by an hour into the same
    // full day, which would loop.
    return { reason: `${sp.max_per_day} posts already on ${day}`, retryAt: easternToUtc(nextDay(day), '10:00') };
  }

  for (const t of taken) {
    const gapH = Math.abs(at - t.at) / HOUR;

    if (gapH < sp.any_two_posts_hours) {
      return {
        reason: `within ${sp.any_two_posts_hours}h of another post`,
        retryAt: t.at + sp.any_two_posts_hours * HOUR,
      };
    }
    if (type === 'event' && t.type === 'event' && gapH < sp.two_event_posts_hours) {
      return {
        reason: `within ${sp.two_event_posts_hours}h of another event post`,
        retryAt: t.at + sp.two_event_posts_hours * HOUR,
      };
    }
    if (type === 'reel' && t.type === 'event' && gapH * 60 < sp.reel_near_event_minutes) {
      return {
        reason: `within ${sp.reel_near_event_minutes}min of an event post`,
        retryAt: t.at + sp.reel_near_event_minutes * 60e3,
      };
    }
    if (eventId && t.event_id === eventId && gapH < policy.min_gap_same_event_hours) {
      return {
        reason: `within ${policy.min_gap_same_event_hours}h of another post for the same show`,
        retryAt: t.at + policy.min_gap_same_event_hours * HOUR,
      };
    }
  }
  return null;
}

function nextDay(dateStr) {
  return isoDate(Date.parse(`${dateStr}T00:00:00Z`) + 86400e3);
}

/** Nothing publishes overnight; it reads as a bot and nobody sees it. */
function shiftOutOfQuietHours(at, [start, end]) {
  const { date, time } = utcToEastern(at);
  const hour = Number(time.slice(0, 2));
  if (start > end) {          // window wraps midnight, e.g. 23 -> 7
    if (hour >= start) return easternToUtc(nextDay(date), pad(end));
    if (hour < end) return easternToUtc(date, pad(end));
  } else if (hour >= start && hour < end) {
    return easternToUtc(date, pad(end));
  }
  return at;
}

function pad(h) {
  return `${String(h).padStart(2, '0')}:00`;
}

/** Everything already on the calendar or already out, for collision checks. */
async function scheduledTimeline(env, ignoreItemId) {
  const rows = await env.DB.prepare(
    `SELECT id, type, event_id, COALESCE(published_at, scheduled_for) AS at
       FROM content_items
      WHERE status IN ('scheduled','publishing','published')
        AND COALESCE(published_at, scheduled_for) IS NOT NULL`
  ).all();
  return (rows.results || [])
    .filter((r) => r.id !== ignoreItemId)
    .map((r) => ({ id: r.id, type: r.type, event_id: r.event_id, at: r.at }));
}

/**
 * Take an exclusive lease on an item.
 *
 * The WHERE clause carries the whole guarantee: status must still be
 * `scheduled`, and any existing lease must have expired. Two concurrent workers
 * issue the same statement; SQLite serialises them and exactly one sees
 * `changes === 1`.
 *
 * The lease is 10 minutes because a Reel container can legitimately take over a
 * minute to process, and a lease shorter than the work it protects is not a
 * lease.
 */
export async function claim(env, itemId, { at = nowMs(), leaseMs = 10 * 60e3 } = {}) {
  const token = crypto.randomUUID();
  const res = await env.DB.prepare(
    `UPDATE content_items
        SET status='publishing', lease_token=?, lease_until=?, attempts=attempts+1,
            last_attempt_at=?, updated_at=?
      WHERE id=? AND status='scheduled' AND (lease_until IS NULL OR lease_until < ?)`
  ).bind(token, at + leaseMs, at, at, itemId, at).run();
  const won = res.meta && res.meta.changes === 1;
  return won ? token : null;
}

export async function releaseLease(env, itemId, token, status, { at = nowMs(), reason = null, nextRetryAt = null } = {}) {
  await env.DB.prepare(
    `UPDATE content_items SET status=?, lease_token=NULL, lease_until=NULL,
       failure_reason=?, next_retry_at=?, updated_at=? WHERE id=? AND lease_token=?`
  ).bind(status, reason, nextRetryAt, at, itemId, token).run();
}

/**
 * Items whose time has come.
 *
 * `next_retry_at` gates the backoff: a failed item stays `scheduled` and simply
 * is not due again until its backoff expires, so a transient Instagram outage
 * does not need a separate retry queue.
 */
export async function dueItems(env, { at = nowMs(), limit = 5 } = {}) {
  const rows = await env.DB.prepare(
    `SELECT * FROM content_items
      WHERE status='scheduled' AND scheduled_for IS NOT NULL AND scheduled_for <= ?
        AND (next_retry_at IS NULL OR next_retry_at <= ?)
      ORDER BY scheduled_for LIMIT ?`
  ).bind(at, at, limit).all();
  return rows.results || [];
}

/**
 * Reclaim work abandoned mid-flight — a worker that was evicted while holding a
 * lease. Back to `scheduled`, where the normal path (including the "did this
 * actually publish?" check) picks it up again.
 */
export async function reapStaleLeases(env, { at = nowMs() } = {}) {
  const rows = await env.DB.prepare(
    "SELECT id, title, attempts FROM content_items WHERE status='publishing' AND lease_until < ?"
  ).bind(at).all();
  for (const r of rows.results || []) {
    await env.DB.prepare(
      `UPDATE content_items SET status='scheduled', lease_token=NULL, lease_until=NULL,
         next_retry_at=?, updated_at=? WHERE id=?`
    ).bind(at + backoffMs(r.attempts), at, r.id).run();
    await log(env, 'warn', 'publish', r.id,
      `Publish lease expired mid-flight — requeued: ${r.title}`, { attempts: r.attempts }, at);
  }
  return (rows.results || []).length;
}

/** Exponential backoff, 2min -> 4 -> 8 ... capped at 2h, with jitter. */
export function backoffMs(attempts) {
  const base = Math.min(2 * 60e3 * 2 ** Math.max(0, attempts - 1), 2 * HOUR);
  return Math.round(base * (0.85 + Math.random() * 0.3));
}

export const MAX_ATTEMPTS = 6;
