#!/usr/bin/env python3
"""FEAT-07 Phase 4: morning/evening prompt bookkeeping (`prompt_events`, D48).

A prompt is *open* while it is the newest prompt for the chat and has been neither
answered nor skipped. Before `window_ends_at` anything typed is the entry; after it
(until the next prompt) a message is held for confirmation (D45). Times use the
travel-mode zone (D19). Import-safe.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, time as time_cls, timedelta

import checkins

SESSIONS = ("morning", "evening")
MORNING_WINDOW_END = time_cls(11, 0)   # D45
EVENING_WINDOW_END = time_cls(3, 0)    # next calendar day
OPEN_MAX = timedelta(hours=24)         # safety cap if a later prompt never goes out
COLS = ("id", "chat_id", "local_date", "session", "message_id", "sent_at", "window_ends_at",
        "skipped_at", "entry_id", "answered_at")


def window_end(session: str, sent: datetime) -> datetime:
    sent = sent.astimezone(checkins.TZ)
    if session == "morning":
        end = sent.replace(hour=MORNING_WINDOW_END.hour, minute=0, second=0, microsecond=0)
        return end if end > sent else sent + timedelta(hours=1)  # a prompt sent late still gets an hour
    end = (sent + timedelta(days=1)).replace(hour=EVENING_WINDOW_END.hour, minute=0, second=0,
                                             microsecond=0)
    return end


def record(conn: sqlite3.Connection, *, chat_id: str, session: str, message_id: str | None,
           now: datetime | None = None) -> int:
    now = now or checkins.now_local()
    cur = conn.execute(
        "INSERT INTO prompt_events (chat_id, local_date, session, message_id, sent_at, "
        "window_ends_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(chat_id), checkins.local_date(now), session, message_id, now.isoformat(),
         window_end(session, now).isoformat()))
    return cur.lastrowid


def _row(r) -> dict | None:
    return dict(zip(COLS, r)) if r else None


def get(conn, prompt_id: int) -> dict | None:
    return _row(conn.execute(f"SELECT {', '.join(COLS)} FROM prompt_events WHERE id = ?",
                             (prompt_id,)).fetchone())


def latest(conn, chat_id: str) -> dict | None:
    return _row(conn.execute(
        f"SELECT {', '.join(COLS)} FROM prompt_events WHERE chat_id = ? "
        "ORDER BY sent_at DESC, id DESC LIMIT 1", (str(chat_id),)).fetchone())


def open_prompt(conn, chat_id: str, now: datetime | None = None) -> dict | None:
    """The newest prompt if it is still awaiting an entry (not answered, not skipped)."""
    p = latest(conn, chat_id)
    if not p or p["entry_id"] or p["skipped_at"]:
        return None
    if (now or checkins.now_local()) - datetime.fromisoformat(p["sent_at"]) > OPEN_MAX:
        return None
    return p


def in_window(p: dict, now: datetime | None = None) -> bool:
    return (now or checkins.now_local()) < datetime.fromisoformat(p["window_ends_at"])


def by_message(conn, chat_id: str, message_id) -> dict | None:
    if message_id in (None, ""):
        return None
    return _row(conn.execute(
        f"SELECT {', '.join(COLS)} FROM prompt_events WHERE chat_id = ? AND message_id = ? "
        "ORDER BY id DESC LIMIT 1", (str(chat_id), str(message_id))).fetchone())


def skip(conn, prompt_id: int, now: datetime | None = None) -> None:
    conn.execute("UPDATE prompt_events SET skipped_at = ? WHERE id = ? AND entry_id IS NULL",
                 ((now or checkins.now_local()).isoformat(), prompt_id))


def unskip(conn, prompt_id: int) -> None:
    conn.execute("UPDATE prompt_events SET skipped_at = NULL WHERE id = ?", (prompt_id,))


def current_session(conn, chat_id: str, now: datetime | None = None) -> str:
    """D49: morning if no morning entry yet today and no evening prompt has gone out."""
    now = now or checkins.now_local()
    day = checkins.local_date(now)
    has_morning = conn.execute(
        "SELECT 1 FROM journal_entries WHERE date = ? AND session = 'morning' LIMIT 1",
        (day,)).fetchone()
    evening_sent = conn.execute(
        "SELECT 1 FROM prompt_events WHERE chat_id = ? AND local_date = ? AND session = 'evening'",
        (str(chat_id), day)).fetchone()
    return "morning" if not has_morning and not evening_sent else "evening"


def link_entry(conn, entry_id: int, chat_id: str) -> int | None:
    """Mark the matching prompt answered when an entry is saved (called from save_entry via
    checkins.merge_into_entry). Matches the entry's day + session, newest unanswered first."""
    row = conn.execute("SELECT date, session, created_at FROM journal_entries WHERE id = ?",
                       (entry_id,)).fetchone()
    if not row:
        return None
    day, session, created_at = row
    p = conn.execute(
        "SELECT id FROM prompt_events WHERE chat_id = ? AND local_date = ? AND session = ? "
        "AND entry_id IS NULL ORDER BY id DESC LIMIT 1", (str(chat_id), day, session)).fetchone()
    if not p:
        return None
    conn.execute("UPDATE prompt_events SET entry_id = ?, answered_at = ?, skipped_at = NULL "
                 "WHERE id = ?", (entry_id, created_at, p[0]))
    return p[0]
