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
stdout (command):  {"reply": {"text": "...", "channelData": {"telegram": {"buttons": [[...]]}}}}

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
    # P3-D4: card buttons carry their day (`:YYYYMMDD`); the plan's suffix-less form stays valid.
    "mood": re.compile(r"^mood:(10|[1-9])(?::(\d{8}))?$"),
    "mod": re.compile(r"^mod:(emotions|creativity|happiness)(?::(\d{8}))?$"),
    "fb": re.compile(r"^fb:([rt])(\d+):(up|down)$"),
    "fbr": re.compile(r"^fbr:([rt])(\d+):(generic|offbase|long|more)$"),
    "write": re.compile(r"^write:(morning|evening)$"),
    "skip": re.compile(r"^skip:(morning|evening)$"),
    "note": re.compile(r"^note:(mood|module)(?::(\d{8}))?$"),
    "noop": re.compile(r"^noop$"),
}
NOT_YET = {"write": 4, "skip": 4}  # action -> phase that adds it
NOTE_HOURS = 2
LIVE_COMMANDS = ("mood", "module")  # /journal and /skip land with Phase 4 (P3-D5)

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


def chat_of(req: dict) -> str:
    """Telegram chat id; commands arrive as `telegram:<id>` (P3-D8)."""
    raw = str(req.get("chatId") or checkins.coach_config()["chat_id"])
    return raw.split(":", 1)[1] if raw.startswith("telegram:") else raw


def day_tag(day: str) -> str:
    return day.replace("-", "")


def tag_day(tag: str) -> str:
    return f"{tag[:4]}-{tag[4:6]}-{tag[6:]}"


def card(conn, chat_id: str, day: str) -> tuple[str, list]:
    """The check-in card for `day`, rendered from the DB (never from the callback text)."""
    state = checkins.today_state(conn, chat_id, day)
    mood = (state.get("mood") or {}).get("value")
    module = (state.get("module") or {}).get("value")
    tag = day_tag(day)
    title = datetime.strptime(day, "%Y-%m-%d").strftime("Check-in · %a %-d %b")
    parts = []
    if mood:
        parts.append(f"Mood: {mood} ✓")
    if module:
        parts.append(f"Module: {module.capitalize()} ✓")
    lines = [title, " · ".join(parts) if parts else "Tap a mood (1–10) and, if you like, a Stoic module."]
    for ctype, label in (("mood", "Mood note"), ("module", "Module note")):
        note = (state.get(ctype) or {}).get("note")
        if note:
            lines.append(f"📝 {label}: {note if len(note) <= 120 else note[:117] + '…'}")

    def mark(label, chosen):
        return f"{label} ✓" if chosen else label

    rows = [[btn(mark(str(n), mood == str(n)), f"sc:mood:{n}:{tag}") for n in range(1, 6)],
            [btn(mark(str(n), mood == str(n)), f"sc:mood:{n}:{tag}") for n in range(6, 11)],
            [btn(mark(k.capitalize(), module == k), f"sc:mod:{k}:{tag}") for k in MODULE_KEYS]]
    notes = [t for t in ("mood", "module") if (state.get(t) or {}).get("value")]
    if len(notes) == 1:
        rows.append([btn("📝 Add a note", f"sc:note:{notes[0]}:{tag}")])
    elif notes:
        rows.append([btn("📝 Mood note", f"sc:note:mood:{tag}"),
                     btn("📝 Module note", f"sc:note:module:{tag}")])
    return "\n".join(lines), rows


def expired(day: str) -> dict:
    when = datetime.strptime(day, "%Y-%m-%d").strftime("%a %-d %b")
    return {"actions": [{"type": "edit", "buttons": [],
                         "text": f"This check-in card is from {when} and has expired. Send /mood for today's."}]}


def card_day(req: dict, conn, chat_id: str, tag: str | None, today: str) -> str | None:
    """The card's day, or None when the tap is stale (G5 / P3-D4)."""
    if tag:
        return today if tag_day(tag) == today else None
    ui = tg.lookup_ui_message(conn, chat_id, req["messageId"]) if req.get("messageId") is not None else None
    return None if ui and ui["local_date"] != today else today


def handle_checkin(req: dict, ctype: str, value: str, tag: str | None, conn, now: datetime) -> dict:
    chat_id = chat_of(req)
    today = checkins.local_date(now)
    day = card_day(req, conn, chat_id, tag, today)
    if day is None:
        stale = tag_day(tag) if tag else tg.lookup_ui_message(conn, chat_id, req["messageId"])["local_date"]
        tg.log("INFO", f"sc_dispatch: stale {ctype} tap from {stale} (today {today}); ignored")
        return expired(stale)
    message_id = req.get("messageId")
    with conn:
        checkins.upsert(conn, chat_id=chat_id, ctype=ctype, value=value, source="button",
                        day=day, message_id=str(message_id) if message_id else None, now=now)
    tg.log("INFO", f"sc_dispatch: checkin {ctype}={value} chat={chat_id} day={day}")
    text, rows = card(conn, chat_id, day)
    return {"actions": [{"type": "edit", "text": text, "buttons": rows}]}


def handle_note(req: dict, ctype: str, tag: str | None, conn, now: datetime) -> dict:
    chat_id = chat_of(req)
    today = checkins.local_date(now)
    day = card_day(req, conn, chat_id, tag, today)
    if day is None:
        return expired(tag_day(tag) if tag else today)
    if not checkins.today_state(conn, chat_id, day).get(ctype):
        return {"actions": [{"type": "reply", "text": f"Pick a {ctype} first, then add the note."}]}
    tg.set_pending(f"note:{ctype}:{day_tag(day)}", chat_id=chat_id,
                   message_id=str(req.get("messageId") or ""),
                   expires_at=now + timedelta(hours=NOTE_HOURS))
    tg.log("INFO", f"sc_dispatch: note requested for {ctype} on {day}")
    return {"actions": [{"type": "reply", "text": f"Add your {ctype} note below."}]}


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
        return handle_checkin(req, "mood", groups[0], groups[1], conn, now)
    if action == "mod":
        return handle_checkin(req, "module", groups[0], groups[1], conn, now)
    if action == "note":
        return handle_note(req, groups[0], groups[1], conn, now)
    if action in ("fb", "fbr"):
        return handle_feedback(req, action, groups, conn, now)
    if action == "noop":  # a status button ("✓ Noted …"); nothing to do
        return {"actions": []}
    return {"actions": []}  # unreachable while PATTERNS and the branches agree


def handle_command(req: dict, conn=None, now: datetime | None = None) -> dict:
    """Slash commands. Returns {"reply": ReplyPayload}; the shim passes it through as-is."""
    command = str(req.get("command") or "")
    if command not in LIVE_COMMANDS:
        tg.log("INFO", f"sc_dispatch: /{command} (lands with Phase 4)")
        return {"reply": {"text": "Coming soon. This command goes live in a later update."}}
    conn = conn or tg.db_connect()
    now = now or checkins.now_local()
    chat_id = chat_of(req)
    text, rows = card(conn, chat_id, checkins.local_date(now))
    tg.log("INFO", f"sc_dispatch: /{command} -> check-in card")
    # P3-D2: channelData.telegram.buttons keeps the exact 2x5 rows (presentation would re-chunk by 3).
    return {"reply": {"text": text, "channelData": {"telegram": {"buttons": rows}}}}


JOURNAL_PREFIXES = ("morning prep:", "evening review:")


def handle_message(req: dict) -> dict:
    """P3-B1: the plugin's message_received hook, for every inbound coach-chat message.

    Saves the text deterministically if a note / "Tell me more" answer is pending, so it
    never depends on the LLM running step 0. Slash commands and journal entries are left
    alone (step 0 skips those too). Returns {"saved": bool}; the hook ignores the result.
    """
    text = str(req.get("text") or "")
    body = text.lstrip().lower()
    if not body or body.startswith("/") or body.startswith(JOURNAL_PREFIXES):
        return {"saved": False}
    import save_pending_note  # local: keeps callback/command paths free of it
    saved = save_pending_note.save_note(text, chat_of(req), from_hook=True)
    tg.log("INFO", f"sc_dispatch: message hook chat={chat_of(req)} (raw {req.get('chatId')!r}) saved={saved}")
    return {"saved": saved}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        tg.log("ERROR", f"sc_dispatch: bad stdin JSON: {exc}")
        print(json.dumps({"actions": []}))
        return 0
    try:
        kind = req.get("kind")
        out = (handle_command(req) if kind == "command"
               else handle_message(req) if kind == "message"
               else handle_callback(req))
    except Exception as exc:  # never let a tap crash into the agent; log and do nothing
        tg.log("ERROR", f"sc_dispatch: {type(exc).__name__}: {exc} (req={req!r})")
        out = ({"reply": {"text": "Something went wrong; it's logged."}} if req.get("kind") == "command"
               else {"saved": False} if req.get("kind") == "message" else {"actions": []})
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
