#!/usr/bin/env python3
"""FEAT-07 P2.4: save a "Tell me more" answer as the note on a 👎 rating.

After a 👎 → "Tell me more" tap, sc_dispatch sets pending state `fb_more:<r|t><id>`
(2h). The coach runs this FIRST on every message without a journal prefix
(AGENTS.md §1 step 0) until Phase 4's route_entry.py takes over (P2-D10):

    printf '%s' "<message>" | python3 save_feedback_note.py --text-stdin

Prints SAVED (note stored, pending cleared; the agent sends a short ack only) or
NONE (nothing pending; handle the message as usual). Never fails loudly: any error
prints NONE so a normal message is never swallowed.
"""
from __future__ import annotations

import argparse
import re
import sys

import tg

PENDING_RE = re.compile(r"^fb_more:([rt])(\d+)$")


def save_note(text: str, chat_id: str | None = None, conn=None, state_path=None) -> bool:
    pending = tg.get_pending(chat_id, path=state_path)
    m = PENDING_RE.match((pending or {}).get("kind") or "")
    if not m or not text.strip():
        return False
    kind, target_id = m.group(1), int(m.group(2))
    conn = conn or tg.db_connect()
    with conn:
        cur = conn.execute("UPDATE response_feedback SET note = ? WHERE target_kind = ? "
                           "AND target_id = ?", (text.strip(), kind, target_id))
    if cur.rowcount == 0:
        tg.log("WARNING", f"save_feedback_note: no feedback row for {kind}{target_id}; pending cleared")
        tg.clear_pending(chat_id, path=state_path)
        return False
    tg.clear_pending(chat_id, path=state_path)
    tg.log("INFO", f"save_feedback_note: note saved on {kind}{target_id} ({len(text.strip())} chars)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text-stdin", action="store_true", required=True)
    ap.add_argument("--chat-id")
    args = ap.parse_args()
    try:
        saved = save_note(sys.stdin.read(), args.chat_id)
    except Exception as exc:
        tg.log("ERROR", f"save_feedback_note: {type(exc).__name__}: {exc}")
        saved = False
    print("SAVED" if saved else "NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
