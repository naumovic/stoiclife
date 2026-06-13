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
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_trigger_events_date  ON trigger_events(date);
CREATE INDEX IF NOT EXISTS idx_trigger_events_state ON trigger_events(state, fired);
"""


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
        conn.commit()
    print(f"trigger_events ready in {db_path}")


if __name__ == "__main__":
    main()
