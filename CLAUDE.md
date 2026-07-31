# Sake Kitty Cards Site

Small-vendor Pokémon card website. Owner: Nick Williams. Contact: nick@sakekittycards.com (customer-facing). The `sakekittycards@gmail.com` Google account is the underlying inbox / Web3Forms recipient, but Nick does **not** want it shown anywhere on the public site — always use `nick@sakekittycards.com` in mailto: links and display copy.

## Stack

- **Host:** GitHub Pages, auto-deploys on push to `main` at https://github.com/sakekittycards/sakekittycards.github.io
- **Domain:** sakekittycards.com (GoDaddy DNS → GitHub Pages)
- **Tech:** vanilla HTML/CSS/JS, no framework, no build step
- **Cache-buster:** `?v=N` on style.css and main.js. Bump when shipping CSS/JS.
- **Fonts:** Bangers (display) + Inter (body), Google Fonts
- **Forms:** Web3Forms (access key is inline in trade-in.html, grading-prep.html, contact.html) → routes to sakekittycards@gmail.com inbox under the hood, but customer-facing display always uses nick@sakekittycards.com
- **Card data:** TCGdex (`api.tcgdex.net`, MIT — English catalog: names/numbers/sets/images ONLY, its `pricing` block is never read because TCGdex can't sublicense TCGplayer/Cardmarket data) + TCG CSV via our Cloudflare Worker proxy at `https://tcgcsv-proxy.nwilliams23999.workers.dev` (English sealed + Japanese + price backfill). pokemontcg.io was dropped 2026-07-30 (57% failure rate after the Scrydex acquisition).

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
- `shipping.html` — "How to Pack Your Cards" guide. Pure content page (no forms/data). Four packing tiers (1 / up-to-10 / 10-19 / 20+), DO NOT rules, clear-sleeve rules, shipping/extra tips. Visuals are cropped photo strips at `assets/shipping/tier{1-4}.png` (extracted from the original ChatGPT infographic). Linked from nav and footer between Sell/Trade and Grading Prep on every page.
- `faq.html`, `about.html`, `contact.html` — info pages

## Conventions

- Nav and footer are **identical on every page**. When renaming or restructuring, touch all pages or delegate to an agent.
- Bump cache-buster (`style.css?v=N` and `main.js?v=N`) on every page when shipping CSS/JS.
- **SEO baseline (every customer-facing page):** `<link rel="canonical">` + `og:title/description/image/url/type` + `twitter:card/title/description/image`. Shared `og-image.png` (1200×630). Pattern matches `index.html`. Twitter card meta is purely metadata — Nick doesn't need a Twitter account.
- **A11y baseline (every page):** `<a class="skip-link" href="#main">Skip to main content</a>` as first child of `<body>`, and `<main id="main">` on the wrapper. CSS in `style.css` (`.skip-link` rule). Nav + footer logo `<img>` tags carry explicit `width`/`height` to prevent CLS.
- Commit messages: short conversational summary, then `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. See `git log` for style.
- **Branch workflow:** all work happens on `dev`. Claude commits + pushes to `dev` (non-default branch, no harness wall). When ready to deploy, Nick clicks "Merge pull request" on the open `dev → main` PR — that's the deploy moment, GitHub Pages rebuilds from `main`. After merge, Claude runs `git pull` on dev to fast-forward to the new main. Do NOT push directly to `main` — the harness blocks it. The previous "small edits go straight to main" note is retired.
- Typography baseline: body copy 14–15px, headings use Bangers with gradient fill. Don't drop below 13px for readable copy.

## Customer-facing forms — Sell/Trade and Grading Prep are paired

`trade-in.html` and `grading-prep.html` share the same lookup architecture. **Any change to lookup-form mechanics ships to BOTH files in the same PR.** Form-specific concerns stay specific (pricing display + condition multipliers on Sell/Trade; service tiers + turnaround + Card Prep on Grading Prep). Purpose-specific features don't auto-port — the rule is about visual/mechanical consistency, not blanket symmetry.

### Search source layering (raw cards, both forms)

| Language | Search source(s) | Notes |
|---|---|---|
| English | TCGdex API (live, `dexSearch()` — catalog only, rows carry `tcgplayer.prices: {}` and `_dex: true`) + `assets/en-cards.json` (TCG CSV cat 3, ~12k entries) + `assets/all-cards-fallback.json` (PC, tertiary safety net) | All three fire in parallel; deduped by lowercased name+number. TCGdex wins for shared cards (nicer images); when an en-static row collides with a dex row, the dex row inherits `_enStaticProductId` from the static twin (dex rows are priceless — without the graft they'd fall out of the pricing chain). Pokémon TCG *Pocket* (digital) sets are excluded via the `tcgp` serie list + hardcoded snapshot. en-static fills gaps TCGdex misses; PC catches what neither has. |
| Japanese | pre-built `assets/jp-cards.json` (~15k entries from `tcgcsv.com/tcgplayer/85`) + TCG CSV groups via the `tcgcsv-proxy` worker for set-name search | Static index is character-name searchable; worker path handles set-hint searches |
| English sealed | TCG CSV groups via `tcgcsv-proxy` | — |
| Chinese | **EXCLUDED from raw search and Grading Prep entirely.** Allowed ONLY in the Sell/Trade graded card form (autocomplete pulls from PC fallback with CN badge, `[CN]` prefix on add). | Per user policy 2026-05-04 |

Sealed JP (booster boxes, ETBs) — included in the Japanese dropdown section since the UX is the same. Customer-side filtering happens at click time.

### Pricing chain (raw cards, in order — first hit wins)

1. **`_enStaticProductId` / `_fallbackProductId`** resolved via `/tcg/market` — dex/static rows that carry a productId (including the en-static→dex collision graft) go straight to TCGplayer's published Market Price
2. **TCG CSV `marketPrice`** by set+number (`lookupTcgCsvSinglePrice`) — same TCGplayer Market Price the reprice pipeline anchors on. Number matching handles exact, promo-prefix-stripped, and slash/zero-pad forms ("74" ↔ "74/73" ↔ "074"); TCGdex promo set names map to TCG CSV group names via `_SET_NAME_ALIASES` ("SVP Black Star Promos" → "SV: Scarlet & Violet Promo Cards")
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

### Grading Prep — locked business rules (don't drift)

- **Card Prep = penny sleeve + card saver. NOT top loaders.** Don't reword to include "top-load" — Card Prep doesn't ship in top loaders. (Top loaders are a Tier-1 packing requirement on the shipping guide; that's different.)
- **Error cards go to PSA OR CGC**, not just CGC. Customers can pick either. Don't revert to CGC-only without confirming.
- **Screening disclaimer (locked phrase):** "Screening does not guarantee a specific grade. Final grades are determined by PSA, CGC, or Beckett." Appears on grading-prep.html twice (top trust banner + above submit button). Reuse verbatim in any related copy.
- **CTA copy:** Submit button reads "Submit Grading Prep Request" (was "Send Request"). Failure-state reset uses the same string.
- **Submission Choice + Turnaround panels are conditionally hidden** — Submission Choice only renders when at least one card has a Card Prep service selected; Turnaround only renders when Card Prep is selected AND submitting through us. Both reveals are intentional; don't make them always-visible.
- **Form fields:** Name + Email (required) · Phone or Instagram Handle (optional) · Hand-Off Preference radio (Mail In default / In Person) · Notes (optional) · Terms checkbox (required). The submission worker payload + Web3Forms email both carry `phone` + `handoff`.

### Worker — `sakekitty-prices` (`workers/prices/`)

Cloudflare Worker. Endpoints:
- `GET /health`
- `GET /lookup?q=<query>` — 130point graded sold-listing scrape (legacy, used by trade-in graded "Check sold prices" link)
- `GET /tcg/market?productId=<id>` — TCGplayer mpapi `/pricepoints`. Returns `{ok, market, printings:[{type,market}]}`. Picks highest non-null market across printings.
- `GET /tcg/lastsold?productId=<id>` — TCGplayer mpapi `/latestsales`. Returns trimmed-mean recent sold avg.
- `GET /dev/raw?q=<query>` — debug passthrough.

Edge-cached 6h via `caches.default`. Deploy: `cd workers/prices && wrangler deploy`. URL: `https://sakekitty-prices.nwilliams23999.workers.dev`.

### Static indexes (built locally, checked into git, lazy-loaded by both forms)

- `assets/en-cards.json` (~830 KB) — 12,818 EN non-sealed cards from TCG CSV (categoryId 3) at $3 floor. Built 2026-05-07. Build: `python scripts/build_en_card_index.py` (~10 min).
- `assets/jp-cards.json` (~1.0 MB) — 15,567 JP non-sealed cards from TCG CSV (categoryId 85) at $3 floor. Build: `python scripts/build_jp_card_index.py` (~8 min).
- `assets/all-cards-fallback.json` (~1.5 MB) — 27,262 unique-by-productId Pokemon entries from PriceCharting (English + Japanese + Chinese) at $3 floor. Tertiary safety net — fires when neither TCGdex nor en-static had the card. Build: `python scripts/build_all_cards_index.py`.
- `assets/pc-graded.json` (~2.0 MB) — 47,020 entries with per-grade values keyed by productId (or `pc:<id>` for Chinese). Build: `python scripts/build_pc_graded_index.py`.

All three build scripts auto-download a fresh PriceCharting CSV from the user's saved subscription URL at `~/.claude/pricecharting_csv_url.txt`. Re-run scripts after PC publishes a new CSV; commit the regenerated JSONs.

### Cart persistence + Clear All

Both forms persist their cart to `localStorage` on every change (keys: `sk_tradein_v1` / `sk_gradingprep_v1`, schema-versioned). `Clear All` button sits next to the "Your List" / "Your Cards" header inside the orange-glow container. Confirmation goes through the branded `window.skConfirm({...})` modal in `main.js` (centered, Sake Kitty logo, Bangers gradient title, ESC + Enter shortcuts) — drop-in replacement for `window.confirm()`.

### Bangers heading gotcha

Bangers' character feet sit further below the baseline than a normal line-box allocates, and `-webkit-background-clip:text` crops anything outside the box. Headings using Bangers + gradient text-fill need `padding: 2px 0 6px` (or similar bottom padding) to render descenders cleanly. Pattern is documented inline at `.cart-drawer-header h3` in style.css.

## Business rules (relevant to code)

- **Shipping policy** (live values per main.js, doc synced 2026-06-11): **Free shipping over $100, flat $5 under**. Applies to apparel, merch, cards, sealed — anything direct on the site. Constants in main.js: `SK_SHIP_FLAT_FEE = 5` + `SK_FREE_SHIP_THRESHOLD = 100`. Cart drawer shows "FREE" when threshold met + an "Add $X for free shipping" upsell hint when under. Stated on faq.html shipping FAQ + shop.html trust strip + cart drawer empty-state. Why the threshold approach: flat-bake-into-product would under-price heavy sealed orders (boxes/cases cost $12-40 to ship); threshold lets high-value orders absorb their own ship cost while cheap orders still cover the flat $5. Shipping insurance is **$1.50 per $100** (`SK_INSURANCE_RATE_PER_100 = 1.50`), kicks in once the insurable subtotal hits $100 — stated on faq.html (both the visible FAQ + JSON-LD) and shop.html trust strip; keep all three in sync with the constant. (Prior doc said $50 free / $1 insurance — both were stale vs. the shipped code.)
- **No plushies on the site (yet).** Don't add "plushies" to customer-facing copy. Once Nick has actual plushie SKUs in Square, restore the references to faq.html shipping copy + shop.html section subs (was removed 2026-05-01).
- **No direct-sale singles on the site (yet).** Singles are listed on TCGPlayer only. Don't claim direct-on-this-site singles availability in homepage hero / shop section sub / meta descriptions. Trade-in BUYS singles (keep that copy intact). Once direct singles are listed, restore the references (was removed 2026-05-01).
- **Trade-in tiers (unified $100/$500/$1,000 breakpoints; sealed premium + `<$5` retired 2026-07-06).** Codified in `trade-in.html` `RATES` const + matrix panel + the buy-offer PDF engine (`scripts/graded-uploader/_offer_engine.py` `raw_rate`). Mirrors the tcgenie app id-54 matrix.
  - **Singles**: <$100 70/80 · $100–$499 80/90 · $500–$999 85/95 · ≥$1,000 90/100
  - **Sealed**:  <$100 80/90 · $100–$499 83/93 · $500–$999 86/96 · ≥$1,000 90/100  (premium ladder — sealed earns more at every band)
  - **Graded**:  <$100 NOT ACCEPTED · $100–$499 80/90 · $500–$999 85/95 · ≥$1,000 90/100
  - The old `<$5 65/80` tier was retired 2026-07-06 to match the app matrix (screenshot-driven). Singles <$5 now buy at 70/80, sealed <$5 at 80/90.
  - Graded under $100 isn't accepted — slab cost ($25-30 for grading) outweighs the card. Matrix shows ✕ in that cell with footnote explanation. Form falls through to singles `RATES.base` (70/80) if a low-value graded card is added so quotes stay sane even when the policy guidance is bypassed. All other graded bands match singles/sealed exactly. 90% cash hard cap at $1,000+. **Cash was bumped +5pts to match the booth across all tiers (2026-07-03); credit unchanged.** New sub-$5 band: singles & sealed under $5 buy at **65% cash / 80% credit** (handling cost outweighs the bump on low-value singles) — `RATES.low`. Cash-vs-credit spread is now +10pts on most tiers (+15 on the sub-$5 band) — still nudges customers toward credit, which cycles back into booth purchases via Square gift card. Headline banner reads "Up to 90% cash · 100% trade credit". History: rates dropped 10pts uniformly 2026-05-12 then rebalanced same day to the current asymmetric model (cash -5 vs booth, credit matches booth).
- **Unsorted-bulk by-weight tier** (added 2026-05-12): top row of the bulk table. **$1.50/lb cash · $2.50/lb trade credit** for English Pokémon only. **No basic energy cards. No jumbo / oversized cards.** Powered by a `unit: 'lb'` field on the `BULK_RATES` row that flips the rate-cell display from "$X" to "$X /lb" and the modal suffix from "per card" to "per lb". Pattern reusable for any future weight-priced tier.
- **Bulk rates:** 13 categories (12 per-card + the unsorted by-weight tier above), defined in `BULK_RATES` array in trade-in.html. **English Pokémon only on bulk** — Japanese/Chinese not accepted at bulk rates (graded and high-value singles in those languages are fine via the per-card form). **Jumbo / oversized cards (4x6" or larger) are not accepted at any tier** — bulk, raw, sealed, or graded. Stated in the trade-in intro paragraph + bulk-section sub copy + email-templates.md template #2. Keep in sync if categories change. Rates were rebalanced data-driven 2026-05-05 against TCGplayer mpapi /latestsales sold-avg (cheapest card per category as the floor, buy at 60%) — see commit history for the table. History: Bulk CGC + Bulk PSA/BGS graded buckets were removed 2026-05-05 — graded sells via the per-card form (cert # + value). Illustration Rare (S&V), Secret/Hyper Rare, and Trainer/Galarian Gallery removed 2026-05-05 — those have real value and route through the per-card singles tiers instead. GX was split out from "GX, EX, or V" into its own row 2026-05-05 (different era, different bulk price). Radiant and Amazing Rare split apart 2026-05-05 (Amazing Rare is a much rarer pull). Bottom singles tier label is "Non-bulk Singles under $100" so customers don't confuse the 70/80% rate with bulk.
- **Payment methods:** Venmo, PayPal, Cash App. **Zelle is NOT an option.** Square in progress (see below).
- **Local-vendor inventory policy** (locked 2026-05-06): Sake Kitty sells at Florida card shows AND online. Site stock can lag a real-time in-person sale on slabs / sealed / raw singles. **Every order is reviewed before we charge.** If something just sold at a booth, we offer refund / swap / hold same-day. Apparel + merch are POD (Printful) and never go OOS. Customer-facing copy lives on `shop.html` (cyan banner above inventory), `product.html` (inline note under Add-to-Cart), and `faq.html` (top FAQ entry). All three use the cyan tone with 📍 icon and the "We're local vendors" opener — reuse verbatim if surfacing on a new page (e.g., cart drawer).
- **Contrast baseline** (locked 2026-05-06 after two sunlight-readability bumps): `--muted: rgba(255,255,255,0.85)` and `--dim: rgba(255,255,255,0.65)`. Don't lower these — Nick reads the site on his phone in direct sunlight at outdoor shows. Body text minimum is 13px; reserve <12px for decorative eyebrows / badges / pills only. `html, body { overflow-x: hidden; max-width: 100% }` is also locked — defense against any rogue child element forcing horizontal scroll on phone.

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
- TCGdex collapses printings: one row per card, no 1st Edition / Shadowless / Holo distinction (same limitation pokemontcg.io had). Variant-specific rows come from en-static / the printings expansion.
- Variant keywords ("1st", "unlimited", "shadowless") in the trade-in search flip `dexSearch` to oldest-first ordering (`oldestFirst`), since modern cards don't have those variants. TCGdex has no release dates, so "oldest" is a hardcoded series ladder (`_DEX_SERIES`) — coarse, sort-preference only.
- OneDrive + git: you'll see benign CRLF / LF warnings on every add. Ignore them.
- Wake up script: `main.js` injects the lava-lamp SVG goo filter + nav blobs on every page. Easter egg: click same nav blob 5 times to unlock one page-drip animation.

## Local scripts

- `scripts/upload-variant-images.mjs` — batch-upload images to Square and attach them to item variations (e.g., per-color shirt photos). Needs `SQUARE_ACCESS_TOKEN` as an env var and a `mapping.json` inside the target folder. See `scripts/README.md` for the full flow and how to find variation IDs.

## Repo + deploy flow

- Repo: https://github.com/sakekittycards/sakekittycards.github.io
- Every push to `main` triggers GitHub Pages build (~1–3 min). No CI, no tests, no linting.
- Cloudflare Worker (`tcgcsv-proxy`) lives at `workers/tcgcsv/` (promoted 2026-07-30 from a dashboard-pasted `cloudflare-worker.js`; deploy with `npx wrangler deploy` from that folder). Its upstream fetches MUST send the custom `User-Agent` — tcgcsv.com 401-blocks unidentified clients, which took the proxy down for everyone on 2026-07-30. Error responses are `no-store` (the old worker stamped public/6h on 401s and browsers cached the outage); the site calls it with `?b=2` to bust those poisoned browser caches.

## Email templates

`email-templates.md` in the project root has copy-paste templates for replying to trade-in / buylist / store-credit customers. Update the templates when business rules change (rate tiers, shipping, payment methods).
