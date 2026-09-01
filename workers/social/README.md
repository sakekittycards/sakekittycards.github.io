# sakekitty-social

The social content engine's system of record. Owns the database, the media
store, the scheduler and every Instagram call.

Full design notes: [`docs/social-content-engine.md`](../../docs/social-content-engine.md).

## The two rules this worker enforces

1. **An unapproved video can never reach the Instagram publish function.**
   `src/video.js` `assertPublishable()` is called at both choke points —
   `items.createReelItem()` and the first line of `publish.buildPayload()`.
2. **Live publishing needs two independent switches.** `PUBLISH_MODE` here in
   `wrangler.toml` *and* `policy.mode` in the database. Either one at `dry`
   keeps the whole system in dry run.

## First-time setup

```sh
cd workers/social

# 1. database (needs a token with D1:Edit — the .cf-deploy-token cannot do this)
wrangler d1 create sk-social
#    paste the returned uuid into wrangler.toml -> [[d1_databases]] database_id
#    The schema applies itself on first request; there is nothing to run.

# 2. media bucket (already created 2026-09-01)
wrangler r2 bucket create sk-social-media

# 3. secrets
wrangler secret put ADMIN_TOKEN        # gates everything except /health and /m/<token>
wrangler secret put DISCORD_WEBHOOK    # optional: mirrors published/failed to #sk-ops

# 4. deploy (stays in dry run — PUBLISH_MODE defaults to "dry")
wrangler deploy
```

Instagram credentials are deliberately a separate, later step. Everything except
the final publish call works without them; see §6 of the design doc.

```sh
wrangler secret put IG_ACCESS_TOKEN    # long-lived, instagram_content_publish
wrangler secret put IG_USER_ID         # numeric IG Business account id
```

## Local development

Runs the real worker against real (local) D1 and R2:

```sh
echo "ADMIN_TOKEN=$(openssl rand -base64 24)" > .dev.vars   # gitignored
npx wrangler dev --local --port 8799
```

Point the console at it with `social.html?api=http://127.0.0.1:8799`.

Cron does not fire automatically in local dev. Trigger a tick by hand:

```sh
curl "http://127.0.0.1:8799/cdn-cgi/handler/scheduled"
# or, with auth, the same work synchronously:
curl -X POST -H "X-Sake-Admin-Token: $TOK" http://127.0.0.1:8799/scheduler/tick
```

> `compatibility_date` is pinned to `2026-04-28` because the repo's wrangler
> (4.84.1) bundles a `workerd` that refuses anything newer, and a date it cannot
> run means the only way to exercise the worker is to deploy it. Nothing here
> needs a later date.

## Tests

```sh
node test/run_all.mjs      # 158 checks, exits non-zero on any failure
```

D1 is backed by a real in-process SQLite (`node:sqlite`), not a mock — the lease
and idempotency guarantees are properties of a conditional `UPDATE`'s `changes`
count, and a hand-written fake would prove nothing.

| Suite | Covers |
|---|---|
| `video_approval_test.mjs` | The invariant, attacked from 13 angles (59 checks). |
| `engine_test.mjs` | Time/DST, ingestion, opportunities, spacing, leases, staleness, dry run, policy (99 checks). |

## Endpoints

Everything except `/health` and `/m/:token` requires `X-Sake-Admin-Token`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Mode, whether Instagram is configured, token health. Public. |
| GET | `/m/:token` | Serves media to Instagram's fetcher. Range-capable. Public by capability token. |
| POST | `/events/ingest` | Reconcile a full snapshot of the website calendar. |
| GET | `/events`, `/events/unpromoted` | The mirror; shows with nothing planned. |
| POST | `/opportunities/refresh` | Recompute the promotion ladder. |
| GET | `/opportunities`, `/opportunities/due` | The ladder; what the renderer should build. |
| POST | `/media/upload`, `/media/fetch-flyer` | Store rendered bytes; fetch first-party artwork. |
| POST | `/video/register`, `/video/register-batch` | Register probes. **Always lands in REVIEW.** |
| GET | `/video`, `/video/detail` | Registry + compatibility + transition history. |
| POST | `/video/approve`, `/reject`, `/revoke` | The human gate. `approve` requires `by` and `source`. |
| POST | `/video/attach-media` | Deliver approved bytes; refuses a hash mismatch. |
| POST | `/items/event`, `/items/reel` | Create drafts. `/items/reel` 409s on an unapproved video. |
| GET | `/items`, `/items/detail` | The queue; one item with its would-be payload. |
| POST | `/items/approve`, `/schedule`, `/unschedule`, `/caption`, `/media`, `/reject`, `/archive` | Queue actions. |
| POST | `/items/publish-now` | Full publisher, "now". Honours dry run. |
| POST | `/scheduler/tick` | What the cron does, on demand. |
| GET | `/dry-run` | What would be sent for everything approved or scheduled. |
| GET | `/queue`, `/activity`, `/history` | Console data. |
| GET/POST | `/policy` | Read / patch cadence and automation. |
| GET | `/ig/account`, POST `/ig/check`, `/ig/refresh-token` | Account, token health, refresh. |
| POST | `/analytics/collect`, GET `/analytics` | Insight collection and summary. |

## Cron

`*/15 * * * *` — refresh opportunities, revalidate approved items against their
sources, reap dead leases, publish what is due. On the first tick of each hour it
also checks token health and collects insights.

The order matters: revalidation runs *before* publishing, so a change that landed
since the last tick is caught before it can go out rather than after.

## Schema

Applied idempotently on every isolate boot from `src/schema.js` — the pattern the
tcgenie worker settled on after eight separate guarded migration blocks drifted
apart. **Append only.** Never edit an existing DDL line: a deployed database has
already run it, so an edit applies to new databases only and the two diverge.
