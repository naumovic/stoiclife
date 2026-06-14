#!/usr/bin/env python3
"""stoiclife Phase 5 — capture a usefulness rating for a delivered coaching push.

When Mihajlo replies to a stoiclife message (a 👍/👎, a one-word reply, or a
short sentence), the journal/WhatsApp flow calls this to persist a lightweight
usefulness signal against the `trigger_coaching` row and mirror it onto the
linked `trigger_events.usefulness` field. It does NOT call an LLM — the caller
(the agent) infers the normalized +1/0/-1 from the reply and passes it in.

By default the rating attaches to the most-recent DELIVERED, still-unrated
coaching within `feedback.rating_window_hours`, which is almost always the one
Mihajlo is reacting to. A specific row can be targeted with --coaching-id or
--event-id.

Usage:
    python3 record_reaction.py --usefulness 1  --reaction "👍 spot on"
    python3 record_reaction.py --usefulness -1 --reaction "not really" --event-id 42
    python3 record_reaction.py --list          # show pending-rating pushes
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Brisbane")
REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(os.path.expanduser(db_path)))
    conn.row_factory = sqlite3.Row
    return conn


def pending(conn) -> list[sqlite3.Row]:
    """Delivered (valid + sent), not-yet-rated coaching, newest first."""
    return conn.execute(
        """
        SELECT c.id, c.event_id, c.generated_at, c.state, e.date, e.session
        FROM trigger_coaching c
        JOIN trigger_events e ON e.id = c.event_id
        WHERE c.valid = 1 AND c.usefulness IS NULL AND e.message_sent = 1
        ORDER BY c.generated_at DESC, c.id DESC
        """
    ).fetchall()


def latest_unrated(conn, window_hours: int) -> sqlite3.Row | None:
    """The most-recent delivered+unrated coaching within the rating window."""
    cutoff = (datetime.now(TZ) - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    rows = pending(conn)
    for r in rows:
        if r["generated_at"] >= cutoff:
            return r
    return None


def resolve_target(conn, args, window_hours: int) -> sqlite3.Row | None:
    if args.coaching_id is not None:
        return conn.execute(
            """
            SELECT c.id, c.event_id, c.generated_at, c.state, e.date, e.session
            FROM trigger_coaching c JOIN trigger_events e ON e.id = c.event_id
            WHERE c.id = ?
            """,
            (args.coaching_id,),
        ).fetchone()
    if args.event_id is not None:
        return conn.execute(
            """
            SELECT c.id, c.event_id, c.generated_at, c.state, e.date, e.session
            FROM trigger_coaching c JOIN trigger_events e ON e.id = c.event_id
            WHERE c.event_id = ? AND c.valid = 1
            ORDER BY c.id DESC LIMIT 1
            """,
            (args.event_id,),
        ).fetchone()
    return latest_unrated(conn, window_hours)


def main() -> int:
    p = argparse.ArgumentParser(description="Record a usefulness rating for a stoiclife push.")
    p.add_argument("--usefulness", type=int, choices=[-1, 0, 1],
                   help="+1 useful / 0 neutral / -1 not useful (agent infers from the reply)")
    p.add_argument("--reaction", default=None, help="raw reply text, stored verbatim")
    p.add_argument("--coaching-id", type=int, default=None, help="target a specific trigger_coaching row")
    p.add_argument("--event-id", type=int, default=None, help="target the latest coaching for an event")
    p.add_argument("--list", action="store_true", help="list delivered, unrated pushes and exit")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = p.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    window = cfg.get("feedback", {}).get("rating_window_hours", 18)
    conn = connect(cfg["db_path"])

    if args.list:
        rows = pending(conn)
        if not rows:
            print("no delivered, unrated coaching pushes")
        for r in rows:
            print(f"coaching_id={r['id']} event_id={r['event_id']} {r['date']}/{r['session']} "
                  f"{r['state']} (generated {r['generated_at']})")
        return 0

    if args.usefulness is None:
        print("error: --usefulness is required (unless --list)", file=sys.stderr)
        return 1

    target = resolve_target(conn, args, window)
    if target is None:
        print("no matching coaching to rate "
              f"(no delivered, unrated push within {window}h)", file=sys.stderr)
        return 3

    now = datetime.now(TZ).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE trigger_coaching SET usefulness = ?, reaction_raw = ?, reacted_at = ? WHERE id = ?",
        (args.usefulness, args.reaction, now, target["id"]),
    )
    conn.execute(
        "UPDATE trigger_events SET usefulness = ? WHERE id = ?",
        (args.usefulness, target["event_id"]),
    )
    conn.commit()
    conn.close()
    label = {1: "useful (+1)", 0: "neutral (0)", -1: "not useful (-1)"}[args.usefulness]
    print(f"rated coaching_id={target['id']} (event {target['event_id']}, "
          f"{target['date']}/{target['session']} {target['state']}): {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
