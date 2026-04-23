# scripts/

Local utilities for admin tasks. Not used by the site or the worker at runtime.

## upload-variant-images.mjs

Batch-uploads images to Square Catalog and attaches each one to a specific item variation.

Use it when you have a shirt (or any item) with color/size variants and want to attach a different photo per variant without clicking through the Square Dashboard UI for each one.

### What you need

1. **Node 18+** (already installed if you use wrangler).
2. **Your Square access token.** Grab it fresh from Square Developer Dashboard → your app → Credentials (Production tab). Do **not** commit it anywhere. Rotate it after the batch is done if you want to be extra safe.
3. **A folder** containing your images and a `mapping.json` file.

### Folder layout

```
my-shirt-uploads/
  black.jpg
  navy.jpg
  heather-grey.jpg
  mapping.json
```

### mapping.json format

```json
[
  { "file": "black.jpg",        "variationId": "W5Y4ZABCDEF...", "caption": "Black",   "isPrimary": true },
  { "file": "navy.jpg",         "variationId": "X8A2BGHIJKL...", "caption": "Navy" },
  { "file": "heather-grey.jpg", "variationId": "K1P7QMNOPQR...", "caption": "Heather Grey" }
]
```

Fields:
- `file` — filename inside the folder. JPG/PNG/GIF. ≤15MB.
- `variationId` — the Square catalog **variation** ID (not the item ID). See "Finding variation IDs" below.
- `caption` — optional. Defaults to the filename stem.
- `isPrimary` — optional. If `true`, this image becomes the variation's primary/hero image.

### Finding variation IDs

Two easy ways:

**Option A — use the worker (fastest):**
```
curl https://sakekitty-square.nwilliams23999.workers.dev/items | jq '.items[] | {name, variations}'
```
Look for your item, then copy the `id` field from each entry inside `variations`. Those are the `variationId` values.

**Option B — Square Dashboard:**
Items → pick the item → each variation row has a "…" menu → "View details" shows the ID in the URL (`.../items/ITEM_ID/variations/VARIATION_ID`).

### Run it

From the repo root:

```bash
SQUARE_ACCESS_TOKEN=your_prod_token_here node scripts/upload-variant-images.mjs ./my-shirt-uploads
```

To hit sandbox instead (for testing against the sandbox catalog):

```bash
SQUARE_ACCESS_TOKEN=your_sandbox_token SQUARE_ENV=sandbox node scripts/upload-variant-images.mjs ./my-shirt-uploads
```

### Output

```
env:     production
folder:  /c/Users/lunar/OneDrive/Desktop/sake-kitty-cards-site/my-shirt-uploads
uploads: 3

  ✓ black.jpg → W5Y4Z...  (image ABCDEFG...)
  ✓ navy.jpg → X8A2B...  (image HIJKLMN...)
  ✓ heather-grey.jpg → K1P7Q...  (image OPQRSTU...)

done. 3 uploaded, 0 failed.
```

After this runs, hit `/items` on the worker and you'll see `variations[i].imageUrl` populated with the new images. The product page will now swap the main photo when a shopper clicks a color.

### Notes

- The script is **idempotent per run** (uses a fresh `idempotency_key` per request) but **not across runs** — running it twice will upload duplicate images. Delete old ones in Square Dashboard if you re-run.
- If one upload fails, the script keeps going and reports the count at the end. The exit code is non-zero if anything failed, so you can chain it in automation.
- The token is read from env, never written to disk or logged.
