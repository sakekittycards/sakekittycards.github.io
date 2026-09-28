# Wholesale first-touch auto-reply — runbook

Two pieces:

| Piece | Where | Job |
|---|---|---|
| Classifier + log + switches | `workers/square/src/wholesale-autoreply.js`, routes in `src/index.js`, D1 tables | decides, remembers, throttles |
| Gmail arm | `WholesaleAutoReply.gs` in this folder | reads mail, carries out the decision |

Every rule lives in the Worker. The Apps Script never decides anything, so
changing behaviour is a Worker deploy or a config write, never a script edit.

## The rule this exists to enforce

> Auto-send only what is true regardless of who is asking. Never auto-send
> anything touching a price, a product, availability, quantity, sourcing or
> English product. Default on ambiguity is **route to Nick**.

## Install

### 1. Migrate D1

```bash
cd workers/square
wrangler d1 execute sk-promo-codes --file=migrations/0005_wholesale_autoreply.sql --remote
```

Ships in **shadow mode with the kill switch on**. Nothing can send.

### 2. Deploy the Worker

```bash
cd workers/square
wrangler deploy
```

Note: merging to `main` deploys the *site* via Pages. It does **not** deploy
the Worker — that is this `wrangler deploy`, run separately.

### 3. Set up the Apps Script

1. <https://script.google.com> → New project, signed in as `sakekittycards@gmail.com`
2. Paste `WholesaleAutoReply.gs` over `Code.gs`
3. **Services** (＋) → add **Gmail API**, identifier `Gmail`
4. **Project Settings → Script Properties**:
   | Key | Value |
   |---|---|
   | `WORKER_URL` | `https://sakekitty-square.<your-subdomain>.workers.dev` |
   | `ADMIN_TOKEN` | the same secret as the Worker's `ADMIN_TOKEN` |
5. Run `installTriggers()` once and grant the permissions it asks for.
   This also stamps `START_AFTER`, so the backlog is never touched.

### 4. Confirm the send-as alias

Gmail → Settings → Accounts → "Send mail as" must already list
`wholesale@sakekittycards.com`. Without it, Gmail rejects the `From:` header
when the mode reaches `draft` or `live`.

## Rollout

Shadow → draft → auto-send. Do not skip a stage.

### Stage 1 — shadow (log only)

```bash
curl -s -X POST "$WORKER/admin/wholesale/autoreply/config" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"updates":{"mode":"shadow"}}'
```

Mail gets labelled `SK-AutoReply/would-reply` or `.../routed-to-Nick` and
nothing is sent. Read the log:

```bash
curl -s "$WORKER/admin/wholesale/autoreply/log?limit=50" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN"
```

Stay here until the log is boring and every `would-reply` is one you would
genuinely have been happy to send unread.

### Stage 2 — draft

```bash
curl -s -X POST "$WORKER/admin/wholesale/autoreply/config" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"updates":{"mode":"draft","kill_switch":"0"}}'
```

Eligible mail becomes a Gmail draft. Send it, edit it, or bin it.

After each one, tell the system whether you changed anything — this is what
counts toward auto-send:

```bash
# sent exactly as written
curl -s -X POST "$WORKER/admin/wholesale/autoreply/approve" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"gmailMessageId":"<id from the log>","clean":true}'

# needed edits — resets the streak to zero
  -d '{"gmailMessageId":"<id>","clean":false}'
```

### Stage 3 — auto-send

Only once the streak reaches 10. Check it:

```bash
curl -s "$WORKER/admin/wholesale/autoreply/config" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN"     # -> cleanDraftStreak
```

```bash
curl -s -X POST "$WORKER/admin/wholesale/autoreply/config" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"updates":{"mode":"live"}}'
```

## Kill switch

Stops all outbound immediately, no deploy:

```bash
curl -s -X POST "$WORKER/admin/wholesale/autoreply/config" \
  -H "X-Sake-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"updates":{"kill_switch":"1"}}'
```

Everything then routes to Nick instead. To stop the script reading mail at
all, delete the triggers in the Apps Script UI.

## Caps

| Setting | Default | Meaning |
|---|---|---|
| `cap_per_hour` | 3 | auto-sends per hour |
| `cap_per_day` | 10 | auto-sends per day |
| one per sender | — | ever, tracked in `wholesale_autoreply_senders` |

Hitting a cap routes to Nick rather than queueing.

## Endpoints

All take `X-Sake-Admin-Token`, compared timing-safe against `ADMIN_TOKEN`.

| Method | Path | Use |
|---|---|---|
| POST | `/wholesale/autoreply/classify` | decide one message |
| POST | `/wholesale/autoreply/record` | report what was done |
| GET | `/wholesale/autoreply/digest` | daily digest data |
| GET/POST | `/admin/wholesale/autoreply/config` | read / change switches |
| GET | `/admin/wholesale/autoreply/log` | the decision log |
| POST | `/admin/wholesale/autoreply/approve` | mark a draft clean or edited |

## Tests

```bash
node --test workers/square/test/wholesale-autoreply.test.js
```

The corpus test runs the classifier over eight real first-touch enquiries
taken from the live mailbox. It fails if a rule change starts auto-replying
to any of them. `test/fixtures/real-enquiries.json` holds real customer
names and addresses — the repo is public, so **do not** move that file
anywhere it gets served, and think before adding more.

## Loop safety

- outbound carries `Auto-Submitted: auto-replied`, `Precedence: auto_reply`
  and `X-Auto-Response-Suppress: All`
- inbound carrying `Auto-Submitted`, `List-Id`, `List-Unsubscribe` or
  `Precedence: bulk` is dropped before classification
- `no-reply@`, `noreply@`, `notify+`, `mailer-daemon@`, `postmaster@` dropped
- any `@sakekittycards.com`, `sakekittycards@gmail.com` and `@tcgenie.io`
  dropped, so it can never answer itself or TCGenie
- one auto-reply per address ever

## The site contact form

`web3forms` relays form submissions from `notify+xxxxx@web3forms.com` with
the real sender inside the body:

```
name : Marcus Trelane
email : marcus@northvaleretail.example
topic : Wholesale / B2B
message : ...
```

This is the busiest wholesale intake channel. `parseWeb3Form()` unwraps it
before anything else runs — otherwise every form submission would be
discarded by the `notify+` drop rule. A reply to a form submission goes out
as a new message, not a threaded reply, because there is nothing of the
sender's to thread onto.
