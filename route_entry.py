#!/usr/bin/env python3
"""FEAT-07 Phase 4: decide where an inbound coach-chat message goes (D40, D41, D44–D46).

Called from the plugin's awaited `before_dispatch` hook via sc_dispatch.py, before the
coach agent is involved. Priority:

  0. a tapped hold coming back as `callback_data: sc:hold:<e|c>:<id>` → the held text;
     a tapped 🧭 "Yes, full read" (`callback_data: sc:clar:<id>:y`) → clarify (MIN-132);
     a `/command` → passthrough (OpenClaw / plugin commands, never routed)
  1. a legacy prefix (`morning prep:` …)              → entry, that session, prefix stripped
  2. a reply to a stored prompt message               → entry, that prompt's session
  3. a pending note / "Tell me more"                  → note (saved here, LLM-free, D42)
  4. a pending ✍️ Write / `/journal`                  → entry, its session (D49)
  4b. an open CLARIFY 🧭 question and a bare yes / no  → clarify / clarify_no (MIN-132)
  5. an open prompt, inside its window:
       ends in `?` → hold [📝 It's my entry] [❓ It's a question]   (D46)
       otherwise   → entry                                           (D45)
  6. an open prompt, past its window (until the next prompt)
                   → hold [📝 Save as <session> prep] [💬 Just chatting] (D45)
  7. otherwise → conversation

`decide()` is pure apart from reading the DB/state; it never sends or writes.
Holds live in state.json (`holds`, one slot per chat, D44).
"""
from __future__ import annotations

import re
from datetime import datetime

import checkins
import clarify
import prompts
import tg

PREFIXES = {"morning prep:": "morning", "evening review:": "evening"}
HOLD_CB_RE = re.compile(r"^callback_data:\s*sc:hold:([ec]):(\d+)\s*$")
CLAR_CB_RE = re.compile(r"^callback_data:\s*sc:clar:(\d+):y\s*$")
NOTE_KINDS = re.compile(r"^(fb_more:[rt]\d+|note:(mood|module):\d{8})$")
WRITE_RE = re.compile(r"^write:(morning|evening)$")


def strip_prefix(text: str) -> tuple[str | None, str]:
    body = text.lstrip()
    for prefix, session in PREFIXES.items():
        if body[: len(prefix)].lower() == prefix:
            return session, body[len(prefix):].lstrip()
    return None, text


def is_question(text: str) -> bool:
    return text.rstrip().endswith("?")


def decide(conn, *, chat_id: str, text: str, reply_to_id=None, now: datetime | None = None,
           state_path=None) -> dict:
    """Return {route, session, source, text, prompt_id?, hold_kind?, hold_id?, note_kind?}."""
    now = now or checkins.now_local()
    chat_id = str(chat_id)

    # 0. a resolved hold, re-entering as the synthetic tap message
    m = HOLD_CB_RE.match(text.strip())
    if m:
        hold = get_hold(chat_id, path=state_path)
        if hold and hold["id"] == int(m.group(2)) and hold.get("resolved"):
            if hold["resolved"] == "entry":
                return {"route": "entry", "session": hold["session"], "source": "hold",
                        "text": hold["text"], "prompt_id": hold.get("prompt_id"), "hold_id": hold["id"]}
            return {"route": "conversation", "session": None, "source": "hold",
                    "text": hold["text"], "hold_id": hold["id"]}
        return {"route": "conversation", "session": None, "source": "stale_hold", "text": ""}

    # 0b. a tapped 🧭 "Yes, full read" (sc_dispatch already recorded the answer)
    m = CLAR_CB_RE.match(text.strip())
    if m:
        c = clarify.get(conn, int(m.group(1)))
        if c and c["answer"] == "yes" and c["answer_source"] == "button" and not c["route_id"]:
            return {"route": "clarify", "session": None, "source": "button", "text": "yes",
                    "clarify_id": c["id"]}
        return {"route": "conversation", "session": None, "source": "stale_clarify", "text": ""}

    if text.lstrip().startswith("/"):
        return {"route": "passthrough", "session": None, "source": "command", "text": text}

    # 1. legacy prefix
    session, body = strip_prefix(text)
    if session:
        p = prompts.open_prompt(conn, chat_id, now)
        return {"route": "entry", "session": session, "source": "prefix", "text": body,
                "prompt_id": p["id"] if p and p["session"] == session else None}

    # 2. reply to a prompt message (even if its window has passed)
    p = prompts.by_message(conn, chat_id, reply_to_id)
    if p:
        return {"route": "entry", "session": p["session"], "source": "reply", "text": text,
                "prompt_id": p["id"]}

    # 3. pending note / Tell me more (one pending slot, D36)
    pending = tg.get_pending(chat_id, now=now, path=state_path)
    pkind = (pending or {}).get("kind") or ""
    if NOTE_KINDS.match(pkind) and text.strip():
        return {"route": "note", "session": None, "source": "note", "text": text, "note_kind": pkind}


    # 4. explicit intent: ✍️ Write / /journal
    w = WRITE_RE.match(pkind)
    if w:
        op = prompts.open_prompt(conn, chat_id, now)
        return {"route": "entry", "session": w.group(1), "source": "write", "text": text,
                "prompt_id": op["id"] if op and op["session"] == w.group(1) else None}

    # 4b. an open CLARIFY question: only a bare yes / no counts as the answer
    c = clarify.pending(conn, chat_id, now)
    if c:
        ans = clarify.parse_answer(text)
        if ans:
            return {"route": "clarify" if ans == "yes" else "clarify_no", "session": None,
                    "source": "typed", "text": text, "clarify_id": c["id"]}

    # 5./6. an open prompt
    op = prompts.open_prompt(conn, chat_id, now)
    if op:
        base = {"session": op["session"], "text": text, "prompt_id": op["id"]}
        if prompts.in_window(op, now):
            if is_question(text):
                return {"route": "hold", "source": "window", "hold_kind": "question", **base}
            return {"route": "entry", "source": "window", **base}
        return {"route": "hold", "source": "late", "hold_kind": "late", **base}

    # 7.
    return {"route": "conversation", "session": None, "source": "none", "text": text}


# --- holds (D44) -------------------------------------------------------------------

def hold_buttons(hold: dict) -> list:
    hid, session = hold["id"], hold["session"]
    if hold["kind"] == "question":
        return [[{"text": "📝 It's my entry", "callback_data": f"sc:hold:e:{hid}"},
                 {"text": "❓ It's a question", "callback_data": f"sc:hold:c:{hid}"}]]
    label = "morning prep" if session == "morning" else "evening review"
    return [[{"text": f"📝 Save as {label}", "callback_data": f"sc:hold:e:{hid}"},
             {"text": "💬 Just chatting", "callback_data": f"sc:hold:c:{hid}"}]]


def hold_question(hold: dict) -> str:
    label = "morning prep" if hold["session"] == "morning" else "evening review"
    if hold["kind"] == "question":
        return f"Is that part of your {label}, or a question for me?"
    return f"Your {label} is still open. Save that message as it, or are we just chatting?"


def chosen_label(hold: dict, choice: str) -> str:
    label = "morning prep" if hold["session"] == "morning" else "evening review"
    if choice == "entry":
        return f"✓ Saved as {label}"
    return "✓ It's a question" if hold["kind"] == "question" else "✓ Just chatting"


def new_hold(chat_id: str, decision: dict, *, now: datetime | None = None, path=None) -> dict:
    state = tg.read_state(path)
    seq = int(state.get("hold_seq") or 0) + 1
    hold = {"id": seq, "kind": decision["hold_kind"], "session": decision["session"],
            "text": decision["text"], "prompt_id": decision.get("prompt_id"),
            "created_at": (now or checkins.now_local()).isoformat(), "resolved": None,
            "message_id": None}
    state["hold_seq"] = seq
    state.setdefault("holds", {})[str(chat_id)] = hold
    tg.write_state(state, path)
    return hold


def get_hold(chat_id: str, path=None) -> dict | None:
    return (tg.read_state(path).get("holds") or {}).get(str(chat_id))


def update_hold(chat_id: str, path=None, **fields) -> dict | None:
    state = tg.read_state(path)
    hold = (state.get("holds") or {}).get(str(chat_id))
    if not hold:
        return None
    hold.update(fields)
    tg.write_state(state, path)
    return hold


def clear_hold(chat_id: str, path=None) -> None:
    state = tg.read_state(path)
    if (state.get("holds") or {}).pop(str(chat_id), None) is not None:
        tg.write_state(state, path)
