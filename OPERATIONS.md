# stoiclife — Operations

How the live system runs on the Beelink box. Code is in this repo; the
schedule + delivery live in OpenClaw (Gateway-backed cron store, not git), so
the recreate commands are recorded here.

## Pipeline

```
stoiclife_run.py  (deterministic brain: matrix → cooldown → confidence gate → quiet hours → dedup)
      │  prints  STOICLIFE_ACTION: SILENT | CLARIFY | SEND_FULL | HOLD_QUIET
      ▼
OpenClaw cron (agentTurn)  → Ewok reads the action and:
      • SILENT / HOLD_QUIET → replies HEARTBEAT_OK  (framework delivers nothing)
      • CLARIFY            → announces the one-line nudge
      • SEND_FULL          → generates coaching from the payload, validates+records
                             via record_coaching.py (sets message_sent=1), announces it
      ▼
announce → WhatsApp +61410772771
```

Generation happens **inside Ewok's agent turn** (correct model chain, no
script-level LLM call → no paid-fallback spillover). The script never sends.

## Live cron — "stoiclife Safety-Net (11:00)"

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
