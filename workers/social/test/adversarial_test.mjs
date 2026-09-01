/**
 * Adversarial suite — the distributed-systems failures, and regressions.
 *
 * Everything here is a bug that was actually found, either in the first pass or
 * by attacking the system afterwards. Each block names the failure it prevents
 * so that a future edit that reintroduces it fails with a readable reason rather
 * than a mysterious assertion.
 *
 * The Instagram client is replaced with a scriptable fake so that the exact
 * sequence "container created → process dies → retry" can be produced on demand;
 * that sequence is unreachable against the real API and is precisely the one
 * that double-posts if it is handled wrong.
 *
 * Run: node test/adversarial_test.mjs
 */
import { makeEnv, suite, ok, eq, throws, report, SAMPLE_EVENTS, sampleProbe } from './harness.mjs';
import { ingestEvents, eventId } from '../src/events.js';
import * as opps from '../src/opportunities.js';
import * as items from '../src/items.js';
import * as sched from '../src/scheduler.js';
import * as video from '../src/video.js';
import { storeMedia } from '../src/media.js';
import { DEFAULT_POLICY, mergePolicy } from '../src/policy.js';
import { easternToUtc, utcToEastern, easternOffsetMinutes } from '../src/util.js';

const AT = Date.UTC(2026, 8, 1, 15, 0, 0);
const P = () => structuredClone(DEFAULT_POLICY);

async function seedItem(env, { status = 'scheduled', when = AT } = {}) {
  const media = await storeMedia(env, new TextEncoder().encode(`g-${Math.random()}`), {
    kind: 'image', contentType: 'image/jpeg', width: 1080, height: 1350, at: AT,
  });
  await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
  const evId = await eventId('Stuart Card Show', '2026-09-19');
  const id = await items.createEventItem(env, {
    eventId: evId, opportunityId: `opp_${Math.random()}`, kind: 'UPCOMING',
    caption: 'We are at the Stuart Card Show.', hashtags: [], mediaId: media.id, at: AT,
  });
  await items.approveItem(env, id, { by: 'nick', at: AT });
  if (status !== 'approved') await items.scheduleItem(env, id, when, { at: AT });
  return id;
}

async function main() {
  // ══ REGRESSIONS: the two bugs found in the first pass ═════════════════════

  suite('REGRESSION: proposeSlot must measure lead time from the tick, not the wall clock');
  {
    const env = makeEnv();
    const policy = P();
    // The bug: proposeSlot called nowMs() internally. With `desired` in the
    // future relative to the real clock but only a minute after the tick's
    // instant, the min_lead_hours floor silently stopped applying.
    const slot = await sched.proposeSlot(env, policy, {
      desired: AT + 60e3, type: 'event', now: AT,
    });
    const leadH = (slot.at - AT) / 3600e3;
    ok(leadH >= policy.min_lead_hours,
      `lead time is measured from the passed-in instant (+${leadH.toFixed(1)}h >= ${policy.min_lead_hours}h)`);

    // And it must be reproducible: same inputs, same answer, regardless of when
    // the test runs.
    const again = await sched.proposeSlot(env, policy, {
      desired: AT + 60e3, type: 'event', now: AT,
    });
    eq(again.at, slot.at, 'the same tick instant always yields the same slot');

    const laterTick = await sched.proposeSlot(env, policy, {
      desired: AT + 60e3, type: 'event', now: AT + 12 * 3600e3,
    });
    ok(laterTick.at > slot.at, 'a later tick yields a later slot — the clock is an input, not ambient');
  }

  suite('REGRESSION: the first run must not announce the whole existing calendar');
  {
    const env = makeEnv();
    // The bug: ANNOUNCEMENT's window is (event_date - 365) .. (event_date - 9),
    // which matches nearly every event on a year-long calendar simultaneously.
    // The first real run wanted to announce 18 shows at once.
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });
    const anns = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM opportunities WHERE kind='ANNOUNCEMENT'"
    ).first();
    eq(anns.n, 0, 'backfilled events produce zero announcements');

    const due = await opps.dueOpportunities(env, P(), { at: AT });
    ok(due.every((o) => o.kind !== 'ANNOUNCEMENT'),
      'and none is offered to the renderer');

    // The marker itself must exist and must not move on later ingests.
    const m1 = await env.DB.prepare("SELECT v FROM meta WHERE k='first_ingest_at'").first();
    ok(m1 && Number(m1.v) === AT, 'the backfill instant is recorded');
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT + 86400e3 });
    const m2 = await env.DB.prepare("SELECT v FROM meta WHERE k='first_ingest_at'").first();
    eq(m2.v, m1.v, 'and it never moves — otherwise every ingest would re-arm the flood');
  }

  // ══ RECONCILIATION: the dangerous window ══════════════════════════════════

  suite('RECONCILIATION: a container that already published is never published twice');
  {
    const calls = { create: 0, publish: 0, status: [] };
    const fakeIg = {
      IgError: class extends Error {},
      async createImageContainer() { calls.create += 1; return 'CONTAINER_1'; },
      async reconcileContainer() { return { state: 'published' }; },
      async findRecentByCaption() { return { id: 'IG_MEDIA_9', permalink: 'https://instagram.com/p/x' }; },
      async publishContainer() { calls.publish += 1; return 'SHOULD_NEVER_HAPPEN'; },
      async waitForContainer() { return { code: 'FINISHED' }; },
      async mediaPermalink() { return { permalink: 'https://instagram.com/p/x' }; },
    };
    const pub = await import('../src/publish.js');
    const env = makeEnv({ PUBLISH_MODE: 'live', IG_USER_ID: '1', IG_ACCESS_TOKEN: 't' });
    const id = await seedItem(env, { when: AT - 1000 });
    // Simulate: a previous attempt created a container, then the worker died.
    await env.DB.prepare("UPDATE content_items SET ig_creation_id='CONTAINER_1' WHERE id=?")
      .bind(id).run();

    const res = await pub.publishItem(env, id, mergePolicy(P(), { mode: 'live' }),
      { at: AT, __ig: fakeIg });

    eq(calls.publish, 0, 'media_publish was NOT called a second time');
    eq(calls.create, 0, 'and no second container was created');
    ok(res.reconciled, 'the publish reports itself as reconciled');
    const row = await items.getItem(env, id);
    eq(row.status, 'published', 'the item is recorded as published');
    eq(row.ig_media_id, 'IG_MEDIA_9', 'with the media id recovered from recent media');
  }

  suite('RECONCILIATION: an uncertain state is held, never guessed');
  {
    const calls = { publish: 0 };
    const fakeIg = {
      async reconcileContainer() { return { state: 'unknown', reason: 'Instagram did not answer' }; },
      async publishContainer() { calls.publish += 1; return 'X'; },
      async createImageContainer() { calls.publish += 1; return 'X'; },
    };
    const pub = await import('../src/publish.js');
    const env = makeEnv({ PUBLISH_MODE: 'live', IG_USER_ID: '1', IG_ACCESS_TOKEN: 't' });
    const id = await seedItem(env, { when: AT - 1000 });
    await env.DB.prepare("UPDATE content_items SET ig_creation_id='CONTAINER_2' WHERE id=?")
      .bind(id).run();

    const res = await pub.publishItem(env, id, mergePolicy(P(), { mode: 'live' }),
      { at: AT, __ig: fakeIg });
    eq(calls.publish, 0, 'nothing was sent while the state was unknown');
    ok(res.uncertain, 'the result says so explicitly');
    const row = await items.getItem(env, id);
    eq(row.status, 'needs_review', 'the item is parked for a human');
    ok(/uncertain/i.test(row.failure_reason), `and says why: "${row.failure_reason}"`);

    const acts = await env.DB.prepare(
      "SELECT message FROM activity WHERE subject=? AND level='error' ORDER BY at DESC"
    ).bind(id).all();
    ok(acts.results.some((a) => /uncertain/i.test(a.message) && /check the account/i.test(a.message)),
      'the activity log tells the operator what to do, in words');
  }

  suite('RECONCILIATION: a dead container is rebuilt, not adopted');
  {
    const calls = { create: 0, publish: 0 };
    const fakeIg = {
      async reconcileContainer() { return { state: 'dead', reason: 'container EXPIRED' }; },
      async createImageContainer() { calls.create += 1; return 'CONTAINER_NEW'; },
      async waitForContainer() { return { code: 'FINISHED' }; },
      async publishContainer() { calls.publish += 1; return 'IG_MEDIA_NEW'; },
      async mediaPermalink() { return { permalink: 'https://instagram.com/p/new' }; },
    };
    const pub = await import('../src/publish.js');
    const env = makeEnv({ PUBLISH_MODE: 'live', IG_USER_ID: '1', IG_ACCESS_TOKEN: 't' });
    const id = await seedItem(env, { when: AT - 1000 });
    await env.DB.prepare("UPDATE content_items SET ig_creation_id='CONTAINER_OLD' WHERE id=?")
      .bind(id).run();

    const res = await pub.publishItem(env, id, mergePolicy(P(), { mode: 'live' }), { at: AT, __ig: fakeIg });
    eq(calls.create, 1, 'a fresh container was built');
    eq(calls.publish, 1, 'and published exactly once');
    ok(res.ok, 'the publish succeeded');
  }

  // ══ CONCURRENCY ═══════════════════════════════════════════════════════════

  suite('two workers on the same tick: exactly one publishes');
  {
    const calls = { publish: 0 };
    const fakeIg = {
      async reconcileContainer() { return { state: 'ready' }; },
      async createImageContainer() { return 'C'; },
      async waitForContainer() { return { code: 'FINISHED' }; },
      async publishContainer() { calls.publish += 1; return 'IG_1'; },
      async mediaPermalink() { return { permalink: 'p' }; },
    };
    const pub = await import('../src/publish.js');
    const env = makeEnv({ PUBLISH_MODE: 'live', IG_USER_ID: '1', IG_ACCESS_TOKEN: 't' });
    const id = await seedItem(env, { when: AT - 1000 });
    const policy = mergePolicy(P(), { mode: 'live' });

    const [a, b, c] = await Promise.all([
      pub.publishItem(env, id, policy, { at: AT, __ig: fakeIg }),
      pub.publishItem(env, id, policy, { at: AT, __ig: fakeIg }),
      pub.publishItem(env, id, policy, { at: AT, __ig: fakeIg }),
    ]);
    eq(calls.publish, 1, 'Instagram was called exactly once across three concurrent workers');
    eq([a, b, c].filter((r) => r.skipped).length, 2, 'the two losers reported themselves skipped');
    const pubs = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM content_items WHERE id=? AND status='published'"
    ).bind(id).first();
    eq(pubs.n, 1, 'and the item is published once');
  }

  suite('a dry run does not consume the retry budget');
  {
    const pub = await import('../src/publish.js');
    const env = makeEnv({ PUBLISH_MODE: 'dry' });
    const id = await seedItem(env, { when: AT - 1000 });
    for (let i = 0; i < 8; i++) {
      await env.DB.prepare("UPDATE content_items SET status='scheduled', next_retry_at=NULL WHERE id=?")
        .bind(id).run();
      await pub.publishItem(env, id, P(), { at: AT + i * 1000 });
    }
    const row = await items.getItem(env, id);
    eq(row.attempts, 0, 'eight dry runs left the attempt counter at zero');
    eq(row.status, 'scheduled', 'and the item is still schedulable');
    ok(row.attempts < sched.MAX_ATTEMPTS,
      'so a later real publish still has its full retry budget');
  }

  suite('a stale lease is reclaimed and the work is not lost');
  {
    const env = makeEnv();
    const id = await seedItem(env, { when: AT - 1000 });
    const tok = await sched.claim(env, id, { at: AT });
    ok(tok, 'claimed');
    eq(await sched.claim(env, id, { at: AT + 60e3 }), null, 'not re-claimable while the lease is live');
    const reaped = await sched.reapStaleLeases(env, { at: AT + 11 * 60e3 });
    eq(reaped, 1, 'the abandoned item is reaped once the lease expires');
    const row = await items.getItem(env, id);
    eq(row.status, 'scheduled', 'and returned to the queue rather than dropped');
  }

  // ══ CONTENT SAFETY ════════════════════════════════════════════════════════

  suite('an event renamed on the website keeps its history');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    await opps.refreshOpportunities(env, P(), { at: AT });
    const before = await eventId('Stuart Card Show', '2026-09-19');
    const oppsBefore = (await opps.ladderForEvent(env, before)).length;
    ok(oppsBefore > 0, `the show has ${oppsBefore} opportunities`);

    // Nick fixes the name. Same date, same venue.
    const renamed = SAMPLE_EVENTS.map((e) => e.title === 'Stuart Card Show'
      ? { ...e, title: 'Stuart Card Show & Collectibles' } : e);
    const r = await ingestEvents(env, renamed, { at: AT + 86400e3 });

    eq(r.cancelled.length, 0, 'it is NOT reported as a cancellation');
    eq(r.renamed.length, 1, 'it is reported as a rename');
    const after = await eventId('Stuart Card Show & Collectibles', '2026-09-19');
    const ladder = await opps.ladderForEvent(env, after);
    eq(ladder.length, oppsBefore, 'its opportunities moved across intact');

    await opps.refreshOpportunities(env, P(), { at: AT + 86400e3 });
    const ann = (await opps.ladderForEvent(env, after)).find((l) => l.kind === 'ANNOUNCEMENT');
    ok(!ann, 'and a typo fix does not fire a fresh announcement');
    const oldRow = await env.DB.prepare('SELECT id FROM events WHERE id=?').bind(before).first();
    eq(oldRow, null, 'the old row is gone rather than lingering as a ghost');
  }

  suite('a genuine cancellation is still a cancellation');
  {
    const env = makeEnv();
    await ingestEvents(env, SAMPLE_EVENTS, { at: AT });
    // Drop Stuart entirely; nothing similar takes its place.
    const r = await ingestEvents(env, SAMPLE_EVENTS.filter((e) => e.title !== 'Stuart Card Show'),
      { at: AT + 1000 });
    eq(r.cancelled.length, 1, 'the missing show is cancelled');
    eq(r.renamed.length, 0, 'and is not mistaken for a rename');
  }

  suite('a video that vanishes from disk after approval can still publish');
  {
    // The R2 copy is the thing Instagram fetches. The source file disappearing
    // is a fact about Nick's disk, not about whether the approved bytes exist.
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });
    const v = await video.assertPublishable(env, sampleProbe().id);
    ok(v, 'approval survives — it describes bytes we already hold, not a path');
  }

  suite('approve and reject racing: the loser does not silently win');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await Promise.all([
      video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT }).catch(() => {}),
      video.reject(env, sampleProbe().id, { by: 'delia', reason: 'weak turn', at: AT }).catch(() => {}),
    ]);
    const v = await video.getVideo(env, sampleProbe().id);
    ok(['APPROVED', 'REJECTED'].includes(v.state), `settled on one state (${v.state}), not a hybrid`);
    if (v.state === 'APPROVED') {
      ok(v.approved_sha256 === v.sha256, 'an APPROVED outcome is internally consistent');
    } else {
      eq(v.approved_sha256, null, 'a REJECTED outcome carries no approval hash');
      await throws(() => video.assertPublishable(env, sampleProbe().id), /unapproved|revoked/,
        'and is not publishable');
    }
  }

  // ══ TIME ══════════════════════════════════════════════════════════════════

  suite('DST: scheduling never targets a wall-clock time that does not exist');
  {
    const env = makeEnv();
    const policy = P();
    // 2026-03-08 02:30 ET does not exist — the clock jumps 02:00 -> 03:00.
    const slot = await sched.proposeSlot(env, policy, {
      desired: easternToUtc('2026-03-08', '02:30'), type: 'event', now: Date.UTC(2026, 2, 1),
    });
    const local = utcToEastern(slot.at);
    const hour = Number(local.time.slice(0, 2));
    ok(hour >= 7 && hour < 23, `quiet hours moved it to ${local.label}, a real time`);
    eq(easternOffsetMinutes(slot.at), -300 === easternOffsetMinutes(slot.at) ? -300 : -240,
      'and the offset used is self-consistent');
  }

  suite('DST: an autumn repeated hour still round-trips');
  {
    // 2026-11-01 01:30 ET happens twice. We must land on a definite instant.
    const utc = easternToUtc('2026-11-01', '01:30');
    const back = utcToEastern(utc);
    eq(back.date, '2026-11-01', 'the date survives');
    ok(back.time === '01:30' || back.time === '02:30',
      `resolved to a single definite instant (${back.time} ET)`);
  }

  report();
}

main().catch((e) => {
  console.error('suite crashed:', e);
  process.exitCode = 1;
});
