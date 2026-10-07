# FEAT-07 Telegram UX: progress checklist

The step-by-step tracker for FEAT-07. **If a session ends, start here.** The plan itself (plan v2 + review gaps G1–G20) is `docs/FEAT07-UX-TELEGRAM-SEED.md`. Current-system facts are in `docs/CURRENT-STATE.md`. Dated history goes in `docs/PROGRESS.md`. Tick boxes as steps land, and commit this file with the step.

## ▶ Resume here

- **Phase:** 2 (feedback buttons), **planned, not started**. The discrepancy fixes below (P2-D1..D11) were approved in the plan on 2026-10-07. Mihajlo asked to be told before any Phase 2 code starts.
- **Branch:** `feat07-phase2-feedback` (from `main` @ a2726ee). Don't push unless asked.
- **Last done:** Phase 1 merged to `main`; this tracker created.
- **Next:** get Mihajlo's go → P2.0 live checks (bold via CLI, `NO_REPLY` in a DM turn).

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

## Phase 2: Feedback buttons 📝 planned

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
- [ ] **P2.0** Live checks: bold via `tg.send`; DM `NO_REPLY` suppressed. Stop and decide if either fails. Clean up test rows.
- [ ] **P2.1** `send_coaching.py`: `--text-stdin`; r auto `data_flags_json`
- [ ] **P2.2** `record_coaching.py --send`
- [ ] **P2.3** `sc_dispatch.py`: `fb` up/down, `fbr` reasons, `more` → pending `fb_more:<k><id>` (2h), `noop`; `t` → `record_reaction.py --coaching-id`
- [ ] **P2.4** `save_feedback_note.py`
- [ ] **P2.5** `record_feedback.py` (typed legacy)
- [ ] **P2.6** `coach-workspace/AGENTS.md` §1 step 0 + step 6, §2; size check
- [ ] **P2.7** Cron `700b6841` message → `record_coaching … --send`, then `NO_REPLY` (job backed up)
- [ ] **P2.8** `tests/test_feat07_phase2.py`; existing suites green
- [ ] **P2.9** Live acceptance with Mihajlo (👍, 👎 → reason, Tell me more → note, `t` usefulness, no double send)
- [ ] Phase summary for review (incl. any workspace files touched); merge on approval

## Phase 3: Mood/module buttons + commands
- [ ] Planned and checked against code (incl. G18 3-per-row layout, plain-text edit issue as in P2-D5)
- [ ] Built, tested, live-accepted, merged

## Phase 4: Morning/evening without prefixes
- [ ] Planned and checked against code (`route_entry.py`, reply-to availability, D5 `NO_REPLY` for command crons G11)
- [ ] Built, tested, live-accepted, merged

## Phase 5: 11am update
- [ ] Current 11:00 + FEAT-05 behaviour documented; smallest change proposed (D17)
- [ ] Built (12:00 retry cron in travel-mode tz list, G13), tested, live-accepted, merged

## Phase 6: Self-test metrics
- [ ] `ux_metrics.py` against the live DB
- [ ] Legacy prefix removal (separate change, after a week of zero use)
