# sakekitty-square Worker

Cloudflare Worker that proxies Square API calls for the Sake Kitty Cards site.

The site calls this Worker instead of talking to Square directly, so the Square access token stays server-side (never in browser JS, never in git).

## Endpoints

- `GET  /health`   — liveness check
- `GET  /items`    — list products from Square catalog
- `POST /checkout` — create a Square Payment Link from a cart; body: `{ items: [{ name, price, quantity }], shippingCost?, note?, returnUrl? }`
- `GET  /items` graded items also carry `cert` (digits from the `Cert #:` description line) and `sold`. Card items (cert, `Card ID:`, or `SEAL-*` SKU) whose description holds a `Status: sold` line are **omitted** — merch never carries the marker.
- `POST /admin/set-item-status` — `{ item_id, status: 'sold' | 'live' }` (X-Sake-Admin-Token). Adds/removes the `Status: sold` description line; never deletes the item.

**The Square catalog is a mirror of Nick's TCGenie inventory (account 54).** TCGenie's daily run (13:00 UTC, `POST /admin/reprice-sk` on the TCGenie worker) creates slabs, syncs prices/photos and marks sold items here. Edit inventory and prices in TCGenie — Square-side hand edits are overwritten on the next run.

## First-time deploy

```sh
cd workers/square

# (once, globally) install wrangler if you don't have it
npm install -g wrangler

# log in to Cloudflare (opens a browser)
wrangler login

# set the Square access token as an encrypted secret
# wrangler will prompt you — paste the token and press Enter
wrangler secret put SQUARE_ACCESS_TOKEN

# deploy
wrangler deploy
```

After `wrangler deploy` it'll print a URL like:
```
https://sakekitty-square.<your-subdomain>.workers.dev
```
Put that URL into the site code as the Worker base URL.

## Updating the token later

```sh
wrangler secret put SQUARE_ACCESS_TOKEN   # re-paste a new token
```

## Flipping from Sandbox to Production

1. `wrangler secret put SQUARE_ACCESS_TOKEN` — paste the **production** access token
2. Edit `wrangler.toml`:
   - `SQUARE_APPLICATION_ID` → the production Application ID (no `sandbox-` prefix)
   - `SQUARE_LOCATION_ID` → `LWJ5EY6TCBCGV`
   - `SQUARE_ENV` → `"production"`
3. `wrangler deploy`

## Local dev (optional)

Create a `.dev.vars` file (gitignored) with:
```
SQUARE_ACCESS_TOKEN=the_sandbox_token_here
```
Then `wrangler dev` runs the worker locally against Square sandbox.
