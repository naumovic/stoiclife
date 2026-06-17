#!/usr/bin/env python3
"""stoiclife-owned migration against the shared Stoic journal DB.

Creates the `trigger_events` audit/tuning table. Idempotent. This does NOT
touch the OpenClaw `scripts/db_init.py`; stoiclife only adds its own table to
the shared database.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_DB = "~/.openclaw/stoic/stoic_journal.db"

# Every evaluation writes a row here, whether or not it fires — the audit trail.
SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_events (
    id                  INTEGER PRIMARY KEY,
    eval_datetime       TEXT NOT NULL,            -- ISO8601, AEST, when the matrix ran
    date                TEXT NOT NULL,            -- the day being classified (YYYY-MM-DD)
    session             TEXT NOT NULL,            -- morning | evening | safety-net
    state               TEXT NOT NULL,            -- rattled_but_ready | running_on_fumes | system_drain | sweet_spot | neutral | insufficient_data
    deltas_json         TEXT,                     -- JSON: today's deltas vs 7-day baseline
    matched_keywords    TEXT,                     -- comma-separated keywords found in today's journal
    confidence          INTEGER,                  -- 0-100
    fired               INTEGER NOT NULL DEFAULT 0,  -- bool: a non-silent state cleared cooldown
    cooldown_skipped    INTEGER NOT NULL DEFAULT 0,  -- bool: would have fired but suppressed by cooldown
    message_sent        INTEGER NOT NULL DEFAULT 0,  -- bool: set in Phase 4
    held_for_quiet_hours INTEGER NOT NULL DEFAULT 0, -- bool: set in Phase 4
    usefulness          INTEGER,                  -- nullable: set in Phase 5 feedback loop
    status_signal       TEXT,                     -- FEAT-02: status line emitted on a silent day (all_ok | warning | none); per-eval audit only
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_trigger_events_date  ON trigger_events(date);
CREATE INDEX IF NOT EXISTS idx_trigger_events_state ON trigger_events(state, fired);

-- Phase 3: generated coaching text, linked to the firing event. One event can
-- have more than one row if a first generation fails validation and is retried.
CREATE TABLE IF NOT EXISTS trigger_coaching (
    id                INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES trigger_events(id),
    generated_at      TEXT NOT NULL,            -- ISO8601, AEST
    state             TEXT NOT NULL,
    coaching_text     TEXT NOT NULL,
    valid             INTEGER NOT NULL,         -- bool: passed strict-format validation
    validation_errors TEXT,                     -- comma-separated, NULL when valid
    -- Phase 5 feedback loop: usefulness rating captured when Mihajlo reacts.
    usefulness        INTEGER,                  -- +1 useful / 0 neutral / -1 not useful / NULL unrated
    reaction_raw      TEXT,                     -- the raw reply text (👍, a word, a sentence)
    reacted_at        TEXT                      -- ISO8601, AEST, when the rating landed
);

CREATE INDEX IF NOT EXISTS idx_trigger_coaching_event ON trigger_coaching(event_id);
"""

# Columns added to tables that predate them (the CREATE above only applies to
# fresh DBs; `biometrics` is owned by OpenClaw's db_init). Each is added only if
# missing, so this is safe to run repeatedly.
COLUMN_MIGRATIONS = {
    "trigger_coaching": [
        ("usefulness", "INTEGER"),
        ("reaction_raw", "TEXT"),
        ("reacted_at", "TEXT"),
    ],
    # FEAT-02: per-eval audit of the status line emitted on a silent day
    # (all_ok | warning | none). Audit-only — no weekly surfacing planned.
    "trigger_events": [
        ("status_signal", "TEXT"),
    ],
    # FEAT-01 Part A: self-computed nightly sleep score (0-100), NULL when a
    # night lacks stage data. Usually already present on the live DB.
    # FEAT-01 Part B: blood-oxygen (SpO2) from the Google Health API
    # `daily-oxygen-saturation` type, computed post-sleep (dated to yesterday).
    # min/max are the distribution's lower/upper bound percentages; stddev is the
    # night's variability. All nullable — a night without a reading stays NULL.
    "biometrics": [
        ("sleep_score", "INTEGER"),
        ("spo2_avg", "REAL"),
        ("spo2_min", "REAL"),
        ("spo2_max", "REAL"),
        ("spo2_stddev", "REAL"),
    ],
}


def add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """Idempotently ALTER in any Phase 5 columns absent from an existing table."""
    added = []
    for table, cols in COLUMN_MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(f"{table}.{name}")
    return added


def resolve_db_path() -> Path:
    """Use the same db_path the matrix uses, falling back to the default."""
    cfg = REPO_DIR / "stoiclife_config.json"
    raw = DEFAULT_DB
    if cfg.exists():
        try:
            raw = json.loads(cfg.read_text()).get("db_path", DEFAULT_DB)
        except (ValueError, OSError):
            raw = DEFAULT_DB
    return Path(os.path.expanduser(raw))


def main() -> None:
    db_path = resolve_db_path()
    if not db_path.exists():
        raise SystemExit(
            f"Shared DB not found at {db_path}. Run the OpenClaw db_init.py first."
        )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        added = add_missing_columns(conn)
        conn.commit()
    print(f"trigger_events + trigger_coaching ready in {db_path}")
    if added:
        print(f"migrated columns: {', '.join(added)}")


if __name__ == "__main__":
    main()
