-- FEAT-07 Phase 4 (D41, D48): prompts sent, and the route decided for each inbound message.
-- Idempotent. Times are ISO8601 in the active travel-mode zone (D19).

-- One row per morning/evening prompt (D48). An open prompt = newest row for the chat,
-- not answered and not skipped; `window_ends_at` splits "type = entry" from "hold" (D45).
CREATE TABLE IF NOT EXISTS prompt_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id         TEXT NOT NULL,
  local_date      TEXT NOT NULL,          -- logical journaling day of the prompt
  session         TEXT NOT NULL,          -- 'morning' | 'evening'
  message_id      TEXT,                   -- Telegram id of the prompt (reply-to matching)
  sent_at         TEXT NOT NULL,
  window_ends_at  TEXT NOT NULL,          -- morning 11:00, evening 03:00 next day
  skipped_at      TEXT,
  entry_id        INTEGER,                -- journal_entries.id once answered
  answered_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_prompt_events_chat ON prompt_events(chat_id, sent_at);

-- One row per routed inbound message (D41): written by before_dispatch, stamped
-- `injected_at` by before_prompt_build. Acceptance evidence + Phase 6 input method.
CREATE TABLE IF NOT EXISTS route_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id       TEXT NOT NULL,
  session_key   TEXT,
  at            TEXT NOT NULL,
  route         TEXT NOT NULL,            -- entry | conversation | note | hold | ask_text
  session       TEXT,                     -- morning | evening (entry / hold / ask_text)
  source        TEXT NOT NULL,            -- prefix | reply | write | window | hold | note | none
  prompt_id     INTEGER,                  -- prompt_events.id it answers, if any
  hold_id       INTEGER,
  text          TEXT,                     -- the message text the coach must use (D43)
  injected_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_route_events_key ON route_events(session_key, injected_at);
