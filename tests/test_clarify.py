#!/usr/bin/env python3
"""MIN-132 — the CLARIFY 🧭 question with Yes/No buttons and its routed answer:
clarify.py (send, pending, answer), route_entry 0b/4b, sc_dispatch tap + dispatch + inject,
the outbound guard and the CLI. Scratch DB, temp state/log, fake sender: nothing live is touched.
Run: python3 tests/test_clarify.py
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
import clarify  # noqa: E402
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


TMP = Path(tempfile.mkdtemp(prefix="min132-"))
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
    r = subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(db), "--no-backup"],
                       capture_output=True, text=True)
    return sqlite3.connect(db), r


def at(h, m=0, day=8):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def sent():
    return [json.loads(l)["args"] for l in FAKE.read_text().splitlines()] if FAKE.exists() else []


def button_values(args):
    return [b["value"] for blk in json.loads(args[args.index("--presentation") + 1])["blocks"] for b in blk["buttons"]]


def event(conn, sent_flag=0):
    deltas = {"hrv_delta_pct": 9.3, "sleep_today_min": 348}
    with conn:
        cur = conn.execute(
            "INSERT INTO trigger_events (eval_datetime, date, session, state, deltas_json, confidence, "
            "fired, message_sent) VALUES (?, '2026-10-08', 'evening', 'running_on_fumes', ?, 40, 1, ?)",
            (at(21).isoformat(), json.dumps(deltas), sent_flag))
    return cur.lastrowid


def tap(cid, choice, now, chat=CHAT):
    return sc_dispatch.handle_callback({"payload": f"clar:{cid}:{choice}", "chatId": chat}, conn, now)


def dispatch(text, now, key="agent:coach:main"):
    return sc_dispatch.handle_dispatch({"text": text, "chatId": CHAT, "sessionKey": key}, conn, now)


def inject(now, key="agent:coach:main"):
    return sc_dispatch.handle_inject({"sessionKey": key, "chatId": CHAT}, conn, now)["prependContext"]


def status(out):
    return out["actions"][0]["buttons"][0][0]["text"]


conn, r = fresh(TMP / "c.db")
check("migration 004 applies on a fresh DB", "004_clarify_prompts.sql" in r.stdout, r.stdout + r.stderr)

# --- answers ---------------------------------------------------------------------------------
for t in ("Yes", "yes!", "  YES please ", "Yep.", "ok", "send it"):
    check(f"parse_answer({t!r}) -> yes", clarify.parse_answer(t) == "yes")
for t in ("No", "no thanks", "Not now."):
    check(f"parse_answer({t!r}) -> no", clarify.parse_answer(t) == "no")
for t in ("yes, but why am I tired?", "👍", "Thanks", "maybe"):
    check(f"parse_answer({t!r}) -> None", clarify.parse_answer(t) is None)

# --- send -----------------------------------------------------------------------------------
e1 = event(conn)
cid = clarify.send(conn, e1, chat_id=CHAT, now=at(21))
a = sent()[-1]
check("send: 🧭 question in Telegram bold, audible", a[a.index("--message") + 1].startswith("🧭 stoiclife")
      and "**Running on Fumes**" in a[a.index("--message") + 1] and "--silent" not in a, a)
check("send: Yes/No buttons carry the clarify id", button_values(a) == [f"sc:clar:{cid}:y", f"sc:clar:{cid}:n"], a)
check("send: ui_messages kind=clarify", conn.execute("SELECT kind, ref_id FROM ui_messages").fetchall() == [("clarify", cid)])
check("pending: open right after sending", clarify.pending(conn, CHAT, at(21, 1))["id"] == cid)
check("pending: expired after 12h", clarify.pending(conn, CHAT, at(9, 1, day=9)) is None)
n = len(sent())
check("send: an event that already has its full read -> nothing sent",
      clarify.send(conn, event(conn, sent_flag=1), chat_id=CHAT, now=at(21)) is None and len(sent()) == n)

# --- tap Yes -> coach gets CLARIFY_YES -------------------------------------------------------
out = tap(cid, "y", at(21, 3))
check("tap Yes -> '✓ Full read coming' + passed to the coach", status(out) == "✓ Full read coming"
      and out.get("passToAgent") is True, out)
check("tap Yes recorded (yes, button)", clarify.get(conn, cid)["answer"] == "yes"
      and clarify.get(conn, cid)["answer_source"] == "button")
check("synthetic tap message -> clarify route, not handled", dispatch(f"callback_data: sc:clar:{cid}:y", at(21, 3)) == {"handled": False})
check("clarify row linked to its route", clarify.get(conn, cid)["route_id"] is not None)
line = inject(at(21, 3))
check("route line: CLARIFY_YES with the event id, no stoiclife_run", f"CLARIFY_YES event={e1}" in line
      and "§1b" in line and "Don't run stoiclife_run.py" in line, line)
check("same synthetic tap again -> stale, dropped", dispatch(f"callback_data: sc:clar:{cid}:y", at(21, 4)) == {"handled": True})
check("tap Yes twice -> '✓ Already answered', not passed on", status(tap(cid, "y", at(21, 4))) == "✓ Already answered"
      and "passToAgent" not in tap(cid, "y", at(21, 4)))
with conn:
    conn.execute("UPDATE trigger_events SET message_sent = 1 WHERE id = ?", (e1,))
check("after record_coaching --send -> '✓ Full read sent'", status(tap(cid, "n", at(21, 6))) == "✓ Full read sent")

# --- tap No ---------------------------------------------------------------------------------
cid2 = clarify.send(conn, event(conn), chat_id=CHAT, now=at(21, 10))
out = tap(cid2, "n", at(21, 11))
check("tap No -> '✓ No full read', no coach turn", status(out) == "✓ No full read" and "passToAgent" not in out, out)
check("after No, a typed 'yes' is just conversation", route_entry.decide(conn, chat_id=CHAT, text="yes", now=at(21, 12))["route"] == "conversation")

# --- typed answers --------------------------------------------------------------------------
e3 = event(conn)
cid3 = clarify.send(conn, e3, chat_id=CHAT, now=at(21, 20))
check("typed 'yes, but why?' -> conversation (whole-message answers only)",
      route_entry.decide(conn, chat_id=CHAT, text="yes, but why?", now=at(21, 21))["route"] == "conversation")
check("typed 'Yes!' -> clarify route", dispatch("Yes!", at(21, 22), key="k3") == {"handled": False}
      and clarify.get(conn, cid3)["answer_source"] == "typed")
check("typed yes -> CLARIFY_YES route line", f"CLARIFY_YES event={e3}" in inject(at(21, 22), key="k3"))
cid4 = clarify.send(conn, event(conn), chat_id=CHAT, now=at(21, 30))
check("typed 'no thanks' -> answered here", dispatch("no thanks", at(21, 31)) == {"handled": True, "text": "OK, no full read."}
      and clarify.get(conn, cid4)["answer"] == "no")
check("old question's Yes after a typed no -> '✓ Already answered'", status(tap(cid4, "y", at(21, 32))) == "✓ Already answered")

# --- stale / foreign -------------------------------------------------------------------------
cid5 = clarify.send(conn, event(conn), chat_id=CHAT, now=at(8))
check("tap after 12h -> Expired", status(tap(cid5, "y", at(21, 0))) == "Expired")
check("tap from another chat -> Expired", status(tap(cid5, "y", at(9), chat="123")) == "Expired")
check("unknown id -> Expired", status(tap(9999, "y", at(9))) == "Expired")

# --- outbound guard: clarify.py counts as a script send --------------------------------------
tools = [{"command": f"python3 {REPO}/clarify.py --event-id 241", "output": "NO_REPLY", "error": None}]
check("narration after clarify.py -> cancelled", sc_dispatch.handle_outbound(
      {"text": "Sent the question.", "tools": tools}) == {"cancel": "script_sent"})

# --- CLI ------------------------------------------------------------------------------------
env = {**os.environ, "HOME": str(HOME), tg.FAKE_ENV: str(FAKE)}
hdb = HOME / ".openclaw" / "stoic" / "stoic_journal.db"
hc, _ = fresh(hdb)
he = event(hc)
r = subprocess.run([sys.executable, str(REPO / "clarify.py"), "--event-id", str(he), "--db", str(hdb),
                    "--chat-id", CHAT], capture_output=True, text=True, env=env)
check("CLI -> NO_REPLY + a clarify_prompts row", r.stdout.strip() == "NO_REPLY"
      and hc.execute("SELECT COUNT(*) FROM clarify_prompts WHERE event_id = ?", (he,)).fetchone()[0] == 1,
      r.stdout + r.stderr)
r = subprocess.run([sys.executable, str(REPO / "clarify.py"), "--event-id", "424242", "--db", str(hdb),
                    "--chat-id", CHAT], capture_output=True, text=True, env=env)
check("CLI with an unknown event -> exit 1, nothing printed on stdout", r.returncode == 1 and not r.stdout.strip(), r.stdout)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
