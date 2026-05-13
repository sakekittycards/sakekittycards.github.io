# sakekitty-vendor — Vendor Portal Worker

Cloudflare Worker that backs `vendor-portal.html`.  Handles magic-link auth
(no passwords), session cookies, vendor + bookings storage, and outbound
email via Resend.

## Endpoints

### Public (no auth)

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/vendor/login` | `{ email }` | Email a magic-link to the vendor (or silently no-op if email isn't on the list). Always returns 200. |
| GET  | `/vendor/verify?token=...` | — | Exchange a magic-link token for a session cookie. |
| GET  | `/vendor/me` | — | Return `{ authenticated, email, vendor }` based on cookie. |
| POST | `/vendor/logout` | — | Clear the session cookie. |

### Admin (`X-Sake-Admin-Token` header gated)

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/admin/vendor/upsert` | `{ email, name, bookings: [{event, startDate, endDate?, owed, paid}] }` | Add or update a vendor + their bookings. |
| GET  | `/admin/vendor/list` | — | Dump every vendor record. |
| POST | `/admin/vendor/delete` | `{ email }` | Remove a vendor. |
| POST | `/admin/blast` | `{ email }` or `{ email, custom: { subject, html, text } }` | Email one vendor their booking status (or a one-off custom message). |
| POST | `/admin/blast-all` | — | Email every vendor their booking status. |

## One-time setup

1. **Resend account.** Sign up at <https://resend.com> (free tier = 3K emails/month).  Add `sakekittycards.com` as a sending domain and verify it via the DNS records Resend tells you to add at your registrar (GoDaddy). Until verification clears, Resend will only let you send to your own verified email.
2. **API key.** Resend → Settings → API Keys → create a key with "Sending access" scope.
3. **Admin token.** Pick any random string Nick will use to call the `/admin/*` endpoints. Easiest: `node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"`. Save this somewhere — you'll need it to add/update vendors.
4. **KV namespace.**
   ```bash
   cd workers/vendor-portal
   npx wrangler kv namespace create VENDOR_KV
   ```
   Paste the returned id into `wrangler.toml` (`[[kv_namespaces]] id = "..."`).
5. **Push secrets.**
   ```bash
   npx wrangler secret put RESEND_API_KEY    # paste the Resend key
   npx wrangler secret put ADMIN_TOKEN       # paste the random admin token
   ```
6. **Deploy.**
   ```bash
   npx wrangler deploy
   ```
   Wrangler prints the URL (e.g. `https://sakekitty-vendor.nwilliams23999.workers.dev`). The frontend in `vendor-portal.html` already calls this URL; update the constant there if you use a custom subdomain.

## Adding the first vendors

After deploy, seed the three current co-vendors. Replace `<ADMIN_TOKEN>` with the value you set above and `andrew@...` with each vendor's real address:

```bash
# Andrew — $200 owed for SuperCon Jul 18-19
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/vendor/upsert \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "andrew@example.com",
    "name": "Andrew",
    "bookings": [
      {"event":"TCG Trade N Play SuperCon","startDate":"2026-07-18","endDate":"2026-07-19","owed":200,"paid":false}
    ]
  }'

# Delia — Jul 26 Card Party $115 owed + Aug 9 Cardichu $140 paid
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/vendor/upsert \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "delia@example.com",
    "name": "Delia",
    "bookings": [
      {"event":"Card Party S. Florida 4","startDate":"2026-07-26","owed":115,"paid":false},
      {"event":"Cardichu — Pompano Beach","startDate":"2026-08-09","owed":140,"paid":true}
    ]
  }'

# Josh — $115 owed for Card Party Jul 26
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/vendor/upsert \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "josh@example.com",
    "name": "Josh",
    "bookings": [
      {"event":"Card Party S. Florida 4","startDate":"2026-07-26","owed":115,"paid":false}
    ]
  }'
```

## Sending the booking emails

Once vendors are seeded:

```bash
# Email one vendor their current booking status
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/blast \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"andrew@example.com"}'

# Or blast all three at once
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/blast-all \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>"
```

The email contains a "Open the vendor portal →" button.  Vendor clicks it, gets to `vendor-portal.html`, enters their email, gets a one-time magic link, and they're in.

## Marking a payment as paid

```bash
# Easiest: re-send the full upsert with the booking flipped to paid:true
curl -X POST https://sakekitty-vendor.nwilliams23999.workers.dev/admin/vendor/upsert \
  -H "X-Sake-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"andrew@example.com","name":"Andrew","bookings":[{"event":"TCG Trade N Play SuperCon","startDate":"2026-07-18","endDate":"2026-07-19","owed":200,"paid":true}]}'
```

(A nicer `/admin/booking/update` partial-update endpoint can be added later.)
