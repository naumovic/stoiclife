#!/usr/bin/env python3
"""FEAT-05 — unit tests for status.is_late_morning and the status-line gate.

Covers the boundary conditions of the "a morning entry after 11:00 IS the safety-net
run" rule: session, cutoff edge, today-only, and the config kill switch. The coaching
gate in trigger_matrix.evaluate() consumes the same predicate, so this pins both.
Run: python3 tests/test_late_morning.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from status import is_late_morning, resolve_status_line  # noqa: E402

TODAY = "2026-08-11"
CFG = {
    "late_morning": {"enabled": True, "cutoff": "11:00"},
    "status_signal": {"enabled": True, "in_turn_sessions": ["evening"],
                      "ok_emoji": "🟢", "ok_line": "*stoiclife:* all ok",
                      "warn_emoji": "⚠️", "warn_line": "*stoiclife:* heads up —"},
}


def at(hhmm: str, date: str = TODAY) -> datetime:
    return datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M")


# (label, session, now, target_date, cfg, expected)
CASES = [
    ("morning prep at 07:30 — still deferred",  "morning",    at("07:30"), TODAY, CFG, False),
    ("morning at 10:59 — one minute early",     "morning",    at("10:59"), TODAY, CFG, False),
    ("morning at 11:00 — cutoff is inclusive",  "morning",    at("11:00"), TODAY, CFG, True),
    ("morning at 12:59 — the live miss",        "morning",    at("12:59"), TODAY, CFG, True),
    ("morning at 20:30 — still counts",         "morning",    at("20:30"), TODAY, CFG, True),
    ("evening is never 'late morning'",         "evening",    at("20:30"), TODAY, CFG, False),
    ("safety-net is never 'late morning'",      "safety-net", at("11:00"), TODAY, CFG, False),
    ("back-dated: clock today, entry yesterday", "morning",   at("12:59"), "2026-08-10", CFG, False),
    ("no clock (batch/tests) => off",           "morning",    None,        TODAY, CFG, False),
    ("no target date => off",                   "morning",    at("12:59"), None,  CFG, False),
    ("kill switch",                             "morning",    at("12:59"), TODAY,
     {**CFG, "late_morning": {"enabled": False, "cutoff": "11:00"}}, False),
    ("missing config block => off (strict FEAT-04)", "morning", at("12:59"), TODAY,
     {"status_signal": CFG["status_signal"]}, False),
    ("malformed cutoff => off",                 "morning",    at("12:59"), TODAY,
     {**CFG, "late_morning": {"enabled": True, "cutoff": "eleven"}}, False),
]

HEALTHY = {"ok": True, "reasons": [], "checks": {}}
SICK = {"ok": False, "reasons": ["sleep score not yet computed"], "checks": {}}

# (label, action, session, now, health, expected_signal, line_expected)
LINE_CASES = [
    ("late morning, silent + healthy => 🟢", "SILENT", "morning", at("12:59"), HEALTHY,
     "all_ok", True),
    ("late morning, silent + unhealthy => ⚠️", "SILENT", "morning", at("12:59"), SICK,
     "warning", True),
    ("early morning stays clean", "SILENT", "morning", at("07:30"), HEALTHY, "none", False),
    ("late morning that FIRED gets no line", "SEND_FULL", "morning", at("12:59"), HEALTHY,
     "none", False),
    ("evening unchanged", "SILENT", "evening", at("20:30"), HEALTHY, "all_ok", True),
    ("safety-net stays out-of-turn", "SILENT", "safety-net", at("11:00"), HEALTHY,
     "none", False),
]


def run() -> int:
    failures = 0
    for label, session, now, target_date, cfg, expected in CASES:
        got = is_late_morning(cfg, session, target_date, now)
        ok = got is expected
        failures += 0 if ok else 1
        print(f"[{'ok ' if ok else 'FAIL'}] {label} -> {got} (want {expected})")

    print()
    for label, action, session, now, health, exp_signal, exp_line in LINE_CASES:
        signal, line = resolve_status_line(CFG, action, session, health,
                                           target_date=TODAY, now=now)
        ok = signal == exp_signal and bool(line) is exp_line
        failures += 0 if ok else 1
        print(f"[{'ok ' if ok else 'FAIL'}] {label} -> {signal!r}, line={line!r}")

    total = len(CASES) + len(LINE_CASES)
    print(f"\n{total - failures}/{total} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
