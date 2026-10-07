#!/usr/bin/env python3
"""FEAT-07 Phase 5 — daily_update.py (D53–D58): sync check + postpone, silent update,
CLARIFY / SEND_FULL escalation, 12:00 retry, idempotency, buttons; route-line exclusion
for script sessions; record_coaching --send already-sent guard. Scratch DB, fake sender,
engine and coach turn stubbed: nothing live is touched.
Run: python3 tests/test_feat07_phase5.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = Path.home() / ".openclaw" / "workspace" / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(SCRIPTS))

import checkins  # noqa: E402
import daily_update as du  # noqa: E402
import sc_dispatch  # noqa: E402
import tg  # noqa: E402
from _tz import TZ  # noqa: E402

failures = 0
total = 0


def check(label, ok, detail=""):
    global failures, total
    total += 1
    if not ok:
        failures += 1
        print(f"FAIL  {label}  {detail}")
    else:
        print(f"ok    {label}")


TMP = Path(tempfile.mkdtemp(prefix="feat07p5-"))
tg.LOG_PATH = TMP / "stoic.log"
tg.STATE_PATH = TMP / "state.json"
FAKE = TMP / "sent.jsonl"
os.environ[tg.FAKE_ENV] = str(FAKE)
CHAT = "8917837483"
schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))
DB = TMP / "p5.db"
with sqlite3.connect(DB) as c:
    c.executescript(schema)
r = subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(DB), "--no-backup"], capture_output=True, text=True)
check("migration 003 applies", "003_daily_updates.sql" in r.stdout, r.stdout + r.stderr)
conn = sqlite3.connect(DB)
with conn:  # 7-day baseline + "today" without sleep yet
    for d, hrv in (("01", 40), ("02", 42), ("03", 44), ("04", 46), ("05", 40), ("06", 42), ("07", 46)):
        conn.execute("INSERT INTO biometrics (date, hrv_rmssd_ms, resting_hr_bpm, sleep_duration_min, sleep_score) "
                     "VALUES (?, ?, 55, 420, 80)", (f"2026-10-{d}", hrv))
    conn.execute("INSERT INTO biometrics (date, steps) VALUES ('2026-10-08', 900)")

CLOCK = {"now": datetime(2026, 10, 8, 11, 0, tzinfo=TZ)}
du.now_local = lambda: CLOCK["now"]
ENGINE = {"out": "STOICLIFE_ACTION: SILENT\n# date=2026-10-08 session=safety-net state=neutral confidence=0 event_id=77 dry_run=False\n", "calls": 0}


def fake_engine():
    ENGINE["calls"] += 1
    return ENGINE["out"]


du.run_engine = fake_engine
ORIG_ESCALATE = du.escalate_send_full
ESC = {"calls": [], "ok": True}
du.escalate_send_full = lambda out, day, chat: (ESC["calls"].append((day, chat)) or ESC["ok"])


def sends():
    return [json.loads(l)["args"] for l in FAKE.read_text().splitlines()] if FAKE.exists() else []


def run(*a):
    n = len(sends())
    rc = du.main(["--db", str(DB), *a])
    return rc, sends()[n:]


def upd():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c.execute("SELECT * FROM daily_updates WHERE local_date = '2026-10-08'").fetchone()


def msg(a):
    return a[a.index("--message") + 1]


# --- 11:00, not synced (D54) ---------------------------------------------------------------
rc, s = run()
u = upd()
check("not synced: one silent message, engine NOT run", len(s) == 1 and "--silent" in s[0] and ENGINE["calls"] == 0, s)
check("…saying it'll check at 12:00 + morning status", "hasn't synced yet" in msg(s[0])
      and "No morning entry yet" in msg(s[0]) and "No check-in yet" in msg(s[0]), msg(s[0]))
vals = [b["value"] for blk in json.loads(s[0][s[0].index("--presentation") + 1])["blocks"] for b in blk["buttons"]]
check("buttons: ✍️ Write entry + 🙂 Check in (D55, D56)", vals == ["sc:write:morning", "sc:card:20261008"], vals)
check("day logged pending_sync", u["status"] == "pending_sync" and u["synced"] == 0)
rc, s = run()
check("11:00 re-run sends nothing (idempotent)", s == [] and ENGINE["calls"] == 0)

# --- 12:00 retry, still not synced ------------------------------------------------------------
CLOCK["now"] = datetime(2026, 10, 8, 12, 0, tzinfo=TZ)
rc, s = run("--retry")
check("12:00 still not synced: no message, no engine (no stale push)", s == [] and ENGINE["calls"] == 0)
check("day logged not_synced", upd()["status"] == "not_synced")
rc, s = run("--retry")
check("a second retry does nothing", s == [] and ENGINE["calls"] == 0)

# --- retry path when the data lands by 12:00 ---------------------------------------------------
with conn:
    conn.execute("UPDATE daily_updates SET status = 'pending_sync' WHERE local_date = '2026-10-08'")
    conn.execute("UPDATE biometrics SET sleep_duration_min = 550, sleep_score = 93, hrv_rmssd_ms = 49.7, "
                 "resting_hr_bpm = 52 WHERE date = '2026-10-08'")
rc, s = run("--retry")
check("12:00 synced: engine runs once, one silent update", ENGINE["calls"] == 1 and len(s) == 1 and "--silent" in s[0], s)
check("data line: last night + HRV vs 7-day + RHR", msg(s[0]).startswith(
      "📊 Last night: 9h10 sleep · HRV 50 ms (+16% vs 7-day) · RHR 52 bpm"), msg(s[0]))
u = upd()
check("day complete with action + event id", u["status"] == "complete" and u["synced"] == 1
      and u["action"] == "SILENT" and u["event_id"] == 77 and u["escalation"] == "none", dict(u))


def reset_day():
    with conn:
        conn.execute("DELETE FROM daily_updates")
    ENGINE["calls"] = 0


# --- 11:00 synced, with entry + check-in, SILENT -------------------------------------------------
reset_day()
CLOCK["now"] = datetime(2026, 10, 8, 11, 0, tzinfo=TZ)
with conn:
    conn.execute("INSERT INTO journal_entries (date, session, raw_response, mood_score, module, created_at) "
                 "VALUES ('2026-10-08', 'morning', 'x', 7, 'creativity', '2026-10-08T08:00:00+10:00')")
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=7, source="button",
                    now=datetime(2026, 10, 8, 7, 45, tzinfo=TZ))
rc, s = run()
check("morning line: Mood 7 · Creativity · entry ✓", msg(s[0]).endswith("This morning: Mood 7 · Creativity · entry ✓"), msg(s[0]))
check("nothing missing -> no buttons", "--presentation" not in s[0])
check("SILENT -> just the silent update", len(s) == 1)

# --- CLARIFY ----------------------------------------------------------------------------------------
reset_day()
ENGINE["out"] = ("STOICLIFE_ACTION: CLARIFY\n# date=2026-10-08 session=safety-net state=running_on_fumes "
                 "confidence=55 event_id=78 dry_run=False\n# confidence 55\n\n# AGENT: send the line below\n\n"
                 "🧭 stoiclife: I'm seeing a possible **Running on Fumes** pattern today. Want the full read?\n")
rc, s = run()
check("CLARIFY: silent update, then the 🧭 line audible (one ping, D53)", len(s) == 2 and "--silent" in s[0]
      and "--silent" not in s[1] and msg(s[1]).startswith("🧭 stoiclife"), [msg(x)[:40] for x in s])
check("escalation=clarify logged", upd()["escalation"] == "clarify")

# --- SEND_FULL ----------------------------------------------------------------------------------------
reset_day()
ENGINE["out"] = "STOICLIFE_ACTION: SEND_FULL\n# date=2026-10-08 session=safety-net state=system_drain confidence=80 event_id=79 dry_run=False\n"
rc, s = run()
check("SEND_FULL: silent update + one coach turn (no script-sent push)", len(s) == 1 and "--silent" in s[0]
      and ESC["calls"] == [("2026-10-08", CHAT)], (s, ESC["calls"]))
check("escalation=send_full logged", upd()["escalation"] == "send_full" and upd()["event_id"] == 79)
reset_day()
ESC["ok"] = False
run()
check("coach turn failure logged as send_full_failed", upd()["escalation"] == "send_full_failed")
ESC["ok"] = True
check("prompt text points the coach at record_coaching --send", "--send" in du.ESCALATION_PROMPT and "NO_REPLY" in du.ESCALATION_PROMPT)
cmd_check = {}
orig_run = du.subprocess.run


class _Done:
    returncode = 0
    stdout = '{"status": "ok", "deliveryStatus": {"status": "suppressed"}}'


du.subprocess.run = lambda cmd, **kw: cmd_check.setdefault("cmd", cmd) and _Done()
try:
    ORIG_ESCALATE("ENGINE OUT", "2026-10-08", CHAT)
finally:
    du.subprocess.run = orig_run
c = cmd_check["cmd"]
check("coach turn: own session key, --deliver to the coach chat",
      "--session-key" in c and c[c.index("--session-key") + 1] == "agent:coach:stoiclife-11am-2026-10-08"
      and "--deliver" in c and c[c.index("--reply-to") + 1] == CHAT and c[c.index("--reply-account") + 1] == "coach", c)

# --- guards ---------------------------------------------------------------------------------------------
check("no route line for script sessions (D58)", sc_dispatch.handle_inject(
      {"sessionKey": "agent:coach:stoiclife-11am-2026-10-08", "chatId": CHAT}, conn) == {})
cfg = json.loads((REPO / "stoiclife_config.json").read_text())
cfg["db_path"] = str(DB)
CFG = TMP / "config.json"
CFG.write_text(json.dumps(cfg))
with conn:
    ev = conn.execute("INSERT INTO trigger_events (eval_datetime, date, session, state, fired, message_sent) "
                      "VALUES ('x', '2026-10-08', 'safety-net', 'system_drain', 1, 1)").lastrowid
n0 = len(sends())
r = subprocess.run([sys.executable, str(REPO / "record_coaching.py"), "--event-id", str(ev), "--channel", "telegram",
                    "--send", "--config", str(CFG)], input="anything", capture_output=True, text=True,
                   env={**os.environ, tg.FAKE_ENV: str(FAKE)})
check("record_coaching --send refuses an already-sent event (NO_REPLY, nothing stored/sent)",
      r.returncode == 0 and r.stdout.strip() == "NO_REPLY" and len(sends()) == n0
      and conn.execute("SELECT COUNT(*) FROM trigger_coaching WHERE event_id = ?", (ev,)).fetchone()[0] == 0,
      r.stdout + r.stderr)

# --- D54 extension: entry-time runs on a not_synced day are journal-only ---------------------------
import trigger_matrix  # noqa: E402
from status import health_check  # noqa: E402

DB2 = TMP / "d54.db"
with sqlite3.connect(DB2) as c:
    c.executescript(schema)
subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(DB2), "--no-backup"], check=True, capture_output=True)
c2 = trigger_matrix.connect(str(DB2))
mcfg = trigger_matrix.load_config(REPO / "stoiclife_config.json")
with c2:  # baseline 01–06 normal; 07 is a drained night (HRV down, RHR up); no row for 08/09
    for d in ("01", "02", "03", "04", "05", "06"):
        c2.execute("INSERT INTO biometrics (date, hrv_rmssd_ms, resting_hr_bpm, sleep_duration_min, sleep_score) "
                   "VALUES (?, 50, 50, 450, 85)", (f"2026-10-{d}",))
    c2.execute("INSERT INTO biometrics (date, hrv_rmssd_ms, resting_hr_bpm, sleep_duration_min, sleep_score) "
               "VALUES ('2026-10-07', 40, 60, 300, 50)")
    for day, session in (("2026-10-08", "evening"), ("2026-10-08", "morning"), ("2026-10-09", "morning"),
                         ("2026-10-10", "evening")):
        c2.execute("INSERT INTO journal_entries (date, session, raw_response, mood_score, created_at) "
                   "VALUES (?, ?, 'drained and exhausted, no energy', 3, ?)", (day, session, f"{day}T20:40:00+10:00"))
EVE = datetime(2026, 10, 8, 20, 40, tzinfo=TZ)

res, fired, _, ev_ctl = trigger_matrix.evaluate(c2, mcfg, "2026-10-08", "evening", write=False, now=EVE)
check("control: without not_synced, the stale (lag-1) row drives a firing state",
      res.state == "system_drain" and fired and res.deltas.get("bio_lag_days") == 1, (res.state, fired, res.deltas.get("bio_lag_days")))

with c2:
    c2.execute("INSERT INTO daily_updates (chat_id, local_date, status, synced, created_at, updated_at) "
               "VALUES (?, '2026-10-08', 'not_synced', 0, 'x', 'x')", (CHAT,))
res, fired, cd, ev = trigger_matrix.evaluate(c2, mcfg, "2026-10-08", "evening", write=True, now=EVE)
row = c2.execute("SELECT state, fired, notes FROM trigger_events WHERE id = ?", (ev,)).fetchone()
check("evening entry after not_synced -> journal-only: neutral, never fires (D54)",
      res.state == "neutral" and not fired and res.deltas == {"journal_only": True}, (res.state, fired, res.deltas))
check("…mood and keywords still read for the audit", res.mental_summary == "mood 3 (evening)"
      and {"drained", "exhausted", "no energy"} <= set(res.matched_keywords), (res.mental_summary, res.matched_keywords))
check("…event logged with the D54 note", row["state"] == "neutral" and row["fired"] == 0 and "D54" in row["notes"], dict(row))
h = health_check(mcfg, res, trigger_matrix.fetch_biometrics_today(c2, "2026-10-08", 2), now=EVE)
check("…health line is a warning that says 'not synced', never 🟢 all ok",
      not h["ok"] and "not synced" in h["checks"]["biometrics_fresh"]["detail"], h["checks"]["biometrics_fresh"])

late, fired, _, _ = trigger_matrix.evaluate(c2, mcfg, "2026-10-08", "morning", write=False,
                                            now=datetime(2026, 10, 8, 13, 0, tzinfo=TZ))
check("late morning prep (FEAT-05 time) on a not_synced day -> journal-only, no fire",
      late.state == "neutral" and not fired and late.deltas.get("journal_only"), (late.state, fired))

normal, fired, _, _ = trigger_matrix.evaluate(c2, mcfg, "2026-10-09", "morning", write=False,
                                              now=datetime(2026, 10, 9, 7, 45, tzinfo=TZ))
check("normal 07:30 entry unaffected: uses yesterday's data via the 2-day tolerance",
      not normal.deltas.get("journal_only") and normal.deltas.get("hrv_delta_pct") is not None
      and normal.deltas.get("bio_lag_days") == 2 and normal.state == "system_drain", (normal.state, normal.deltas))
check("…and still evaluate-only at 07:45 (FEAT-04), as before", not fired)
res10, fired10, _, _ = trigger_matrix.evaluate(c2, mcfg, "2026-10-10", "evening", write=False,
                                               now=datetime(2026, 10, 10, 20, 40, tzinfo=TZ))
check("not_synced on one day doesn't leak to another day", not res10.deltas.get("journal_only"))

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
