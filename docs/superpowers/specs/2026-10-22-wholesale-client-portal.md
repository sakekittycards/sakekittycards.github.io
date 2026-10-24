# Sake Kitty wholesale client portal — design spec

**Date:** 2026-10-22 · **Status:** approved, not built
**Brainstorm:** `~/.claude/handoffs/sk-client-portal-BRAINSTORM-2026-10-22.md`

> This file lives in a **public repo**. No supplier costs, no margins, no
> buyer contact details. Costs are referenced by invoice number only.

## Problem

Wholesale today is three disconnected things:

1. `wholesale-pokemon.html` — public, price-free, says nothing about how to buy.
2. `wholesale.html` — the real price list. Unlinked and `noindex`, shared by
   pasting the URL. Anyone who has ever been sent the link keeps it forever.
3. `POST /sk/wholesale-order` on the TCGenie worker — **emails Nick and Andrew
   and stores nothing.** There is no order record anywhere, so there is nothing
   to show a buyer who asks "any update?".

Two failures follow from that, both of which have already cost real money:

- **Silence.** Nick verifies stock with the supplier out of band. The buyer sees
  nothing happening. Connor went to a competitor; Pritesh sent four messages in
  two days.
- **Price drift.** Catalogue prices are hard-coded in HTML, so updating one is a
  commit. When landed cost moved on two SKUs, the page kept selling below cost
  until someone noticed — the gap that made invoice `SKW-20260928-01` land well
  above what the buyer thought he was asking for.

## Shape

Three layers.

| Layer | Who sees it | Where |
|---|---|---|
| **Public** | anyone | `wholesale-pokemon.html` — wholesale exists, it is an application process, here is how to apply |
| **Application** | applicant → Nick | `/apply` on the portal. Nick vets and decides. **No self-signup.** |
| **Portal** | onboarded buyers | `wholesale.sakekittycards.com` — catalogue, place an order, track it, order history |

`wholesale.html` stops being a secret URL and becomes a redirect to the portal.
Prices move out of the repo and into the database, where Nick can edit them
without a deploy.

## Order lifecycle

Seven stages, picked over a shorter version because "Checking stock" is the
honest answer to "any update?" — it makes the supplier-verification step
visible instead of silent.

```
submitted → checking_stock → quoted → awaiting_payment → paid → shipped → delivered
```

plus terminal `cancelled`. Stages only move forward; `cancelled` is reachable
from anywhere before `shipped`.

**The catalogue price is not binding — the quote is.** The order carries the
listed prices it was submitted at as a snapshot, and the `quoted` stage sets the
real number. This matches the existing R3 presale terms.

**Price negotiation stays out of the portal.** Nick emails or DMs the buyer. The
order sits at its current stage while that happens. No in-portal approve/reject.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Platform | Cloudflare Worker + D1 | Same as everything else here; `vendors.sakekittycards.com` already proves the pattern |
| Where it lives | `workers/wholesale-portal/` in this repo | 6 workers already live in `workers/`; the public-page changes ship in the same PR |
| Language | JavaScript ESM, no build step | Matches `workers/social/`, whose schema imports straight into `node:sqlite` tests. The vendor portal's TypeScript does not |
| Sign-in | Magic link, then optional username + password | Lifted from the vendor portal. No passwords for Nick to reset |
| Admin surface | **Inside the portal**, admin-gated | Nick confirmed 2026-10-22. He flips stages and pastes tracking from his phone at a show; it should be the same app the order lives in |
| Who is admin | Nick **and Andrew**, each with their own login | Nick confirmed 2026-10-22. Separate credentials, not a shared one, so the log can name who did it |
| Catalogue price rule | landed cost ÷ 0.93, rounded up to the dollar | Nick confirmed 2026-10-22. Documented page rule since 2026-09-03. Lists a few dollars above what the ×1.07 invoice charges, so a quote can never land *above* the listed price |
| Money storage | integer cents | The page uses whole dollars today; ÷ 0.93 does not land on one |
| Cart | client-side `localStorage`, re-priced server-side at submit | Keeps the existing dock UX. Client prices are never trusted |

### Prices move into the database

`products` carries both `price_cents` and `cost_cents`. Cost is admin-only and
never rendered to a buyer. The admin product editor refuses to save, and flags
on sight, any row where price is at or below cost.

This is the actual fix for the stale-price problem: the page went underwater
because repricing required a commit and nobody made one. The initial 23 rows are
imported from a CSV generated locally and **never committed** — that is what
keeps prices out of a public repo. (Git history still holds the old ones; that
cannot be undone and is not worth trying to.)

## Data model

`buyers` · `products` · `orders` · `order_items` · `order_events` ·
`magic_tokens` · `sessions` · `audit_log`

- A buyer and an applicant are the same row: `buyers.status` is
  `applied | approved | declined | suspended`. Only `approved` can sign in.
- `order_items` snapshots name, unit and unit price at submit, because the
  catalogue changes underneath an open order.
- `order_events` is the buyer-visible timeline; `audit_log` is the internal one.

### Every change is attributable

Nick asked for this explicitly on 2026-10-22, and it is the reason admins get
individual logins rather than one shared password: a shared credential makes
the log useless the moment two people can use it.

- Each admin password maps to a **name** (`Nick`, `Andrew`), carried on the
  session as `admin_label`. The vendor portal already works this way.
- **Every** admin action that changes state writes one `audit_log` row:
  who, what, which subject, and **the old value and the new value**. A row
  saying `price_updated` without the two numbers is not a log.
- `audit_log` is append-only. Nothing in the codebase updates or deletes a row
  in it, and no admin route exposes a way to.
- `/admin/activity` renders it newest-first for any admin.
- This is enforced by test, not by discipline: a test enumerates every
  state-changing admin route and fails if one of them completes without
  writing an audit row.

## Rules that must hold

- **$1,500 minimum before shipping**, enforced server-side at submit, not only
  in the dock UI.
- **Server re-prices every line from `products` at submit.** The client's posted
  prices are read for nothing.
- **A buyer can only ever load their own orders**, scoped by session, never by
  order reference alone.
- **`wholesale-pokemon.html` must never link to `wholesale.html`** (standing
  rule) — after this it links to the portal's `/apply` instead.
- Order refs keep today's `WS-YYYYMMDD-XXX` format for continuity with invoices
  already in buyers' inboxes.
- Portal pages are `noindex, nofollow` and never enter `sitemap.xml`.

## Email (Resend, via the existing pattern)

| Trigger | To | Notes |
|---|---|---|
| Application received | Nick + Andrew | reply-to the applicant |
| Application approved | applicant | carries a sign-in link |
| Order submitted | Nick + Andrew | reply-to the buyer, same as the current worker |
| Stage changed | buyer | one per stage; `quoted` and `shipped` carry the number |
| Magic link / invite | buyer | lifted verbatim |

## Out of scope

Payment capture (Nick invoices out of band), freight quoting, inventory
decrement, and anything that writes back to TCGenie or Square.

## Open before launch

- DNS: `wholesale.sakekittycards.com` CNAME, same as `vendors.`
- Secrets: `COOKIE_SECRET`, `MAGIC_LINK_SECRET`, `RESEND_API_KEY`,
  `ADMIN_PASSWORD` (Nick), `ADMIN_PASSWORD_ANDREW` (Andrew) — two distinct
  values; issuing them the same password silently destroys attribution
- `wrangler d1 create sake-kitty-wholesale` needs a token with D1:Edit — the
  same permission gap that is still blocking the social engine's database
- 21 of 23 SKUs still carry 2026-09-23 prices against unverified costs
