#!/usr/bin/env python3
"""Voice journal entries: routing of `<media:audio>` and the transcript swap at injection.

OpenClaw transcribes a voice note *after* before_dispatch, so route_entry only sees the
placeholder; sc_dispatch.handle_inject takes the transcript from the prompt OpenClaw built.
Scratch DB, temp state, fake sender: nothing live is touched. Run: python3 tests/test_voice.py
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import checkins  # noqa: E402
import prompts  # noqa: E402
import route_entry  # noqa: E402
import sc_dispatch  # noqa: E402
import tg  # noqa: E402
from _tz import TZ  # noqa: E402

failures = total = 0


def check(label, ok, detail=""):
    global failures, total
    total += 1
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f"  {detail!r}"))


TMP = Path(tempfile.mkdtemp(prefix="voice-"))
tg.LOG_PATH = TMP / "stoic.log"
tg.STATE_PATH = TMP / "state.json"
os.environ[tg.FAKE_ENV] = str(TMP / "sent.jsonl")
CHAT = "8917837483"
VOICE = "<media:audio>"
# the real prompt tail from the 2026-10-09 probe
PROMPT = ('[stoiclife route #17] …\n\n[media attached: media://inbound/x.ogg (audio/ogg)]\n'
          'To send an image back, use the message tool.\n'
          '[Audio transcript (machine-generated, untrusted)]: "Testing voice notes. Mood seven."')

schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))
DB = TMP / "v.db"
with sqlite3.connect(DB) as c:
    c.executescript(schema)
subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(DB), "--no-backup"],
               capture_output=True, text=True, check=True)
conn = sqlite3.connect(DB)


def at(h, m=0, day=8):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def route(text, now):
    return route_entry.decide(conn, chat_id=CHAT, text=text, now=now)


tg.write_state({})

# --- transcript parsing ----------------------------------------------------------------------
check("transcript from the real prompt", sc_dispatch.transcript_from(PROMPT) == "Testing voice notes. Mood seven.")
check("multi-line transcript keeps its lines",
      sc_dispatch.transcript_from('x\n[Audio transcript (machine-generated, untrusted)]: "Line one.\nLine two."')
      == "Line one.\nLine two.")
check("no transcript -> None", sc_dispatch.transcript_from("just text") is None)
check("empty transcript -> None", sc_dispatch.transcript_from('[Audio transcript (x)]: ""') is None)
check("is_voice: placeholder only", route_entry.is_voice(" <media:audio> ") and not route_entry.is_voice("hello"))

# --- routing ---------------------------------------------------------------------------------
check("no prompt open -> conversation", route(VOICE, at(7, 0))["route"] == "conversation")
with conn:
    pm = prompts.record(conn, chat_id=CHAT, session="morning", message_id="300", now=at(7, 30))
d = route(VOICE, at(8))
check("in the window -> morning entry", d["route"] == "entry" and d["session"] == "morning" and d["prompt_id"] == pm, d)
d = route(VOICE, at(13))
check("past the window -> ask_text, never a hold (a hold is never transcribed)",
      d["route"] == "ask_text" and d["session"] == "morning", d)
check("typed text past the window still holds", route("Lunch was good", at(13))["route"] == "hold")
tg.set_pending("fb_more:t5", chat_id=CHAT)
d = route(VOICE, at(8))
check("pending 'Tell me more' -> not a note (falls through to the window)", d["route"] == "entry", d)
check("typed text is still the note", route("tired", at(8))["route"] == "note")
tg.clear_pending(CHAT)
tg.set_pending("write:morning", chat_id=CHAT, expires_at=at(10))
check("✍️ write slot -> entry", route(VOICE, at(9))["source"] == "write")

# --- dispatch + inject -----------------------------------------------------------------------
out = sc_dispatch.handle_dispatch({"text": VOICE, "chatId": CHAT, "sessionKey": "k1"}, conn, at(9))
check("dispatch: not handled (goes to the coach to be transcribed)", out == {"handled": False}, out)
check("dispatch: the write slot is used up", tg.get_pending(CHAT, now=at(9)) is None)
row = conn.execute("SELECT route, source, text FROM route_events ORDER BY id DESC LIMIT 1").fetchone()
check("dispatch: recorded as entry, source voice, placeholder text", row == ("entry", "voice", VOICE), row)

inj = sc_dispatch.handle_inject({"sessionKey": "k1", "chatId": CHAT, "prompt": PROMPT}, conn, at(9))["prependContext"]
check("inject: ENTRY line carries the transcript", "ENTRY session=morning source=voice" in inj
      and "<<<\nTesting voice notes. Mood seven.\n>>>" in inj and VOICE not in inj, inj)
row = conn.execute("SELECT text FROM route_events ORDER BY id DESC LIMIT 1").fetchone()
check("inject: route_events.text now holds the transcript", row[0] == "Testing voice notes. Mood seven.", row)

sc_dispatch.handle_dispatch({"text": VOICE, "chatId": CHAT, "sessionKey": "k2"}, conn, at(9, 30))
inj = sc_dispatch.handle_inject({"sessionKey": "k2", "chatId": CHAT, "prompt": "no transcript here"}, conn,
                                at(9, 30))["prependContext"]
check("inject without a transcript: told not to save, ask him to retype", "VOICE NOT TRANSCRIBED" in inj
      and "Don't save" in inj and "ENTRY" not in inj, inj)

sc_dispatch.handle_dispatch({"text": "Typed entry.", "chatId": CHAT, "sessionKey": "k3"}, conn, at(9, 40))
inj = sc_dispatch.handle_inject({"sessionKey": "k3", "chatId": CHAT, "prompt": PROMPT}, conn, at(9, 40))["prependContext"]
check("typed entry: a transcript-like prompt never replaces typed text",
      "<<<\nTyped entry.\n>>>" in inj and "source=window" in inj, inj)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
