# FEAT-07 — Stoic Coach Telegram UX (working file)

The blueprint for FEAT-07. Mihajlo's plan v2 is reproduced verbatim further down ("Plan v2"). Claude's review of it comes first: gaps G1–G17, each with the amendment adopted. **Where a G-amendment and the plan text disagree, the amendment wins.** Ground truth for the current system is `docs/CURRENT-STATE.md`. History goes in `docs/PROGRESS.md`.

## Phase status

| Phase | Branch | Status |
|---|---|---|
| 0 Discovery | `feat07-phase0-current-state` | ✅ done, merged to main (44c5a11) |
| 1 Foundation | `feat07-phase1-foundation` | ✅ done, merged to main |
| 2 Feedback buttons | `feat07-phase2-feedback` | ✅ done, merged to main (fixes P2-D1..D11 in the PROGRESS file) |
| 3 Mood/module buttons + commands | — | not started |
| 4 Morning/evening without prefixes | — | not started |
| 5 11am update | — | not started |
| 6 Self-test metrics | — | not started |

## Review: gaps and amendments (Claude, 2026-10-07)

Reviewed against the live code (`save_entry.py`, `set_prompt_state.py`, `record_reaction.py`, the cron rows) and the bundled 2026.6.8 SDK.

### Blocking for Phase 1 (resolved by the amendment)

- **G1. The `local_date` comment says Australia/Brisbane** (`checkin_events` SQL), which contradicts D19. **Amendment:** `local_date` = the *logical journaling day* in the active zone (`active_tz.TZ`), using the same 07:30 rollover as `save_entry.logical_date`. A mood tapped at 01:00 belongs to the previous day, just like an after-midnight evening review. One helper (`checkins.local_date()`) is used everywhere.
- **G2. `state.json` is overwritten wholesale by two writers.** `set_prompt_state.py` writes a fresh 3-key dict, and `save_entry.py` resets it to `INITIAL_STATE` after every save. A `pending` extension (D9) would be wiped on every prompt and every entry. **Amendment:** both become read-modify-write and preserve unknown keys (a minimal workspace-script change, listed per D16). Layout: the legacy top-level keys (`awaiting_response`, `session`, `prompt_sent_at`) stay unchanged in meaning, plus `"pending": {"<chat_id>": {"kind", "message_id", "set_at", "expires_at"}}`. All new reads and writes go through `tg.py`.
- **G3. Nothing knows the chat id.** `save_entry.py` and the crons don't have one. **Amendment:** add `"coach": {"chat_id": "8917837483", "account": "coach"}` to `stoiclife_config.json`. Scripts default to it.
- **G4. There's nowhere to store a trigger push's Telegram message id, or a prompt's.** `coaching_responses` only covers `r`. **Amendment:** migration 001 also creates **`ui_messages`** (`message_id, chat_id, kind, ref_id, session, local_date, created_at`), with one row for every bot message carrying `sc` buttons (prompts, pickers, coaching `r`/`t`, test). It serves: (a) the stale-button guard (G5), (b) Phase 4 rule 2 (reply-to → session), (c) Phase 6 "prompt sent" counts, (d) message ids of `t` pushes without altering `trigger_coaching`. `coaching_responses` also gets a **`text`** column, so feedback can be reviewed against what was actually said.
- **G5. Stale buttons.** `sc:mood:7` carries no date, so tapping yesterday's picker would log today's mood. **Amendment:** the dispatcher looks up the tapped message in `ui_messages`. If its `local_date` isn't today, it edits the message to "This picker has expired" and writes nothing. A message missing from `ui_messages` is treated as today, which is the safe default.
- **G6. Plugin code changes need a gateway restart, and the gateway is shared (D20).** **Amendment:** the plugin is a **thin JS shim**. It checks the account and auth, then pipes `{data, payload, chat_id, message_id, message_text, sender_id}` as JSON to **`sc_dispatch.py`** and applies the JSON actions it returns (`edit`, `editButtons`, `clearButtons`, `reply`). All logic lives in Python. This answers step 3's "pick one and be consistent" (Python scripts, which own the DB like every existing writer). Logic changes and unit tests then need no restart. The shim is plain ESM JS with no build step.
- **G7. Installing the plugin restarts the gateway itself.** `openclaw plugins install --link` triggers an automatic restart of a managed gateway (bundled `manage-plugins.md`), and config edits may trigger a reload too. **Amendment:** do all of it in one quiet window: snapshot `openclaw.json`, apply the config edits and the link install, then do one explicit restart and the D20 checks. "Restart once" becomes "one maintenance window". The rollback is a single documented command.
- **G8. Slash commands would cost a second restart in Phase 3.** **Amendment:** Phase 1's shim also registers `/mood`, `/module`, `/journal`, `/skip`, forwarding to the same dispatcher. Until Phase 3 the dispatcher replies "Coming soon" (`/mood` and `/module` may work early, since the picker code is the same). This saves a shared-gateway restart. Side effect: the commands appear in the `/` menu from Phase 1 on.
- **G9. Button mood vs two entries a day.** "Merge today's `checkin_events` when an entry is saved" would stamp a morning tap onto the evening entry too. **Amendment (merge rule):** a check-in merges into the entry being saved only if (a) the entry has no inline value for that field (inline wins), and (b) the check-in was updated **after the previous entry of the same logical day** was created, or there is no previous entry. So a morning tap goes to the morning entry, and the evening entry falls back to inference unless there's a newer tap. Merged mood → `mood_source='manual'`. The merge runs in `save_entry.py` inside try/except, so it can never block saving.
- **G10. The "test chat" is the live coach DM**, the only chat. Test messages are visible to Mihajlo and need his tap. **Amendment:** test messages are clearly labelled `[FEAT-07 test]`. After verification, the test `checkin_events` row is deleted (and logged) so it can't merge into a real entry.

### Non-blocking (later phases), recorded so they aren't lost

- **G11 (D5).** The bundled `automation/cron-jobs.md` says a command printing only `NO_REPLY` posts nothing, and the weekly review job already relies on it. Re-verify live in Phase 4.
- **G12 (Phase 2).** Verify that an agent reply of `NO_REPLY` in an inbound DM turn (not a cron) is suppressed before relying on it, using one test message.
- **G13 (Phase 5).** The 12:00 retry is a new cron. Its `schedule.tz` must come from the travel-mode knob (`travel-mode.sh` manages the cron tz list, so add the new job to it).
- **G14.** Python is stdlib only (no system pip). Tests follow the repo style: `python3 tests/test_x.py` with a `check()` counter, no pytest.
- **G15.** `trigger_coaching.usefulness` is −1/0/1. Mapping: up = 1, down = −1. The reason and note live only in `response_feedback`.
- **G16 (Phase 2).** Typed 👍 currently targets only `t` (`record_reaction.py`, 18h window). Phase 2 must define "latest target" across `r` and `t`. Proposed: the most recent `ui_messages` row of kind `coaching_r`/`coaching_t` within 18h that has no `response_feedback` yet.
- **G17.** An `sc:` tap arriving on a non-coach account is logged and swallowed (`handled: true`), never passed to another agent.

### Found during Phase 1

- **G18. Script-sent buttons are laid out 3 per row.** OpenClaw's Telegram presentation renderer chunks every `buttons` block into rows of 3 (`TELEGRAM_INTERACTIVE_ROW_SIZE`, `dist/button-types-*.js`). A 1–10 mood picker sent from a script renders as `[1 2 3][4 5 6][7 8 9][10]`, not 2×5 (D1). Exact rows are only possible from the plugin's callback handler (`respond.reply/editMessage/editButtons` take raw rows). **Phase 3 decides:** accept 3-per-row from scripts, or send pickers from the plugin (e.g. a command reply or a `channelData` route, to be checked).
- **G19. `openclaw message edit` is text-only** (no `--presentation`). Scripts can't change buttons on an existing message; button edits happen in the plugin handler. This matters for Phase 5 if it wants to edit an earlier message's buttons.
- **G20. Plugin slash commands register on every Telegram account,** so `/mood /module /journal /skip` also show in the trip bot's `/` menu. There they return `continueAgent` (the trip bot's agent sees the text as usual). Cosmetic; revisit if it confuses anyone.
- **Install facts.** `openclaw plugins install --link` added the plugin to `plugins.allow`, `plugins.entries` and `plugins.load.paths`, but did **not** restart the gateway. The follow-up `config set` did (an automatic reload-restart). The 2026-10-07 window took one restart in total.

### Decided questions (2026-10-07)

- **Q1 (Phase 3): decided no.** A mood tap *after* today's entry is already saved does **not** update that entry. It only lands in `checkin_events` and applies to the next entry per G9.
- **Q2: decided yes.** The slash commands show in the `/` menu from Phase 1 (G8), including the trip bot's menu (G20). Accepted.

---

# Plan v2 (verbatim, as handed over 2026-10-07)

# Stoic Coach — Telegram UX Upgrade Plan (v2)

Phased implementation plan for the dedicated Stoic coaching Telegram bot (OpenClaw 2026.6.8, repo `~/projects/stoiclife`).
Hand this to Claude Code **one phase at a time**. Each phase ends with acceptance criteria. Don't start the next phase until they pass and the changes have been manually reviewed.

> **v2 changes:** updated after the full Phase 0 findings (`docs/CURRENT-STATE.md`). Decisions D1–D21 are recorded in the next section. Main changes: 1–10 mood scale, evening review in scope, no ForceReply, reply keyboard or voice, free text still goes to the agent but its routing is decided by a deterministic script, and the 11am update builds on the existing trigger engine.

---

## Decisions (resolving Phase 0 mismatches)

| # | Issue | Decision |
|---|---|---|
| D1 | Mood is 1–10 in existing data, plan assumed 1–5 | **Keep 1–10.** Don't break 214 entries of history. Picker = two rows of five buttons. |
| D2 | Evening review (20:30) missing from plan | **In scope.** Gets the same treatment as morning prep (no prefix, buttons, feedback). Weekly review (Sun 08:00) stays out of scope for now. |
| D3 | Normal coaching replies have no id | New `coaching_responses` table. The agent no longer posts the coaching reply directly. It calls `send_coaching.py`, which stores the row, sends the reply with feedback buttons, and returns `NO_REPLY` to the agent. |
| D4 | Two feedback targets (normal replies vs `trigger_coaching` pushes) | One button scheme with a kind prefix: `r` = `coaching_responses`, `t` = `trigger_coaching`. `t` ratings still update `trigger_coaching` usefulness via `record_reaction.py` logic. |
| D5 | Morning/evening crons are command payloads (stdout delivered verbatim) | Scripts send the message themselves via `openclaw message send --channel telegram --account coach --presentation <json>`, then print `NO_REPLY`. Verify that `NO_REPLY` suppresses stdout delivery for command payloads; if it doesn't, find the supported way to send nothing. |
| D6 | No ForceReply | **Drop ForceReply.** "✍️ Write entry" sets the pending state and replies "Go ahead — type your entry below." Routing is by state, so ForceReply isn't needed. Swipe-reply still works as a secondary signal where the reply-to id is available. |
| D7 | No persistent reply keyboard | **Drop it.** Use `api.registerCommand` slash commands (`/mood`, `/module`, `/journal`, `/skip`), which bypass the LLM, and surface them in the bot's `/` menu. |
| D8 | Deterministic free-text interception needs plugin conversation binding (every message would hit the plugin first) | **Don't bind.** Free text needs the LLM anyway. Keep it going to the agent, but routing is decided by a deterministic script (`route_entry.py`) that reads pending state, never by the LLM guessing from prefixes. Buttons and commands bypass the LLM via the plugin. |
| D9 | Pending state | **Reuse the existing `state.json` / `set_prompt_state.py`** rather than a new `pending_state` table. Extend it with `kind`, `message_id`, `expires_at`, and key it by `chat_id` (future clients). |
| D10 | Silent send is CLI-only | Fine. The 11am routine update goes out from a script via `message send --silent`. |
| D11 | OpenClaw version | **Stay on 2026.6.8** for this work. Newer releases may add ForceReply (`ask_user`'s "Other…" opens Telegram's reply input in current docs), but don't upgrade mid-project. Revisit after Phase 6. |
| D12 | No migrations framework | Add a minimal one in Phase 1: numbered SQL scripts plus a `schema_migrations` table. Back up using the existing `stoic_journal.db.bak-<tag>-<ts>` pattern before each migration. |
| D13 | Coach has no plugin; installing one means editing the `plugins.allow` allowlist and restarting the gateway | Accepted. Do it in Phase 1, before any handler code is relied on. Snapshot `openclaw.json` first, restart once, and confirm the existing coach flows (morning cron, 11am, evening, inbound replies) still work before continuing. |
| D14 | Online "rich messages" docs page doesn't match 2026.6.8 | Use the **bundled** docs shipped with the installed version (Telegram channel and message-presentation) as the reference. Treat online docs as background only. |
| D15 | Voice transcription unverified | **Out of scope.** Voice notes will be a separate feature later. Don't test, wire up or install anything for voice in this plan. |
| D16 | Journal scripts (`save_entry.py`, `update_entry.py`, `set_prompt_state.py`, `evening-prompt.sh`, …) live in `~/.openclaw/workspace/scripts/`, which auto-commits | **New** scripts go in `~/projects/stoiclife/`. Changes to existing workspace scripts are allowed but kept minimal. List every workspace file touched in the phase summary, with a diff, so it can be reviewed despite the auto-commit. Don't move scripts between repos in this project. |
| D17 | The 11:00 job already runs a trigger engine (`stoiclife_run.py`: 7-day baseline deltas, states, cooldown, quiet hours, strict validator, FEAT-05 late-morning prep logic) | **Phase 5 builds on the engine; it doesn't replace it.** No new 14-day baseline or flag logic. The engine's state decides silent vs escalated. Cooldown, quiet hours, validation and FEAT-05 behaviour are preserved, and the "missing morning entry" nudge merges with FEAT-05 instead of duplicating it. |
| D18 | Coaching replies are gated by `stoiclife_run.py` (SEND_FULL / CLARIFY / SILENT / HOLD_QUIET) | `send_coaching.py` is only called where the agent currently posts its reply, and it must respect that decision. Nothing is sent on SILENT, and HOLD_QUIET keeps its current behaviour. Buttons are added only to messages that would have been sent anyway. |
| D19 | Timezone comes from the travel-mode setting, not a fixed zone | `local_date`, prompt expiries and the 11:00/14:00/03:00 cut-offs all use the **same timezone source the crons use**. Never hardcode Australia/Brisbane. |
| D20 | The gateway is shared (WhatsApp/Ewok and other channels), and a bad config takes all channels down | Restart at a quiet time. Snapshot `openclaw.json` and keep a one-command rollback ready. After restarting, check `is-active` and that **every** channel (not just the coach) reconnects, before continuing. |
| D21 | Two `openclaw` binaries; `/usr/bin` is stale | All scripts and helpers call `~/.npm-global/bin/openclaw` by absolute path (one constant in the helper). |

---

## Context (read before any phase)

- `docs/CURRENT-STATE.md` is the source of truth for topology, automations, parsing locations, schema and capabilities. Read it first. Where it and this plan disagree, stop and ask.
- `journal_entries` already has `mood_score` (1–10), `mood_source` ('manual' | 'inferred') and `module`. Reuse these columns, and don't add parallel ones.
- Agent `coach`, Telegram account `coach`, DM allowlist. `plugins.allow` is an allowlist, so the new plugin must be added to it.
- Automations: 07:30 morning prep (command, `coach_morning.sh`), 11:00 safety net (agentTurn), 20:30 evening review (command), Sun 08:00 weekly review (command, out of scope).
- Inbound free text goes to the LLM, which follows `coach-workspace/AGENTS.md` §1 → `save_entry.py` → `coach_context.py` → composes the reply → `update_entry.py` → `stoiclife_run.py`.
- Plugin API confirmed in 2026.6.8:
  - `api.registerInteractiveHandler({ channel: "telegram", namespace: "sc", handler })`
  - Callbacks are acked automatically and deduped by id.
  - `ctx.respond.reply({ text, buttons })`, `editMessage`, `editButtons`, `clearButtons`, `deleteMessage`
  - `api.registerCommand` for slash commands that bypass the LLM

**Key architectural rule:** button taps and slash commands are handled **deterministically by the plugin**, never by the LLM. Free text goes to the agent, but which session it belongs to is decided by `route_entry.py`, not by the LLM.

**Ground rules for every phase**
- Work in `~/projects/stoiclife`, not the auto-committing workspace repo. One branch per phase (`feat07-phaseN-…`), with an entry in `docs/PROGRESS.md`.
- Back up `stoic_journal.db` before any schema change. Migrations are numbered and idempotent.
- Keep the legacy prefixes (`morning prep:`, `evening review:`, `mood N`, `module:x`, typed 👍/👎) working as fallbacks until Phase 6 says otherwise.
- Don't push unless asked. Summarise all changes at the end of each phase for manual review.

---

## Callback data scheme

Telegram limits `callback_data` to 64 bytes. The plugin claims namespace `sc`, and core splits the data at the first `:`.

| Callback | Meaning |
|---|---|
| `sc:mood:<1-10>` | Mood rating |
| `sc:mod:<emotions\|creativity\|happiness>` | Stoic module |
| `sc:fb:<r\|t><id>:<up\|down>` | Feedback on a coaching reply (`r`) or a trigger push (`t`) |
| `sc:fbr:<r\|t><id>:<generic\|offbase\|long\|more>` | Reason after 👎 |
| `sc:write:<morning\|evening>` | Start an entry (sets pending state) |
| `sc:skip:<morning\|evening>` | Skip today's session |
| `sc:note:<mood\|module>` | Add a note to today's mood/module |

---

## Phase 1 — Foundation: plugin, migrations, helpers

**Goal:** The `sc` plugin works end to end on a test button. No user-facing flow changes yet.

1. **Migrations:** add a `migrations/` folder, a runner script and a `schema_migrations` table, coexisting with the existing `db_init.py` (don't rewrite it). Back up the DB first. Migration `001_ux_tables`:
   ```sql
   CREATE TABLE IF NOT EXISTS checkin_events (
     id          INTEGER PRIMARY KEY AUTOINCREMENT,
     chat_id     TEXT NOT NULL,
     local_date  TEXT NOT NULL,          -- Australia/Brisbane   [amended G1: logical day, active TZ]
     type        TEXT NOT NULL,          -- 'mood' | 'module'
     value       TEXT NOT NULL,          -- mood '1'..'10' | module name
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
     created_at          TEXT NOT NULL
   );                                    -- [amended G4: + text TEXT]

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
   -- [amended G4: + ui_messages]
   ```
2. **Mood precedence:** a button or command mood counts as a **manual** mood. When an entry is saved for that day, merge today's `checkin_events` into `journal_entries`: `mood_score` with `mood_source='manual'`, and `module`. An inline `mood N` / `module:x` in the entry text wins over the button value for that entry. `update_entry.py`'s existing never-overwrite-manual rule stays intact. *[amended G9: merge rule for two entries a day]*
3. **Plugin `stoic-coach-ui`:** *[amended G6/G8: thin shim → `sc_dispatch.py`; commands registered now]*
   - Register an interactive handler, namespace `sc`, on Telegram, restricted to the `coach` account. Reject taps where `ctx.auth.isAuthorizedSender` is false.
   - Parse and validate per the scheme. Unknown values are logged and ignored.
   - Each action is a small handler that calls Python scripts (or writes SQLite directly; pick one and be consistent) and then edits the message.
   - Add it to `plugins.allow`. Set `channels.telegram.accounts.coach.capabilities.inlineButtons: "dm"` explicitly.
   - Snapshot `openclaw.json` before editing, restart the gateway once at a quiet time, and confirm that **all** channels and the existing coach flows still work (D13, D20). *[amended G7]*
   - Reference: the bundled Telegram and message-presentation docs for 2026.6.8 (D14).
4. **Shared helpers** (`scripts/tg.py` or similar), wrapping `openclaw message send/edit`:
   - send with presentation buttons, returning the message id (`--json`)
   - send silently (`--silent`)
   - edit text and buttons
   - set/read/clear pending state (extend `set_prompt_state.py` / `state.json` per D9) *[amended G2]*
5. **`send_coaching.py`:** two modes.
   - `--kind r`: takes entry id, session, data flags and reply text, inserts `coaching_responses`, and sends with `[👍 Helpful] [👎 Not quite]` (`sc:fb:r<id>:…`).
   - `--kind t --target-id <trigger_coaching.id>`: sends an existing push with `sc:fb:t<id>:…` buttons.
   - Both store the Telegram message id. Not wired in yet.
6. **Test:** a script sends a message with a `sc:mood:7` button. Tapping it upserts `checkin_events` and edits the message to `Mood: 7 ✓`. *[amended G10]*

**Acceptance criteria**
- Gateway restarted once, `is-active` passes, and every channel (incl. WhatsApp) plus the existing coach flows still work afterwards. The rollback command is documented.
- Tapping the test button writes the row and edits in place, and **no agent turn appears in the logs**.
- Unknown `sc:` data is logged, not passed to the agent. Non-`sc` callbacks are unaffected.
- Migrations are re-runnable, a backup exists, and the counts in pre-existing tables are unchanged.
- `send_coaching.py` works from the CLI against the test chat.

---

## Phase 2 — Feedback buttons

**Goal:** Replace typed 👍/👎 with buttons on every coaching message.

1. **Normal replies:** update `AGENTS.md` §1 so that, at the point where the agent currently posts its coaching reply, it calls `send_coaching.py --kind r` (passing the text via a temp file to avoid quoting issues) and then replies `NO_REPLY`. This only happens when `stoiclife_run.py` returns a sending decision (D18). The rest of the pipeline is unchanged. *[see G12]*
2. **Trigger pushes:** after `record_coaching.py` validates a push, it's sent with `send_coaching.py --kind t --target-id <id>` instead of as the agent's reply. Strict validation stays in front of sending.
3. **AGENTS.md §2:** keep typed 👍/👎 interpretation as the legacy fallback only.
4. **Handlers:**
   - 👍 → upsert `response_feedback`, clear buttons, append `Noted 👍`. For `t`, also update `trigger_coaching` usefulness (reuse the `record_reaction.py` logic). *[see G15]*
   - 👎 → upsert with rating `down` and swap in a reason row: `[Too generic] [Off-base] [Too long] [Tell me more]`.
   - A reason → update the row, clear buttons, append `Noted — <reason>`.
   - "Tell me more" → reply "What would have been more useful?" and set pending state `fb_more:<kind><id>` (2h expiry). The next free text routes to the note (Phase 4 routing; until then, have the agent call a `save_feedback_note.py` when that state is active). No coaching reply.
5. Typed 👍/👎 still work (legacy) and write to `response_feedback` against the latest target (respecting `record_reaction.py`'s existing 18h window). *[see G16]*

**Acceptance criteria**
- Every coaching reply and trigger push has buttons and a stored id.
- All paths persist correctly; re-tapping updates rather than duplicating.
- The agent's own message isn't sent twice (`NO_REPLY` respected).

---

## Phase 3 — Mood and module via buttons and commands

**Goal:** Replace `mood N` and `module:x`.

1. **Inline pickers** (reusable presentation blocks):
   - Mood: two rows, `[1]…[5]` and `[6]…[10]` → `sc:mood:<n>`
   - Module: `[Emotions] [Creativity] [Happiness]` → `sc:mod:<name>`
   - On tap: upsert `checkin_events`, edit to show `Mood: 7 ✓ · Module: Creativity ✓` (keep the unchosen picker visible), and offer `[📝 Add a note]` → `sc:note:<target>` → reply "Add your note" and set pending state `note:<target>`.
2. **Slash commands** via `api.registerCommand` (no LLM): `/mood` and `/module` send the picker, `/journal` sets pending state `adhoc` and replies "Go ahead", and `/skip` skips the currently pending session. Verify the commands appear in Telegram's `/` menu; if they don't, register them via `setMyCommands` once. *[registered in Phase 1 per G8]*
3. Legacy `mood N` / `module:x` keep working and write `checkin_events` with `source = legacy_prefix`. *[see Q1]*

**Acceptance criteria**
- Mood and module can be logged entirely by taps or commands, one per day each (latest wins), with an optional note.
- A same-day journal entry picks up the button mood as manual mood.
- No LLM turns from taps or commands.

---

## Phase 4 — Morning and evening without prefixes

**Goal:** Users journal by simply typing after a prompt.

1. **Morning message** (`coach_morning.sh`): send via the helper with buttons, then print `NO_REPLY` (D5). *[see G11]*
   ```
   ☀️ Morning prep · <Wed 8 Oct>
   Yesterday (<Tue>): <sleep> sleep · HRV <x> · RHR <x> · <steps> steps

   Anticipation: …
   Response: …
   Dichotomy: …

   Just type below to journal ↓
   [✍️ Write entry] [Skip today]
   Mood    [1]…[5] / [6]…[10]
   Module  [Emotions] [Creativity] [Happiness]
   ```
   - Label health data with the actual day.
   - Set pending state `morning` (expires 11:00) with the message id.
2. **Evening message** (20:30 job): same pattern with the evening review prompts, pending state `evening` (expires 03:00 next day), and `[✍️ Write entry] [Skip today]`. Mood buttons only if no mood was logged today.
3. **`route_entry.py`** (deterministic). Input: chat id, text, and optional reply-to message id. Output: the session to use. Priority:
   1. A legacy prefix is present → that session (strip the prefix).
   2. Reply-to matches a stored morning/evening message id → that session (even if expired). *[uses `ui_messages`, G4]*
   3. An active, unexpired pending state → its kind (`morning`, `evening`, `note:*`, `fb_more:*`, `adhoc`).
   4. Otherwise → `conversation` (AGENTS.md §3), not a journal entry.
4. **Update `AGENTS.md` §1:** for every inbound free-text message, the agent first runs `route_entry.py` and follows its output exactly. For `note:*` and `fb_more:*`, it saves via the relevant script and sends a short ack only. For `morning`, `evening` and `adhoc`, it runs the existing pipeline (`save_entry.py` → `coach_context.py` → compose → `update_entry.py` → `stoiclife_run.py`) and ends with `send_coaching.py` when the decision is to send. Remove the prefix-detection instructions and the "Save this as your morning prep?" confirmation, since `route_entry.py` handles both legacy prefixes and forgotten-prefix cases.
   - Questions and conversation (§3) must still work. Define how `route_entry.py` tells an entry from a question when no session is pending: default to §3 conversation unless the user used `/journal` or a write button. Only pending state or explicit intent creates an ad-hoc entry.
   - Check whether the reply-to id reaches the agent's context. If it does, pass it to `route_entry.py`. If it doesn't, skip rule 2 and note it in `CURRENT-STATE.md`.
5. **Buttons:**
   - `sc:write:<session>` → set pending state and reply "Go ahead — type your entry below."
   - `sc:skip:<session>` → record the skip, clear state, edit the message to `Skipped today`, and remove the write/skip buttons.

**Acceptance criteria**
- Plain text after morning or evening prep is saved to the right session and coached, with no prefix.
- Skip and write paths both work, and so do legacy prefixes.
- Text with no pending state is treated as conversation; `/journal` or a write button makes it an ad-hoc entry.
- `route_entry.py` has unit tests covering every priority rule and the expiry edge cases.

---

## Phase 5 — 11am update (always on)

**Goal:** A daily data update after the wearable sync, linked to the morning check-in.

1. **Understand first:** document how the current 11:00 safety-net job and FEAT-05 late-morning prep logic behave, and propose the smallest change before implementing it (D17).
2. The 11:00 run uses the **existing trigger engine** (`stoiclife_run.py`, 7-day baseline deltas and states) to classify the day, then always sends a compact update via the helper:
   ```
   📊 Last night: <sleep> sleep · HRV <x> (<±%> vs 7-day) · RHR <x>
   This morning: Mood 7 · Creativity · entry ✓
   ```
   - **Silent states** (neutral / sweet_spot / insufficient_data, or cooldown-suppressed): `--silent`, with no Stoic push.
   - **Firing states:** the existing escalation path runs (agent composes, `record_coaching.py` validates, sent via `send_coaching.py --kind t`). Quiet hours and cooldown behave exactly as today.
   - Log every update in `trigger_events` (or a linked table) so Phase 6 can measure it.
3. **Missing morning data:**
   - No mood/module → append "No check-in yet" plus the pickers.
   - No morning entry → use FEAT-05's existing late-prep behaviour, with a `[✍️ Write entry]` button added (sets pending state `morning` with a new expiry of 14:00). Don't create a second nudge.
4. If health data hasn't synced by 11:00, say so in one line and retry once at 12:00. Never present stale data as today's. *[see G13]*
5. The run is idempotent: one update per day, even if the job re-runs.

**Acceptance criteria**
- An update arrives every day (silent when normal, audible and escalated when flagged).
- Missing entries get one-tap fixes, and there are no duplicates on re-run.

---

## Phase 6 — Self-test instrumentation

**Goal:** Measure whether the UX works over a two-week self-test.

1. `scripts/ux_metrics.py <from> <to>` prints:
   - Completion rate for morning and evening separately (entry submitted ÷ prompt sent), plus the skip rate
   - Median time from prompt to entry
   - Mood and module logging rate, broken down by source
   - Feedback rate and 👍 share, by target kind (`r`/`t`), by session, and by flagged vs unflagged data
   - Entries by input method (typed after prompt / button-started / legacy prefix)
2. Once the legacy prefixes show zero use for a week, remove their parsing in a separate, reviewed change.

**Acceptance criteria**
- The script runs against the live DB and produces all of the metrics above.
