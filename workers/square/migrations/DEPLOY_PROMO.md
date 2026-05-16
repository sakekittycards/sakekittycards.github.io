# Deploy the promo-code system

Everything's pushed to `dev`. Three steps remain — they require **wrangler authentication** (you don't have a CLOUDFLARE_API_TOKEN configured yet), so you need to run them yourself.

Total time: ~10 minutes including testing.

---

## 1. Authenticate wrangler (one time, ~1 min)

Open PowerShell or any terminal in the repo:

```
cd C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\workers\square
wrangler login
```

This opens your browser, you click "Allow", done.

---

## 2. Create the D1 database + run migrations (~3 min)

```
wrangler d1 create sk-promo-codes
```

You'll get back something like:
```
✅ Successfully created DB 'sk-promo-codes'
[[d1_databases]]
binding = "DB"
database_name = "sk-promo-codes"
database_id = "abc12345-6789-...-..."
```

**Copy the `database_id` UUID** and paste it into `wrangler.toml` replacing the placeholder `REPLACE_WITH_D1_UUID_AFTER_CREATE`:

```
[[d1_databases]]
binding       = "PROMO_DB"
database_name = "sk-promo-codes"
database_id   = "abc12345-...-..."   # ← your real UUID here
```

Now run the schema + seed migrations against the remote D1:

```
wrangler d1 execute sk-promo-codes --file=migrations/0001_promo_codes.sql --remote
wrangler d1 execute sk-promo-codes --file=migrations/0002_seed_promo_codes.sql --remote
```

The seed migration inserts all 500 codes. Should take ~5 seconds.

---

## 3. Deploy the worker (~30 sec)

```
wrangler deploy
```

That's it — worker is now live with the new endpoints.

---

## 4. Merge dev → main to deploy the site (~2 min)

The frontend changes (cart drawer with promo input, etc.) are on `dev`. Merge the PR to deploy:

- Open https://github.com/sakekittycards/sakekittycards.github.io/pulls
- There should be an auto-opened or recent PR titled "Show promo codes: D1-backed single-use redemption in cart + Square discount."
- If not, run from the repo root: `gh pr create --base main --head dev`
- Click "Merge pull request"
- GitHub Pages rebuilds in ~2 min

---

## 5. Smoke test (~3 min)

1. Open https://sakekittycards.com/shop.html
2. Add an item that gets cart subtotal ≥ $100
3. Open cart drawer
4. Type any code from `promo_codes.csv` (e.g. `234P`)
5. Click "Apply" — should show green "✓ 234P applied — $10.00 off"
6. Total updates to subtract the $10
7. Click "Pay with Square" — Square hosted checkout opens showing the discount line
8. **Don't actually pay** for the test — just confirm the discount line appears

Then in another tab, hit the validate endpoint to confirm the test code is now marked used:
```
curl -X POST https://sakekitty-square.nwilliams23999.workers.dev/promo/validate \
  -H "Content-Type: application/json" \
  -d '{"code":"234P","cart_subtotal":15000}'
```
Should return `{"valid":false,"reason":"already_redeemed"}` if you completed a real payment, or `{"valid":true,...}` if you only previewed.

(Note: redemption locks the code when /checkout creates the Payment Link — even if the customer doesn't complete payment. This is intentional — Square Payment Links carry the discount; if we waited for actual payment we'd open a race window. The trade-off is some codes get "burned" by customers who abandon the checkout. Worst case: you re-enable a few via D1: `UPDATE promo_codes SET status='active' WHERE code IN ('XXXX', 'YYYY');`)

---

## Quick admin queries (handy in Cloudflare D1 dashboard)

```sql
-- How many redeemed so far this weekend?
SELECT COUNT(*) FROM promo_codes WHERE status = 'used';

-- Who redeemed today?
SELECT code, used_by_email, used_amount/100.0 AS amount_usd, used_at
  FROM promo_codes
 WHERE used_at LIKE date('now') || '%'
 ORDER BY used_at DESC;

-- All validation attempts (including failures — abuse audit)
SELECT code, outcome, COUNT(*) AS n
  FROM promo_attempts
 GROUP BY code, outcome
 ORDER BY n DESC
 LIMIT 30;

-- Re-enable a specific code that got burned by an abandoned cart
UPDATE promo_codes
   SET status = 'active', used_at = NULL, used_by_email = NULL,
       used_amount = NULL, used_order_id = NULL, used_channel = NULL
 WHERE code = 'XXXX';

-- Disable a specific code (e.g., if you handed it to the wrong person)
UPDATE promo_codes SET status = 'disabled' WHERE code = 'XXXX';
```
