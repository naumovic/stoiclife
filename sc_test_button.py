#!/usr/bin/env python3
"""FEAT-07 Phase 1 acceptance test: send one `sc:mood:7` button to the coach chat.

Tapping it should upsert checkin_events (mood 7, source=button) and edit the message
to show `Mood: 7 ✓`, with no agent turn. Afterwards run `--cleanup` to delete the test
check-in so it can't merge into a real entry (G10).

    python3 sc_test_button.py            # send
    python3 sc_test_button.py --cleanup  # remove today's test check-in + ui_messages row
"""
from __future__ import annotations

import argparse
import sys

import checkins
import tg

TEST_TEXT = "[FEAT-07 test] Tap the button. It should turn into \"Mood: 7 ✓\"."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()
    conn = tg.db_connect()
    chat_id = checkins.coach_config()["chat_id"]

    if args.cleanup:
        ids = [r[0] for r in conn.execute(
            "SELECT message_id FROM ui_messages WHERE chat_id = ? AND kind = 'test'", (chat_id,))]
        with conn:
            n = 0
            for mid in ids:
                n += conn.execute("DELETE FROM checkin_events WHERE chat_id = ? AND message_id = ?",
                                  (chat_id, mid)).rowcount
            conn.execute("DELETE FROM ui_messages WHERE chat_id = ? AND kind = 'test'", (chat_id,))
        tg.log("INFO", f"sc_test_button: cleanup removed {n} test check-in(s), {len(ids)} ui row(s)")
        print(f"removed {n} test check-in(s) and {len(ids)} test ui_messages row(s)")
        return 0

    mid = tg.send(TEST_TEXT, [[("7", "sc:mood:7")]])
    if mid:
        with conn:
            tg.record_ui_message(conn, message_id=mid, kind="test", chat_id=chat_id)
    print(f"sent test button, message_id={mid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
