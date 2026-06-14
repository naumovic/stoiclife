#!/usr/bin/env python3
"""stoiclife Phase 5 — weekly review + flag-gated weekend Sweet Spot recap.

Emits WhatsApp-formatted plain text (no markdown tables/headers) summarising the
week's triggers and, when the week skews Sweet Spot/stable, a short positive
recap (Decision F, behind the `weekend_recap.enabled` config flag). It does NOT
call an LLM and sends nothing itself — it prints to stdout for the existing
Sunday digest (`scripts/weekly-digest.sh`) to deliver.

Usage:
    python3 weekly_review.py --section both           # default: review + recap
    python3 weekly_review.py --section weekly
    python3 weekly_review.py --section recap --asof 2026-06-14 --days 7
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from states import STATE_DISPLAY

TZ = ZoneInfo("Australia/Brisbane")
REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"

NON_SILENT = {"rattled_but_ready", "running_on_fumes", "system_drain"}


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(os.path.expanduser(db_path)))
    conn.row_factory = sqlite3.Row
    return conn


def daterange(asof: str, days: int) -> tuple[str, str]:
    end = date_cls.fromisoformat(asof)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def representative_state_per_day(events: list[sqlite3.Row]) -> dict[str, str]:
    """The last eval of each day is that day's headline state."""
    by_day: dict[str, sqlite3.Row] = {}
    for e in sorted(events, key=lambda r: (r["date"], r["eval_datetime"])):
        by_day[e["date"]] = e  # later eval wins
    return {d: r["state"] for d, r in by_day.items()}


# --------------------------------------------------------------------------- #
# Weekly review
# --------------------------------------------------------------------------- #
def weekly_section(conn, cfg, start: str, end: str) -> str:
    events = conn.execute(
        "SELECT * FROM trigger_events WHERE date >= ? AND date <= ? ORDER BY date, eval_datetime",
        (start, end),
    ).fetchall()

    fired = [e for e in events if e["fired"]]
    fired_by_state: dict[str, int] = {}
    for e in fired:
        fired_by_state[e["state"]] = fired_by_state.get(e["state"], 0) + 1

    insufficient_days = sorted({e["date"] for e in events if e["state"] == "insufficient_data"})

    # Delivered coaching + usefulness within the window.
    delivered = conn.execute(
        """
        SELECT c.usefulness FROM trigger_coaching c
        JOIN trigger_events e ON e.id = c.event_id
        WHERE c.valid = 1 AND e.message_sent = 1 AND e.date >= ? AND e.date <= ?
        """,
        (start, end),
    ).fetchall()
    useful = sum(1 for r in delivered if r["usefulness"] == 1)
    not_useful = sum(1 for r in delivered if r["usefulness"] == -1)
    neutral = sum(1 for r in delivered if r["usefulness"] == 0)
    unrated = sum(1 for r in delivered if r["usefulness"] is None)

    lines = ["🧭 *stoiclife — weekly review*"]
    if not events:
        lines.append("  • No evaluations logged this week.")
        return "\n".join(lines)

    if fired_by_state:
        parts = ", ".join(f"{STATE_DISPLAY[s]} ×{n}" for s, n in sorted(fired_by_state.items()))
        lines.append(f"  • Triggers fired: {len(fired)} ({parts})")
    else:
        lines.append("  • Triggers fired: 0 (a quiet week — signal stayed below threshold)")

    if delivered:
        lines.append(f"  • Pushes delivered: {len(delivered)} — "
                     f"👍 {useful} / 👎 {not_useful} / neutral {neutral} / unrated {unrated}")
    else:
        lines.append("  • Pushes delivered: 0")

    if insufficient_days:
        lines.append(f"  • Insufficient-data days: {len(insufficient_days)} "
                     f"({', '.join(insufficient_days)})")

    lines.append(_tuning_suggestion(conn, cfg, start, end))
    return "\n".join(lines)


def _tuning_suggestion(conn, cfg, start: str, end: str) -> str:
    """Flag any state firing >= min_fires whose rated usefulness ratio is poor."""
    fb = cfg.get("feedback", {})
    min_fires = fb.get("tuning_min_fires", 3)
    min_ratio = fb.get("tuning_useful_ratio", 0.34)

    rows = conn.execute(
        """
        SELECT e.state AS state, c.usefulness AS usefulness
        FROM trigger_coaching c JOIN trigger_events e ON e.id = c.event_id
        WHERE c.valid = 1 AND e.message_sent = 1 AND e.date >= ? AND e.date <= ?
        """,
        (start, end),
    ).fetchall()

    by_state: dict[str, list[int]] = {}
    for r in rows:
        if r["usefulness"] is not None:
            by_state.setdefault(r["state"], []).append(r["usefulness"])

    suggestions = []
    for state, ratings in by_state.items():
        if len(ratings) < min_fires:
            continue
        ratio = sum(1 for v in ratings if v == 1) / len(ratings)
        if ratio < min_ratio:
            suggestions.append(
                f"{STATE_DISPLAY[state]} fired {len(ratings)}× but only {ratio:.0%} were "
                f"useful — consider tightening its threshold/cooldown.")
    if not suggestions:
        # Honest about why: usually not enough rated data yet.
        rated = sum(len(v) for v in by_state.values())
        if rated == 0:
            return "  • Tuning: no rated pushes yet — react to a push to start the feedback loop."
        return "  • Tuning: ratings look healthy; no threshold change suggested."
    return "  • Tuning suggestions:\n" + "\n".join(f"    – {s}" for s in suggestions)


# --------------------------------------------------------------------------- #
# Weekend Sweet Spot recap (Decision F, flag-gated)
# --------------------------------------------------------------------------- #
def recap_section(conn, cfg, start: str, end: str) -> str:
    wr = cfg.get("weekend_recap", {})
    if not wr.get("enabled", False):
        return ""

    events = conn.execute(
        "SELECT * FROM trigger_events WHERE date >= ? AND date <= ?",
        (start, end),
    ).fetchall()
    rep = representative_state_per_day(events)
    classified = {d: s for d, s in rep.items() if s != "insufficient_data"}
    if not classified:
        return ""
    sweet_days = [d for d, s in classified.items() if s == "sweet_spot"]
    ratio = len(sweet_days) / len(classified)
    if ratio < wr.get("min_sweet_spot_ratio", 0.5):
        return ""  # week didn't skew positive enough — stay silent

    # Best-recovery day = highest HRV in window.
    bio = conn.execute(
        """
        SELECT date, hrv_rmssd_ms, sleep_duration_min FROM biometrics
        WHERE date >= ? AND date <= ? AND hrv_rmssd_ms IS NOT NULL
        ORDER BY hrv_rmssd_ms DESC LIMIT 1
        """,
        (start, end),
    ).fetchone()

    # Mood high point + a simple streak of mood >= 7 days.
    journal = conn.execute(
        """
        SELECT date, MAX(mood_score) AS mood FROM journal_entries
        WHERE date >= ? AND date <= ? AND mood_score IS NOT NULL
        GROUP BY date ORDER BY date
        """,
        (start, end),
    ).fetchall()

    lines = ["🌿 *stoiclife — your week*",
             f"A steady, good week — {len(sweet_days)} of {len(classified)} days landed in a strong place."]
    if bio is not None:
        nice_date = date_cls.fromisoformat(bio["date"]).strftime("%a %-d %b")
        lines.append(f"  • Best recovery: {nice_date} — HRV {bio['hrv_rmssd_ms']} ms.")
    if journal:
        top = max(journal, key=lambda r: r["mood"])
        nice_date = date_cls.fromisoformat(top["date"]).strftime("%a %-d %b")
        lines.append(f"  • Mood high: {nice_date} — you rated the day {top['mood']}/10.")
        streak = _longest_mood_streak([r["mood"] for r in journal], threshold=7)
        if streak >= 2:
            lines.append(f"  • You strung together {streak} days at mood 7+ — name what made them work, and keep it.")
    lines.append("Nothing to fix this week. Onceness: it won't come again exactly like this — savour it.")
    return "\n".join(lines)


def _longest_mood_streak(moods: list[int], threshold: int) -> int:
    best = cur = 0
    for m in moods:
        cur = cur + 1 if m >= threshold else 0
        best = max(best, cur)
    return best


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description="stoiclife weekly review + weekend recap")
    p.add_argument("--section", choices=["weekly", "recap", "both"], default="both")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--asof", default=datetime.now(TZ).strftime("%Y-%m-%d"))
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = p.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    conn = connect(cfg["db_path"])
    start, end = daterange(args.asof, args.days)

    blocks = []
    if args.section in ("weekly", "both"):
        blocks.append(weekly_section(conn, cfg, start, end))
    if args.section in ("recap", "both"):
        recap = recap_section(conn, cfg, start, end)
        if recap:
            blocks.append(recap)
    conn.close()

    out = "\n\n".join(b for b in blocks if b)
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
