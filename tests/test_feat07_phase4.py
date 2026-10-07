#!/usr/bin/env python3
"""FEAT-07 Phase 4 — routing on arrival (D41–D52): prompts/windows, route_entry rules,
hold and confirm, LLM-free notes, route injection, write/skip/card, /journal /skip,
send_prompt. Scratch DB, temp state, fake sender: nothing live is touched.
Run: python3 tests/test_feat07_phase4.py
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
import prompts  # noqa: E402
import route_entry  # noqa: E402
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


TMP = Path(tempfile.mkdtemp(prefix="feat07p4-"))
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


def fresh(name):
    db = TMP / name
    with sqlite3.connect(db) as c:
        c.executescript(schema)
    r = subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(db), "--no-backup"],
                       capture_output=True, text=True)
    return sqlite3.connect(db), r, db


def at(h, m=0, day=8):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def reset_state():
    tg.write_state({"awaiting_response": False, "session": None, "prompt_sent_at": None})


def sent():
    return [json.loads(l)["args"] for l in FAKE.read_text().splitlines()] if FAKE.exists() else []


conn, r, DB = fresh("p4.db")
check("migration 002 applies (fresh DB gets 001 + 002)", "002_prompt_events.sql" in r.stdout, r.stdout + r.stderr)
tables = {t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("prompt_events + route_events exist", {"prompt_events", "route_events"} <= tables)

# --- prompts ---------------------------------------------------------------------------
check("morning window ends 11:00", prompts.window_end("morning", at(7, 30)) == at(11))
check("evening window ends 03:00 next day", prompts.window_end("evening", at(20, 30)) == at(3, day=9))
check("a late morning prompt still gets an hour", prompts.window_end("morning", at(11, 30)) == at(12, 30))
with conn:
    pm = prompts.record(conn, chat_id=CHAT, session="morning", message_id="300", now=at(7, 30))
op = prompts.open_prompt(conn, CHAT, at(8))
check("open prompt found", op and op["id"] == pm and op["local_date"] == "2026-10-08")
check("in window at 10:59, not at 11:00", prompts.in_window(op, at(10, 59)) and not prompts.in_window(op, at(11)))
check("current session: morning before any morning entry", prompts.current_session(conn, CHAT, at(9)) == "morning")

# --- routing rules -------------------------------------------------------------------------
reset_state()


def route(text, now, reply=None):
    return route_entry.decide(conn, chat_id=CHAT, text=text, reply_to_id=reply, now=now)


d = route("Slept badly but ready.", at(8))
check("window: plain text -> morning entry", d["route"] == "entry" and d["session"] == "morning"
      and d["source"] == "window" and d["prompt_id"] == pm, d)
d = route("Why do I always rush?", at(8))
check("window: ends in ? -> hold (question)", d["route"] == "hold" and d["hold_kind"] == "question", d)
check("window: '?  ' trailing spaces still a question", route("really?  ", at(8))["route"] == "hold")
d = route("Lunch was good", at(13))
check("late (after 11:00): -> hold (late)", d["route"] == "hold" and d["hold_kind"] == "late" and d["session"] == "morning", d)
d = route("morning prep: Calm start. mood 7", at(13))
check("legacy prefix -> entry, prefix stripped", d["route"] == "entry" and d["source"] == "prefix"
      and d["text"] == "Calm start. mood 7" and d["prompt_id"] == pm, d)
d = route("Evening review: fine", at(13))
check("prefix for the other session -> entry, no prompt link", d["session"] == "evening" and d["prompt_id"] is None, d)
d = route("Answering this one", at(15), reply="300")
check("reply to the prompt (past window) -> entry", d["route"] == "entry" and d["source"] == "reply", d)
check("/command -> passthrough", route("/mood", at(8))["route"] == "passthrough")
tg.set_pending("note:mood:20261008", chat_id=CHAT)
d = route("tired but fine", at(8))
check("pending note beats the open window", d["route"] == "note", d)
check("prefix beats a pending note", route("morning prep: x", at(8))["route"] == "entry")
tg.set_pending("write:evening", chat_id=CHAT, expires_at=at(10))
d = route("Written via /journal?", at(9))
check("pending write -> entry directly, even with '?'", d["route"] == "entry" and d["source"] == "write"
      and d["session"] == "evening", d)
check("expired write slot -> back to the window", route("hello", at(10, 30))["source"] == "window")
tg.clear_pending(CHAT)
with conn:
    pe = prompts.record(conn, chat_id=CHAT, session="evening", message_id="301", now=at(20, 30))
d = route("Good day", at(21))
check("newer evening prompt replaces the morning one", d["session"] == "evening" and d["prompt_id"] == pe, d)
check("evening late after 03:00 -> hold", route("hi", at(3, 30, day=9))["route"] == "hold")
with conn:
    prompts.skip(conn, pe, at(21))
check("skipped prompt -> conversation", route("hi", at(21, 5))["route"] == "conversation")
with conn:
    prompts.unskip(conn, pe)
    e = conn.execute("INSERT INTO journal_entries (date, session, raw_response, created_at) VALUES "
                     "('2026-10-08','evening','x',?)", (at(21, 10).isoformat(),)).lastrowid
    checkins.merge_into_entry(conn, e, CHAT)
check("saving an entry links the prompt (answered)", prompts.get(conn, pe)["entry_id"] == e)
check("answered prompt -> conversation", route("thanks!", at(21, 20))["route"] == "conversation")
check("24h after the last prompt -> conversation", route_entry.decide(
      conn, chat_id=CHAT, text="x", now=at(21, 0, day=10))["route"] == "conversation")
check("current session: evening once the evening prompt went out", prompts.current_session(conn, CHAT, at(21)) == "evening")

# --- dispatch: notes, holds, entries, injection ----------------------------------------------
conn, _, DB = fresh("p4b.db")
reset_state()
with conn:
    pm = prompts.record(conn, chat_id=CHAT, session="morning", message_id="400", now=at(7, 30))
    checkins.upsert(conn, chat_id=CHAT, ctype="mood", value=6, source="button", now=at(7, 40))
tg.set_pending("note:mood:20261008", chat_id=CHAT)
out = sc_dispatch.handle_dispatch({"text": "slept 4h", "chatId": CHAT, "sessionKey": "k1"}, conn, at(7, 45))
check("note -> handled with 'Thanks, noted.' (no agent, D42)", out == {"handled": True, "text": "Thanks, noted."}, out)
check("note saved", conn.execute("SELECT note FROM checkin_events WHERE type='mood'").fetchone()[0] == "slept 4h")

n0 = len(sent())
out = sc_dispatch.handle_dispatch({"text": "Is patience a virtue?", "chatId": f"telegram:{CHAT}", "sessionKey": "k2"},
                                  conn, at(8))
hold = route_entry.get_hold(CHAT)
check("question in window -> held (handled, no text)", out == {"handled": True}, out)
check("hold stored with text and confirm message id", hold and hold["text"] == "Is patience a virtue?"
      and hold["message_id"] == str(90000 + n0), hold)
a = sent()[-1]
vals = [b["value"] for blk in json.loads(a[a.index("--presentation") + 1])["blocks"] for b in blk["buttons"]]
check("confirm buttons sent", vals == [f"sc:hold:e:{hold['id']}", f"sc:hold:c:{hold['id']}"], vals)
tap = sc_dispatch.handle_callback({"payload": f"hold:e:{hold['id']}", "chatId": CHAT, "messageId": 1}, conn, at(8, 1))
check("tap 📝 -> ticked + passToAgent", tap["passToAgent"] is True and
      tap["actions"][0]["buttons"][0][0]["text"] == "✓ Saved as morning prep", tap)
out = sc_dispatch.handle_dispatch({"text": f"callback_data: sc:hold:e:{hold['id']}", "chatId": CHAT,
                                   "sessionKey": "k3"}, conn, at(8, 1))
row = conn.execute("SELECT route, session, source, text, hold_id FROM route_events ORDER BY id DESC LIMIT 1").fetchone()
check("synthetic tap -> entry route with the HELD text", out == {"handled": False}
      and row == ("entry", "morning", "hold", "Is patience a virtue?", hold["id"]), row)
check("hold cleared after use", route_entry.get_hold(CHAT) is None)
inj = sc_dispatch.handle_inject({"sessionKey": "k3", "chatId": CHAT}, conn, at(8, 1, ))
check("inject: ENTRY line with the held text", "ENTRY session=morning" in inj["prependContext"]
      and "<<<\nIs patience a virtue?\n>>>" in inj["prependContext"], inj)
check("injected_at stamped", conn.execute("SELECT injected_at FROM route_events ORDER BY id DESC LIMIT 1").fetchone()[0])
check("a route is injected only once", "NONE recorded" in sc_dispatch.handle_inject({"sessionKey": "k3", "chatId": CHAT}, conn, at(8, 1))["prependContext"])

sc_dispatch.handle_dispatch({"text": "Calm morning, all fine.", "chatId": CHAT, "sessionKey": "k4"}, conn, at(8, 5))
inj = sc_dispatch.handle_inject({"sessionKey": "other-key", "chatId": CHAT}, conn, at(8, 5))
check("key mismatch -> chat fallback still finds the route (P4-D13)", "Calm morning, all fine." in inj["prependContext"], inj)
sc_dispatch.handle_dispatch({"text": "just chatting now", "chatId": CHAT, "sessionKey": "k5"}, conn, at(8, 6))
check("stale route (>2 min) is not injected", "NONE recorded" in sc_dispatch.handle_inject(
      {"sessionKey": "k5", "chatId": CHAT}, conn, at(8, 9))["prependContext"])

out = sc_dispatch.handle_dispatch({"text": "Lunch!", "chatId": CHAT, "sessionKey": "k6"}, conn, at(13))
h = route_entry.get_hold(CHAT)
tap = sc_dispatch.handle_callback({"payload": f"hold:c:{h['id']}", "chatId": CHAT}, conn, at(13, 1))
check("late hold, tap 💬 -> '✓ Just chatting' + passToAgent", tap["passToAgent"]
      and tap["actions"][0]["buttons"][0][0]["text"] == "✓ Just chatting", tap)
sc_dispatch.handle_dispatch({"text": f"callback_data: sc:hold:c:{h['id']}", "chatId": CHAT, "sessionKey": "k7"}, conn, at(13, 1))
inj = sc_dispatch.handle_inject({"sessionKey": "k7", "chatId": CHAT}, conn, at(13, 1))
check("💬 -> CONVERSATION with the held text", "CONVERSATION" in inj["prependContext"] and "Lunch!" in inj["prependContext"], inj)
tap = sc_dispatch.handle_callback({"payload": f"hold:e:{h['id']}", "chatId": CHAT}, conn, at(13, 2))
check("second tap on a used hold -> Expired, not passed on", "passToAgent" not in tap
      and tap["actions"][0]["buttons"][0][0]["text"] == "Expired", tap)
check("synthetic tap for a stale hold -> dropped (handled)", sc_dispatch.handle_dispatch(
      {"text": "callback_data: sc:hold:e:999", "chatId": CHAT}, conn, at(13, 3)) == {"handled": True})
sc_dispatch.handle_dispatch({"text": "first", "chatId": CHAT}, conn, at(13, 10))
first = route_entry.get_hold(CHAT)["id"]
sc_dispatch.handle_dispatch({"text": "second", "chatId": CHAT}, conn, at(13, 11))
check("a newer held message replaces the older hold", route_entry.get_hold(CHAT)["text"] == "second")
check("the older hold's tap -> Expired", sc_dispatch.handle_callback(
      {"payload": f"hold:e:{first}", "chatId": CHAT}, conn, at(13, 12))["actions"][0]["buttons"][0][0]["text"] == "Expired")
os.environ[tg.FAKE_ENV] = str(TMP)  # a directory: sends raise
out = sc_dispatch.handle_dispatch({"text": "late again", "chatId": CHAT, "sessionKey": "k8"}, conn, at(13, 20))
os.environ[tg.FAKE_ENV] = str(FAKE)
inj = sc_dispatch.handle_inject({"sessionKey": "k8", "chatId": CHAT}, conn, at(13, 20))
check("hold send fails -> coach asks in text (ASK route, D44 fallback)", out == {"handled": False}
      and "ASK session=morning" in inj["prependContext"] and route_entry.get_hold(CHAT) is None, inj)
check("passthrough /commands record nothing", sc_dispatch.handle_dispatch({"text": "/new", "chatId": CHAT}, conn, at(13, 30)) == {"handled": False})

# --- write / skip / card taps, commands ---------------------------------------------------------
route_entry.clear_hold(CHAT)
out = sc_dispatch.handle_callback({"payload": f"write:morning:{pm}", "chatId": CHAT}, conn, at(13, 40))
check("✍️ Write -> 'Go ahead' + pending write", out["actions"][0]["text"].startswith("Go ahead")
      and tg.get_pending(CHAT, now=at(13, 41))["kind"] == "write:morning", out)
sc_dispatch.handle_dispatch({"text": "Late but here?", "chatId": CHAT, "sessionKey": "k9"}, conn, at(13, 45))
check("text after Write -> entry directly (no hold), slot cleared",
      conn.execute("SELECT route, source FROM route_events ORDER BY id DESC LIMIT 1").fetchone() == ("entry", "write")
      and tg.get_pending(CHAT, now=at(13, 46)) is None)
tg.write_state({**tg.read_state(), "awaiting_response": True, "session": "morning", "prompt_sent_at": at(7, 30).isoformat()})
out = sc_dispatch.handle_callback({"payload": f"skip:morning:{pm}", "chatId": CHAT}, conn, at(14))
check("Skip -> '✓ Skipped today' + Check in kept", [[b["text"] for b in r] for r in out["actions"][0]["buttons"]]
      == [["✓ Skipped today"], ["🙂 Check in"]], out)
check("skip recorded + legacy awaiting cleared", prompts.get(conn, pm)["skipped_at"] and not tg.read_state()["awaiting_response"])
check("after skip -> conversation", route_entry.decide(conn, chat_id=CHAT, text="hi", now=at(14, 5))["route"] == "conversation")
out = sc_dispatch.handle_callback({"payload": "card:20261008", "chatId": CHAT}, conn, at(14))
check("Check in -> card reply with exact 2x5 rows", out["actions"][0]["type"] == "reply"
      and out["actions"][0]["buttons"][1][0]["callback_data"] == "sc:mood:6:20261008" and len(out["actions"][0]["buttons"][0]) == 5, out)
check("old prompt's Check in -> expired", "expired" in sc_dispatch.handle_callback(
      {"payload": "card:20261007", "chatId": CHAT}, conn, at(14))["actions"][0]["text"])
out = sc_dispatch.handle_command({"command": "journal", "chatId": f"telegram:{CHAT}"}, conn, at(15))
check("/journal -> current session (no morning entry, no evening prompt -> morning)",
      "morning prep" in out["reply"]["text"] and tg.get_pending(CHAT, now=at(15))["kind"] == "write:morning", out)
check("/skip with nothing open", "Nothing to skip" in sc_dispatch.handle_command({"command": "skip", "chatId": CHAT}, conn, at(15))["reply"]["text"])

# --- send_prompt -------------------------------------------------------------------------------
env = {**os.environ, "HOME": str(HOME), tg.FAKE_ENV: str(FAKE)}
hdb = HOME / ".openclaw" / "stoic" / "stoic_journal.db"
with sqlite3.connect(hdb) as c:
    c.executescript(schema)
subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(hdb), "--no-backup"], check=True, capture_output=True)
r = subprocess.run([sys.executable, str(REPO / "send_prompt.py"), "--session", "evening"], input="🌙 Evening review\n\nHow was it?",
                   capture_output=True, text=True, env=env)
hc = sqlite3.connect(hdb)
pr = hc.execute("SELECT id, session, message_id FROM prompt_events").fetchall()
check("send_prompt -> NO_REPLY + prompt row with message id", r.stdout.strip() == "NO_REPLY" and len(pr) == 1
      and pr[0][1] == "evening" and pr[0][2], r.stdout + r.stderr)
check("ui_messages prompt_evening recorded", hc.execute("SELECT kind, ref_id FROM ui_messages").fetchall() == [("prompt_evening", pr[0][0])])
a = sent()[-1]
vals = [b["value"] for blk in json.loads(a[a.index("--presentation") + 1])["blocks"] for b in blk["buttons"]]
check("buttons carry the prompt id; evening Check in when no mood", vals[:2] == [f"sc:write:evening:{pr[0][0]}", f"sc:skip:evening:{pr[0][0]}"]
      and vals[2].startswith("sc:card:"), vals)
r = subprocess.run([sys.executable, str(REPO / "send_prompt.py"), "--session", "morning"], input="☀️ Morning prep\n\nGo",
                   capture_output=True, text=True, env={**env, tg.FAKE_ENV: str(TMP)})
check("failed send -> prints the prompt text (D51)", r.returncode == 0 and r.stdout.startswith("☀️ Morning prep"), r.stdout + r.stderr)
r = subprocess.run([sys.executable, str(REPO / "send_prompt.py"), "--session", "morning"], input="t",
                   capture_output=True, text=True, env={**env, "STOICLIFE_SKIP_PROMPT_STATE": "1"})
check("test mode -> sends but records nothing", r.stdout.strip() == "NO_REPLY" and
      hc.execute("SELECT COUNT(*) FROM prompt_events").fetchone()[0] == 2)  # 1 + the failed-send row

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
