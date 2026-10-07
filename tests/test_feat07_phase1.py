#!/usr/bin/env python3
"""FEAT-07 Phase 1 — migrations, check-ins + merge rule (G9), sc_dispatch, pending
state (G2), and the save_entry / set_prompt_state patches, all against scratch copies.

Never touches the live DB or ~/.openclaw/stoic/state.json: a temp HOME is used for the
workspace-script subprocess tests. Run: python3 tests/test_feat07_phase1.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = Path.home() / ".openclaw" / "workspace" / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(SCRIPTS))

import checkins  # noqa: E402
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


TMP = Path(tempfile.mkdtemp(prefix="feat07-"))
tg.LOG_PATH = TMP / "stoic.log"  # keep test noise out of the live log
LIVE_SCHEMA = subprocess.run(
    ["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
    capture_output=True, text=True, check=True).stdout
# sqlite_sequence appears once AUTOINCREMENT tables exist; it can't be created by hand.
LIVE_SCHEMA = "\n".join(l for l in LIVE_SCHEMA.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))


def scratch_db(name="t.db") -> Path:
    db = TMP / name
    if db.exists():
        db.unlink()
    with sqlite3.connect(db) as c:
        c.executescript(LIVE_SCHEMA)
    return db


def migrate(db: Path):
    return subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(db), "--no-backup"],
                          capture_output=True, text=True)


def at(h, m, day=7):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


# --- migrations ---------------------------------------------------------------
db = scratch_db()
r1 = migrate(db)
r2 = migrate(db)
check("migrate applies 001", "applied 001_ux_tables.sql" in r1.stdout, r1.stdout + r1.stderr)
check("migrate re-run is a no-op", "no pending migrations" in r2.stdout, r2.stdout)
conn = sqlite3.connect(db)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
for t in ("checkin_events", "coaching_responses", "response_feedback", "ui_messages",
          "schema_migrations"):
    check(f"table {t} exists", t in tables)
check("schema_migrations has one row per migration file",
      conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(list((REPO / "migrations").glob("*.sql"))))
# Applying the SQL a second time directly (lost schema_migrations row) is harmless.
conn.executescript((REPO / "migrations" / "001_ux_tables.sql").read_text())
check("001 SQL itself is idempotent", True)

# --- local_date (G1) ----------------------------------------------------------
import save_entry  # noqa: E402
check("MORNING_CUTOFF matches save_entry", checkins.MORNING_CUTOFF == save_entry.MORNING_CUTOFF)
check("07:29 -> previous day", checkins.local_date(at(7, 29)) == "2026-10-06")
check("07:30 -> same day", checkins.local_date(at(7, 30)) == "2026-10-07")
check("01:00 -> previous day", checkins.local_date(at(1, 0, day=8)) == "2026-10-07")

# --- upsert -------------------------------------------------------------------
CHAT = "8917837483"
with conn:
    a = checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=7, source="button", now=at(8, 0))
    b = checkins.upsert(conn, chat_id=CHAT, ctype="mood", value="4", source="command", now=at(9, 0))
row = conn.execute("SELECT value, source, created_at, updated_at FROM checkin_events WHERE id=?",
                   (a,)).fetchone()
check("upsert keeps one row per day/type", a == b and
      conn.execute("SELECT COUNT(*) FROM checkin_events").fetchone()[0] == 1)
check("latest wins", row[0] == "4" and row[1] == "command", row)
check("created_at kept, updated_at bumped", row[2] < row[3], row)
for bad in (0, 11, "x"):
    try:
        checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=bad, source="button")
        check(f"mood {bad!r} rejected", False)
    except ValueError:
        check(f"mood {bad!r} rejected", True)

# --- merge rule (G9) ----------------------------------------------------------
def entry(conn, day, created, mood=None, source="inferred", module=None):
    cur = conn.execute(
        "INSERT INTO journal_entries (date, session, raw_response, mood_score, mood_source, "
        "module, created_at) VALUES (?, 'x', 't', ?, ?, ?, ?)",
        (day, mood, source, module, created.isoformat()))
    return cur.lastrowid


db = scratch_db("merge.db"); migrate(db); conn = sqlite3.connect(db)
with conn:
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=6, source="button", now=at(7, 40))
    checkins.upsert(conn, chat_id=CHAT, ctype="module", value="creativity", source="button",
                    now=at(7, 41))
    e1 = entry(conn, "2026-10-07", at(7, 50))
    ch1 = checkins.merge_into_entry(conn, e1, CHAT)
check("first entry of day takes button mood+module",
      ch1 == {"mood_score": 6, "module": "creativity"}, ch1)
check("merged mood is manual",
      conn.execute("SELECT mood_source FROM journal_entries WHERE id=?", (e1,)).fetchone()[0] == "manual")
with conn:
    e2 = entry(conn, "2026-10-07", at(20, 40))
    ch2 = checkins.merge_into_entry(conn, e2, CHAT)
check("evening entry does NOT inherit the morning tap", ch2 == {}, ch2)
with conn:
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=3, source="button", now=at(20, 45))
    e3 = entry(conn, "2026-10-07", at(20, 50))
    ch3 = checkins.merge_into_entry(conn, e3, CHAT)
check("a tap after the previous entry lands on the next one", ch3 == {"mood_score": 3}, ch3)
with conn:
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=9, source="button", now=at(8, 0, day=8))
    checkins.upsert(conn, chat_id=CHAT, ctype="module", value="emotions", source="button", now=at(8, 0, day=8))
    e4 = entry(conn, "2026-10-08", at(8, 5, day=8), mood=5, source="manual", module="happiness")
    ch4 = checkins.merge_into_entry(conn, e4, CHAT)
check("inline mood + module win over buttons", ch4 == {}, ch4)
with conn:
    e5 = entry(conn, "2026-10-09", at(8, 0, day=9))
    ch5 = checkins.merge_into_entry(conn, e5, CHAT)
check("no check-ins that day -> nothing merged", ch5 == {}, ch5)

# --- sc_dispatch ----------------------------------------------------------------
for payload, want in [("mood:7", "mood"), ("mood:10", "mood"), ("mood:0", None), ("mood:11", None),
                      ("mod:creativity", "mod"), ("mod:joy", None),
                      ("fb:r12:up", "fb"), ("fb:t3:down", "fb"), ("fb:x3:up", None),
                      ("fbr:r12:offbase", "fbr"), ("fbr:r12:meh", None),
                      ("write:morning", "write"), ("skip:evening", "skip"), ("skip:noon", None),
                      ("note:mood", "note"), ("", None), ("bogus", None), ("mood:7:extra", None)]:
    check(f"parse {payload!r} -> {want}", sc_dispatch.parse(payload)[0] == want)

db = scratch_db("dispatch.db"); migrate(db); conn = sqlite3.connect(db)
now = at(10, 0)
out = sc_dispatch.handle_callback({"payload": "mood:7", "chatId": CHAT, "messageId": 555,
                                   "messageText": "[FEAT-07 test] Tap"}, conn, now)
# Since Phase 3 a tap re-renders the check-in card (own tests in test_feat07_phase3.py).
check("mood tap edits message", out["actions"][0]["type"] == "edit"
      and out["actions"][0]["text"] == "Check-in · Wed 7 Oct\nMood: 7 ✓", out)
check("mood tap wrote check-in", conn.execute(
      "SELECT value, source, message_id, local_date FROM checkin_events").fetchall()
      == [("7", "button", "555", "2026-10-07")])
out = sc_dispatch.handle_callback({"payload": "mood:8", "chatId": CHAT, "messageId": 555,
                                   "messageText": "[FEAT-07 test] Tap\n\n✓ Mood: 7 ✓"}, conn, now)
check("re-tap replaces the status line, not appends",
      out["actions"][0]["text"] == "Check-in · Wed 7 Oct\nMood: 8 ✓", out)
out = sc_dispatch.handle_callback({"payload": "mod:happiness", "chatId": CHAT, "messageId": 556,
                                   "messageText": "pick"}, conn, now)
check("module tap", out["actions"][0]["text"].endswith("Module: Happiness ✓"), out)
with conn:
    tg.record_ui_message(conn, message_id="600", kind="picker", chat_id=CHAT, day="2026-10-06")
before = conn.execute("SELECT COUNT(*), MAX(updated_at) FROM checkin_events").fetchone()
out = sc_dispatch.handle_callback({"payload": "mood:2", "chatId": CHAT, "messageId": 600,
                                   "messageText": "old picker"}, conn, now)
check("stale picker (G5) -> expired edit", "expired" in out["actions"][0]["text"], out)
check("stale picker writes nothing",
      conn.execute("SELECT COUNT(*), MAX(updated_at) FROM checkin_events").fetchone() == before)
for p in ("bogus:1", "mood:99", "skip:noon"):  # fb:* live since Phase 2, write/skip since Phase 4
    out = sc_dispatch.handle_callback({"payload": p, "chatId": CHAT, "messageId": 1}, conn, now)
    check(f"{p} -> no actions (logged)", out == {"actions": []}, out)
check("unknown commands answer 'coming soon'",
      "Coming soon" in sc_dispatch.handle_command({"command": "nope"}, conn, now)["reply"]["text"])


# --- tg helpers -------------------------------------------------------------------
check("presentation: one buttons block per row",
      tg.presentation([[("1", "sc:mood:1"), ("2", "sc:mood:2")], [("x", "sc:mod:emotions")]])
      == {"blocks": [{"type": "buttons", "buttons": [{"label": "1", "value": "sc:mood:1"},
                                                     {"label": "2", "value": "sc:mood:2"}]},
                     {"type": "buttons", "buttons": [{"label": "x", "value": "sc:mod:emotions"}]}]})
try:
    tg.presentation([[("x", "sc:" + "a" * 70)]])
    check("over-64-byte callback rejected", False)
except ValueError:
    check("over-64-byte callback rejected", True)
check("message id found in nested CLI JSON",
      tg._find_message_id({"payload": {"result": {"messageId": 4242}}}) == "4242")
check("JSON parsed after warning lines",
      tg._parse_json_stdout("warn: x\n{\"a\": 1}\n") == {"a": 1})

sp = TMP / "state.json"
sp.write_text(json.dumps({"awaiting_response": True, "session": "morning", "prompt_sent_at": "x"}))
tg.set_pending("morning", chat_id=CHAT, message_id="77",
               expires_at=datetime.now(TZ) + timedelta(hours=1), path=sp)
st = json.loads(sp.read_text())
check("set_pending keeps legacy keys", st["awaiting_response"] is True and st["session"] == "morning")
check("get_pending returns live entry", (tg.get_pending(CHAT, path=sp) or {}).get("message_id") == "77")
check("get_pending ignores expired",
      tg.get_pending(CHAT, now=datetime.now(TZ) + timedelta(hours=2), path=sp) is None)
tg.clear_pending(CHAT, path=sp)
check("clear_pending removes it", tg.get_pending(CHAT, path=sp) is None)

# --- workspace scripts under a temp HOME (G2 + G9 end to end) ----------------------
home = TMP / "home"
(home / ".openclaw" / "stoic").mkdir(parents=True)
(home / "projects").mkdir()
os.symlink(REPO, home / "projects" / "stoiclife")
hdb = home / ".openclaw" / "stoic" / "stoic_journal.db"
with sqlite3.connect(hdb) as c:
    c.executescript(LIVE_SCHEMA)
migrate(hdb)
hstate = home / ".openclaw" / "stoic" / "state.json"
pending = {CHAT: {"kind": "morning", "message_id": "1", "set_at": "x", "expires_at": None}}
hstate.write_text(json.dumps({"awaiting_response": False, "session": None,
                              "prompt_sent_at": None, "pending": pending}))
env = {**os.environ, "HOME": str(home)}
(home / ".openclaw" / "workspace").mkdir()
os.symlink(SCRIPTS, home / ".openclaw" / "workspace" / "scripts")  # active_tz etc., read-only use
proc = subprocess.run([sys.executable, str(REPO / "sc_dispatch.py")], input="not json",
                      capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
check("bad stdin -> empty actions, exit 0",
      proc.returncode == 0 and json.loads(proc.stdout) == {"actions": []}, proc.stdout + proc.stderr)
r = subprocess.run([sys.executable, str(SCRIPTS / "set_prompt_state.py"), "--session", "morning"],
                   capture_output=True, text=True, env=env)
st = json.loads(hstate.read_text())
check("set_prompt_state keeps pending (G2)", r.returncode == 0 and st.get("pending") == pending
      and st["awaiting_response"] is True, r.stderr + json.dumps(st))

with sqlite3.connect(hdb) as c:
    # save_entry dates this entry by the prompt's calendar date (set_prompt_state just ran),
    # so pin the check-ins to that day: before 07:30 the logical day would be yesterday.
    prompt_day = datetime.now(TZ).strftime("%Y-%m-%d")
    checkins.upsert(c, chat_id=CHAT, ctype="mood", value=8, source="button", day=prompt_day)
    checkins.upsert(c, chat_id=CHAT, ctype="module", value="emotions", source="button", day=prompt_day)
r = subprocess.run([sys.executable, str(SCRIPTS / "save_entry.py"), "--session", "morning",
                    "--response", "plain entry, no inline tags"],
                   capture_output=True, text=True, env=env)
st = json.loads(hstate.read_text())
row = sqlite3.connect(hdb).execute(
    "SELECT mood_score, mood_source, module FROM journal_entries ORDER BY id DESC LIMIT 1").fetchone()
check("save_entry ok", r.returncode == 0 and r.stdout.strip().isdigit(), r.stdout + r.stderr)
check("save_entry merged button mood+module (G9)", row == (8, "manual", "emotions"), row)
check("save_entry reset keeps pending (G2)", st.get("pending") == pending and
      st["awaiting_response"] is False, json.dumps(st))
r = subprocess.run([sys.executable, str(SCRIPTS / "save_entry.py"), "--session", "evening",
                    "--response", "mood 3 evening words", "--force"],
                   capture_output=True, text=True, env=env)
row = sqlite3.connect(hdb).execute(
    "SELECT mood_score, mood_source, module FROM journal_entries ORDER BY id DESC LIMIT 1").fetchone()
check("second entry: inline mood kept, morning tap not re-applied", row == (3, "manual", None), row)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
