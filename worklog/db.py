"""SQLite schema, connection helpers, migrations."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from worklog.paths import db_path

SCHEMA_VERSION = 2

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS customer (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    color           TEXT,
    round_minutes   INTEGER,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE(customer_id, name)
);

CREATE TABLE IF NOT EXISTS log_entry (
    id                  INTEGER PRIMARY KEY,
    project_id          INTEGER NOT NULL REFERENCES project(id),
    task                TEXT,
    description         TEXT,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    duration_seconds    INTEGER,
    rounded_to_minutes  INTEGER,
    is_manual           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_log_entry_project ON log_entry(project_id);
CREATE INDEX IF NOT EXISTS idx_log_entry_started ON log_entry(started_at);
CREATE INDEX IF NOT EXISTS idx_log_entry_task    ON log_entry(task);

CREATE TABLE IF NOT EXISTS app_state (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    running_log_id           INTEGER REFERENCES log_entry(id),
    last_project_id          INTEGER REFERENCES project(id),
    default_round_minutes    INTEGER NOT NULL DEFAULT 15
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flag (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS log_entry_flag (
    log_id   INTEGER NOT NULL REFERENCES log_entry(id) ON DELETE CASCADE,
    flag_id  INTEGER NOT NULL REFERENCES flag(id) ON DELETE CASCADE,
    PRIMARY KEY (log_id, flag_id)
);

CREATE INDEX IF NOT EXISTS idx_log_entry_flag_log ON log_entry_flag(log_id);
"""

DEFAULT_FLAGS = [
    ("gebucht", "#10B981", 10),
    ("invoiced", "#3B82F6", 20),
    ("canceled", "#EF4444", 30),
]


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with sane defaults and run migrations."""
    target = str(path) if path is not None else str(db_path())
    conn = sqlite3.connect(target, detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(INITIAL_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    current = row["version"] if row else 0
    if current == 0:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        conn.execute(
            "INSERT OR IGNORE INTO app_state(id, running_log_id, last_project_id, default_round_minutes) "
            "VALUES (1, NULL, NULL, 15)"
        )
        _seed_default_flags(conn)
    elif current < SCHEMA_VERSION:
        # v1 → v2: flag tables already created via INITIAL_SCHEMA above; only seed
        _seed_default_flags(conn)
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _seed_default_flags(conn: sqlite3.Connection) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for name, color, sort_order in DEFAULT_FLAGS:
        conn.execute(
            "INSERT OR IGNORE INTO flag(name, color, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (name, color, sort_order, now),
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
