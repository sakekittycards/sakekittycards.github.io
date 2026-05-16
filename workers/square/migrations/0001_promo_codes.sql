-- Promo code redemption tables for the show campaign.
-- Single-use codes, server-side enforcement at checkout.

CREATE TABLE IF NOT EXISTS promo_codes (
  code            TEXT PRIMARY KEY,           -- the 4-char code, e.g. "K7P3"
  campaign        TEXT NOT NULL,              -- e.g. "may-2026-shows"
  offer_type      TEXT NOT NULL,              -- "buyer" / "seller" / "grader" / "any"
  discount_kind   TEXT NOT NULL,              -- "fixed_amount" or "percent"
  discount_value  INTEGER NOT NULL,           -- cents for fixed_amount; basis points (e.g. 1000 = 10%) for percent
  min_subtotal    INTEGER NOT NULL DEFAULT 0, -- cents — min order subtotal before discount
  expires_at      TEXT,                       -- ISO date, NULL = never
  status          TEXT NOT NULL DEFAULT 'active',  -- "active" / "used" / "disabled"
  used_at         TEXT,                       -- ISO timestamp set on first redemption
  used_by_email   TEXT,                       -- email of redeemer
  used_amount     INTEGER,                    -- cart subtotal at redemption (cents)
  used_order_id   TEXT,                       -- Square order_id
  used_channel    TEXT,                       -- "site" / "booth" / "tcgplayer" / "buylist" / "grading"
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_promo_status ON promo_codes(status);
CREATE INDEX IF NOT EXISTS idx_promo_campaign ON promo_codes(campaign);

-- Append-only audit log so we can see every validation attempt + outcome.
CREATE TABLE IF NOT EXISTS promo_attempts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  code            TEXT NOT NULL,
  outcome         TEXT NOT NULL,              -- "valid" / "used" / "not_found" / "below_min" / "expired" / "disabled" / "redeemed"
  attempted_at    TEXT NOT NULL DEFAULT (datetime('now')),
  cart_subtotal   INTEGER,                    -- cents (when known)
  email           TEXT,                       -- when supplied
  channel         TEXT,                       -- "site" usually
  ip_hash         TEXT,                       -- short hash of CF-Connecting-IP for abuse audit
  ua_hash         TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_code ON promo_attempts(code);
CREATE INDEX IF NOT EXISTS idx_attempts_time ON promo_attempts(attempted_at);
