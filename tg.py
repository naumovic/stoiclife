#!/usr/bin/env python3
"""FEAT-07: Telegram helpers for the coach bot (send/edit via the openclaw CLI,
pending state in state.json, and the ui_messages registry).

CLI limits on OpenClaw 2026.6.8 (see docs/FEAT07-UX-TELEGRAM-SEED.md G18/G19):
  * `message send --presentation` lays buttons out 3 per row, whatever rows we pass;
    exact row layouts are only possible from the plugin's callback handler.
  * `message edit` is text-only; button edits happen in the plugin handler.

Buttons here are rows of (label, callback_value) tuples.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from checkins import DEFAULT_DB, coach_config, local_date, now_local

OPENCLAW = str(Path.home() / ".npm-global" / "bin" / "openclaw")  # D21: never bare `openclaw`
STATE_PATH = Path.home() / ".openclaw" / "stoic" / "state.json"
LOG_PATH = Path.home() / ".openclaw" / "stoic" / "stoic.log"
CALLBACK_MAX_BYTES = 64


class TgError(RuntimeError):
    pass


def log(level: str, message: str) -> None:
    with LOG_PATH.open("a") as fh:
        fh.write(f"{now_local().isoformat()} {level} tg: {message}\n")


# --- sending -----------------------------------------------------------------

def presentation(buttons) -> dict:
    blocks = []
    for row in buttons or []:
        btns = []
        for label, value in row:
            if len(value.encode()) > CALLBACK_MAX_BYTES:
                raise ValueError(f"callback_data over {CALLBACK_MAX_BYTES} bytes: {value}")
            btns.append({"label": label, "value": value})
        blocks.append({"type": "buttons", "buttons": btns})
    return {"blocks": blocks}


def _find_message_id(obj):
    """Dig the Telegram message id out of the CLI's --json result, whatever its nesting."""
    if isinstance(obj, dict):
        for key in ("messageId", "message_id"):
            if key in obj and obj[key] not in (None, ""):
                return str(obj[key])
        for v in obj.values():
            hit = _find_message_id(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_message_id(v)
            if hit:
                return hit
    return None


def _parse_json_stdout(stdout: str):
    # The CLI can print warnings before the JSON; take from the first line that starts it.
    m = re.search(r"^[{\[]", stdout, re.M)
    if not m:
        raise TgError(f"no JSON in CLI output: {stdout[:300]!r}")
    return json.loads(stdout[m.start():])


# Tests set STOICLIFE_TG_FAKE=<file>: sends/edits are appended there as JSON lines
# (with a fake, incrementing message id) instead of calling the CLI.
FAKE_ENV = "STOICLIFE_TG_FAKE"


def _fake(args: list[str]) -> dict:
    path = Path(os.environ[FAKE_ENV])
    n = sum(1 for _ in path.open()) if path.exists() else 0
    with path.open("a") as fh:
        fh.write(json.dumps({"args": args}) + "\n")
    return {"payload": {"messageId": 90000 + n}}


def _run(args: list[str], timeout: int = 60) -> dict:
    if os.environ.get(FAKE_ENV):
        return _fake(args)
    proc = subprocess.run([OPENCLAW, *args, "--json"], capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise TgError(f"openclaw {args[:2]} exit {proc.returncode}: "
                      f"{(proc.stderr or proc.stdout)[-500:]}")
    return _parse_json_stdout(proc.stdout)


def send(text: str, buttons=None, *, silent: bool = False, reply_to: str | None = None,
         chat_id: str | None = None, account: str | None = None) -> str | None:
    """Send to the coach chat; returns the Telegram message id (None if the CLI didn't say)."""
    cfg = coach_config()
    args = ["message", "send", "--channel", "telegram",
            "--account", account or cfg["account"],
            "--target", str(chat_id or cfg["chat_id"]), "--message", text]
    if buttons:
        args += ["--presentation", json.dumps(presentation(buttons))]
    if silent:
        args.append("--silent")
    if reply_to:
        args += ["--reply-to", str(reply_to)]
    result = _run(args)
    mid = _find_message_id(result)
    log("INFO", f"sent message_id={mid} buttons={bool(buttons)} silent={silent}")
    return mid


def edit_text(message_id: str, text: str, *, chat_id: str | None = None,
              account: str | None = None) -> dict:
    """Text-only edit (CLI limit G19)."""
    cfg = coach_config()
    return _run(["message", "edit", "--channel", "telegram",
                 "--account", account or cfg["account"],
                 "--target", str(chat_id or cfg["chat_id"]),
                 "--message-id", str(message_id), "--message", text])


# --- ui_messages registry (G4) -------------------------------------------------

def record_ui_message(conn: sqlite3.Connection, *, message_id: str, kind: str,
                      chat_id: str | None = None, ref_id: int | None = None,
                      session: str | None = None, day: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ui_messages (message_id, chat_id, kind, ref_id, session, "
        "local_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(message_id), str(chat_id or coach_config()["chat_id"]), kind, ref_id, session,
         day or local_date(), now_local().isoformat()),
    )


def lookup_ui_message(conn: sqlite3.Connection, chat_id: str, message_id) -> dict | None:
    row = conn.execute(
        "SELECT kind, ref_id, session, local_date, created_at FROM ui_messages "
        "WHERE chat_id = ? AND message_id = ?",
        (str(chat_id), str(message_id)),
    ).fetchone()
    if not row:
        return None
    return dict(zip(("kind", "ref_id", "session", "local_date", "created_at"), row))


def db_connect(path: Path | str | None = None) -> sqlite3.Connection:
    return sqlite3.connect(os.path.expanduser(str(path or DEFAULT_DB)))


# --- pending state (D9, G2) ----------------------------------------------------
# state.json keeps its legacy top-level keys (awaiting_response, session,
# prompt_sent_at) for save_entry/set_prompt_state; FEAT-07 adds
#   "pending": {"<chat_id>": {"kind", "message_id", "set_at", "expires_at"}}
# Every writer must read-modify-write so neither half wipes the other.

def read_state(path: Path | None = None) -> dict:
    path = path or STATE_PATH
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE_PATH
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def get_pending(chat_id: str | None = None, *, now: datetime | None = None,
                path: Path | None = None) -> dict | None:
    """The chat's pending state, or None if absent or expired."""
    path = path or STATE_PATH
    chat_id = str(chat_id or coach_config()["chat_id"])
    entry = (read_state(path).get("pending") or {}).get(chat_id)
    if not entry:
        return None
    exp = entry.get("expires_at")
    if exp and datetime.fromisoformat(exp) <= (now or now_local()):
        return None
    return entry


def set_pending(kind: str, *, chat_id: str | None = None, message_id: str | None = None,
                expires_at: datetime | None = None, path: Path | None = None) -> dict:
    path = path or STATE_PATH
    chat_id = str(chat_id or coach_config()["chat_id"])
    state = read_state(path)
    entry = {"kind": kind, "message_id": message_id, "set_at": now_local().isoformat(),
             "expires_at": expires_at.isoformat() if expires_at else None}
    state.setdefault("pending", {})[chat_id] = entry
    write_state(state, path)
    log("INFO", f"pending set chat={chat_id} kind={kind} expires={entry['expires_at']}")
    return entry


def clear_pending(chat_id: str | None = None, *, path: Path | None = None) -> None:
    path = path or STATE_PATH
    chat_id = str(chat_id or coach_config()["chat_id"])
    state = read_state(path)
    if (state.get("pending") or {}).pop(chat_id, None) is not None:
        write_state(state, path)
        log("INFO", f"pending cleared chat={chat_id}")


# --- consumed marker (P3-B1) ---------------------------------------------------
# The plugin's message_received hook saves a pending note deterministically, before
# the LLM sees the message. It leaves {"consumed": {chat: {text, kind, at}}} so the
# coach's step 0, run on the same message moments later, still answers SAVED.

def mark_consumed(text: str, kind: str, *, chat_id: str | None = None,
                  path: Path | None = None) -> None:
    chat_id = str(chat_id or coach_config()["chat_id"])
    state = read_state(path)
    state.setdefault("consumed", {})[chat_id] = {"text": text.strip(), "kind": kind,
                                                 "at": now_local().isoformat()}
    write_state(state, path)


def take_consumed(text: str, *, chat_id: str | None = None, max_age_s: int = 600,
                  now: datetime | None = None, path: Path | None = None) -> dict | None:
    """Pop the marker if it is for this exact text and recent; else None (marker kept)."""
    chat_id = str(chat_id or coach_config()["chat_id"])
    state = read_state(path)
    mark = (state.get("consumed") or {}).get(chat_id)
    if not mark or mark.get("text") != text.strip():
        return None
    age = ((now or now_local()) - datetime.fromisoformat(mark["at"])).total_seconds()
    state["consumed"].pop(chat_id, None)
    write_state(state, path)
    return mark if age <= max_age_s else None


def clear_legacy_prompt(session: str, path: Path | None = None) -> None:
    """Reset the legacy awaiting-response keys if they point at `session` (skip, D48)."""
    state = read_state(path)
    if state.get("session") == session and state.get("awaiting_response"):
        state.update({"awaiting_response": False, "session": None, "prompt_sent_at": None})
        write_state(state, path)
        log("INFO", f"legacy prompt state cleared for {session}")
