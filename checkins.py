#!/usr/bin/env python3
"""FEAT-07: mood/module check-ins (buttons, commands, legacy prefixes).

One row per (chat, logical day, type) in `checkin_events`; the latest tap wins.
`merge_into_entry` folds a day's check-ins into a journal entry as it is saved
(called from save_entry.py), following the G9 rule in docs/FEAT07-UX-TELEGRAM-SEED.md:

  * an inline `mood N` / `module:x` in the entry text always wins;
  * a check-in only lands on an entry if it was updated after the previous entry
    of the same logical day was created (so a morning tap belongs to the morning
    entry and doesn't leak onto the evening one).

Pure stdlib; no network. Import-safe (no side effects).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time as time_cls, timedelta
from pathlib import Path

from _tz import TZ  # active travel-mode zone (D19)

REPO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = REPO_DIR / "stoiclife_config.json"
DEFAULT_DB = Path.home() / ".openclaw" / "stoic" / "stoic_journal.db"

# Keep in step with save_entry.MORNING_CUTOFF (tests/test_checkins.py asserts it):
# the journaling day rolls over at the morning prompt, not at midnight.
MORNING_CUTOFF = time_cls(7, 30)

CHECKIN_TYPES = ("mood", "module")
SOURCES = ("button", "command", "legacy_prefix")
MOOD_MIN, MOOD_MAX = 1, 10


def coach_config() -> dict:
    """The `coach` block of stoiclife_config.json (chat_id, account)."""
    try:
        block = json.loads(CONFIG_PATH.read_text()).get("coach") or {}
    except (OSError, ValueError):
        block = {}
    return {"chat_id": str(block.get("chat_id", "8917837483")),
            "account": block.get("account", "coach")}


def now_local() -> datetime:
    return datetime.now(TZ)


def local_date(now: datetime | None = None) -> str:
    """Logical journaling day (YYYY-MM-DD) in the active zone: before 07:30 counts as yesterday."""
    now = (now or now_local()).astimezone(TZ)
    if now.time() < MORNING_CUTOFF:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def validate(ctype: str, value) -> str:
    """Normalise a check-in value or raise ValueError."""
    if ctype == "mood":
        n = int(value)
        if not MOOD_MIN <= n <= MOOD_MAX:
            raise ValueError(f"mood out of range: {n}")
        return str(n)
    if ctype == "module":
        v = str(value).strip().lower()
        if not v:
            raise ValueError("empty module")
        return v
    raise ValueError(f"unknown check-in type: {ctype}")


def upsert(conn: sqlite3.Connection, *, chat_id: str, ctype: str, value, source: str,
           day: str | None = None, message_id: str | None = None,
           now: datetime | None = None) -> int:
    """Insert or replace today's check-in of this type. Returns the row id."""
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    value = validate(ctype, value)
    now = now or now_local()
    day = day or local_date(now)
    ts = now.isoformat()
    conn.execute(
        """
        INSERT INTO checkin_events (chat_id, local_date, type, value, source, message_id,
                                    created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, local_date, type) DO UPDATE SET
            value = excluded.value, source = excluded.source,
            message_id = COALESCE(excluded.message_id, checkin_events.message_id),
            updated_at = excluded.updated_at
        """,
        (str(chat_id), day, ctype, value, source, message_id, ts, ts),
    )
    return conn.execute(
        "SELECT id FROM checkin_events WHERE chat_id=? AND local_date=? AND type=?",
        (str(chat_id), day, ctype),
    ).fetchone()[0]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def merge_into_entry(conn: sqlite3.Connection, entry_id: int, chat_id: str) -> dict:
    """Apply the day's check-ins to a freshly saved entry (G9). Returns what changed."""
    row = conn.execute(
        "SELECT date, mood_source, module, created_at FROM journal_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        return {}
    day, mood_source, module, created_at = row
    prev = conn.execute(
        "SELECT created_at FROM journal_entries WHERE date = ? AND id < ? "
        "ORDER BY id DESC LIMIT 1",
        (day, entry_id),
    ).fetchone()
    prev_at = _ts(prev[0]) if prev and prev[0] else None

    checkins = {
        t: (v, _ts(u))
        for t, v, u in conn.execute(
            "SELECT type, value, updated_at FROM checkin_events "
            "WHERE chat_id = ? AND local_date = ?",
            (str(chat_id), day),
        )
    }

    def fresh(ctype: str) -> str | None:
        hit = checkins.get(ctype)
        if not hit:
            return None
        value, updated = hit
        return value if prev_at is None or updated > prev_at else None

    changed = {}
    mood = fresh("mood")
    if mood is not None and mood_source != "manual":  # inline mood wins
        conn.execute(
            "UPDATE journal_entries SET mood_score = ?, mood_source = 'manual' WHERE id = ?",
            (int(mood), entry_id),
        )
        changed["mood_score"] = int(mood)
    mod = fresh("module")
    if mod is not None and not module:  # inline module wins
        conn.execute("UPDATE journal_entries SET module = ? WHERE id = ?", (mod, entry_id))
        changed["module"] = mod
    return changed
