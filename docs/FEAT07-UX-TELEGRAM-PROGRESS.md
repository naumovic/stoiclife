# FEAT-07 Telegram UX: progress checklist

The step-by-step tracker for FEAT-07. **If a session ends, start here.** The spec (v4, maintained with Claude Opus) is `docs/FEAT07-UX-TELEGRAM-SEED.md`; Code's early review gaps G1–G20 are in `docs/FEAT07-UX-TELEGRAM-REVIEW.md`. Current-system facts are in `docs/CURRENT-STATE.md`. Dated history goes in `docs/PROGRESS.md`. Tick boxes as steps land, and commit this file with the step.

## ▶ Resume here

- **Status (2026-10-08):** Phases 0–5 merged and pushed; Phase 6 metrics merged and pushed. **Self-test running** (two weeks from 2026-10-08). Mihajlo: treat anything found as bugs, fix freely.
- **Branch:** `main` (create `fix/<topic>` branches for bug fixes). Push when a fix is done and tested.
- **Watch / open:** first real 11:00 update (P5.3b); bug P4-B1 (coach replies to a bare "thanks"?); a flagged day's CLARIFY / SEND_FULL path end to end; late-morning hold after 11:00; legacy prefix removal after a week of zero use.
- **Metrics:** `python3 ux_metrics.py 2026-10-08 $(date +%F)`.
- **Note:** the coach workspace *is* this repo dir, so the checked-out branch's `coach-workspace/AGENTS.md` is what's live. Plugin `index.js` changes need a gateway restart; Python ones don't.

## Live state pointers

| What | Where |
|---|---|
| Plugin | `plugin/stoic-coach-ui/` (linked install; thin shim → `sc_dispatch.py`). Editing Python needs no restart; editing `index.js` does. |
| Config snapshot before the plugin | `~/.openclaw/openclaw.json.pre-feat07-20261007-222449` |
| Rollback | `OPERATIONS.md` → "FEAT-07 coach UI plugin" (one command) |
| DB backup before migration 001 | `~/.openclaw/stoic/stoic_journal.db.bak-mig001-20261007-222424` |
| Migrations | `python3 migrate.py --status` / `python3 migrate.py` (backs up first) |
| Logs | `~/.openclaw/stoic/stoic.log` (`tg:` / `sc_dispatch:` lines); `journalctl --user -u openclaw-gateway \| grep stoic-coach-ui` |
| Tests | `python3 tests/test_feat07_phase1.py` (+ each phase's file), plus `test_manual_mood`, `test_stoic_modules`, `test_channel_fmt`, `test_late_morning` |
| Workspace scripts touched (auto-committed repo, D16) | `save_entry.py`, `set_prompt_state.py` (Phase 1) |

## Phase 0: Discovery ✅
- [x] `docs/CURRENT-STATE.md` (crons, inbound path, parsing, schema, capability yes/no)

## Phase 1: Foundation ✅ (merged 2026-10-07)
- [x] Migration runner `migrate.py` + `001_ux_tables.sql` (checkin_events, coaching_responses + text, response_feedback, ui_messages); live backup; re-run is a no-op; counts unchanged
- [x] `checkins.py` (logical-day `local_date` G1, upsert, G9 merge rule)
- [x] `tg.py` (CLI send/edit, pending state G2, ui_messages G4)
- [x] `sc_dispatch.py` (mood/mod live; other actions logged "later phase"; stale-picker guard G5)
- [x] `send_coaching.py` r/t (not wired in)
- [x] Plugin shim + `/mood /module /journal /skip` ("Coming soon") (G6, G8)
- [x] Workspace: `save_entry.py` merge + keep `pending`; `set_prompt_state.py` read-modify-write
- [x] Gateway window: allow-list, `inlineButtons: dm`, one restart; all channels back
- [x] Live acceptance: tap → row + edit, no agent turn; unbuilt `sc:` logged; "hi" answered; test rows cleaned
- [x] Q1 = no (tap after an entry doesn't update it); Q2 = yes (commands in the menus, incl. the trip bot)

## Phase 2: Feedback buttons ✅ (merged 2026-10-07)

### Discrepancies vs plan v2 (approved fixes)
- **P2-D1** In the journal flow, the normal coaching reply is *always* sent (SILENT/HOLD_QUIET/CLARIFY too), now through `send_coaching --kind r`. "Nothing on SILENT" applies only to the 11:00 cron. (Plan step 1 / D18 would have dropped normal replies.)
- **P2-D2** Text goes to `send_coaching.py` on **stdin**, not a temp file. The coach can't write files.
- **P2-D3** The 11:00 push instructions live in cron `700b6841`'s message, so it gets edited too (back up the job first).
- **P2-D4** `record_coaching.py --send`: validate → store → send with `t` buttons → `NO_REPLY`. Without the flag it behaves as today.
- **P2-D5** Feedback taps swap **buttons only** (`✓ Noted 👍`, reason row, `✓ Noted: …` via `sc:noop`). They never re-edit coaching text, which would lose the bold.
- **P2-D6** No buttons on 🧭 CLARIFY lines (no `trigger_coaching` row).
- **P2-D7** Verify `**bold**` renders via `openclaw message send` before relying on it.
- **P2-D8** Verify an agent `NO_REPLY` in a DM turn sends nothing (G12).
- **P2-D9** `record_feedback.py` for typed 👍/👎/neutral: latest unrated `r`|`t` in `ui_messages` within 18h; `t` also → `record_reaction.py --coaching-id`.
- **P2-D10** `save_feedback_note.py` runs first on unprefixed messages and saves the text only if `fb_more:*` is pending; otherwise `NONE`.
- **P2-D11** `send_coaching --kind r --entry-id N` fills `data_flags_json` itself from that entry's latest `trigger_events` row.

### Steps
- [x] **P2.0** Live checks (2026-10-07): bold + strict-format markup via `tg.send` with buttons renders correctly (msg 69; CLI sends default to markdown→HTML, `send-*.js` textMode); an inbound DM turn answered `NO_REPLY` → no outbound send in the gateway log. Test row cleaned.
- [x] **P2.1** `send_coaching.py`: `--text-stdin`; r auto `data_flags_json`
- [x] **P2.2** `record_coaching.py --send` (exit 2 invalid / 3 send failed → event reset to unsent); `stoiclife_run.py` prints the command with `--send` on telegram only
- [x] **P2.3** `sc_dispatch.py`: `fb` up/down, `fbr` reasons, `more` → pending `fb_more:<k><id>` (2h), `noop`; `t` → `record_reaction.py --coaching-id`
- [x] **P2.4** `save_feedback_note.py`
- [x] **P2.5** `record_feedback.py` (typed legacy)
- [x] **P2.6** `coach-workspace/AGENTS.md` §1 step 0 + step 6/7, §2 (7.5k chars). ⚠️ The coach workspace *is* this repo dir, so the checked-out branch's AGENTS.md is what's live.
- [x] **P2.7** Cron `700b6841` message → `record_coaching … --send`, then `NO_REPLY` (exit 3 → reply the text). Backup `~/.openclaw/cron/bak-feat07-p2-safetynet-20261007-225138.json`
- [x] **P2.8** `tests/test_feat07_phase2.py` 43/43; phase1 67/67 (fb now live); existing suites green. `tg.py` gained a `STOICLIFE_TG_FAKE` test hook.
- [x] **P2.9a** Live button acceptance (2026-10-07 22:56–22:58): 👍 on a `t` push → `✓ Noted 👍`, trigger_coaching/events usefulness +1 via record_reaction; 👎 on an `r` reply → 2×2 reasons → Tell me more → question + pending `fb_more:r2` → typed note saved by step 0 (`SAVED`), single "Thanks, noted." (second transcript copy = delivery-mirror); no agent turn on taps. Test rows removed, push 19 restored to unrated.
- [x] **P2.9b** Agent wiring, via a throwaway entry (2026-10-07 23:03): save → context → update → stoiclife_run (HOLD_QUIET) → `send_coaching --kind r` → agent `NO_REPLY`; one outbound message (81) with 👍/👎; `data_flags_json` filled (event 239). Test rows + the quiet-hours hold deleted. Tomorrow's real entries = confirmation; anything odd is logged as a bug.
- [x] Phase summary (PROGRESS.md 2026-10-07); no workspace scripts or gateway config touched; merged to main

## Phase 3: Mood/module buttons + commands ✅ (merged 2026-10-07)

### Discrepancies vs plan v2 (proposed fixes)
- **P3-D1 One check-in card, not separate pickers.** "Keep the unchosen picker visible" only works if mood and module share a message. `/mood` and `/module` both send the same card: a status line (`Mood: 7 ✓ · Module: Creativity ✓`), mood 1–5 / 6–10, the three modules, and `📝 Add a note` once something is chosen. Every tap re-renders the whole card from the DB, so it is deterministic and never built from the callback's plain text (P2-D5 lesson).
- **P3-D2 2×5 mood rows are possible for command replies** (G18 resolved for them): `channelData.telegram.buttons` takes precedence over presentation (`resolveTelegramInlineButtons`). Script-sent cards (Phase 4/5) stay 3-per-row unless they're sent another way; decide then.
- **P3-D3 The plugin shim drops `channelData`.** It returns only `text`/`presentation` for commands, so **one `index.js` change + one gateway restart** is needed (G8 assumed none). Make the shim pass the dispatcher's reply object through untouched, so later phases need no further restart.
- **P3-D4 Stale cards from commands can't be caught by `ui_messages`.** The framework sends command replies, so we never learn their message id (G5 only works for script sends). Fix: card buttons carry the day, `sc:mood:7:20261008` / `sc:mod:creativity:20261008` / `sc:note:mood:20261008` (≤ 30 bytes). A tap whose day isn't today → card edited to "expired, use /mood". The plan's suffix-less forms stay accepted (→ `ui_messages`, else today).
- **P3-D5 `/journal` and `/skip` depend on Phase 4.** An `adhoc` pending state means nothing until `route_entry.py` exists, and skipping needs the prompt messages Phase 4 creates. Keep them "Coming soon" until Phase 4.
- **P3-D6 Legacy `mood N` / `module:x` → `checkin_events` needs no workspace edit.** `checkins.merge_into_entry` (already called by `save_entry.py`) also records the entry's inline values as `legacy_prefix`, stamped with the **entry's `created_at`**. If it were stamped "now", the G9 rule would treat it as newer than the entry and leak the morning's inline mood onto the evening entry.
- **P3-D7 "Add a note" needs the step-0 script to handle `note:*` too.** Rename `save_feedback_note.py` → `save_pending_note.py` (handles `fb_more:*` and `note:<mood|module>` → `checkin_events.note` on today's row) and update the AGENTS.md step 0 path. One pending slot per chat, so a newer intent replaces an older one (e.g. a note tap cancels an unanswered "Tell me more").
- **P3-D8 Command chat id arrives as `telegram:8917837483`.** The dispatcher strips the `telegram:` prefix (the Phase 1 shim passes `ctx.from`).
- **P3-D9 Acceptance "a same-day entry picks up the button mood" was already met in Phase 1** (G9), with Q1 = no. Re-verified in tests, not rebuilt.

### Steps
- [x] **P3.1** `checkins.py`: `record_inline()` (legacy_prefix @ entry created_at, called from `merge_into_entry`), `set_note()`, `today_state()`
- [x] **P3.2** `sc_dispatch.py`: card render; `mood`/`mod` with optional `:YYYYMMDD`, re-render on tap; stale-day guard; `note:<t>[:day]` → pending `note:<t>` (2h) + "Add your note below."; `/mood` `/module` → card via `channelData.telegram.buttons`; chat-id normalise; `/journal` `/skip` stay "Coming soon"
- [x] **P3.3** `save_pending_note.py` (rename + `note:*`); AGENTS.md step 0 path
- [x] **P3.4** Plugin shim: pass the dispatcher reply object through (text, channelData, presentation)
- [x] **P3.5** `tests/test_feat07_phase3.py` 33/33; phase1 67/67 (card semantics), phase2 43/43 (rename); existing suites green
- [x] **P3.6** Gateway restart 2026-10-07 23:14 (shim pass-through live); `is-active`, plugin registered, WhatsApp + both Telegram bots back
- [x] **P3.7** Live acceptance 2026-10-07 23:16–23:19: `/mood` in the menu → 2×5 card; mood + module taps re-render in place; old card → expired; `/journal` → Coming soon; no agent turn on taps/commands. **Except the note:** see bug P3-B1. Test rows cleaned.
- [x] **P3.8 Bug P3-B1: typed note not saved.** OpenClaw appends the inbound text to the recent-history block with no separator (`#82 … test card.\n\nRockin`); the coach read "Rockin" as part of msg 82, skipped step 0 and replied `NO_REPLY`. **Fix:** the plugin's `message_received` hook (coach account) pipes every non-command, non-prefixed message to `sc_dispatch.py` (kind `message`) → `save_pending_note.save_note(from_hook=True)` saves deterministically and leaves a `consumed` marker in state.json; the coach's step 0 on the same text (≤10 min) answers `SAVED` from it. AGENTS.md: "his message is the text after the last `#N` line", step 0 runs first, never `NO_REPLY` to him unless a script sent the reply. Gateway restart 23:25. **Live 23:27:** hook saved the note at :28.696, step 0 got SAVED at :32.7, one "Thanks, noted."; a normal "Ok then" → hook `saved=False`, step 0 `NONE`, normal reply. Tests phase3 48/48.
- [x] Phase summary (PROGRESS.md 2026-10-07); merged to main

## Phase 4: Morning/evening without prefixes ✅ (merged + pushed 2026-10-08)

### Answers to Opus's two questions (2026-10-07)
- **Where the D32 layout fix lives:** only in our repo. `sc_dispatch.py` returns `channelData.telegram.buttons` (a supported `ReplyPayload` field that OpenClaw prefers over presentation), and `plugin/stoic-coach-ui/index.js` passes the reply through. Nothing in the OpenClaw install has changed: `find ~/.npm-global/lib/node_modules/openclaw -newermt 2026-10-06` → 0 files; the newest file there dates from the 2026-06-20 install. Upgrade risk: `channelData.telegram.buttons` is a channel-specific field and could change in a new release, so add "`/mood` shows a 2×5 card" to the post-upgrade checks.
- **Ordering guarantee:** `message_received` (used for the P3-B1 fix) is **fire-and-forget**: `dispatch-*.js` calls it via `fireAndForgetHook(...)`, so there's **no** ordering guarantee. The note fix was safe only because the consumed marker works in either order. Phase 4 therefore uses two **awaited** hooks instead (P4-D1).

### Discrepancies vs v4 (proposed fixes)
- **P4-D1 Route via `before_dispatch` + `before_prompt_build`, both awaited.** `before_dispatch` runs on the inbound path *before the agent is dispatched*: `await … hookRunner.runBeforeDispatch(...)` in `dispatch-*.js`, followed by the agent dispatch. It gets the clean message `content`, `accountId`, `conversationId` and `replyToId`. The plugin computes the route there (Python `route_entry.py`, unit-tested) and records it, keyed by session key. `before_prompt_build` (awaited before the model call in `attempt.prompt-helpers-*.js`) then **puts the route into the coach's prompt** (`prependContext`, e.g. `[stoiclife route] morning · prompt msg 312 · day 2026-10-08`). The coach never has to run anything to learn the route. Ordering is guaranteed by the code path, not by timing. Both hooks log a timestamped line, which gives the acceptance evidence.
- **P4-D2 Notes and "Tell me more" become fully LLM-free.** `before_dispatch` can return `{handled: true, text}`, and OpenClaw then sends that text and **skips the agent**. A pending note/`fb_more` is saved and answered "Thanks, noted." right there. This supersedes D39's implementation: the `message_received` hook and AGENTS.md step 0 are removed (the consumed marker becomes unused).
- **P4-D3 Prompt buttons: script sends are 3 per row (D31).** The 2×5 card can't be embedded in a script-sent prompt. Prompt buttons: `[✍️ Write entry] [Skip today]` + `[🙂 Check in]`. Check in → `sc:card:<day>`, and the plugin **replies with the full 2×5 card** (callback replies take exact rows). Evening shows Check in only if no mood is logged that day.
- **P4-D4 A hard 11:00 expiry would break FEAT-05.** A morning prep typed at 12:59 would become conversation; today the coach asks "Save this as your morning prep?". Proposal: before the expiry, free text → entry (deterministic). After it, until the next prompt, route `late:morning` → the coach asks that same confirmation (today's behaviour). Same for evening after 03:00.
- **P4-D5 Questions inside the open window.** A pure state rule saves "what was my HRV?" typed at 08:00 as the morning entry. **Decision needed:** (a) accept it, or (b) a message ending in `?` → conversation, even while the window is open.
- **P4-D6 `adhoc` isn't a session anywhere downstream.** `save_entry.py`, `stoiclife_run.py` and the trigger matrix only know morning/evening (and safety-net). Proposal: `/journal` (and Write after expiry) opens the **current** session: morning if there's no morning entry yet today and the evening prompt hasn't gone out, else evening.
- **P4-D7 Skips have nowhere to be stored.** Migration `002_prompt_events`: one row per prompt (day, session, message_id, sent_at, expires_at, skipped_at, entry_id, opened_by). Skip writes `skipped_at` and clears the pending slot and legacy `awaiting_response`. It also gives Phase 6 its completion, skip and time-to-entry numbers.
- **P4-D8 Evening gets its own script.** New `coach_evening.sh` in stoiclife (same pattern as `coach_morning.sh`), cron `7e8a7edd` repointed (job backed up). Workspace `evening-prompt.sh` stays untouched, since the WhatsApp rollback uses it.
- **P4-D9 Prompt send safety.** D5 (`NO_REPLY` from a command cron sends nothing) is documented and already relied on by the weekly job; verify live once with a labelled one-shot job. If the CLI send fails, the script prints the prompt as plain text instead, so a prompt is never lost.
- **P4-D10 Keep legacy `state.json` in step.** Prompts still call `set_prompt_state.py` (prompt-date attribution in `save_entry.logical_date`). The new pending slot sits alongside it, and skip/expiry clear both.
- **P4-D11 Fallback (v4).** If the coach's prompt has no route (hook failed), the injected line says `no route recorded`. The coach treats the message as conversation, the gap is logged, and it may suggest `/journal`.
- **P4-D12 One gateway restart** (shim gains `before_dispatch` + `before_prompt_build`; `message_received` removed).
- **P4-D13 Verify live that both hooks see the same session key.** If they don't, match on "latest unconsumed route for agent `coach`, < 2 min old".

### Mihajlo's answers (2026-10-07) → spec D44–D46
- P4-D4: after 11:00 (until the evening prompt) the **plugin** holds the message with `[📝 Save as morning prep] [💬 Just chatting]`; evening the same after 03:00.
- P4-D5: a `?` message inside an open window is held with `[📝 It's my entry] [❓ It's a question]`.
- One "hold and confirm" component for both. Mechanism (verified in `bot-*.js`): the tap handler returns `handled: false`, so OpenClaw sends a synthetic `callback_data: sc:hold:…` message through the normal pipeline; `before_dispatch` resolves the hold and records the route with the held text.

### Steps
- [x] **P4.1** Migration `002_prompt_events`; `route_entry.py` (prefix → reply-to → write/journal → window (`?` → hold) → late (hold) → conversation; expiries in the travel tz) + `holds` in state.json + unit tests
- [x] **P4.2** `sc_dispatch.py`: kinds `dispatch` (route, notes handled, holds) and `prompt` (route injection); `sc:hold`, `sc:write`, `sc:skip`, `sc:card`; `/journal`, `/skip` live; prompt answered-linking on save (via `checkins.merge_into_entry`)
- [x] **P4.3** `coach_morning.sh` + new `coach_evening.sh`: helper send with buttons, `prompt_events` + `ui_messages`, print `NO_REPLY`; plain-text fallback
- [x] **P4.4** AGENTS.md §1: act on the injected route (use its text verbatim); remove prefix detection, the forgotten-prefix question and step 0
- [x] **P4.5** Plugin shim: `before_dispatch` + `before_prompt_build`; `passToAgent` support for taps; drop `message_received`
- [x] **P4.6** Tests (every routing rule + expiry edges, holds, handlers, scripts with the fake sender); all suites green
- [x] **P4.7** Quiet-window restart; repoint the evening cron; one-shot command-cron `NO_REPLY` check
- [x] **P4.7 notes** Live DB migrated (backup `stoic_journal.db.bak-mig002-20261007-235648`); evening cron `7e8a7edd` → `coach_evening.sh` (backup `~/.openclaw/cron/bak-feat07-p4-evening-20261007-235652.json`); restart 23:57, all channels back; one-shot command cron ran `coach_evening.sh` → one outbound (msg 105, buttons), run `ok`/`not-delivered` (NO_REPLY suppressed: D5/D51 verified).
- [x] **P4.8** Live acceptance 2026-10-08 00:01–00:06: `Was today a good day?` → hold buttons → ❓ → coach answered the held question (route #2 via the synthetic tap); plain text → evening entry 215 + one coaching reply with 👍/👎, prompt linked; `/skip` → nothing to skip; note → saved + "Thanks, noted." by the plugin, the coach never saw it. Every route recorded by `before_dispatch` then injected by `before_prompt_build` (session-key match, 0.2–0.4 s apart). Late holds (after 11:00 / 03:00) covered by unit tests only (same component). Test data removed.
- [ ] **Bug P4-B1:** the coach answered `Thanks` (CONVERSATION route) with `NO_REPLY`. The route line now says "always reply, even to a bare thanks; never NO_REPLY here" (Python only, no restart). Verify on the next casual message.
- [x] Phase summary (PROGRESS.md 2026-10-08); merged to main and pushed

## Phase 5: 11am update ✅ (merged + pushed 2026-10-08)

Step 1 (understand first) is written up in `docs/CURRENT-STATE.md` §7.

### Discrepancies vs spec v4.1 (proposed fixes)
- **P5-D1 The update must be deterministic, but the 11:00 job is an agentTurn.** Smallest change (D17): keep the proven cron. Its step 1 runs a new **`daily_update.py`** instead of `stoiclife_run.py`. The script runs `stoiclife_run.py` itself, sends the compact update (a script send, no LLM), then prints the engine's directive **unchanged**, so the coach's SILENT / CLARIFY / SEND_FULL handling stays exactly as today. Not chosen: a command cron plus `openclaw agent --deliver` for pushes. That's fully LLM-free but a new, untested path.
- **P5-D2 FEAT-05 is not a nudge to merge with.** It's coaching for a late entry, and it stays as is. The "missing morning entry" one-tap fix is the update's `No morning entry yet` + `[✍️ Write entry]` (the existing write slot). Spec step 3's "pending morning, expiry 14:00" conflicts with D45 (the late hold lasts until the evening prompt), so **drop the 14:00 expiry**.
- **P5-D3 Pickers in the update → `[🙂 Check in]`** (opens the 2×5 card), as in D47. Script sends can't lay out the picker (D31).
- **P5-D4 One ping on a flagged day, not two.** The spec makes the update audible on firing days, and the push is a second audible message seconds later. Proposal: the update is **always silent**, and on a firing day the 🧭 push is the one notification. **Decision needed.**
- **P5-D5 "Synced" needs a precise test.** It means today's row has sleep data and a sleep score (reuse `status.health_check`). A lagged row is never shown as "last night". Not synced at 11:00 → one silent line ("Last night's data hasn't synced yet, I'll check again at 12:00") + a new **12:00 retry cron** (same agentTurn, `daily_update.py --retry`). It does nothing if the 11:00 update was complete, and sends nothing more if the data is still missing (the 10:00 sync's failure alert already covers that). `travel-mode.sh` retimes every cron job, so the new one needs no workspace change (G13 resolved).
- **P5-D6 The engine may push on stale data while the update says "not synced".** With `biometrics_max_lag_days` = 2, the 11:00 evaluation classifies on yesterday's row if today's is missing. Proposal: when not synced at 11:00, `daily_update.py` **defers the evaluation to the 12:00 retry** (prints `SILENT`). If you prefer strict D17 ("engine untouched"), keep evaluating at 11:00 and only the update text changes. **Decision needed.**
- **P5-D7 Idempotency + measurement.** Migration `003_daily_updates`: one row per day (status complete / pending_sync, silent, message id, trigger event id, synced, entry and check-in present). A re-run never sends a second update. It feeds Phase 6.
- **P5-D8 No gateway restart** (no plugin change). Cron edits: the 11:00 message (backed up first) + the new 12:00 job.

### Proposed update message (silent)
```
📊 Last night: 9h10 sleep · HRV 50 ms (+12% vs 7-day) · RHR 52 bpm
This morning: Mood 7 · Creativity · entry ✓
```
Missing pieces get buttons: `No morning entry yet` → `[✍️ Write entry]`; `No check-in yet` → `[🙂 Check in]`.

### Mihajlo's answers (2026-10-08) → spec D53–D59
- P5-D4: one ping (the update is always silent). P5-D6: (a), postpone the engine to 12:00; still missing at 12:00 → no engine run that day, logged `not_synced`.
- Asked for a command cron instead of the agentTurn → verified clean on 2026.6.8 (D58).

### Steps
- [x] **P5.1** Migration 003 (live backup `stoic_journal.db.bak-mig003-20261008-002638`); `daily_update.py`; route-line exclusion for `agent:coach:stoiclife-*`; `record_coaching --send` already-sent guard; tests phase5 24/24, phase1 time-of-day fix, phase2 adjusted for the guard, all suites green
- [x] **P5.2** Crons: `80be6ec8` Coach Daily Update (11:00) + `522605b8` re-check (12:00), command jobs, exact, 420 s; `700b6841` disabled (backup `~/.openclaw/cron/bak-feat07-p5-safetynet-20261008-002646.json`); OPERATIONS.md cron table updated
- [x] **P5.3a** Agent CLI path verified live (2026-10-08 00:22): a `NO_REPLY` turn → suppressed; a one-line turn → sent once; own session. Real cron path verified with a one-shot (00:28): not-synced branch → one silent message (124) with ✍️/🙂, run `ok`/`not-delivered`. Test row removed.
- [x] **P5.4 (D60)** D54 extension: `trigger_matrix.evaluate` checks `daily_updates` for `not_synced`; if so, `classify_journal_only` (mood + keywords, no deltas/modulators, neutral, never fires) and the health line says "not synced". Mood/keyword block refactored into `mental_signal()` (engine dry run on real data identical before/after). Tests phase5 33/33 (entry after not_synced, late morning, normal 07:30 unaffected, control, no cross-day leak).
- [ ] **P5.3b (watch, in self-test)** First real 11:00 run (2026-10-08): silent update with last night's data; engine ran; check `daily_updates`, `stoic.log`, `cron_run_logs`. A flagged day (CLARIFY/SEND_FULL) is verified when it happens.
- [x] Phase summary (PROGRESS.md 2026-10-08); merged to main and pushed (Mihajlo: merge now, treat issues found in self-test as bugs)

## Phase 6: Self-test metrics 🔨 metrics live (2026-10-08); legacy removal waits on the self-test
- [x] `ux_metrics.py <from> <to> [--json]` (repo root; spec said `scripts/`, this repo keeps scripts at the root). Read-only (`mode=ro`). Reports: completion + skip per session, median prompt → entry, mood/module logging rate by source, feedback rate + 👍 share by kind / session / flagged vs unflagged (+ 👎 reasons), entries by input method (from `route_events`; older entries → "before routing"), daily-update outcomes. Tests `tests/test_feat07_phase6.py` 15/15.
- [ ] Self-test (two weeks from 2026-10-08): run `python3 ux_metrics.py 2026-10-08 <today>` and log bugs in `docs/PROGRESS.md`.
- [ ] Legacy prefix removal: only after a week with zero `legacy prefix` entries in the metrics (and zero `legacy_prefix` check-ins). Separate, reviewed change.

## Self-test fixes (Linear)
- [x] **MIN-127** duplicate "Go ahead" / narration (adc00fb); **MIN-128** outbound guard + coach streaming off (8373b5e); **MIN-132** CLARIFY Yes/No buttons + routed answer (aaa97a8, 0ca9771). Details in OPERATIONS.md.
- [x] **MIN-129** (2026-10-08): the prompt's check-in comes first, in place: [🙂 Check in] [Skip] → mood → module / No module → [✍️ Write entry] [Skip today] (`prompt_ui.py`, `sc:pc:<pid>:…`). A day with a mood already logged starts at Write entry. Skip today offers Check in only while no mood is logged. Tests `tests/test_prompt_checkin.py` 19/19. First real use: 07:30 Coach Morning, 2026-10-09.
- [x] **MIN-133** (2026-10-08): the evening review prompt opens on the module step (module or No module, no mood), then [✍️ Write entry] [Skip today]. The pick lands on the evening entry only (`merge_into_entry` freshness) and reaches the coaching as the `STOIC MODULE` block. Tests `tests/test_prompt_checkin.py` 26/26. First real use: 20:30 Coach Evening Review, 2026-10-09.
- [x] **MIN-136** (2026-10-09): evening mood check-in **declined**. Mood stays one check-in a day (D47/MIN-133); the evening mood is the coach's inference, already on every evening entry (101 of 105). Instead: `journal_entries.inferred_mood` keeps the coach's guess on every entry (also next to a manual mood), so `ux_metrics` section 7 can show you vs coach (backfill: 209 inferred + 5 manual from `stoic.log`; first read 5 pairs, mean |diff| 0.2). Evening prompt ends with "Add mood: N if you like." Tests `tests/test_inferred_mood.py` 17/17; DB backup `stoic_journal.db.bak-min136-20261009-214356`.
- [x] **MIN-137** (2026-10-09): morning/evening prompt section headings in bold (`1. **Anticipation:**`, `**The Wins:**`, `🧠 **The Mogi Brain Check**`, …). `channel_fmt.bold_headings` (CLI `channel_fmt.py headings telegram`) runs in `coach_morning.sh` / `coach_evening.sh` at send time, falling back to plain text on any error. The prompt files stay plain, because the WhatsApp rollback scripts read them too. Tests `test_channel_fmt.py` 30/30.
- [x] **MIN-130** (2026-10-08): check-in notes removed (the 📝 card buttons, `handle_note`, the `note:<mood|module>:<day>` pending kind, `checkins.set_note`). Nothing read them (not coaching, metrics, the coach or any cron) and none were ever saved. The "Tell me more" pending note is unchanged. `checkin_events.note` stays in the schema, unused (dropping it needs a non-idempotent migration). An old card's 📝 tap replies "Notes are gone: add it to your journal entry." Phase 3 tests 42/42 (the 4 earlier failures were clock-dependent note tests).
