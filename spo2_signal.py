#!/usr/bin/env python3
"""stoiclife FEAT-01 Part B — blood-oxygen (SpO2) signal + matrix modulator.

SpO2 is synced into biometrics (spo2_avg/min/max/stddev) from the Google Health
`daily-oxygen-saturation` data type — measured during main sleep and computed
post-night, so the freshest value is YESTERDAY's (the anchor biometrics row).

This module turns that into a *modulator* for the trigger matrix — extra
"physical depletion" evidence, never a new state (FEAT-01 Integration model):

    - evaluate yesterday's measured SpO2 (the anchor row's spo2_avg) against a
      fixed, configurable baseline;
    - surface a 7-day rolling average (nulls excluded) for monitoring /
      self-calibration of that baseline over time;
    - raise `flag` when SpO2 drops below `drop_flag_below_pct` (absolute floor)
      OR `>= drop_threshold_pct` below `baseline_pct` (a relative dip).

The matrix folds `flag` into the physical side (toward "low") and applies a
configurable `state_bias_points` confidence bias. It only shifts a borderline
call — mood gating + the confidence gate still decide whether anything fires.

Framing: SpO2 is a sensitive wellness signal, NOT a medical reading. Coaching
copy must avoid diagnostic language and, only if values are persistently low,
suggest checking with a professional (handled in the prompt/payload layer).

This module is import-only (no CLI); B4 owns the backfill + verification run.
"""
from __future__ import annotations


def rolling_spo2_avg(conn, anchor_date: str, window: int) -> dict:
    """7-day (window) rolling avg of spo2_avg, trailing and INCLUDING anchor_date.

    Mirrors sleep_score.rolling_sleep_avgs: a "sustained recent" window, not a
    baseline that excludes today. NULL nights (no SpO2 captured) are excluded.
    """
    rows = conn.execute(
        """
        SELECT spo2_avg FROM biometrics
        WHERE date <= ? AND date > date(?, ?)
        """,
        (anchor_date, anchor_date, f"-{window} days"),
    ).fetchall()
    vals = [r["spo2_avg"] for r in rows if r["spo2_avg"] is not None]
    return {
        "window": window,
        "n": len(vals),
        "spo2_avg": round(sum(vals) / len(vals), 1) if vals else None,
    }


def latest_spo2(conn, anchor_date: str, max_lag_days: int) -> tuple:
    """Freshest measured SpO2 at/before anchor_date, within max_lag_days.

    SpO2 is computed post-sleep, so the "today" biometrics row (which after
    Issue-003 C is the same-day lag-0 row) usually has a NULL spo2_avg until the
    next day — yet yesterday's value is the relevant overnight reading. Mirror the
    matrix's body-data lag tolerance: take the most recent non-NULL spo2_avg up to
    max_lag_days old. Returns (value, date, lag_days) or (None, None, None).
    """
    row = conn.execute(
        """
        SELECT date, spo2_avg FROM biometrics
        WHERE spo2_avg IS NOT NULL AND date <= ? AND date >= date(?, ?)
        ORDER BY date DESC LIMIT 1
        """,
        (anchor_date, anchor_date, f"-{max_lag_days} days"),
    ).fetchone()
    if row is None:
        return None, None, None
    from datetime import date as _d
    lag = (_d.fromisoformat(anchor_date) - _d.fromisoformat(row["date"])).days
    return row["spo2_avg"], row["date"], lag


def spo2_modulator(conn, cfg: dict, anchor_date: str) -> dict | None:
    """Rolling avg + below-baseline flag for the matrix modulator.

    Returns None when the feature isn't configured (no `spo2` block) so the
    matrix simply skips this modulation. Otherwise evaluates the freshest measured
    SpO2 (anchor row, or the most recent within the body-data lag — SpO2 is
    computed post-sleep so today's own value is usually still NULL) against the
    rolling average + benchmarks, a boolean `flag` (absolute floor OR relative
    drop), and the reasons. `confidence_bias`/`effect` are set by the matrix.
    """
    sp = cfg.get("spo2")
    if not sp:
        return None

    max_lag = cfg.get("biometrics_max_lag_days", 0)
    today_spo2, spo2_date, spo2_lag = latest_spo2(conn, anchor_date, max_lag)

    avgs = rolling_spo2_avg(conn, anchor_date, sp["rolling_window_days"])
    baseline = sp["baseline_pct"]
    floor = sp["drop_flag_below_pct"]
    drop_th = sp["drop_threshold_pct"]

    reasons = []
    if today_spo2 is not None:
        # Round the gap to 1 decimal before comparing: SpO2 values carry one
        # decimal, and raw float subtraction (e.g. 95.5 - 94.7 = 0.79999…) would
        # otherwise drop a night that is exactly at the threshold by accident.
        drop = round(baseline - today_spo2, 1)
        if today_spo2 < floor:
            reasons.append(f"SpO2 {today_spo2}% < floor {floor}%")
        elif drop >= drop_th:
            reasons.append(
                f"SpO2 {today_spo2}% is {drop}pp below "
                f"baseline {baseline}% (>= {drop_th}pp drop)"
            )

    return {
        "yesterday_spo2": today_spo2,   # freshest measured value (anchor or lagged)
        "spo2_date": spo2_date,
        "spo2_lag_days": spo2_lag,
        "rolling_avg": avgs["spo2_avg"],
        "window": avgs["window"],
        "n": avgs["n"],
        "baseline_pct": baseline,
        "drop_flag_below_pct": floor,
        "drop_threshold_pct": drop_th,
        "state_bias_points": sp.get("state_bias_points", 0),
        "flag": bool(reasons),
        "reasons": reasons,
        "confidence_bias": 0,   # set by the matrix
        "effect": "",           # set by the matrix
    }
