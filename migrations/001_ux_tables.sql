-- FEAT-07 Phase 1: tables for the Telegram UX (buttons, check-ins, feedback).
-- Idempotent: every statement is IF NOT EXISTS, so re-running is a no-op.
-- local_date is the *logical journaling day* in the active travel-mode zone
-- (07:30 rollover, same as save_entry.logical_date), never a hardcoded zone.

CREATE TABLE IF NOT EXISTS checkin_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id     TEXT NOT NULL,
  local_date  TEXT NOT NULL,          -- logical day, active TZ (YYYY-MM-DD)
  type        TEXT NOT NULL,          -- 'mood' | 'module'
  value       TEXT NOT NULL,          -- mood '1'..'10' | module key
  source      TEXT NOT NULL,          -- 'button' | 'command' | 'legacy_prefix'
  note        TEXT,
  message_id  TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_checkin_day
  ON checkin_events(chat_id, local_date, type);   -- latest wins via upsert

CREATE TABLE IF NOT EXISTS coaching_responses (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id            INTEGER,        -- journal_entries.id
  chat_id             TEXT NOT NULL,
  telegram_message_id TEXT,
  session             TEXT,           -- 'morning' | 'evening' | 'adhoc'
  data_flags_json     TEXT,
  text                TEXT,           -- what was actually sent (G4)
  created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS response_feedback (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  target_kind  TEXT NOT NULL,         -- 'r' | 't'
  target_id    INTEGER NOT NULL,
  rating       TEXT NOT NULL,         -- 'up' | 'down'
  reason       TEXT,
  note         TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE(target_kind, target_id)      -- one rating per target; re-tap updates
);

-- G4: every bot message that carries sc: buttons. Stale-button guard (G5),
-- reply-to -> session (Phase 4), prompt counts (Phase 6), t-push message ids.
CREATE TABLE IF NOT EXISTS ui_messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id  TEXT NOT NULL,
  chat_id     TEXT NOT NULL,
  kind        TEXT NOT NULL,          -- prompt_morning | prompt_evening | picker | coaching_r | coaching_t | test
  ref_id      INTEGER,                -- coaching_responses.id / trigger_coaching.id
  session     TEXT,
  local_date  TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_messages_msg ON ui_messages(chat_id, message_id);
