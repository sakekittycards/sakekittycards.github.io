/**
 * Event ingestion.
 *
 * The website's `assets/events-data.js` is the source of truth and stays that
 * way — Nick adds a show by editing that file, exactly as he does today. This
 * module accepts a normalized snapshot of it and reconciles our mirror against
 * it. Nothing here ever writes back to the site.
 *
 * Two ideas carry the whole file:
 *
 *   identity     `id` is derived from (normalized title, start date). Those two
 *                are what make a show *that* show; venue, hours and description
 *                can all be corrected without the event becoming a new one.
 *
 *   fingerprint  a hash of only the facts a post actually states. A change to
 *                the fingerprint means an already-approved graphic is now
 *                telling people something untrue, so the item goes back for
 *                re-review. A change outside it is invisible to the audience and
 *                must not generate work.
 */
import { stableId, sha256Hex, nowMs, daysBetween } from './util.js';
import { log } from './log.js';

/** Fields a post states. Order is fixed — a reorder would invalidate every row. */
const FINGERPRINT_FIELDS = [
  'title', 'venue', 'address', 'city', 'state',
  'event_date', 'end_date', 'hours_text', 'booth', 'status',
];

export async function eventFingerprint(ev) {
  const parts = FINGERPRINT_FIELDS.map((f) => `${f}=${normalizeValue(ev[f])}`);
  return sha256Hex(parts.join(''));
}

function normalizeValue(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/\s+/g, ' ').trim().toLowerCase();
}

/** Identity key: what makes this show *this* show. */
export function identityKey(title, eventDate) {
  return `${normalizeValue(title)}|${eventDate}`;
}

export async function eventId(title, eventDate) {
  return stableId('ev', identityKey(title, eventDate));
}

/**
 * Reconcile a full snapshot against the mirror.
 *
 * Full-snapshot semantics, not a delta feed: an event that disappears from the
 * site is treated as cancelled rather than quietly forgotten, because a
 * cancelled show with a scheduled post is the single most damaging thing this
 * system could publish.
 */
export async function ingestEvents(env, snapshot, { at = nowMs(), source = 'events-data.js' } = {}) {
  // The first ingest is a backfill of a calendar that already existed. Those
  // events are not news, and announcing all of them would be the single most
  // annoying thing this system could do on day one. Recording when the backfill
  // happened is what lets the opportunity engine tell "new show" from "show we
  // have always known about" — see planWindow().
  const firstIngest = await env.DB.prepare("SELECT v FROM meta WHERE k='first_ingest_at'").first();
  if (!firstIngest) {
    await env.DB.prepare("INSERT OR REPLACE INTO meta (k,v) VALUES ('first_ingest_at', ?)")
      .bind(String(at)).run();
  }

  const seen = new Set();
  const result = { added: [], updated: [], material: [], cancelled: [], unchanged: 0 };

  for (const raw of snapshot) {
    const ev = normalizeEvent(raw);
    if (!ev.title || !ev.event_date) continue;
    ev.id = await eventId(ev.title, ev.event_date);
    ev.fingerprint = await eventFingerprint(ev);
    seen.add(ev.id);

    const existing = await env.DB.prepare('SELECT * FROM events WHERE id = ?').bind(ev.id).first();

    if (!existing) {
      await env.DB.prepare(
        `INSERT INTO events (id, source, title, venue, address, city, state, event_date, end_date,
           start_time, end_time, hours_text, organizer, event_url, website_url, booth, description,
           flyer_url, social_url, kind, masked, reveal_at, status, content_status, fingerprint, raw,
           first_seen_at, created_at, updated_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
      ).bind(
        ev.id, source, ev.title, ev.venue, ev.address, ev.city, ev.state, ev.event_date, ev.end_date,
        ev.start_time, ev.end_time, ev.hours_text, ev.organizer, ev.event_url, ev.website_url,
        ev.booth, ev.description, ev.flyer_url, ev.social_url, ev.kind, ev.masked ? 1 : 0,
        ev.reveal_at, ev.status, 'new', ev.fingerprint, JSON.stringify(raw), at, at, at
      ).run();
      result.added.push(ev.id);
      await log(env, 'info', 'events', ev.id,
        `Found new event: ${ev.title} — ${humanDate(ev.event_date)}`,
        { venue: ev.venue, city: ev.city, state: ev.state }, at);
      continue;
    }

    if (existing.fingerprint === ev.fingerprint && existing.status === ev.status) {
      // Non-material fields can still drift; keep the mirror faithful without
      // touching content_status or waking any approved item.
      await env.DB.prepare(
        `UPDATE events SET description = ?, event_url = ?, website_url = ?, organizer = ?,
           flyer_url = COALESCE(?, flyer_url), social_url = COALESCE(?, social_url),
           raw = ?, updated_at = ? WHERE id = ?`
      ).bind(ev.description, ev.event_url, ev.website_url, ev.organizer,
        ev.flyer_url, ev.social_url, JSON.stringify(raw), at, ev.id).run();
      result.unchanged += 1;
      continue;
    }

    const changed = diffFields(existing, ev);
    await env.DB.prepare(
      `UPDATE events SET title=?, venue=?, address=?, city=?, state=?, event_date=?, end_date=?,
         start_time=?, end_time=?, hours_text=?, organizer=?, event_url=?, website_url=?, booth=?,
         description=?, flyer_url=COALESCE(?, flyer_url), social_url=COALESCE(?, social_url),
         kind=?, masked=?, reveal_at=?, status=?, fingerprint=?, raw=?, updated_at=? WHERE id=?`
    ).bind(
      ev.title, ev.venue, ev.address, ev.city, ev.state, ev.event_date, ev.end_date,
      ev.start_time, ev.end_time, ev.hours_text, ev.organizer, ev.event_url, ev.website_url,
      ev.booth, ev.description, ev.flyer_url, ev.social_url, ev.kind, ev.masked ? 1 : 0,
      ev.reveal_at, ev.status, ev.fingerprint, JSON.stringify(raw), at, ev.id
    ).run();

    result.updated.push(ev.id);
    result.material.push({ id: ev.id, changed });
    await log(env, 'warn', 'events', ev.id,
      `Event changed: ${ev.title} — ${changed.map((c) => c.field).join(', ')}`,
      { changed }, at);
  }

  // Anything we know about that the site no longer lists, and that has not
  // already happened, is a cancellation.
  const today = new Date(at).toISOString().slice(0, 10);
  const stale = await env.DB.prepare(
    `SELECT id, title, event_date FROM events
      WHERE source = ? AND status = 'scheduled' AND COALESCE(end_date, event_date) >= ?`
  ).bind(source, today).all();

  for (const row of stale.results || []) {
    if (seen.has(row.id)) continue;
    await env.DB.prepare(
      "UPDATE events SET status = 'cancelled', fingerprint = ?, updated_at = ? WHERE id = ?"
    ).bind(await sha256Hex(`cancelled:${row.id}`), at, row.id).run();
    result.cancelled.push(row.id);
    await log(env, 'warn', 'events', row.id,
      `Event no longer on the website — treating as cancelled: ${row.title} (${row.event_date})`,
      null, at);
  }

  return result;
}

function diffFields(before, after) {
  const out = [];
  for (const f of FINGERPRINT_FIELDS) {
    if (normalizeValue(before[f]) !== normalizeValue(after[f])) {
      out.push({ field: f, from: before[f] ?? null, to: after[f] ?? null });
    }
  }
  return out;
}

/**
 * Coerce an inbound record into the stored shape.
 *
 * The site's own schema is loose by design (a single `loc` string carrying
 * "Venue · Street, City, ST ZIP"); the split happens in the local ingest script
 * where it can be eyeballed, and this is the defensive backstop.
 */
export function normalizeEvent(raw) {
  const masked = Boolean(raw.masked);
  return {
    title: str(raw.title),
    venue: str(raw.venue),
    address: str(raw.address),
    city: str(raw.city),
    state: str(raw.state),
    event_date: str(raw.event_date),
    end_date: str(raw.end_date) || null,
    start_time: str(raw.start_time) || null,
    end_time: str(raw.end_time) || null,
    hours_text: str(raw.hours_text) || null,
    organizer: str(raw.organizer) || null,
    event_url: str(raw.event_url) || null,
    website_url: str(raw.website_url) || null,
    booth: str(raw.booth) || null,
    description: str(raw.description) || null,
    flyer_url: str(raw.flyer_url) || null,
    social_url: str(raw.social_url) || null,
    kind: raw.kind === 'online' ? 'online' : 'show',
    masked,
    reveal_at: str(raw.reveal_at) || null,
    status: raw.status === 'cancelled' ? 'cancelled' : 'scheduled',
  };
}

function str(v) {
  return v === null || v === undefined ? '' : String(v).trim();
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

export function humanDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

/**
 * Is this event still masked as a teaser?
 *
 * The site hides some shows behind "👀 Secret Show — Stay Tuned" until a reveal
 * date. Promoting the real name early would break that on the one channel where
 * it is most visible, so a masked event is not promotable at all until reveal —
 * we do not have a "post the teaser" template, and inventing one silently is
 * worse than skipping.
 */
export function isMasked(ev, todayIso) {
  if (!ev.masked) return false;
  if (!ev.reveal_at) return true;
  return todayIso < ev.reveal_at;
}

export function daysUntil(ev, todayIso) {
  return daysBetween(todayIso, ev.event_date);
}
