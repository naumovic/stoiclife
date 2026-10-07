#!/usr/bin/env python3
"""stoiclife Phase 4 — Proactive Delivery orchestrator.

Deterministic brain that decides whether to interrupt and how. It does NOT call
an LLM or send anything itself; it prints a machine-readable directive that the
OpenClaw cron's agentTurn acts on (the agent generates the coaching and the framework
announces it; HEARTBEAT_OK = stay silent). `--channel` (default $STOICLIFE_CHANNEL, else
whatsapp) picks the text format for the channel that will deliver it.

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
import sys
from datetime import datetime
from pathlib import Path

import channel_fmt
from build_payload import render_payload
from states import STATE_DISPLAY
from status import health_check, render_health_lines, resolve_status_line
from trigger_matrix import (
    Result,
    connect,
    evaluate,
    fetch_biometrics_today,
    load_config,
)

from _tz import TZ  # active zone: home, or the trip zone while travel-mode is on
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


def find_held(conn, target_date: str, max_age_days: int):
    """Most recent fired, held, not-yet-sent message still within the release window.

    A quiet-hours hold is meant to be delivered the *next* morning (Decision B), so a
    hold whose date is older than max_age_days is stale: it is skipped here (and cleared
    by expire_stale_holds) rather than delivered days/weeks late.
    """
    return conn.execute(
        "SELECT * FROM trigger_events "
        "WHERE held_for_quiet_hours = 1 AND message_sent = 0 AND fired = 1 "
        "  AND date >= date(?, ?) "
        "ORDER BY id DESC LIMIT 1",
        (target_date, f"-{max_age_days} days"),
    ).fetchone()


def count_stale_holds(conn, target_date: str, max_age_days: int) -> int:
    """Held-but-undelivered messages older than the release window."""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM trigger_events "
        "WHERE held_for_quiet_hours = 1 AND message_sent = 0 AND fired = 1 "
        "  AND date < date(?, ?)",
        (target_date, f"-{max_age_days} days"),
    ).fetchone()["n"]


def expire_stale_holds(conn, target_date: str, max_age_days: int) -> int:
    """Clear the held flag on holds older than the release window (never delivered).

    Keeps stale holds from lingering as held=1 and from being delivered late if the
    window is later widened. Returns the number expired.
    """
    note = f"hold expired: stale >{max_age_days}d, never delivered"
    cur = conn.execute(
        "UPDATE trigger_events SET held_for_quiet_hours = 0, "
        "  notes = COALESCE(notes || '; ', '') || ? "
        "WHERE held_for_quiet_hours = 1 AND message_sent = 0 AND fired = 1 "
        "  AND date < date(?, ?)",
        (note, target_date, f"-{max_age_days} days"),
    )
    conn.commit()
    return cur.rowcount


def mark_hold_released(conn, event_id: int) -> None:
    """Clear the held flag when a hold is released to the agent (deliver-once).

    Load-bearing fix for the FEAT-04 wedge: a CLARIFY hold has no downstream
    record_coaching step to set message_sent=1, so without this it is re-found on every
    run and the start-of-run sweep never reaches today's eval (the 2026-06-20 → 08-05
    morning/safety-net outage). SEND_FULL is cleared here too — a hold is delivered once,
    the next morning, not retried for days; a failed generation is dropped, consistent
    with the normal fired path (which also doesn't retry). Stale-expiry is the backstop.
    """
    conn.execute("UPDATE trigger_events SET held_for_quiet_hours = 0 WHERE id = ?",
                 (event_id,))
    conn.commit()


def result_from_row(row) -> Result:
    """Reconstruct a Result from a stored trigger_events row (for held release)."""
    return Result(
        date=row["date"], session=row["session"], state=row["state"],
        physical_summary="(held)", mental_summary="(held)",
        deltas=json.loads(row["deltas_json"] or "{}"),
        matched_keywords=(row["matched_keywords"].split(",") if row["matched_keywords"] else []),
        confidence=row["confidence"], notes="released from overnight quiet-hours hold",
    )


def decide(conn, cfg, target_date, session, write, ignore_quiet_hours=False):
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
    if not ignore_quiet_hours and in_quiet_hours(datetime.now(TZ), cfg):
        if write and event_id is not None:
            conn.execute("UPDATE trigger_events SET held_for_quiet_hours = 1 WHERE id = ?",
                         (event_id,))
            conn.commit()
        return "HOLD_QUIET", result, fired, event_id, f"{action} held until quiet hours end"

    return action, result, fired, event_id, f"confidence {conf}"


def emit(conn, cfg, action, result, event_id, detail, dry, health=None,
         status_line=None, signal="none", channel=channel_fmt.DEFAULT_CHANNEL):
    print(f"STOICLIFE_ACTION: {action}")
    print(f"# date={result.date} session={result.session} state={result.state} "
          f"confidence={result.confidence} event_id={event_id} dry_run={dry}")
    print(f"# {detail}")
    sm = result.deltas.get("sleep_modulator")
    if sm:
        print(f"# sleep_modulator: flag={sm['flag']} 7d_score_avg={sm.get('sleep_score_avg')} "
              f"7d_dur_avg={sm.get('sleep_duration_avg')} bias={sm.get('confidence_bias')} "
              f"effect=\"{sm.get('effect') or 'no change'}\""
              + (f" reasons=\"{'; '.join(sm['reasons'])}\"" if sm.get("reasons") else ""))
    spm = result.deltas.get("spo2_modulator")
    if spm:
        print(f"# spo2_modulator: flag={spm['flag']} spo2={spm.get('yesterday_spo2')} "
              f"7d_avg={spm.get('rolling_avg')} bias={spm.get('confidence_bias')} "
              f"effect=\"{spm.get('effect') or 'no change'}\""
              + (f" reasons=\"{'; '.join(spm['reasons'])}\"" if spm.get("reasons") else ""))

    # FEAT-02 Step 1: surface the pipeline-health breakdown in --dry-run. Nothing
    # is sent or written yet — the status line itself lands in Step 2.
    if dry and health is not None:
        for line in render_health_lines(health):
            print(line)
        # FEAT-02 Step 3: surface the resolved status for any date — the exact
        # line (when any) is printed as the STOICLIFE_STATUS directive below.
        print(f"# status_signal: {signal}"
              + ("" if status_line else " (no line appended on this eval)"))

    # FEAT-02 Step 2: the in-turn status line to append to the silent-day coach
    # reply (resolve_status_line gates this to SILENT morning/evening evals).
    if status_line is not None:
        print()
        print("# AGENT: append the STOICLIFE_STATUS line below verbatim as the final "
              "line of the normal Stoic coach reply.")
        print(f"STOICLIFE_STATUS: {status_line}")

    if action in ("SILENT", "HOLD_QUIET"):
        return

    if action == "CLARIFY":
        print()
        print("# AGENT: send the line below to Mihajlo verbatim. In the journal hook, also send "
              "the normal coaching reply.")
        print()
        print(channel_fmt.render(clarify_message(result.state, result.deltas), channel))
        return

    if action == "SEND_FULL":
        # FEAT-07 (P2-D4): on Telegram, record_coaching --send delivers the message itself
        # with 👍/👎 buttons and prints NO_REPLY. WhatsApp (rollback path) is unchanged.
        send = " --send" if channel == "telegram" else ""
        rec = (f"printf '%s' \"<your message>\" | python3 {REPO_DIR}/record_coaching.py "
               f"--event-id {event_id} --channel {channel}{send}")
        print()
        print("# AGENT: compose the coaching per the payload below (strict format), then record+send it:")
        print(f"#   {rec}")
        if send:
            print("#   If it rejects (exit 2), fix the format and retry once. On exit 0 it has sent the "
                  "message for you: reply NO_REPLY. In the journal hook this REPLACES the normal reply.")
        else:
            print("#   If record_coaching rejects (exit!=0), fix the format and retry once, then send "
                  "the message. In the journal hook this REPLACES the normal reply.")
        print()
        print(render_payload(
            conn, cfg, state=result.state, date=result.date, session=result.session,
            deltas=result.deltas, matched_keywords=",".join(result.matched_keywords),
            confidence=result.confidence, channel=channel,
        ))


def main():
    p = argparse.ArgumentParser(description="stoiclife proactive delivery orchestrator")
    p.add_argument("--date", default=None,
                   help="defaults to the --entry-id row's date, else today in the active tz")
    p.add_argument("--entry-id", type=int, default=None,
                   help="evaluate the day this journal entry belongs to (preferred for the "
                        "in-turn hook: save_entry.py back-dates late replies, so the row's "
                        "date is authoritative and the wall clock is not)")
    p.add_argument("--session", choices=["morning", "evening", "safety-net"],
                   default="safety-net")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--dry-run", action="store_true",
                   help="read-only: classify + decide + show the message, write nothing")
    p.add_argument("--ignore-quiet-hours", action="store_true",
                   help="testing override: do not hold sends during quiet hours")
    p.add_argument("--channel", choices=channel_fmt.CHANNELS, default=None,
                   help=f"text format for the delivering channel "
                        f"(default: ${channel_fmt.ENV_VAR}, else {channel_fmt.DEFAULT_CHANNEL})")
    args = p.parse_args()
    channel = channel_fmt.resolve(args.channel)

    cfg = load_config(Path(args.config))
    conn = connect(cfg["db_path"])

    # Resolve the day being evaluated. The wall clock is the wrong answer whenever
    # save_entry.py back-dated the reply — an evening review answered after midnight
    # belongs to the previous day, but a wall-clock --date would evaluate the new one,
    # find no journal entry, and emit a false "heads up" warning (trigger_events ids 80
    # and 86 are exactly this). The saved row knows its own date, so prefer it.
    if args.date is None:
        if args.entry_id is not None:
            row = conn.execute(
                "SELECT date FROM journal_entries WHERE id = ?", (args.entry_id,)
            ).fetchone()
            if row is None:
                print(f"error: no journal entry with id {args.entry_id}", file=sys.stderr)
                sys.exit(2)   # main() has no return-code contract; exit directly
            args.date = row["date"]
        else:
            args.date = datetime.now(TZ).strftime("%Y-%m-%d")

    # Start-of-run sweep (Decision B): once quiet hours have passed, deliver any
    # message that was held overnight, before evaluating today. A hold is released
    # exactly once (the next morning) and marked handled on release so it can't
    # re-wedge the sweep; holds older than held_max_age_days are expired, never
    # delivered late. See INSTRUCTIONS.md FEAT-04. (Progress notes go to stderr so the
    # STOICLIFE_ACTION-first-line stdout contract is preserved.)
    if not args.ignore_quiet_hours and not in_quiet_hours(datetime.now(TZ), cfg):
        max_age = cfg.get("quiet_hours", {}).get("held_max_age_days", 2)
        n_stale = count_stale_holds(conn, args.date, max_age)
        if n_stale:
            if not args.dry_run:
                expire_stale_holds(conn, args.date, max_age)
            print(f"# {'would expire' if args.dry_run else 'expired'} {n_stale} stale held "
                  f"message(s) (>{max_age}d, never delivered)", file=sys.stderr)
        held = find_held(conn, args.date, max_age)
        if held is not None:
            res = result_from_row(held)
            gate = cfg["confidence_gate"]
            action = "SEND_FULL" if res.confidence >= gate["auto_send"] else "CLARIFY"
            # Deliver-once: mark the hold handled BEFORE emitting so it is never
            # re-found next run (CLARIFY has no record_coaching step to clear it).
            if not args.dry_run:
                mark_hold_released(conn, held["id"])
            emit(conn, cfg, action, res, held["id"], "released from overnight quiet-hours hold",
                 args.dry_run, channel=channel)
            conn.close()
            return

    action, result, fired, event_id, detail = decide(
        conn, cfg, args.date, args.session, write=not args.dry_run,
        ignore_quiet_hours=args.ignore_quiet_hours,
    )
    # FEAT-02 Step 1: certify pipeline health for this eval (reuse the matrix's
    # lag-resolved "today" biometrics row). Exposed for the dry-run breakdown;
    # the in-turn status line is wired in Step 2.
    today_bio = fetch_biometrics_today(conn, args.date, cfg.get("biometrics_max_lag_days", 0))
    health = health_check(cfg, result, today_bio, now=datetime.now(TZ))

    # FEAT-02 Step 2: resolve the in-turn status line (SILENT evening, plus a FEAT-05
    # late morning) and record what was emitted on this eval's row (all_ok|warning|none).
    signal, status_line = resolve_status_line(cfg, action, args.session, health,
                                              target_date=args.date, now=datetime.now(TZ),
                                              channel=channel)
    if not args.dry_run and event_id is not None:
        conn.execute("UPDATE trigger_events SET status_signal = ? WHERE id = ?",
                     (signal, event_id))
        conn.commit()

    emit(conn, cfg, action, result, event_id, detail, args.dry_run,
         health=health, status_line=status_line, signal=signal, channel=channel)
    conn.close()


if __name__ == "__main__":
    main()
