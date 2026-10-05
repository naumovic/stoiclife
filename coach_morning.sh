#!/usr/bin/env bash
# Coach morning message: Health Snapshot + Stoic morning prep, for the Telegram coach bot.
# Run by the "Coach Morning (07:30)" command cron; stdout is delivered verbatim.
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

OUT=""

# --- HEALTH SNAPSHOT (Fitbit biometrics: sleep/HRV/resting HR) ---
YDAY=$(TZ="$EWOK_TZ" date -d yesterday '+%F')
BIO=$(sqlite3 -separator '|' "$HOME/.openclaw/stoic/stoic_journal.db" \
  "SELECT COALESCE(sleep_duration_min,''), COALESCE(deep_min,''), COALESCE(rem_min,''),
          COALESCE(hrv_rmssd_ms,''), COALESCE(resting_hr_bpm,''), COALESCE(steps,'')
   FROM biometrics WHERE date='${YDAY}';" 2>/dev/null || true)
HEALTH=""
if [ -n "$BIO" ]; then
  IFS='|' read -r SLEEP_MIN DEEP REM HRV RHR STEPS <<< "$BIO"
  if [ -n "$SLEEP_MIN" ]; then
    HEALTH+="
Sleep: $((SLEEP_MIN / 60))h$(printf '%02d' $((SLEEP_MIN % 60)))${DEEP:+ (deep ${DEEP}m}${REM:+, REM ${REM}m}${DEEP:+)}"
  fi
  [ -n "$HRV" ] && HEALTH+="
HRV: ${HRV} ms${RHR:+ · Resting HR: ${RHR} bpm}"
  [ -n "$STEPS" ] && HEALTH+="
Steps (yesterday): ${STEPS}"
fi
if [ -n "$HEALTH" ]; then
  OUT+="🏃 Health Snapshot${HEALTH}

"
fi

# --- STOIC MORNING PREP ---
OUT+=$(cat "$HOME/.openclaw/workspace/stoic/prompts/morning_prompt.txt")

echo "$OUT"
