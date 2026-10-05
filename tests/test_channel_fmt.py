#!/usr/bin/env python3
"""Coaching migration Phase 3 — unit tests for per-channel formatting.

Pins the WhatsApp -> Telegram bold conversion (`*x*` -> `**x**`), channel resolution
(flag > $STOICLIFE_CHANNEL > whatsapp), the validator's per-channel labels, and the
status line. WhatsApp output must stay byte-for-byte unchanged.
Run: python3 tests/test_channel_fmt.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import channel_fmt  # noqa: E402
from coaching_format import validate  # noqa: E402
from status import resolve_status_line  # noqa: E402

WA_MSG = """🧭 stoiclife — Running on Fumes
*Observation:* HRV down 18% on 5h40 of sleep.
*Correlation:* Tuesday's review named the deadline twice.
1. Move the hard call to the morning.
2. Lights out by 22:00."""
TG_MSG = WA_MSG.replace("*Observation:*", "**Observation:**").replace(
    "*Correlation:*", "**Correlation:**")

# (label, text, channel, expected)
RENDER_CASES = [
    ("whatsapp is untouched", "🟢 *stoiclife:* all ok", "whatsapp", "🟢 *stoiclife:* all ok"),
    ("telegram bolds a label", "🟢 *stoiclife:* all ok", "telegram", "🟢 **stoiclife:** all ok"),
    ("telegram: two spans on one line", "a *yes* and *no*", "telegram", "a **yes** and **no**"),
    ("telegram: already-bold left alone", "**done**", "telegram", "**done**"),
    ("telegram: span never crosses a line", "*open\nclose*", "telegram", "*open\nclose*"),
    ("telegram: lone asterisk left alone", "5 * 3 = 15", "telegram", "5 * 3 = 15"),
    ("telegram: whole weekly header", "🧭 *stoiclife — weekly review*", "telegram",
     "🧭 **stoiclife — weekly review**"),
]

# (label, text, channel, expected_ok)
VALIDATE_CASES = [
    ("whatsapp message on whatsapp", WA_MSG, "whatsapp", True),
    ("telegram message on telegram", TG_MSG, "telegram", True),
    ("whatsapp bold rejected on telegram (would render italic)", WA_MSG, "telegram", False),
    ("telegram bold rejected on whatsapp", TG_MSG, "whatsapp", False),
    ("default channel is whatsapp", WA_MSG, None, True),
]

CFG = {"status_signal": {"enabled": True, "in_turn_sessions": ["evening"],
                         "ok_emoji": "🟢", "ok_line": "*stoiclife:* all ok",
                         "warn_emoji": "⚠️", "warn_line": "*stoiclife:* heads up —"}}
HEALTHY = {"ok": True, "reasons": [], "checks": {}}
SICK = {"ok": False, "reasons": ["sleep score not yet computed"], "checks": {}}
NOW = datetime(2026, 10, 6, 20, 30)

# (label, health, channel, expected_line)
STATUS_CASES = [
    ("all ok, whatsapp", HEALTHY, "whatsapp", "🟢 *stoiclife:* all ok"),
    ("all ok, telegram", HEALTHY, "telegram", "🟢 **stoiclife:** all ok"),
    ("warning, telegram", SICK, "telegram",
     "⚠️ **stoiclife:** heads up — sleep score not yet computed"),
]


def check(label: str, ok: bool, detail: str) -> int:
    print(f"[{'ok ' if ok else 'FAIL'}] {label} -> {detail}")
    return 0 if ok else 1


def run() -> int:
    failures = total = 0
    for label, text, channel, expected in RENDER_CASES:
        got = channel_fmt.render(text, channel)
        failures += check(label, got == expected, repr(got))
        total += 1

    print()
    for label, text, channel, expected in VALIDATE_CASES:
        ok, errors = validate(text) if channel is None else validate(text, channel)
        failures += check(label, ok is expected, f"valid={ok} {errors}")
        total += 1

    print()
    for label, health, channel, expected in STATUS_CASES:
        _, line = resolve_status_line(CFG, "SILENT", "evening", health, now=NOW, channel=channel)
        failures += check(label, line == expected, repr(line))
        total += 1

    print()
    saved = os.environ.pop(channel_fmt.ENV_VAR, None)
    try:
        failures += check("resolve: nothing set => whatsapp",
                          channel_fmt.resolve() == "whatsapp", channel_fmt.resolve())
        os.environ[channel_fmt.ENV_VAR] = "Telegram"
        failures += check("resolve: env (any case) => telegram",
                          channel_fmt.resolve() == "telegram", channel_fmt.resolve())
        failures += check("resolve: flag beats env",
                          channel_fmt.resolve("whatsapp") == "whatsapp",
                          channel_fmt.resolve("whatsapp"))
        try:
            channel_fmt.resolve("sms")
            failures += check("resolve: unknown channel raises", False, "no error")
        except ValueError as e:
            failures += check("resolve: unknown channel raises", True, str(e))
        total += 4
    finally:
        os.environ.pop(channel_fmt.ENV_VAR, None)
        if saved is not None:
            os.environ[channel_fmt.ENV_VAR] = saved

    print(f"\n{total - failures}/{total} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
