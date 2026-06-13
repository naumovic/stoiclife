#!/usr/bin/env python3
"""stoiclife Phase 4 — Proactive Delivery orchestrator.

Deterministic brain that decides whether to interrupt and how. It does NOT call
an LLM or send anything itself; it prints a machine-readable directive that the
OpenClaw cron's agentTurn acts on (Ewok generates the coaching and the framework
announces it to WhatsApp; HEARTBEAT_OK = stay silent).

Flow: matrix -> cooldown -> confidence gate -> quiet hours -> dedup.

Actions printed on the first line as `STOICLIFE_ACTION: <X>`:
  SILENT        nothing to do (silent state, cooldown, <40 confidence, already sent)
  CLARIFY       40-69 confidence: a short one-line "want the full read?" message follows
  SEND_FULL     >=70: the build_payload payload follows, for Ewok to generate + send
  HOLD_QUIET    a sendable state landed in quiet hours; held to release next morning

Usage:
    python3 stoiclife_run.py --session safety-net            # real run (writes events)
    python3 stoiclife_run.py --session evening --dry-run     # read-only simulation
    python3 stoiclife_run.py --date 2026-06-09 --dry-run
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from build_payload import render_payload
from states import STATE_DISPLAY
from trigger_matrix import connect, evaluate, load_config

TZ = ZoneInfo("Australia/Brisbane")
REPO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_DIR / "stoiclife_config.json"


def in_quiet_hours(now: datetime, cfg: dict) -> bool:
    qh = cfg["quiet_hours"]
    start = datetime.strptime(qh["start"], "%H:%M").time()
    end = datetime.strptime(qh["end"], "%H:%M").time()
    t = now.time()
    if start <= end:               # same-day window
        return start <= t < end
    return t >= start or t < end   # wraps midnight (21:00 -> 07:00)


def clarify_message(state: str, deltas: dict) -> str:
    """A short, LLM-free 'want the full read?' nudge for mid-confidence states."""
    display = STATE_DISPLAY[state]
    bits = []
    if deltas.get("hrv_delta_pct") is not None:
        bits.append(f"HRV {deltas['hrv_delta_pct']:+}% vs baseline")
    if deltas.get("sleep_today_min") is not None:
        bits.append(f"sleep {int(deltas['sleep_today_min']) // 60}h{int(deltas['sleep_today_min']) % 60:02d}")
    signal = "; ".join(bits) if bits else "a mixed mind/body signal"
    return (f"🧭 stoiclife: I'm seeing a possible *{display}* pattern today ({signal}). "
            f"Want the full read? Reply *yes* and I'll send the coaching.")


def decide(conn, cfg, target_date, session, write):
    """Return (action, result, fired, event_id, detail)."""
    gate = cfg["confidence_gate"]
    result, fired, cooldown_skipped, event_id = evaluate(
        conn, cfg, target_date, session, write=write
    )

    # Silent states / suppressed -> no message (event still logged when write=True).
    if not fired:
        return "SILENT", result, fired, event_id, f"state={result.state}, cooldown_skipped={cooldown_skipped}"

    # Idempotency: if this same state already sent a full message today, don't repeat.
    if write and event_id is not None:
        already = conn.execute(
            "SELECT COUNT(*) AS n FROM trigger_events "
            "WHERE date = ? AND state = ? AND message_sent = 1 AND id != ?",
            (target_date, result.state, event_id),
        ).fetchone()["n"]
        if already:
            return "SILENT", result, fired, event_id, "already sent today"

    # Confidence gate (Decision E).
    conf = result.confidence
    if conf < gate["clarify_min"]:
        return "SILENT", result, fired, event_id, f"confidence {conf} < {gate['clarify_min']}"
    if conf < gate["auto_send"]:
        action = "CLARIFY"
    else:
        action = "SEND_FULL"

    # Quiet hours (Decision B): hold, don't drop.
    if in_quiet_hours(datetime.now(TZ), cfg):
        if write and event_id is not None:
            conn.execute("UPDATE trigger_events SET held_for_quiet_hours = 1 WHERE id = ?",
                         (event_id,))
            conn.commit()
        return "HOLD_QUIET", result, fired, event_id, f"{action} held until quiet hours end"

    return action, result, fired, event_id, f"confidence {conf}"


def emit(conn, cfg, action, result, event_id, detail, dry):
    print(f"STOICLIFE_ACTION: {action}")
    print(f"# date={result.date} session={result.session} state={result.state} "
          f"confidence={result.confidence} event_id={event_id} dry_run={dry}")
    print(f"# {detail}")

    if action in ("SILENT", "HOLD_QUIET"):
        return

    if action == "CLARIFY":
        print()
        print(clarify_message(result.state, result.deltas))
        return

    if action == "SEND_FULL":
        print()
        print(render_payload(
            conn, cfg, state=result.state, date=result.date, session=result.session,
            deltas=result.deltas, matched_keywords=",".join(result.matched_keywords),
            confidence=result.confidence,
        ))


def main():
    p = argparse.ArgumentParser(description="stoiclife proactive delivery orchestrator")
    p.add_argument("--date", default=datetime.now(TZ).strftime("%Y-%m-%d"),
                   help="defaults to today (AEST)")
    p.add_argument("--session", choices=["morning", "evening", "safety-net"],
                   default="safety-net")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--dry-run", action="store_true",
                   help="read-only: classify + decide + show the message, write nothing")
    args = p.parse_args()

    cfg = load_config(Path(args.config))
    conn = connect(cfg["db_path"])
    action, result, fired, event_id, detail = decide(
        conn, cfg, args.date, args.session, write=not args.dry_run
    )
    emit(conn, cfg, action, result, event_id, detail, args.dry_run)
    conn.close()


if __name__ == "__main__":
    main()
