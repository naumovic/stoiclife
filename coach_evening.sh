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
# MIN-135: last night's sleep/HRV(vs 7-day)/RHR, the same 📊 line as the 11:00 update. No steps:
# Fitbit last syncs at 10:00. Must never block the message: empty on no data or any error.
HEALTH=$(cd "$HOME/projects/stoiclife" && timeout 15 python3 daily_update.py --data-line 2>/dev/null || true)
# The prompt file's first line is its own title ("🌙 Evening Review"); ours replaces it.
PROMPTS=$(sed '1{/Evening Review/d}' "$HOME/.openclaw/workspace/stoic/prompts/evening_prompt.txt" | sed '/./,$!d')
# MIN-137: bold the section headings for Telegram (the file stays plain: WhatsApp rollback uses it).
PROMPTS=$(printf '%s' "$PROMPTS" | python3 "$HOME/projects/stoiclife/channel_fmt.py" headings telegram 2>/dev/null || printf '%s' "$PROMPTS")
OUT="$TITLE"
[ -n "$HEALTH" ] && OUT+=$'\n'"$HEALTH"
OUT+=$'\n\n'"$PROMPTS"$'\n\n'"Just type below to journal ↓"
# MIN-136: no evening mood step (one check-in a day, the morning's); the coach infers the
# evening mood unless the entry starts or ends with `mood N` (save_entry.py, FEAT-03).
OUT+=$'\n'"Add mood: N if you like."

printf '%s' "$OUT" | python3 "$HOME/projects/stoiclife/send_prompt.py" --session evening || echo "$OUT"
