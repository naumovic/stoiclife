-- MIN-132: one row per CLARIFY 🧭 question ("want the full read?") sent with buttons.
-- The answer (tapped or typed) routes deterministically: yes -> a CLARIFY_YES route line
-- for the coach, no -> acknowledged without the LLM. Idempotent.
CREATE TABLE IF NOT EXISTS clarify_prompts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id        TEXT NOT NULL,
  event_id       INTEGER NOT NULL,       -- trigger_events.id the full read is for
  message_id     TEXT,                   -- the 🧭 question's Telegram id
  local_date     TEXT NOT NULL,
  sent_at        TEXT NOT NULL,
  expires_at     TEXT NOT NULL,
  answer         TEXT,                   -- yes | no (NULL = unanswered)
  answer_source  TEXT,                   -- button | typed
  answered_at    TEXT,
  route_id       INTEGER                 -- route_events.id of the CLARIFY_YES turn
);
CREATE INDEX IF NOT EXISTS ix_clarify_prompts_chat ON clarify_prompts(chat_id, id);
