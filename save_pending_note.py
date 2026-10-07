#!/usr/bin/env python3
"""FEAT-07: save the message that answers a pending "type something" prompt.

Two pending kinds (set by sc_dispatch, 2h expiry, one slot per chat):
  fb_more:<r|t><id>          👎 → "Tell me more"   → response_feedback.note  (P2.4)
  note:<mood|module>:<day>   "📝 Add a note"     → checkin_events.note     (P3-D7)

The coach runs this FIRST on every message without a journal prefix
(AGENTS.md §1 step 0) until Phase 4's route_entry.py takes over:

    printf '%s' "<message>" | python3 save_pending_note.py --text-stdin

Prints SAVED (note stored, pending cleared; the agent sends a short ack only) or
NONE (nothing pending; handle the message as usual). Never fails loudly: any error
prints NONE so a normal message is never swallowed.
"""
from __future__ import annotations

import argparse
import re
import sys

import checkins
import tg

PENDING_RE = re.compile(r"^fb_more:([rt])(\d+)$")
NOTE_RE = re.compile(r"^note:(mood|module):(\d{8})$")


def save_note(text: str, chat_id: str | None = None, conn=None, state_path=None) -> bool:
    pending = tg.get_pending(chat_id, path=state_path)
    kind_s = (pending or {}).get("kind") or ""
    if not text.strip():
        return False
    n = NOTE_RE.match(kind_s)
    if n:
        ctype, tag = n.groups()
        day = f"{tag[:4]}-{tag[4:6]}-{tag[6:]}"
        conn = conn or tg.db_connect()
        chat = str(chat_id or checkins.coach_config()["chat_id"])
        with conn:
            ok = checkins.set_note(conn, chat, day, ctype, text)
        tg.clear_pending(chat_id, path=state_path)
        tg.log("INFO" if ok else "WARNING",
               f"save_pending_note: {ctype} note on {day} {'saved' if ok else 'had no check-in'}")
        return ok
    m = PENDING_RE.match(kind_s)
    if not m:
        return False
    kind, target_id = m.group(1), int(m.group(2))
    conn = conn or tg.db_connect()
    with conn:
        cur = conn.execute("UPDATE response_feedback SET note = ? WHERE target_kind = ? "
                           "AND target_id = ?", (text.strip(), kind, target_id))
    if cur.rowcount == 0:
        tg.log("WARNING", f"save_pending_note: no feedback row for {kind}{target_id}; pending cleared")
        tg.clear_pending(chat_id, path=state_path)
        return False
    tg.clear_pending(chat_id, path=state_path)
    tg.log("INFO", f"save_pending_note: note saved on {kind}{target_id} ({len(text.strip())} chars)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text-stdin", action="store_true", required=True)
    ap.add_argument("--chat-id")
    args = ap.parse_args()
    try:
        saved = save_note(sys.stdin.read(), args.chat_id)
    except Exception as exc:
        tg.log("ERROR", f"save_pending_note: {type(exc).__name__}: {exc}")
        saved = False
    print("SAVED" if saved else "NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
