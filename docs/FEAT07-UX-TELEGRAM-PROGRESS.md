# FEAT-07 Telegram UX: progress checklist

The step-by-step tracker for FEAT-07. **If a session ends, start here.** The plan itself (plan v2 + review gaps G1–G20) is `docs/FEAT07-UX-TELEGRAM-SEED.md`. Current-system facts are in `docs/CURRENT-STATE.md`. Dated history goes in `docs/PROGRESS.md`. Tick boxes as steps land, and commit this file with the step.

## ▶ Resume here

- **Phase:** 3 (mood/module buttons + commands), **in progress**: P3.1–P3.5 done; P3.6 restart done; next P3.7 live test.
- **Branch:** `feat07-phase3-checkins` (from `main` @ 985a066). Don't push unless asked.
- **Last done:** Phase 2 merged; Phase 3 planned + checked against the code.
- **Watch:** first real entries on 2026-10-08 should arrive once each, with 👍/👎. Treat anything odd as a Phase 2 bug.
- **Note:** the coach workspace *is* this repo dir, so the checked-out branch's `coach-workspace/AGENTS.md` is what's live.

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

## Phase 3: Mood/module buttons + commands 🔨 in progress (OK'd 2026-10-07)

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
- [ ] **P3.7** Live acceptance: `/mood` → 2×5 card; mood + module taps re-render; note via "Add a note"; an old card → expired; no agent turn on taps or commands; test rows cleaned
- [ ] Phase summary; merge on approval

## Phase 4: Morning/evening without prefixes
- [ ] Planned and checked against code (`route_entry.py`, reply-to availability, D5 `NO_REPLY` for command crons G11)
- [ ] Built, tested, live-accepted, merged

## Phase 5: 11am update
- [ ] Current 11:00 + FEAT-05 behaviour documented; smallest change proposed (D17)
- [ ] Built (12:00 retry cron in travel-mode tz list, G13), tested, live-accepted, merged

## Phase 6: Self-test metrics
- [ ] `ux_metrics.py` against the live DB
- [ ] Legacy prefix removal (separate change, after a week of zero use)
