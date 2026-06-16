#!/usr/bin/env python3
"""stoiclife FEAT-01 Part A — nightly sleep-score computation.

Computes a self-derived nightly sleep score (0-100) from the stage data already
in `biometrics` — Fitbit's own Sleep Score isn't exposed by the API. Three
weighted components, all weights + targets from `stoiclife_config.json`:

    Duration   (50%): D = clamp(sleep_duration_min / target_duration_min, 0, 1)
    REM        (25%): rem_pct = rem_min / sleep_duration_min   (dur IS asleep total)
                      R = clamp(rem_pct / target_rem_pct, 0, 1)
    Continuity (25%): efficiency = dur / (dur + minutes_awake)
                      C = clamp((efficiency - efficiency_floor) / (1 - floor), 0, 1)

    sleep_score = round(100 * (wd*D + wr*R + wc*C))

Nights missing stage data (a nap, a classic-mode night, or a night the device
didn't capture stages) are SKIPPED — stored as NULL, never zeroed — and are
ignored by the rolling average (A3).

This module only computes + stores the per-night score. The rolling average,
benchmark flag, and matrix modulation come in A3.

Usage:
    python3 sleep_score.py --date 2026-06-16            # (re)compute one night
    python3 sleep_score.py --start 2026-06-01 --end 2026-06-16   # backfill range
    python3 sleep_score.py --all                        # backfill every row
    python3 sleep_score.py --all --dry-run              # show, write nothing
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping

from trigger_matrix import DEFAULT_CONFIG, connect, load_config

# Stage minutes that must all be present for a night to be scored. deep/light
# aren't in the formula but their absence marks a non-stages night to skip.
STAGE_FIELDS = ("deep_min", "light_min", "rem_min")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def has_stage_data(row: Mapping) -> bool:
    """True only if this is a full stages night we can score."""
    row = dict(row)  # accept sqlite3.Row or a plain mapping
    if not row.get("sleep_duration_min"):  # NULL or 0 -> nothing to score
        return False
    return all(row.get(f) is not None for f in STAGE_FIELDS)


def compute_sleep_score(row: Mapping, cfg: dict) -> int | None:
    """Nightly 0-100 score, or None when the night lacks stage data."""
    row = dict(row)  # accept sqlite3.Row or a plain mapping
    if not has_stage_data(row):
        return None

    ss = cfg["sleep_score"]
    w = ss["weights"]
    dur = float(row["sleep_duration_min"])
    rem = float(row["rem_min"])
    awake = float(row["minutes_awake"] or 0)  # absent wake -> treat as 0

    duration = _clamp(dur / ss["target_duration_min"])

    rem_pct = rem / dur  # dur is the asleep total (deep+light+rem), confirmed A0
    rem_vs_light = _clamp(rem_pct / ss["target_rem_pct"])

    efficiency = dur / (dur + awake)
    floor = ss["efficiency_floor"]
    continuity = _clamp((efficiency - floor) / (1 - floor))

    score = 100 * (
        w["duration"] * duration
        + w["rem_vs_light"] * rem_vs_light
        + w["continuity"] * continuity
    )
    return round(score)


# --------------------------------------------------------------------------- #
# Rolling average + benchmark flag (A3 modulator inputs)
# --------------------------------------------------------------------------- #
def rolling_sleep_avgs(conn, anchor_date: str, window: int) -> dict:
    """7-day (window) rolling avgs of sleep_score and sleep_duration_min.

    Trailing window ending at and INCLUDING anchor_date (the most recent night's
    data) — "sustained" recent sleep, not a baseline that excludes today. NULLs
    are excluded from each average independently (a night may have a duration but
    no computed score, or vice versa).
    """
    rows = conn.execute(
        """
        SELECT sleep_score, sleep_duration_min FROM biometrics
        WHERE date <= ? AND date > date(?, ?)
        """,
        (anchor_date, anchor_date, f"-{window} days"),
    ).fetchall()
    scores = [r["sleep_score"] for r in rows if r["sleep_score"] is not None]
    durs = [r["sleep_duration_min"] for r in rows if r["sleep_duration_min"] is not None]
    return {
        "window": window,
        "n_score": len(scores),
        "n_duration": len(durs),
        "sleep_score_avg": round(sum(scores) / len(scores), 1) if scores else None,
        "sleep_duration_avg": round(sum(durs) / len(durs), 1) if durs else None,
    }


def sleep_modulator(conn, cfg: dict, anchor_date: str) -> dict | None:
    """Compute the rolling avgs + below-benchmark flag for the matrix modulator.

    Returns None when the feature isn't configured (no `sleep_score` block) so the
    matrix simply skips modulation. Otherwise returns the averages, the benchmarks,
    a boolean `flag` (either rolling avg below its benchmark), and the reasons.
    `confidence_bias`/`effect` are filled in by the matrix once it knows the state.
    """
    ss = cfg.get("sleep_score")
    if not ss:
        return None
    avgs = rolling_sleep_avgs(conn, anchor_date, ss["rolling_window_days"])
    score_bm = ss["sleep_score_benchmark"]
    dur_bm = ss["duration_benchmark_min"]
    reasons = []
    if avgs["sleep_score_avg"] is not None and avgs["sleep_score_avg"] < score_bm:
        reasons.append(f"7d sleep_score avg {avgs['sleep_score_avg']} < {score_bm}")
    if avgs["sleep_duration_avg"] is not None and avgs["sleep_duration_avg"] < dur_bm:
        reasons.append(f"7d sleep_duration avg {avgs['sleep_duration_avg']} < {dur_bm} min")
    return {
        **avgs,
        "score_benchmark": score_bm,
        "duration_benchmark": dur_bm,
        "state_bias_points": ss.get("state_bias_points", 0),
        "flag": bool(reasons),
        "reasons": reasons,
        "confidence_bias": 0,   # set by the matrix
        "effect": "",           # set by the matrix
    }


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def fetch_rows(conn, *, date=None, start=None, end=None, all_rows=False) -> list:
    if date:
        return conn.execute(
            "SELECT * FROM biometrics WHERE date = ?", (date,)
        ).fetchall()
    if all_rows:
        return conn.execute("SELECT * FROM biometrics ORDER BY date").fetchall()
    return conn.execute(
        "SELECT * FROM biometrics WHERE date >= ? AND date <= ? ORDER BY date",
        (start, end),
    ).fetchall()


def store_score(conn, date: str, score: int | None) -> None:
    conn.execute("UPDATE biometrics SET sleep_score = ? WHERE date = ?", (score, date))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="Compute nightly sleep score(s).")
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--date", help="(re)compute a single night YYYY-MM-DD")
    sel.add_argument("--start", help="backfill range start YYYY-MM-DD (needs --end)")
    sel.add_argument("--all", action="store_true", help="(re)compute every row")
    p.add_argument("--end", help="backfill range end YYYY-MM-DD (with --start)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print computed scores; write nothing to the DB",
    )
    args = p.parse_args()

    if args.start and not args.end:
        p.error("--start requires --end")

    cfg = load_config(Path(args.config))
    conn = connect(cfg["db_path"])
    rows = fetch_rows(
        conn, date=args.date, start=args.start, end=args.end, all_rows=args.all
    )

    if not rows:
        print("no biometrics rows matched.")
        return

    scored = skipped = 0
    print(f"{'date':12} {'dur':>4} {'rem':>4} {'awake':>5}  sleep_score")
    print("-" * 40)
    for r in rows:
        score = compute_sleep_score(r, cfg)
        if score is None:
            skipped += 1
            label = "NULL (no stage data)"
        else:
            scored += 1
            label = str(score)
        print(
            f"{r['date']:12} {r['sleep_duration_min'] or '-':>4} "
            f"{r['rem_min'] or '-':>4} {r['minutes_awake'] or '-':>5}  {label}"
        )
        if not args.dry_run:
            store_score(conn, r["date"], score)

    if args.dry_run:
        print(f"\n[dry-run] {scored} scored, {skipped} skipped — no DB writes.")
    else:
        conn.commit()
        print(f"\nWrote {scored} score(s), {skipped} skipped (NULL).")
    conn.close()


if __name__ == "__main__":
    main()
