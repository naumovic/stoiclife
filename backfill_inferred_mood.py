#!/usr/bin/env python3
"""MIN-136: one-off backfill of `journal_entries.inferred_mood` (the agent's mood guess).

  * inferred entries: the stored mood_score *is* the guess, so copy it;
  * manual entries: update_entry.py discarded the guess but logged it
    ("entry N has manual mood … (ignored inferred mood M)") — take the latest such
    line per entry from stoic.log (an entry can be scored more than once).

Only fills NULLs, so re-running is a no-op. Needs the column (python3 db_init.py).

    python3 backfill_inferred_mood.py --dry-run
    python3 backfill_inferred_mood.py [--db PATH] [--log PATH]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

STOIC_DIR = Path.home() / ".openclaw" / "stoic"
LOG_RE = re.compile(r"update_entry: entry (\d+) has manual mood .*\(ignored inferred mood (\d+)\)")


def logged_guesses(lines) -> dict[int, int]:
    """{entry_id: guess} from update_entry log lines; the latest line per entry wins."""
    out = {}
    for line in lines:
        m = LOG_RE.search(line)
        if m:
            out[int(m.group(1))] = int(m.group(2))
    return out


def backfill(conn: sqlite3.Connection, guesses: dict[int, int], dry_run: bool = False) -> dict:
    inferred = conn.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE inferred_mood IS NULL "
        "AND mood_source = 'inferred' AND mood_score IS NOT NULL").fetchone()[0]
    manual = [(eid, g) for eid, g in sorted(guesses.items())
              if conn.execute("SELECT 1 FROM journal_entries WHERE id = ? AND mood_source = 'manual' "
                              "AND inferred_mood IS NULL", (eid,)).fetchone()]
    if not dry_run:
        with conn:
            conn.execute("UPDATE journal_entries SET inferred_mood = mood_score WHERE inferred_mood IS NULL "
                         "AND mood_source = 'inferred' AND mood_score IS NOT NULL")
            conn.executemany("UPDATE journal_entries SET inferred_mood = ? WHERE id = ?",
                             [(g, eid) for eid, g in manual])
    return {"inferred": inferred, "manual": manual}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=STOIC_DIR / "stoic_journal.db")
    ap.add_argument("--log", type=Path, default=STOIC_DIR / "stoic.log")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with args.log.open(errors="replace") as fh:
        guesses = logged_guesses(fh)
    conn = sqlite3.connect(args.db)
    res = backfill(conn, guesses, dry_run=args.dry_run)
    verb = "would set" if args.dry_run else "set"
    print(f"{verb} inferred_mood on {res['inferred']} inferred entries (= mood_score)")
    print(f"{verb} inferred_mood on {len(res['manual'])} manual entries from the log:")
    for eid, g in res["manual"]:
        session, mood = conn.execute("SELECT session, mood_score FROM journal_entries WHERE id = ?",
                                     (eid,)).fetchone()
        print(f"  entry {eid} ({session}): you {mood}, coach {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
