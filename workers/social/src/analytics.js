/**
 * Performance collection.
 *
 * Explicitly NOT an optimiser. With a handful of posts, "Tuesdays at 6pm do
 * better" is noise dressed as a finding, and acting on it would be worse than
 * acting on nothing. So this module only records — wide, timestamped rows with
 * the day-of-week and local hour already denormalised — and the scheduler does
 * not read them.
 *
 * `summary()` shows what has been collected and says plainly when there is not
 * enough of it to draw a conclusion from.
 */
import { nowMs, utcToEastern } from './util.js';
import * as ig from './instagram.js';
import { log } from './log.js';

/** How long to keep re-collecting a post. Engagement is basically done by day 7. */
const COLLECT_WINDOW_MS = 7 * 86400e3;

export async function collect(env, { at = nowMs(), limit = 25 } = {}) {
  const rows = await env.DB.prepare(
    `SELECT id, ig_media_id, published_at, type, surface FROM content_items
      WHERE status='published' AND ig_media_id IS NOT NULL AND published_at > ?
      ORDER BY published_at DESC LIMIT ?`
  ).bind(at - COLLECT_WINDOW_MS, limit).all();

  let ok = 0;
  let failed = 0;
  for (const item of rows.results || []) {
    try {
      const mediaType = item.type === 'reel' ? 'REELS' : 'IMAGE';
      const data = await ig.insights(env, item.ig_media_id, mediaType);
      const local = utcToEastern(item.published_at);
      await env.DB.prepare(
        `INSERT OR REPLACE INTO insights (item_id, ig_media_id, collected_at, published_at, dow,
           hour_local, content_type, impressions, reach, likes, comments, shares, saved,
           profile_visits, follows, video_views, watch_time_ms, raw)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
      ).bind(
        item.id, item.ig_media_id, at, item.published_at,
        new Date(item.published_at).getUTCDay(), Number(local.time.slice(0, 2)),
        item.type,
        num(data.impressions ?? data.views), num(data.reach), num(data.likes), num(data.comments),
        num(data.shares), num(data.saved), num(data.profile_visits), num(data.follows),
        num(data.views), num(data.ig_reels_video_view_total_time),
        JSON.stringify(data).slice(0, 4000)
      ).run();
      ok += 1;
    } catch (e) {
      failed += 1;
      if (e instanceof ig.IgError && e.kind === 'auth') {
        await log(env, 'error', 'analytics', item.id,
          `Insights collection stopped — token problem: ${e.message}`, null, at);
        break;
      }
    }
  }
  return { collected: ok, failed };
}

function num(v) {
  return typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null;
}

/**
 * What the data says, and whether it says it loudly enough to act on.
 *
 * The threshold is deliberate: below 12 posts in a bucket the differences are
 * inside the noise, and the console prints that instead of a ranking.
 */
export async function summary(env) {
  const latest = await env.DB.prepare(
    `SELECT i.* FROM insights i
      JOIN (SELECT ig_media_id, MAX(collected_at) AS c FROM insights GROUP BY ig_media_id) m
        ON m.ig_media_id = i.ig_media_id AND m.c = i.collected_at`
  ).all();
  const rows = latest.results || [];

  const byHour = bucket(rows, (r) => r.hour_local);
  const byDow = bucket(rows, (r) => r.dow);
  const byType = bucket(rows, (r) => r.content_type);

  return {
    posts: rows.length,
    enough_data: rows.length >= 12,
    note: rows.length >= 12
      ? null
      : `${rows.length} posts measured. Below 12 the differences between slots are noise — ` +
        'no scheduling decision reads this yet, by design.',
    by_hour: byHour,
    by_dow: byDow,
    by_type: byType,
  };
}

function bucket(rows, keyOf) {
  const map = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (k === null || k === undefined) continue;
    const b = map.get(k) || { n: 0, reach: 0, likes: 0, saved: 0 };
    b.n += 1;
    b.reach += r.reach || 0;
    b.likes += r.likes || 0;
    b.saved += r.saved || 0;
    map.set(k, b);
  }
  return [...map.entries()]
    .map(([k, b]) => ({
      key: k, n: b.n,
      avg_reach: Math.round(b.reach / b.n),
      avg_likes: Math.round(b.likes / b.n),
      avg_saved: Math.round(b.saved / b.n),
    }))
    .sort((a, b) => b.avg_reach - a.avg_reach);
}
