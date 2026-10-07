# Stoic Coach — Telegram UX Upgrade Plan (v4)

Phased implementation plan for the dedicated Stoic coaching Telegram bot (OpenClaw 2026.6.8, repo `~/projects/stoiclife`).
Hand this to Claude Code **one phase at a time**. Each phase ends with acceptance criteria. Don't start the next phase until they pass and the changes have been manually reviewed.

This file is the **spec**. Live progress (current phase, branch, step checkboxes, rollback, backups, logs and tests) is tracked in `docs/FEAT07-UX-TELEGRAM-PROGRESS.md` in the repo. Start each new session there.

## Status

| Phase | Status |
|---|---|
| 0 — Discovery | ✅ Merged (`docs/CURRENT-STATE.md`) |
| 1 — Foundation | ✅ Merged to `main` (not pushed) |
| 2 — Feedback buttons | ✅ Merged to `main` (not pushed). Live check: first real 07:30 / 20:30 replies |
| 3 — Check-in card | ✅ Merged to `main` at `26c9311` (not pushed). Bug P3-B1 fixed (D39). Live check: real `/mood` use |
| 4 — Morning/evening routing | 📝 Routing approach changed (D40); awaiting "plan Phase 4" discrepancy review |
| 5 — 11am update | Not started |
| 6 — Instrumentation | Not started |

> **v4 changes:** Phases 2–3 merged; D39 (plugin captures pending text on arrival) and D40 (Phase 4 routing decided by the plugin, not by the agent running a script) added; Phase 4 rewritten accordingly. **v3 changes:** Phase 2 and 3 revised after Code's pre-implementation review (D22–D38); D18 corrected. Earlier **v2 changes:** updated after the full Phase 0 findings (`docs/CURRENT-STATE.md`). Decisions D1–D21 are recorded in the next section. Main changes: 1–10 mood scale, evening review in scope, no ForceReply, reply keyboard or voice, free text still goes to the agent but its routing is decided by a deterministic script, and the 11am update builds on the existing trigger engine.

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
| D8 | Deterministic free-text interception needs plugin conversation binding (every message would hit the plugin first) | **Don't bind.** Free text needs the LLM anyway. Keep it going to the agent, but routing is decided deterministically, never by the LLM guessing from prefixes. Buttons and commands bypass the LLM via the plugin. *(Routing location updated by D40: the plugin decides on arrival.)* |
| D9 | Pending state | **Reuse the existing `state.json` / `set_prompt_state.py`** rather than a new `pending_state` table. Extend it with `kind`, `message_id`, `expires_at`, and key it by `chat_id` (future clients). |
| D10 | Silent send is CLI-only | Fine. The 11am routine update goes out from a script via `message send --silent`. |
| D11 | OpenClaw version | **Stay on 2026.6.8** for this work. Newer releases may add ForceReply (`ask_user`'s "Other…" opens Telegram's reply input in current docs), but don't upgrade mid-project. Revisit after Phase 6. |
| D12 | No migrations framework | Add a minimal one in Phase 1: numbered SQL scripts plus a `schema_migrations` table. Back up using the existing `stoic_journal.db.bak-<tag>-<ts>` pattern before each migration. |
| D13 | Coach has no plugin; installing one means editing the `plugins.allow` allowlist and restarting the gateway | Accepted. Do it in Phase 1, before any handler code is relied on. Snapshot `openclaw.json` first, restart once, and confirm the existing coach flows (morning cron, 11am, evening, inbound replies) still work before continuing. |
| D14 | Online "rich messages" docs page doesn't match 2026.6.8 | Use the **bundled** docs shipped with the installed version (Telegram channel and message-presentation) as the reference. Treat online docs as background only. |
| D15 | Voice transcription unverified | **Out of scope.** Voice notes will be a separate feature later. Don't test, wire up or install anything for voice in this plan. |
| D16 | Journal scripts (`save_entry.py`, `update_entry.py`, `set_prompt_state.py`, `evening-prompt.sh`, …) live in `~/.openclaw/workspace/scripts/`, which auto-commits | **New** scripts go in `~/projects/stoiclife/`. Changes to existing workspace scripts are allowed but kept minimal. List every workspace file touched in the phase summary, with a diff, so it can be reviewed despite the auto-commit. Don't move scripts between repos in this project. |
| D17 | The 11:00 job already runs a trigger engine (`stoiclife_run.py`: 7-day baseline deltas, states, cooldown, quiet hours, strict validator, FEAT-05 late-morning prep logic) | **Phase 5 builds on the engine; it doesn't replace it.** No new 14-day baseline or flag logic. The engine's state decides silent vs escalated. Cooldown, quiet hours, validation and FEAT-05 behaviour are preserved, and the "missing morning entry" nudge merges with FEAT-05 instead of duplicating it. |
| D18 | ~~Coaching replies are gated by `stoiclife_run.py`~~ **Corrected in v3:** the SEND_FULL / CLARIFY / SILENT / HOLD_QUIET decision governs the **🧭 trigger push**, not the coaching reply to a journal entry. | **Every coaching reply to a journal entry is always sent**, now with 👍/👎 buttons. The engine's decision only controls whether a 🧭 push goes out. |
| D19 | Timezone comes from the travel-mode setting, not a fixed zone | `local_date`, prompt expiries and the 11:00/14:00/03:00 cut-offs all use the **same timezone source the crons use**. Never hardcode Australia/Brisbane. |
| D20 | The gateway is shared (WhatsApp/Ewok and other channels), and a bad config takes all channels down | Restart at a quiet time. Snapshot `openclaw.json` and keep a one-command rollback ready. After restarting, check `is-active` and that **every** channel (not just the coach) reconnects, before continuing. |
| D21 | Two `openclaw` binaries; `/usr/bin` is stale | All scripts and helpers call `~/.npm-global/bin/openclaw` by absolute path (one constant in the helper). |

### Phase 2 decisions (from Code's pre-implementation review)

| # | Issue | Decision |
|---|---|---|
| D22 | D18 as originally written would have suppressed normal coaching replies | Superseded (see corrected D18). Coaching replies always go out with buttons. |
| D23 | The coach agent can't write files (no temp file for reply text) | Pass the reply text to `send_coaching.py` via **stdin pipe**, the same way `record_coaching.py` already works. |
| D24 | 11:00 push instructions live in the cron job's message, not `AGENTS.md` | Edit the 11:00 cron job's message too, after backing up the cron row. |
| D25 | Two-step sending for pushes is unnecessary | `record_coaching.py` gets a `--send` option: validate format → store → send with `sc:fb:t…` buttons in one step. Validation stays first. `send_coaching.py` keeps the `--kind r` path. |
| D26 | Editing message text after a tap loses Telegram formatting (bold) | On a tap, **only the buttons change** (e.g. to `✓ Noted 👍` or `✓ Noted — too generic`). The message text is never edited. This applies to all later phases too. |
| D27 | 🧭 CLARIFY questions have no stored push | No rating buttons on CLARIFY messages. |
| D28 | Two behaviours unproven: bold formatting via script sends, and agent `NO_REPLY` sending nothing in the DM | **Step P2.0** tests both with two labelled test messages before any other Phase 2 work, and stops if either fails. |
| D29 | Legacy typed feedback was underspecified | A small script applies a typed 👍/👎/neutral word to the **latest unrated coaching message (reply or push) within 18 hours**. `response_feedback.rating` accepts `up`, `down` and `neutral` (maps to usefulness 1/-1/0 for pushes). A second small script catches the "Tell me more" answer until Phase 4's routing replaces it. |

### Phase 3 decisions

| # | Issue | Decision |
|---|---|---|
| D30 | Separate pickers can't both stay visible after a tap | **One check-in card.** `/mood` and `/module` both open the same card (mood 2×5, modules, Add a note). Every tap redraws the whole card from the database, so it always shows the true state. |
| D31 | Button row layout | Exact rows (2×5 mood) work for command replies. Script-sent messages default to 3 per row, so script-sent pickers must be checked in later phases. |
| D32 | Command replies drop custom button rows | One-time fix in **our plugin** (`stoic-coach-ui`), made generic so later phases don't need another restart. **Must not patch OpenClaw core files** (an upgrade would overwrite them). Needs one more gateway restart, handled per D20. |
| D33 | Can't track message ids for command replies, so a stale card could log to the wrong day | Every check-in button carries its date: `sc:mood:7:20261008`, `sc:mod:creativity:20261008`, `sc:note:mood:20261008`. The date uses the travel-mode timezone (D19). A tap on a past day's card changes nothing and replies "This card has expired, use /mood". |
| D34 | `/journal` and `/skip` depend on Phase 4 routing and prompts | Moved to **Phase 4**. |
| D35 | Legacy typed `mood N` / `module:x` should feed the check-in data | Mirror them into `checkin_events` (`source = legacy_prefix`) **dated by the entry's timestamp, not "now"**, so a morning's typed mood can't land on the wrong day. No workspace script changes required. |
| D36 | "Add a note" needs the same pending-text mechanism as "Tell me more" | Generalise the Phase 2 catcher script to handle check-in notes too. There's **one pending slot** per chat: starting a new one (e.g. Add a note) cancels an unanswered one (e.g. Tell me more). |
| D37 | Commands see the chat id with a `telegram:` prefix | Normalise chat ids in one place (strip the prefix) so commands, buttons and scripts all use the same id. |
| D38 | "Same-day entry picks up button mood as manual" was delivered in Phase 1 | Re-test in Phase 3; don't rebuild. |

### Phase 3 outcome and Phase 4 direction

| # | Issue | Decision |
|---|---|---|
| D39 | **Bug P3-B1:** OpenClaw appended the user's message to the end of the chat history, so the coach misread it and the note was lost | The plugin **saves pending text (notes, "Tell me more") the moment the message arrives**, before the coach is involved. The coach only sends the short "Thanks, noted." Fixed and verified live. |
| D40 | Phase 4 routing via the agent running `route_entry.py` first relies on the LLM remembering to do so, and P3-B1 showed the agent's view of the message can be unreliable | **Supersedes the routing part of D8.** The plugin decides the route as each message arrives (legacy prefix → reply-to match → pending slot → conversation) and records the decision. The agent only acts on that recorded decision. Still no conversation binding: the message continues to the agent as today. `route_entry.py` becomes the plugin's routing logic (or a module it calls), and keeps unit tests for every rule and expiry edge case. |

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

**Key architectural rule:** button taps and slash commands are handled **deterministically by the plugin**, never by the LLM. Free text goes to the agent, but which session it belongs to is decided **by the plugin on arrival** (D40), not by the LLM.

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

## Phase 1 — Foundation: plugin, migrations, helpers ✅ merged

**Goal:** The `sc` plugin works end to end on a test button. No user-facing flow changes yet.

1. **Migrations:** add a `migrations/` folder, a runner script and a `schema_migrations` table, coexisting with the existing `db_init.py` (don't rewrite it). Back up the DB first. Migration `001_ux_tables`:
   ```sql
   CREATE TABLE IF NOT EXISTS checkin_events (
     id          INTEGER PRIMARY KEY AUTOINCREMENT,
     chat_id     TEXT NOT NULL,
     local_date  TEXT NOT NULL,          -- Australia/Brisbane
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
   ```
2. **Mood precedence:** a button or command mood counts as a **manual** mood. When an entry is saved for that day, merge today's `checkin_events` into `journal_entries`: `mood_score` with `mood_source='manual'`, and `module`. An inline `mood N` / `module:x` in the entry text wins over the button value for that entry. `update_entry.py`'s existing never-overwrite-manual rule stays intact.
3. **Plugin `stoic-coach-ui`:**
   - Register an interactive handler, namespace `sc`, on Telegram, restricted to the `coach` account. Reject taps where `ctx.auth.isAuthorizedSender` is false.
   - Parse and validate per the scheme. Unknown values are logged and ignored.
   - Each action is a small handler that calls Python scripts (or writes SQLite directly; pick one and be consistent) and then edits the message.
   - Add it to `plugins.allow`. Set `channels.telegram.accounts.coach.capabilities.inlineButtons: "dm"` explicitly.
   - Snapshot `openclaw.json` before editing, restart the gateway once at a quiet time, and confirm that **all** channels and the existing coach flows still work (D13, D20).
   - Reference: the bundled Telegram and message-presentation docs for 2026.6.8 (D14).
4. **Shared helpers** (`scripts/tg.py` or similar), wrapping `openclaw message send/edit`:
   - send with presentation buttons, returning the message id (`--json`)
   - send silently (`--silent`)
   - edit text and buttons
   - set/read/clear pending state (extend `set_prompt_state.py` / `state.json` per D9)
5. **`send_coaching.py`:** two modes.
   - `--kind r`: takes entry id, session, data flags and reply text, inserts `coaching_responses`, and sends with `[👍 Helpful] [👎 Not quite]` (`sc:fb:r<id>:…`).
   - `--kind t --target-id <trigger_coaching.id>`: sends an existing push with `sc:fb:t<id>:…` buttons.
   - Both store the Telegram message id. Not wired in yet.
6. **Test:** a script sends a message with a `sc:mood:7` button. Tapping it upserts `checkin_events` and edits the message to `Mood: 7 ✓`.

**Acceptance criteria**
- Gateway restarted once, `is-active` passes, and every channel (incl. WhatsApp) plus the existing coach flows still work afterwards. The rollback command is documented.
- Tapping the test button writes the row and edits in place, and **no agent turn appears in the logs**.
- Unknown `sc:` data is logged, not passed to the agent. Non-`sc` callbacks are unaffected.
- Migrations are re-runnable, a backup exists, and the counts in pre-existing tables are unchanged.
- `send_coaching.py` works from the CLI against the test chat.

---

## Phase 2 — Feedback buttons ✅ merged

**Goal:** Replace typed 👍/👎 with buttons on every coaching reply and 🧭 push. No gateway restart expected.

0. **P2.0 checks (D28), before anything else:** send two labelled test messages to the coach chat, to confirm (a) bold formatting survives a script send, and (b) an agent `NO_REPLY` in the DM sends nothing. If either fails, stop and report.
1. **Coaching replies (D18, D23):** update `AGENTS.md` §1 so that, where the agent currently posts its coaching reply, it pipes the text into `send_coaching.py --kind r` (with entry id and session) and then replies `NO_REPLY`. **Every** coaching reply to a journal entry goes out this way, whatever `stoiclife_run.py` decides about pushes.
2. **🧭 pushes (D24, D25, D27):** `record_coaching.py --send` validates the format, stores the push, and sends it with `sc:fb:t<id>:…` buttons. Update the 11:00 cron job's message (back up the cron row first) and anywhere else pushes are sent. CLARIFY questions get no buttons.
3. **AGENTS.md §2:** typed 👍/👎 handling becomes the legacy fallback and calls the D29 script instead of the LLM interpreting it.
4. **Handlers (D26, buttons only; text never edited):**
   - 👍 → upsert `response_feedback`, replace the buttons with `✓ Noted 👍`. For `t`, also set `trigger_coaching` usefulness.
   - 👎 → upsert rating `down`, replace the buttons with the reason row `[Too generic] [Off-base] [Too long] [Tell me more]`.
   - A reason → update the row, replace the buttons with `✓ Noted — <reason>`.
   - "Tell me more" → reply "What would have been more useful?" and set the single pending slot to `fb_more:<kind><id>` (2h expiry). The catcher script (D29) saves the next free text as the note and sends a short ack; no coaching reply.
5. **Legacy typed feedback (D29):** applies to the latest unrated reply or push within 18 hours; accepts up, down and neutral.

**Acceptance criteria**
- P2.0 passed (or stopped with a report).
- Every coaching reply has buttons and a `coaching_responses` row; every valid 🧭 push has buttons; CLARIFY has none.
- All tap paths persist; re-tapping updates rather than duplicating; message text and formatting are unchanged after taps.
- The agent's message is never sent twice.
- Typed 👍/👎/neutral and the "Tell me more" note both persist to the right target.

---

## Phase 3 — Check-in card (mood and module) ✅ merged

**Goal:** Replace typed `mood N` / `module:x` with one tappable check-in card. No LLM involved in any tap or command.

1. **Plugin layout fix (D32):** make command replies keep custom button rows, as a generic fix in `stoic-coach-ui` only. Restart the gateway once at a quiet time, following D20.
2. **Check-in card (D30, D33):** `/mood` and `/module` both open:
   ```
   Check-in · Thu 8 Oct
   Mood: 7 ✓ · Module: Creativity ✓
   [1] [2] [3] [4] [5]
   [6] [7✓] [8] [9] [10]
   [Emotions] [Creativity ✓] [Happiness]
   [📝 Add a note]
   ```
   - Every tap upserts `checkin_events` (one mood and one module per day; latest wins) and redraws the card from the database.
   - Buttons carry their date; a tap on a past day's card replies "This card has expired, use /mood" and changes nothing.
3. **Add a note (D36):** sets the single pending slot to `note:<mood|module>:<date>`; the generalised catcher saves the next free text to that day's event. Starting it cancels any unanswered "Tell me more".
4. **Legacy prefixes (D35):** typed `mood N` / `module:x` keep working and are mirrored into `checkin_events` with `source = legacy_prefix`, dated by the entry's timestamp.
5. **Chat ids (D37):** normalise in one place.
6. **Re-test (D38):** same-day journal entry picks up the card's mood as manual mood.

**Acceptance criteria**
- `/mood` and `/module` open the card with a 2×5 mood layout; mood, module and note can be logged entirely by taps.
- The card always reflects the database after each tap; stale cards are refused.
- Typed legacy mood/module still work and land on the right day.
- No LLM turns from taps or commands (verified in logs); all channels healthy after the restart.

---

## Phase 4 — Morning and evening without prefixes

**Goal:** Users journal by simply typing after a prompt.

1. **Morning message** (`coach_morning.sh`): send via the helper with buttons, then print `NO_REPLY` (D5).
   ```
   ☀️ Morning prep · <Wed 8 Oct>
   Yesterday (<Tue>): <sleep> sleep · HRV <x> · RHR <x> · <steps> steps

   Anticipation: …
   Response: …
   Dichotomy: …

   Just type below to journal ↓
   [✍️ Write entry] [Skip today]
   (check-in card buttons from Phase 3, dated per D33)
   ```
   - Label health data with the actual day.
   - Set pending state `morning` (expires 11:00) with the message id.
2. **Evening message** (20:30 job): same pattern with the evening review prompts, pending state `evening` (expires 03:00 next day), and `[✍️ Write entry] [Skip today]`. Mood buttons only if no mood was logged today.
3. **Routing on arrival (D40).** When a free-text message arrives, the plugin decides its route before the agent is involved, and records it where the agent can read it reliably. Priority:
   1. A legacy prefix is present → that session (strip the prefix).
   2. Reply-to matches a stored morning/evening message id → that session (even if expired).
   3. An active, unexpired pending slot → its kind (`morning`, `evening`, `note:*`, `fb_more:*`, `adhoc`). Notes and `fb_more` are already saved by the plugin (D39).
   4. Otherwise → `conversation` (AGENTS.md §3), not a journal entry.
   - The routing logic has unit tests for every rule and the expiry edge cases.
4. **Update `AGENTS.md` §1:** the agent reads the recorded route and acts on it; it never decides the session itself. For `morning`, `evening` and `adhoc`, it runs the existing pipeline (`save_entry.py` → `coach_context.py` → compose → `update_entry.py` → `stoiclife_run.py`) and always sends the reply via `send_coaching.py` (corrected D18). For notes and `fb_more`, it only acknowledges. Remove the prefix-detection instructions and the "Save this as your morning prep?" confirmation.
   - If no route has been recorded for a message (e.g. the plugin failed), the agent treats it as conversation and logs the gap, rather than guessing.
5. **Buttons:**
   - `sc:write:<session>` → set pending state and reply "Go ahead — type your entry below."
   - `sc:skip:<session>` → record the skip, clear state, and replace the write/skip buttons with `✓ Skipped today` (buttons only, per D26).
6. **Slash commands moved from Phase 3 (D34):** `/journal` sets the pending slot to `adhoc` and replies "Go ahead — type your entry below"; `/skip` skips the currently pending morning or evening session.

**Acceptance criteria**
- Plain text after morning or evening prep is saved to the right session and coached, with no prefix.
- Skip and write paths both work, and so do legacy prefixes.
- Text with no pending state is treated as conversation; `/journal` or a write button makes it an ad-hoc entry.
- Routing unit tests cover every priority rule and expiry edge case, and logs show the route was recorded before the agent acted on each message.

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
4. If health data hasn't synced by 11:00, say so in one line and retry once at 12:00. Never present stale data as today's.
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
