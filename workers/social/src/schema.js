/**
 * Social engine schema.
 *
 * Applied idempotently on every isolate boot rather than through a migration
 * runner — the same pattern the tcgenie worker settled on after eight separate
 * guarded migration blocks drifted apart. `CREATE TABLE IF NOT EXISTS` and
 * `ALTER TABLE ADD COLUMN` are naturally idempotent; anything else needs a guard
 * and belongs in a numbered file under migrations/ instead.
 *
 * Append only. Never edit an existing line — a deployed database has already run
 * it, so an edit silently applies to new databases only, and the two diverge.
 */
export const SCHEMA_DDL = [
  // ── Events: a normalized mirror of the website's calendar ──────────────────
  // The website is the source of truth. This table is a cache with provenance,
  // never a second place to edit a show. `fingerprint` covers only the fields a
  // post actually states, so fixing a typo in a description does not invalidate
  // an approved graphic, but moving the venue does.
  `CREATE TABLE IF NOT EXISTS events (
     id             TEXT PRIMARY KEY,
     source         TEXT NOT NULL DEFAULT 'events-data.js',
     title          TEXT NOT NULL,
     venue          TEXT,
     address        TEXT,
     city           TEXT,
     state          TEXT,
     event_date     TEXT NOT NULL,
     end_date       TEXT,
     start_time     TEXT,
     end_time       TEXT,
     hours_text     TEXT,
     organizer      TEXT,
     event_url      TEXT,
     website_url    TEXT,
     booth          TEXT,
     description    TEXT,
     flyer_url      TEXT,
     social_url     TEXT,
     kind           TEXT NOT NULL DEFAULT 'show',
     masked         INTEGER NOT NULL DEFAULT 0,
     reveal_at      TEXT,
     status         TEXT NOT NULL DEFAULT 'scheduled',
     content_status TEXT NOT NULL DEFAULT 'new',
     fingerprint    TEXT NOT NULL,
     raw            TEXT,
     first_seen_at  INTEGER NOT NULL,
     created_at     INTEGER NOT NULL,
     updated_at     INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date)`,
  `CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)`,

  // ── Content opportunities ─────────────────────────────────────────────────
  // The unit the automation reasons about. One row per (event, promo kind), id
  // derived from that pair, so the engine can run a thousand times and still
  // produce exactly one 7-day reminder for a given show.
  `CREATE TABLE IF NOT EXISTS opportunities (
     id            TEXT PRIMARY KEY,
     event_id      TEXT NOT NULL,
     kind          TEXT NOT NULL,
     eligible_from TEXT NOT NULL,
     eligible_to   TEXT NOT NULL,
     target_at     INTEGER,
     status        TEXT NOT NULL DEFAULT 'pending',
     item_id       TEXT,
     reason        TEXT,
     created_at    INTEGER NOT NULL,
     updated_at    INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_opps_event ON opportunities(event_id)`,
  `CREATE INDEX IF NOT EXISTS idx_opps_status ON opportunities(status)`,

  // ── Video assets: the approval registry ───────────────────────────────────
  // A row here is NOT permission to publish. `state` plus a hash match is.
  //
  // `sha256` is the hash of the file as last observed; `approved_sha256` is the
  // hash of the exact bytes a human approved. They are separate columns on
  // purpose: re-rendering a short in place changes the first and not the second,
  // and that difference is what stops an edited cut riding a stale approval.
  `CREATE TABLE IF NOT EXISTS video_assets (
     id              TEXT PRIMARY KEY,
     title           TEXT NOT NULL,
     source_path     TEXT NOT NULL,
     final_path      TEXT,
     sha256          TEXT NOT NULL,
     bytes           INTEGER,
     duration_s      REAL,
     width           INTEGER,
     height          INTEGER,
     fps             REAL,
     vcodec          TEXT,
     acodec          TEXT,
     container       TEXT,
     has_audio       INTEGER NOT NULL DEFAULT 1,
     state           TEXT NOT NULL DEFAULT 'RAW',
     approved_at     INTEGER,
     approved_by     TEXT,
     approval_source TEXT,
     approval_note   TEXT,
     approved_sha256 TEXT,
     revoked_at      INTEGER,
     revoked_reason  TEXT,
     caption_draft   TEXT,
     cover_media_id  TEXT,
     media_id        TEXT,
     probe           TEXT,
     created_at      INTEGER NOT NULL,
     updated_at      INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_video_state ON video_assets(state)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_video_source ON video_assets(source_path)`,

  // Every state transition, append-only. "Who approved this and when" must
  // survive a later edit to the video row itself.
  `CREATE TABLE IF NOT EXISTS video_events (
     id         INTEGER PRIMARY KEY AUTOINCREMENT,
     video_id   TEXT NOT NULL,
     from_state TEXT,
     to_state   TEXT NOT NULL,
     actor      TEXT,
     source     TEXT,
     note       TEXT,
     sha256     TEXT,
     at         INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_video_events_vid ON video_events(video_id)`,

  // ── Media assets: rendered images / prepared video, stored in R2 ───────────
  `CREATE TABLE IF NOT EXISTS media_assets (
     id            TEXT PRIMARY KEY,
     kind          TEXT NOT NULL,
     r2_key        TEXT NOT NULL,
     content_type  TEXT NOT NULL,
     bytes         INTEGER,
     width         INTEGER,
     height        INTEGER,
     sha256        TEXT NOT NULL,
     public_token  TEXT NOT NULL,
     template      TEXT,
     source_kind   TEXT,
     source_url    TEXT,
     source_domain TEXT,
     acquisition   TEXT,
     retrieved_at  INTEGER,
     original_name TEXT,
     provenance    TEXT,
     created_at    INTEGER NOT NULL
   )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_media_token ON media_assets(public_token)`,
  `CREATE INDEX IF NOT EXISTS idx_media_sha ON media_assets(sha256)`,

  // ── Content items: the thing that gets published ──────────────────────────
  // `subject_fingerprint` binds the item to the state of its source at approval
  // time. The publisher recomputes it and refuses to send if it moved.
  `CREATE TABLE IF NOT EXISTS content_items (
     id                  TEXT PRIMARY KEY,
     type                TEXT NOT NULL,
     surface             TEXT NOT NULL DEFAULT 'feed',
     status              TEXT NOT NULL DEFAULT 'draft',
     event_id            TEXT,
     opportunity_id      TEXT,
     video_id            TEXT,
     title               TEXT,
     caption             TEXT,
     hashtags            TEXT,
     media_id            TEXT,
     cover_media_id      TEXT,
     warnings            TEXT,
     policy_auto         INTEGER NOT NULL DEFAULT 0,
     subject_fingerprint TEXT,
     approved_at         INTEGER,
     approved_by         TEXT,
     scheduled_for       INTEGER,
     timezone            TEXT NOT NULL DEFAULT 'America/New_York',
     attempts            INTEGER NOT NULL DEFAULT 0,
     last_attempt_at     INTEGER,
     next_retry_at       INTEGER,
     lease_until         INTEGER,
     lease_token         TEXT,
     ig_creation_id      TEXT,
     ig_media_id         TEXT,
     permalink           TEXT,
     published_at        INTEGER,
     failure_reason      TEXT,
     dry_run             INTEGER NOT NULL DEFAULT 0,
     created_at          INTEGER NOT NULL,
     updated_at          INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_items_status ON content_items(status)`,
  `CREATE INDEX IF NOT EXISTS idx_items_sched ON content_items(scheduled_for)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_items_opp ON content_items(opportunity_id)`,

  // ── Publications: one row per publish attempt, successful or not ──────────
  `CREATE TABLE IF NOT EXISTS publications (
     id            TEXT PRIMARY KEY,
     item_id       TEXT NOT NULL,
     attempt       INTEGER NOT NULL,
     mode          TEXT NOT NULL,
     phase         TEXT NOT NULL,
     ok            INTEGER NOT NULL,
     ig_creation_id TEXT,
     ig_media_id   TEXT,
     permalink     TEXT,
     error_kind    TEXT,
     error         TEXT,
     payload       TEXT,
     at            INTEGER NOT NULL
   )`,
  `CREATE INDEX IF NOT EXISTS idx_pubs_item ON publications(item_id)`,

  // ── Performance ───────────────────────────────────────────────────────────
  // Deliberately wide and mostly empty at first. The point today is that the
  // rows exist so that in three months there is history to optimise against;
  // no scheduling decision reads this table yet.
  `CREATE TABLE IF NOT EXISTS insights (
     item_id        TEXT NOT NULL,
     ig_media_id    TEXT NOT NULL,
     collected_at   INTEGER NOT NULL,
     published_at   INTEGER,
     dow            INTEGER,
     hour_local     INTEGER,
     content_type   TEXT,
     impressions    INTEGER,
     reach          INTEGER,
     likes          INTEGER,
     comments       INTEGER,
     shares         INTEGER,
     saved          INTEGER,
     profile_visits INTEGER,
     follows        INTEGER,
     video_views    INTEGER,
     watch_time_ms  INTEGER,
     raw            TEXT,
     PRIMARY KEY (ig_media_id, collected_at)
   )`,

  // ── Human-readable activity stream ────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS activity (
     id       INTEGER PRIMARY KEY AUTOINCREMENT,
     at       INTEGER NOT NULL,
     level    TEXT NOT NULL DEFAULT 'info',
     scope    TEXT NOT NULL,
     subject  TEXT,
     message  TEXT NOT NULL,
     detail   TEXT
   )`,
  `CREATE INDEX IF NOT EXISTS idx_activity_at ON activity(at)`,

  // ── Policy + small key/value state ────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS policy (
     k          TEXT PRIMARY KEY,
     v          TEXT NOT NULL,
     updated_at INTEGER NOT NULL
   )`,
  `CREATE TABLE IF NOT EXISTS meta (
     k TEXT PRIMARY KEY,
     v TEXT NOT NULL
   )`,
];

let ready = false;

export async function ensureSchema(env) {
  if (ready) return;
  let allOk = true;
  for (const ddl of SCHEMA_DDL) {
    try {
      await env.DB.prepare(ddl).run();
    } catch (e) {
      const m = String((e && e.message) || e);
      // ALTER ADD COLUMN on an existing column and CREATE on an existing object
      // are the expected no-ops of an idempotent schema, not failures.
      if (/duplicate column|already exists/i.test(m)) continue;
      allOk = false;
      console.error('schema:', ddl.slice(0, 70), m.slice(0, 200));
    }
  }
  if (allOk) ready = true;
}
