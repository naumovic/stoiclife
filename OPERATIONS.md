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
