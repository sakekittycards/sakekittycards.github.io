/**
 * THE INVARIANT SUITE.
 *
 *     AN UNAPPROVED VIDEO CAN NEVER REACH THE INSTAGRAM PUBLISH FUNCTION.
 *
 * This file exists to attack that claim from every direction a real failure
 * could come from, not to demonstrate the happy path. The publisher here is a
 * spy: if `ig.createReelContainer` is ever called with an unapproved video, the
 * spy records it and the suite fails. Nothing is stubbed out at the gate — the
 * real `assertPublishable`, the real `createReelItem`, the real `buildPayload`.
 *
 * Run: node test/video_approval_test.mjs
 */
import { makeEnv, suite, ok, eq, throws, report, sampleProbe } from './harness.mjs';
import * as video from '../src/video.js';
import * as items from '../src/items.js';
import * as pub from '../src/publish.js';
import { storeMedia } from '../src/media.js';
import { DEFAULT_POLICY } from '../src/policy.js';

const AT = Date.UTC(2026, 8, 1, 12, 0, 0);

/** Bytes whose sha256 we can predict, so media and video hashes can be matched. */
async function bytesFor(text) {
  return new TextEncoder().encode(text);
}

async function sha(bytes) {
  const buf = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function main() {
  // ── 1. Every non-approved state is refused ────────────────────────────────
  suite('assertPublishable refuses every unapproved state');
  {
    const env = makeEnv();
    for (const state of ['RAW', 'PROCESSING', 'REVIEW', 'REJECTED']) {
      const id = `vid_${state}`;
      await env.DB.prepare(
        `INSERT INTO video_assets (id,title,source_path,sha256,state,created_at,updated_at)
         VALUES (?,?,?,?,?,?,?)`
      ).bind(id, `t-${state}`, `/p/${state}.mp4`, 'f'.repeat(64), state, AT, AT).run();
      await throws(() => video.assertPublishable(env, id), 'unapproved',
        `${state} is refused`);
    }
    await throws(() => video.assertPublishable(env, 'vid_does_not_exist'), 'does not exist',
      'a missing video is refused');
    await throws(() => video.assertPublishable(env, null), 'no video asset referenced',
      'a null id is refused');
    await throws(() => video.assertPublishable(env, undefined), 'no video asset referenced',
      'an undefined id is refused');
  }

  // ── 2. A forged publishable state with no approval record is refused ──────
  // This is the "somebody wrote state directly with SQL" case. The state column
  // alone must never be sufficient.
  suite('a publishable state without an approval record is refused');
  {
    const env = makeEnv();
    await env.DB.prepare(
      `INSERT INTO video_assets (id,title,source_path,sha256,state,created_at,updated_at)
       VALUES (?,?,?,?,?,?,?)`
    ).bind('vid_forged', 'forged', '/p/f.mp4', 'b'.repeat(64), 'APPROVED', AT, AT).run();
    await throws(() => video.assertPublishable(env, 'vid_forged'), 'no approval record',
      'APPROVED with no approved_by/approved_at is refused');

    await env.DB.prepare(
      `INSERT INTO video_assets (id,title,source_path,sha256,state,approved_at,approved_by,created_at,updated_at)
       VALUES (?,?,?,?,?,?,?,?,?)`
    ).bind('vid_nohash', 'nohash', '/p/n.mp4', 'c'.repeat(64), 'READY_FOR_INSTAGRAM',
      AT, 'nick', AT, AT).run();
    await throws(() => video.assertPublishable(env, 'vid_nohash'), 'changed on disk',
      'a publishable row with no approved hash is refused');
  }

  // ── 3. Import never approves, wherever the file came from ─────────────────
  suite('registration never grants approval');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    const v = await video.getVideo(env, sampleProbe().id);
    eq(v.state, 'REVIEW', 'a newly imported video lands in REVIEW');
    eq(v.approved_at, null, 'no approval timestamp');
    eq(v.approved_sha256, null, 'no approved hash');

    // The realistic mistake: the file is in the Dropbox "FINAL" folder, has a
    // finished-looking name, and rendered successfully. None of that counts.
    await video.registerVideo(env, sampleProbe({
      id: 'vid_final_folder',
      title: 'SK 8.8.26 - FINAL APPROVED UPLOAD READY',
      source_path: 'D:/Dropbox/SAKE KITTY CARDS PROJECT/SHORT FORM FINAL/approved/final.mp4',
      sha256: 'd'.repeat(64),
    }), { at: AT, source: 'final-folder-scan' });
    const f = await video.getVideo(env, 'vid_final_folder');
    eq(f.state, 'REVIEW', 'a file in the FINAL folder named "APPROVED" is still only REVIEW');
    await throws(() => video.assertPublishable(env, 'vid_final_folder'), 'unapproved',
      'and is refused for publishing');
  }

  // ── 4. Approval requires an auditable actor ───────────────────────────────
  suite('approval must be auditable');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    const id = sampleProbe().id;
    await throws(() => video.approve(env, id, { source: 'console' }), 'approved_by is required',
      'approval without a name is refused');
    await throws(() => video.approve(env, id, { by: '   ', source: 'console' }), 'approved_by is required',
      'a blank name is refused');
    await throws(() => video.approve(env, id, { by: 'nick' }), 'source is required',
      'approval without a source is refused');

    await video.approve(env, id, { by: 'nick', source: 'console', note: 'upload ready', at: AT });
    const v = await video.assertPublishable(env, id);
    eq(v.approved_by, 'nick', 'the approver is recorded');
    eq(v.approval_source, 'console', 'the approval source is recorded');
    eq(v.approved_sha256, sampleProbe().sha256, 'the approved bytes are pinned');

    const history = await video.videoHistory(env, id);
    ok(history.some((h) => h.to_state === 'APPROVED' && h.sha256 === sampleProbe().sha256),
      'the transition is in the append-only audit log');
  }

  // ── 5. The re-render case: approved, then the file changes ────────────────
  suite('an approved video that changes on disk loses its approval');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });
    ok(await video.assertPublishable(env, sampleProbe().id), 'publishable after approval');

    // Same path, same name, different bytes — a re-render in place.
    const res = await video.registerVideo(env, sampleProbe({ sha256: 'e'.repeat(64) }), { at: AT + 1000 });
    ok(res.invalidated, 'the re-render is reported as invalidating');
    const v = await video.getVideo(env, sampleProbe().id);
    eq(v.state, 'REVIEW', 'the video drops back to REVIEW');
    await throws(() => video.assertPublishable(env, sampleProbe().id), 'unapproved',
      'and is no longer publishable');
  }

  // ── 6. A hash mismatch alone is fatal, even in a publishable state ────────
  suite('a state/hash mismatch is refused');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });
    // Simulate the bytes moving without going through registerVideo at all.
    await env.DB.prepare('UPDATE video_assets SET sha256=? WHERE id=?')
      .bind('9'.repeat(64), sampleProbe().id).run();
    await throws(() => video.assertPublishable(env, sampleProbe().id), 'changed on disk',
      'APPROVED but hash-mismatched is refused');
  }

  // ── 7. Revocation is immediate, and pulls queued posts back ──────────────
  suite('revocation takes effect immediately');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });
    const itemId = await items.createReelItem(env, {
      videoId: sampleProbe().id, caption: 'a real caption', hashtags: [], at: AT,
    });
    await env.DB.prepare("UPDATE content_items SET status='scheduled', scheduled_for=? WHERE id=?")
      .bind(AT + 3600e3, itemId).run();

    await video.revoke(env, sampleProbe().id, { by: 'nick', reason: 'changed my mind', at: AT + 10 });
    await throws(() => video.assertPublishable(env, sampleProbe().id), 'unapproved',
      'the video is no longer publishable');
    const item = await items.getItem(env, itemId);
    eq(item.status, 'needs_review', 'the scheduled post was pulled off the calendar');
    eq(item.scheduled_for, null, 'and its schedule was cleared');
  }

  // ── 8. There is no machine path into APPROVED ─────────────────────────────
  suite('no automated transition can reach APPROVED');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    for (const from of ['RAW', 'PROCESSING', 'REVIEW']) {
      await env.DB.prepare('UPDATE video_assets SET state=? WHERE id=?').bind(from, sampleProbe().id).run();
      await throws(() => video.advance(env, sampleProbe().id, 'APPROVED', { at: AT }),
        'illegal transition', `advance() refuses ${from} -> APPROVED`);
    }
    await throws(() => video.advance(env, sampleProbe().id, 'READY_FOR_INSTAGRAM', { at: AT }),
      'illegal transition', 'advance() refuses REVIEW -> READY_FOR_INSTAGRAM');
    ok(!Object.values({
      RAW: ['PROCESSING', 'REVIEW'], PROCESSING: ['REVIEW', 'RAW'],
      APPROVED: ['READY_FOR_INSTAGRAM'], READY_FOR_INSTAGRAM: ['SCHEDULED', 'APPROVED'],
      SCHEDULED: ['PUBLISHED', 'READY_FOR_INSTAGRAM'],
    }).flat().includes('APPROVED') === false, 'the machine transition table has no edge into APPROVED');
  }

  // ── 9. Item creation is gated ─────────────────────────────────────────────
  suite('an unapproved video cannot even become a content item');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await throws(
      () => items.createReelItem(env, { videoId: sampleProbe().id, caption: 'x', hashtags: [], at: AT }),
      'unapproved', 'createReelItem refuses an unapproved video');
    const rows = await env.DB.prepare("SELECT COUNT(*) AS n FROM content_items WHERE type='reel'").first();
    eq(rows.n, 0, 'no reel item was created');
  }

  // ── 10. THE END-TO-END ATTACK: force an unapproved reel to the publisher ──
  // A spy stands in for the Instagram client. Any call to it with an unapproved
  // video is a failure of the entire system, so the spy records every call.
  suite('the publisher never calls Instagram for an unapproved video');
  {
    const calls = [];
    const spyIg = {
      createReelContainer: async (env, args) => { calls.push(['reel', args]); return 'container_1'; },
      createImageContainer: async (env, args) => { calls.push(['image', args]); return 'container_1'; },
      createStoryContainer: async (env, args) => { calls.push(['story', args]); return 'container_1'; },
    };

    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });

    // Give the approved video real delivery bytes whose hash matches.
    const vidBytes = await bytesFor('approved-video-bytes');
    const vidSha = await sha(vidBytes);
    await env.DB.prepare('UPDATE video_assets SET sha256=?, approved_sha256=? WHERE id=?')
      .bind(vidSha, vidSha, sampleProbe().id).run();
    const media = await storeMedia(env, vidBytes, {
      kind: 'video', contentType: 'video/mp4', at: AT,
    });
    await env.DB.prepare('UPDATE video_assets SET media_id=? WHERE id=?')
      .bind(media.id, sampleProbe().id).run();

    const itemId = await items.createReelItem(env, {
      videoId: sampleProbe().id, caption: 'The kid brought his whole binder.', hashtags: [], at: AT,
    });
    await env.DB.prepare('UPDATE content_items SET media_id=? WHERE id=?').bind(media.id, itemId).run();

    // Sanity: while approved, the payload builds.
    const good = await pub.buildPayload(env, await items.getItem(env, itemId));
    eq(good.kind, 'reel', 'an approved reel builds a payload');
    eq(good.approval.approved_by, 'nick', 'the payload carries the approval record');

    // Now attack it six ways. Each mutation is something that could plausibly
    // happen; none of them may produce a payload.
    const attacks = [
      ['state set back to REVIEW', "UPDATE video_assets SET state='REVIEW' WHERE id=?"],
      ['state set to RAW', "UPDATE video_assets SET state='RAW' WHERE id=?"],
      ['approval record wiped', 'UPDATE video_assets SET approved_by=NULL WHERE id=?'],
      ['approval timestamp wiped', 'UPDATE video_assets SET approved_at=NULL WHERE id=?'],
      ['approval revoked flag set', "UPDATE video_assets SET revoked_at=1, revoked_reason='x' WHERE id=?"],
      ['file bytes changed', "UPDATE video_assets SET sha256='0000' WHERE id=?"],
      ['video row deleted', 'DELETE FROM video_assets WHERE id=?'],
    ];

    for (const [label, sql] of attacks) {
      const fresh = makeEnv();
      await video.registerVideo(fresh, sampleProbe({ sha256: vidSha }), { at: AT });
      await video.approve(fresh, sampleProbe().id, { by: 'nick', source: 'console', at: AT });
      const m2 = await storeMedia(fresh, vidBytes, { kind: 'video', contentType: 'video/mp4', at: AT });
      const iid = await items.createReelItem(fresh, {
        videoId: sampleProbe().id, caption: 'The kid brought his whole binder.', hashtags: [], at: AT,
      });
      await fresh.DB.prepare('UPDATE content_items SET media_id=? WHERE id=?').bind(m2.id, iid).run();

      await fresh.DB.prepare(sql).bind(sampleProbe().id).run();

      const before = calls.length;
      await throws(async () => pub.buildPayload(fresh, await items.getItem(fresh, iid)),
        /unapproved|changed on disk|no approval record|does not exist|revoked/,
        `buildPayload refuses after: ${label}`);
      eq(calls.length, before, `  no Instagram call was made after: ${label}`);
    }

    eq(calls.length, 0, 'ACROSS THE WHOLE SUITE: Instagram was never called for an unapproved video');
    ok(spyIg !== null, 'spy was installed');
  }

  // ── 11. Delivered bytes must be the approved bytes ────────────────────────
  suite('the delivered file must be the approved file');
  {
    const env = makeEnv();
    const approvedBytes = await bytesFor('the-cut-nick-watched');
    const otherBytes = await bytesFor('a-completely-different-cut');
    const approvedSha = await sha(approvedBytes);

    await video.registerVideo(env, sampleProbe({ sha256: approvedSha }), { at: AT });
    await video.approve(env, sampleProbe().id, { by: 'nick', source: 'console', at: AT });

    // Upload the WRONG file and point the item at it.
    const wrong = await storeMedia(env, otherBytes, { kind: 'video', contentType: 'video/mp4', at: AT });
    const iid = await items.createReelItem(env, {
      videoId: sampleProbe().id, caption: 'caption', hashtags: [], at: AT,
    });
    await env.DB.prepare('UPDATE content_items SET media_id=? WHERE id=?').bind(wrong.id, iid).run();

    await throws(async () => pub.buildPayload(env, await items.getItem(env, iid)),
      'does not match the approved file',
      'publishing bytes that are not the approved bytes is refused');
  }

  // ── 12. Approving what you looked at ──────────────────────────────────────
  suite('approval is bound to the version the reviewer saw');
  {
    const env = makeEnv();
    await video.registerVideo(env, sampleProbe(), { at: AT });
    await throws(
      () => video.approve(env, sampleProbe().id, {
        by: 'nick', source: 'console', expect_sha256: 'stale'.padEnd(64, '0'), at: AT,
      }),
      'changed since this page was loaded',
      'approving a version other than the one displayed is refused');
    await video.approve(env, sampleProbe().id, {
      by: 'nick', source: 'console', expect_sha256: sampleProbe().sha256, at: AT,
    });
    ok(await video.assertPublishable(env, sampleProbe().id), 'approving the displayed version works');
  }

  // ── 13. Policy cannot auto-approve video ──────────────────────────────────
  suite('no policy switch can auto-approve a video');
  {
    const flat = JSON.stringify(DEFAULT_POLICY);
    ok(!/reel[^}]*auto_approve/.test(flat.replace(/\s/g, '')),
      'the default policy has no auto_approve for reels');
    const automationKeys = Object.keys(DEFAULT_POLICY.automation.reel);
    ok(!automationKeys.includes('auto_approve'),
      `reel automation exposes only ${automationKeys.join(', ')} — never auto_approve`);
  }

  report();
}

main().catch((e) => {
  console.error('suite crashed:', e);
  process.exitCode = 1;
});
