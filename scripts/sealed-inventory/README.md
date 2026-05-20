# Sealed Inventory — Master Ledger Setup (Day 1)

This is the operational home for the sealed-product inventory system. The master ledger lives in **Airtable**, with Cloudflare Workers handling sync to Square (website) and TCGplayer CSV (TCGplayer Direct). Coming online incrementally.

## Architecture (recap)

```
                Airtable: Sealed Inventory  (single source of truth)
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          Square API   TCGplayer CSV   Show ledger
          (live sync)  (manual upload) (booth count)
              │             │
              ▼             ▼
       order webhook   daily sales CSV
              │             │
              └────►  Airtable decrement  ◄────┘
```

## Day 1 deliverables (this commit)

- This README with the full Airtable schema spec
- `_initial_import.csv` — seed file with the 13 SKUs from the inventory brief, pre-tagged with platform + tier

## Step-by-step: create the Airtable base

### 1. Create the base + table

1. Go to https://airtable.com → **Add a base** → **Start from scratch**
2. Name the base: **Sake Kitty — Sealed Inventory**
3. Rename the default `Table 1` to `Sealed Inventory`
4. (Optional but recommended) Add this base to the existing grading-prep workspace so all Sake Kitty data lives in one place

### 2. Define fields (in this order — formulas reference earlier fields)

| # | Field name | Type | Options / Formula |
|---|---|---|---|
| 1 | `sku` | Single line text | Primary field. Pattern: `SEAL-{SET}-{TYPE}` (e.g. `SEAL-ASCH-ETB`) |
| 2 | `product_name` | Single line text | Customer-facing name |
| 3 | `set` | Single line text | Set name (e.g. "Ascended Heroes", "Prismatic Evolutions") |
| 4 | `language` | Single select | Options: `EN`, `JP` |
| 5 | `product_type` | Single select | `BoosterBox`, `ETB`, `Bundle`, `Blister`, `Tin`, `Pack`, `Deck`, `CollectionBox`, `Promo`, `Accessory` |
| 6 | `on_hand` | Number (integer) | Physical units owned |
| 7 | `website_alloc` | Number (integer) | Reserved for Square / website |
| 8 | `tcgplayer_alloc` | Number (integer) | Reserved for TCGplayer Direct |
| 9 | `show_reserve` | Number (integer) | Held back for booth (not listed online) |
| 10 | `cost_basis` | Currency (USD) | What we paid per unit |
| 11 | `tcg_market_price` | Currency (USD) | Auto-pulled from `sakekitty-prices` worker later; manual for now |
| 12 | `liquidity_tier` | Single select | `High`, `Medium`, `Low`, `Collector` |
| 13 | `platform_assignment` | Single select | `Website`, `TCGplayer`, `Both`, `ShowOnly` |
| 14 | `is_homepage_featured` | Checkbox | Show on home page "featured sealed" section |
| 15 | `target_roi_pct` | Number (percent) | Used by pricing formulas (default 25%) |
| 16 | `website_price` | Formula | See below |
| 17 | `tcgplayer_price` | Formula | See below |
| 18 | `manual_price_override` | Currency (USD) | If set, both `website_price` and `tcgplayer_price` use this |
| 19 | `location` | Single select | `Storage A`, `Storage B`, `Booth`, `In-Transit` |
| 20 | `received_date` | Date | When the product arrived |
| 21 | `last_updated` | Last modified time | Auto |
| 22 | `notes` | Long text | Free-form |
| 23 | `published` | Checkbox | When true, sync workers will push this row to its assigned platforms |
| 24 | `alloc_drift` | Formula | Reconciliation guard. `IF({website_alloc} + {tcgplayer_alloc} + {show_reserve} > {on_hand}, "⚠️ OVER", "OK")` |

### 3. Pricing formulas

Both pricing formulas honor `manual_price_override` first; otherwise they apply tier-based markup to `tcg_market_price`.

**`website_price` formula** (paste into the field):
```
IF(
  {manual_price_override},
  {manual_price_override},
  IF(
    {liquidity_tier} = "High",     {tcg_market_price} * 1.10,
    IF({liquidity_tier} = "Medium", {tcg_market_price} * 1.15,
      IF({liquidity_tier} = "Low",  {tcg_market_price} * 1.25,
        {tcg_market_price} * 1.30)
    )
  )
)
```

**`tcgplayer_price` formula:**
```
IF(
  {manual_price_override},
  {manual_price_override},
  IF(
    {liquidity_tier} = "High",     {tcg_market_price} * 1.00,
    IF({liquidity_tier} = "Medium", {tcg_market_price} * 1.05,
      IF({liquidity_tier} = "Low",  {tcg_market_price} * 1.10,
        BLANK())
    )
  )
)
```

`Collector` tier returns `BLANK()` on TCGplayer because those SKUs aren't listed there — the website carries them exclusively at a 30%+ premium.

### 4. Import the seed file

1. With the `Sealed Inventory` table open, click the table dropdown → **Import data** → **CSV file**
2. Select `scripts/sealed-inventory/_initial_import.csv`
3. Match columns by name; let Airtable create new rows
4. Confirm import

### 5. Fill in the gaps (one-time, ~10 min)

For each "ALL"-marked SKU (the ones I left `on_hand` blank), do a physical count and update:
- `on_hand`
- `website_alloc` (usually = `on_hand` for website-only SKUs)
- `cost_basis` (what you paid per unit)
- `tcg_market_price` (look up the current TCGplayer market price)
- `received_date`

For SKUs I pre-filled (Prismatic ETBs, First Partner Packs, 151 Bundles, Destined Rivals BB), confirm the quantities match your actual stock and tweak if needed.

Then flip `published` to true on every row that's ready to list.

## Inventory brief — initial allocation

This is what's encoded in `_initial_import.csv`. Source: your strategic brief.

### Website / Show (Collector tier — no TCGplayer listing)
| SKU | Product | Allocation |
|---|---|---|
| `SEAL-ASCH-ETB` | Ascended Heroes ETB (EN) | ALL → website |
| `SEAL-DR-ETB` | Destined Rivals ETB (EN) | ALL → website |
| `SEAL-M2INF-BB` | M2 Inferno X Booster Box (JP) | ALL → website |
| `SEAL-NINJA-BB` | Ninja Spinner Booster Box (JP) | ALL → website |
| `SEAL-KAMI-BB` | Adventure on Kami's Island Booster Box (JP) | ALL → website |
| `SEAL-151-MTIN` | 151 Mini Tin (EN) | ALL → website |
| `SEAL-MFERA-BOX` | Mega Feraligatr ex Box (EN) | ALL → website |
| `SEAL-MDIANCIE-DECK` | Mega Battle Deck (Mega Diancie ex) | ALL → website |

### Split allocation (Medium tier — both platforms)
| SKU | Product | Web | TCG | Total |
|---|---|---|---|---|
| `SEAL-PRE-ETB` | Prismatic Evolutions ETB | 10 | 5 | 15 |
| `SEAL-FP-PACK` | First Partner Pack | 22 | 22 | 44 |

### TCGplayer only (High tier — liquidity)
| SKU | Product | TCG qty |
|---|---|---|
| `SEAL-FS-BLISTER` | Fusion Strike Blister | ALL → tcg |
| `SEAL-151-BUND` | 151 Booster Bundle | 8 |
| `SEAL-DR-BB` | Destined Rivals Booster Box | 2 |

## What's next (Day 2+)

- **Day 2 (DONE 2026-05-20)**: Added `POST /admin/sync-sealed-inventory` to the existing `sakekitty-square` worker (cleaner than a parallel worker — Square + Airtable plumbing already exists). Reads Airtable rows where `published=true` + `website_alloc>0`, upserts each as a Square ITEM with one ITEM_VARIATION at `website_price`, sets inventory count to `website_alloc`, writes `square_item_id` + `square_variation_id` back to Airtable for stable re-syncs.

  Test (dry-run): `curl -X GET -H "X-Sake-Admin-Token: $TOKEN" "https://sakekitty-square.nwilliams23999.workers.dev/admin/sync-sealed-inventory?dry_run=1"`

  Real sync: same URL, POST, drop `dry_run=1`.

- **Day 2b (DONE 2026-05-20)**: Added `GET /admin/export-tcgplayer-csv` to the same worker. Streams a CSV of every `published=true` row with `tcgplayer_alloc>0` and `tcgplayer_product_id` set. Columns: `TCGplayer Id, SKU, Product Name, Set, Total Quantity`. **Quantity only — pricing is handled by your separate TCG marketplace pipeline.**

  Download the CSV:
  ```
  curl -H "X-Sake-Admin-Token: $TOKEN" \
    "https://sakekitty-square.nwilliams23999.workers.dev/admin/export-tcgplayer-csv" \
    -o sealed-tcgplayer-qty-$(date +%Y-%m-%d).csv
  ```

  Browser-friendly JSON preview:
  ```
  curl -H "X-Sake-Admin-Token: $TOKEN" \
    "https://sakekitty-square.nwilliams23999.workers.dev/admin/export-tcgplayer-csv?json=1"
  ```

  Workflow: this CSV updates `Total Quantity` on existing TCGplayer listings. Match it against your TCGplayer Seller Hub current-listings download, copy quantities across, re-upload. Or upload as-is if the columns match.
- **Day 3**: Wire Square webhook `order.created` → Worker → Airtable decrement (atomic on_hand + website_alloc).
- **Day 4**: Build `GET /export/tcgplayer.csv` — streams TCGplayer Direct upload CSV from Airtable rows where `published=true` + `tcgplayer_alloc>0`. Manual download → upload to TCGplayer Seller Hub.
- **Day 5**: Build `POST /ingest/tcgplayer-sales` — accepts TCGplayer's daily sales-export CSV, decrements `on_hand` + `tcgplayer_alloc` per row.
- **Day 6**: Daily reconciliation cron — emails Nick if any row has `alloc_drift = "⚠️ OVER"`.
- **Day 7**: Document the 5-min daily workflow (review drift alert, push TCG sales CSV if any).

## Overselling guardrail (how this prevents it)

Each platform only ever sees its own allocation bucket, never `on_hand`. With Prismatic ETBs at 10/5:
- Square publishes inventory = 10. Website can sell at most 10.
- TCGplayer CSV uploads qty = 5. TCG can sell at most 5.
- Neither platform can dip into the other's pool because they don't see it.

When one pool depletes (e.g. TCG sells out at 0), Nick reallocates in Airtable (`tcgplayer_alloc=0`, `website_alloc=15`), next sync re-publishes the new counts to both platforms.

The `alloc_drift` formula field catches any data-entry mistake where the three buckets sum to more than `on_hand`.
