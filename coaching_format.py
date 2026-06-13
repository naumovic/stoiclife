#!/usr/bin/env python3
"""Strict-format validator for stoiclife coaching messages (Phase 3/4).

The required shape (plain text, WhatsApp-safe):

    🧭 stoiclife — [State]
    *Observation:* <one line>
    *Correlation:* <one line>
    1. <actionable recommendation>
    2. <actionable recommendation>

Rules enforced: the header line, an Observation line, a Correlation line, and
EXACTLY two numbered recommendations (1. and 2., no 3.). No markdown tables or
ATX headers. Importable as `validate(text)`; also a stdin CLI.

Usage:
    echo "<message>" | python3 coaching_format.py
"""
from __future__ import annotations

import re
import sys

HEADER_PREFIX = "🧭 stoiclife —"
OBSERVATION = "*Observation:*"
CORRELATION = "*Correlation:*"


def validate(text: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]

    if not lines:
        return False, ["empty message"]

    if not lines[0].startswith(HEADER_PREFIX):
        errors.append(f"first line must start with '{HEADER_PREFIX}'")

    if not any(ln.startswith(OBSERVATION) for ln in lines):
        errors.append(f"missing '{OBSERVATION}' line")
    if not any(ln.startswith(CORRELATION) for ln in lines):
        errors.append(f"missing '{CORRELATION}' line")

    numbered = [ln for ln in lines if re.match(r"^\d+\.\s+\S", ln)]
    labels = [ln.split(".", 1)[0] for ln in numbered]
    if labels != ["1", "2"]:
        errors.append(
            f"must have exactly two numbered recommendations '1.' and '2.' "
            f"(found {labels or 'none'})"
        )

    # WhatsApp formatting guards.
    if any(ln.startswith("#") for ln in lines):
        errors.append("markdown headers (#) are not allowed")
    if any("|" in ln and ln.count("|") >= 2 for ln in lines):
        errors.append("markdown tables are not allowed")

    return (not errors), errors


def main() -> int:
    text = sys.stdin.read()
    ok, errors = validate(text)
    if ok:
        print("OK — valid coaching format")
        return 0
    print("INVALID:")
    for e in errors:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
