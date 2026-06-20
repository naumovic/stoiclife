#!/usr/bin/env python3
"""stoiclife FEAT-02 — System heartbeat / "all ok" health check.

`health_check()` certifies that the proactive pipeline actually ran and saw
fresh data on a silent day, so an absence of coaching is legible as "checked,
nothing wrong" rather than a quietly broken pipeline (the failure mode behind
Issue-002 and FEAT-01-Issue-01/02).

Hard checks — all must pass for `ok`:
  eval_ran             classify() returned a non-error state (insufficient_data => not ok,
                       reason = whichever input is missing: biometrics, journal, or mood)
  biometrics_fresh     a biometrics row exists within biometrics_max_lag_days (the matrix's
                       own lag logic — we read the row it resolved as "today")
  sleep_score_present  last night's sleep_score is non-NULL (FEAT-01-Issue-01 failure mode);
                       on today's still-filling row a NULL score is "pending", not a warning,
                       until the morning grace cutoff (see _in_sleep_grace)

Soft check — informational, never blocks `ok` (SpO2 is legitimately NULL some nights, so a
missing value is noted but does NOT cry wolf):
  spo2_fresh           SpO2 present on the freshest biometrics row

FEAT-02 Step 1 sends nothing — this only computes and exposes the result for the
orchestrator (Step 2) and surfaces it in --dry-run.
"""
from __future__ import annotations

from datetime import datetime


def _check(ok: bool, detail: str, hard: bool) -> dict:
    return {"ok": ok, "detail": detail, "hard": hard}


def _in_sleep_grace(sig: dict, now: datetime | None) -> bool:
    """True while a NULL sleep_score on *today's* row is still expected, not broken.

    The 07:00 primary Fitbit sync usually beats Fitbit's overnight cloud upload, so
    it writes today's biometrics row with no sleep stages yet — sleep_score.py has
    nothing to derive from and leaves the score NULL until the 10:00 catch-up sync
    fills the stages (the FEAT-01-Issue-01 timing race). Before
    `status_signal.sleep_score_grace_until` we treat that NULL as pending rather
    than warning; after the cutoff (so for the 11:00 safety-net and every evening
    eval) a NULL score is a genuine failure again.
    """
    if now is None or not sig.get("sleep_grace_enabled", True):
        return False
    cutoff = sig.get("sleep_score_grace_until")
    if not cutoff:
        return False
    try:
        cutoff_t = datetime.strptime(cutoff, "%H:%M").time()
    except ValueError:
        return False
    return now.time() < cutoff_t


def health_check(cfg: dict, result, today_bio, now: datetime | None = None) -> dict:
    """Return {ok, reasons, checks} certifying pipeline health for `result`.

    Args:
        cfg:       loaded stoiclife config (the `status_signal` block is read here).
        result:    the Result from trigger_matrix.classify/evaluate.
        today_bio: the biometrics row the matrix used as "today" (None if none fell
                   within biometrics_max_lag_days). Reusing the matrix's lag-resolved
                   row keeps freshness here consistent with what classification saw.
        now:       eval wall-clock time (AEST); enables the morning grace window for a
                   not-yet-computed sleep_score. None disables grace (always strict).
    """
    sig = cfg.get("status_signal", {})
    require_bio = sig.get("require_biometrics", True)
    require_sleep = sig.get("require_sleep_score", True)
    spo2_soft = sig.get("spo2_soft_check", True)
    max_lag = cfg.get("biometrics_max_lag_days", 0)

    checks: dict[str, dict] = {}

    # --- Hard: eval ran + classified (insufficient_data => not ok) ---
    eval_ran = result.state != "insufficient_data"
    checks["eval_ran"] = _check(
        eval_ran,
        "classified" if eval_ran else (result.notes or "insufficient_data"),
        hard=True,
    )

    # --- Hard: biometrics fresh (the matrix's lag-resolved row) ---
    lag = result.deltas.get("bio_lag_days")
    if today_bio is None:
        bio_ok, bio_detail = False, f"no biometrics row within {max_lag}d"
    else:
        bio_ok = True
        bio_detail = f"bio {today_bio['date']} " + (f"(lag {lag}d)" if lag else "(today)")
    checks["biometrics_fresh"] = _check(bio_ok, bio_detail, hard=require_bio)

    # --- Hard: last night's sleep_score computed (FEAT-01-Issue-01) ---
    # Grace: a NULL sleep_score on *today's* still-filling row (lag 0/None) before the
    # morning cutoff is expected (the 10:00 catch-up sync hasn't run yet), not broken —
    # so an early journal entry doesn't draw a false ⚠️. Past the cutoff, or on a
    # lag>=1 row that should already carry a complete night, NULL warns. See
    # _in_sleep_grace.
    score = today_bio["sleep_score"] if today_bio is not None else None
    if score is not None:
        sleep_ok, sleep_detail = True, f"sleep_score={score}"
    elif today_bio is not None and not lag and _in_sleep_grace(sig, now):
        sleep_ok = True
        sleep_detail = f"sleep_score pending (grace until {sig.get('sleep_score_grace_until')})"
    else:
        sleep_ok, sleep_detail = False, "sleep score not yet computed"
    checks["sleep_score_present"] = _check(sleep_ok, sleep_detail, hard=require_sleep)

    # --- Soft: SpO2 fresh (NULL is normal — never blocks ok) ---
    spo2 = today_bio["spo2_avg"] if today_bio is not None else None
    checks["spo2_fresh"] = _check(
        spo2 is not None,
        f"spo2={spo2}" if spo2 is not None else "no SpO2 reading (normal some nights)",
        hard=not spo2_soft,
    )

    # ok requires every hard check to pass. Keep reasons concise: a failed eval is
    # the root cause (the data isn't there to trust the rest), so it stands alone;
    # otherwise surface the specific stale/missing hard input(s).
    ok = all(c["ok"] for c in checks.values() if c["hard"])
    if not eval_ran:
        reasons = [checks["eval_ran"]["detail"]]
    else:
        reasons = [c["detail"] for c in checks.values() if c["hard"] and not c["ok"]]

    return {"ok": ok, "reasons": reasons, "checks": checks}


# In-turn sessions: the status line rides the journal-hook coach reply only.
# safety-net (the 11:00 out-of-turn cron) never emits a line — FEAT-02 is in-turn only.
IN_TURN_SESSIONS = ("morning", "evening")


def resolve_status_line(cfg: dict, action: str, session: str, health: dict):
    """FEAT-02: the status line to append to a SILENT in-turn coach reply.

    Returns (signal, line):
      signal: 'all_ok' | 'warning' | 'none'  — recorded on trigger_events.status_signal.
      line:   the WhatsApp text to append, or None when nothing is appended.

    Appended ONLY on a SILENT in-turn (morning/evening) eval — never on a fired day
    (SEND_FULL / CLARIFY / HOLD_QUIET) and never out-of-turn (safety-net). The all-ok
    emoji comes from config and is deliberately not the ✅ "Stoic entry saved" tick.
    """
    sig = cfg.get("status_signal", {})
    if not sig.get("enabled", True):
        return "none", None
    if action != "SILENT" or session not in IN_TURN_SESSIONS:
        return "none", None
    if health["ok"]:
        return "all_ok", f"{sig.get('ok_emoji', '🟢')} {sig.get('ok_line', '*stoiclife:* all ok')}"
    reason = health["reasons"][0] if health["reasons"] else "status check could not confirm health"
    warn = sig.get("warn_line", "*stoiclife:* heads up —")
    return "warning", f"{sig.get('warn_emoji', '⚠️')} {warn} {reason}"


def render_health_lines(health: dict) -> list[str]:
    """Human-readable health_check breakdown for --dry-run output (comment lines)."""
    mark = {True: "ok", False: "FAIL"}
    lines = [f"# health_check: ok={health['ok']}"]
    for name, c in health["checks"].items():
        tag = "hard" if c["hard"] else "soft"
        lines.append(f"#   [{tag}] {name}: {mark[c['ok']]} — {c['detail']}")
    if health["reasons"]:
        lines.append(f"#   reasons: {'; '.join(health['reasons'])}")
    return lines
