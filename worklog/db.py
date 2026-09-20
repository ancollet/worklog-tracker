"""SQLite schema, connection helpers, migrations."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from worklog.paths import db_path

SCHEMA_VERSION = 7  # 6 = Snippets, 7 = Salesforce-Account registrieren

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS customer (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    booking_system  TEXT,
    external_ref    TEXT,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    color           TEXT,
    round_minutes   INTEGER,
    external_ref    TEXT,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE(customer_id, name)
);

CREATE TABLE IF NOT EXISTS log_entry (
    id                    INTEGER PRIMARY KEY,
    project_id            INTEGER NOT NULL REFERENCES project(id),
    task                  TEXT,
    description           TEXT,
    started_at            TEXT NOT NULL,
    ended_at              TEXT,
    duration_seconds      INTEGER,
    rounded_to_minutes    INTEGER,
    is_manual             INTEGER NOT NULL DEFAULT 0,
    external_worklog_id   TEXT,
    external_worklog_url  TEXT,
    external_synced_at    TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
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

# Not part of INITIAL_SCHEMA: the start snippets are seeded exactly once, when
# this table is created (fresh DB or migration to v6). A user who deletes them
# must not get them back on the next start.
SNIPPET_SCHEMA = """
CREATE TABLE snippet (
    id          INTEGER PRIMARY KEY,
    text        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""

START_SNIPPETS = ("Codereview", "Entwicklung", "Istanalyse", "Recherche")

_LEGACY_DEFAULT_FLAG_NAMES = ("gebucht", "invoiced", "canceled")

BOOKING_SYSTEMS = ("jira", "salesforce")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _create_snippet_table(conn: sqlite3.Connection) -> None:
    if _has_table(conn, "snippet"):
        return
    conn.executescript(SNIPPET_SCHEMA)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO snippet(text, sort_order, created_at) VALUES (?, ?, ?)",
        [(text, order, now) for order, text in enumerate(START_SNIPPETS)],
    )


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
        _create_snippet_table(conn)
        _migrate_to_7_salesforce_account(conn)
    elif current < SCHEMA_VERSION:
        if current < 3:
            # v2 introduced auto-seeded flags; v3 removes them again. Drop the
            # legacy defaults only if they exist *and* are unused (no log
            # assignments and unmodified colors not relevant — name match is enough).
            placeholders = ",".join("?" * len(_LEGACY_DEFAULT_FLAG_NAMES))
            conn.execute(
                f"""
                DELETE FROM flag
                WHERE name IN ({placeholders})
                  AND id NOT IN (SELECT DISTINCT flag_id FROM log_entry_flag)
                """,
                _LEGACY_DEFAULT_FLAG_NAMES,
            )
        if current < 4:
            if not _has_column(conn, "customer", "booking_system"):
                conn.execute("ALTER TABLE customer ADD COLUMN booking_system TEXT")
            if not _has_column(conn, "customer", "external_ref"):
                conn.execute("ALTER TABLE customer ADD COLUMN external_ref TEXT")
            if not _has_column(conn, "project", "external_ref"):
                conn.execute("ALTER TABLE project ADD COLUMN external_ref TEXT")
        if current < 5:
            for col in ("external_worklog_id", "external_worklog_url", "external_synced_at"):
                if not _has_column(conn, "log_entry", col):
                    conn.execute(f"ALTER TABLE log_entry ADD COLUMN {col} TEXT")
        if current < 6:
            _create_snippet_table(conn)
        if current < 7:
            _migrate_to_7_salesforce_account(conn)
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------- Schritt "→ 7": Salesforce-Account registrieren ----------

def _migrate_to_7_salesforce_account(conn: sqlite3.Connection) -> None:
    """Eine Account-ID darf nur an einem Kunden hängen (leere Werte ausgenommen).

    Idempotent and independent of every other step; runs for fresh databases too,
    because the index cannot live in INITIAL_SCHEMA (older databases get the
    columns it needs only during migration). Only Salesforce-Kunden are covered:
    for Jira-Kunden the external reference is a project key, not an Account-ID.

    Hand-typed duplicates from before: the oldest Kunde keeps the Account, the
    others stay (with Projekte and Einträge) but lose the Account-ID and can be
    connected again in the Kunden-Tab.

    `external_name` holds the name of the connected Account, so the UI can show
    it instead of the ID even after the Kunde was renamed.
    """
    if not _has_column(conn, "customer", "external_name"):
        conn.execute("ALTER TABLE customer ADD COLUMN external_name TEXT")
    conn.execute(
        """
        UPDATE customer SET external_ref = NULL
        WHERE booking_system = 'salesforce' AND external_ref IS NOT NULL AND external_ref <> ''
          AND EXISTS (
              SELECT 1 FROM customer older
              WHERE older.booking_system = 'salesforce'
                AND older.external_ref = customer.external_ref
                AND older.id < customer.id
          )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_salesforce_account
        ON customer(external_ref)
        WHERE booking_system = 'salesforce' AND external_ref IS NOT NULL AND external_ref <> ''
        """
    )
