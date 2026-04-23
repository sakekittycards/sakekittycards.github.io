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
- `shop.html` — placeholder product grid; will become cart-based storefront once Square is wired
- `events.html` — interactive calendar + event list; event schema supports optional `hours` and `type: 'whatnot'`
- `vendors.html` — Nick, Jonathan Delia, Joshua Noplis
- `trade-in.html` — "Sell / Trade" unified page: card search (singles/sealed/Japanese/graded) AND bulk rates. Submits via Web3Forms with cards + bulk subtotals + grand total.
- `buylist.html` — **redirect only** to trade-in.html (legacy link support). Don't restore old content.
- `faq.html`, `about.html`, `contact.html` — info pages

## Conventions

- Nav and footer are **identical on every page**. When renaming or restructuring, touch all pages or delegate to an agent.
- Bump cache-buster (`style.css?v=N` and `main.js?v=N`) on every page when shipping CSS/JS.
- Commit messages: short conversational summary, then `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. See `git log` for style.
- Small edits go straight to `main` (no branching). This is a solo project.
- Typography baseline: body copy 14–15px, headings use Bangers with gradient fill. Don't drop below 13px for readable copy.

## Business rules (relevant to code)

- **Shipping policy:** free on orders $35+, flat $5 below. Applies to cards, plushies, sealed, everything. Currently stated in `faq.html` only.
- **Trade-in tiers:** Singles 60% cash / 75% credit · Sealed 75/85 · Graded <$1k 75/85 · Graded ≥$1k 85/95. Codified in `trade-in.html`.
- **Bulk rates:** 15 categories, defined in `BULK_RATES` array in trade-in.html. Keep in sync if categories change.
- **Payment methods:** Venmo, PayPal, Cash App. **Zelle is NOT an option.** Square in progress (see below).

## In-flight / next up

- **Square cart integration.** Hosted-checkout flow: Cloudflare Worker generates Square Payment Links on demand, customer redirects to Square. Worker deployed at `https://sakekitty-square.nwilliams23999.workers.dev` (sandbox). Endpoints: `/health`, `/items`, `POST /checkout`. Code in `workers/square/`.
  - **Sandbox Application ID:** `sandbox-sq0idb-yd8K60RrJoZVHoyWjCJVxQ`
  - **Sandbox Location ID:** `L609TAK1JWN13`
  - **Production Location ID:** `LWJ5EY6TCBCGV` (for swap when we go live)
  - **Production Application ID:** TBD — user grabs from Developer Dashboard when we flip to production
  - **Access token** lives as Cloudflare Worker secret (`wrangler secret put SQUARE_ACCESS_TOKEN`), never in repo. Has been rotated due to a chat leak during setup.
  - **Cart UI not yet built.** Plan: shop.html pulls products from Worker `/items`; cart drawer UI in main.js with localStorage persistence; checkout button POSTs cart to Worker `/checkout` → redirect to Square hosted checkout.
- **First plushie / merch product** not yet in the site. Will seed the cart when user adds the first product.
- **Store credit.** Leaning toward manual ledger until customer volume justifies Square Gift Cards.
- **eBay developer API** — pending approval; will wire up graded card live pricing + sealed price comparison when access is granted.

## Known gotchas

- `trade-in.html` is ~1.7k lines — Read tool errors on full-file reads. Use `offset`/`limit` or Grep.
- pokemontcg.io only tracks "holofoil" for Base Set Charizard — no 1st Edition / Shadowless distinction. API limitation, not a bug.
- Variant keywords ("1st", "unlimited", "shadowless") in the trade-in search re-sort the pokemontcg.io query to vintage-first, since modern cards don't have those variants.
- OneDrive + git: you'll see benign CRLF / LF warnings on every add. Ignore them.
- Wake up script: `main.js` injects the lava-lamp SVG goo filter + nav blobs on every page. Easter egg: click same nav blob 5 times to unlock one page-drip animation.

## Repo + deploy flow

- Repo: https://github.com/sakekittycards/sakekittycards.github.io
- Every push to `main` triggers GitHub Pages build (~1–3 min). No CI, no tests, no linting.
- Cloudflare Worker (`tcgcsv-proxy`) is deployed separately from its own small project. Not in this repo.

## Email templates

`email-templates.md` in the project root has copy-paste templates for replying to trade-in / buylist / store-credit customers. Update the templates when business rules change (rate tiers, shipping, payment methods).
