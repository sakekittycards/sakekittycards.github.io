# Sake Kitty Cards Site

Small-vendor Pokémon card website. Owner: Nick Williams. Contact: sakekittycards@gmail.com.

## Stack

- **Host:** GitHub Pages, auto-deploys on push to `main` at https://github.com/sakekittycards/sakekittycards.github.io
- **Domain:** sakekittycards.com (GoDaddy DNS → GitHub Pages)
- **Tech:** vanilla HTML/CSS/JS, no framework, no build step
- **Cache-buster:** `?v=N` on style.css and main.js. Bump when shipping CSS/JS.
- **Fonts:** Bangers (display) + Inter (body), Google Fonts
- **Forms:** Web3Forms (access key is inline in trade-in.html and contact.html) → sakekittycards@gmail.com
- **Card data:** pokemontcg.io (English singles) + TCG CSV via our Cloudflare Worker proxy at `https://tcgcsv-proxy.nwilliams23999.workers.dev` (English sealed + Japanese)

## Pages

- `index.html` — home, glowing hero, feature grid
- `shop.html` — product grid pulled from Square via the worker. Each card is a link to `product.html?id=<productId>` — no inline variant selector or Add-to-Cart (moved to PDP).
- `product.html` — product detail page. URL: `?id=<productId>`. Pulls from `/items` and filters client-side. Renders image gallery (product + per-variation images, dedupped), variant buttons (color/size), and Add to Cart. Main image auto-swaps to variant image when a variant with its own photo is selected.
- `events.html` — interactive calendar + event list; event schema supports optional `hours` and `type: 'whatnot'`
- `team.html` — Nick, Jonathan Delia, Joshua Noplis (nav links this page as "Our Team")
- `vendors.html` — **redirect only** to team.html (legacy link support). Don't restore old content.
- `trade-in.html` — "Sell / Trade" unified page: card search (singles/sealed/Japanese/graded) AND bulk rates. Submits via Web3Forms with cards + bulk subtotals + grand total.
- `buylist.html` — **redirect only** to trade-in.html (legacy link support). Don't restore old content.
- `track.html` — customer-facing grading-prep order tracker. Takes `?order=SK-YYYY-XXXXXX`, shows an 8-stage status bar, card list, and PSA cert numbers once graded. Hits `GET /grading/track` on the worker.
- `faq.html`, `about.html`, `contact.html` — info pages

## Conventions

- Nav and footer are **identical on every page**. When renaming or restructuring, touch all pages or delegate to an agent.
- Bump cache-buster (`style.css?v=N` and `main.js?v=N`) on every page when shipping CSS/JS.
- Commit messages: short conversational summary, then `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. See `git log` for style.
- **Branch workflow:** all work happens on `dev`. Claude commits + pushes to `dev` (non-default branch, no harness wall). When ready to deploy, Nick clicks "Merge pull request" on the open `dev → main` PR — that's the deploy moment, GitHub Pages rebuilds from `main`. After merge, Claude runs `git pull` on dev to fast-forward to the new main. Do NOT push directly to `main` — the harness blocks it. The previous "small edits go straight to main" note is retired.
- Typography baseline: body copy 14–15px, headings use Bangers with gradient fill. Don't drop below 13px for readable copy.

## Customer-facing forms — Sell/Trade and Grading Prep are paired

`trade-in.html` and `grading-prep.html` share the same lookup architecture. **Any change to lookup-form mechanics ships to BOTH files in the same PR.** Form-specific concerns stay specific (pricing display + condition multipliers on Sell/Trade; service tiers + turnaround + Card Prep on Grading Prep). Purpose-specific features don't auto-port — the rule is about visual/mechanical consistency, not blanket symmetry.

### Search source layering (raw cards, both forms)

| Language | Search source(s) | Notes |
|---|---|---|
| English | pokemontcg.io API + PriceCharting `assets/all-cards-fallback.json` (only kicks in when pokemontcg.io returned <5 results) | pokemontcg.io is the primary; PC fills modern set + vintage gaps |
| Japanese | pre-built `assets/jp-cards.json` (29k entries from `tcgcsv.com/tcgplayer/85`) + TCG CSV groups via the `tcgcsv-proxy` worker for set-name search | Static index is character-name searchable; worker path handles set-hint searches |
| English sealed | TCG CSV groups via `tcgcsv-proxy` | — |
| Chinese | **EXCLUDED from raw search and Grading Prep entirely.** Allowed ONLY in the Sell/Trade graded card form (autocomplete pulls from PC fallback with CN badge, `[CN]` prefix on add). | Per user policy 2026-05-04 |

Sealed JP (booster boxes, ETBs) — included in the Japanese dropdown section since the UX is the same. Customer-side filtering happens at click time.

### Pricing chain (raw cards, in order — first hit wins)

1. **pokemontcg.io's `tcgplayer.prices.market`** — embedded in pokemontcg.io payload, daily refresh
2. **TCG CSV `marketPrice`** by set+number — same TCGplayer Market Price the reprice pipeline anchors on
3. **TCGplayer `/v2/product/{id}/pricepoints`** via the `sakekitty-prices` worker (`/tcg/market`) — TCGplayer's PUBLISHED Market Price (same number their product page shows). Edge-cached 6h.
4. **TCGplayer `/v2/product/{id}/latestsales`** via the `sakekitty-prices` worker (`/tcg/lastsold`) — trimmed avg of last ~10 sold transactions. Drops `ListingWithPhotos` rows (off-center copies). Edge-cached 6h.
5. **PriceCharting `loose-price`** from `assets/pc-graded.json` — final fallback only. PC's loose-price diverges from TCGplayer in some cases; never overrides a TCGplayer number.
6. **Customer manual entry** — inline numeric input on the list line for cards no source has data on.

`COND_MULT` then discounts by condition (NM 1.0 / LP 0.85 / MP 0.70 / HP 0.50 / DMG 0.30) for the Market display + Cash + Credit offers (all three move in lockstep).

### Pricing chain (graded cards, Sell/Trade graded form)

`assets/pc-graded.json` (~47k entries keyed by TCGplayer productId) — auto-fills the "Estimated value" field when the customer picks a graded card from the autocomplete + selects a grade. Switching grades after picking a card re-fills. Never overwrites a value the user typed. Column mapping (verified 2026-05-02 against PC's web pages):
- `loose-price` → Ungraded
- `new-price` → PSA 8
- `graded-price` → PSA 9
- `box-only-price` → PSA 9.5 / BGS 9.5
- `manual-only-price` → PSA 10
- `bgs-10-price` → BGS 10
- CGC + SGC mapped to PSA-equivalent columns (PC doesn't track separately for Pokemon)

Synthetic `pc:<id>` productIds (Chinese cards) skip the TCG endpoints and go straight to the PC index (TCGplayer doesn't carry Chinese).

### Grading Prep extras

Each card in the list shows an inline **profit-margin panel** under the service tier row:
- Ungraded NM market value
- Each PSA / BGS grade that clears the ~$30 fee floor (Card Prep $5 + PSA Value Plus $25), with the profit-over-ungraded margin in green
- Quiet "No grade clears the fee floor" note when nothing's profitable

ProductId resolution: JP cards have it from the static index; English cards get it via name+set+number lookup against `all-cards-fallback.json`.

### Worker — `sakekitty-prices` (`workers/prices/`)

Cloudflare Worker. Endpoints:
- `GET /health`
- `GET /lookup?q=<query>` — 130point graded sold-listing scrape (legacy, used by trade-in graded "Check sold prices" link)
- `GET /tcg/market?productId=<id>` — TCGplayer mpapi `/pricepoints`. Returns `{ok, market, printings:[{type,market}]}`. Picks highest non-null market across printings.
- `GET /tcg/lastsold?productId=<id>` — TCGplayer mpapi `/latestsales`. Returns trimmed-mean recent sold avg.
- `GET /dev/raw?q=<query>` — debug passthrough.

Edge-cached 6h via `caches.default`. Deploy: `cd workers/prices && wrangler deploy`. URL: `https://sakekitty-prices.nwilliams23999.workers.dev`.

### Static indexes (built locally, checked into git, lazy-loaded by both forms)

- `assets/jp-cards.json` (~1.9 MB) — 29,278 JP non-sealed cards from TCG CSV. Build: `python scripts/build_jp_card_index.py` (~8 min).
- `assets/all-cards-fallback.json` (~2.7 MB) — 48,461 unique-by-productId Pokemon entries from PriceCharting (English + Japanese + Chinese). Used as the search-only fallback for cards pokemontcg.io / TCG CSV miss. Build: `python scripts/build_all_cards_index.py`.
- `assets/pc-graded.json` (~2.0 MB) — 47,020 entries with per-grade values keyed by productId (or `pc:<id>` for Chinese). Build: `python scripts/build_pc_graded_index.py`.

All three build scripts auto-download a fresh PriceCharting CSV from the user's saved subscription URL at `~/.claude/pricecharting_csv_url.txt`. Re-run scripts after PC publishes a new CSV; commit the regenerated JSONs.

### Cart persistence + Clear All

Both forms persist their cart to `localStorage` on every change (keys: `sk_tradein_v1` / `sk_gradingprep_v1`, schema-versioned). `Clear All` button sits next to the "Your List" / "Your Cards" header inside the orange-glow container. Confirmation goes through the branded `window.skConfirm({...})` modal in `main.js` (centered, Sake Kitty logo, Bangers gradient title, ESC + Enter shortcuts) — drop-in replacement for `window.confirm()`.

### Bangers heading gotcha

Bangers' character feet sit further below the baseline than a normal line-box allocates, and `-webkit-background-clip:text` crops anything outside the box. Headings using Bangers + gradient text-fill need `padding: 2px 0 6px` (or similar bottom padding) to render descenders cleanly. Pattern is documented inline at `.cart-drawer-header h3` in style.css.

## Business rules (relevant to code)

- **Shipping policy:** flat $5 on every order — no free-shipping tier. Applies to apparel, merch, future card/sealed drops, everything. Stated on faq.html + shop.html; cart logic in main.js uses `SK_SHIP_FLAT_FEE`.
- **No plushies on the site (yet).** Don't add "plushies" to customer-facing copy. Once Nick has actual plushie SKUs in Square, restore the references to faq.html shipping copy + shop.html section subs (was removed 2026-05-01).
- **No direct-sale singles on the site (yet).** Singles are listed on TCGPlayer only. Don't claim direct-on-this-site singles availability in homepage hero / shop section sub / meta descriptions. Trade-in BUYS singles (keep that copy intact). Once direct singles are listed, restore the references (was removed 2026-05-01).
- **Trade-in tiers:** Raw singles tier by market value — <$100: 70/80, ≥$100: 80/90, ≥$300: 85/95, ≥$500: 90/100 · Sealed 80/90 · Graded <$500 80/90 · Graded $500–$999 85/95 · Graded ≥$1k 90/100. Codified in `trade-in.html` (`RATES` const) and the rate-card panel rendered on the page. Updated 2026-05-05: sealed bumped 75→80, graded re-tiered into three bands. Trade credit follows cash + 10pts on every tier. Singles tier up steeply on chase cards to stay competitive with major buylists; bottom tier starts at 70% so we're not undercutting walk-up sellers on common rares.
- **Bulk rates:** 12 categories, defined in `BULK_RATES` array in trade-in.html. **English Pokémon only on bulk** — Japanese/Chinese not accepted at bulk rates (graded and high-value singles in those languages are fine via the per-card form). Stated in the bulk-section sub copy + email-templates.md template #2. Keep in sync if categories change. Rates were rebalanced data-driven 2026-05-05 against TCGplayer mpapi /latestsales sold-avg (cheapest card per category as the floor, buy at 60%) — see commit history for the table. History: Bulk CGC + Bulk PSA/BGS graded buckets were removed 2026-05-05 — graded sells via the per-card form (cert # + value). Illustration Rare (S&V), Secret/Hyper Rare, and Trainer/Galarian Gallery removed 2026-05-05 — those have real value and route through the per-card singles tiers instead. GX was split out from "GX, EX, or V" into its own row 2026-05-05 (different era, different bulk price). Radiant and Amazing Rare split apart 2026-05-05 (Amazing Rare is a much rarer pull). Bottom singles tier label is "Non-bulk Singles under $100" so customers don't confuse the 70/80% rate with bulk.
- **Payment methods:** Venmo, PayPal, Cash App. **Zelle is NOT an option.** Square in progress (see below).

## In-flight / next up

- **Square cart integration.** Hosted-checkout flow: Cloudflare Worker generates Square Payment Links on demand, customer redirects to Square. Worker deployed at `https://sakekitty-square.nwilliams23999.workers.dev`. Endpoints: `/health`, `/items`, `POST /checkout`. Code in `workers/square/`. `/items` enriches Square catalog data with per-variant mockup URLs from Printful (see below) so apparel color swatches on product.html can swap the main image.
  - **Sandbox Application ID:** `sandbox-sq0idb-yd8K60RrJoZVHoyWjCJVxQ`
  - **Sandbox Location ID:** `L609TAK1JWN13`
  - **Production Location ID:** `LWJ5EY6TCBCGV` (for swap when we go live)
  - **Production Application ID:** TBD — user grabs from Developer Dashboard when we flip to production
  - **Access token** lives as Cloudflare Worker secret (`wrangler secret put SQUARE_ACCESS_TOKEN`), never in repo. Has been rotated due to a chat leak during setup.
  - **Cart UI not yet built.** Plan: shop.html pulls products from Worker `/items`; cart drawer UI in main.js with localStorage persistence; checkout button POSTs cart to Worker `/checkout` → redirect to Square hosted checkout.
- **Printful integration** (live). Worker merges Printful per-variant mockups into the `/items` response. Source: `GET /sync/products` and `GET /sync/products/{id}` with `X-PF-Store-Id` header. Mapping key: Printful's `sync_variant.external_id` == Square's variation ID. Mockup preference: `files[type=preview].preview_url` (branded mockup with logo), fallback `product.image` (plain color shot). Results cached at the Cloudflare edge for 5 min so shop loads don't trigger 7+ Printful calls per request. If Printful call fails, `/items` still returns Square data without mockups (fail-open).
  - **Printful Store ID:** `18064906` (Square-connected store)
  - **Secret:** `PRINTFUL_ACCESS_TOKEN` (set via `wrangler secret put`, never committed)
- **Grading-prep tracker** (live). Worker exposes `POST /grading/submit` and `GET /grading/track?order=...`, backed by an Airtable `Submissions` table. Submissions from `grading-prep.html` fire-and-forget in parallel: the worker writes a tracking row to Airtable, Web3Forms emails Nick — if either fails the customer still gets served from the other. Order numbers: `SK-YYYY-XXXXXX` (6 random chars, excludes 0/O/1/I). Tracker page `track.html` reads from the worker; `Customer Name` is returned as first name only to keep the guess-a-number attack surface small. **PSA scraping is NOT set up** — the Collectors.com SSO requires JS-rendered auth which Cloudflare Workers can't do. Status updates are manual (Nick edits Airtable) for now; email-based automation via Gmail Apps Script is the future path.
  - **Airtable base:** `appG9mKWxmwq9ZbTq` → `Submissions` table (`tbldRJdVmABVQskRY`)
  - **Secret:** `AIRTABLE_TOKEN` (set via `wrangler secret put`, scoped to just this base)
  - **Schema note:** Airtable API doesn't allow creating formula / createdTime / lastModifiedTime fields. `Order Number` is a plain text field, populated by the worker. Built-in `createdTime` on records is available through the API for auditing.
- **First plushie / merch product** not yet in the site. Will seed the cart when user adds the first product.
- **Store credit = Square Gift Cards.** Each trade-in credit is issued as a Square gift card (unique code, balance loaded). Booth staff verify + redeem via the Square POS app; same code will work at the online checkout once the cart is live. No custom site-side balance lookup is planned — copy on `trade-in.html` directs customers to email/DM if they want to check between visits. Setup happens in the Square Dashboard (Gift Cards must be enabled before the first credit is issued).
- **eBay developer API** — pending approval; will wire up graded card live pricing + sealed price comparison when access is granted.

## Known gotchas

- `trade-in.html` is ~1.7k lines — Read tool errors on full-file reads. Use `offset`/`limit` or Grep.
- pokemontcg.io only tracks "holofoil" for Base Set Charizard — no 1st Edition / Shadowless distinction. API limitation, not a bug.
- Variant keywords ("1st", "unlimited", "shadowless") in the trade-in search re-sort the pokemontcg.io query to vintage-first, since modern cards don't have those variants.
- OneDrive + git: you'll see benign CRLF / LF warnings on every add. Ignore them.
- Wake up script: `main.js` injects the lava-lamp SVG goo filter + nav blobs on every page. Easter egg: click same nav blob 5 times to unlock one page-drip animation.

## Local scripts

- `scripts/upload-variant-images.mjs` — batch-upload images to Square and attach them to item variations (e.g., per-color shirt photos). Needs `SQUARE_ACCESS_TOKEN` as an env var and a `mapping.json` inside the target folder. See `scripts/README.md` for the full flow and how to find variation IDs.

## Repo + deploy flow

- Repo: https://github.com/sakekittycards/sakekittycards.github.io
- Every push to `main` triggers GitHub Pages build (~1–3 min). No CI, no tests, no linting.
- Cloudflare Worker (`tcgcsv-proxy`) is deployed separately from its own small project. Not in this repo.

## Email templates

`email-templates.md` in the project root has copy-paste templates for replying to trade-in / buylist / store-credit customers. Update the templates when business rules change (rate tiers, shipping, payment methods).
