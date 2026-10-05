#!/usr/bin/env python3
"""Strict-format validator for stoiclife coaching messages (Phase 3/4).

The required shape (plain text; shown in WhatsApp style, see channel_fmt for Telegram):

    🧭 stoiclife — [State]
    *Observation:* <one line>
    *Correlation:* <one line>
    1. <actionable recommendation>
    2. <actionable recommendation>

Rules enforced: the header line, an Observation line, a Correlation line, and
EXACTLY two numbered recommendations (1. and 2., no 3.). No markdown tables or
ATX headers. The label bold is per channel: `*Observation:*` on WhatsApp,
`**Observation:**` on Telegram. Importable as `validate(text, channel)`; also a stdin CLI.

Usage:
    echo "<message>" | python3 coaching_format.py [--channel telegram]
"""
from __future__ import annotations

import argparse
import re
import sys

import channel_fmt

HEADER_PREFIX = "🧭 stoiclife —"
# WhatsApp (canonical) labels; labels(channel) gives the per-channel form.
OBSERVATION = "*Observation:*"
CORRELATION = "*Correlation:*"


def labels(channel: str = channel_fmt.DEFAULT_CHANNEL) -> tuple[str, str]:
    """(observation, correlation) labels as the model must write them on `channel`."""
    return (channel_fmt.render(OBSERVATION, channel),
            channel_fmt.render(CORRELATION, channel))


def validate(text: str, channel: str = channel_fmt.DEFAULT_CHANNEL) -> tuple[bool, list[str]]:
    errors: list[str] = []
    observation, correlation = labels(channel)
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]

    if not lines:
        return False, ["empty message"]

    if not lines[0].startswith(HEADER_PREFIX):
        errors.append(f"first line must start with '{HEADER_PREFIX}'")

    if not any(ln.startswith(observation) for ln in lines):
        errors.append(f"missing '{observation}' line")
    if not any(ln.startswith(correlation) for ln in lines):
        errors.append(f"missing '{correlation}' line")

    numbered = [ln for ln in lines if re.match(r"^\d+\.\s+\S", ln)]
    numbers = [ln.split(".", 1)[0] for ln in numbered]
    if numbers != ["1", "2"]:
        errors.append(
            f"must have exactly two numbered recommendations '1.' and '2.' "
            f"(found {numbers or 'none'})"
        )

    # Formatting guards (both channels).
    if any(ln.startswith("#") for ln in lines):
        errors.append("markdown headers (#) are not allowed")
    if any("|" in ln and ln.count("|") >= 2 for ln in lines):
        errors.append("markdown tables are not allowed")

    return (not errors), errors


def main() -> int:
    p = argparse.ArgumentParser(description="Validate a stoiclife coaching message (stdin).")
    p.add_argument("--channel", choices=channel_fmt.CHANNELS, default=None,
                   help=f"default: ${channel_fmt.ENV_VAR}, else {channel_fmt.DEFAULT_CHANNEL}")
    args = p.parse_args()
    text = sys.stdin.read()
    ok, errors = validate(text, channel_fmt.resolve(args.channel))
    if ok:
        print("OK — valid coaching format")
        return 0
    print("INVALID:")
    for e in errors:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
