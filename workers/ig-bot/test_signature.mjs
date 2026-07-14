// Verifies the webhook signature check against real HMAC-SHA256 vectors, and that
// the /webhook route actually rejects forgeries end-to-end.
import worker, { verifySignature } from "./worker.js";
import { createHmac } from "node:crypto";

let fails = 0;
const ok = (c, m) => { console.log(`${c ? "  PASS" : "  FAIL"}  ${m}`); if (!c) fails++; };

const SECRET = "test_app_secret_123";
const sign = (body, secret = SECRET) =>
  "sha256=" + createHmac("sha256", secret).update(body).digest("hex");

const BODY = JSON.stringify({
  entry: [{ messaging: [{ sender: { id: "999" }, message: { mid: "m1", text: "hi" } }] }],
});

// ── 1. verifySignature ───────────────────────────────────────────────────────
console.log("\n[1] verifySignature vs node:crypto HMAC vectors");
ok(await verifySignature(BODY, sign(BODY), SECRET), "accepts a correctly signed body");
ok(!(await verifySignature(BODY, sign(BODY, "wrong_secret"), SECRET)), "rejects a signature from the wrong secret");
ok(!(await verifySignature(BODY + " ", sign(BODY), SECRET)), "rejects when the body was tampered with");
ok(!(await verifySignature(BODY, undefined, SECRET)), "rejects a missing header");
ok(!(await verifySignature(BODY, "", SECRET)), "rejects an empty header");
ok(!(await verifySignature(BODY, "sha1=" + sign(BODY).slice(7), SECRET)), "rejects a non-sha256 algo prefix");
ok(!(await verifySignature(BODY, "sha256=", SECRET)), "rejects an empty digest");
ok(!(await verifySignature(BODY, "garbage", SECRET)), "rejects a malformed header");
ok(!(await verifySignature(BODY, sign(BODY), "")), "rejects when no secret is configured");
ok(!(await verifySignature(BODY, "sha256=" + "a".repeat(64), SECRET)), "rejects a wrong same-length digest");
ok(await verifySignature(BODY, sign(BODY).toUpperCase().replace("SHA256", "sha256"), SECRET), "accepts an uppercase hex digest");

// ── 2. the route itself ──────────────────────────────────────────────────────
console.log("\n[2] POST /webhook enforcement");
const KV = () => { const m = new Map(); return { put: async (k, v) => void m.set(k, v), get: async (k) => m.get(k) ?? null, list: async () => ({ keys: [...m.keys()].map((name) => ({ name })) }), _m: m }; };
const post = (body, sig, env) =>
  worker.fetch(new Request("https://x/webhook", {
    method: "POST", body,
    headers: sig ? { "x-hub-signature-256": sig } : {},
  }), env);

let kv = KV();
let res = await post(BODY, sign(BODY), { APP_SECRET: SECRET, QUEUE: kv });
ok(res.status === 200, `signed payload accepted (${res.status})`);
ok(kv._m.size === 1, "…and queued");

kv = KV();
res = await post(BODY, sign(BODY, "attacker_guess"), { APP_SECRET: SECRET, QUEUE: kv });
ok(res.status === 403, `FORGED payload rejected (${res.status})`);
ok(kv._m.size === 0, "…and NOT queued — the forgery never reaches the runner");

kv = KV();
res = await post(BODY, undefined, { APP_SECRET: SECRET, QUEUE: kv });
ok(res.status === 403, `unsigned payload rejected when secret is set (${res.status})`);
ok(kv._m.size === 0, "…and not queued");

// tampering with a validly-signed body
kv = KV();
const evil = BODY.replace('"999"', '"attacker"');
res = await post(evil, sign(BODY), { APP_SECRET: SECRET, QUEUE: kv });
ok(res.status === 403, `body swapped after signing is rejected (${res.status})`);

// back-compat: no APP_SECRET configured = today's behaviour, still accepts
kv = KV();
res = await post(BODY, undefined, { QUEUE: kv });
ok(res.status === 200, `no APP_SECRET => still accepts (no flag day) (${res.status})`);
ok(kv._m.size === 1, "…and still queues, so real DMs keep flowing until the secret is set");

console.log(fails === 0 ? "\nALL PASS\n" : `\n${fails} FAILURE(S)\n`);
process.exit(fails === 0 ? 0 : 1);
