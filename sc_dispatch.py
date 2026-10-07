#!/usr/bin/env python3
"""FEAT-07: deterministic handler for coach-bot buttons and slash commands.

The `stoic-coach-ui` plugin is a thin shim (G6): for every `sc:` callback and every
/mood /module /journal /skip command on the coach account it pipes one JSON object
to this script's stdin and applies the JSON it prints. No LLM is involved.

stdin (callback):  {"kind": "callback", "payload": "mood:7", "chatId": "...",
                    "messageId": 123, "messageText": "...", "senderId": "..."}
stdin (command):   {"kind": "command", "command": "mood", "args": "", "chatId": "..."}

stdout (callback): {"actions": [{"type": "edit", "text": "...", "buttons": [[...]]},
                                {"type": "editButtons", "buttons": [[...]]},
                                {"type": "clearButtons"},
                                {"type": "reply", "text": "...", "buttons": [[...]]}]}
stdout (command):  {"text": "..."}

Buttons are Telegram rows: [[{"text": "7", "callback_data": "sc:mood:7"}]].
Anything malformed or unknown is logged and answered with no actions; it is never
passed on to the agent.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime

import checkins
import tg

MODULE_KEYS = ("emotions", "creativity", "happiness")
SESSIONS = ("morning", "evening")

# Accepted payload shapes (after the `sc:` namespace) — the scheme in the seed doc.
PATTERNS = {
    "mood": re.compile(r"^mood:(10|[1-9])$"),
    "mod": re.compile(r"^mod:(emotions|creativity|happiness)$"),
    "fb": re.compile(r"^fb:([rt])(\d+):(up|down)$"),
    "fbr": re.compile(r"^fbr:([rt])(\d+):(generic|offbase|long|more)$"),
    "write": re.compile(r"^write:(morning|evening)$"),
    "skip": re.compile(r"^skip:(morning|evening)$"),
    "note": re.compile(r"^note:(mood|module)$"),
}
NOT_YET = {"fb": 2, "fbr": 2, "note": 3, "write": 4, "skip": 4}  # action -> phase that adds it


def parse(payload: str):
    """Return (action, groups) or (None, None) for anything outside the scheme."""
    action = payload.split(":", 1)[0]
    pat = PATTERNS.get(action)
    if not pat:
        return None, None
    m = pat.match(payload)
    return (action, m.groups()) if m else (None, None)


def _first_block(text: str | None) -> str:
    """The message text without any status lines we appended on an earlier tap."""
    return (text or "").split("\n\n✓ ", 1)[0].rstrip()


def handle_checkin(req: dict, ctype: str, value: str, conn, now: datetime) -> dict:
    chat_id = str(req.get("chatId") or checkins.coach_config()["chat_id"])
    message_id = req.get("messageId")
    today = checkins.local_date(now)

    ui = tg.lookup_ui_message(conn, chat_id, message_id) if message_id is not None else None
    if ui and ui["local_date"] != today:  # G5: stale picker
        tg.log("INFO", f"sc_dispatch: stale {ctype} tap on message {message_id} "
                       f"from {ui['local_date']} (today {today}); ignored")
        return {"actions": [{"type": "edit",
                             "text": _first_block(req.get("messageText"))
                             + "\n\n✓ This picker has expired. Use /mood for today."}]}

    with conn:
        checkins.upsert(conn, chat_id=chat_id, ctype=ctype, value=value, source="button",
                        day=today, message_id=str(message_id) if message_id else None, now=now)
    label = f"Mood: {value} ✓" if ctype == "mood" else f"Module: {value.capitalize()} ✓"
    tg.log("INFO", f"sc_dispatch: checkin {ctype}={value} chat={chat_id} day={today}")
    return {"actions": [{"type": "edit",
                         "text": _first_block(req.get("messageText")) + "\n\n✓ " + label}]}


def handle_callback(req: dict, conn=None, now: datetime | None = None) -> dict:
    payload = str(req.get("payload") or "")
    action, groups = parse(payload)
    if action is None:
        tg.log("WARNING", f"sc_dispatch: unknown callback sc:{payload!r}; ignored")
        return {"actions": []}
    if action in NOT_YET:
        tg.log("INFO", f"sc_dispatch: sc:{payload} is valid but lands in Phase "
                       f"{NOT_YET[action]}; ignored")
        return {"actions": []}
    now = now or checkins.now_local()
    conn = conn or tg.db_connect()
    if action == "mood":
        return handle_checkin(req, "mood", groups[0], conn, now)
    if action == "mod":
        return handle_checkin(req, "module", groups[0], conn, now)
    return {"actions": []}  # unreachable while PATTERNS and the branches agree


def handle_command(req: dict) -> dict:
    command = str(req.get("command") or "")
    tg.log("INFO", f"sc_dispatch: /{command} (not live until Phase 3/4)")
    return {"text": "Coming soon. This command goes live in a later update."}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        tg.log("ERROR", f"sc_dispatch: bad stdin JSON: {exc}")
        print(json.dumps({"actions": []}))
        return 0
    try:
        out = handle_command(req) if req.get("kind") == "command" else handle_callback(req)
    except Exception as exc:  # never let a tap crash into the agent; log and do nothing
        tg.log("ERROR", f"sc_dispatch: {type(exc).__name__}: {exc} (req={req!r})")
        out = {"actions": []} if req.get("kind") != "command" else {"text": "Something went wrong; it's logged."}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
