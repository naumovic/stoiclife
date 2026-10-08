#!/usr/bin/env python3
"""FEAT-07 Phase 4: send the morning/evening prompt with buttons (D47, D48, D51).

Reads the prompt text on stdin (built by coach_morning.sh / coach_evening.sh), records a
`prompt_events` row, sends it with the check-in first (MIN-129, prompt_ui.py: morning [🙂 Check in]
[Skip], then mood, module, then [✍️ Write entry] [Skip today], starting at Write entry when
a mood is logged already; evening, MIN-133: module or No module, then Write entry),
stores the Telegram id in
`prompt_events` + `ui_messages` (reply-to matching), and clears any open hold (D45:
a late hold lasts until the next prompt).

stdout is what the command cron delivers: `NO_REPLY` after a successful send, or the
prompt text itself if sending failed (D51: a prompt is never lost).

STOICLIFE_SKIP_PROMPT_STATE=1 (test runs): record nothing, so the test doesn't open a prompt
window, and send plain [✍️ Write entry] [Skip today] (the check-in steps need a prompt id).

    printf '%s' "$TEXT" | python3 send_prompt.py --session morning
"""
from __future__ import annotations

import argparse
import os
import sys

import checkins
import prompt_ui
import prompts
import route_entry
import tg


def buttons(conn, session: str, pid: int | None, chat_id: str, day: str) -> list:
    if not pid:  # test send: no prompt row for the check-in steps to attach to
        return [[("✍️ Write entry", f"sc:write:{session}"), ("Skip today", f"sc:skip:{session}")]]
    state = checkins.today_state(conn, chat_id, day)
    rows = prompt_ui.rows(prompt_ui.start_stage(state, session), {"id": pid, "session": session}, state)
    return prompt_ui.as_tuples(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True, choices=prompts.SESSIONS)
    args = ap.parse_args()
    text = sys.stdin.read().strip()
    if not text:
        print("error: empty prompt text", file=sys.stderr)
        return 1
    test = os.environ.get("STOICLIFE_SKIP_PROMPT_STATE") == "1"
    chat_id = checkins.coach_config()["chat_id"]
    now = checkins.now_local()
    day = checkins.local_date(now)
    try:
        conn = tg.db_connect()
        pid = None
        if not test:
            with conn:
                pid = prompts.record(conn, chat_id=chat_id, session=args.session, message_id=None, now=now)
            route_entry.clear_hold(chat_id)
        mid = tg.send(text, buttons(conn, args.session, pid, chat_id, day), chat_id=chat_id)
        if pid:
            with conn:
                conn.execute("UPDATE prompt_events SET message_id = ? WHERE id = ?", (mid, pid))
                if mid:
                    tg.record_ui_message(conn, message_id=mid, kind=f"prompt_{args.session}",
                                         chat_id=chat_id, ref_id=pid, session=args.session, day=day)
        tg.log("INFO", f"send_prompt: {args.session} prompt {pid} sent as message {mid}"
                       f"{' (test, not recorded)' if test else ''}")
        print("NO_REPLY")
    except Exception as exc:  # D51: fall back to the plain-text prompt via the cron's stdout
        tg.log("ERROR", f"send_prompt: {args.session} buttoned send failed ({exc}); plain-text fallback")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
