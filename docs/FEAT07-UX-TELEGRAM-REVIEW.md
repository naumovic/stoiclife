# FEAT-07: Code's review notes (gaps G1–G20)

Moved here on 2026-10-07 when the v4 spec replaced `FEAT07-UX-TELEGRAM-SEED.md`. These are Claude Code's review gaps from Phases 0–1 and their amendments. The PROGRESS file and commit messages refer to them as G1–G20. Later reviews live in the PROGRESS file (P2-D*, P3-D*, P4-D*) and, once adopted, as D-numbers in the spec.

## Gaps and amendments (Claude, 2026-10-07)

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
