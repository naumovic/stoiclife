#!/usr/bin/env python3
"""MIN-129: the prompt message's buttons, check-in first, then the journal entry.

The morning/evening prompt walks through its steps in place (editButtons, never a text
edit: P2-D5), so the whole check-in is taps on the one message:

  1  [🙂 Check in] [Skip]
  2  [1]..[5] / [6]..[10]                                   (mood)
  3  [✓ Mood 6] / [Emotions][Creativity][Happiness] / [No module]
  4  [✓ Mood 6 · Happiness] / [✍️ Write entry] [Skip today]

Skip at step 1 jumps to step 4 ("Check-in skipped"). A prompt sent when a mood is already
logged that day starts at step 4. Callbacks: `sc:pc:<prompt id>:<go|skip|m<n>|k<module|none>>`
(sc_dispatch.handle_prompt_checkin); step 4 reuses `sc:write` / `sc:skip`.
"""
from __future__ import annotations

MODULE_KEYS = ("emotions", "creativity", "happiness")


def btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def status_label(state: dict, skipped: bool = False) -> str:
    if skipped:
        return "Check-in skipped"
    mood = (state.get("mood") or {}).get("value")
    module = (state.get("module") or {}).get("value")
    parts = [f"Mood {mood}"] if mood else []
    if module:
        parts.append(module.capitalize())
    return "✓ " + " · ".join(parts) if parts else "Check-in skipped"


def start_stage(state: dict) -> int:
    """Where a new prompt starts: step 4 if a mood is already logged that day."""
    return 4 if (state.get("mood") or {}).get("value") else 1


def rows(stage: int, prompt: dict, state: dict, *, skipped: bool = False) -> list:
    pid, session = prompt["id"], prompt["session"]
    pc = f"sc:pc:{pid}:"
    if stage == 1:
        return [[btn("🙂 Check in", pc + "go"), btn("Skip", pc + "skip")]]
    if stage == 2:
        return [[btn(str(n), f"{pc}m{n}") for n in range(1, 6)],
                [btn(str(n), f"{pc}m{n}") for n in range(6, 11)]]
    if stage == 3:
        return [[btn(status_label(state), "sc:noop")],
                [btn(k.capitalize(), f"{pc}k{k}") for k in MODULE_KEYS],
                [btn("No module", pc + "knone")]]
    return [[btn(status_label(state, skipped), "sc:noop")],
            [btn("✍️ Write entry", f"sc:write:{session}:{pid}"),
             btn("Skip today", f"sc:skip:{session}:{pid}")]]


def as_tuples(dict_rows: list) -> list:
    """tg.send takes (label, value) pairs."""
    return [[(b["text"], b["callback_data"]) for b in r] for r in dict_rows]
