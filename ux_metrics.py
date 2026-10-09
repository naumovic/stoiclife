#!/usr/bin/env python3
"""FEAT-07 Phase 6: self-test metrics for the Telegram coach UX (read-only).

    python3 ux_metrics.py 2026-10-08 2026-10-21          # inclusive date range
    python3 ux_metrics.py 2026-10-08 2026-10-21 --json   # machine-readable

Reports, for the range:
  1. Prompt completion (entry ÷ prompt sent) and skip rate, morning and evening separately
  2. Median time from prompt to entry
  3. Mood and module logging rate (days with a check-in ÷ days), by source
  4. Feedback rate and 👍 share, by target kind (r = coaching reply, t = 🧭 push), by session,
     and by flagged vs unflagged data
  5. Entries by input method (typed after a prompt / button-started / legacy prefix / …)
  6. Daily update outcomes (synced, postponed, not synced, escalations)

Days are journaling days (`local_date` / `date`); everything reads the live DB with
`mode=ro`, so it never writes. Pre-FEAT-07 rows simply don't appear in the new tables.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_DB = Path.home() / ".openclaw" / "stoic" / "stoic_journal.db"
METHOD_LABELS = {
    "window": "typed after a prompt",
    "reply": "reply to a prompt",
    "hold": "confirmed via hold buttons",
    "write": "button-started (✍️ / /journal)",
    "prefix": "legacy prefix",
}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def prompts(conn, a: str, b: str) -> dict:
    out = {}
    for session in ("morning", "evening"):
        rows = conn.execute(
            "SELECT sent_at, skipped_at, entry_id, answered_at FROM prompt_events "
            "WHERE session = ? AND local_date BETWEEN ? AND ?", (session, a, b)).fetchall()
        sent = len(rows)
        answered = [r for r in rows if r["entry_id"]]
        skipped = [r for r in rows if r["skipped_at"] and not r["entry_id"]]
        mins = [(datetime.fromisoformat(r["answered_at"]) - datetime.fromisoformat(r["sent_at"])).total_seconds() / 60
                for r in answered if r["answered_at"]]
        out[session] = {"sent": sent, "answered": len(answered), "skipped": len(skipped),
                        "completion_pct": pct(len(answered), sent), "skip_pct": pct(len(skipped), sent),
                        "median_minutes_to_entry": round(statistics.median(mins), 1) if mins else None}
    return out


def checkins(conn, a: str, b: str, n_days: int) -> dict:
    out = {}
    for ctype in ("mood", "module"):
        rows = conn.execute("SELECT local_date, source FROM checkin_events WHERE type = ? AND "
                            "local_date BETWEEN ? AND ?", (ctype, a, b)).fetchall()
        days = {r["local_date"] for r in rows}
        by_source: dict[str, int] = {}
        for r in rows:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        out[ctype] = {"days_logged": len(days), "rate_pct": pct(len(days), n_days), "by_source": by_source}
    return out


def _flagged_r(flags_json: str | None) -> bool | None:
    if not flags_json:
        return None
    try:
        f = json.loads(flags_json)
    except ValueError:
        return None
    return bool(f.get("fired")) or f.get("state") not in (None, "neutral", "sweet_spot", "insufficient_data")


def feedback(conn, a: str, b: str) -> dict:
    """Targets = coaching messages sent in range (ui_messages coaching_r/coaching_t)."""
    targets = []
    for r in conn.execute(
            "SELECT kind, ref_id, session FROM ui_messages WHERE kind IN ('coaching_r', 'coaching_t') "
            "AND local_date BETWEEN ? AND ?", (a, b)):
        kind = r["kind"][-1]
        session, flagged = r["session"], None
        if kind == "r":
            cr = conn.execute("SELECT session, data_flags_json FROM coaching_responses WHERE id = ?",
                              (r["ref_id"],)).fetchone()
            if cr:
                session = cr["session"] or session
                flagged = _flagged_r(cr["data_flags_json"])
        else:
            tc = conn.execute("SELECT e.session FROM trigger_coaching c JOIN trigger_events e ON e.id = c.event_id "
                              "WHERE c.id = ?", (r["ref_id"],)).fetchone()
            session = tc["session"] if tc else session
            flagged = True  # a 🧭 push only exists on a flagged day
        fb = conn.execute("SELECT rating FROM response_feedback WHERE target_kind = ? AND target_id = ?",
                          (kind, r["ref_id"])).fetchone()
        targets.append({"kind": kind, "session": session or "unknown",
                        "flagged": {True: "flagged", False: "unflagged", None: "unknown"}[flagged],
                        "rating": fb["rating"] if fb else None})

    def summarise(rows):
        rated = [t for t in rows if t["rating"]]
        ups = [t for t in rated if t["rating"] == "up"]
        return {"sent": len(rows), "rated": len(rated), "feedback_rate_pct": pct(len(rated), len(rows)),
                "thumbs_up_share_pct": pct(len(ups), len(rated)),
                "down": sum(1 for t in rated if t["rating"] == "down"),
                "neutral": sum(1 for t in rated if t["rating"] == "neutral")}

    def group(key):
        keys = sorted({t[key] for t in targets})
        return {k: summarise([t for t in targets if t[key] == k]) for k in keys}

    reasons = {r["reason"]: r["n"] for r in conn.execute(
        "SELECT reason, COUNT(*) AS n FROM response_feedback WHERE reason IS NOT NULL GROUP BY reason")}
    return {"all": summarise(targets), "by_kind": group("kind"), "by_session": group("session"),
            "by_flagged": group("flagged"), "down_reasons_all_time": reasons}


def entries(conn, a: str, b: str) -> dict:
    """Input method per entry, from the Phase 4 route log; older entries count as 'before routing'."""
    total = conn.execute("SELECT COUNT(*) FROM journal_entries WHERE date BETWEEN ? AND ?", (a, b)).fetchone()[0]
    start, end = a + "T00:00:00", (date.fromisoformat(b) + timedelta(days=2)).isoformat() + "T00:00:00"
    routed = conn.execute("SELECT source, COUNT(*) AS n FROM route_events WHERE route = 'entry' "
                          "AND at >= ? AND at < ? GROUP BY source", (start, end)).fetchall()
    methods = {METHOD_LABELS.get(r["source"], r["source"]): r["n"] for r in routed}
    known = sum(methods.values())
    if total > known:
        methods["before routing / not routed"] = total - known
    holds = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) AS n FROM route_events WHERE route = 'hold' AND at >= ? AND at < ? "
        "GROUP BY source", (start, end))}
    return {"entries": total, "by_method": methods, "holds_offered": holds}


def daily_updates(conn, a: str, b: str) -> dict:
    rows = conn.execute("SELECT status, escalation FROM daily_updates WHERE local_date BETWEEN ? AND ?",
                        (a, b)).fetchall()
    count = lambda col: {k: sum(1 for r in rows if r[col] == k) for k in sorted({r[col] for r in rows if r[col]})}
    return {"days": len(rows), "status": count("status"), "escalation": count("escalation")}


def mood_guess(conn, a: str, b: str) -> dict | None:
    """MIN-136: your own mood (manual) vs the coach's guess (inferred_mood) on the same entry.
    None when the column isn't there yet (db_init.py adds it)."""
    try:
        rows = conn.execute("SELECT session, mood_score, inferred_mood FROM journal_entries WHERE date BETWEEN ? "
                            "AND ? AND mood_source = 'manual' AND mood_score IS NOT NULL "
                            "AND inferred_mood IS NOT NULL", (a, b)).fetchall()
    except sqlite3.OperationalError:
        return None

    def summarise(rs):
        diffs = [r["inferred_mood"] - r["mood_score"] for r in rs]
        n = len(diffs)
        return {"pairs": n,
                "mean_abs_diff": round(sum(abs(d) for d in diffs) / n, 2) if n else None,
                "exact_pct": pct(sum(1 for d in diffs if d == 0), n),
                "bias": round(sum(diffs) / n, 2) if n else None}
    out = {"all": summarise(rows)}
    for session in ("morning", "evening"):
        out[session] = summarise([r for r in rows if r["session"] == session])
    return out


def collect(conn, a: str, b: str) -> dict:
    n_days = (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
    return {"range": [a, b], "days": n_days, "prompts": prompts(conn, a, b),
            "checkins": checkins(conn, a, b, n_days), "feedback": feedback(conn, a, b),
            "entries": entries(conn, a, b), "daily_updates": daily_updates(conn, a, b),
            "mood_guess": mood_guess(conn, a, b)}


def fmt(v, suffix="") -> str:
    return "–" if v is None else f"{v}{suffix}"


def render(m: dict) -> str:
    L = [f"FEAT-07 UX metrics · {m['range'][0]} → {m['range'][1]} ({m['days']} days)", ""]
    L.append("1–2. Prompts")
    for s, p in m["prompts"].items():
        L.append(f"  {s:8} sent {p['sent']:3} · answered {p['answered']:3} ({fmt(p['completion_pct'], '%')}) · "
                 f"skipped {p['skipped']:3} ({fmt(p['skip_pct'], '%')}) · median to entry {fmt(p['median_minutes_to_entry'], ' min')}")
    L += ["", "3. Check-ins (days logged ÷ days)"]
    for t, c in m["checkins"].items():
        src = ", ".join(f"{k} {v}" for k, v in sorted(c["by_source"].items())) or "none"
        L.append(f"  {t:8} {c['days_logged']:3} days ({fmt(c['rate_pct'], '%')}) · by source: {src}")
    f = m["feedback"]
    L += ["", "4. Feedback (rated ÷ sent · 👍 share of rated)"]

    def line(label, s):
        return (f"  {label:18} sent {s['sent']:3} · rated {s['rated']:3} ({fmt(s['feedback_rate_pct'], '%')}) · "
                f"👍 {fmt(s['thumbs_up_share_pct'], '%')} · 👎 {s['down']} · neutral {s['neutral']}")
    L.append(line("all", f["all"]))
    for grp, title in (("by_kind", "kind"), ("by_session", "session"), ("by_flagged", "data")):
        for k, s in f[grp].items():
            label = {"r": "reply (r)", "t": "🧭 push (t)"}.get(k, k)
            L.append(line(f"{title}: {label}", s))
    if f["down_reasons_all_time"]:
        L.append("  👎 reasons (all time): " + ", ".join(f"{k} {v}" for k, v in f["down_reasons_all_time"].items()))
    e = m["entries"]
    L += ["", f"5. Entries by input method ({e['entries']} entries)"]
    for k, v in e["by_method"].items():
        L.append(f"  {k:32} {v}")
    if e["holds_offered"]:
        L.append("  holds offered: " + ", ".join(f"{k} {v}" for k, v in e["holds_offered"].items()))
    d = m["daily_updates"]
    L += ["", f"6. Daily updates ({d['days']} days)",
          "  status: " + (", ".join(f"{k} {v}" for k, v in d["status"].items()) or "none"),
          "  escalation: " + (", ".join(f"{k} {v}" for k, v in d["escalation"].items()) or "none")]
    g = m.get("mood_guess")
    L += ["", "7. Mood: you vs coach (entries with your mood and the coach's guess; bias = coach − you)"]
    if g is None:
        L.append("  inferred_mood column missing (run db_init.py)")
    else:
        for k, s in g.items():
            L.append(f"  {k:8} pairs {s['pairs']:3} · mean |diff| {fmt(s['mean_abs_diff'])} · "
                     f"exact {fmt(s['exact_pct'], '%')} · bias {fmt(s['bias'])}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("start", help="first day, YYYY-MM-DD")
    ap.add_argument("end", help="last day, YYYY-MM-DD (inclusive)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)
    for d in (args.start, args.end):
        date.fromisoformat(d)
    m = collect(connect(args.db), args.start, args.end)
    print(json.dumps(m, indent=2, ensure_ascii=False) if args.json else render(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
