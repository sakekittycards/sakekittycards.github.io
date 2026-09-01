/**
 * Test harness.
 *
 * D1 is backed by a real in-process SQLite (`node:sqlite`), not a mock. That
 * matters more than it sounds: the two guarantees this suite exists to prove —
 * the publish lease and container idempotency — are both properties of a
 * conditional UPDATE's `changes` count. A hand-written fake would return
 * whatever we told it to and would prove nothing at all.
 */
import { DatabaseSync } from 'node:sqlite';
import { SCHEMA_DDL } from '../src/schema.js';

export function makeD1() {
  const db = new DatabaseSync(':memory:');
  for (const ddl of SCHEMA_DDL) db.exec(ddl);
  return {
    _db: db,
    prepare(sql) {
      let stmt;
      let bound = [];
      const self = {
        bind(...args) { bound = args; return self; },
        async run() {
          stmt = stmt || db.prepare(sql);
          const r = stmt.run(...bound.map(coerce));
          return { success: true, meta: { changes: r.changes, last_row_id: Number(r.lastInsertRowid) } };
        },
        async first() {
          stmt = stmt || db.prepare(sql);
          const r = stmt.get(...bound.map(coerce));
          return r === undefined ? null : { ...r };
        },
        async all() {
          stmt = stmt || db.prepare(sql);
          return { results: stmt.all(...bound.map(coerce)).map((r) => ({ ...r })), success: true };
        },
      };
      return self;
    },
  };
}

function coerce(v) {
  if (v === undefined) return null;
  if (typeof v === 'boolean') return v ? 1 : 0;
  return v;
}

/** In-memory R2. Only the surface the worker actually uses. */
export function makeR2() {
  const store = new Map();
  return {
    async put(key, bytes) { store.set(key, new Uint8Array(bytes)); return { key }; },
    async get(key, opts) {
      const v = store.get(key);
      if (!v) return null;
      if (opts && opts.range) {
        const { offset = 0, length = v.byteLength - offset } = opts.range;
        return { body: v.slice(offset, offset + length), range: { offset, length } };
      }
      return { body: v };
    },
    async delete(key) { store.delete(key); },
    _store: store,
  };
}

export function makeEnv(overrides = {}) {
  return {
    DB: makeD1(),
    MEDIA: makeR2(),
    ADMIN_TOKEN: 'test-admin-token',
    PUBLIC_BASE: 'https://social.example.test',
    PUBLISH_MODE: 'dry',
    ...overrides,
  };
}

// ── A tiny assertion kit, matching the house style in tcgenie's tests ────────
let passed = 0;
let failed = 0;
const failures = [];
let currentSuite = '';

export function suite(name) {
  currentSuite = name;
  console.log(`\n── ${name} ${'─'.repeat(Math.max(2, 64 - name.length))}`);
}

export function ok(cond, label) {
  if (cond) {
    passed += 1;
    console.log(`  pass  ${label}`);
  } else {
    failed += 1;
    failures.push(`${currentSuite} / ${label}`);
    console.log(`  FAIL  ${label}`);
  }
}

export function eq(actual, expected, label) {
  const same = JSON.stringify(actual) === JSON.stringify(expected);
  ok(same, same ? label : `${label} (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`);
}

/** Assert that `fn` throws, and that the message or code matches `match`. */
export async function throws(fn, match, label) {
  try {
    await fn();
    ok(false, `${label} — expected a throw, got none`);
    return null;
  } catch (e) {
    const hay = `${e.code || ''} ${e.message || ''}`;
    const hit = match instanceof RegExp ? match.test(hay) : hay.includes(match);
    ok(hit, hit ? label : `${label} — threw "${e.message}" (code ${e.code}), expected /${match}/`);
    return e;
  }
}

export function report() {
  console.log(`\n${'='.repeat(70)}`);
  console.log(`pass: ${passed}   fail: ${failed}`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
  }
  console.log('='.repeat(70));
  if (failed) process.exitCode = 1;
  return { passed, failed };
}

// ── Fixtures ────────────────────────────────────────────────────────────────
export const SAMPLE_EVENTS = [
  {
    title: 'Stuart Card Show', venue: 'The Flagler', address: '201 SW Flagler Ave',
    city: 'Stuart', state: 'FL', event_date: '2026-09-19', hours_text: '10am–5pm',
    start_time: '10:00', end_time: '17:00', kind: 'show',
  },
  {
    title: 'SWFL Super Card Show X2', venue: 'Lee Civic Center',
    address: '11831 Bayshore Road', city: 'North Fort Myers', state: 'FL',
    event_date: '2026-09-11', end_date: '2026-09-13',
    hours_text: 'Fri 5pm setup · Sat 10am–6pm · Sun 10am–5pm', kind: 'show',
  },
  {
    title: '👀 Secret Show — Stay Tuned', venue: '', city: '', state: 'FL',
    event_date: '2026-10-17', masked: true, reveal_at: '2026-10-01', kind: 'show',
  },
  {
    title: 'Whatnot Stream', venue: 'Online', city: '', state: '',
    event_date: '2026-09-08', kind: 'online',
  },
];

export function sampleProbe(over = {}) {
  return {
    id: 'vid_test0000000000001',
    title: 'SK 5.17.26 - The Kid\'s Binder',
    source_path: 'D:/Dropbox/SAKE KITTY CARDS PROJECT/SHORT FORM FINAL/SK 5.17.26 - The Kid\'s Binder.mp4',
    sha256: 'a'.repeat(64),
    bytes: 88598387,
    duration_s: 58.4,
    width: 1080, height: 1920, fps: 29.97,
    vcodec: 'h264', acodec: 'aac', container: 'mp4', has_audio: true,
    ...over,
  };
}
