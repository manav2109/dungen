"""Storage backend selection.

SQLite is the default and only backend this deploy (`webapp/deploy/`)
actually uses — a single file on local disk, durable, exactly one
process. Postgres is also supported, triggered by setting `DATABASE_URL`:
kept as an optional escape hatch (see `webapp/deploy/backend.Dockerfile`'s
own comment — it installs psycopg2's runtime dependency "in case
DATABASE_URL is ever set") rather than because anything here currently
points at one.

Picked automatically from environment; nothing else in the app needs to
branch on which one is active. Callers write SQL with `?` placeholders
(sqlite3's style) — translated to `%s` automatically when running against
Postgres — and get a context manager that commits/rolls back/closes on
`with db.connect() as conn:` either way.

`INSTANCE_CONNECTION_NAME` (Cloud SQL's Unix-socket connection method) is
also still wired up below, but it's GCP-specific and nothing in this repo
targets GCP anymore — this branch is effectively dead code now, kept only
because removing it is a real decision, not a comment fix.
"""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path

INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME")
DATABASE_URL = os.environ.get("DATABASE_URL")

BACKEND = "postgres" if (INSTANCE_CONNECTION_NAME or DATABASE_URL) else "sqlite"

SQLITE_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "projects.db"


def _pg_connect():
    import psycopg2

    if INSTANCE_CONNECTION_NAME:
        return psycopg2.connect(
            host=f"/cloudsql/{INSTANCE_CONNECTION_NAME}",
            dbname=os.environ.get("DB_NAME", "diagen"),
            user=os.environ.get("DB_USER", "diagen"),
            password=os.environ["DB_PASS"],
        )
    return psycopg2.connect(DATABASE_URL)


class _PgConnWrapper:
    """Enough of sqlite3.Connection's surface for this app: `?` -> `%s`
    translation, and `with connect() as conn:` that commits-or-rolls-back
    AND closes (sqlite3's own __exit__ only handles the transaction, not
    closing — we want the closing behavior on Postgres, since a Cloud Run
    instance living for hours would otherwise leak one TCP connection per
    call)."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return _PgCursorWrapper(cur)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        self._raw.close()
        return False


class _PgCursorWrapper:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


def connect():
    """`with db.connect() as conn:` — same shape on both backends."""
    if BACKEND == "sqlite":
        SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(SQLITE_DB_PATH)
    return _PgConnWrapper(_pg_connect())


def add_column_if_missing(conn, table: str, column: str, coltype: str):
    """`ALTER TABLE ... ADD COLUMN` — Postgres supports `IF NOT EXISTS`
    natively; SQLite (pre-3.35, and simplest to just always do this way)
    doesn't, so swallow the "duplicate column" error instead."""
    if BACKEND == "postgres":
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}")
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    except sqlite3.OperationalError:
        pass  # column already exists


def is_integrity_error(exc: BaseException) -> bool:
    """True for a UNIQUE-constraint violation on either backend, without
    importing psycopg2 in modules that don't otherwise need it."""
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if BACKEND == "postgres":
        import psycopg2

        return isinstance(exc, psycopg2.IntegrityError)
    return False
