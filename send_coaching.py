#!/usr/bin/env python3
"""FEAT-07: send a coaching message with feedback buttons and remember it.

  --kind r  a normal coaching reply: inserts `coaching_responses`, sends the text with
            [👍 Helpful] [👎 Not quite] (sc:fb:r<id>:up|down), stores the message id.
  --kind t  an already-recorded stoiclife push: sends trigger_coaching.coaching_text
            (or --text-file) with sc:fb:t<id>:… buttons.

Both record the message in `ui_messages` and print NO_REPLY on success, so an agent
can relay stdout as its own (silent) reply.

The coach can't write files, so it pipes the text in (P2-D2). For --kind r the
`data_flags_json` is filled from the entry's latest trigger_events row (P2-D11).

    printf '%s' "<reply>" | python3 send_coaching.py --kind r --entry-id 214 --session morning --text-stdin
    python3 send_coaching.py --kind t --target-id 19
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import checkins
import tg


def feedback_buttons(kind: str, target_id: int):
    return [[("👍 Helpful", f"sc:fb:{kind}{target_id}:up"),
             ("👎 Not quite", f"sc:fb:{kind}{target_id}:down")]]


def entry_flags(conn, entry_id: int | None) -> dict | None:
    """The stoiclife verdict behind a reply: the entry's latest trigger_events row (P2-D11)."""
    if not entry_id:
        return None
    row = conn.execute("SELECT date, session FROM journal_entries WHERE id = ?",
                       (entry_id,)).fetchone()
    if not row:
        return None
    ev = conn.execute(
        "SELECT id, state, confidence, fired, cooldown_skipped, held_for_quiet_hours, "
        "status_signal FROM trigger_events WHERE date = ? AND session = ? "
        "ORDER BY id DESC LIMIT 1", row).fetchone()
    if not ev:
        return None
    keys = ("event_id", "state", "confidence", "fired", "cooldown_skipped", "held",
            "status_signal")
    return dict(zip(keys, ev))


def read_text(args) -> str | None:
    if args.text_stdin:
        return sys.stdin.read().strip()
    if args.text_file:
        return Path(args.text_file).read_text().strip()
    if args.text:
        return args.text.strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", required=True, choices=["r", "t"])
    ap.add_argument("--entry-id", type=int)
    ap.add_argument("--session", choices=["morning", "evening", "adhoc"])
    ap.add_argument("--data-flags", help="JSON object of the data flags behind the reply")
    ap.add_argument("--target-id", type=int, help="trigger_coaching.id (kind t)")
    ap.add_argument("--text", help="message text (prefer --text-file: no quoting issues)")
    ap.add_argument("--text-file")
    ap.add_argument("--text-stdin", action="store_true", help="read the message text from stdin")
    ap.add_argument("--chat-id")
    ap.add_argument("--db")
    args = ap.parse_args()

    chat_id = str(args.chat_id or checkins.coach_config()["chat_id"])
    conn = tg.db_connect(args.db)
    text = read_text(args)

    if args.kind == "r":
        if not text:
            ap.error("--kind r needs --text or --text-file")
        flags = json.loads(args.data_flags) if args.data_flags else entry_flags(conn, args.entry_id)
        with conn:
            cur = conn.execute(
                "INSERT INTO coaching_responses (entry_id, chat_id, session, data_flags_json, "
                "text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (args.entry_id, chat_id, args.session, json.dumps(flags) if flags else None,
                 text, checkins.now_local().isoformat()),
            )
            target_id = cur.lastrowid
    else:
        if not args.target_id:
            ap.error("--kind t needs --target-id")
        row = conn.execute("SELECT coaching_text, valid FROM trigger_coaching WHERE id = ?",
                           (args.target_id,)).fetchone()
        if not row:
            print(f"error: trigger_coaching {args.target_id} not found", file=sys.stderr)
            return 1
        if not row[1]:
            print(f"error: trigger_coaching {args.target_id} failed validation; not sending",
                  file=sys.stderr)
            return 1
        target_id = args.target_id
        text = text or row[0]

    try:
        message_id = tg.send(text, feedback_buttons(args.kind, target_id), chat_id=chat_id)
    except Exception as exc:
        tg.log("ERROR", f"send_coaching: send failed kind={args.kind} id={target_id}: {exc}")
        print(f"error: send failed: {exc}", file=sys.stderr)
        return 1

    with conn:
        if args.kind == "r":
            conn.execute("UPDATE coaching_responses SET telegram_message_id = ? WHERE id = ?",
                         (message_id, target_id))
        if message_id:
            tg.record_ui_message(conn, message_id=message_id, kind=f"coaching_{args.kind}",
                                 chat_id=chat_id, ref_id=target_id, session=args.session)
    tg.log("INFO", f"send_coaching: kind={args.kind} id={target_id} message_id={message_id}")
    print("NO_REPLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
