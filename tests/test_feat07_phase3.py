#!/usr/bin/env python3
"""FEAT-07 Phase 3 — check-in card, dated buttons + stale guard, notes, /mood /module,
legacy inline values -> checkin_events (stamped at the entry's created_at), and the
G9 merge with all of it. Scratch DB + temp HOME; nothing live is touched.
Run: python3 tests/test_feat07_phase3.py
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
import save_pending_note  # noqa: E402
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


TMP = Path(tempfile.mkdtemp(prefix="feat07p3-"))
tg.LOG_PATH = TMP / "stoic.log"
tg.STATE_PATH = TMP / "state.json"
(TMP / ".openclaw" / "workspace").mkdir(parents=True)
(TMP / ".openclaw" / "stoic").mkdir()
os.symlink(Path.home() / ".openclaw" / "workspace" / "scripts", TMP / ".openclaw" / "workspace" / "scripts")
CHAT = "8917837483"
schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))


def fresh_db(name):
    db = TMP / name
    with sqlite3.connect(db) as c:
        c.executescript(schema)
    subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(db), "--no-backup"],
                   check=True, capture_output=True)
    return sqlite3.connect(db)


def at(h, m, day=8):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def labels(rows):
    return [[b["text"] for b in r] for r in rows]


def datas(rows):
    return [[b["callback_data"] for b in r] for r in rows]


conn = fresh_db("card.db")
NOW = at(9, 0)

# --- card rendering -----------------------------------------------------------------
text, rows = sc_dispatch.card(conn, CHAT, "2026-10-08")
check("empty card: title + hint", text == "Check-in · Thu 8 Oct\nTap a mood (1–10) and, if you like, a Stoic module.", text)
check("empty card: 2x5 mood + 3 modules, no note button",
      labels(rows) == [["1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"],
                       ["Emotions", "Creativity", "Happiness"]], labels(rows))
check("buttons carry the day (P3-D4)", datas(rows)[0][0] == "sc:mood:1:20261008"
      and datas(rows)[2][1] == "sc:mod:creativity:20261008")
check("all callback_data <= 64 bytes", all(len(d.encode()) <= 64 for r in datas(rows) for d in r))

# --- taps ------------------------------------------------------------------------------
def tap(payload, mid=500, now=NOW):
    return sc_dispatch.handle_callback({"payload": payload, "chatId": CHAT, "messageId": mid,
                                        "messageText": "whatever"}, conn, now)


out = tap("mood:7:20261008")["actions"][0]
check("mood tap re-renders the card", out["type"] == "edit" and out["text"] == "Check-in · Thu 8 Oct\nMood: 7 ✓", out)
check("chosen mood marked, module row still there", labels(out["buttons"])[1][1] == "7 ✓"
      and labels(out["buttons"])[2] == ["Emotions", "Creativity", "Happiness"], labels(out["buttons"]))
check("one note button once mood chosen", datas(out["buttons"])[3] == ["sc:note:mood:20261008"])
out = tap("mod:creativity:20261008")["actions"][0]
check("module tap: combined status line", out["text"].endswith("Mood: 7 ✓ · Module: Creativity ✓"), out["text"])
check("two note buttons when both chosen", datas(out["buttons"])[3] == ["sc:note:mood:20261008", "sc:note:module:20261008"])
out = tap("mood:3:20261008")["actions"][0]
check("re-tap: latest wins, one row", "Mood: 3 ✓" in out["text"] and conn.execute(
      "SELECT COUNT(*), MAX(value) FROM checkin_events WHERE type='mood'").fetchone() == (1, "3"))
check("source=button", conn.execute("SELECT source FROM checkin_events WHERE type='mood'").fetchone()[0] == "button")

out = tap("mood:9:20261007")
check("yesterday's card -> expired, nothing written", out["actions"][0]["buttons"] == []
      and "expired" in out["actions"][0]["text"] and conn.execute(
      "SELECT value FROM checkin_events WHERE type='mood'").fetchone()[0] == "3", out)
check("plan's suffix-less form still accepted", "Mood: 4 ✓" in tap("mood:4")["actions"][0]["text"])
out = tap("mood:5:20261008", now=at(7, 0, day=9))  # 07:00 on the 9th is still logical day 8
check("before 07:30 the previous day's card is still live", "Mood: 5 ✓" in out["actions"][0]["text"], out)

# --- notes -------------------------------------------------------------------------------
out = tap("note:mood:20261008")
check("note tap asks for the note", out == {"actions": [{"type": "reply", "text": "Add your mood note below."}]}, out)
pend = tg.get_pending(CHAT)
check("pending note:mood:<day>, ~2h", pend and pend["kind"] == "note:mood:20261008"
      and datetime.fromisoformat(pend["expires_at"]) == NOW + timedelta(hours=2), pend)
check("typed note saved (SAVED)", save_pending_note.save_note("slept badly, still ok", CHAT, conn))
check("note stored on the mood row", conn.execute(
      "SELECT note FROM checkin_events WHERE type='mood'").fetchone()[0] == "slept badly, still ok")
check("pending cleared", tg.get_pending(CHAT) is None)
text, _ = sc_dispatch.card(conn, CHAT, "2026-10-08")
check("card shows the note", "📝 Mood note: slept badly, still ok" in text, text)
c2 = fresh_db("nonote.db")
out = sc_dispatch.handle_callback({"payload": "note:module:20261008", "chatId": CHAT, "messageId": 1}, c2, NOW)
check("note before choosing -> asks to pick first", "Pick a module first" in out["actions"][0]["text"], out)
tap("fb:r1:up")  # unknown target; just make sure the fb path still coexists
tg.set_pending("note:mood:20261008", chat_id=CHAT)
tap("note:module:20261008")
check("newer intent replaces the pending slot", tg.get_pending(CHAT)["kind"] == "note:module:20261008")
tg.clear_pending(CHAT)

# --- P3-B1: message_received hook saves deterministically -----------------------------------
tg.set_pending("note:module:20261008", chat_id=CHAT, expires_at=datetime.now(TZ) + timedelta(hours=1))
c_msg = conn
_orig_connect = tg.db_connect
tg.db_connect = lambda path=None: c_msg  # the hook path opens its own connection
out = sc_dispatch.handle_message({"text": "Rockin", "chatId": f"telegram:{CHAT}"})
check("hook saves the pending note before the LLM", out == {"saved": True}, out)
check("module note stored", conn.execute("SELECT note FROM checkin_events WHERE type='module'").fetchone()[0] == "Rockin")
check("pending cleared, consumed marker left", tg.get_pending(CHAT) is None
      and (tg.read_state().get("consumed") or {}).get(CHAT, {}).get("text") == "Rockin")
check("coach step 0 on the same message -> SAVED (from the marker)", save_pending_note.save_note("Rockin", CHAT, conn))
check("marker used up", not (tg.read_state().get("consumed") or {}).get(CHAT))
check("a later normal message -> NONE", not save_pending_note.save_note("Rockin", CHAT, conn))
tg.mark_consumed("old note", "note:mood:20261008", chat_id=CHAT)
check("different text -> marker not used", not save_pending_note.save_note("something else", CHAT, conn))
check("stale marker (>10 min) -> not SAVED", tg.take_consumed("old note", chat_id=CHAT,
      now=datetime.now(TZ) + timedelta(minutes=11)) is None)
tg.set_pending("note:mood:20261008", chat_id=CHAT, expires_at=datetime.now(TZ) + timedelta(hours=1))
for t in ("/mood", "morning prep: today is fine", "Evening review: ok", "  "):
    check(f"hook ignores {t!r}", sc_dispatch.handle_message({"text": t, "chatId": CHAT}) == {"saved": False}
          and tg.get_pending(CHAT) is not None)
check("agent-first path still works (hook then finds nothing)",
      save_pending_note.save_note("agent got here first", CHAT, conn)
      and sc_dispatch.handle_message({"text": "agent got here first", "chatId": CHAT}) == {"saved": False})
check("no pending -> hook does nothing", sc_dispatch.handle_message({"text": "hello", "chatId": CHAT}) == {"saved": False})
tg.db_connect = _orig_connect

# --- commands --------------------------------------------------------------------------
out = sc_dispatch.handle_command({"command": "mood", "chatId": f"telegram:{CHAT}"}, conn, NOW)
rep = out["reply"]
check("/mood -> card with exact rows in channelData (P3-D2)",
      rep["text"].startswith("Check-in · Thu 8 Oct") and
      datas(rep["channelData"]["telegram"]["buttons"])[0] == [f"sc:mood:{n}:20261008" for n in range(1, 6)], rep)
check("/mood strips the telegram: prefix (P3-D8)", "Mood: 5 ✓" in rep["text"], rep["text"])
check("/module -> same card", sc_dispatch.handle_command({"command": "module", "chatId": CHAT}, conn, NOW)["reply"]["text"] == rep["text"])
for cmd in ("journal", "skip"):
    check(f"/{cmd} still 'Coming soon' (P3-D5)",
          "Coming soon" in sc_dispatch.handle_command({"command": cmd})["reply"]["text"])
proc = subprocess.run([sys.executable, str(REPO / "sc_dispatch.py")],
                      input=json.dumps({"kind": "command", "command": "skip"}), capture_output=True, text=True,
                      env={**os.environ, "HOME": str(TMP)})
check("CLI command output is {'reply': …}", proc.returncode == 0 and "reply" in json.loads(proc.stdout), proc.stdout + proc.stderr)
proc = subprocess.run([sys.executable, str(REPO / "sc_dispatch.py")],
                      input=json.dumps({"kind": "message", "text": "/mood", "chatId": "telegram:1"}),
                      capture_output=True, text=True, env={**os.environ, "HOME": str(TMP)})
check("CLI message kind -> {'saved': False}", proc.returncode == 0 and json.loads(proc.stdout) == {"saved": False},
      proc.stdout + proc.stderr)

# --- legacy inline -> checkin_events (P3-D6) + G9 -----------------------------------------
c3 = fresh_db("legacy.db")


def entry(day, created, mood=None, source="inferred", module=None):
    with c3:
        return c3.execute("INSERT INTO journal_entries (date, session, raw_response, mood_score, mood_source, "
                          "module, created_at) VALUES (?, 'x', 't', ?, ?, ?, ?)",
                          (day, mood, source, module, created.isoformat())).lastrowid


e1 = entry("2026-10-08", at(7, 50), mood=6, source="manual", module="emotions")
with c3:
    checkins.merge_into_entry(c3, e1, CHAT)
rows3 = c3.execute("SELECT type, value, source, updated_at FROM checkin_events ORDER BY type").fetchall()
check("inline mood + module logged as legacy_prefix",
      [(t, v, s) for t, v, s, _ in rows3] == [("module", "emotions", "legacy_prefix"), ("mood", "6", "legacy_prefix")], rows3)
check("stamped at the entry's created_at", all(u == at(7, 50).isoformat() for *_, u in rows3), rows3)
e2 = entry("2026-10-08", at(20, 40))
with c3:
    ch = checkins.merge_into_entry(c3, e2, CHAT)
check("evening entry does NOT inherit the morning's inline values", ch == {}, ch)
with c3:
    checkins.upsert(c3, chat_id=CHAT, ctype="mood", value=8, source="button", now=at(7, 40, day=9))
e3 = entry("2026-10-09", at(7, 45, day=9), mood=4, source="manual")
with c3:
    checkins.merge_into_entry(c3, e3, CHAT)
check("inline beats an earlier button tap (entry keeps 4, check-in becomes 4/legacy)",
      c3.execute("SELECT mood_score FROM journal_entries WHERE id=?", (e3,)).fetchone()[0] == 4 and
      c3.execute("SELECT value, source FROM checkin_events WHERE local_date='2026-10-09' AND type='mood'").fetchone()
      == ("4", "legacy_prefix"))
with c3:
    checkins.upsert(c3, chat_id=CHAT, ctype="mood", value=2, source="button", now=at(7, 40, day=10))
e4 = entry("2026-10-10", at(7, 50, day=10))
with c3:
    ch = checkins.merge_into_entry(c3, e4, CHAT)
check("button tap before an entry with no inline mood still merges (G9)", ch == {"mood_score": 2}, ch)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
