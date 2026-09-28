-- Wholesale first-touch auto-reply.
--
-- Apply with:
--   wrangler d1 execute sk-promo-codes --file=migrations/0005_wholesale_autoreply.sql --remote
--
-- Three tables:
--   _log     every classification decision, including shadow-mode ones
--   _senders the one-auto-reply-per-address-ever ledger
--   _config  runtime switches, so the mode and the kill switch change
--            without a deploy

-- Every decision the classifier makes, whatever the mode. This is the
-- shadow-mode record and the audit trail; nothing is ever deleted from it.
CREATE TABLE IF NOT EXISTS wholesale_autoreply_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  gmail_message_id TEXT   NOT NULL,
  gmail_thread_id TEXT,
  -- The real sender, after unwrapping a web3forms submission.
  sender_email    TEXT    NOT NULL,
  sender_name     TEXT,
  subject         TEXT,
  via_web_form    INTEGER NOT NULL DEFAULT 0,
  -- 'drop' | 'route' | 'reply'
  decision        TEXT    NOT NULL,
  -- Comma-separated REASONS codes, verbatim from the classifier.
  reasons         TEXT    NOT NULL,
  -- Mode in force when the decision was taken: shadow | draft | live
  mode            TEXT    NOT NULL,
  -- What actually happened: none | drafted | sent | labelled | error
  action          TEXT    NOT NULL DEFAULT 'none',
  -- Gmail id of the draft or sent message, when there is one.
  result_message_id TEXT,
  error           TEXT,
  -- Set when Nick approves a draft unedited; drives the 10-clean-drafts gate.
  draft_approved_clean INTEGER,
  -- Set once the routed message has been replied to by a human.
  human_replied_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_war_log_msg
  ON wholesale_autoreply_log (gmail_message_id);
CREATE INDEX IF NOT EXISTS idx_war_log_created
  ON wholesale_autoreply_log (created_at);
CREATE INDEX IF NOT EXISTS idx_war_log_sender
  ON wholesale_autoreply_log (sender_email);
CREATE INDEX IF NOT EXISTS idx_war_log_decision
  ON wholesale_autoreply_log (decision, created_at);

-- One auto-reply per sender address, ever. Kept separate from the log so the
-- guarantee survives any future log pruning.
CREATE TABLE IF NOT EXISTS wholesale_autoreply_senders (
  sender_email    TEXT PRIMARY KEY,
  first_seen_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  replied_at      TEXT,
  reply_message_id TEXT,
  -- 1 when this address is a known contact or existing customer, which
  -- routes on sight regardless of content.
  known_contact   INTEGER NOT NULL DEFAULT 0,
  note            TEXT
);

CREATE TABLE IF NOT EXISTS wholesale_autoreply_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Start in shadow mode with the kill switch ON. Nothing can go out until
-- both are changed deliberately.
INSERT OR IGNORE INTO wholesale_autoreply_config (key, value) VALUES
  ('mode',            'shadow'),
  ('kill_switch',     '1'),
  ('cap_per_hour',    '3'),
  ('cap_per_day',     '10'),
  ('clean_drafts_required', '10'),
  ('catalogue_url',   'https://sakekittycards.com/wholesale-pokemon'),
  ('reply_from',      'wholesale@sakekittycards.com');

-- The known-contact list is NOT seeded here.
--
-- THIS REPOSITORY IS PUBLIC. Customer email addresses must never be
-- committed to it. Seed the list separately from the private seed file kept
-- alongside the wholesale handoff notes:
--
--   wrangler d1 execute sk-promo-codes --remote \
--     --file="<handoff folder>/0005a_known_contacts.private.sql"
--
-- Until that runs, no address is marked known_contact, so existing
-- customers are protected only by the content rules and by the
-- one-reply-per-sender ledger. Seed it before leaving shadow mode.
