# TOOLS.md — what the coach can touch

Only these tools exist for the coach: `exec`, `process`, `read`, `message`, `session_status`. Nothing else (no web, no file writing, no cron/gateway control). Use `exec` only for the commands documented in `AGENTS.md`. No other shell work, no file edits through the shell, no installs.

**Python:** always `python3` with **absolute** script paths. Your cwd is this workspace, not the scripts' directory.

**Data (read-only via sqlite3, except through the scripts):** `~/.openclaw/stoic/stoic_journal.db`
- `journal_entries`: id, date, session (morning|evening), raw_response, processed_themes, mood_score, mood_source
- `biometrics`: one row per date: hrv_rmssd_ms, deep_sleep_rmssd_ms, resting_hr_bpm, sleep_duration_min, minutes_awake, light_min, deep_min, rem_min, sleep_score, steps, spo2_avg/min/max
- `trigger_events` / `trigger_coaching`: stoiclife's detections and delivered pushes

Always query with `sqlite3 -readonly`. Never `INSERT`/`UPDATE`/`DELETE` by hand; writes go through the scripts.

**openclaw CLI (if ever needed):** `~/.npm-global/bin/openclaw`. Never bare `openclaw`, because `/usr/bin/openclaw` is a stale build.
