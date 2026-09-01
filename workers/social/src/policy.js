/**
 * Promotion + automation policy.
 *
 * Everything the engine decides — which reminders exist, how close together two
 * posts may land, whether a content type may skip a human — is a value in here,
 * not a constant buried in a scheduler. Nick changes cadence from the console;
 * nobody edits a cron expression.
 *
 * Defaults are deliberately conservative: every content type requires manual
 * approval, and publishing runs in dry mode until it is explicitly turned off.
 */

export const DEFAULT_POLICY = {
  // ── Publishing mode ───────────────────────────────────────────────────────
  // 'dry'  — build the full Instagram payload, log exactly what would be sent,
  //          stop before the call. This is the shipping default.
  // 'live' — actually publish.
  mode: 'dry',

  // ── Promotion windows, in days before the event's first day ───────────────
  // `enabled` turns a rung of the ladder on or off. `from`/`to` bound the window
  // in which the opportunity is eligible; `post_at` is the local time of day it
  // targets. An event added inside a window still gets that window's post — but
  // `min_lead_hours` stops a show added tonight from firing three posts at once.
  windows: {
    // An announcement is about the show being NEW, not about the show existing.
    // `announce_within_days` is measured from when we first saw the event, not
    // from the event date — otherwise every show already on the calendar is
    // inside its announcement window and the engine wants to post 18 of them.
    ANNOUNCEMENT: {
      enabled: true, from: 365, to: 9, post_at: '18:30', label: 'Announcement',
      announce_within_days: 10,   // of first seeing it
      max_horizon_days: 120,      // do not announce a show 11 months out
    },
    UPCOMING: { enabled: true, from: 8, to: 5, post_at: '18:30', label: '7-day reminder' },
    THIS_WEEKEND: { enabled: true, from: 3, to: 2, post_at: '11:00', label: 'This weekend' },
    DAY_OF: { enabled: false, from: 0, to: 0, post_at: '08:30', label: 'Show day', surface: 'story' },
  },

  // A show announced with 4 days' notice should get one good post, not the
  // announcement, the 7-day and the weekend reminder stacked inside 72 hours.
  max_posts_per_event: 2,
  min_lead_hours: 6,          // never schedule something less than this from now
  min_gap_same_event_hours: 40,

  // ── Collision rules ───────────────────────────────────────────────────────
  spacing: {
    any_two_posts_hours: 20,      // nothing lands closer than this
    two_event_posts_hours: 44,    // event posts specifically breathe further apart
    reel_near_event_minutes: 180, // a reel this close to an event post needs an override
    max_per_day: 2,
    quiet_hours_local: [23, 7],   // [start, end) — nothing publishes overnight
  },

  // ── Automation per content type ───────────────────────────────────────────
  // `auto_approve` skips the human gate. `auto_schedule` puts an approved item
  // straight on the calendar. Both start off. Video deliberately has no
  // auto_approve key at all — see video.js; social approval of a reel is a
  // second gate on top of the video's own approval, and neither is automatable
  // from the policy table.
  automation: {
    event_graphic: { auto_approve: false, auto_schedule: false },
    event_caption: { auto_approve: false },
    reel: { auto_schedule_after_approval: false },
  },

  // ── Voice ─────────────────────────────────────────────────────────────────
  hashtags: {
    // Small, deliberate sets. Thirty hashtags is a 2019 growth hack that now
    // reads as spam, and Instagram's own guidance is 3-5.
    event: ['#pokemoncards', '#cardshow', '#floridacardshows', '#pokemontcg'],
    reel: ['#pokemoncards', '#pokemontcg', '#cardcollector'],
    max: 6,
  },

  services: {
    buy: true,
    sell: true,
    trade: true,
    grading_prep: true,
    collections: true,
  },
};

export async function getPolicy(env) {
  const row = await env.DB.prepare('SELECT v FROM policy WHERE k = ?').bind('main').first();
  if (!row) return structuredClone(DEFAULT_POLICY);
  try {
    return mergePolicy(structuredClone(DEFAULT_POLICY), JSON.parse(row.v));
  } catch {
    return structuredClone(DEFAULT_POLICY);
  }
}

export async function setPolicy(env, patch, at) {
  const current = await getPolicy(env);
  const next = mergePolicy(current, patch);
  await env.DB.prepare(
    'INSERT INTO policy (k, v, updated_at) VALUES (?, ?, ?) ' +
    'ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at'
  ).bind('main', JSON.stringify(next), at).run();
  return next;
}

/** Deep merge, objects only — arrays are replaced wholesale, not concatenated. */
export function mergePolicy(base, patch) {
  if (!patch || typeof patch !== 'object') return base;
  for (const [k, v] of Object.entries(patch)) {
    if (v && typeof v === 'object' && !Array.isArray(v) && base[k] && typeof base[k] === 'object' && !Array.isArray(base[k])) {
      base[k] = mergePolicy(base[k], v);
    } else {
      base[k] = v;
    }
  }
  return base;
}

/**
 * The effective publish mode.
 *
 * Two independent gates, and the safer one always wins: the worker's own
 * `PUBLISH_MODE` var (deploy-time) and the policy row (runtime). Live publishing
 * requires BOTH to say live, so flipping the console switch on a worker that was
 * never configured for live posting does nothing.
 */
export function effectiveMode(env, policy) {
  const deploy = String(env.PUBLISH_MODE || 'dry').toLowerCase();
  const runtime = String(policy.mode || 'dry').toLowerCase();
  return deploy === 'live' && runtime === 'live' ? 'live' : 'dry';
}
