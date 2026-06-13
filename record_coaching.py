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
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from coaching_format import validate

TZ = ZoneInfo("Australia/Brisbane")
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

    ok, errors = validate(text)
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
    if ok:
        conn.execute("UPDATE trigger_events SET message_sent = 1 WHERE id = ?",
                     (args.event_id,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()
    print(f"stored coaching id={cid} for event {args.event_id} (valid={ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
