#!/usr/bin/env python3
"""FEAT-06 — tests for Stoic modules: the STOIC-MODULES.md loader and inline
`module:<name>` parsing (alone, and together with `mood N` in every order).

stoic_modules.py and save_entry.py live in the shared OpenClaw scripts dir, not
this repo, so we add it to sys.path (imports are side-effect free).
Run: python3 tests/test_stoic_modules.py
"""
import sys
from pathlib import Path

SCRIPTS = Path.home() / ".openclaw" / "workspace" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from save_entry import MANUAL_MOOD_DEFAULTS, parse_inline_tags  # noqa: E402
from stoic_modules import STOIC_MODULES_DEFAULTS, load_modules, parse_module  # noqa: E402

MODULES_PATH = Path(__file__).resolve().parent.parent / "coach-workspace" / "STOIC-MODULES.md"
ALIASES = load_modules(MODULES_PATH)
MOOD_CFG = dict(MANUAL_MOOD_DEFAULTS)
MOD_CFG = dict(STOIC_MODULES_DEFAULTS)

failures = 0
total = 0


def check(label, ok, detail=""):
    global failures, total
    total += 1
    if not ok:
        failures += 1
    print(f"[{'ok ' if ok else 'FAIL'}] {label}" + (f"\n       {detail}" if not ok and detail else ""))


# --- loader ---
by_key = {m.key: m for m in ALIASES.values()}
check("3 modules loaded", sorted(by_key) == ["creativity", "emotions", "happiness"], sorted(by_key))
check("principle counts 9/3/5",
      [len(by_key[k].principles) for k in ("happiness", "creativity", "emotions")] == [9, 3, 5],
      [len(m.principles) for m in by_key.values()])
check("numbers are aliases", [ALIASES[n].key for n in "123"] == ["happiness", "creativity", "emotions"])
check("typo alias 'hapiness'", ALIASES.get("hapiness") is by_key["happiness"])
check("Kodawari bullet kept verbatim",
      by_key["happiness"].principles[-1].endswith("Kodawari is a nagomi between your ideals and the reality of the status quo."))
check("missing file -> {}", load_modules("/nonexistent/STOIC-MODULES.md") == {})

# --- module token alone: (input, expected_key, expected_text, expect_note) ---
CASES = [
    ("module:emotions rough morning",            "emotions",   "rough morning",              False),
    ("Module: Happiness — calm day",             "happiness",  "calm day",                   False),
    ("module:hapiness - typo still works",       "happiness",  "typo still works",           False),
    ("module:2 building the app",                "creativity", "building the app",           False),
    ("good day with the kids. module:happiness", "happiness",  "good day with the kids.",    False),
    ("long day, module: emotions",               "emotions",   "long day",                   False),
    ("finished the build module:creativity!",    "creativity", "finished the build",         False),
    ("module:courage tough one",                 None,         "module:courage tough one",   True),   # unknown
    ("module 2 of the course was hard",          None,         "module 2 of the course was hard", False),  # no colon = prose
    ("the module: emotions part was good today", None,         "the module: emotions part was good today", False),  # mid-sentence
    ("just a normal entry",                      None,         "just a normal entry",        False),
]
for text, key, exp_text, exp_note in CASES:
    got_key, got_text, note = parse_module(text, ALIASES)
    check(f"module {text!r}", (got_key, got_text, bool(note)) == (key, exp_text, exp_note),
          f"got=({got_key!r}, {got_text!r}, note={note!r})")

# --- module + mood in every order: (input, mood, mood_source, module, text) ---
COMBOS = [
    ("module:emotions mood:6 rough start",                6,    "manual",   "emotions",   "rough start"),
    ("mood 6 module:emotions rough start",                6,    "manual",   "emotions",   "rough start"),
    ("rough start, kids were great. mood:7 module:happiness", 7, "manual", "happiness",  "rough start, kids were great."),
    ("rough start, kids were great. module:happiness mood:7", 7, "manual", "happiness",  "rough start, kids were great."),
    ("module:creativity built the parser. mood 8",        8,    "manual",   "creativity", "built the parser."),
    ("mood 5 — slow day module:emotions",                 5,    "manual",   "emotions",   "slow day"),
    ("morning prep: module:emotions mood:6 tired",        6,    "manual",   "emotions",   "tired"),  # defensive prefix
    ("feeling better. mood:7",                            7,    "manual",   None,         "feeling better."),  # FEAT-03 unchanged
    ("quiet day module:happiness",                        None, "inferred", "happiness",  "quiet day"),
    ("quiet day module:courage mood 6",                   6,    "manual",   None,         "quiet day module:courage"),  # unknown kept
    ("plain entry",                                       None, "inferred", None,         "plain entry"),
]
for text, mood, src, key, exp_text in COMBOS:
    m, t, s, k, _notes = parse_inline_tags(text, MOOD_CFG, MOD_CFG, ALIASES)
    check(f"combo {text!r}", (m, s, k, t) == (mood, src, key, exp_text),
          f"got=({m!r}, {s!r}, {k!r}, {t!r})")

# disabled modules: token left for the coach to see, mood still parsed
m, t, s, k, _ = parse_inline_tags("ok day module:emotions mood 6", MOOD_CFG, {**MOD_CFG, "enabled": False}, ALIASES)
check("modules disabled", (m, k, t) == (6, None, "ok day module:emotions"), f"got=({m!r}, {k!r}, {t!r})")

print(f"\n{total - failures}/{total} passed.")
sys.exit(1 if failures else 0)
