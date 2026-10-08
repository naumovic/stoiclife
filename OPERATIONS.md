# stoiclife — Operations

How the live system runs on the Beelink box. Code is in this repo; the
schedule + delivery live in OpenClaw (Gateway-backed cron store, not git), so
the recreate commands are recorded here.

## Pipeline

```
stoiclife_run.py  (deterministic brain: matrix → cooldown → confidence gate → quiet hours → dedup)
      │  prints  STOICLIFE_ACTION: SILENT | CLARIFY | SEND_FULL | HOLD_QUIET
      ▼
OpenClaw cron (agentTurn)  → the coach agent (was Ewok) reads the action and:
      • SILENT / HOLD_QUIET → replies HEARTBEAT_OK  (framework delivers nothing)
      • CLARIFY            → announces the one-line nudge
      • SEND_FULL          → generates coaching from the payload, validates+records
                             via record_coaching.py (sets message_sent=1), announces it
      ▼
announce → Telegram, coach bot (account `coach`) → 8917837483   (WhatsApp until 2026-10-06)
```

Generation happens **inside Ewok's agent turn** (correct model chain, no
script-level LLM call → no paid-fallback spillover). The script never sends.

## Coaching channel (since 2026-10-06: Telegram coach bot)

All Stoic coaching goes through **@stoiclife_coach_bot** (OpenClaw telegram account `coach`, bound to agent `coach`, workspace `coach-workspace/`). Ewok on WhatsApp keeps calendar/system/tasks and points journal entries at the coach bot. Migration log: `docs/PROGRESS.md`.

**Knob:** `~/.openclaw/stoic/coaching-channel` (`whatsapp` | `telegram`, missing = `whatsapp`), read by `workspace/scripts/coaching-channel.sh`. On `telegram`, `morning-brief.sh` drops Health Snapshot + morning prep + `set_prompt_state`, and `weekly-digest.sh` drops the weekly review.

**Live coach crons** (all agent `coach`, announce telegram account `coach` → `8917837483`, tz from the travel-mode knob):

| Job | id | Payload |
|---|---|---|
| Coach Morning (07:30) | `73c880ac` | command `~/projects/stoiclife/coach_morning.sh` (sets morning prompt state) |
| Coach Evening Review (20:30) | `7e8a7edd` | command `~/projects/stoiclife/coach_evening.sh` (FEAT-07 D50; sets evening prompt state, sends with buttons via `send_prompt.py`; was `workspace/scripts/evening-prompt.sh`, backup `~/.openclaw/cron/bak-feat07-p4-evening-20261007-235652.json`) |
| Coach Weekly Review (Sun 08:00) | `5dcb0e1a` | command `cd ~/projects/stoiclife && out=$(python3 weekly_review.py --section both --channel telegram) \|\| exit 1; echo "${out:-NO_REPLY}"` |
| Coach Daily Update (11:00) | `80be6ec8` | command `cd ~/projects/stoiclife && python3 daily_update.py` (FEAT-07 D53–D58: silent update; engine only when synced; CLARIFY sent directly; SEND_FULL → `openclaw agent` coach turn in session `agent:coach:stoiclife-11am-<date>`; timeout 420 s) |
| Coach Daily Update re-check (12:00) | `522605b8` | command `… python3 daily_update.py --retry` (only acts if 11:00 logged `pending_sync`; still not synced → no engine run that day, logged `not_synced`) |
| ~~Coach Safety-Net (11:00)~~ | `700b6841` | **disabled 2026-10-08** (replaced by the two jobs above; backup `~/.openclaw/cron/bak-feat07-p5-safetynet-20261008-002646.json`). Rollback: `openclaw cron edit 700b6841 --enable` + `--disable` the two Daily Update jobs. |

Command payloads deliver stdout verbatim (no model turn); `NO_REPLY` stays silent. Test a command job without touching prompt state: a one-shot copy with `--at +1m --delete-after-run --command-env STOICLIFE_SKIP_PROMPT_STATE=1`. `cron list` hides disabled jobs; check `cron_jobs` in `~/.openclaw/state/openclaw.sqlite`.

Fitbit 07:00 / 10:00 failure alerts go to **both** WhatsApp and the coach bot (`accountId: "coach"` is required, or Telegram uses the Travelboard bot).

**Known limits:** Telegram *tap* reactions don't reach the coach (rate by typing 👍/👎). Command-cron prompts aren't mirrored into the coach's session (`state.json` + prefixes carry attribution; the coach asks before saving an unprefixed reply).

### FEAT-07 coach UI plugin (`stoic-coach-ui`, since 2026-10-07)

`plugin/stoic-coach-ui/` (linked install, `plugins.load.paths`) claims Telegram callbacks starting `sc:` and the `/mood /module /journal /skip` commands on the coach account, and pipes each one to `sc_dispatch.py`. All logic is in Python, so editing `sc_dispatch.py`, `checkins.py` or `tg.py` needs **no** restart; editing `index.js` or the manifest does. Logs: `~/.openclaw/stoic/stoic.log` (`tg:` / `sc_dispatch:` lines) and `journalctl --user -u openclaw-gateway | grep stoic-coach-ui`. Schema: `python3 migrate.py --status` (`migrations/NNN_*.sql`; the runner backs up the DB first). Working file: `docs/FEAT07-UX-TELEGRAM-SEED.md`.

**Outbound guard (MIN-127/MIN-128, 2026-10-08):** OpenClaw delivers every text block of a coach turn and drops only an exact `NO_REPLY`. So the plugin's `reply_payload_sending` hook asks `sc_dispatch.handle_outbound` about each coach text. It strips stray `NO_REPLY` tokens and cancels wordless payloads (a lone 🧭). It also cancels any further text once `send_coaching.py`/`record_coaching.py` sent the reply in that run, except the CLARIFY 🧭 line or after a later failed step. It fails open. Log: `sc_dispatch: outbound …` lines. The coach account also has `streaming: {mode: "off"}` (no live preview), so pre-tool text can't flash up mid-turn. Config backup from before that change: `~/.openclaw/openclaw.json.pre-min127-20261008-211040`.

**Self-test metrics:** `python3 ux_metrics.py 2026-10-08 $(date +%F)` (read-only; `--json` for raw numbers).

**Rollback (one command; config snapshot taken before the install):**
`cp ~/.openclaw/openclaw.json.pre-feat07-20261007-222449 ~/.openclaw/openclaw.json && systemctl --user restart openclaw-gateway && sleep 20 && systemctl --user is-active openclaw-gateway`
Then check the journal shows WhatsApp + both Telegram providers starting. This removes the plugin from `plugins.allow`/`load.paths` and the coach's `inlineButtons: dm`. The new tables are additive and harmless to leave in place; the DB backup is `stoic_journal.db.bak-mig001-20261007-222424`.

### Rollback to WhatsApp

1. `echo whatsapp > ~/.openclaw/stoic/coaching-channel`
2. `openclaw cron edit <id> --disable` for the four coach jobs above.
3. `openclaw cron edit <id> --enable` for `12a4a4e5` (Stoic Evening Review) and `74b9acbe` (stoiclife Safety-Net).
4. Restore Ewok's Stoic sections in `workspace/TOOLS.md` + `AGENTS.md` from `docs/ewok-stoic-sections-archived.md`. Check the 20,000-char bootstrap limit, then the gateway log.
5. Optional: drop the Telegram copy from the Fitbit alerts (`~/.openclaw/cron/bak-coach-fitbit-20261006-005659.json` has the old messages). Full pre-cutover job backup: `~/.openclaw/cron/bak-coach-cutover-20261006-011509.json`.

`~/.openclaw/stoic/stoic_knowledge.md` → `coach-workspace/stoic_knowledge.md` (was `workspace/stoic/stoic_knowledge.md`, identical content); either works for rollback.

## WhatsApp cron — "stoiclife Safety-Net (11:00)" (DISABLED since 2026-10-06, kept for rollback)

- Schedule: `0 11 * * *` Australia/Brisbane (after the 10:00 Fitbit catch-up).
- `agentTurn` + `announce` → whatsapp `+61410772771`, session `isolated`, 300s timeout.
- Job id (this box): `74b9acbe-8b0b-4729-ab63-baf7efe72375`.

Manage:
```
openclaw cron list
openclaw cron show  --id <id>      # or: openclaw cron get --id <id>
openclaw cron run   <id>           # debug run now (async; silent today = HEARTBEAT_OK)
openclaw cron runs  --id <id>      # run history
openclaw cron disable <id>         # pause
openclaw cron rm    <id>           # remove
```

Recreate (the agentTurn prompt is the integration glue — keep in sync with the
orchestrator's STOICLIFE_ACTION contract):
```
openclaw cron add \
  --name "stoiclife Safety-Net (11:00)" \
  --cron "0 11 * * *" --tz "Australia/Brisbane" \
  --agent main --session isolated --wake now --timeout-seconds 300 \
  --announce --channel whatsapp --to "+61410772771" \
  --message "<see agentTurn prompt below>"
```

### agentTurn prompt
```
stoiclife safety-net check. Run this and act on the result, nothing else.

1. Execute: python3 ~/projects/stoiclife/stoiclife_run.py --session safety-net
2. Read the first line "STOICLIFE_ACTION: <X>" and the "# ... event_id=N" comment line.
3. Act:
   - SILENT or HOLD_QUIET: reply with exactly HEARTBEAT_OK and nothing else.
   - CLARIFY: reply with exactly the line starting with the compass emoji that the script printed, nothing else.
   - SEND_FULL: the script prints a "=== SYSTEM PROMPT ===" payload. Follow it to compose the
     coaching message in the required strict format (compass header, *Observation:*, *Correlation:*,
     then exactly two numbered actions). Validate and record it by running:
       printf '%s' "YOUR_MESSAGE" | python3 ~/projects/stoiclife/record_coaching.py --event-id N
     using the event_id from step 2. If it exits non-zero, fix the format per its errors and retry
     once. Once it exits 0, reply with EXACTLY the coaching message and nothing else.

Never invent data. No preamble, sign-off, or commentary. If anything errors, reply HEARTBEAT_OK.
```

## Derived sleep score (FEAT-01-Issue-01)

`biometrics.sleep_score` is **derived by stoiclife**, not synced — fitbit-sync
stores the raw stage data (`sleep_duration_min`, `deep/light/rem_min`,
`minutes_awake`) and leaves `sleep_score` NULL. The score is an opinionated index
(weights/targets in `stoiclife_config.json`, tuned to Mihajlo), so its
computation stays here; only its *trigger* lives in the sync pipeline.

The derive runs as the last step of **both** Fitbit sync crons, right after the
raw rows land:

```
python3 ~/projects/stoiclife/sleep_score.py --recent 4
```

- `--recent N` recomputes each of the last N nights' **own** per-night score
  (no aggregation — each date stores its single-night value). The 7-day rolling
  average the matrix modulator uses is computed at read time, not stored.
- The window is 4 days to match the catch-up's 4-day reconciliation window, so a
  night whose stage data the COALESCE upsert backfilled late gets re-scored.
  Idempotent (overwrites), so running it at both 07:00 and 10:00 is safe.
- **10:00 is load-bearing** (must populate today's score before the 11:00
  safety-net reads it; retry + WhatsApp alert on failure). **07:00 is
  best-effort** (heals early, stays quiet on failure — 10:00 backstops it).

No coupling: fitbit-sync knows nothing about stoiclife; the cron command string
is the integration glue. Retune → re-backfill all history with `sleep_score.py
--all`.

## Fitbit token re-consent (`invalid_grant`)

The whole pipeline reads `biometrics`, which the **fitbit-sync** project fills via
the Google Health API. When its OAuth token dies, every sync fails and the matrix
falls back to stale/yesterday data (or `insufficient_data`), and today's
`sleep_score` can't be derived. The canonical procedure lives in
`~/projects/fitbit-sync/RUNBOOK.md` §"Re-consent OAuth"; the operator steps are
duplicated here because stoiclife depends on it.

**Symptom (seen 2026-06-18):** both Fitbit sync crons WhatsApp a failure alert and
`~/projects/fitbit-sync/sync.log` shows:
```
ERROR sync: sync failed for <date>: ('invalid_grant: Token has been expired or revoked.', ...)
```
With the cron hardening (below), the sleep-score step no longer fires its own alert
in this case — a missing today-row is attributed to the sync, not to sleep_score.

**Root cause:** the OAuth client expires refresh tokens ~7 days after consent while
in *Testing* status. **Published to Production 2026-06-18** to stop the weekly
expiry; if `invalid_grant` still recurs, just re-consent:

```bash
# 1. Generate the consent URL (writes a one-shot PKCE state file)
~/projects/fitbit-sync/.venv/bin/python ~/projects/fitbit-sync/auth.py login-url
# 2. Open the printed URL in ANY browser, approve all three scopes.
#    The final redirect to localhost:8400 fails to load — EXPECTED. Copy that
#    failing URL (it contains ?code=...) from the address bar.
# 3. Exchange it for a fresh token:
~/projects/fitbit-sync/.venv/bin/python ~/projects/fitbit-sync/auth.py login-code --response-url '<pasted URL>'
# 4. Verify (all 3 data types should be HTTP 200):
~/projects/fitbit-sync/.venv/bin/python ~/projects/fitbit-sync/auth.py smoke
```

**Then heal the data** the outage skipped (so the matrix + sleep_score catch up):
```bash
~/projects/fitbit-sync/.venv/bin/python ~/projects/fitbit-sync/sync.py --backfill <first-missed> <today>
python3 ~/projects/stoiclife/sleep_score.py --recent 4
```
Confirm today's row + score landed:
```bash
sqlite3 ~/.openclaw/stoic/stoic_journal.db \
  "SELECT date, hrv_rmssd_ms, sleep_duration_min, sleep_score FROM biometrics ORDER BY date DESC LIMIT 4;"
```

**Cron hardening (10:00 catch-up, id `697feda9…`):** the sleep-score step is now
judged purely by `sleep_score.py`'s own exit code — exit 0 is success even if it
wrote fewer than 4 scores or today's score is absent (a missing today-row is the
sync's failure, already alerted). It only alerts if the command itself exits
non-zero. The sync-failure alert now names `invalid_grant` explicitly so the cause
is obvious. The cron message is Gateway-stored, not git — edit with
`openclaw cron edit 697feda9-050e-46f9-8ae6-31acc9fb4aec --message "<text>"`.

## Manual / test invocations

```
# read-only simulation (writes nothing):
python3 stoiclife_run.py --date 2026-06-09 --session evening --dry-run
# testing a real send outside business hours:
python3 stoiclife_run.py --date 2026-06-09 --session evening --ignore-quiet-hours
```

## Quiet hours

21:00–07:00 AEST (config `quiet_hours`). Sendable states in that window become
`HOLD_QUIET` and are released the next morning. `--ignore-quiet-hours` overrides
for testing only.

## Event-driven evaluation (after morning/evening entries)

TODO (Decision A+C): in addition to the 11:00 safety-net, evaluate right after a
journal entry is saved AND mood is inferred. See INSTRUCTIONS.md Phase 4.
