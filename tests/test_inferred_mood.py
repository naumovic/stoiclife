#!/usr/bin/env python3
"""MIN-136: the coach's mood guess is kept on every entry (inferred_mood).

update_entry.py (shared workspace scripts) writes it next to a manual mood without touching
mood_score; backfill_inferred_mood.py recovers old guesses from the log; ux_metrics reports
you vs coach. Scratch DB only. Run: python3 tests/test_inferred_mood.py
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# repo first: the workspace scripts dir has its own (OpenClaw) db_init.py
sys.path.insert(0, str(Path.home() / ".openclaw" / "workspace" / "scripts"))
sys.path.insert(0, str(REPO))

import backfill_inferred_mood as bf  # noqa: E402
import db_init  # noqa: E402
import update_entry  # noqa: E402
import ux_metrics  # noqa: E402

failures = 0


def check(name, ok, got=None):
    global failures
    failures += 0 if ok else 1
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n       got={got!r}"))


tmp = Path(tempfile.mkdtemp())
DB = tmp / "j.db"
update_entry.DB_PATH, update_entry.LOG_PATH = DB, tmp / "stoic.log"


def fresh_db(with_column=True):
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE journal_entries (id INTEGER PRIMARY KEY, date TEXT, session TEXT, "
                 "raw_response TEXT, processed_themes TEXT, mood_score INTEGER, "
                 "mood_source TEXT DEFAULT 'inferred', module TEXT, created_at TEXT)")
    if with_column:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN inferred_mood INTEGER")
    conn.executemany("INSERT INTO journal_entries (id, date, session, mood_score, mood_source) VALUES (?,?,?,?,?)",
                     [(1, "2026-10-09", "morning", 6, "manual"), (2, "2026-10-09", "evening", None, "inferred"),
                      (3, "2026-10-10", "morning", 8, "manual")])
    conn.commit()
    return conn


def score(eid, mood):
    sys.argv = ["update_entry.py", "--entry-id", str(eid), "--mood-score", str(mood), "--themes", "a,b"]
    update_entry.main()


def row(conn, eid):
    return conn.execute("SELECT mood_score, mood_source, inferred_mood FROM journal_entries WHERE id = ?",
                        (eid,)).fetchone()


# --- the column is declared where stoiclife adds journal_entries columns -----------------
check("db_init declares journal_entries.inferred_mood",
      ("inferred_mood", "INTEGER") in db_init.COLUMN_MIGRATIONS["journal_entries"])

# --- update_entry --------------------------------------------------------------------------
conn = fresh_db()
score(1, 7)
check("manual entry: mood_score stays 6, guess 7 stored", row(conn, 1) == (6, "manual", 7), row(conn, 1))
score(2, 5)
check("inferred entry: mood_score and guess both 5", row(conn, 2) == (5, "inferred", 5), row(conn, 2))
score(1, 4)
check("re-scored: latest guess wins, manual mood kept", row(conn, 1) == (6, "manual", 4), row(conn, 1))
check("the log line is kept", "ignored inferred mood 4" in update_entry.LOG_PATH.read_text())

conn = fresh_db(with_column=False)
score(2, 6)
check("no column yet: update still works", conn.execute(
    "SELECT mood_score, processed_themes FROM journal_entries WHERE id = 2").fetchone() == (6, '["a", "b"]'))

# --- backfill --------------------------------------------------------------------------------
LOG = [
    "2026-10-07T20:49 INFO update_entry: entry 1 has manual mood — kept it, updated themes only (ignored inferred mood 5)",
    "2026-10-07T23:03 INFO update_entry: entry 1 has manual mood — kept it, updated themes only (ignored inferred mood 7)",
    "2026-10-08T07:39 INFO update_entry: entry 2 has manual mood — kept it, updated themes only (ignored inferred mood 9)",
    "2026-10-08T07:40 INFO sc_dispatch: something else entirely",
]
g = bf.logged_guesses(LOG)
check("log parse: latest line per entry", g == {1: 7, 2: 9}, g)

conn = fresh_db()
conn.execute("UPDATE journal_entries SET mood_score = 5 WHERE id = 2")
conn.commit()
res = bf.backfill(conn, g, dry_run=True)
check("dry run changes nothing", row(conn, 1)[2] is None and row(conn, 2)[2] is None)
check("dry run counts: 1 inferred, manual only entry 1 (entry 2 isn't manual)",
      res["inferred"] == 1 and res["manual"] == [(1, 7)], res)
bf.backfill(conn, g)
check("backfill: manual entry gets the logged guess", row(conn, 1) == (6, "manual", 7), row(conn, 1))
check("backfill: inferred entry copies mood_score", row(conn, 2) == (5, "inferred", 5), row(conn, 2))
check("backfill: no log line -> left NULL", row(conn, 3)[2] is None, row(conn, 3))
conn.execute("UPDATE journal_entries SET inferred_mood = 3 WHERE id = 1")
conn.commit()
again = bf.backfill(conn, g)
check("re-run is a no-op (only fills NULLs)", row(conn, 1)[2] == 3 and again["manual"] == [], again)

# --- ux_metrics ------------------------------------------------------------------------------
conn = fresh_db()
conn.executemany("UPDATE journal_entries SET inferred_mood = ? WHERE id = ?", [(7, 1), (5, 2), (8, 3)])
conn.commit()
mconn = ux_metrics.connect(DB)
m = ux_metrics.mood_guess(mconn, "2026-10-09", "2026-10-10")
check("metrics: only manual entries pair up (2 mornings)", m["all"]["pairs"] == 2 and m["evening"]["pairs"] == 0, m)
check("metrics: |diff| 0.5, exact 50%, bias +0.5",
      (m["all"]["mean_abs_diff"], m["all"]["exact_pct"], m["all"]["bias"]) == (0.5, 50.0, 0.5), m["all"])
# (the scratch DB has no FEAT-07 tables, so render a minimal metrics dict)
empty = {"sent": 0, "rated": 0, "feedback_rate_pct": None, "thumbs_up_share_pct": None, "down": 0, "neutral": 0}
out = ux_metrics.render({
    "range": ["2026-10-09", "2026-10-10"], "days": 2, "prompts": {}, "checkins": {},
    "feedback": {"all": empty, "by_kind": {}, "by_session": {}, "by_flagged": {}, "down_reasons_all_time": {}},
    "entries": {"entries": 0, "by_method": {}, "holds_offered": {}},
    "daily_updates": {"days": 0, "status": {}, "escalation": {}}, "mood_guess": m})
check("metrics: renders section 7", "7. Mood: you vs coach" in out and "pairs   2" in out, out)
conn = fresh_db(with_column=False)
check("metrics: no column -> None", ux_metrics.mood_guess(ux_metrics.connect(DB), "2026-10-09", "2026-10-10") is None)

print(f"\n{'all passed' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
