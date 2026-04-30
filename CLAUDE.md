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
- Small edits go straight to `main` (no branching). This is a solo project.
- Typography baseline: body copy 14–15px, headings use Bangers with gradient fill. Don't drop below 13px for readable copy.

## Business rules (relevant to code)

- **Shipping policy:** flat $5 on every order — no free-shipping tier. Applies to cards, plushies, sealed, everything. Stated on faq.html + shop.html; cart logic in main.js uses `SK_SHIP_FLAT_FEE`.
- **Trade-in tiers:** Raw singles tier by market value — <$25: 60/75, $25–$50: 70/80, ≥$50: 80/90 · Sealed 75/85 · Graded <$1k 75/85 · Graded ≥$1k 85/95. Codified in `trade-in.html`. The tiered raw-singles rates (vs. a flat 60/75) avoid being uncompetitive on chase cards where booth would normally pay 80–90%.
- **Bulk rates:** 15 categories, defined in `BULK_RATES` array in trade-in.html. Keep in sync if categories change.
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
