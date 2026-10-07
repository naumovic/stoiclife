#!/usr/bin/env python3
"""FEAT-07: minimal numbered-migration runner for the shared Stoic journal DB.

Applies `migrations/NNN_*.sql` in order, recording each in `schema_migrations`.
Coexists with db_init.py (which stays as-is). Each migration must itself be
idempotent, so a lost `schema_migrations` row only means a harmless re-run.

Before applying anything new it backs the DB up as
`stoic_journal.db.bak-mig<NNN>-<YYYYMMDD-HHMMSS>` (the existing pattern).

    python3 migrate.py            # apply pending
    python3 migrate.py --status   # list applied / pending
    python3 migrate.py --db /tmp/x.db --no-backup   # tests
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = REPO_DIR / "migrations"
DEFAULT_DB = Path.home() / ".openclaw" / "stoic" / "stoic_journal.db"


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def applied(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def backup(db: Path, version: str) -> Path:
    # sqlite3's online backup API: consistent even if another writer is mid-transaction.
    dest = db.with_name(f"{db.name}.bak-mig{version}-{datetime.now():%Y%m%d-%H%M%S}")
    src = sqlite3.connect(db)
    try:
        with sqlite3.connect(dest) as out:
            src.backup(out)
    finally:
        src.close()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    done = applied(conn)
    pending = [p for p in migration_files() if p.name[:3] not in done]

    if args.status:
        for p in migration_files():
            print(f"{'applied' if p.name[:3] in done else 'PENDING'}  {p.name}")
        return 0
    if not pending:
        print("no pending migrations")
        return 0

    conn.close()
    if not args.no_backup:
        print(f"backup: {backup(args.db, pending[0].name[:3])}")
    conn = sqlite3.connect(args.db)
    for p in pending:
        version = p.name[:3]
        with conn:  # one transaction per migration
            conn.executescript(p.read_text())
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now().astimezone().isoformat()),
            )
        print(f"applied {p.name}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
