/**
 * Engine suite: ingestion, opportunities, scheduling, idempotency, publishing.
 *
 * The publish tests use a fake Instagram module injected through
 * `globalThis.__IG_FAKE__` (see the hook at the bottom of instagram.js's import
 * in publish.js — the fake is installed by monkey-patching the module's exports,
 * which works because ES module namespace objects are live bindings we control
 * here via a wrapper). Where a real HTTP call would be, we count calls: the
 * whole point of the idempotency tests is "how many times did we call publish".
 *
 * Run: node test/engine_test.mjs
 */
import { makeEnv, suite, ok, eq, throws, report, SAMPLE_EVENTS, sampleProbe } from './harness.mjs';
import { ingestEvents, eventFingerprint, eventId, isMasked, normalizeEvent } from '../src/events.js';
import * as opps from '../src/opportunities.js';
import * as items from '../src/items.js';
import * as sched from '../src/scheduler.js';
import * as pub from '../src/publish.js';
import * as video from '../src/video.js';
import { storeMedia } from '../src/media.js';
import { DEFAULT_POLICY, mergePolicy, effectiveMode, setPolicy, getPolicy } from '../src/policy.js';
import { easternToUtc, utcToEastern, easternOffsetMinutes, daysBetween, addDays } from '../src/util.js';

const AT = Date.UTC(2026, 8, 1, 15, 0, 0);   // 2026-09-01 11:00 ET
const P = () => structuredClone(DEFAULT_POLICY);

async function seedMedia(env) {
  const bytes = new TextEncoder().encode(`graphic-${Math.random()}`);
  return storeMedia(env, bytes, { kind: 'image', contentType: 'image/jpeg', width: 1080, height: 1350, at: AT });
}

async function main() {
  // ── Time ──────────────────────────────────────────────────────────────────
  suite('Eastern time handling');
  {
    eq(easternOffsetMinutes(Date.UTC(2026, 6, 4, 12)), -240, 'July is EDT (UTC-4)');
    eq(easternOffsetMinutes(Date.UTC(2026, 0, 15, 12)), -300, 'January is EST (UTC-5)');
    // 2026: DST starts Mar 8, ends Nov 1.
    eq(easternOffsetMinutes(Date.UTC(2026, 2, 8, 6, 59)), -300, 'just before the spring transition is EST');
    eq(easternOffsetMinutes(Date.UTC(2026, 2, 8, 7, 1)), -240, 'just after the spring transition is EDT');
    eq(easternOffsetMinutes(Date.UTC(2026, 10, 1, 5, 59)), -240, 'just before the autumn transition is EDT');
    eq(easternOffsetMinutes(Date.UTC(2026, 10, 1, 6, 1)), -300, 'just after the autumn transition is EST');

    const utc = easternToUtc('2026-09-19', '18:30');
    eq(utcToEastern(utc).label, '2026-09-19 18:30 ET', '18:30 ET round-trips');
    const winter = easternToUtc('2026-12-12', '08:30');
    eq(utcToEastern(winter).label, '2026-12-12 08:30 ET', '08:30 ET round-trips in winter');
    eq(daysBetween('2026-09-01', '2026-09-19'), 18, 'day arithmetic');
    eq(addDays('2026-09-19', -7), '2026-09-12', 'addDays across a week');
    eq(addDays('2026-03-01', -1), '2026-02-28', 'addDays across a month boundary');
  }

  // ── Ingestion ─────────────────────────────────────────────────────────────
  suite('event ingestion is idempotent');
  {
    const env = makeEnv();
    const r1 = await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    eq(r1.added.length, 4, 'four events added on first run');

    const r2 = await ingestEvents(env, SAMPLE_EVENTS, { at: AT + 1000 });
    eq(r2.added.length, 0, 'nothing added on a second identical run');
    eq(r2.updated.length, 0, 'nothing updated either');
    eq(r2.unchanged, 4, 'all four recognised as unchanged');

    const count = await env.DB.prepare('SELECT COUNT(*) AS n FROM events').first();
    eq(count.n, 4, 'still exactly four rows');
  }

  suite('identity survives a non-material edit, but a material one is flagged');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const id = await eventId('Stuart Card Show', '2026-09-19');

    // A description tweak states nothing a post states.
    const cosmetic = SAMPLE_EVENTS.map((e) => e.title === 'Stuart Card Show'
      ? { ...e, description: 'now with more tables', event_url: 'https://example.test/x' } : e);
    const r = await ingestEvents(env, cosmetic, { at: AT + 2000 });
    eq(r.material.length, 0, 'a description change is not material');
    const still = await env.DB.prepare('SELECT * FROM events WHERE id=?').bind(id).first();
    eq(still.description, 'now with more tables', 'but it is still mirrored');

    // Moving the venue changes what a post would say.
    const moved = SAMPLE_EVENTS.map((e) => e.title === 'Stuart Card Show'
      ? { ...e, venue: 'Somewhere Else', address: '1 Other Rd' } : e);
    const r2 = await ingestEvents(env, moved, { at: AT + 3000 });
    eq(r2.material.length, 1, 'a venue change IS material');
    ok(r2.material[0].changed.some((c) => c.field === 'venue'), 'and names the changed field');
    eq(r2.added.length, 0, 'the event kept its identity — no duplicate created');
  }

  suite('an event dropped from the website is treated as cancelled');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const without = SAMPLE_EVENTS.filter((e) => e.title !== 'Stuart Card Show');
    const r = await ingestEvents(env, without, { at: AT + 1000 });
    eq(r.cancelled.length, 1, 'the missing event is cancelled');
    const id = await eventId('Stuart Card Show', '2026-09-19');
    const ev = await env.DB.prepare('SELECT status FROM events WHERE id=?').bind(id).first();
    eq(ev.status, 'cancelled', 'and its row says so rather than disappearing');
  }

  suite('masking is respected');
  {
    ok(isMasked({ masked: 1, reveal_at: '2026-10-01' }, '2026-09-01'), 'masked before the reveal date');
    ok(!isMasked({ masked: 1, reveal_at: '2026-10-01' }, '2026-10-02'), 'not masked after it');
    ok(isMasked({ masked: 1, reveal_at: null }, '2026-09-01'), 'masked forever with no reveal date');
    ok(!isMasked({ masked: 0 }, '2026-09-01'), 'unmasked events are never masked');
  }

  // ── Opportunities ─────────────────────────────────────────────────────────
  suite('the opportunity ladder');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const policy = P();
    const r = await opps.refreshOpportunities(env, policy, { at: AT });
    ok(r.created > 0, `created ${r.created} opportunities`);

    const before = await env.DB.prepare('SELECT COUNT(*) AS n FROM opportunities').first();
    await opps.refreshOpportunities(env, policy, { at: AT + 1000 });
    const after = await env.DB.prepare('SELECT COUNT(*) AS n FROM opportunities').first();
    eq(after.n, before.n, 'a second refresh creates nothing new — deterministic ids');

    const stuart = await eventId('Stuart Card Show', '2026-09-19');
    const ladder = await opps.ladderForEvent(env, stuart);
    const kinds = ladder.map((l) => l.kind).sort();
    eq(kinds, ['THIS_WEEKEND', 'UPCOMING'],
      'a backfilled show gets its reminders — no announcement (it is not news) and no DAY_OF (disabled)');

    const up = ladder.find((l) => l.kind === 'UPCOMING');
    eq([up.eligible_from, up.eligible_to], ['2026-09-11', '2026-09-14'], '7-day reminder window');
    const we = ladder.find((l) => l.kind === 'THIS_WEEKEND');
    eq([we.eligible_from, we.eligible_to], ['2026-09-16', '2026-09-17'], 'weekend reminder window');
  }

  suite('announcements fire for NEW shows, not for the whole existing calendar');
  {
    const env = makeEnv();
    // First ingest = backfill. Everything in it was already on the public
    // calendar before the engine existed.
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });

    const anns = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM opportunities WHERE kind='ANNOUNCEMENT'"
    ).first();
    eq(anns.n, 0, 'the backfill announces nothing — this is the flood that must not happen');

    // Nick adds a show two days later. THAT is news.
    const later = AT + 2 * 86400e3;
    await ingestEvents(env, [...SAMPLE_EVENTS, {
      title: 'Naples Card Show', venue: 'The White Rose', city: 'Naples', state: 'FL',
      event_date: '2026-10-11', hours_text: '10am-4pm', kind: 'show',
    }], { at: later });
    await opps.refreshOpportunities(env, P(), { at: later });

    const newId = await eventId('Naples Card Show', '2026-10-11');
    const ladder = await opps.ladderForEvent(env, newId);
    ok(ladder.some((l) => l.kind === 'ANNOUNCEMENT' && l.status === 'pending'),
      'the newly added show DOES get an announcement');

    const stuart = await eventId('Stuart Card Show', '2026-09-19');
    const old = await opps.ladderForEvent(env, stuart);
    ok(!old.some((l) => l.kind === 'ANNOUNCEMENT'),
      'and the pre-existing shows still do not');
  }

  suite('an announcement goes stale if nobody acts on it');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const added = AT + 86400e3;
    await ingestEvents(env, [...SAMPLE_EVENTS, {
      title: 'Late Addition Show', venue: 'A Hall', city: 'Tampa', state: 'FL',
      event_date: '2026-11-14', kind: 'show',
    }], { at: added });
    await opps.refreshOpportunities(env, P(), { at: added });
    const id = await eventId('Late Addition Show', '2026-11-14');
    ok((await opps.ladderForEvent(env, id)).some((l) => l.kind === 'ANNOUNCEMENT'),
      'announceable when it is new');

    // 20 days later it is no longer news.
    const late = added + 20 * 86400e3;
    await opps.refreshOpportunities(env, P(), { at: late });
    const ann = (await opps.ladderForEvent(env, id)).find((l) => l.kind === 'ANNOUNCEMENT');
    eq(ann.status, 'expired', 'the unused announcement expires rather than firing weeks late');
  }

  suite('a show beyond the announcement horizon waits');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const added = AT + 86400e3;
    // 2027-01-09 is ~130 days out from 2026-09-02, past the 120-day horizon.
    await ingestEvents(env, [...SAMPLE_EVENTS, {
      title: 'The Hobby Card Show', venue: 'Broward County Convention Center',
      city: 'Fort Lauderdale', state: 'FL', event_date: '2027-01-09',
      end_date: '2027-01-10', kind: 'show',
    }], { at: added });
    await opps.refreshOpportunities(env, P(), { at: added });
    const id = await eventId('The Hobby Card Show', '2027-01-09');
    const ladder = await opps.ladderForEvent(env, id);
    ok(!ladder.some((l) => l.kind === 'ANNOUNCEMENT'),
      'a show four months out is not announced yet');
  }

  suite('a masked event produces no opportunities until it is revealed');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });
    const secret = await eventId('👀 Secret Show — Stay Tuned', '2026-10-17');
    const ladder = await opps.ladderForEvent(env, secret);
    eq(ladder.length, 0, 'nothing scheduled for a teaser show');
  }

  suite('cancelling an event retires its pending opportunities');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });
    const id = await eventId('Stuart Card Show', '2026-09-19');
    const live = await opps.ladderForEvent(env, id);
    ok(live.length >= 2, `the show has a ladder (${live.length} rungs)`);

    await ingestEvents(env, SAMPLE_EVENTS.filter((e) => e.title !== 'Stuart Card Show'), { at: AT + 1000 });
    const r = await opps.refreshOpportunities(env, P(), { at: AT + 1000 });
    ok(r.retired >= 2, `${r.retired} opportunities retired`);
    const after = await opps.ladderForEvent(env, id);
    ok(after.every((o) => o.status !== 'pending'), 'nothing is still pending for a cancelled show');
  }

  suite('a show added at short notice does not fire the whole ladder');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });          // backfill first
    const added = AT + 1000;
    // Added on 2026-09-01 for 2026-09-04 — inside the announcement AND the
    // weekend window at once.
    await ingestEvents(env, [...SAMPLE_EVENTS, {
      title: 'Last Minute Show', venue: 'A Hall', city: 'Naples', state: 'FL',
      event_date: '2026-09-04', kind: 'show',
    }], { at: added });
    const policy = P();
    await opps.refreshOpportunities(env, policy, { at: added });
    const evId = await eventId('Last Minute Show', '2026-09-04');
    const due = (await opps.dueOpportunities(env, policy, { at: added }))
      .filter((o) => o.event_id === evId);
    ok(due.length <= policy.max_posts_per_event,
      `${due.length} opportunities offered for it, cap is ${policy.max_posts_per_event}`);
  }

  // ── Scheduling + spacing ──────────────────────────────────────────────────
  suite('spacing rules');
  {
    const env = makeEnv();
    const policy = P();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');

    const media = await seedMedia(env);
    const first = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_a', kind: 'ANNOUNCEMENT',
      caption: 'We are at the Stuart Card Show.', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, first, { by: 'nick', at: AT });
    const slotA = await sched.proposeSlot(env, policy, {
      desired: easternToUtc('2026-09-05', '18:30'), type: 'event', eventId: evId, ignoreItemId: first, now: AT,
    });
    await items.scheduleItem(env, first, slotA.at, { at: AT });
    eq(utcToEastern(slotA.at).label, '2026-09-05 18:30 ET', 'the first post takes the time it asked for');

    // A second event post an hour later must be pushed out.
    const ev2 = await eventId('SWFL Super Card Show X2', '2026-09-11');
    const m2 = await seedMedia(env);
    const second = await items.createEventItem(env, {
      eventId: ev2, opportunityId: 'opp_b', kind: 'ANNOUNCEMENT',
      caption: 'And SWFL the week after.', hashtags: [], mediaId: m2.id, at: AT,
    });
    const slotB = await sched.proposeSlot(env, policy, {
      desired: easternToUtc('2026-09-05', '19:30'), type: 'event', eventId: ev2, ignoreItemId: second, now: AT,
    });
    ok(slotB.moved, 'the second event post was moved');
    const gapH = (slotB.at - slotA.at) / 3600e3;
    ok(gapH >= policy.spacing.two_event_posts_hours,
      `moved to a ${gapH.toFixed(1)}h gap (rule: ${policy.spacing.two_event_posts_hours}h)`);
  }

  suite('quiet hours');
  {
    const env = makeEnv();
    const policy = P();
    const slot = await sched.proposeSlot(env, policy, {
      desired: easternToUtc('2026-09-10', '02:00'), type: 'event', now: AT,
    });
    const hour = Number(utcToEastern(slot.at).time.slice(0, 2));
    ok(hour >= 7 && hour < 23, `2am was moved to ${utcToEastern(slot.at).time} ET`);
  }

  suite('minimum lead time');
  {
    const env = makeEnv();
    const policy = P();
    const slot = await sched.proposeSlot(env, policy, { desired: AT + 60e3, type: 'event', now: AT });
    const leadH = (slot.at - AT) / 3600e3;
    ok(leadH >= policy.min_lead_hours, `a post requested for one minute out was pushed to +${leadH.toFixed(1)}h`);
  }

  // ── Leases and idempotency ────────────────────────────────────────────────
  suite('the publish lease admits exactly one winner');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_lease', kind: 'ANNOUNCEMENT',
      caption: 'c', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT, { at: AT });

    const a = await sched.claim(env, id, { at: AT });
    const b = await sched.claim(env, id, { at: AT });
    const c = await sched.claim(env, id, { at: AT });
    ok(a !== null, 'the first claimant wins');
    eq(b, null, 'the second gets nothing');
    eq(c, null, 'the third gets nothing');

    // After the lease expires the work becomes claimable again.
    const later = AT + 11 * 60e3;
    await env.DB.prepare("UPDATE content_items SET status='scheduled' WHERE id=?").bind(id).run();
    const d = await sched.claim(env, id, { at: later });
    ok(d !== null, 'an expired lease can be reclaimed');
    ok(d !== a, 'with a fresh token');
  }

  suite('a claim on an item that is not scheduled is refused');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_x', kind: 'ANNOUNCEMENT',
      caption: 'c', hashtags: [], mediaId: media.id, at: AT,
    });
    eq(await sched.claim(env, id, { at: AT }), null, 'a draft cannot be claimed');
    await items.approveItem(env, id, { by: 'nick', at: AT });
    eq(await sched.claim(env, id, { at: AT }), null, 'an approved-but-unscheduled item cannot be claimed');
    await items.scheduleItem(env, id, AT, { at: AT });
    ok(await sched.claim(env, id, { at: AT }), 'a scheduled item can');
  }

  suite('a published item cannot be claimed again');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_p', kind: 'ANNOUNCEMENT',
      caption: 'c', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT, { at: AT });
    await env.DB.prepare("UPDATE content_items SET status='published', ig_media_id='m1' WHERE id=?")
      .bind(id).run();
    eq(await sched.claim(env, id, { at: AT }), null, 'a published post is never re-leased');
  }

  suite('backoff grows and is bounded');
  {
    const a = sched.backoffMs(1);
    const b = sched.backoffMs(3);
    const z = sched.backoffMs(20);
    ok(b > a, 'the third attempt waits longer than the first');
    ok(z <= 2.4 * 3600e3, `attempt 20 is capped at ~2h (${(z / 3600e3).toFixed(2)}h)`);
    ok(a >= 100e3, 'the first backoff is at least ~100s');
  }

  suite('a stale lease is reclaimed, not lost');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_r', kind: 'ANNOUNCEMENT',
      caption: 'c', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT, { at: AT });
    await sched.claim(env, id, { at: AT });
    const n = await sched.reapStaleLeases(env, { at: AT + 20 * 60e3 });
    eq(n, 1, 'the abandoned item was reaped');
    const row = await items.getItem(env, id);
    eq(row.status, 'scheduled', 'and put back on the calendar rather than dropped');
  }

  // ── Staleness ─────────────────────────────────────────────────────────────
  suite('an approved post is pulled back when its event changes');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_s', kind: 'ANNOUNCEMENT',
      caption: 'The Flagler, Stuart.', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT + 86400e3, { at: AT });

    await ingestEvents(env, SAMPLE_EVENTS.map((e) => e.title === 'Stuart Card Show'
      ? { ...e, venue: 'A Different Hall' } : e), { at: AT + 1000 });

    const flagged = await items.revalidate(env, { at: AT + 2000 });
    eq(flagged.length, 1, 'exactly one item was flagged');
    const row = await items.getItem(env, id);
    eq(row.status, 'needs_review', 'the approved post is back in review');
    eq(row.scheduled_for, null, 'and off the calendar');

    await throws(async () => pub.buildPayload(env, await items.getItem(env, id)),
      'changed after approval', 'and the publisher would refuse it too');
  }

  suite('editing a caption after approval un-approves the item');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_c', kind: 'ANNOUNCEMENT',
      caption: 'original', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT + 86400e3, { at: AT });
    const r = await items.editCaption(env, id, { caption: 'something completely different', at: AT + 10 });
    ok(r.reset, 'the edit reset the approval');
    const row = await items.getItem(env, id);
    eq(row.status, 'needs_review', 'the item needs review again');
    eq(row.approved_by, null, 'the old signature is gone');
  }

  // ── Publishing, dry run and idempotency ───────────────────────────────────
  suite('dry run builds the real payload and never publishes');
  {
    const env = makeEnv({ PUBLISH_MODE: 'dry' });
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_d', kind: 'ANNOUNCEMENT',
      caption: "We're at the Stuart Card Show this Saturday.", hashtags: ['#pokemoncards'],
      mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT - 1000, { at: AT });

    const res = await pub.publishItem(env, id, P(), { at: AT });
    ok(res.dryRun, 'the publish was a dry run');
    ok(res.payload.params.image_url.includes('/m/'), 'a real media URL was built');
    ok(res.payload.params.caption.includes('#pokemoncards'), 'hashtags are folded into the caption');

    const row = await items.getItem(env, id);
    eq(row.status, 'scheduled', 'the item is still scheduled, not published');
    eq(row.ig_media_id, null, 'no Instagram media id was recorded');

    const pubs = await env.DB.prepare("SELECT * FROM publications WHERE item_id=?").bind(id).all();
    ok(pubs.results.some((p) => p.phase === 'dry-run' && p.mode === 'dry'),
      'the dry run is recorded in the publication log');
  }

  suite('live mode requires both gates');
  {
    eq(effectiveMode({ PUBLISH_MODE: 'dry' }, { mode: 'live' }), 'dry',
      'runtime live + deploy dry = dry');
    eq(effectiveMode({ PUBLISH_MODE: 'live' }, { mode: 'dry' }), 'dry',
      'deploy live + runtime dry = dry');
    eq(effectiveMode({ PUBLISH_MODE: 'live' }, { mode: 'live' }), 'live',
      'both live = live');
    eq(effectiveMode({}, { mode: 'live' }), 'dry', 'an unset deploy var means dry');
  }

  suite('the dry-run report covers the whole queue');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const good = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_g', kind: 'ANNOUNCEMENT',
      caption: 'fine', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, good, { by: 'nick', at: AT });

    const ev2 = await eventId('SWFL Super Card Show X2', '2026-09-11');
    const bad = await items.createEventItem(env, {
      eventId: ev2, opportunityId: 'opp_h', kind: 'ANNOUNCEMENT',
      caption: 'no graphic', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, bad, { by: 'nick', at: AT });
    await env.DB.prepare('UPDATE content_items SET media_id=NULL WHERE id=?').bind(bad).run();

    const rep = await pub.dryRunReport(env, P(), { at: AT });
    eq(rep.mode, 'dry', 'the report states the mode');
    eq(rep.items.length, 2, 'both approved items are covered');
    ok(rep.items.some((i) => i.would === 'publish'), 'one would publish');
    const refused = rep.items.find((i) => i.would === 'refuse');
    ok(refused && refused.reason.includes('no graphic'), 'and one is refused with a readable reason');
  }

  suite('publication history records every attempt');
  {
    const env = makeEnv();
    const media = await seedMedia(env);
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: 'opp_hist', kind: 'ANNOUNCEMENT',
      caption: 'x', hashtags: [], mediaId: media.id, at: AT,
    });
    await items.approveItem(env, id, { by: 'nick', at: AT });
    await items.scheduleItem(env, id, AT - 1000, { at: AT });
    await pub.publishItem(env, id, P(), { at: AT });
    await env.DB.prepare("UPDATE content_items SET status='scheduled', next_retry_at=NULL WHERE id=?").bind(id).run();
    await pub.publishItem(env, id, P(), { at: AT + 60e3 });

    const rows = await env.DB.prepare('SELECT * FROM publications WHERE item_id=? ORDER BY at').bind(id).all();
    ok(rows.results.length >= 2, `${rows.results.length} attempts recorded`);
    ok(rows.results.every((r) => r.mode === 'dry'), 'each row records the mode it ran in');
  }

  // ── Policy ────────────────────────────────────────────────────────────────
  suite('policy merge and persistence');
  {
    const env = makeEnv();
    const merged = mergePolicy(structuredClone(DEFAULT_POLICY), {
      windows: { UPCOMING: { post_at: '12:00' } },
      spacing: { max_per_day: 3 },
    });
    eq(merged.windows.UPCOMING.post_at, '12:00', 'a nested value is patched');
    eq(merged.windows.UPCOMING.enabled, true, 'siblings survive the merge');
    eq(merged.windows.ANNOUNCEMENT.post_at, '18:30', 'other windows are untouched');
    eq(merged.spacing.max_per_day, 3, 'a second branch is patched too');

    await setPolicy(env, { windows: { DAY_OF: { enabled: true } } }, AT);
    const loaded = await getPolicy(env);
    eq(loaded.windows.DAY_OF.enabled, true, 'the change persists');
    eq(loaded.mode, 'dry', 'and the mode still defaults to dry');
  }

  suite('turning on DAY_OF produces day-of opportunities');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    const policy = mergePolicy(P(), { windows: { DAY_OF: { enabled: true } } });
    await opps.refreshOpportunities(env, policy, { at: AT });
    const id = await eventId('Stuart Card Show', '2026-09-19');
    const ladder = await opps.ladderForEvent(env, id);
    ok(ladder.some((l) => l.kind === 'DAY_OF'), 'a show-day opportunity now exists');
  }

  // ── Console-facing queries ────────────────────────────────────────────────
  suite('unpromoted shows are surfaced');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });
    const un = await opps.unpromotedEvents(env, { at: AT });
    ok(un.length >= 2, `${un.length} upcoming shows have nothing planned yet`);

    const media = await seedMedia(env);
    const evId = await eventId('Stuart Card Show', '2026-09-19');
    const oppId = await opps.opportunityId(evId, 'UPCOMING');
    const id = await items.createEventItem(env, {
      eventId: evId, opportunityId: oppId, kind: 'UPCOMING',
      caption: 'x', hashtags: [], mediaId: media.id, at: AT,
    });
    await opps.markDrafted(env, oppId, id, AT);
    const un2 = await opps.unpromotedEvents(env, { at: AT });
    ok(!un2.some((e) => e.id === evId), 'a show with a draft is no longer listed as unpromoted');
  }

  // ── Video compatibility reporting ─────────────────────────────────────────
  suite('video compatibility reports rather than repairs');
  {
    eq(video.compatibility({ duration_s: 58, width: 1080, height: 1920, vcodec: 'h264', acodec: 'aac', container: 'mp4', has_audio: 1 }).ok,
      true, 'a normal SK short passes');
    const short = video.compatibility({ duration_s: 2, width: 1080, height: 1920, vcodec: 'h264', acodec: 'aac', container: 'mp4', has_audio: 1 });
    eq(short.ok, false, 'a 2s clip is blocked');
    const landscape = video.compatibility({ duration_s: 60, width: 1920, height: 1080, vcodec: 'h264', acodec: 'aac', container: 'mp4', has_audio: 1 });
    eq(landscape.ok, true, 'a landscape long-form is not BLOCKED');
    ok(landscape.warnings.some((w) => w.includes('9:16')), 'but it is warned about');
    const badCodec = video.compatibility({ duration_s: 60, width: 1080, height: 1920, vcodec: 'prores', acodec: 'aac', container: 'mov', has_audio: 1 });
    eq(badCodec.ok, false, 'ProRes is blocked');
  }

  report();
}

main().catch((e) => {
  console.error('suite crashed:', e);
  process.exitCode = 1;
});
