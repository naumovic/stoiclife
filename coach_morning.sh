#!/usr/bin/env bash
# Coach morning message: yesterday's HRV/RHR/steps line + Stoic morning prep, for the Telegram coach bot.
# Run by the "Coach Morning (07:30)" command cron; stdout is delivered verbatim. Since FEAT-07
# Phase 4 the message is sent by send_prompt.py (with buttons) and stdout is just NO_REPLY.
#
# The coaching half of ~/.openclaw/workspace/scripts/morning-brief.sh (calendar/system stay
# on the WhatsApp brief). Keep the Health Snapshot block in step with the brief's until
# Phase 4 switches those sections off there.
#
# STOICLIFE_SKIP_PROMPT_STATE=1 skips set_prompt_state.py, so a test run doesn't make the
# next "morning prep:" reply attribute to it.
set -euo pipefail

WS_SCRIPTS="$HOME/.openclaw/workspace/scripts"
source "$WS_SCRIPTS/active-tz.sh"

# Must never block the message: errors are swallowed (set_prompt_state.py logs its own).
if [ "${STOICLIFE_SKIP_PROMPT_STATE:-}" != "1" ]; then
  python3 "$WS_SCRIPTS/set_prompt_state.py" --session morning >/dev/null 2>&1 || true
fi

# --- MESSAGE (FEAT-07 Phase 4 layout, D47) ---
TITLE="☀️ Morning prep · $(TZ="$EWOK_TZ" date '+%a %-d %b')"
YLABEL=$(TZ="$EWOK_TZ" date -d yesterday '+%a')

# --- HEALTH (Fitbit biometrics, yesterday's row: the wearable hasn't synced today yet) ---
# No sleep here (MIN-135): yesterday's row holds the night before yesterday; last night's
# sleep is in the 11:00 update and the evening review.
YDAY=$(TZ="$EWOK_TZ" date -d yesterday '+%F')
BIO=$(sqlite3 -separator '|' "$HOME/.openclaw/stoic/stoic_journal.db" \
  "SELECT COALESCE(hrv_rmssd_ms,''), COALESCE(resting_hr_bpm,''),
          COALESCE(steps,'')
   FROM biometrics WHERE date='${YDAY}';" 2>/dev/null || true)
PARTS=()
if [ -n "$BIO" ]; then
  IFS='|' read -r HRV RHR STEPS <<< "$BIO"
  [ -n "$HRV" ] && PARTS+=("HRV ${HRV%.*} ms")
  [ -n "$RHR" ] && PARTS+=("RHR ${RHR} bpm")
  [ -n "$STEPS" ] && PARTS+=("$(printf "%'d" "$STEPS") steps")
fi
HEALTH=""
if [ ${#PARTS[@]} -gt 0 ]; then
  HEALTH="Yesterday (${YLABEL}): $(IFS='·'; echo "${PARTS[*]}" | sed 's/·/ · /g')"
fi

# The prompt file's first line is its own title ("🌅 Morning Prep"); ours replaces it.
PROMPTS=$(sed '1{/Morning Prep/d}' "$HOME/.openclaw/workspace/stoic/prompts/morning_prompt.txt" | sed '/./,$!d')
# MIN-137: bold the section headings for Telegram (the file stays plain: WhatsApp rollback uses it).
PROMPTS=$(printf '%s' "$PROMPTS" | python3 "$HOME/projects/stoiclife/channel_fmt.py" headings telegram 2>/dev/null || printf '%s' "$PROMPTS")

OUT="$TITLE"
[ -n "$HEALTH" ] && OUT+=$'\n'"$HEALTH"
OUT+=$'\n\n'"$PROMPTS"$'\n\n'"Just type below to journal ↓"

# Sends with buttons and prints NO_REPLY; on a failed send it prints $OUT (D51).
printf '%s' "$OUT" | python3 "$HOME/projects/stoiclife/send_prompt.py" --session morning || echo "$OUT"
