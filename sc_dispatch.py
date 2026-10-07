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
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

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
    "noop": re.compile(r"^noop$"),
}
NOT_YET = {"note": 3, "write": 4, "skip": 4}  # action -> phase that adds it

REPO_DIR = Path(__file__).resolve().parent
REACTION_CONFIG = REPO_DIR / "stoiclife_config.json"  # tests point this at a scratch config
REASONS = {"generic": "Too generic", "offbase": "Off-base", "long": "Too long",
           "more": "Tell me more"}
FB_MORE_HOURS = 2
TARGET_TABLES = {"r": "coaching_responses", "t": "trigger_coaching"}


def btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def status_buttons(label: str) -> list:
    # P2-D5: feedback never re-edits the coaching text (the callback only carries plain
    # text, so an edit would drop the bold). The buttons become a status line instead.
    return [[btn(label, "sc:noop")]]


def reason_buttons(kind: str, target_id: int) -> list:
    k = f"{kind}{target_id}"
    return [[btn(REASONS["generic"], f"sc:fbr:{k}:generic"), btn(REASONS["offbase"], f"sc:fbr:{k}:offbase")],
            [btn(REASONS["long"], f"sc:fbr:{k}:long"), btn(REASONS["more"], f"sc:fbr:{k}:more")]]


def upsert_feedback(conn, kind: str, target_id: int, rating: str, reason: str | None,
                    now: datetime, keep_reason: bool = False) -> None:
    conn.execute(
        "INSERT INTO response_feedback (target_kind, target_id, rating, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(target_kind, target_id) DO UPDATE SET "
        "rating = excluded.rating, reason = "
        + ("COALESCE(excluded.reason, response_feedback.reason)" if keep_reason else "excluded.reason"),
        (kind, target_id, rating, reason, now.isoformat()))


def sync_trigger_usefulness(target_id: int, usefulness: int, reaction: str) -> None:
    """D4: a `t` rating also lands on trigger_coaching/trigger_events via record_reaction.py."""
    proc = subprocess.run(
        [sys.executable, str(REPO_DIR / "record_reaction.py"), "--coaching-id", str(target_id),
         "--usefulness", str(usefulness), "--reaction", reaction, "--config", str(REACTION_CONFIG)],
        capture_output=True, text=True)
    level = "INFO" if proc.returncode == 0 else "ERROR"
    tg.log(level, f"sc_dispatch: record_reaction t{target_id} {usefulness:+d}: "
                  f"{(proc.stdout or proc.stderr).strip()[-200:]}")


def handle_feedback(req: dict, action: str, groups, conn, now: datetime) -> dict:
    kind, target_id = groups[0], int(groups[1])
    if not conn.execute(f"SELECT 1 FROM {TARGET_TABLES[kind]} WHERE id = ?", (target_id,)).fetchone():
        tg.log("WARNING", f"sc_dispatch: feedback for unknown target {kind}{target_id}; buttons cleared")
        return {"actions": [{"type": "clearButtons"}]}

    if action == "fb":
        rating = groups[2]
        with conn:
            upsert_feedback(conn, kind, target_id, rating, None, now, keep_reason=(rating == "down"))
        if kind == "t":
            sync_trigger_usefulness(target_id, 1 if rating == "up" else -1, f"button:{rating}")
        tg.log("INFO", f"sc_dispatch: feedback {kind}{target_id} {rating}")
        if rating == "up":
            return {"actions": [{"type": "editButtons", "buttons": status_buttons("✓ Noted 👍")}]}
        return {"actions": [{"type": "editButtons", "buttons": reason_buttons(kind, target_id)}]}

    # fbr: a reason after 👎
    reason = groups[2]
    with conn:
        upsert_feedback(conn, kind, target_id, "down", reason, now)
    if kind == "t":
        sync_trigger_usefulness(target_id, -1, f"button:down:{reason}")
    tg.log("INFO", f"sc_dispatch: feedback {kind}{target_id} down reason={reason}")
    actions = [{"type": "editButtons", "buttons": status_buttons(f"✓ Noted: {REASONS[reason]}")}]
    if reason == "more":
        tg.set_pending(f"fb_more:{kind}{target_id}", chat_id=req.get("chatId"),
                       message_id=str(req.get("messageId") or ""),
                       expires_at=now + timedelta(hours=FB_MORE_HOURS))
        actions.append({"type": "reply", "text": "What would have been more useful?"})
    return {"actions": actions}


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
    if action in ("fb", "fbr"):
        return handle_feedback(req, action, groups, conn, now)
    if action == "noop":  # a status button ("✓ Noted …"); nothing to do
        return {"actions": []}
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
