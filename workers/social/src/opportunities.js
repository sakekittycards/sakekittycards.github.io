/**
 * The content opportunity engine.
 *
 * Cron jobs answer "is it time to post?" — which is the wrong question, because
 * the answer depends on what we already posted, when the show was added, and
 * whether the event is still real. Opportunities answer "what promotion of this
 * show is still worth doing?", which is a question you can look at and check.
 *
 * For one show the model reads:
 *
 *     SWFL Super Card Show X2 — Sep 11
 *       Announcement    eligible through Sep 2   used     (posted Aug 20)
 *       7-day reminder  eligible Sep 3 – Sep 6   pending
 *       This weekend    eligible Sep 8 – Sep 9   pending
 *       Show day        Sep 11                   disabled
 *
 * Every row has a deterministic id derived from (event, kind), so the engine is
 * idempotent: running it a hundred times produces those four rows and no more.
 */
import { stableId, isoDate, addDays, daysBetween, easternToUtc, nowMs } from './util.js';
import { isMasked } from './events.js';
import { log } from './log.js';

export const KINDS = ['ANNOUNCEMENT', 'UPCOMING', 'THIS_WEEKEND', 'DAY_OF'];

export async function opportunityId(eventId, kind) {
  return stableId('opp', eventId, kind);
}

/**
 * Recompute the opportunity ladder for every live event.
 *
 * Never destructive: an opportunity that has already produced an item keeps its
 * status. Only `pending` rows are re-derived, so a policy change reshapes the
 * future without rewriting history.
 */
export async function refreshOpportunities(env, policy, { at = nowMs() } = {}) {
  const today = isoDate(at);
  const summary = { created: 0, retired: 0, expired: 0, skipped: 0, cancelledItems: 0 };

  // When the calendar was first mirrored. Everything already present at that
  // moment is history, not news — see the ANNOUNCEMENT branch of planWindow().
  const marker = await env.DB.prepare("SELECT v FROM meta WHERE k='first_ingest_at'").first();
  const firstIngestAt = marker ? Number(marker.v) : 0;

  const events = await env.DB.prepare(
    `SELECT * FROM events WHERE COALESCE(end_date, event_date) >= ? ORDER BY event_date`
  ).bind(addDays(today, -1)).all();

  for (const ev of events.results || []) {
    const existing = await env.DB.prepare(
      'SELECT * FROM opportunities WHERE event_id = ?'
    ).bind(ev.id).all();
    const byKind = new Map((existing.results || []).map((o) => [o.kind, o]));

    // A cancelled show retires everything that has not gone out yet. This is the
    // single most important branch in the file.
    if (ev.status === 'cancelled') {
      for (const opp of existing.results || []) {
        if (opp.status === 'pending' || opp.status === 'ready') {
          await setStatus(env, opp.id, 'retired', 'event cancelled', at);
          summary.retired += 1;
        }
      }

      // Retiring the opportunities is not enough. Any draft or approved post
      // already built for this show has to leave the queue too — otherwise it
      // sits in 'needs_review' where a human can still approve it, and posting
      // "come see us at X" for a cancelled show is the single most damaging
      // thing this system could do. Published items are left alone; that
      // already happened and rewriting it would make the post log lie.
      const killed = await env.DB.prepare(
        `UPDATE content_items
            SET status='rejected', scheduled_for=NULL, failure_reason=?, updated_at=?
          WHERE event_id=? AND status IN ('draft','needs_review','approved','scheduled','failed')`
      ).bind('the show was cancelled or removed from the website', at, ev.id).run();
      const n = killed.meta ? killed.meta.changes : 0;
      if (n) {
        summary.cancelledItems += n;
        await log(env, 'warn', 'items', ev.id,
          `${n} queued post(s) removed from the queue — "${ev.title}" is no longer on the website. `
          + 'They cannot be approved or published.', null, at);
      }
      continue;
    }

    for (const kind of KINDS) {
      const win = policy.windows[kind];
      const plan = planWindow(ev, kind, win, today, { firstIngestAt, now: at });
      const prior = byKind.get(kind);

      if (!plan.applicable) {
        if (prior && prior.status === 'pending') {
          await setStatus(env, prior.id, plan.terminal ? 'expired' : 'skipped', plan.reason, at);
          if (plan.terminal) summary.expired += 1; else summary.skipped += 1;
        }
        continue;
      }

      const id = await opportunityId(ev.id, kind);
      if (!prior) {
        await env.DB.prepare(
          `INSERT INTO opportunities (id, event_id, kind, eligible_from, eligible_to, target_at,
             status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)`
        ).bind(id, ev.id, kind, plan.from, plan.to, plan.target_at, 'pending', at, at).run();
        summary.created += 1;
        continue;
      }

      if (prior.status === 'pending') {
        await env.DB.prepare(
          'UPDATE opportunities SET eligible_from=?, eligible_to=?, target_at=?, updated_at=? WHERE id=?'
        ).bind(plan.from, plan.to, plan.target_at, at, prior.id).run();
      }
    }
  }

  return summary;
}

/**
 * Should this (event, kind) exist, and when is it eligible?
 *
 * `terminal` distinguishes "the window has closed forever" (expired) from
 * "policy or event state rules this out" (skipped) — the console shows those
 * differently because only one of them is worth looking at.
 */
export function planWindow(ev, kind, win, todayIso, ctx = {}) {
  if (!win || !win.enabled) {
    return { applicable: false, terminal: false, reason: `${kind} disabled in policy` };
  }
  if (isMasked(ev, todayIso)) {
    return { applicable: false, terminal: false, reason: 'event still masked as a teaser on the site' };
  }

  const daysOut = daysBetween(todayIso, ev.event_date);

  // Window bounds expressed as dates rather than day counts, so the console can
  // show "eligible Sep 3 – Sep 6" instead of "between 8 and 5 days out".
  const from = addDays(ev.event_date, -win.from);
  const to = addDays(ev.event_date, -win.to);

  if (daysOut < -0.5 && kind !== 'DAY_OF') {
    return { applicable: false, terminal: true, reason: 'event has passed' };
  }
  if (todayIso > to) {
    return { applicable: false, terminal: true, reason: `${kind} window closed on ${to}` };
  }

  // ── Announcements are about news, and news has two limits ────────────────
  //
  // Without these, "announce any show more than 9 days out" matches nearly every
  // event on a year-long calendar at once. The first run of the engine wanted to
  // announce eighteen shows, which at the configured spacing is a solid month of
  // posting nothing else. Both limits below exist because that actually happened.
  if (kind === 'ANNOUNCEMENT') {
    const horizon = win.max_horizon_days ?? 120;
    if (daysOut > horizon) {
      return {
        applicable: false, terminal: false,
        reason: `${daysOut} days out — beyond the ${horizon}-day announcement horizon`,
      };
    }

    const firstIngestAt = ctx.firstIngestAt || 0;
    const firstSeen = Number(ev.first_seen_at || 0);
    // Events present at the initial backfill are not new; they were already on
    // the public calendar before this system existed.
    if (firstIngestAt && firstSeen <= firstIngestAt) {
      return {
        applicable: false, terminal: true,
        reason: 'already on the calendar when the engine was installed — not news',
      };
    }

    const within = win.announce_within_days ?? 10;
    const ageDays = (Number(ctx.now || Date.now()) - firstSeen) / 86400e3;
    if (firstSeen && ageDays > within) {
      return {
        applicable: false, terminal: true,
        reason: `added ${Math.round(ageDays)} days ago — past the ${within}-day announcement window`,
      };
    }
  }

  const postAt = win.post_at || '18:30';
  // Target the first eligible day, or today if we are already inside the window.
  const targetDate = todayIso > from ? todayIso : from;
  return {
    applicable: true,
    terminal: false,
    from,
    to,
    target_at: easternToUtc(targetDate, postAt),
    reason: null,
  };
}


async function setStatus(env, id, status, reason, at) {
  await env.DB.prepare(
    'UPDATE opportunities SET status=?, reason=?, updated_at=? WHERE id=?'
  ).bind(status, reason, at, id).run();
}

/**
 * Opportunities that are eligible right now and have no content item yet.
 *
 * The per-event cap is applied here rather than at scheduling time so that a
 * show added four days out produces one draft, not three that a human has to
 * decline. `max_posts_per_event` counts what has already gone out plus what is
 * already queued.
 */
export async function dueOpportunities(env, policy, { at = nowMs(), limit = 25 } = {}) {
  const today = isoDate(at);
  const rows = await env.DB.prepare(
    `SELECT o.*, e.title, e.event_date, e.status AS event_status
       FROM opportunities o JOIN events e ON e.id = o.event_id
      WHERE o.status = 'pending' AND o.eligible_from <= ? AND o.eligible_to >= ?
        AND e.status = 'scheduled'
      ORDER BY e.event_date, o.kind LIMIT ?`
  ).bind(today, today, limit * 4).all();

  const out = [];
  const perEvent = new Map();
  for (const opp of rows.results || []) {
    if (out.length >= limit) break;
    let used = perEvent.get(opp.event_id);
    if (used === undefined) {
      const c = await env.DB.prepare(
        `SELECT COUNT(*) AS n FROM opportunities
          WHERE event_id = ? AND status IN ('drafted','scheduled','published')`
      ).bind(opp.event_id).first();
      used = c ? c.n : 0;
      perEvent.set(opp.event_id, used);
    }
    if (used >= policy.max_posts_per_event) {
      await setStatus(env, opp.id, 'skipped',
        `already ${used} posts for this event (cap ${policy.max_posts_per_event})`, at);
      continue;
    }
    perEvent.set(opp.event_id, used + 1);
    out.push(opp);
  }
  return out;
}

export async function markDrafted(env, oppId, itemId, at = nowMs()) {
  await env.DB.prepare(
    "UPDATE opportunities SET status='drafted', item_id=?, updated_at=? WHERE id=?"
  ).bind(itemId, at, oppId).run();
}

export async function markPublished(env, oppId, at = nowMs()) {
  await env.DB.prepare(
    "UPDATE opportunities SET status='published', updated_at=? WHERE id=?"
  ).bind(at, oppId).run();
}

/** The per-event ladder, for the console. */
export async function ladderForEvent(env, eventId) {
  const rows = await env.DB.prepare(
    'SELECT * FROM opportunities WHERE event_id = ? ORDER BY eligible_from'
  ).bind(eventId).all();
  return rows.results || [];
}

/**
 * Upcoming shows with nothing planned — the "what have we not promoted?" list
 * the console leads with.
 */
export async function unpromotedEvents(env, { at = nowMs(), withinDays = 60 } = {}) {
  const today = isoDate(at);
  const horizon = addDays(today, withinDays);
  const rows = await env.DB.prepare(
    `SELECT e.*,
            (SELECT COUNT(*) FROM opportunities o
              WHERE o.event_id = e.id AND o.status IN ('drafted','scheduled','published')) AS planned
       FROM events e
      WHERE e.status = 'scheduled' AND e.event_date BETWEEN ? AND ?
      ORDER BY e.event_date`
  ).bind(today, horizon).all();
  return (rows.results || []).filter((e) => e.planned === 0);
}
