/**
 * Run every suite and exit non-zero if anything failed.
 *
 *   node workers/social/test/run_all.mjs
 *
 * The suites run as separate processes on purpose: each one builds its own
 * in-memory database and its own module state, and a shared process would let
 * one suite's leftovers make another one pass.
 */
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));

const SUITES = [
  ['video_approval_test.mjs', 'the invariant: an unapproved video can never reach publish'],
  ['engine_test.mjs', 'ingestion, opportunities, scheduling, idempotency, dry run'],
  ['adversarial_test.mjs', 'reconciliation, concurrency, renames, DST, and both first-pass regressions'],
];

let total = 0;
let failed = 0;
const results = [];

for (const [file, description] of SUITES) {
  const r = spawnSync(process.execPath, [join(HERE, file)], { encoding: 'utf8' });
  const out = (r.stdout || '') + (r.stderr || '');
  const m = /pass:\s*(\d+)\s+fail:\s*(\d+)/.exec(out);
  const pass = m ? Number(m[1]) : 0;
  const fail = m ? Number(m[2]) : -1;
  total += pass;
  failed += Math.max(fail, 0);

  if (r.status !== 0 || fail !== 0) {
    console.log(out);
  }
  results.push({ file, description, pass, fail, status: r.status });
}

console.log('\n' + '='.repeat(74));
for (const r of results) {
  const state = r.fail === 0 && r.status === 0 ? 'PASS' : 'FAIL';
  console.log(`${state}  ${String(r.pass).padStart(4)} checks  ${r.file}`);
  console.log(`             ${r.description}`);
}
console.log('-'.repeat(74));
console.log(`${total} checks, ${failed} failed`);
console.log('='.repeat(74));

process.exit(failed === 0 && results.every((r) => r.status === 0) ? 0 : 1);
