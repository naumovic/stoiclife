-- FEAT-07 Phase 5 (D57): one row per day for the 11:00 update. Idempotency (a re-run
-- never sends a second update) and Phase 6 measurement. Idempotent.
CREATE TABLE IF NOT EXISTS daily_updates (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id          TEXT NOT NULL,
  local_date       TEXT NOT NULL,
  status           TEXT NOT NULL,        -- complete | pending_sync | not_synced
  synced           INTEGER NOT NULL DEFAULT 0,
  action           TEXT,                 -- engine STOICLIFE_ACTION (SILENT/CLARIFY/SEND_FULL/HOLD_QUIET)
  event_id         INTEGER,              -- trigger_events.id of the engine run
  message_id       TEXT,                 -- the update's Telegram id
  escalation       TEXT,                 -- none | clarify | send_full | send_full_failed
  entry_present    INTEGER,
  checkin_present  INTEGER,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  UNIQUE(chat_id, local_date)
);
