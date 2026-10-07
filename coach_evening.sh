#!/usr/bin/env bash
# Coach evening message: Stoic evening review, for the Telegram coach bot (FEAT-07 D50).
# Run by the "Coach Evening Review (20:30)" command cron; stdout is delivered verbatim.
# send_prompt.py sends it with buttons and prints NO_REPLY (or the text, if sending fails).
#
# Replaces ~/.openclaw/workspace/scripts/evening-prompt.sh for the coach bot only; that
# script stays as it is for the WhatsApp rollback path.
#
# STOICLIFE_SKIP_PROMPT_STATE=1 skips set_prompt_state.py and prompt recording (test runs).
set -euo pipefail

WS_SCRIPTS="$HOME/.openclaw/workspace/scripts"
source "$WS_SCRIPTS/active-tz.sh"

if [ "${STOICLIFE_SKIP_PROMPT_STATE:-}" != "1" ]; then
  python3 "$WS_SCRIPTS/set_prompt_state.py" --session evening >/dev/null 2>&1 || true
fi

TITLE="🌙 Evening review · $(TZ="$EWOK_TZ" date '+%a %-d %b')"
# The prompt file's first line is its own title ("🌙 Evening Review"); ours replaces it.
PROMPTS=$(sed '1{/Evening Review/d}' "$HOME/.openclaw/workspace/stoic/prompts/evening_prompt.txt" | sed '/./,$!d')
OUT="$TITLE"$'\n\n'"$PROMPTS"$'\n\n'"Just type below to journal ↓"

printf '%s' "$OUT" | python3 "$HOME/projects/stoiclife/send_prompt.py" --session evening || echo "$OUT"
