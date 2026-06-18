#!/usr/bin/env python3
"""FEAT-03 Step 2 — unit tests for save_entry.parse_manual_mood.

save_entry.py lives in the shared OpenClaw scripts dir, not this repo, so we add
it to sys.path and import the pure parse function (importing is side-effect free —
main() is guarded). Run: python3 tests/test_manual_mood.py
"""
import sys
from pathlib import Path

SCRIPTS = Path.home() / ".openclaw" / "workspace" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from save_entry import parse_manual_mood, MANUAL_MOOD_DEFAULTS  # noqa: E402

CFG = dict(MANUAL_MOOD_DEFAULTS)  # enabled, keyword=mood, min=1, max=10

# (input, expected_score, expected_stored_text, expected_source, expect_note)
CASES = [
    # --- valid manual moods ---
    ("mood 7",                              7,    "",                 "manual",   False),
    ("mood: 7",                             7,    "",                 "manual",   False),
    ("Mood7",                               7,    "",                 "manual",   False),
    ("mood 7 — today was steady, BJJ am",   7,    "today was steady, BJJ am", "manual", False),
    ("mood: 8 - solid day",                 8,    "solid day",        "manual",   False),
    ("Mood 9. Felt good",                   9,    "Felt good",        "manual",   False),
    ("mood 10 great session",               10,   "great session",    "manual",   False),  # max boundary
    ("mood 1, rough night",                 1,    "rough night",      "manual",   False),  # min boundary
    # defensive: a leading session prefix is stripped before the anchor test
    ("evening review: mood 6 — ok day",     6,    "ok day",           "manual",   False),
    # --- token-like but out of range / malformed: ignore, fall back to inference ---
    ("mood 12 way too high",                None, "mood 12 way too high", "inferred", True),
    ("mood 0",                              None, "mood 0",           "inferred", True),
    # --- not a manual mood at all: text preserved verbatim, inference runs ---
    ("mood swings all day",                 None, "mood swings all day", "inferred", False),
    ("today was just fine",                 None, "today was just fine", "inferred", False),
]


def run() -> int:
    failures = 0
    for text, exp_score, exp_text, exp_source, exp_note in CASES:
        score, stored, source, note = parse_manual_mood(text, CFG)
        ok = (score == exp_score and stored == exp_text and source == exp_source
              and bool(note) == exp_note)
        status = "ok " if ok else "FAIL"
        if not ok:
            failures += 1
            print(f"[{status}] {text!r}\n       got=({score!r}, {stored!r}, {source!r}, note={bool(note)})"
                  f"\n       exp=({exp_score!r}, {exp_text!r}, {exp_source!r}, note={exp_note})")
        else:
            print(f"[{status}] {text!r} -> ({score!r}, {stored!r}, {source})")

    # disabled config: even a valid token is left for inference
    score, stored, source, note = parse_manual_mood("mood 7", {**CFG, "enabled": False})
    ok = (score is None and stored == "mood 7" and source == "inferred")
    print(f"[{'ok ' if ok else 'FAIL'}] disabled -> ({score!r}, {stored!r}, {source})")
    failures += 0 if ok else 1

    print(f"\n{len(CASES) + 1 - failures}/{len(CASES) + 1} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
