-- 0004: on-demand batch minting + scan tracking (2026-07)
-- Adds a human batch label + scan counters so the print app can mint fresh
-- batches on demand and the admin dashboard can show scanned/used/unused.
-- Safe to re-run: ADD COLUMN is idempotent only if the column is absent, so
-- run this exactly once per DB (D1 has no "ADD COLUMN IF NOT EXISTS").

ALTER TABLE promo_codes ADD COLUMN batch_label TEXT;
ALTER TABLE promo_codes ADD COLUMN scanned_at  TEXT;
ALTER TABLE promo_codes ADD COLUMN scan_count  INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_promo_batch   ON promo_codes(campaign);
CREATE INDEX IF NOT EXISTS idx_promo_scanned ON promo_codes(scanned_at);
