# Social Content Engine

One system that turns website events and approved videos into Instagram posts,
with a human gate in front of the publish call.

```
assets/events-data.js ──> ingest ──> opportunities ──┐
                                                     ├──> DRAFT ──> APPROVAL ──> SCHEDULE ──> Instagram ──> log
SHORT FORM FINAL/*.mp4 ──> registry ──> APPROVED ────┘
```

Everything before `APPROVAL` is automatic. Nothing after it happens without a
person, and nothing at all happens for real until publishing is switched to live
in two separate places.

---

## 1. What existed before

| Component | What it did | Verdict | Role now |
|---|---|---|---|
| `assets/events-data.js` | Hand-edited `window.SK_EVENTS`, read by `events.html` + `index.html` | **KEEP, unchanged** | The source of truth. The engine mirrors it and never writes back. |
| `scripts/_make_ig_stuart.py` | One-off 1080×1350 IG post for one show, date/venue hardcoded | **SUPERSEDED** | Its visual ideas live in `templates.py`; the file stays as historical record. |
| `scripts/_make_ig_stuart_video.py` | One-off 1080×1920 Reel overlay for the same show | **SUPERSEDED** | Same. |
| `scripts/_make_ig_live.py` | One-off "shop is live" IG post | **SUPERSEDED** | Same. |
| `gen_og.py`, `gen_cover.py`, `gen_fb_cover.py` | Site OG / cover / FB images | **KEEP** | Different job (site metadata), untouched. Their palette was wrong; see §7. |
| Booth-banner build scripts (scratchpad) | Print banner, measured palette, glyph-by-glyph tracking | **PROMOTED** | Their type engine is now `scripts/social/sk_brand.py`. |
| `workers/ig-bot/` | Inbound IG DM webhook → KV → local pricing runner | **KEEP, untouched** | Different surface (Messaging). Shares only the Meta app. |
| `workers/feeds/` | Cron → Discord announcements incl. IG *reads* | **KEEP, untouched** | Never deployed (its KV id is still a placeholder). Outbound Discord, not publishing. |
| `workers/square/` | Square catalog, checkout, promo codes, grading tracker | **KEEP, untouched** | Its `X-Sake-Admin-Token` + `json()` + `timingSafeEqual` conventions are reused verbatim. |
| `admin-promo.html` | Token-gated admin dashboard | **PATTERN REUSED** | `social.html` follows it exactly. |
| `scripts/graded-uploader/_review_queue.py` | Local JSON approve/reject queue for offer PDFs | **PATTERN REUSED** | Its `auto_ok` idea became the policy table. |
| Video pipeline (`D:\Pokemon Footage Nick\_pipeline`) | 60+ scripts, ends at `SHORT FORM FINAL/` | **KEEP, untouched** | The engine reads its output. It does not modify the pipeline. |

### The finding that shaped the design

**There was no machine-readable approval state anywhere.** Approval was Nick
watching a short and saying *"looks good to push"*, after which a human wrote a
line of prose in `_ref/clip_content_ledger.md`. There was a folder convention —
`_staging/` meant "awaiting Nick", the root meant "shipped" — but **on
2026-08-31 the staging step was removed** and builds started landing directly in
the root. Since that day `SHORT FORM FINAL/` has held approved shorts,
unreviewed builds and killed builds side by side.

So a path, a filename, an export location and a successful render are all
worthless as evidence of approval. That is why approval is a database row plus a
content hash, and why the importer puts *everything* in `REVIEW`.

---

## 2. Architecture

Rendering needs Pillow, ffmpeg and the brand fonts; publishing needs to run at
3am whether or not a laptop is open. Those are different machines, so they are
different halves.

### `workers/social/` — the system of record (Cloudflare Worker)

Owns D1, R2, the cron, the admin API, and every Instagram call.

| Module | Responsibility |
|---|---|
| `index.js` | Router, auth, cron. |
| `schema.js` | Self-applying DDL (the tcgenie pattern — append-only, idempotent). |
| `events.js` | Ingest + identity + fingerprints. |
| `opportunities.js` | What promotion of a show is still worth doing. |
| `video.js` | **The approval registry and the invariant.** |
| `items.js` | Content items: draft → approve → schedule. |
| `media.js` | R2 storage, token-addressed delivery, flyer fetch + validation. |
| `scheduler.js` | Spacing rules, publish leases, backoff. |
| `publish.js` | The publisher, including dry run. |
| `instagram.js` | Graph API client with error classification. |
| `analytics.js` | Insight collection (records only; nothing reads it yet). |
| `policy.js` | All cadence and automation configuration. |
| `log.js` | The human-readable activity stream. |

### `scripts/social/` — the local agent (Python)

Decides nothing. Renders, probes, uploads, and files drafts.

| File | Responsibility |
|---|---|
| `sk_brand.py` | The design system: palette, type engine, mascot rules. |
| `templates.py` | `banner` / `flyer` / `photo` at 4:5, 1:1, 9:16. |
| `captions.py` | Deterministic captions + the anti-slop lint. |
| `ingest.py` | Parses `events-data.js` and normalizes it. |
| `flyer.py` | First-party flyer resolver chain. |
| `video.py` | ffprobe + SHA-256 + register / approve / deliver. |
| `run.py` | One command runs a whole content pass. |
| `preview.py` | Contact sheet of the templates against real events. |
| `client.py` | Admin API client. |

### `social.html` — the Content Command Center

Standalone, `noindex`, unlinked, token-gated. Same pattern as `admin-promo.html`.

---

## 3. The video invariant

> **An unapproved video can never reach the Instagram publish function.**

Enforced at two independent choke points, both of which call
`video.assertPublishable()`:

1. `items.createReelItem()` — the only code path that can create a
   `type='reel'` row at all.
2. `publish.buildPayload()` — the first statement in the function, before any
   other check can shadow it.

`assertPublishable` requires **all** of:

- `state ∈ {APPROVED, READY_FOR_INSTAGRAM, SCHEDULED, PUBLISHED}` — every one of
  which is only reachable through `approve()`
- `approved_at` and `approved_by` both present
- `revoked_at` unset
- **`approved_sha256 === sha256`**

That last condition is what survives the realistic failure: a short is approved,
then re-rendered in place under the same filename. The bytes change, the stored
approval hash does not, and the mismatch drops the asset back to `REVIEW` and
pulls any queued post off the calendar.

There is no policy flag that auto-approves video, no trusted folder, and no
endpoint that writes `state` directly — `setState` is not exported, and the
machine transition table has no edge into `APPROVED`.

**Verified end-to-end on a live worker:**

```
POST /items/reel  (video in REVIEW)  ->  HTTP 409
  {"error":"video \"The Kid's Binder\" is REVIEW, not approved
            — Instagram ingestion refused","code":"unapproved"}

POST /video/approve                  ->  {"ok":true}
POST /items/reel                     ->  HTTP 200

# then: append one byte to the file, rescan
video: REVIEW | approved_by None
item : needs_review | source video changed after approval
would: video "The Kid's Binder" is REVIEW, not approved — Instagram ingestion refused
```

---

## 4. Idempotency and safety

| Risk | Protection |
|---|---|
| Duplicate posts from a retry | `scheduler.claim()` is a conditional `UPDATE`; exactly one caller sees `changes === 1`. |
| Double post after a publish timeout | The container id is persisted **before** `media_publish`. A retry reuses it and checks recent media rather than creating a second container. |
| Duplicate drafts | Opportunity ids are `sha256(event_id, kind)`; content item ids derive from the opportunity. |
| Duplicate events from an edit | Event identity is `(normalized title, start date)` — venue and hours can change without creating a new event. |
| Publishing stale event details | `subject_fingerprint` is captured at approval and re-checked at publish; a mismatch forces re-review. |
| Publishing a cancelled show | An event dropped from the website is marked `cancelled`, which retires every pending opportunity. |
| A worker dying mid-publish | Leases expire after 10 minutes and are reaped back to `scheduled`. |
| Losing the source asset | The engine never writes to `SHORT FORM FINAL/` or `events-data.js`. |
| Accidentally going live | Live requires **both** `PUBLISH_MODE=live` (deploy) and `policy.mode=live` (runtime). |
| An expired token retrying forever | Auth errors are classified `auth`, pause publishing and alert once. |

---

## 5. Cadence

Configured in `policy.windows`, not in code.

| Rung | When | Default |
|---|---|---|
| `ANNOUNCEMENT` | Within 10 days of the show being **added**, ≤120 days out, ≥9 days before | on |
| `UPCOMING` | 8–5 days before | on |
| `THIS_WEEKEND` | 3–2 days before | on |
| `DAY_OF` | Morning of, as a Story | **off** |

An announcement fires because a show is *news*, not because it exists. The first
run of the engine against the real calendar wanted to announce **18 shows at
once**; the backfill marker (`meta.first_ingest_at`) is what stops that, and the
120-day horizon stops a show being announced eleven months early.

Spacing: nothing within 20h of another post, 44h between two event posts, 3h
between a reel and an event post, max 2/day, nothing between 23:00 and 07:00 ET.
`max_posts_per_event` (default 2) stops a late-added show firing three rungs at
once.

---

## 6. Rollout

| Phase | State |
|---|---|
| 1 — audit + architecture | done |
| 2 — ingestion | done, verified against all 53 real events |
| 3 — generation + approval console | done |
| 4 — Instagram integration, dry run | done; **this is where it ships** |
| 5 — manual POST NOW | needs Meta credentials |
| 6 — scheduled posts | flip `policy.mode` |
| 7 — automatic event publishing | flip `automation.event_graphic` |
| 8 — analytics-led scheduling | not before ~12 posts of data |

### Enabling live posting

Three deliberate steps, in order.

**1. Meta app** (`Sake Kitty Worker`, App ID `1663513611433623` — the app the DM
bot already uses). Add the **Instagram Content Publishing** use case and get
`instagram_content_publish` through App Review. This is the long pole: it needs
Business Verification and, per the existing notes, "Become a Tech Provider".

**2. Secrets:**
```sh
cd workers/social
wrangler secret put IG_ACCESS_TOKEN   # long-lived token with content publishing
wrangler secret put IG_USER_ID        # numeric IG Business account id
```
Confirm with `POST /ig/check` — it stores token health and the publishing quota.

**3. Flip both gates.** Deploy-time:
```toml
PUBLISH_MODE = "live"    # wrangler.toml, then wrangler deploy
```
Runtime:
```sh
curl -X POST -H "X-Sake-Admin-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"patch":{"mode":"live"},"by":"nick"}' \
  https://sakekitty-social.nwilliams23999.workers.dev/policy
```
Either one left at `dry` keeps the whole system in dry run. Flip the runtime one
first and use **Post now** on a single approved item before enabling the cron.

Long-lived tokens expire after 60 days. `POST /ig/refresh-token` returns a fresh
one for `wrangler secret put`; it is deliberately not stored automatically, so a
live publishing credential never sits in a row that an admin read returns.

---

## 7. Brand

The palette is **sampled from the mascot**, not chosen:

| role | hex | note |
|---|---|---|
| gold | `#f2b905` | 8% of pixels — the outline colour of the illustration |
| orange | `#f04800` | the dominant mass |
| magenta | `#d81860` | |
| cobalt / azure | `#0060c0` / `#0090d8` | a true blue, not cyan |

Cyan `#22c8ff` and violet `#7b2fff` appear nowhere in the artwork. Both were in
`gen_og.py` and the old `_make_ig_*` scripts, and they are what made that output
read as a generic neon rainbow bolted onto the cat. They are absent here.

Rules encoded in `sk_brand.py`: glows are built at full canvas size (a blur
inside a content-sized layer clips into a visible rectangle); no text stroke on
display type; the mascot is composited as supplied, cropped and resized only,
positioned so its straight bottom cut falls off-canvas behind a scrim.

Text on graphics is always drawn from structured data by `templates.py`. No
generative model renders any factual text, and none is asked what an event is
called.

---

## 8. Running it

```sh
# once a day, or after editing events-data.js
python scripts/social/ingest.py          # mirror the calendar
python scripts/social/run.py             # ingest + render + draft in one pass

# video
python scripts/social/video.py scan      # probe + register (everything -> REVIEW)
python scripts/social/video.py approve <id> --by nick
python scripts/social/video.py deliver <id>

# look at it
open social.html                         # the console
python scripts/social/preview.py         # template contact sheet

# tests
node workers/social/test/run_all.mjs     # 158 checks
```

Local development runs the real worker with real D1 and R2:

```sh
cd workers/social && npx wrangler dev --local --port 8799
# then point the console at it:
#   social.html?api=http://127.0.0.1:8799
```
