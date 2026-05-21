# Sealed image fix sheet

`_image_fix_sheet.csv` is a snapshot of all 25 sealed items currently
live on Square, with the columns you need to swap in cleaner images.

## Why this exists

TCGplayer stock photos have wildly different native framing — some
crop tight to the product, some have a half-inch of whitespace. Side
by side on the Just Listed grid the disparity shows: Whimsicott (Single
Pack Blister, tight crop) looks twice the size of Lycanroc (same
product type, padded source image). Same story for Premium Checklane
Blisters (Alakazam too big), Mini Tins, and so on.

Already shipped as a band-aid: bumped the sealed-product card padding
from 8% to 14% in `style.css`. That makes the gap less obvious but
doesn't fully fix it — only consistent source images do.

## Columns

| Column | Purpose |
|---|---|
| `square_item_id` | The Square catalog item ID. Don't edit. |
| `product_type` | Bucket label so similar SKUs cluster together. |
| `product_name` | Current item name. Don't edit. |
| `current_image_url` | The image Square is using right now (open in browser to compare). |
| `new_image_url` | **Fill this in** for any row you want to swap. Leave blank to skip. |
| `notes` | Free-text. Optional. |

## How to find better source images

Within a `product_type` bucket, pick one row whose `current_image_url`
already renders well, and use that same source style for the others.
Easy wins:

- **Single Pack Blister** — pick the most-padded reference (Lycanroc
  is fine), get the others to match that framing.
- **Premium Checklane Blister** — these are bigger products by nature
  but should still match each other (Alakazam, Togekiss, Horsea).
- **Mini Tin** — three SKUs, should be visually identical size.
- **Booster Box** — naturally largest, four SKUs.

Sources that tend to be consistent: TCGplayer category pages, Pokemon
Center's product images, the publisher's announcement PNGs.

## How to apply the sheet

Once you've filled in `new_image_url` for the rows you want changed,
run (TBD — script lives in `apply_image_fix_sheet.py`, will be added
once you've staged a batch).

Skeleton flow:
1. Script reads each row with a non-empty `new_image_url`
2. Posts to `POST /admin/replace-sealed-image` on the Cloudflare worker
3. Worker downloads the image, uploads to Square, deletes the old
   image object, sets the new one as primary
4. Reports back per-row status

Each replace costs ~3 Square subrequests (delete + upload + item
upsert with image_ids preserved), so the free-tier 50/request cap
limits one batch to ~16 rows. If you need to do more, the script
should auto-chunk with a `?sku=X` filter.
