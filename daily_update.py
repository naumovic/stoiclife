#!/usr/bin/env python3
"""FEAT-07 Phase 5: the daily 11:00 update (spec D53–D58), run by a command cron.

  11:00  python3 daily_update.py           12:00  python3 daily_update.py --retry

1. Sync check (D54): today's biometrics row must have last night's sleep and a sleep score.
   - Not synced at 11:00 → one silent line + morning status; the engine is NOT run;
     the day is `pending_sync` and the 12:00 retry takes over.
   - Still not synced at 12:00 → no message, no engine run (no push off stale data);
     the day is `not_synced` (the Fitbit sync alert covers it).
2. Synced → run the engine (`stoiclife_run.py --session safety-net --channel telegram`),
   then send the compact update, always silent (D53):
       📊 Last night: 9h10 sleep · HRV 50 ms (+12% vs 7-day) · RHR 52 bpm
       This morning: Mood 7 · Creativity · entry ✓
   with [✍️ Write entry] if there's no morning entry and [🙂 Check in] if no mood (D55, D56).
3. Escalation: CLARIFY → the engine's 🧭 line is sent as is (audible). SEND_FULL → a coach
   turn via `openclaw agent` in its own session (D58); the coach composes, and
   `record_coaching.py --send` validates, records and sends. SILENT / HOLD_QUIET → nothing.

stdout is what the command cron delivers: always `NO_REPLY` (everything is sent here).
Idempotent per day via `daily_updates` (D57). `--dry-run` prints what it would do.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime

import checkins
import clarify as clarify_q
import prompts
import tg
from trigger_matrix import fetch_baseline_rows, load_config, pct_delta, rolling_avg

REPO_DIR = checkins.REPO_DIR
OPENCLAW = tg.OPENCLAW
AGENT_TIMEOUT_S = 300
ESCALATION_PROMPT = """stoiclife 11:00 escalation (scheduled; not a message from Mihajlo). The engine output is below; its first line is STOICLIFE_ACTION: SEND_FULL.

Follow its "=== SYSTEM PROMPT ===" payload to compose the coaching message in the required strict format (compass header, Observation, Correlation, then exactly two numbered actions), using exactly the bold markup the payload shows. Validate, record and send it by running the record_coaching.py command the engine printed (it ends in --send), with your message piped in via printf '%s'. If it exits 2, fix the format per its errors and retry once. If it exits 0, it has sent the message (or it was already sent): reply with exactly NO_REPLY. If it exits 3 (stored but sending failed), reply with EXACTLY the coaching message and nothing else.

Never invent data. No preamble, sign-off or commentary.

--- engine output ---
"""


def now_local() -> datetime:
    return checkins.now_local()


def today_row(conn, day: str):
    return conn.execute("SELECT * FROM biometrics WHERE date = ?", (day,)).fetchone()


def is_synced(row) -> bool:
    return bool(row) and row["sleep_duration_min"] is not None and row["sleep_score"] is not None


def data_line(conn, cfg: dict, row) -> str:
    base = fetch_baseline_rows(conn, row["date"], cfg["rolling_window_days"])
    parts = []
    if row["sleep_duration_min"] is not None:
        m = int(row["sleep_duration_min"])
        parts.append(f"{m // 60}h{m % 60:02d} sleep")
    if row["hrv_rmssd_ms"] is not None:
        d = pct_delta(row["hrv_rmssd_ms"], rolling_avg(base, "hrv_rmssd_ms"))
        parts.append(f"HRV {round(row['hrv_rmssd_ms'])} ms" + (f" ({d:+.0f}% vs 7-day)" if d is not None else ""))
    if row["resting_hr_bpm"] is not None:
        parts.append(f"RHR {row['resting_hr_bpm']} bpm")
    return "📊 Last night: " + " · ".join(parts)


def morning_status(conn, chat_id: str, day: str) -> tuple[str, bool, bool]:
    entry = conn.execute("SELECT mood_score, module FROM journal_entries WHERE date = ? AND session = "
                         "'morning' ORDER BY id DESC LIMIT 1", (day,)).fetchone()
    state = checkins.today_state(conn, chat_id, day)
    mood = (state.get("mood") or {}).get("value") or (entry["mood_score"] if entry and entry["mood_score"] else None)
    module = (state.get("module") or {}).get("value") or (entry["module"] if entry else None)
    bits = []
    bits.append(f"Mood {mood}" if mood else "No check-in yet")
    if module:
        bits.append(str(module).capitalize())
    bits.append("entry ✓" if entry else "No morning entry yet")
    return "This morning: " + " · ".join(bits), bool(entry), bool(mood)


def buttons(conn, chat_id: str, day: str, has_entry: bool, has_mood: bool) -> list:
    row = []
    if not has_entry:
        p = conn.execute("SELECT id FROM prompt_events WHERE chat_id = ? AND local_date = ? AND session = "
                         "'morning' ORDER BY id DESC LIMIT 1", (chat_id, day)).fetchone()
        row.append(("✍️ Write entry", f"sc:write:morning{':' + str(p['id']) if p else ''}"))
    if not has_mood:
        row.append(("🙂 Check in", f"sc:card:{day.replace('-', '')}"))
    return [row] if row else []


def get_update(conn, chat_id: str, day: str):
    return conn.execute("SELECT * FROM daily_updates WHERE chat_id = ? AND local_date = ?",
                        (chat_id, day)).fetchone()


def save_update(conn, chat_id: str, day: str, **f) -> None:
    ts = now_local().isoformat()
    cols = ", ".join(f)
    with conn:
        conn.execute(
            f"INSERT INTO daily_updates (chat_id, local_date, created_at, updated_at, {cols}) "
            f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in f)}) "
            f"ON CONFLICT(chat_id, local_date) DO UPDATE SET updated_at = excluded.updated_at, "
            + ", ".join(f"{k} = excluded.{k}" for k in f),
            (chat_id, day, ts, ts, *f.values()))


def run_engine() -> str:
    proc = subprocess.run([sys.executable, str(REPO_DIR / "stoiclife_run.py"), "--session", "safety-net",
                           "--channel", "telegram"], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"stoiclife_run exit {proc.returncode}: {proc.stderr.strip()[-300:]}")
    return proc.stdout


def parse_engine(out: str) -> tuple[str, int | None, str | None]:
    m = re.search(r"^STOICLIFE_ACTION:\s*(\w+)", out, re.M)
    action = m.group(1) if m else "UNKNOWN"
    e = re.search(r"event_id=(\d+)", out)
    clarify = next((l for l in out.splitlines() if l.startswith("🧭")), None)
    return action, int(e.group(1)) if e else None, clarify


def escalate_send_full(engine_out: str, day: str, chat_id: str) -> bool:
    """D58: one coach turn in its own session; the coach composes and record_coaching --send sends."""
    cmd = [OPENCLAW, "agent", "--agent", "coach", "--session-key", f"agent:coach:stoiclife-11am-{day}",
           "--message", ESCALATION_PROMPT + engine_out, "--deliver", "--reply-channel", "telegram",
           "--reply-account", checkins.coach_config()["account"], "--reply-to", chat_id,
           "--json", "--timeout", str(AGENT_TIMEOUT_S)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=AGENT_TIMEOUT_S + 60)
    try:
        res = tg._parse_json_stdout(proc.stdout)
    except Exception:
        res = {}
    ok = proc.returncode == 0 and res.get("status") == "ok"
    tg.log("INFO" if ok else "ERROR",
           f"daily_update: SEND_FULL coach turn status={res.get('status')} "
           f"delivery={(res.get('deliveryStatus') or {}).get('status')} rc={proc.returncode}")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--retry", action="store_true", help="the 12:00 re-check (D54)")
    ap.add_argument("--dry-run", action="store_true", help="print what would happen; send/write nothing")
    ap.add_argument("--db", help="DB path (tests); default the live journal DB")
    args = ap.parse_args(argv)

    cfg = load_config(REPO_DIR / "stoiclife_config.json")
    chat_id = checkins.coach_config()["chat_id"]
    now = now_local()
    day = now.strftime("%Y-%m-%d")
    conn = tg.db_connect(args.db)
    conn.row_factory = __import__("sqlite3").Row
    existing = get_update(conn, chat_id, day)

    if args.retry:
        if not existing or existing["status"] != "pending_sync":
            print("NO_REPLY")  # nothing to re-check today
            return 0
    elif existing:
        tg.log("INFO", f"daily_update: {day} already {existing['status']}; not sending again")
        print("NO_REPLY")
        return 0

    row = today_row(conn, day)
    synced = is_synced(row)
    status_line, has_entry, has_mood = morning_status(conn, chat_id, day)
    btns = buttons(conn, chat_id, day, has_entry, has_mood)

    if not synced:
        if args.retry:  # D54: still missing → no engine run, no push off stale data today
            if not args.dry_run:
                save_update(conn, chat_id, day, status="not_synced", synced=0, escalation="none",
                            entry_present=int(has_entry), checkin_present=int(has_mood))
            tg.log("WARNING", f"daily_update: {day} still not synced at the 12:00 re-check; no engine run today")
            print("NO_REPLY")
            return 0
        text = "📊 Last night's data hasn't synced yet. I'll check again at 12:00.\n" + status_line
        if args.dry_run:
            print(f"[dry-run] would send (silent):\n{text}\nbuttons={btns}\n[dry-run] engine postponed to 12:00")
            return 0
        mid = tg.send(text, btns or None, silent=True, chat_id=chat_id)
        save_update(conn, chat_id, day, status="pending_sync", synced=0, message_id=mid, escalation="none",
                    entry_present=int(has_entry), checkin_present=int(has_mood))
        print("NO_REPLY")
        return 0

    text = data_line(conn, cfg, row) + "\n" + status_line
    if args.dry_run:
        print(f"[dry-run] would run the engine, then send (silent):\n{text}\nbuttons={btns}")
        return 0

    try:
        engine_out = run_engine()
    except Exception as exc:
        tg.log("ERROR", f"daily_update: engine failed: {exc}")
        engine_out = "STOICLIFE_ACTION: ERROR"
    action, event_id, clarify = parse_engine(engine_out)

    mid = tg.send(text, btns or None, silent=True, chat_id=chat_id)
    escalation = "none"
    if action == "CLARIFY" and clarify:
        # audible: the one notification (D53); MIN-132: with Yes/No buttons, so the answer routes
        try:
            if event_id is None:
                raise ValueError("no event_id in the engine output")
            clarify_q.send(conn, event_id, chat_id=chat_id)
        except Exception as exc:
            tg.log("ERROR", f"daily_update: clarify send failed ({exc}); sending the plain line")
            tg.send(clarify, chat_id=chat_id)
        escalation = "clarify"
    elif action == "SEND_FULL":
        escalation = "send_full" if escalate_send_full(engine_out, day, chat_id) else "send_full_failed"
    save_update(conn, chat_id, day, status="complete", synced=1, action=action, event_id=event_id,
                message_id=mid, escalation=escalation, entry_present=int(has_entry),
                checkin_present=int(has_mood))
    tg.log("INFO", f"daily_update: {day} sent (silent) action={action} escalation={escalation}"
                   f"{' (retry)' if args.retry else ''}")
    print("NO_REPLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
