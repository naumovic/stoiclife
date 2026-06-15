#!/usr/bin/env python3
"""stoiclife Phase 2 — The Trigger Matrix.

Given a date (and optionally a session), classify the day into one of the
trigger states by comparing today's biometrics + inferred mood against a
7-day rolling baseline. This module DETECTS and QUEUES a state only; it does
not generate coaching (Phase 3) or send anything (Phase 4).

States:
    rattled_but_ready  body high (HRV up, RHR down) + mind low      -> push exertion
    running_on_fumes   body low (HRV dropping / short sleep) + mind high -> protect rest
    system_drain       body low (HRV dropping + RHR spiking) + mind low  -> pull the brake
    sweet_spot         body high/stable + mind high                 -> silence
    neutral            within normal band                           -> no trigger
    insufficient_data  today's biometrics row / journal entry missing, or
                       the entry exists but mood_score not yet inferred -> no trigger

Usage:
    python3 trigger_matrix.py --date 2026-06-09
    python3 trigger_matrix.py --date 2026-06-09 --session evening
    python3 trigger_matrix.py --date 2026-06-09 --no-write   # dry run, no DB row
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Brisbane")
REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"

NON_SILENT = {"rattled_but_ready", "running_on_fumes", "system_drain"}


# --------------------------------------------------------------------------- #
# Config + DB helpers
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    return json.loads(path.read_text())


def connect(db_path: str) -> sqlite3.Connection:
    resolved = Path(os.path.expanduser(db_path))
    if not resolved.exists():
        raise SystemExit(f"DB not found at {resolved}")
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def pct_delta(today: float | None, baseline: float | None) -> float | None:
    if today is None or baseline is None or baseline == 0:
        return None
    return round((today - baseline) / baseline * 100, 1)


def rolling_avg(rows: list[sqlite3.Row], field_name: str) -> float | None:
    vals = [r[field_name] for r in rows if r[field_name] is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


# --------------------------------------------------------------------------- #
# Data fetch
# --------------------------------------------------------------------------- #
def fetch_baseline_rows(conn, anchor_date: str, window: int) -> list[sqlite3.Row]:
    """Biometric rows in [anchor-window, anchor-1] (excludes the anchor row).

    Anchored on the biometrics row used as "today" (which may lag target_date),
    so the anchor row is never counted in its own baseline.
    """
    return conn.execute(
        """
        SELECT * FROM biometrics
        WHERE date < ? AND date >= date(?, ?)
        ORDER BY date
        """,
        (anchor_date, anchor_date, f"-{window} days"),
    ).fetchall()


def fetch_biometrics_today(conn, target_date: str, max_lag_days: int = 0) -> sqlite3.Row | None:
    """Most-recent biometrics row at or before target_date, within max_lag_days.

    Fitbit dates a night's sleep on the morning you wake and the sync only fetches
    complete (past) days, so "today" rarely has its own row yet. We accept the
    freshest row up to max_lag_days old as the current physical reading; older than
    that, or nothing at all, returns None -> insufficient_data.
    """
    return conn.execute(
        """
        SELECT * FROM biometrics
        WHERE date <= ? AND date >= date(?, ?)
        ORDER BY date DESC
        LIMIT 1
        """,
        (target_date, target_date, f"-{max_lag_days} days"),
    ).fetchone()


def fetch_entries(conn, target_date: str) -> dict[str, sqlite3.Row]:
    """Latest entry per session for the date (a session can have dupes)."""
    rows = conn.execute(
        "SELECT * FROM journal_entries WHERE date = ? ORDER BY id", (target_date,)
    ).fetchall()
    by_session: dict[str, sqlite3.Row] = {}
    for r in rows:
        by_session[r["session"]] = r  # later id wins
    return by_session


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
@dataclass
class Result:
    date: str
    session: str
    state: str
    physical_summary: str
    mental_summary: str
    deltas: dict
    matched_keywords: list[str] = field(default_factory=list)
    confidence: int = 0
    notes: str = ""


def scan_keywords(text: str, keywords: list[str]) -> list[str]:
    low = text.lower()
    return [kw for kw in keywords if kw.lower() in low]


def _clamp(v: float, lo: float = 0, hi: float = 100) -> int:
    return int(round(max(lo, min(hi, v))))


def classify(cfg: dict, target_date: str, session: str,
             today_bio: sqlite3.Row | None, baseline: list[sqlite3.Row],
             entries: dict[str, sqlite3.Row]) -> Result:
    th = cfg["thresholds"]
    moodc = cfg["mood"]
    win = cfg["rolling_window_days"]

    # --- Guard: insufficient data ---
    if today_bio is None:
        return Result(target_date, session, "insufficient_data", "no biometrics row",
                      "n/a", {}, notes="today's biometrics row missing")
    if not entries:
        return Result(target_date, session, "insufficient_data",
                      "biometrics present", "no journal entry", {},
                      notes="today's journal entry missing")
    if len([r for r in baseline if r["hrv_rmssd_ms"] is not None]) < cfg["min_baseline_days"]:
        return Result(target_date, session, "insufficient_data", "thin baseline",
                      "n/a", {}, notes=f"<{cfg['min_baseline_days']} baseline days in {win}d window")

    # --- Baselines + deltas ---
    hrv_avg = rolling_avg(baseline, "hrv_rmssd_ms")
    rhr_avg = rolling_avg(baseline, "resting_hr_bpm")
    sleep_avg = rolling_avg(baseline, "sleep_duration_min")

    hrv_today = today_bio["hrv_rmssd_ms"]
    rhr_today = today_bio["resting_hr_bpm"]
    sleep_today = today_bio["sleep_duration_min"]

    hrv_d = pct_delta(hrv_today, hrv_avg)
    rhr_d = pct_delta(rhr_today, rhr_avg)
    sleep_d = pct_delta(sleep_today, sleep_avg)
    bio_date = today_bio["date"]
    deltas = {
        "hrv_today_ms": hrv_today, "hrv_avg_ms": hrv_avg, "hrv_delta_pct": hrv_d,
        "rhr_today_bpm": rhr_today, "rhr_avg_bpm": rhr_avg, "rhr_delta_pct": rhr_d,
        "sleep_today_min": sleep_today, "sleep_avg_min": sleep_avg, "sleep_delta_pct": sleep_d,
        "baseline_days": len(baseline),
        "bio_date": bio_date,
        "bio_lag_days": (date_cls.fromisoformat(target_date) - date_cls.fromisoformat(bio_date)).days,
    }

    # --- Physical flags ---
    hrv_high = hrv_d is not None and hrv_d >= th["hrv_high_pct"]
    hrv_drop = hrv_d is not None and hrv_d <= th["hrv_drop_pct"]
    rhr_below = rhr_d is not None and rhr_d <= th["rhr_below_max_pct"]
    rhr_spike = rhr_d is not None and rhr_d >= th["rhr_spike_pct"]
    sleep_short = sleep_today is not None and sleep_today < th["sleep_short_min"]

    physical_high = hrv_high and rhr_below
    physical_drain = hrv_drop and rhr_spike
    physical_fumes = hrv_drop or sleep_short
    physical_stable = not hrv_drop and not rhr_spike

    phys_bits = []
    if hrv_d is not None:
        phys_bits.append(f"HRV {hrv_today}ms ({hrv_d:+.1f}% vs {hrv_avg})")
    if rhr_d is not None:
        phys_bits.append(f"RHR {rhr_today}bpm ({rhr_d:+.1f}% vs {rhr_avg})")
    if sleep_today is not None:
        phys_bits.append(f"sleep {sleep_today}min")
    physical_summary = ", ".join(phys_bits)

    # --- Mental signal (mood from the evaluated session; keywords up to it) ---
    order = ["morning", "evening"]
    if session in ("evening", "safety-net"):
        considered = [s for s in order if s in entries]
    else:  # morning
        considered = [s for s in order[:1] if s in entries]
    if not considered:  # fall back to whatever exists
        considered = list(entries.keys())

    mood_session = session if session in entries else considered[-1]
    mood = entries[mood_session]["mood_score"]

    scan_text = " ".join(
        f"{entries[s]['raw_response'] or ''} {entries[s]['processed_themes'] or ''}"
        for s in considered
    )
    kw = cfg["keywords"]
    matched_rattled = scan_keywords(scan_text, kw["rattled_but_ready"])
    matched_fumes = scan_keywords(scan_text, kw["running_on_fumes"])
    matched_drain = scan_keywords(scan_text, kw["system_drain"])

    mental_summary = f"mood {mood} ({mood_session})" if mood is not None else "mood not yet inferred"

    # --- Guard: entry exists but mood_score not yet inferred (Issue-001) ---
    # The event-driven eval (AGENTS.md step 6) can read the just-saved row before
    # update_entry.py's mood write is visible, leaving mood_score NULL. Treat that
    # exactly like a missing biometrics/journal row: bail to insufficient_data (no
    # fired state, no cooldown) rather than writing a misleading neutral/conf-0 row.
    # A later eval (re-save or the 11:00 safety-net) reclassifies once mood is set.
    if mood is None:
        return Result(target_date, session, "insufficient_data", physical_summary,
                      mental_summary, deltas, notes="mood_score not yet inferred")

    # --- State decision (mind/body divergence first, then sweet spot) ---
    state = "neutral"
    matched: list[str] = []
    if physical_drain and mood < moodc["drain_max"]:
        state, matched = "system_drain", matched_drain
    elif physical_fumes and mood > moodc["fumes_min"]:
        state, matched = "running_on_fumes", matched_fumes
    elif physical_high and mood < moodc["rattled_max"]:
        state, matched = "rattled_but_ready", matched_rattled
    elif (physical_high or physical_stable) and mood > moodc["sweet_spot_min"]:
        state, matched = "sweet_spot", []

    confidence = _confidence(state, th, moodc, hrv_d, rhr_d, sleep_today,
                             mood, matched) if state != "neutral" else 0

    return Result(target_date, session, state, physical_summary, mental_summary,
                  deltas, matched, confidence)


def _confidence(state, th, moodc, hrv_d, rhr_d, sleep_today, mood, matched) -> int:
    """Deterministic 0-100: base + physical margin + mood margin + keywords."""
    if state == "sweet_spot":
        # Silent anyway; report a nominal positive score.
        return _clamp(60 + (mood - moodc["sweet_spot_min"]) * 8)

    base = 15.0
    # Physical strength: how far the relevant driver clears its threshold.
    ratio = 0.0
    if state == "rattled_but_ready" and hrv_d is not None:
        ratio = hrv_d / th["hrv_high_pct"]
    elif state == "running_on_fumes":
        r1 = abs(hrv_d / th["hrv_drop_pct"]) if hrv_d is not None and hrv_d < 0 else 0
        r2 = (th["sleep_short_min"] - sleep_today) / th["sleep_short_min"] if sleep_today is not None and sleep_today < th["sleep_short_min"] else 0
        ratio = max(r1, r2)
    elif state == "system_drain":
        r1 = abs(hrv_d / th["hrv_drop_pct"]) if hrv_d is not None and hrv_d < 0 else 0
        r2 = rhr_d / th["rhr_spike_pct"] if rhr_d is not None and rhr_d > 0 else 0
        ratio = (r1 + r2) / 2
    phys_pts = min(35.0, ratio * 17.5)

    # Mood margin from the cutoff.
    cutoff = {"rattled_but_ready": moodc["rattled_max"],
              "running_on_fumes": moodc["fumes_min"],
              "system_drain": moodc["drain_max"]}[state]
    mood_dist = abs(mood - cutoff)
    mood_pts = min(25.0, mood_dist * 12)

    kw_pts = min(25.0, len(matched) * 12)
    return _clamp(base + phys_pts + mood_pts + kw_pts)


# --------------------------------------------------------------------------- #
# Cooldown + persistence
# --------------------------------------------------------------------------- #
def cooldown_active(conn, state: str, target_date: str, cfg: dict) -> bool:
    days = cfg["cooldown_days"].get(state, cfg["cooldown_days"]["default"])
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM trigger_events
        WHERE state = ? AND fired = 1
          AND date >= date(?, ?) AND date <= ?
        """,
        (state, target_date, f"-{days} days", target_date),
    ).fetchone()
    return row["n"] > 0


def write_event(conn, r: Result, fired: bool, cooldown_skipped: bool) -> int:
    cur = conn.execute(
        """
        INSERT INTO trigger_events
            (eval_datetime, date, session, state, deltas_json, matched_keywords,
             confidence, fired, cooldown_skipped, message_sent, held_for_quiet_hours,
             usefulness, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)
        """,
        (
            datetime.now(TZ).isoformat(timespec="seconds"),
            r.date, r.session, r.state, json.dumps(r.deltas),
            ",".join(r.matched_keywords), r.confidence,
            int(fired), int(cooldown_skipped), r.notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def resolve_session(entries: dict, session: str | None) -> str:
    """Default to the latest entry present for the day, else safety-net."""
    if session:
        return session
    return "evening" if "evening" in entries else ("morning" if "morning" in entries else "safety-net")


def evaluate(conn, cfg: dict, target_date: str, session: str | None, write: bool = True):
    """Classify a day, apply cooldown, optionally persist. Reusable by the orchestrator.

    Returns (result, fired, cooldown_skipped, event_id).
    """
    today_bio = fetch_biometrics_today(conn, target_date, cfg.get("biometrics_max_lag_days", 0))
    anchor_date = today_bio["date"] if today_bio is not None else target_date
    baseline = fetch_baseline_rows(conn, anchor_date, cfg["rolling_window_days"])
    entries = fetch_entries(conn, target_date)
    session = resolve_session(entries, session)

    result = classify(cfg, target_date, session, today_bio, baseline, entries)

    fired = False
    cooldown_skipped = False
    if result.state in NON_SILENT:
        if cooldown_active(conn, result.state, target_date, cfg):
            cooldown_skipped = True
            result.notes = (result.notes + "; " if result.notes else "") + "suppressed by cooldown"
        else:
            fired = True

    event_id = write_event(conn, result, fired, cooldown_skipped) if write else None
    return result, fired, cooldown_skipped, event_id


def run(args) -> Result:
    cfg = load_config(Path(args.config))
    conn = connect(cfg["db_path"])
    result, fired, cooldown_skipped, event_id = evaluate(
        conn, cfg, args.date, args.session, write=not args.no_write
    )
    conn.close()
    _print(result, fired, cooldown_skipped, event_id, args.no_write)
    return result


def _print(r: Result, fired, cooldown_skipped, event_id, dry):
    print(f"date         : {r.date}  (session: {r.session})")
    print(f"state        : {r.state}")
    print(f"physical     : {r.physical_summary}")
    print(f"mental       : {r.mental_summary}")
    if r.matched_keywords:
        print(f"keywords     : {', '.join(r.matched_keywords)}")
    print(f"confidence   : {r.confidence}")
    print(f"fired        : {fired}" + ("  (cooldown_skipped)" if cooldown_skipped else ""))
    if r.notes:
        print(f"notes        : {r.notes}")
    print(f"db           : {'(dry run, not written)' if dry else f'trigger_events id={event_id}'}")


def main():
    p = argparse.ArgumentParser(description="stoiclife trigger matrix (Phase 2)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD to classify")
    p.add_argument("--session", choices=["morning", "evening", "safety-net"],
                   default=None, help="defaults to latest entry present")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--no-write", action="store_true", help="dry run; do not write trigger_events")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
