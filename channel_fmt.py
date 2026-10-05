#!/usr/bin/env python3
"""Coaching migration Phase 3 — per-channel text formatting.

All stoiclife text is authored in one canonical style: WhatsApp's, where `*x*` is
bold. This module converts it at the edge for the channel that will deliver it.

The only difference that matters today is bold. OpenClaw sends Telegram text as
Markdown, where `*x*` is *italic* and bold needs `**x**` (checked against
2026.6.8's `markdownToTelegramHtml`: `*stoiclife:*` -> `<i>`, `**x**` -> `<b>`).

The channel comes from `--channel` on each CLI, else `STOICLIFE_CHANNEL`, else
WhatsApp. It is per invocation, not a config switch, because the WhatsApp and
Telegram crons run side by side until the Phase 4 cutover.
"""
from __future__ import annotations

import os
import re

CHANNELS = ("whatsapp", "telegram")
DEFAULT_CHANNEL = "whatsapp"
ENV_VAR = "STOICLIFE_CHANNEL"

# A single-asterisk span: `*x*` not touching another `*` (so `**x**` is left alone).
_WA_BOLD = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def resolve(channel: str | None = None) -> str:
    """The channel to format for: explicit value > $STOICLIFE_CHANNEL > whatsapp."""
    value = (channel or os.environ.get(ENV_VAR) or DEFAULT_CHANNEL).strip().lower()
    if value not in CHANNELS:
        raise ValueError(f"unknown channel '{value}' (expected one of {', '.join(CHANNELS)})")
    return value


def bold(text: str, channel: str) -> str:
    return f"**{text}**" if channel == "telegram" else f"*{text}*"


def render(text: str, channel: str) -> str:
    """Convert canonical (WhatsApp-style) text for `channel`."""
    if channel == "telegram":
        return _WA_BOLD.sub(r"**\1**", text)
    return text
