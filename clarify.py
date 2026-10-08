#!/usr/bin/env python3
"""MIN-132: the CLARIFY 🧭 question ("want the full read?") and its answer.

stoiclife_run.py prints CLARIFY for a 40-69 confidence state. The question is sent here,
never as the coach's own reply, with [🧭 Yes, full read] [No thanks] buttons
(`sc:clar:<id>:y|n`), and recorded in `clarify_prompts`. The answer then routes without
guesswork (route_entry.decide / sc_dispatch):

  yes (tap or typed) -> route `clarify` -> the coach gets `CLARIFY_YES event=<id>` and
                        runs one fixed procedure (AGENTS.md §1b)
  no  (tap or typed) -> acknowledged here, no LLM

    python3 clarify.py --event-id 241        # the coach's CLARIFY step; prints NO_REPLY
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta

import channel_fmt
import checkins
import tg

CLARIFY_HOURS = 12
COLS = ("id", "chat_id", "event_id", "message_id", "local_date", "sent_at", "expires_at",
        "answer", "answer_source", "answered_at", "route_id")
# Whole-message answers only: "yes, but first tell me…" is conversation, not a yes.
# 👍 stays a coaching rating (AGENTS.md §2), so it isn't a yes here.
YES = {"y", "yes", "yes please", "yeah", "yep", "yup", "sure", "ok", "okay", "please",
       "go ahead", "send it", "yes send it", "full read"}
NO = {"n", "no", "no thanks", "no thank you", "nope", "not now", "not today", "skip"}


def parse_answer(text: str) -> str | None:
    norm = re.sub(r"[^\w\s]", "", text.lower()).strip()
    norm = re.sub(r"\s+", " ", norm)
    return "yes" if norm in YES else "no" if norm in NO else None


def buttons(cid: int) -> list:
    return [[("🧭 Yes, full read", f"sc:clar:{cid}:y"), ("No thanks", f"sc:clar:{cid}:n")]]


def question_text(conn, event_id: int, channel: str = "telegram") -> str:
    from stoiclife_run import clarify_message  # local: keeps the tap path light
    row = conn.execute("SELECT state, deltas_json FROM trigger_events WHERE id = ?",
                       (event_id,)).fetchone()
    if not row:
        raise ValueError(f"trigger_events {event_id} not found")
    return channel_fmt.render(clarify_message(row[0], json.loads(row[1] or "{}")), channel)


# Every read joins the event: once record_coaching --send has set message_sent, the
# question is closed whatever its answer says.
SELECT = (f"SELECT {', '.join('c.' + c for c in COLS)}, COALESCE(e.message_sent, 0) "
          "FROM clarify_prompts c LEFT JOIN trigger_events e ON e.id = c.event_id ")


def _row(row) -> dict | None:
    if not row:
        return None
    return {**dict(zip(COLS, row)), "event_sent": bool(row[len(COLS)])}


def get(conn, cid: int) -> dict | None:
    return _row(conn.execute(SELECT + "WHERE c.id = ?", (cid,)).fetchone())


def for_route(conn, route_id: int) -> dict | None:
    return _row(conn.execute(SELECT + "WHERE c.route_id = ?", (route_id,)).fetchone())


def is_open(c: dict | None, now: datetime) -> bool:
    return bool(c) and not c["answer"] and not c["event_sent"] and c["expires_at"] > now.isoformat()


def pending(conn, chat_id: str, now: datetime) -> dict | None:
    """The chat's latest CLARIFY question, if still unanswered, unexpired and not yet sent."""
    c = _row(conn.execute(SELECT + "WHERE c.chat_id = ? ORDER BY c.id DESC LIMIT 1",
                          (str(chat_id),)).fetchone())
    return c if is_open(c, now) else None


def answer(conn, cid: int, ans: str, source: str, now: datetime) -> None:
    with conn:
        conn.execute("UPDATE clarify_prompts SET answer = ?, answer_source = ?, answered_at = ? "
                     "WHERE id = ?", (ans, source, now.isoformat(), cid))
    tg.log("INFO", f"clarify: #{cid} answered {ans} ({source})")


def link_route(conn, cid: int, route_id: int) -> None:
    with conn:
        conn.execute("UPDATE clarify_prompts SET route_id = ? WHERE id = ?", (route_id, cid))


def send(conn, event_id: int, *, chat_id: str | None = None, now: datetime | None = None,
         channel: str = "telegram") -> int | None:
    """Send the 🧭 question with buttons; returns the clarify_prompts id (None if already sent)."""
    now = now or checkins.now_local()
    chat_id = str(chat_id or checkins.coach_config()["chat_id"])
    sent = conn.execute("SELECT message_sent FROM trigger_events WHERE id = ?", (event_id,)).fetchone()
    if sent and sent[0]:
        tg.log("INFO", f"clarify: event {event_id} already has its full read; question not sent")
        return None
    text = question_text(conn, event_id, channel)
    with conn:
        cur = conn.execute(
            "INSERT INTO clarify_prompts (chat_id, event_id, local_date, sent_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, event_id, now.date().isoformat(), now.isoformat(),
             (now + timedelta(hours=CLARIFY_HOURS)).isoformat()))
        cid = cur.lastrowid
    message_id = tg.send(text, buttons(cid), chat_id=chat_id)
    with conn:
        conn.execute("UPDATE clarify_prompts SET message_id = ? WHERE id = ?", (message_id, cid))
        if message_id:
            tg.record_ui_message(conn, message_id=message_id, kind="clarify", chat_id=chat_id,
                                 ref_id=cid, day=now.date().isoformat())
    tg.log("INFO", f"clarify: #{cid} sent for event {event_id} message_id={message_id}")
    return cid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event-id", type=int, required=True)
    ap.add_argument("--chat-id")
    ap.add_argument("--db")
    args = ap.parse_args()
    conn = tg.db_connect(args.db)
    try:
        send(conn, args.event_id, chat_id=args.chat_id)
    except Exception as exc:
        tg.log("ERROR", f"clarify: send failed for event {args.event_id}: {exc}")
        print(f"error: send failed: {exc}", file=sys.stderr)
        return 1
    print("NO_REPLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
