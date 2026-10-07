#!/usr/bin/env python3
"""stoiclife Phase 3 — validate and persist generated coaching text.

Reads the coaching message Ewok generated for a fired event, validates it
against the strict format, and writes it to the trigger_coaching table linked
to the event. An invalid message is rejected (exit 2) unless --force is given
(in which case it is stored with valid=0 and the validation errors, so a retry
can be triggered).

Usage:
    python3 build_payload.py --event-id N | ewok-generate | \
        python3 record_coaching.py --event-id N
    python3 record_coaching.py --event-id N --file message.txt
    python3 record_coaching.py --event-id N --channel telegram   # validate Telegram bold
    printf '%s' "<msg>" | python3 record_coaching.py --event-id N --channel telegram --send

FEAT-07 (P2-D4): --send also delivers a *valid* message to the coach chat with
👍/👎 buttons (send_coaching.py --kind t) and prints only NO_REPLY, so the agent's
own reply is silent. An invalid message is never sent. If delivery fails, the event
is put back to message_sent=0 and the exit code is 3.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import channel_fmt
from coaching_format import validate

from _tz import TZ  # active zone: home, or the trip zone while travel-mode is on
REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(os.path.expanduser(db_path)))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    p = argparse.ArgumentParser(description="Validate + store generated coaching.")
    p.add_argument("--event-id", type=int, required=True)
    p.add_argument("--file", help="read coaching text from a file (default: stdin)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--force", action="store_true",
                   help="store even if invalid (valid=0), instead of rejecting")
    p.add_argument("--channel", choices=channel_fmt.CHANNELS, default=None,
                   help=f"default: ${channel_fmt.ENV_VAR}, else {channel_fmt.DEFAULT_CHANNEL}")
    p.add_argument("--send", action="store_true",
                   help="FEAT-07: also send it with feedback buttons; prints NO_REPLY")
    args = p.parse_args()

    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    text = text.strip()
    if not text:
        print("error: no coaching text provided", file=sys.stderr)
        return 1

    cfg = json.loads(Path(args.config).read_text())
    conn = connect(cfg["db_path"])
    ev = conn.execute("SELECT id, state, fired FROM trigger_events WHERE id = ?",
                      (args.event_id,)).fetchone()
    if ev is None:
        print(f"error: trigger_events id {args.event_id} not found", file=sys.stderr)
        return 1

    # D58: never deliver an event twice. The agent CLI's documented timeout fallback can
    # run an escalation turn a second time; the event's message_sent flag is the guard.
    if args.send:
        sent = conn.execute("SELECT message_sent FROM trigger_events WHERE id = ?",
                            (args.event_id,)).fetchone()
        if sent and sent["message_sent"]:
            print(f"event {args.event_id} already sent; nothing stored or sent", file=sys.stderr)
            print("NO_REPLY")
            return 0

    ok, errors = validate(text, channel_fmt.resolve(args.channel))
    if not ok and not args.force:
        print("rejected — coaching failed format validation:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    conn.execute(
        """
        INSERT INTO trigger_coaching
            (event_id, generated_at, state, coaching_text, valid, validation_errors)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (args.event_id, datetime.now(TZ).isoformat(timespec="seconds"),
         ev["state"], text, int(ok), None if ok else "; ".join(errors)),
    )
    # A valid coaching record means the message is being delivered now — mark the
    # event sent so re-evaluations the same day don't double-send (dedup signal).
    # Delivery also discharges any quiet-hours hold on the event: clear the flag so
    # it doesn't linger as a phantom "still held" row after the message went out.
    if ok:
        conn.execute("UPDATE trigger_events "
                     "SET message_sent = 1, held_for_quiet_hours = 0 WHERE id = ?",
                     (args.event_id,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    stored = f"stored coaching id={cid} for event {args.event_id} (valid={ok})"
    if not args.send:
        conn.close()
        print(stored)
        return 0

    print(stored, file=sys.stderr)
    if not ok:  # --force stored an invalid message: never deliver it
        conn.close()
        print("error: not sending an invalid message", file=sys.stderr)
        return 2
    proc = subprocess.run(
        [sys.executable, str(REPO_DIR / "send_coaching.py"), "--kind", "t",
         "--target-id", str(cid), "--db", cfg["db_path"]],
        capture_output=True, text=True)
    if proc.returncode != 0 or proc.stdout.strip() != "NO_REPLY":
        conn.execute("UPDATE trigger_events SET message_sent = 0 WHERE id = ?", (args.event_id,))
        conn.commit()
        conn.close()
        print(f"error: send failed, event {args.event_id} reset to unsent: "
              f"{(proc.stderr or proc.stdout).strip()[-400:]}", file=sys.stderr)
        return 3
    conn.close()
    print("NO_REPLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
