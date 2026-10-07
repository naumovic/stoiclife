#!/usr/bin/env python3
"""FEAT-07 P2.5: typed 👍/👎 (legacy) → rating on the latest coaching message.

The buttons are the main path; this keeps a typed rating working (P2-D9, G16).
Target = the newest coaching message (`ui_messages` kind coaching_r / coaching_t)
sent within the rating window (stoiclife_config feedback.rating_window_hours,
default 18h) that has no rating yet. A `t` rating is mirrored to trigger_coaching
via record_reaction.py --coaching-id. If no button-era message matches, it falls
back to record_reaction.py's own latest-unrated-push lookup (pre-FEAT-07 pushes).

    python3 record_feedback.py --rating up|down|neutral --reaction "<his reply>"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import timedelta

import checkins
import tg

USEFULNESS = {"up": 1, "neutral": 0, "down": -1}


def window_hours() -> int:
    try:
        cfg = json.loads(checkins.CONFIG_PATH.read_text())
        return int(cfg.get("feedback", {}).get("rating_window_hours", 18))
    except (OSError, ValueError):
        return 18


def latest_target(conn, chat_id: str, now=None):
    cutoff = ((now or checkins.now_local()) - timedelta(hours=window_hours())).isoformat()
    return conn.execute(
        """
        SELECT u.kind, u.ref_id FROM ui_messages u
        WHERE u.chat_id = ? AND u.kind IN ('coaching_r', 'coaching_t') AND u.created_at >= ?
          AND u.ref_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM response_feedback f
                          WHERE f.target_kind = substr(u.kind, -1) AND f.target_id = u.ref_id)
        ORDER BY u.created_at DESC, u.id DESC LIMIT 1
        """, (str(chat_id), cutoff)).fetchone()


def record_reaction(args_extra: list[str], usefulness: int, reaction: str, config=None):
    cmd = [sys.executable, str(checkins.REPO_DIR / "record_reaction.py"),
           "--usefulness", str(usefulness), "--reaction", reaction, *args_extra]
    if config:
        cmd += ["--config", str(config)]
    return subprocess.run(cmd, capture_output=True, text=True)


def main(argv=None, conn=None, config=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rating", required=True, choices=list(USEFULNESS))
    ap.add_argument("--reaction", default="")
    ap.add_argument("--chat-id")
    args = ap.parse_args(argv)
    chat_id = str(args.chat_id or checkins.coach_config()["chat_id"])
    conn = conn or tg.db_connect()
    use = USEFULNESS[args.rating]

    hit = latest_target(conn, chat_id)
    if hit is None:  # pre-FEAT-07 push without ui_messages: record_reaction's own lookup
        proc = record_reaction([], use, args.reaction, config)
        print((proc.stdout or proc.stderr).strip() or "no coaching message to rate")
        return proc.returncode
    kind, target_id = hit[0][-1], hit[1]
    with conn:
        conn.execute(
            "INSERT INTO response_feedback (target_kind, target_id, rating, note, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(target_kind, target_id) DO UPDATE SET "
            "rating = excluded.rating, note = COALESCE(excluded.note, response_feedback.note)",
            (kind, target_id, args.rating, args.reaction or None, checkins.now_local().isoformat()))
    if kind == "t":
        record_reaction(["--coaching-id", str(target_id)], use, args.reaction, config)
    tg.log("INFO", f"record_feedback: typed {args.rating} on {kind}{target_id}")
    print(f"rated {kind}{target_id}: {args.rating}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
