-- Add claim columns so /promo/claim can atomically assign a unique code
-- to each show-page signup. A code goes: active -> claimed -> used.
-- "Claimed" still permits redemption; it just tracks who got the code.

ALTER TABLE promo_codes ADD COLUMN assigned_to_email TEXT;
ALTER TABLE promo_codes ADD COLUMN assigned_at TEXT;
CREATE INDEX IF NOT EXISTS idx_promo_assigned ON promo_codes(assigned_to_email);
