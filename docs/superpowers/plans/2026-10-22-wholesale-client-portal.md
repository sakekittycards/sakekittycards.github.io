# Wholesale Client Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the secret-URL wholesale price list and the fire-and-forget order email with an application-gated portal where approved buyers order from a database-backed catalogue and watch a seven-stage order move, and where Nick and Andrew work those orders from their phones under an attributable audit log.

**Architecture:** One Cloudflare Worker serving server-rendered HTML from D1, in the shape of `workers/social/` (plain JS ESM, schema DDL exported as an array so `node:sqlite` can build a real database in tests) and the auth shape of `sake-kitty-vendor-portal` (opaque session ids in D1 behind an HMAC-signed cookie, magic link first, optional username+password after). The cart stays client-side in `localStorage`; the server re-prices every line from D1 at submit and reads nothing the client said about money.

**Tech Stack:** Cloudflare Workers · D1 (SQLite) · Resend · vanilla JS ESM, no build step · `node:sqlite` for tests

**Spec:** `docs/superpowers/specs/2026-10-22-wholesale-client-portal.md`

## Global Constraints

- Worker lives at `workers/wholesale-portal/`. Worker name `sake-kitty-wholesale`, D1 binding `DB`, database `sake-kitty-wholesale`, custom domain `wholesale.sakekittycards.com`.
- JavaScript ESM only. No TypeScript, no bundler, no build step.
- **All money is integer cents.** No floats anywhere in a price path.
- **MOQ is 150000 cents ($1,500) before shipping**, enforced server-side.
- Catalogue price rule: `cost_cents / 0.93`, rounded up to the whole dollar. Cost is admin-only and never rendered to a buyer.
- Order refs keep the existing format `WS-YYYYMMDD-XXX`, 3 chars from the alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`.
- Stages, in order: `submitted`, `checking_stock`, `quoted`, `awaiting_payment`, `paid`, `shipped`, `delivered`; plus terminal `cancelled`.
- Every page the worker serves sends `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet`.
- Every state-changing admin route writes exactly one `audit_log` row carrying the actor's name and the old and new values.
- Admin credentials are two distinct secrets, `ADMIN_PASSWORD` (Nick) and `ADMIN_PASSWORD_ANDREW` (Andrew), mapped to labels `Nick` and `Andrew`.
- `wholesale-pokemon.html` must never link to `wholesale.html`.
- No supplier cost, margin, or buyer contact detail is committed to this repo.
- Tests run with `node workers/wholesale-portal/test/run_all.mjs` and print `pass: N fail: N`.

## Review Focus

1. **A tampered cart.** A buyer edits the posted JSON to say a case costs $1. The server must price from `products` and ignore every price the client sent. — Task 7
2. **The catalogue moved underneath an open cart.** A product goes `out`, inactive, or changes price between page load and submit. The order must reject the dead line and price the rest at the current number, not the stale one. — Task 7
3. **MOQ bypassed by posting directly.** The dock blocks it in the UI; a direct `POST /orders` under 150000 cents must be refused too. — Task 7
4. **One buyer loading another's order.** `WS-YYYYMMDD-XXX` has only 32³ possibilities. Order reads must be scoped by session buyer id, so a correct guess still 404s. — Task 8
5. **A double tap on bad signal.** Two `POST /admin/orders/:ref/stage` for the same transition must advance once and log once; a backwards stage must be refused. — Task 9

---

### Task 1: Worker skeleton, schema, and test harness

**Files:**
- Create: `workers/wholesale-portal/wrangler.toml`, `package.json`, `.dev.vars.example`, `src/index.js`, `src/schema.js`, `src/util.js`
- Create: `workers/wholesale-portal/test/harness.mjs`, `test/run_all.mjs`, `test/util_test.mjs`

**Interfaces:**
- Consumes: nothing
- Produces: `SCHEMA_DDL: string[]` from `src/schema.js`; `randomId(n): string`, `sha256Hex(s): Promise<string>`, `hmacSign(secret, msg): Promise<string>`, `esc(s): string`, `money(cents): string`, `orderRef(date?): string` from `src/util.js`; `makeD1()`, `makeEnv(overrides)`, `makeResend()` from `test/harness.mjs`

- [ ] **Step 1: Write the failing tests** in `test/util_test.mjs`

```js
test('money renders cents as whole-dollar USD', () => {
  assertEqual(money(61300), '$613');
  assertEqual(money(0), '$0');
});
test('orderRef matches the existing WS format', () => {
  assertMatch(orderRef(new Date('2026-10-22T00:00:00Z')), /^WS-20261022-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{3}$/);
});
test('esc neutralises angle brackets and quotes', () => {
  assertEqual(esc('<a href="x">'), '&lt;a href=&quot;x&quot;&gt;');
});
test('every table in SCHEMA_DDL creates cleanly in sqlite', () => {
  const db = makeD1();
  assertEqual(db._db.prepare("SELECT count(*) n FROM sqlite_master WHERE type='table'").get().n, 8);
});
```

- [ ] **Step 2: Run to verify it fails** — `node workers/wholesale-portal/test/util_test.mjs`, expect failure on the missing module.

- [ ] **Step 3: Write `src/schema.js`** — `SCHEMA_DDL` as one `CREATE TABLE` string per element, eight tables: `buyers`, `products`, `orders`, `order_items`, `order_events`, `magic_tokens`, `sessions`, `audit_log`. Columns per the spec's data model. All money columns are `INTEGER` named `*_cents`. `buyers.email` is `TEXT NOT NULL UNIQUE COLLATE NOCASE`; `orders.ref` is `TEXT NOT NULL UNIQUE`; `products.id` is `TEXT PRIMARY KEY` so the existing CATALOG ids carry over.

- [ ] **Step 4: Write `src/util.js`** — port `randomId`, `sha256Hex`, `hmacSign`, `esc` from `sake-kitty-vendor-portal/src/util.ts`, converted to JS. `orderRef` ports `_skOrderRef` from `tcgenie/src/index.js:4852`.

- [ ] **Step 5: Write `test/harness.mjs`** — copy the `makeD1()` adapter from `workers/social/test/harness.mjs` on the `social-engine` branch verbatim; it already backs D1 with `node:sqlite`. `makeResend()` records `{to, subject, html}` into an array instead of sending. `makeEnv()` returns `{DB, COOKIE_SECRET:'test-cookie-secret', MAGIC_LINK_SECRET:'test-magic-secret', ADMIN_PASSWORD:'nick-pw', ADMIN_PASSWORD_ANDREW:'andrew-pw', SITE_URL:'https://wholesale.test', _mail}`.

- [ ] **Step 6: Write `test/run_all.mjs`** — same spawn-per-suite shape as `workers/social/test/run_all.mjs`, suite list starting with `util_test.mjs`.

- [ ] **Step 7: Write `src/index.js`** — `export default { fetch }` with one route, `GET /health` returning `{ok:true}` as JSON. Everything else 404s for now.

- [ ] **Step 8: Run tests** — `node workers/wholesale-portal/test/run_all.mjs`, expect `fail: 0`.

- [ ] **Step 9: Commit**

```bash
git add workers/wholesale-portal
git commit -m "Wholesale portal: worker skeleton, schema, and a real-sqlite test harness"
```

---

### Task 2: Sessions, magic links, and password sign-in

**Files:**
- Create: `workers/wholesale-portal/src/auth.js`, `test/auth_test.mjs`
- Modify: `src/index.js` (routes), `test/run_all.mjs` (suite list)

**Interfaces:**
- Consumes: `SCHEMA_DDL`, `randomId`, `sha256Hex`, `hmacSign`, `makeEnv`
- Produces: `loadSession(env, req): {session, buyer}` · `createSession(env, {buyer_id, is_admin, admin_label}): {id, cookie}` · `destroySession(env, id)` · `setCookieHeader(value, maxAgeSec)` · `clearCookieHeader()` · `issueMagicLink(env, email)` · `consumeMagicToken(env, token)` · `adminLogin(env, password): {ok, cookie, label}` · `setBuyerCredentials(env, buyerId, {username, password, currentPassword})` · `loginWithUsernamePassword(env, username, password)`

Port from `sake-kitty-vendor-portal/src/auth.ts`, substituting `buyers` for `vendors`. Keep PBKDF2-SHA256 at 100000 iterations, the constant-time compare, and the dummy-PBKDF2 branch on unknown usernames.

- [ ] **Step 1: Write the failing tests** in `test/auth_test.mjs`

```js
test('a forged cookie signature is rejected', async () => {
  const { id } = await createSession(env, { buyer_id: 1 });
  const req = new Request('https://x/', { headers: { Cookie: `skwp_sess=${id}.deadbeef` } });
  assertEqual((await loadSession(env, req)).session, null);
});
test('a magic token works once', async () => {
  const t = await issueTestToken(env, buyerId);
  assert((await consumeMagicToken(env, t)).ok);
  assertEqual((await consumeMagicToken(env, t)).ok, false);
});
test('an expired session is dropped on load', async () => {
  // backdate expires_at, expect session null and the row gone
});
test('only an approved buyer can sign in', async () => {
  // status applied and declined both refuse, and no token is issued
});
test('the two admin passwords produce differently-labelled sessions', async () => {
  assertEqual((await adminLogin(env, 'nick-pw')).label, 'Nick');
  assertEqual((await adminLogin(env, 'andrew-pw')).label, 'Andrew');
  assertEqual((await adminLogin(env, 'wrong')).ok, false);
});
```

- [ ] **Step 2: Run to verify it fails** — `node workers/wholesale-portal/test/auth_test.mjs`.

- [ ] **Step 3: Implement `src/auth.js`.** Cookie name `skwp_sess`, session TTL 30 days, magic token TTL 7 days. `issueMagicLink` returns `{ok:true}` for an unknown or unapproved email without sending, so the form cannot be used to enumerate buyers.

- [ ] **Step 4: Add routes to `src/index.js`** — `GET|POST /login`, `GET|POST /login/link`, `GET /auth/verify`, `GET /logout`, `GET|POST /admin/login`.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: sessions, magic links, and two named admin logins"`

---

### Task 3: Attributable audit log

**Files:**
- Create: `workers/wholesale-portal/src/audit.js`, `test/audit_test.mjs`

**Interfaces:**
- Consumes: `SCHEMA_DDL`
- Produces: `audit(env, {actor, action, subject, from, to, note}): Promise<void>` · `listAudit(env, {limit, offset}): Promise<Row[]>`

A task of its own because every later task depends on it and Nick named it as a requirement in its own right.

- [ ] **Step 1: Write the failing tests** in `test/audit_test.mjs`

```js
test('an audit row records who, what, and both values', async () => {
  await audit(env, { actor: 'Nick', action: 'product_price', subject: 'product:vol4', from: 53800, to: 61300 });
  const r = (await listAudit(env, { limit: 1 }))[0];
  assertEqual(r.actor, 'Nick');
  assertEqual(JSON.parse(r.detail).from, 53800);
  assertEqual(JSON.parse(r.detail).to, 61300);
});
test('listAudit returns newest first', async () => {
  // three rows, assert the returned order
});
test('the module exposes no way to change or remove a row', () => {
  assertEqual(Object.keys(mod).filter((k) => /update|delete|clear|purge/i.test(k)).length, 0);
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `src/audit.js`** — `detail` is `JSON.stringify({from, to, note})` with undefined keys dropped. Insert only; no update or delete path exists.

- [ ] **Step 4: Run tests** — expect `fail: 0`.

- [ ] **Step 5: Commit** — `"Wholesale portal: append-only audit log with before/after values"`

---

### Task 4: Buyer applications

**Files:**
- Create: `workers/wholesale-portal/src/buyers.js`, `src/email.js`, `src/pages/public.js`, `test/buyers_test.mjs`
- Modify: `src/index.js`

**Interfaces:**
- Consumes: `audit`, `issueMagicLink`, `esc`
- Produces: `submitApplication(env, body, ip): {ok, error?}` · `approveBuyer(env, id, actor)` · `declineBuyer(env, id, actor)` · `listBuyers(env, {status})` · from `src/email.js`: `sendApplicationReceived`, `sendApplicationApproved`, `sendMagicLink`, `sendOrderSubmitted`, `sendStageChanged` — each `(env, ...) => Promise<boolean>`

- [ ] **Step 1: Write the failing tests** in `test/buyers_test.mjs`

```js
test('an application lands as a buyer with status applied', async () => {
  // and a notification email is queued to Nick and Andrew
});
test('the honeypot and the speed trap both succeed silently without writing a row', async () => {
  await submitApplication(env, { ...valid, company_website: 'http://spam' }, ip);
  await submitApplication(env, { ...valid, elapsedMs: 300 }, ip);
  assertEqual(await countBuyers(env), 0);
});
test('approving sends the sign-in email and logs the actor', async () => {
  await approveBuyer(env, id, 'Andrew');
  assertEqual((await listAudit(env, { limit: 1 }))[0].actor, 'Andrew');
  assertEqual(env._mail.length, 1);
});
test('re-applying on a declined email reopens the same row, never a duplicate', async () => {
  assertEqual(await countBuyers(env), 1);
});
test('an application missing a valid email is refused with a message', async () => {
  assertMatch((await submitApplication(env, { ...valid, email: 'nope' }, ip)).error, /email/i);
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `src/buyers.js`.** Port the bot traps from `tcgenie/src/index.js` `skWholesaleOrder`: a filled `company_website` and an `elapsedMs` under 2500 both return success without writing. Field caps match that function.

- [ ] **Step 4: Implement `src/email.js`** — one Resend `POST https://api.resend.com/emails` helper plus the five senders. `sendOrderSubmitted` and `sendApplicationReceived` set `reply_to` to the buyer and go to `SK_ORDER_TO`.

- [ ] **Step 5: Implement `src/pages/public.js`** — `pageApply(flash)`, `pageLogin(flash)`, `pageAdminLogin(flash)`.

- [ ] **Step 6: Wire `GET|POST /apply` into `src/index.js`.**

- [ ] **Step 7: Run tests** — expect `fail: 0`.

- [ ] **Step 8: Commit** — `"Wholesale portal: application intake, vetting, and approval email"`

---

### Task 5: Products in the database

**Files:**
- Create: `workers/wholesale-portal/src/products.js`, `test/products_test.mjs`
- Create: `scripts/wholesale/extract_catalog.py`

**Interfaces:**
- Consumes: `audit`
- Produces: `listProducts(env, {includeInactive, forBuyer})` · `getProduct(env, id)` · `upsertProduct(env, row, actor): {ok, error?}` · `importProductsCsv(env, csvText, actor): {created, updated, errors}` · `priceFromCost(costCents): number`

- [ ] **Step 1: Write the failing tests** in `test/products_test.mjs`

```js
test('priceFromCost applies cost / 0.93 rounded up to the dollar', () => {
  assertEqual(priceFromCost(57000), 61300);   // Vol.4
  assertEqual(priceFromCost(53000), 57000);   // Vol.6
});
test('saving a price at or below cost is refused', async () => {
  assertEqual((await upsertProduct(env, { id: 'p1', price_cents: 50000, cost_cents: 50000 }, 'Nick')).ok, false);
});
test('a price change logs the old and new value against the actor', async () => {
  await upsertProduct(env, { id: 'p1', price_cents: 61300 }, 'Nick');
  const d = JSON.parse((await listAudit(env, { limit: 1 }))[0].detail);
  assertEqual([d.from, d.to].join('->'), '53800->61300');
});
test('cost_cents never appears in a buyer-facing product list', async () => {
  assertEqual('cost_cents' in (await listProducts(env, { forBuyer: true }))[0], false);
});
test('importing a CSV reports per-row errors without discarding the good rows', async () => {
  const r = await importProductsCsv(env, csvWithOneBadRow, 'Nick');
  assertEqual(r.created, 2);
  assertEqual(r.errors.length, 1);
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `src/products.js`.** `priceFromCost` is `Math.ceil(cost / 0.93 / 100) * 100`. `listProducts` omits `cost_cents` and any internal note when `forBuyer` is set. CSV columns: `id,name,set_code,region,grp,unit,status,available,cost_cents,price_cents,boxes_per_case,packs_per_box,cards_per_pack,sort_order`.

- [ ] **Step 4: Write `scripts/wholesale/extract_catalog.py`** — reads the `CATALOG` array out of `git show <rev>:wholesale.html` and writes that CSV to a path given on the command line. **Defaults to the scratchpad and refuses to write inside the repo**, because the output carries prices.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: products in D1, cost-aware pricing, CSV import"`

---

### Task 6: The buyer catalogue

**Files:**
- Create: `workers/wholesale-portal/src/pages/buyer.js`, `src/layout.js`, `test/pages_test.mjs`
- Modify: `src/index.js`

**Interfaces:**
- Consumes: `listProducts`, `loadSession`
- Produces: `pageCatalog(env, buyer)` · `pageAccount(env, buyer)` · from `src/layout.js`: `html(opts)`, `htmlStatus(status, opts)`. (`pageOrders` and `pageOrder` live in the same file but are Task 8's deliverable.)

The catalogue markup, the dock, the MOQ meter and the `localStorage` cart are ported from the existing `wholesale.html` (read it at the revision before Task 10 rewrites it). Storage key becomes `sk_wholesale_cart_v3`, and the stored cart is still dropped on load if a product id has vanished or its price moved — the existing file already does this and the behaviour must survive the port.

- [ ] **Step 1: Write the failing tests** in `test/pages_test.mjs`

```js
test('the catalogue never renders a cost figure', async () => {
  assertEqual(/cost/i.test(await renderCatalog(env, buyer)), false);
});
test('an unauthenticated GET /catalog redirects to /login', async () => {
  assertEqual((await app.fetch(new Request('https://x/catalog'), env)).status, 302);
});
test('every response carries the noindex robots header', async () => {
  assertMatch((await app.fetch(new Request('https://x/login'), env)).headers.get('X-Robots-Tag'), /noindex/);
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `src/layout.js`** — port `html`, `htmlStatus`, `render` from the vendor portal's `layout.ts` (Bangers + Inter, true black, the security headers block). Nav is `Catalogue · My Orders · Account · Sign out` for a buyer and `Orders · Buyers · Products · Activity · Sign out` for an admin.

- [ ] **Step 4: Implement `pageCatalog`** and route `GET /catalog` behind a session check.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: buyer catalogue behind sign-in"`

---

### Task 7: Order submission

**Files:**
- Create: `workers/wholesale-portal/src/orders.js`, `test/orders_test.mjs`
- Modify: `src/index.js`

**Interfaces:**
- Consumes: `getProduct`, `orderRef`, `audit`, `sendOrderSubmitted`
- Produces: `MOQ_CENTS = 150000` · `STAGES: string[]` · `submitOrder(env, buyer, {items, shipTo, notes}): {ok, ref?, error?}` where `items` is `[{id, qty}]`

This task owns Review Focus 1, 2 and 3.

- [ ] **Step 1: Write the failing tests** in `test/orders_test.mjs`

```js
test('posted prices are ignored and each line is priced from the database', async () => {
  const r = await submitOrder(env, buyer, { items: [{ id: 'vol4', qty: 3, price_cents: 100 }], shipTo: 'FL' });
  const items = await itemsOf(env, r.ref);
  assertEqual(items[0].unit_price_cents, 61300);
  assertEqual(items[0].line_total_cents, 183900);
});
test('an order under the $1,500 minimum is refused', async () => {
  const r = await submitOrder(env, buyer, { items: [{ id: 'cheap', qty: 1 }], shipTo: 'FL' });
  assertEqual(r.ok, false);
  assertMatch(r.error, /minimum/i);
});
test('a line whose product went out of stock is refused by name', async () => {
  await upsertProduct(env, { id: 'vol4', status: 'out' }, 'Nick');
  assertMatch((await submitOrder(env, buyer, { items: [{ id: 'vol4', qty: 3 }], shipTo: 'FL' })).error, /Gem Pack Vol\.4/);
});
test('a price that moved since page load is charged at the current price', async () => {
  // reprice vol4 upward, submit, assert the new number on the line
});
test('the order snapshots name, unit and price so a later catalogue edit cannot change it', async () => {
  // reprice after submit, re-read the order, assert the line is unchanged
});
test('submitting writes exactly one order_events row at stage submitted', async () => {
  assertEqual(await countEvents(env, ref), 1);
});
test('an unknown product id is refused, not silently dropped', async () => {
  assertEqual((await submitOrder(env, buyer, { items: [{ id: 'nope', qty: 9 }], shipTo: 'FL' })).ok, false);
});
```

`countEvents(env, ref)`, `itemsOf(env, ref)` and `seedProducts(env)` are shared
test helpers; create `test/helpers.mjs` in this task and import them from
`admin_test.mjs` in Task 9 rather than redefining them.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `submitOrder`.** Read `{id, qty}` only; every other field on a posted item is discarded before use. Load each product fresh, refuse the whole order if any line is unknown, inactive, or `status='out'`, sum `price_cents * qty`, refuse under `MOQ_CENTS`, then insert `orders` + `order_items` + one `order_events` row in that order. Email after the write, and a failed send must not roll back the order — unlike the current worker, the record is the source of truth and the email is only a notification.

- [ ] **Step 4: Route `POST /orders`** behind a buyer session.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: order submission, server-side pricing, MOQ enforcement"`

---

### Task 8: Buyer order tracking

**Files:**
- Modify: `workers/wholesale-portal/src/orders.js`, `src/pages/buyer.js`, `src/index.js`, `test/orders_test.mjs`

**Interfaces:**
- Consumes: `getProduct`, `STAGES`
- Produces: `listOrders(env, buyerId)` · `getOrder(env, ref, {buyerId}): Order|null` · `timeline(env, orderId): Event[]`

This task owns Review Focus 4.

- [ ] **Step 1: Write the failing tests**

```js
test('a buyer cannot load an order belonging to someone else, even with the exact ref', async () => {
  assertEqual(await getOrder(env, refOfBuyerA, { buyerId: buyerB.id }), null);
});
test('an admin read passes no buyerId and gets the order', async () => {
  assert(await getOrder(env, refOfBuyerA, {}));
});
test('the timeline lists every stage the order has passed through, oldest first', async () => {
  assertEqual((await timeline(env, orderId)).map((e) => e.stage), ['submitted', 'checking_stock', 'quoted']);
});
test('a quoted order shows the quoted total, not the submitted subtotal', async () => {
  // set a quote that differs from the subtotal, assert the page renders the quote
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** `getOrder` adds `AND buyer_id = ?` whenever `buyerId` is supplied; the admin path omits it deliberately and is the only caller that may.

- [ ] **Step 4: Implement `pageOrders` and `pageOrder`**, routes `GET /orders` and `GET /orders/:ref`. The detail page renders the seven stages with the reached ones marked, plus tracking when present.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: buyer order history and stage timeline"`

---

### Task 9: The admin surface

**Files:**
- Create: `workers/wholesale-portal/src/pages/admin.js`, `test/admin_test.mjs`
- Modify: `src/orders.js`, `src/index.js`

**Interfaces:**
- Consumes: `listOrders`, `getOrder`, `listBuyers`, `approveBuyer`, `declineBuyer`, `upsertProduct`, `listAudit`, `audit`, `sendStageChanged`
- Produces: `advanceStage(env, ref, stage, {actor, note}): {ok, error?}` · `setQuote(env, ref, cents, actor)` · `setTracking(env, ref, carrier, number, actor)` · `cancelOrder(env, ref, actor, reason)`

This task owns Review Focus 5 and the spec's attribution rule.

- [ ] **Step 1: Write the failing tests** in `test/admin_test.mjs`

```js
test('the same stage posted twice advances once and logs once', async () => {
  await advanceStage(env, ref, 'checking_stock', { actor: 'Nick' });
  assertEqual((await advanceStage(env, ref, 'checking_stock', { actor: 'Nick' })).ok, false);
  assertEqual(await countEvents(env, ref), 2);   // submitted + checking_stock
});
test('a backwards stage is refused', async () => {
  await advanceStage(env, ref, 'shipped', { actor: 'Nick' });
  assertEqual((await advanceStage(env, ref, 'quoted', { actor: 'Nick' })).ok, false);
});
test('cancel is reachable before shipped and refused after', async () => {
  // one order cancelled at quoted, another refused at shipped
});
test('every stage change records which admin made it', async () => {
  await advanceStage(env, ref, 'checking_stock', { actor: 'Andrew' });
  assertEqual((await listAudit(env, { limit: 1 }))[0].actor, 'Andrew');
});
test('EVERY state-changing admin route writes exactly one audit row', async () => {
  // Enumerate the POST routes the admin pages expose, drive each one, and assert
  // the audit count rose by exactly 1. This is the test that keeps the log honest.
});
test('a buyer session gets 403 on an admin route', async () => {
  assertEqual((await app.fetch(adminReqWithBuyerCookie, env)).status, 403);
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement the stage machine in `src/orders.js`.** `advanceStage` refuses a target that is not strictly later in `STAGES` than the current stage; `cancelled` is accepted from any stage before `shipped`. The guard is a conditional `UPDATE ... WHERE ref = ? AND stage = ?` and the decision is made on `meta.changes`, so two concurrent requests cannot both win.

- [ ] **Step 4: Implement `src/pages/admin.js`** — `pageAdminOrders` (queue grouped by stage, newest first), `pageAdminOrder` (stage buttons, quote field, tracking field, internal note), `pageAdminBuyers`, `pageAdminProducts` (price editor showing margin and flagging any row at or below cost), `pageAdminActivity` (the audit log, newest first, actor named on every line). Routes as listed in the spec.

- [ ] **Step 5: Run tests** — expect `fail: 0`.

- [ ] **Step 6: Commit** — `"Wholesale portal: admin order queue, stage machine, product editor, activity log"`

---

### Task 10: Site integration and cutover

**Files:**
- Modify: `wholesale-pokemon.html`, `wholesale.html`, `CLAUDE.md`
- Create: `workers/wholesale-portal/README.md`

- [ ] **Step 1: Rewrite `wholesale.html` as a redirect stub** to `https://wholesale.sakekittycards.com`, following the shape of `buylist.html`. It keeps `noindex, nofollow`. **This is what removes live prices from the public repo** — the `CATALOG` array goes with it.

- [ ] **Step 2: Add the application section to `wholesale-pokemon.html`** — wholesale is an application process, what Nick needs (resale certificate, what they sell, rough volume), and one CTA to `https://wholesale.sakekittycards.com/apply`. **It must not link to `wholesale.html`.** Bump `style.css?v=` and `main.js?v=` on every page per the repo convention.

- [ ] **Step 3: Verify the standing rule holds**

Run: `grep -rn "wholesale\.html" --include=*.html .`
Expected: only the redirect stub itself and the existing comment in `social.html`.

- [ ] **Step 4: Run the SEO audit**

Run: `python scripts/seo_audit.py`
Expected: exit 0. Warnings on redirect stubs are expected. The audit's own
sitemap-coverage check is what confirms the stub stayed out of `sitemap.xml`;
do not hand-edit that file.

- [ ] **Step 5: Run the full test suite**

Run: `node workers/wholesale-portal/test/run_all.mjs`
Expected: `fail: 0`.

- [ ] **Step 6: Write `workers/wholesale-portal/README.md`** — deploy command, the secret list, the D1 migration commands, and how to seed products from a scratchpad CSV. State plainly that the CSV is never committed.

- [ ] **Step 7: Update `CLAUDE.md`** — replace the `wholesale.html` entry with the portal, record the two named admin logins, and note that catalogue prices now live in D1 and are edited in the admin UI rather than in a commit.

- [ ] **Step 8: Commit** — `"Wholesale: public application path, portal cutover, prices out of the repo"`

---

## Deployment (Nick, not the implementer)

1. `wrangler d1 create sake-kitty-wholesale` — **needs a token with D1:Edit**, the same permission gap still blocking the social engine's database.
2. `wrangler d1 migrations apply sake-kitty-wholesale --remote`
3. `wrangler secret put` for `COOKIE_SECRET`, `MAGIC_LINK_SECRET`, `RESEND_API_KEY`, `ADMIN_PASSWORD`, `ADMIN_PASSWORD_ANDREW` — **the two admin passwords must differ**, or the activity log cannot tell Nick and Andrew apart.
4. DNS: `wholesale.sakekittycards.com` as a custom domain on the worker, same as `vendors.`
5. Import the product CSV through the admin UI, then confirm no row sits at or below cost.
