# Coach Telegram UX — current state (FEAT-07 Phase 0)

Snapshot taken 2026-10-07, before the Telegram UX upgrade (buttons, keyboard, state routing). This phase changed no code, config, crons or data. It is read-only discovery.

## 1. Topology

- **Agent `coach`**: model `anthropic/claude-sonnet-4-6`, fallback `google/gemini-3.1-pro-preview`. Tools allow-list: `exec, process, read, message, session_status`. Workspace `~/projects/stoiclife/coach-workspace/`.
- **Telegram account `coach`** (@stoiclife_coach_bot): `dmPolicy: allowlist`, `allowFrom: [8917837483]`, `groupPolicy: disabled`. Binding `{agentId: coach, match: {channel: telegram, accountId: coach}}`.
- **Plugins:** `plugins.allow` is an allow-list (`openclaw-supermemory, whatsapp, google, anthropic, telegram`). A new coach plugin must be added there. Installed extensions: `~/.openclaw/extensions/{openclaw-supermemory,whatsapp}`.
- **Inline buttons:** `channels.telegram.capabilities.inlineButtons` is not set, so the default `allowlist` scope applies. To be safe, set `accounts.coach.capabilities.inlineButtons: "dm"` explicitly.
- **OpenClaw version:** `OpenClaw 2026.6.8 (844f405)` at `~/.npm-global/bin/openclaw`. Never bare `openclaw`, because `/usr/bin` holds a stale build.

## 2. Automations (coach crons)

Source: `cron_jobs` in `~/.openclaw/state/openclaw.sqlite`. All jobs announce to telegram account `coach` → `8917837483`. The timezone comes from the travel-mode knob.

| Time | Job id | Kind | What it does |
|---|---|---|---|
| 07:30 daily | `73c880ac` | **command** | `coach_morning.sh` runs `set_prompt_state.py --session morning` (unless `STOICLIFE_SKIP_PROMPT_STATE=1`), then prints the Health Snapshot (**yesterday's** `biometrics` row) + `~/.openclaw/workspace/stoic/prompts/morning_prompt.txt` (Anticipation / Response / Dichotomy). |
| 11:00 daily | `700b6841` | agentTurn | Safety-Net: `stoiclife_run.py --session safety-net --channel telegram`. On SEND_FULL, the coach composes a message and records it with `record_coaching.py`, which the strict validator checks. Late-morning prep logic lives here (FEAT-05). |
| 20:30 daily | `7e8a7edd` | **command** | `~/.openclaw/workspace/scripts/evening-prompt.sh` sets evening prompt state and prints the evening review prompt. |
| Sun 08:00 | `5dcb0e1a` | **command** | `weekly_review.py --section both --channel telegram` |

Command payloads deliver **stdout verbatim** (no model turn). `NO_REPLY` stays silent. **So a command cron can't attach buttons through stdout.** To get buttons, the script has to send the message itself (`openclaw message send --channel telegram --account coach --target 8917837483 --presentation '<json>' --json`) and then print `NO_REPLY`.

> The upgrade plan only covers morning prep. The **20:30 evening review** follows the same prefix flow (`evening review:`) and needs the same treatment.

## 3. Inbound path: how messages reach the scripts

There is no plugin and no deterministic routing. **Every inbound message, including any button callback today, goes to the LLM agent**, which follows `coach-workspace/AGENTS.md`:

- **§1 Journal entries** (`AGENTS.md:9`): the message is an entry if it starts with `morning prep:` / `evening review:` (case-insensitive). If there's no prefix and `~/.openclaw/stoic/state.json` has `awaiting_response: true`, the agent asks once "Save this as your morning prep?".
  1. `save_entry.py --session <s> --response "<text>"` → new row id (`--force` if no pending prompt)
  2. `coach_context.py --entry-id <id>` → 3-day context (+ `=== STOIC MODULE … ===` block)
  3. The LLM composes `coaching_text`, `mood_score` (1–10) and themes
  4. `update_entry.py --entry-id <id> --mood-score N --themes …`
  5. `stoiclife_run.py --session <s> --entry-id <id> --channel telegram` → SEND_FULL / CLARIFY / SILENT / HOLD_QUIET
- **§2 Feedback on a 🧭 push** (`AGENTS.md:37`): the LLM interprets the reply (👍/👎/word) and runs `record_reaction.py --usefulness <1|0|-1> --reaction "<text>"`.
- **§3** Everything else is conversation. The agent answers health and journal questions through read-only `sqlite3`.

Scripts live in `~/.openclaw/workspace/scripts/` (journal: `save_entry.py`, `update_entry.py`, `coach_context.py`, `set_prompt_state.py`, `stoic_modules.py`, `evening-prompt.sh`) and `~/projects/stoiclife/` (engine: `stoiclife_run.py`, `record_coaching.py`, `record_reaction.py`, `weekly_review.py`, `coach_morning.sh`).

### Where the prefix parsing lives

| Input | Parsed by | Location | Notes |
|---|---|---|---|
| `morning prep:` / `evening review:` | **LLM** | `coach-workspace/AGENTS.md` §1 | Python never sees the prefix; the agent strips it before `save_entry.py`. |
| `mood N` / `mood:N` | Python | `workspace/scripts/save_entry.py:101` `parse_manual_mood` (start or end of entry) | **Scale 1–10** (`MANUAL_MOOD_DEFAULTS`, `save_entry.py:33`), stored as `mood_source='manual'`. `update_entry.py:53-70` never overwrites a manual mood. |
| `module:<name>` | Python | `save_entry.py:159` `parse_inline_tags` / `peel_module:172`; `workspace/scripts/stoic_modules.py:77` `parse_module` | Modules happiness / creativity / emotions (+ aliases), defined in `coach-workspace/STOIC-MODULES.md`; stored in `journal_entries.module`. |
| 👍 / 👎 / word after a push | **LLM** → Python | `AGENTS.md` §2 → `record_reaction.py:48` (latest unrated valid push, 18h window), `:123` (UPDATE) | **Only rates 🧭 stoiclife pushes** (`trigger_coaching`). Regular coaching replies (§1 `coaching_text`) are **not persisted anywhere and have no id.** Telegram tap reactions don't reach the coach. |

## 4. Database

`~/.openclaw/stoic/stoic_journal.db` (SQLite). Row counts on 2026-10-07:

| Table | Rows |
|---|---|
| journal_entries | 214 |
| biometrics | 129 |
| trigger_events | 238 |
| trigger_coaching | 19 |

Schema (`sqlite3 .schema`):

```sql
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    date TEXT,
    session TEXT,
    prompt_sent_at TEXT,
    response_received_at TEXT,
    raw_response TEXT,
    processed_themes TEXT,
    mood_score INTEGER,
    created_at TEXT
, mood_source TEXT DEFAULT 'inferred', module TEXT);
CREATE TABLE biometrics (
    date TEXT PRIMARY KEY,
    hrv_rmssd_ms REAL,
    deep_sleep_rmssd_ms REAL,
    resting_hr_bpm INTEGER,
    sleep_duration_min INTEGER,
    minutes_awake INTEGER,
    light_min INTEGER,
    deep_min INTEGER,
    rem_min INTEGER,
    sleep_score INTEGER,
    raw_json TEXT,
    synced_at TEXT
, steps INTEGER, spo2_avg REAL, spo2_min REAL, spo2_max REAL, spo2_stddev REAL);
CREATE TABLE trigger_events (
    id                  INTEGER PRIMARY KEY,
    eval_datetime       TEXT NOT NULL,            -- ISO8601, AEST, when the matrix ran
    date                TEXT NOT NULL,            -- the day being classified (YYYY-MM-DD)
    session             TEXT NOT NULL,            -- morning | evening | safety-net
    state               TEXT NOT NULL,            -- rattled_but_ready | running_on_fumes | system_drain | sweet_spot | neutral | insufficient_data
    deltas_json         TEXT,                     -- JSON: today's deltas vs 7-day baseline
    matched_keywords    TEXT,                     -- comma-separated keywords found in today's journal
    confidence          INTEGER,                  -- 0-100
    fired               INTEGER NOT NULL DEFAULT 0,  -- bool: a non-silent state cleared cooldown
    cooldown_skipped    INTEGER NOT NULL DEFAULT 0,  -- bool: would have fired but suppressed by cooldown
    message_sent        INTEGER NOT NULL DEFAULT 0,  -- bool: set in Phase 4
    held_for_quiet_hours INTEGER NOT NULL DEFAULT 0, -- bool: set in Phase 4
    usefulness          INTEGER,                  -- nullable: set in Phase 5 feedback loop
    notes               TEXT
, status_signal TEXT);
CREATE INDEX idx_trigger_events_date  ON trigger_events(date);
CREATE INDEX idx_trigger_events_state ON trigger_events(state, fired);
CREATE TABLE trigger_coaching (
    id                INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES trigger_events(id),
    generated_at      TEXT NOT NULL,            -- ISO8601, AEST
    state             TEXT NOT NULL,
    coaching_text     TEXT NOT NULL,
    valid             INTEGER NOT NULL,         -- bool: passed strict-format validation
    validation_errors TEXT                      -- comma-separated, NULL when valid
, usefulness INTEGER, reaction_raw TEXT, reacted_at TEXT);
CREATE INDEX idx_trigger_coaching_event ON trigger_coaching(event_id);
```

Schema management today: `db_init.py` (idempotent `ALTER TABLE … ADD COLUMN` style) plus ad-hoc backups `stoic_journal.db.bak-<tag>-<ts>` in `~/.openclaw/stoic/`. There's no numbered migrations directory yet. Phase 1 should add one (e.g. `migrations/001_*.py`).

Prompt state: `~/.openclaw/stoic/state.json` (`awaiting_response`, `session`, `prompt_sent_at`), written by `set_prompt_state.py`.

## 5. OpenClaw 2026.6.8 capability check

Verified against the bundled docs (`~/.npm-global/lib/node_modules/openclaw/docs/`) and `dist/` code and types. The online `channels/telegram/rich-messages` page does **not** exist in this version's bundled docs. The equivalent material is in `docs/channels/telegram.md` ("Inline buttons", "message actions") and `docs/plugins/message-presentation.md`.

| # | Capability | Answer | Evidence and how to use it |
|---|---|---|---|
| 1 | **Plugin callback handler + prefix claim** | **YES** | `api.registerInteractiveHandler({ channel: "telegram", namespace: "sc", handler })` (`plugin-sdk/types-*.d.ts` `PluginInteractiveRegistration`). Core splits `callback_data` at the **first `:`** → `namespace="sc"`, `payload="mood:3"` (`dist/plugin-runtime-*.js` `resolvePluginInteractiveMatch`). Namespace regex `[A-Za-z0-9._-]+`, one owner per namespace. Unclaimed data goes to the agent as `callback_data: <value>` (`docs/channels/telegram.md`). Handler ctx (`TelegramInteractiveHandlerContext`): `callback.{data,payload,messageId,chatId,messageText}`, `senderId`, `auth.isAuthorizedSender`, `respond.*`. Return `{handled:false}` to fall through. |
| 2 | **Acknowledge callback** | **YES, automatic** | The bot middleware calls `answerCallbackQuery(callback.id)` as soon as a callback arrives (`dist/bot-*.js`). No toast/alert text is possible. Callbacks are deduped by callback id. |
| 3 | **Send with presentation buttons** | **YES** | In the handler: `ctx.respond.reply({ text, buttons: [[{text, callback_data, style?}]] })`. From scripts/crons: `openclaw message send --channel telegram --account coach --target 8917837483 --message … --presentation '<json>' --json`. Agent `message` tool: `buttons` / `presentation`. |
| 4 | **Edit message (incl. button-only)** | **YES** | Handler: `respond.editMessage({text, buttons?})`, `respond.editButtons({buttons})`, `respond.clearButtons()`, `respond.deleteMessage()`. Outside a callback: `openclaw message edit` / agent `editMessage` (`chatId`, `messageId`, `content`, optional `presentation`; a button-only edit updates the reply markup). |
| 5 | **ForceReply** | **NO** | Zero occurrences of `force_reply` / `forceReply` anywhere in dist or docs. **Fallback decision needed** (see §6). |
| 5b | **Persistent reply keyboard** (plan goal) | **NO** | No `ReplyKeyboardMarkup` / `resize_keyboard` / `is_persistent` / `one_time_keyboard`. **Fallback decision needed.** |
| 6 | **Silent send (`disable_notification`)** | **YES via CLI/outbound; NO inside a callback reply** | `openclaw message send --silent` → `disable_notification: true` (`dist/send-*.js`). `respond.reply` has no silent flag. |
| 7 | **reply_to_message_id on inbound** | **YES (metadata); interception only when bound** | `message_received` and `inbound_claim` events carry `replyToId`, `replyToIdFull`, `replyToBody`, `replyToSender`, `replyToIsQuote`, `messageId` (`docs/plugins/hooks.md` "Message hooks"). The agent also gets reply context. **But `inbound_claim` (the hook that can swallow a message before the LLM) only fires for conversations bound to the plugin** (`dist/dispatch-*.js`, `pluginOwnedBinding` branch). `message_received` is observe-only. Deterministic free-text routing therefore needs `ctx.requestConversationBinding()` on the coach DM, after which the plugin sees every message first and must hand non-claimed ones back. |
| 8 | **Voice messages / transcription** | **YES (platform); not yet verified on this host** | Inbound voice notes are transcribed and framed as machine-generated text; `inbound_claim` has a `transcript` field. `tools.media.audio` isn't configured, so auto-detect applies: reply model (Anthropic Sonnet has no audio input) → local `whisper`/`whisper-cli` (**not installed**) → configured provider auth (Google is enabled, so probably Gemini). **Open item:** send one test voice note to the coach bot and check the gateway log. |

Other useful findings:
- `api.registerCommand(...)` registers slash commands that **bypass the LLM** (processed before agent invocation). It's a deterministic entry point for `/mood`, `/module`, `/prep`.
- `inlineButtons` must allow the DM scope on the coach account.

## 6. Mismatches between the upgrade plan and the system (decide before Phase 1)

1. **Mood scale.** The plan has `sc:mood:<1-5>`; the system, DB data and parser use **1–10**. Options: 10 buttons in 2 rows, 5 buttons mapped to 2/4/6/8/10, or move the whole scale to 1–5 (breaks history/inference comparability).
2. **Evening review** (20:30, `evening review:` prefix) isn't in the plan but uses the same flow.
3. **No coaching response id.** `sc:fb:<response_id>` needs a new table (e.g. `coaching_responses`: id, entry_id, text, telegram_message_id, usefulness, reason). Today only 🧭 pushes (`trigger_coaching.id`) are rateable.
4. **Morning prep is a command cron.** Buttons require `coach_morning.sh` to call `openclaw message send --presentation … --json` and print `NO_REPLY`, and store the returned message id if it's to be edited later.
5. **ForceReply and the persistent reply keyboard are unavailable.** Candidate fallback: `sc:prep:write` / `sc:note:*` set a pending state (`state.json` or a plugin state store) and reply "Type your entry…". The next free text is then routed by state, either by the agent (AGENTS.md reads state, as the forgotten-prefix rule does today) or deterministically via a conversation binding. Reply keyboard → bot command menu (`registerCommand`) + inline buttons on the prompts.
6. **Free-text routing.** True deterministic routing means binding the coach DM to the plugin (every message hits the plugin first, which must pass entries and conversation through to the agent). The alternative is to keep the LLM routing and let state + reply-to replace the prefix requirement.
7. **The coach has no plugin today.** The plugin must be installed, added to `plugins.allow`, and the gateway restarted. A bad config takes all channels down (memory: openclaw-doctor-not-authoritative), so restart and check `is-active`.

## 7. The 11:00 safety-net and FEAT-05, as of FEAT-07 Phase 4 (2026-10-08)

Written for FEAT-07 Phase 5, step 1 ("understand first").

**Data timing.** The Fitbit sync runs at 07:00 (primary) and 10:00 (catch-up). Today's `biometrics` row holds **last night's** sleep, HRV and resting HR, plus today's steps so far. At 07:00 the row often has steps only; the 10:00 catch-up fills in the sleep stages, and `sleep_score.py --recent 4` then computes the score. By 11:00, "synced" means today's row exists with `sleep_duration_min` and `sleep_score` set. FEAT-02's `status.health_check()` already tests this (`biometrics_fresh`, `sleep_score_present`).

**The 11:00 job** (`700b6841`, agentTurn, coach agent, announced to the coach chat): the coach runs `stoiclife_run.py --session safety-net --channel telegram` and acts on the first line:
- **Start-of-run sweep:** releases a message held overnight in quiet hours (once, deliver-once) or expires stale holds. This happens before today's evaluation.
- **Evaluation:** `trigger_matrix.evaluate()` classifies the day against the 7-day baseline (`rolling_window_days`). It uses the most recent biometrics row **within `biometrics_max_lag_days` = 2**, so if today's row is missing it can classify on **yesterday's** row. It needs a journal entry for the day (otherwise `insufficient_data`) and ≥ 3 baseline days.
- **Gates:** silent states (neutral, sweet_spot, insufficient_data) → `SILENT`; cooldown (2 days per state) → `SILENT`; "already sent today" → `SILENT`; confidence < 40 → `SILENT`; 40–69 → `CLARIFY` (🧭 one-liner, no buttons); ≥ 70 → `SEND_FULL` (the coach composes, `record_coaching.py --send` validates, stores and sends with 👍/👎); quiet hours 21:00–07:00 → `HOLD_QUIET`.
- **The coach's reply:** `HEARTBEAT_OK` on SILENT/HOLD_QUIET (nothing is delivered), the 🧭 line on CLARIFY, `NO_REPLY` after a `--send`.
- Every evaluation writes a `trigger_events` row (`session = 'safety-net'`).

So on a normal day **the 11:00 job sends nothing**. On a day without a morning entry it logs `insufficient_data` and also sends nothing.

**FEAT-05 (late morning prep)** is not a nudge. It's a rule in the engine: a *morning* entry written **after 11:00 today** is treated as the safety-net run (`status.is_late_morning`), so `evaluate()` may fire coaching for it in-turn and the 🟢/⚠️ status line may be appended. It exists because the 11:00 sweep found no entry, and before FEAT-05 nothing was ever coached that day (the 2026-08-11 miss).

**Since Phase 4**, a message sent after 11:00 while the morning prep is unanswered (and before the evening prompt) is held with `[📝 Save as morning prep] [💬 Just chatting]` (spec D45). Saving it goes through the normal pipeline, so FEAT-05's late-morning coaching still applies.
