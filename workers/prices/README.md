# sakekitty-prices Worker

Cloudflare Worker that scrapes recent sold-listing prices for graded Pokémon cards, so trade-in.html can show live market data instead of asking users to guess.

## Endpoints

- `GET  /health`       — liveness check
- `GET  /lookup?q=<query>` — searches 130point for sold listings, returns summary stats
- `GET  /dev/raw?q=<query>` — dumps raw HTML from 130point for parser debugging (sandbox only)

## Scraping approach

- Spoofs a modern Chrome User-Agent + full browser header set (Accept, Referer, Sec-Fetch-*, etc.)
- Fetches `https://130point.com/sales/?q=<query>&search=1`
- Regex-extracts dollar prices, filters to a plausible range, summarizes avg/median/min/max
- Caches responses via `caches.default` for 6 hours to avoid hammering upstream

## Known fragility

- 130point may fingerprint more aggressively and block Cloudflare IPs. When that happens, `/lookup` returns `{ok: false, error: 'HTTP 403'}` and the front-end shows a graceful fallback ("Check Card Ladder").
- The regex parser grabs dollar amounts; noisy numbers (shipping, navigation prices) get filtered by a sane price range. If parsing accuracy degrades, inspect `/dev/raw` output and refine.

## Deploy

```sh
cd workers/prices
wrangler deploy
```

No secrets required.
