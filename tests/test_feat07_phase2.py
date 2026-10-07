#!/usr/bin/env python3
"""FEAT-07 Phase 2 — feedback buttons: send_coaching (stdin, data flags),
record_coaching --send, sc_dispatch fb/fbr/noop, save_pending_note, record_feedback.

Scratch DB + scratch config + temp HOME; sends go to a fake (STOICLIFE_TG_FAKE), so
nothing reaches Telegram, the live DB, the live log or the live state.json.
Run: python3 tests/test_feat07_phase2.py
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
import record_feedback  # noqa: E402
import save_pending_note  # noqa: E402
import sc_dispatch  # noqa: E402
import tg  # noqa: E402
from _tz import TZ  # noqa: E402
from tests.test_channel_fmt import TG_MSG  # noqa: E402  (a valid Telegram strict-format push)

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


TMP = Path(tempfile.mkdtemp(prefix="feat07p2-"))
HOME = TMP / "home"
(HOME / ".openclaw" / "stoic").mkdir(parents=True)
(HOME / ".openclaw" / "workspace").mkdir()
os.symlink(SCRIPTS, HOME / ".openclaw" / "workspace" / "scripts")
tg.LOG_PATH = TMP / "stoic.log"
tg.STATE_PATH = TMP / "state.json"
FAKE = TMP / "sent.jsonl"
CHAT = "8917837483"

DB = TMP / "j.db"
schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
# sqlite_sequence appears once AUTOINCREMENT tables exist; it can't be created by hand.
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))
with sqlite3.connect(DB) as c:
    c.executescript(schema)
subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(DB), "--no-backup"],
               check=True, capture_output=True)
cfg = json.loads((REPO / "stoiclife_config.json").read_text())
cfg["db_path"] = str(DB)
CFG = TMP / "config.json"
CFG.write_text(json.dumps(cfg))
sc_dispatch.REACTION_CONFIG = CFG

ENV = {**os.environ, "HOME": str(HOME), tg.FAKE_ENV: str(FAKE)}


def run(script, *args, stdin="", env=None):
    return subprocess.run([sys.executable, str(REPO / script), *args], input=stdin,
                          capture_output=True, text=True, env=env or ENV)


def fake_sends():
    return [json.loads(l)["args"] for l in FAKE.read_text().splitlines()] if FAKE.exists() else []


conn = sqlite3.connect(DB)
now = datetime.now(TZ)
with conn:
    e = conn.execute("INSERT INTO journal_entries (date, session, raw_response, created_at) "
                     "VALUES ('2026-10-08', 'morning', 'x', ?)", (now.isoformat(),)).lastrowid
    ev = conn.execute("INSERT INTO trigger_events (eval_datetime, date, session, state, confidence, "
                      "fired, status_signal) VALUES (?, '2026-10-08', 'morning', 'neutral', 55, 0, "
                      "'all_ok')", (now.isoformat(),)).lastrowid
    ev2 = conn.execute("INSERT INTO trigger_events (eval_datetime, date, session, state, confidence, "
                       "fired) VALUES (?, '2026-10-08', 'safety-net', 'running_on_fumes', 80, 1)",
                       (now.isoformat(),)).lastrowid

# --- P2.1 send_coaching --kind r -------------------------------------------------
r = run("send_coaching.py", "--kind", "r", "--entry-id", str(e), "--session", "morning",
        "--text-stdin", "--db", str(DB), stdin="Steady day. **Hold the line.** 🟢 *stoiclife:* all ok\n")
check("send r prints NO_REPLY", r.returncode == 0 and r.stdout.strip() == "NO_REPLY", r.stdout + r.stderr)
row = conn.execute("SELECT id, entry_id, session, text, telegram_message_id, data_flags_json "
                   "FROM coaching_responses").fetchone()
check("coaching_responses row stored with text from stdin",
      row and row[1] == e and row[2] == "morning" and row[3].startswith("Steady day. **Hold"), row)
check("telegram_message_id stored", row and row[4] == "90000", row)
flags = json.loads(row[5]) if row and row[5] else {}
check("data_flags_json filled from the entry's trigger_events (P2-D11)",
      flags.get("event_id") == ev and flags.get("state") == "neutral"
      and flags.get("status_signal") == "all_ok", flags)
ui = conn.execute("SELECT message_id, kind, ref_id, session FROM ui_messages").fetchall()
check("ui_messages coaching_r recorded", ui == [("90000", "coaching_r", row[0], "morning")], ui)
sent = fake_sends()[-1]
pres = json.loads(sent[sent.index("--presentation") + 1])
vals = [b["value"] for blk in pres["blocks"] for b in blk["buttons"]]
check("r message carries 👍/👎 buttons", vals == [f"sc:fb:r{row[0]}:up", f"sc:fb:r{row[0]}:down"], vals)
check("message text passed verbatim", sent[sent.index("--message") + 1].startswith("Steady day."))
R1 = row[0]

# --- P2.2 record_coaching --send ----------------------------------------------------
n_before = len(fake_sends())
r = run("record_coaching.py", "--event-id", str(ev2), "--channel", "telegram", "--send",
        "--config", str(CFG), stdin=TG_MSG)
tc = conn.execute("SELECT id, valid FROM trigger_coaching ORDER BY id DESC LIMIT 1").fetchone()
check("--send valid -> NO_REPLY only on stdout", r.returncode == 0 and r.stdout.strip() == "NO_REPLY",
      r.stdout + r.stderr)
check("--send stored the push", tc and tc[1] == 1, tc)
check("--send delivered once with t buttons", len(fake_sends()) == n_before + 1
      and f"sc:fb:t{tc[0]}:up" in fake_sends()[-1][fake_sends()[-1].index("--presentation") + 1])
check("event marked sent", conn.execute("SELECT message_sent FROM trigger_events WHERE id=?",
                                        (ev2,)).fetchone()[0] == 1)
T1 = tc[0]
n_before = len(fake_sends())
r = run("record_coaching.py", "--event-id", str(ev2), "--channel", "telegram", "--send",
        "--config", str(CFG), stdin="not the strict format")
check("--send invalid -> exit 2, nothing sent", r.returncode == 2 and len(fake_sends()) == n_before)
r = run("record_coaching.py", "--event-id", str(ev2), "--channel", "telegram", "--send", "--force",
        "--config", str(CFG), stdin="not the strict format")
check("--send --force invalid -> stored but never sent", r.returncode == 2 and len(fake_sends()) == n_before)
with conn:
    conn.execute("UPDATE trigger_events SET message_sent = 0 WHERE id = ?", (ev2,))
bad_env = {**ENV, tg.FAKE_ENV: str(TMP)}  # a directory: the fake send raises
r = run("record_coaching.py", "--event-id", str(ev2), "--channel", "telegram", "--send",
        "--config", str(CFG), stdin=TG_MSG, env=bad_env)
check("--send failure -> exit 3", r.returncode == 3, r.stdout + r.stderr)
check("--send failure resets message_sent to 0", conn.execute(
      "SELECT message_sent FROM trigger_events WHERE id=?", (ev2,)).fetchone()[0] == 0)
r = run("record_coaching.py", "--event-id", str(ev2), "--channel", "telegram",
        "--config", str(CFG), stdin=TG_MSG)
check("without --send: unchanged behaviour (stored line, no send)",
      r.returncode == 0 and r.stdout.startswith("stored coaching id="), r.stdout)

# --- P2.3 sc_dispatch feedback ----------------------------------------------------------
def tap(payload, mid=1):
    return sc_dispatch.handle_callback({"payload": payload, "chatId": CHAT, "messageId": mid,
                                        "messageText": "coaching"}, conn, datetime.now(TZ))


def fb(kind, tid):
    return conn.execute("SELECT rating, reason, note FROM response_feedback WHERE target_kind=? "
                        "AND target_id=?", (kind, tid)).fetchall()


out = tap(f"fb:r{R1}:up")
check("👍 r -> status button, text untouched (P2-D5)", out == {"actions": [{"type": "editButtons",
      "buttons": [[{"text": "✓ Noted 👍", "callback_data": "sc:noop"}]]}]}, out)
check("👍 r stored", fb("r", R1) == [("up", None, None)], fb("r", R1))
out = tap(f"fb:r{R1}:down")
rows = out["actions"][0]["buttons"]
check("👎 r -> 2x2 reason rows", out["actions"][0]["type"] == "editButtons" and
      [[b["callback_data"] for b in rw] for rw in rows] ==
      [[f"sc:fbr:r{R1}:generic", f"sc:fbr:r{R1}:offbase"], [f"sc:fbr:r{R1}:long", f"sc:fbr:r{R1}:more"]], rows)
check("👎 re-tap updates the same row", fb("r", R1) == [("down", None, None)], fb("r", R1))
out = tap(f"fbr:r{R1}:generic")
check("reason -> '✓ Noted: Too generic'", out["actions"][0]["buttons"][0][0]["text"] == "✓ Noted: Too generic", out)
check("reason stored", fb("r", R1) == [("down", "generic", None)], fb("r", R1))
tap(f"fb:r{R1}:down")
check("👎 again keeps the reason", fb("r", R1) == [("down", "generic", None)], fb("r", R1))
tap(f"fb:r{R1}:up")
check("👍 after 👎 clears the reason", fb("r", R1) == [("up", None, None)], fb("r", R1))
check("still one feedback row per target",
      conn.execute("SELECT COUNT(*) FROM response_feedback WHERE target_kind='r'").fetchone()[0] == 1)

tap(f"fb:t{T1}:up")
check("👍 t -> trigger_coaching/events usefulness +1", conn.execute(
      "SELECT c.usefulness, e.usefulness FROM trigger_coaching c JOIN trigger_events e "
      "ON e.id = c.event_id WHERE c.id=?", (T1,)).fetchone() == (1, 1))
out = tap(f"fbr:t{T1}:more", mid=777)
check("Tell me more -> asks the question", {"type": "reply", "text": "What would have been more useful?"}
      in out["actions"], out)
check("Tell me more -> usefulness -1", conn.execute(
      "SELECT usefulness FROM trigger_coaching WHERE id=?", (T1,)).fetchone()[0] == -1)
pend = tg.get_pending(CHAT)
check("Tell me more -> pending fb_more:t<id>, ~2h", pend and pend["kind"] == f"fb_more:t{T1}"
      and pend["message_id"] == "777"
      and timedelta(minutes=115) < datetime.fromisoformat(pend["expires_at"]) - datetime.now(TZ)
      <= timedelta(hours=2), pend)
check("unknown target -> buttons cleared, nothing stored",
      tap("fb:r9999:up") == {"actions": [{"type": "clearButtons"}]} and fb("r", 9999) == [])
check("noop -> nothing", tap("noop") == {"actions": []})

# --- P2.4 save_pending_note ------------------------------------------------------------
check("note saved while fb_more pending", save_pending_note.save_note("Name the trade-off.", CHAT, conn))
check("note stored on the t rating", fb("t", T1) == [("down", "more", "Name the trade-off.")], fb("t", T1))
check("pending cleared after the note", tg.get_pending(CHAT) is None)
check("next message -> NONE (normal handling)", not save_pending_note.save_note("hello", CHAT, conn))
tg.set_pending(f"fb_more:r{R1}", chat_id=CHAT, expires_at=datetime.now(TZ) - timedelta(minutes=1))
check("expired fb_more -> NONE", not save_pending_note.save_note("late", CHAT, conn))
tg.set_pending("morning", chat_id=CHAT)
check("other pending kind -> NONE", not save_pending_note.save_note("entry", CHAT, conn))
tg.clear_pending(CHAT)
(HOME / ".openclaw" / "stoic" / "state.json").write_text("{}")
r = run("save_pending_note.py", "--text-stdin", stdin="hi")
check("CLI with nothing pending prints NONE", r.returncode == 0 and r.stdout.strip() == "NONE", r.stdout + r.stderr)

# --- P2.5 record_feedback (typed legacy) -------------------------------------------------
with conn:
    conn.execute("DELETE FROM response_feedback")
    conn.execute("UPDATE trigger_coaching SET usefulness = NULL")
    conn.execute("UPDATE ui_messages SET created_at = ? WHERE kind='coaching_r'",
                 ((datetime.now(TZ) - timedelta(minutes=30)).isoformat(),))
hit = record_feedback.latest_target(conn, CHAT)
check("latest unrated target is the newest (t)", hit == ("coaching_t", T1), hit)
rc = record_feedback.main(["--rating", "up", "--reaction", "👍 good one"], conn, CFG)
check("typed 👍 rates t + mirrors usefulness", rc == 0 and fb("t", T1) == [("up", None, "👍 good one")]
      and conn.execute("SELECT usefulness FROM trigger_coaching WHERE id=?", (T1,)).fetchone()[0] == 1)
check("next latest unrated is r", record_feedback.latest_target(conn, CHAT) == ("coaching_r", R1))
record_feedback.main(["--rating", "neutral", "--reaction", "meh"], conn, CFG)
check("typed neutral on r", fb("r", R1) == [("neutral", None, "meh")], fb("r", R1))
with conn:
    conn.execute("UPDATE ui_messages SET created_at = ?", ((datetime.now(TZ) - timedelta(hours=30)).isoformat(),))
    conn.execute("DELETE FROM response_feedback")
check("outside the 18h window -> no button-era target", record_feedback.latest_target(conn, CHAT) is None)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
