#!/usr/bin/env python3
"""MIN-127/MIN-128 — sc_dispatch.handle_outbound, the coach's outbound text guard.
Cases are the real leaks from 2026-10-08. Pure function, log redirected to a temp
file: nothing live is touched.
Run: python3 tests/test_outbound_guard.py
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import sc_dispatch  # noqa: E402
import tg  # noqa: E402

tg.LOG_PATH = Path(tempfile.mkdtemp()) / "stoic.log"

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


def out(text, tools=None):
    return sc_dispatch.handle_outbound({"kind": "outbound", "text": text, "tools": tools or []})


SAVE = {"command": "python3 …/save_entry.py --session morning --response \"…\"", "output": "215", "error": None}
SENT = {"command": "printf '%s' \"…\" | python3 /home/mihajlo/projects/stoiclife/send_coaching.py --kind r …",
        "output": "NO_REPLY", "error": None}
RECORDED = {"command": "python3 /home/mihajlo/projects/stoiclife/record_coaching.py --event-id 241 --send",
            "output": "stored coaching id=20 for event 241 (valid=True)\nNO_REPLY", "error": None}
SEND_FAILED = {**SENT, "output": "telegram send failed\n\n(Command exited with code 1)"}
PUSH_FAILED = {**RECORDED, "output": "send failed\n\n(Command exited with code 3)"}
NARRATION = "Now I'll compose and send the coaching text with the happiness module lens."
CLARIFY = ("🧭 stoiclife: I'm seeing a possible **Running on Fumes** pattern today. "
           "Want the full read? Reply **yes** and I'll send the coaching.")

# MIN-128: "Thanks" -> "🧭\n\nNO_REPLY"
check("MIN-128: '🧭\\n\\nNO_REPLY' -> cancelled", out("🧭\n\nNO_REPLY") == {"cancel": "no_words"})
check("a lone emoji -> cancelled", out("🧭") == {"cancel": "no_words"})
check("bare NO_REPLY (OpenClaw drops it anyway) -> cancelled", out("NO_REPLY") == {"cancel": "no_words"})

# MIN-127: narration after a script already sent the coaching
check("MIN-127: narration after send_coaching -> cancelled",
      out(NARRATION, [SAVE, SENT]) == {"cancel": "script_sent"})
check("MIN-127: narration after record_coaching --send -> cancelled",
      out("Now I'll compose and send the full Running on Fumes read.", [RECORDED]) == {"cancel": "script_sent"})
check("CLARIFY 🧭 line after send_coaching -> sent", out(CLARIFY, [SAVE, SENT]) == {})
check("CLARIFY line + trailing NO_REPLY -> NO_REPLY stripped",
      out(CLARIFY + "\n\nNO_REPLY", [SENT]) == {"text": CLARIFY})

# failures must still reach him
check("send_coaching failed -> coach's fallback text sent", out("Here's your coaching…", [SAVE, SEND_FAILED]) == {})
check("module sent, then push exit 3 -> failure line sent",
      out("The full read wasn't delivered.", [SENT, PUSH_FAILED]) == {})

# ordinary conversation untouched
check("plain conversation reply -> sent", out("Glad it helped. Enjoy dinner at your mum's.") == {})
check("conversation after a non-sending tool -> sent", out("Your HRV is up 9% this week.", [SAVE]) == {})
check("empty text -> no decision", out("   ") == {})

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
