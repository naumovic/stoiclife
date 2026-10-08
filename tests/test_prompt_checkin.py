#!/usr/bin/env python3
"""MIN-129 — the prompt's in-place check-in: [Check in][Skip] -> mood -> module -> Write entry.
prompt_ui.py, sc_dispatch.handle_prompt_checkin, send_prompt's first step, handle_skip.
Scratch DB, temp state/log, fake sender: nothing live is touched.
Run: python3 tests/test_prompt_checkin.py
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
import prompts  # noqa: E402
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


TMP = Path(tempfile.mkdtemp(prefix="min129-"))
HOME = TMP / "home"
(HOME / ".openclaw" / "stoic").mkdir(parents=True)
(HOME / ".openclaw" / "workspace").mkdir()
os.symlink(SCRIPTS, HOME / ".openclaw" / "workspace" / "scripts")
tg.LOG_PATH = TMP / "stoic.log"
tg.STATE_PATH = TMP / "state.json"
FAKE = TMP / "sent.jsonl"
os.environ[tg.FAKE_ENV] = str(FAKE)
CHAT = "8917837483"
schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))


def fresh(db):
    with sqlite3.connect(db) as c:
        c.executescript(schema)
    subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(db), "--no-backup"],
                   capture_output=True, check=True)
    return sqlite3.connect(db)


def at(h, m=0, day=9):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def tap(pid, op, now, chat=CHAT):
    return sc_dispatch.handle_callback({"payload": f"pc:{pid}:{op}", "chatId": chat, "messageId": 500},
                                       conn, now)


def labels(out):
    return [[b["text"] for b in r] for r in out["actions"][0]["buttons"]]


def datas(out):
    return [[b["callback_data"] for b in r] for r in out["actions"][0]["buttons"]]


def state(day="2026-10-09"):
    return {k: v["value"] for k, v in checkins.today_state(conn, CHAT, day).items()}


conn = fresh(TMP / "p.db")
with conn:
    pm = prompts.record(conn, chat_id=CHAT, session="morning", message_id="500", now=at(7, 30))

# --- full path: go -> mood -> module -> Write entry ----------------------------------------
out = tap(pm, "go", at(7, 31))
check("go -> mood buttons 1-5 / 6-10, edited in place", out["actions"][0]["type"] == "editButtons"
      and labels(out) == [["1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"]]
      and datas(out)[0][0] == f"sc:pc:{pm}:m1", out)
out = tap(pm, "m6", at(7, 32))
check("mood 6 -> stored for the prompt's day (button)", state() == {"mood": "6"}
      and conn.execute("SELECT source FROM checkin_events WHERE type='mood'").fetchone()[0] == "button")
check("mood 6 -> ✓ row + modules + No module", labels(out) == [["✓ Mood 6"], ["Emotions", "Creativity", "Happiness"],
                                                              ["No module"]], out)
out = tap(pm, "m7", at(7, 32))
check("re-tapping a mood updates it", state() == {"mood": "7"} and labels(out)[0] == ["✓ Mood 7"])
out = tap(pm, "khappiness", at(7, 33))
check("module -> stored", state() == {"mood": "7", "module": "happiness"})
check("module -> ✓ Mood 7 · Happiness + Write entry / Skip today",
      labels(out) == [["✓ Mood 7 · Happiness"], ["✍️ Write entry", "Skip today"]]
      and datas(out)[1] == [f"sc:write:morning:{pm}", f"sc:skip:morning:{pm}"], out)
out = sc_dispatch.handle_callback({"payload": f"write:morning:{pm}", "chatId": CHAT}, conn, at(7, 34))
check("Write entry from step 4 -> 'Go ahead' + write slot", out["actions"][0]["text"].startswith("Go ahead")
      and tg.get_pending(CHAT, now=at(7, 35))["kind"] == "write:morning")
tg.clear_pending(CHAT)

# --- morning: No module, Skip ---------------------------------------------------------------
with conn:
    conn.execute("DELETE FROM checkin_events")
tap(pm, "go", at(7, 40))
tap(pm, "m5", at(7, 40))
out = tap(pm, "knone", at(7, 41))
check("morning No module -> no module stored, ✓ Mood 5 + Write/Skip", state() == {"mood": "5"}
      and labels(out) == [["✓ Mood 5"], ["✍️ Write entry", "Skip today"]], out)
with conn:
    conn.execute("DELETE FROM checkin_events")
out = tap(pm, "skip", at(7, 42))
check("Skip check-in -> 'Check-in skipped' + Write/Skip, nothing stored",
      labels(out) == [["Check-in skipped"], ["✍️ Write entry", "Skip today"]] and state() == {}, out)


# --- evening (MIN-133): module step only, lands on the evening entry --------------------------------
def entry(session, day, now):
    with conn:
        cur = conn.execute("INSERT INTO journal_entries (date, session, raw_response, created_at, mood_source) "
                           "VALUES (?, ?, 'x', ?, 'inferred')", (day, session, now.isoformat()))
    checkins.merge_into_entry(conn, cur.lastrowid, CHAT)
    return cur.lastrowid


def module_of(eid):
    return conn.execute("SELECT module FROM journal_entries WHERE id = ?", (eid,)).fetchone()[0]


with conn:
    checkins.upsert(conn, chat_id=CHAT, ctype="module", value="happiness", source="button", now=at(7, 45))
e_m = entry("morning", "2026-10-09", at(8))
check("morning entry gets the morning module", module_of(e_m) == "happiness")
with conn:
    pe = prompts.record(conn, chat_id=CHAT, session="evening", message_id="501", now=at(20, 30))
out = tap(pe, "kcreativity", at(20, 32))
check("evening module -> stored, '✓ Creativity' + Write/Skip (no mood row)",
      state().get("module") == "creativity"
      and labels(out) == [["✓ Creativity"], ["✍️ Write entry", "Skip today"]], out)
e_e = entry("evening", "2026-10-09", at(21))
check("evening entry gets the evening module; morning entry keeps its own",
      module_of(e_e) == "creativity" and module_of(e_m) == "happiness")

with conn:
    checkins.upsert(conn, chat_id=CHAT, ctype="module", value="emotions", source="button", now=at(7, 45, day=12))
e_m2 = entry("morning", "2026-10-12", at(8, day=12))
with conn:
    pe2 = prompts.record(conn, chat_id=CHAT, session="evening", message_id="504", now=at(20, 30, day=12))
out = tap(pe2, "knone", at(20, 32, day=12))
check("evening No module -> 'No module' even with a morning module in the DB",
      labels(out) == [["No module"], ["✍️ Write entry", "Skip today"]]
      and state("2026-10-12").get("module") == "emotions", out)
e_e2 = entry("evening", "2026-10-12", at(21, day=12))
check("evening No module -> the evening entry gets no module (morning's isn't carried over)",
      module_of(e_e2) is None and module_of(e_m2) == "emotions")

# --- evening after midnight, stale, foreign --------------------------------------------------
out = tap(pe, "kemotions", at(0, 30, day=10))
check("evening prompt tapped after midnight -> counts for its journaling day",
      state("2026-10-09").get("module") == "emotions" and not state("2026-10-10"), out)
check("next day after 07:30 -> Expired", labels(tap(pe, "khappiness", at(7, 35, day=10))) == [["Expired"]])
check("another chat -> Expired", labels(tap(pm, "go", at(8), chat="123")) == [["Expired"]])
check("unknown prompt -> Expired", labels(tap(9999, "go", at(8))) == [["Expired"]])
check("malformed payload -> ignored", sc_dispatch.handle_callback({"payload": f"pc:{pm}:m11", "chatId": CHAT},
                                                                  conn, at(8)) == {"actions": []})

# --- Skip today: Check in only while no mood ----------------------------------------------------
with conn:
    pk = prompts.record(conn, chat_id=CHAT, session="morning", message_id="502", now=at(7, 30, day=11))
out = sc_dispatch.handle_callback({"payload": f"skip:morning:{pk}", "chatId": CHAT}, conn, at(8, day=11))
check("Skip today, no mood -> Check in offered", labels(out) == [["✓ Skipped today"], ["🙂 Check in"]], out)
with conn:
    pk2 = prompts.record(conn, chat_id=CHAT, session="evening", message_id="503", now=at(20, 30, day=11))
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value="6", source="button", day="2026-10-11", now=at(20, 31, day=11))
out = sc_dispatch.handle_callback({"payload": f"skip:evening:{pk2}", "chatId": CHAT}, conn, at(20, 40, day=11))
check("Skip today, mood logged -> no Check in", labels(out) == [["✓ Skipped today"]], out)

# --- send_prompt: first step depends on the day's mood ------------------------------------------
env = {**os.environ, "HOME": str(HOME), tg.FAKE_ENV: str(FAKE)}
hdb = HOME / ".openclaw" / "stoic" / "stoic_journal.db"
hc = fresh(hdb)


def send(session):
    r = subprocess.run([sys.executable, str(REPO / "send_prompt.py"), "--session", session], input="☀️ Prep",
                       capture_output=True, text=True, env=env)
    a = [json.loads(l)["args"] for l in FAKE.read_text().splitlines()][-1]
    vals = [b["value"] for blk in json.loads(a[a.index("--presentation") + 1])["blocks"] for b in blk["buttons"]]
    pid = hc.execute("SELECT MAX(id) FROM prompt_events").fetchone()[0]
    return r, vals, pid


r, vals, pid = send("morning")
check("send_prompt, no mood -> [Check in] [Skip] with the prompt id", r.stdout.strip() == "NO_REPLY"
      and vals == [f"sc:pc:{pid}:go", f"sc:pc:{pid}:skip"], vals)
with hc:
    checkins.upsert(hc, chat_id=CHAT, ctype="mood", value="8", source="command")
r, vals, pid = send("morning")
check("send_prompt morning, mood logged today -> starts at ✓ + Write/Skip",
      vals == ["sc:noop", f"sc:write:morning:{pid}", f"sc:skip:morning:{pid}"], vals)
r, vals, pid = send("evening")
EVENING = [f"sc:pc:{pid}:kemotions", f"sc:pc:{pid}:kcreativity", f"sc:pc:{pid}:khappiness", f"sc:pc:{pid}:knone"]
check("send_prompt evening, mood logged -> module step, no mood row (MIN-133)", vals == EVENING, vals)
with hc:
    hc.execute("DELETE FROM checkin_events")
r, vals, pid = send("evening")
check("send_prompt evening, no mood -> still the module step, no mood step",
      vals == [v.replace(f":{pid - 1}:", f":{pid}:") for v in EVENING], vals)
r = subprocess.run([sys.executable, str(REPO / "send_prompt.py"), "--session", "morning"], input="t",
                   capture_output=True, text=True, env={**env, "STOICLIFE_SKIP_PROMPT_STATE": "1"})
a = [json.loads(l)["args"] for l in FAKE.read_text().splitlines()][-1]
vals = [b["value"] for blk in json.loads(a[a.index("--presentation") + 1])["blocks"] for b in blk["buttons"]]
check("test send (no prompt row) -> plain Write/Skip", vals == ["sc:write:morning", "sc:skip:morning"], vals)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
