#!/usr/bin/env python3
"""stoiclife Phase 3 — assemble the coaching payload for a fired trigger.

Given a FIRED trigger_events row, this builds the tailored context block + the
state-specific system prompt that Ewok/OpenClaw consumes to generate the
coaching message. It does NOT call an LLM itself (matching the existing
coach_context.py pattern) and it refuses silent/non-fired states.

The generated text is then validated (coaching_format.py) and stored
(record_coaching.py) before it leaves the evaluation stage.

Usage:
    python3 build_payload.py --event-id N
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from coaching_format import CORRELATION, HEADER_PREFIX, OBSERVATION
from states import NON_SILENT, STATE_DISPLAY, STATE_OBJECTIVE

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"
PROMPTS_DIR = REPO_DIR / "prompts"
KNOWLEDGE_PATH = "~/.openclaw/stoic/stoic_knowledge.md"
JOURNAL_WINDOW_DAYS = 3  # ~72h, by calendar date (matches coach_context.py)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text())


def connect(db_path: str) -> sqlite3.Connection:
    resolved = Path(os.path.expanduser(db_path))
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def fmt_minutes(mins) -> str:
    if mins is None:
        return "n/a"
    return f"{int(mins) // 60}h{int(mins) % 60:02d} ({int(mins)} min)"


def fmt_deltas(d: dict) -> list[str]:
    """Human-readable biometric deltas vs the 7-day baseline."""
    out = []
    if d.get("hrv_today_ms") is not None and d.get("hrv_avg_ms") is not None:
        diff = round(d["hrv_today_ms"] - d["hrv_avg_ms"], 1)
        out.append(
            f"HRV {d['hrv_today_ms']} ms ({diff:+} ms / {d['hrv_delta_pct']:+}% "
            f"vs 7-day avg {d['hrv_avg_ms']})"
        )
    if d.get("rhr_today_bpm") is not None and d.get("rhr_avg_bpm") is not None:
        diff = round(d["rhr_today_bpm"] - d["rhr_avg_bpm"], 1)
        out.append(
            f"Resting HR {d['rhr_today_bpm']} bpm ({diff:+} bpm / {d['rhr_delta_pct']:+}% "
            f"vs avg {d['rhr_avg_bpm']})"
        )
    if d.get("sleep_today_min") is not None:
        sleep = f"Sleep {fmt_minutes(d['sleep_today_min'])}"
        if d.get("sleep_avg_min") is not None:
            sleep += f" (avg {fmt_minutes(d['sleep_avg_min'])})"
        out.append(sleep)
    sm = d.get("sleep_modulator")
    if sm and sm.get("flag"):
        bits = []
        if sm.get("sleep_score_avg") is not None:
            bits.append(f"7-day sleep-score avg {sm['sleep_score_avg']} (benchmark {sm.get('score_benchmark')})")
        if sm.get("sleep_duration_avg") is not None:
            bits.append(f"7-day sleep-duration avg {fmt_minutes(sm['sleep_duration_avg'])}")
        out.append("Sustained low sleep: " + "; ".join(bits))
    spm = d.get("spo2_modulator")
    if spm and spm.get("flag"):
        bits = [f"SpO2 {spm['yesterday_spo2']}% overnight"]
        if spm.get("rolling_avg") is not None:
            bits.append(f"7-day avg {spm['rolling_avg']}%")
        bits.append(f"baseline {spm.get('baseline_pct')}%")
        out.append("Blood-oxygen dip (wellness signal, not a medical reading): "
                   + "; ".join(bits))
    return out


def spo2_guidance(deltas: dict) -> str | None:
    """Non-diagnostic framing line when an SpO2 dip is contributing to coaching."""
    spm = deltas.get("spo2_modulator")
    if not (spm and spm.get("flag")):
        return None
    return ("NOTE on the blood-oxygen (SpO2) signal: treat it as a soft wellness nudge, "
            "NOT a medical reading. Do not use diagnostic or alarming language. Only if it "
            "were persistently low would you gently suggest checking with a professional — "
            "otherwise frame it as one more reason to protect rest/recovery today.")


def fetch_journal_window(conn, end_date: str) -> list[sqlite3.Row]:
    start = f"date('{end_date}', '-{JOURNAL_WINDOW_DAYS - 1} days')"
    return conn.execute(
        f"""
        SELECT date, session, raw_response, mood_score, processed_themes
        FROM journal_entries
        WHERE date >= {start} AND date <= ?
        ORDER BY date, id
        """,
        (end_date,),
    ).fetchall()


def render_payload(conn, cfg: dict, *, state: str, date: str, session: str,
                   deltas: dict, matched_keywords: str, confidence) -> str:
    """Render the full coaching payload from already-classified inputs.

    Used both by build() (from a persisted event) and by the orchestrator's
    dry-run (from an in-memory classification, no DB row required).
    """
    display = STATE_DISPLAY[state]
    objective = STATE_OBJECTIVE[state]
    prompt_template = (PROMPTS_DIR / f"{state}.md").read_text().strip()
    journal = fetch_journal_window(conn, date)

    # --- Context block ---
    ctx = [f"=== CONTEXT: {display} (date {date}, {session}) ===", ""]
    ctx.append(f"Detected state: {display}")
    ctx.append(f"Coach's objective: {objective}")
    if matched_keywords:
        ctx.append(f"Journal keywords matched: {matched_keywords}")
    ctx.append(f"Classifier confidence: {confidence}/100")
    bio_date = deltas.get("bio_date")
    bio_lag = deltas.get("bio_lag_days") or 0
    bio_label = (
        f"Biometric deltas (body data from {bio_date}, {bio_lag} day(s) before today, vs 7-day baseline):"
        if bio_date and bio_lag else "Biometric deltas (today vs 7-day baseline):"
    )
    ctx += ["", bio_label]
    ctx += [f"  • {line}" for line in fmt_deltas(deltas)]
    ctx += ["", f"Journal entries (last {JOURNAL_WINDOW_DAYS} days):", ""]
    for r in journal:
        mood = f"mood {r['mood_score']}" if r["mood_score"] is not None else "mood n/a"
        ctx.append(f"[{r['date']} | {r['session']} | {mood}]")
        ctx.append((r["raw_response"] or "").strip())
        if r["processed_themes"]:
            ctx.append(f"themes: {r['processed_themes']}")
        ctx.append("")

    # --- Strict output contract ---
    fmt_block = "\n".join([
        "Respond with EXACTLY this shape — plain text, no markdown tables or # headers:",
        "",
        f"{HEADER_PREFIX} {display}",
        f"{OBSERVATION} <one line: what today's body/mind data shows>",
        f"{CORRELATION} <one line: how that ties to the recent journal entries>",
        "1. <actionable recommendation>",
        "2. <actionable recommendation>",
        "",
        "Exactly two numbered recommendations. No preamble, no closing line.",
    ])

    payload = "\n".join([
        "=== SYSTEM PROMPT ===",
        f"You are Ewok, a Stoic life coach in the Ken Mogi *Think Like a Stoic* voice "
        f"(see {KNOWLEDGE_PATH}: ikigai, nagomi, kodawari, onceness, dichotomy of "
        f"control, premeditatio malorum, amor fati). Be direct, grounded, and "
        f"action-oriented — candor over flattery, no empty platitudes.",
        "",
        prompt_template,
        "",
        "Ground every line in the specific numbers and journal content below — name "
        "the actual deltas and reference what the user actually wrote. Do not "
        "generalise.",
        *( [ "", guidance ] if (guidance := spo2_guidance(deltas)) else [] ),
        "",
        fmt_block,
        "",
        "\n".join(ctx).rstrip(),
    ])
    return payload


def build(event_id: int, cfg: dict) -> str:
    """CLI entry: load a FIRED event from the DB and render its payload."""
    conn = connect(cfg["db_path"])
    ev = conn.execute("SELECT * FROM trigger_events WHERE id = ?", (event_id,)).fetchone()
    if ev is None:
        die(f"trigger_events id {event_id} not found")
    if ev["state"] not in NON_SILENT:
        die(f"state '{ev['state']}' is silent — no coaching is generated for it")
    if not ev["fired"]:
        die(f"event {event_id} did not fire (cooldown/suppressed) — nothing to coach")

    payload = render_payload(
        conn, cfg, state=ev["state"], date=ev["date"], session=ev["session"],
        deltas=json.loads(ev["deltas_json"] or "{}"),
        matched_keywords=ev["matched_keywords"], confidence=ev["confidence"],
    )
    conn.close()
    return payload


def main():
    p = argparse.ArgumentParser(description="Build the coaching payload for a fired trigger.")
    p.add_argument("--event-id", type=int, required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = p.parse_args()
    print(build(args.event_id, load_config(Path(args.config))))


if __name__ == "__main__":
    main()
