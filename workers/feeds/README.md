# sakekitty-feeds

Cloudflare Worker that posts to the Sake Kitty Discord on a 15-minute cron:

| Feed | Channel | Source | Credential needed |
|------|---------|--------|-------------------|
| YouTube uploads | `#youtube` | channel RSS | none |
| New shop products + restocks | `#site-updates` | the public `sakekitty-square` `/items` | none |
| Instagram posts | `#instagram` | Graph API `/me/media` poll | `IG_TOKEN` |

Each feed is independent. YouTube and the shop feed need **no Meta/Google credential at
all**, so they can go live immediately; Instagram stays dormant until `IG_TOKEN` is set.

This is **not** the same worker as `../ig-bot`. That one is the offer bot's inbound-DM
intake (customer messages → KV → local pricing runner). This one is outbound
announcements. They share nothing but the word "Instagram".

## Deploy (one pass)

All commands run from this directory. Deploy uses the same token as the other workers:

```sh
cd workers/feeds
export CLOUDFLARE_API_TOKEN="$(cat /c/Users/lunar/.cf-deploy-token)"

# 1. Create the de-dupe KV namespace and copy the id it prints.
npx wrangler kv namespace create FEEDS

# 2. Paste that id into wrangler.toml, replacing REPLACE_WITH_KV_ID.

# 3. Set the webhook secrets. The values live in ~/.claude/sk_discord_webhooks.json
#    (never commit them). YouTube + shop work with just these two:
npx wrangler secret put DISCORD_YT_WEBHOOK_URL      # = DISCORD_YT_WEBHOOK_URL   in that file
npx wrangler secret put DISCORD_SITE_WEBHOOK_URL    # = DISCORD_SITE_WEBHOOK_URL in that file
npx wrangler secret put FEED_KEY                    # = any random string; guards /debug

# 4. Deploy.
npx wrangler deploy
```

Instagram is optional and can be added any time later — it does not block the deploy:

```sh
npx wrangler secret put DISCORD_IG_WEBHOOK_URL      # from the same json file
npx wrangler secret put IG_TOKEN                    # Instagram Graph long-lived token
```

## Verify

```sh
# Which feeds are configured — each is true only when its secret(s) exist.
curl -s https://sakekitty-feeds.<subdomain>.workers.dev/health
# -> {"ok":true,"youtube":true,"shop":true,"instagram":false}

# What a run WOULD post right now, without posting (needs FEED_KEY).
curl -s "https://sakekitty-feeds.<subdomain>.workers.dev/debug?key=<FEED_KEY>"
```

## What to expect on the first cron run

**The first run of each feed posts nothing.** It records the current items as the
baseline ("bootstrap") so turning a feed on can't replay the whole back catalogue into
the channel. Real posts start from the *next* new video / product / restock.

Two more expected quiet spots, both correct:

- **Restocks stay silent until cards/sealed return to Square.** Everything in the catalog
  today is Printful merch, which is print-on-demand and never goes out of stock, so there
  are no restock transitions to announce yet.
- **Going *out* of stock posts nothing** (no sold-out spam) — but the state is recorded, so
  the item's *return* fires a "Back in stock".

Backlog is capped at 5 posts per feed per run; an item is marked seen only after Discord
accepts the post, so a failed post retries next run.

## Gotchas

- **`YT_CHANNEL_ID` must be the `UC…` id, not the `@handle`** — the RSS feed rejects the
  handle. It's already set in `wrangler.toml` (resolved from `youtube.com/@SakeKittyCards`)
  and is not a secret.
- **Discord's edge 403s the `Python-urllib` User-Agent.** The worker sends an explicit
  `sakekitty-feeds/1.0` UA on every post for this reason. If you ever port this to a Python
  poster, set a custom UA or it will silently 403.

## Test

`node test_feeds.mjs` — 40 assertions covering the YouTube RSS parse (against the live
feed), the de-dupe/bootstrap/backlog logic, the shop new-product and restock transitions,
and the embed shapes. No network mutation; it uses a fake KV and an injected poster.
