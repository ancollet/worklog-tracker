"""All SQL lives here. UI never touches sqlite directly."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from worklog.models import AppState, Customer, Flag, LogEntry, Project, Snippet


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _row_to_customer(row: sqlite3.Row) -> Customer:
    keys = row.keys()
    return Customer(
        id=row["id"],
        name=row["name"],
        booking_system=row["booking_system"] if "booking_system" in keys else None,
        external_ref=row["external_ref"] if "external_ref" in keys else None,
        archived=bool(row["archived"]),
        created_at=_parse_dt(row["created_at"]),
        external_name=row["external_name"] if "external_name" in keys else None,
    )


def _row_to_project(row: sqlite3.Row) -> Project:
    keys = row.keys()
    return Project(
        id=row["id"],
        customer_id=row["customer_id"],
        name=row["name"],
        color=row["color"],
        round_minutes=row["round_minutes"],
        external_ref=row["external_ref"] if "external_ref" in keys else None,
        archived=bool(row["archived"]),
        created_at=_parse_dt(row["created_at"]),
        customer_name=row["customer_name"] if "customer_name" in keys else None,
        customer_booking_system=row["customer_booking_system"] if "customer_booking_system" in keys else None,
        external_name=row["external_name"] if "external_name" in keys else None,
        default_service_type=row["default_service_type"] if "default_service_type" in keys else None,
        customer_request_type=row["customer_request_type"] if "customer_request_type" in keys else None,
    )


def _row_to_log(row: sqlite3.Row) -> LogEntry:
    keys = row.keys()
    return LogEntry(
        id=row["id"],
        project_id=row["project_id"],
        task=row["task"],
        description=row["description"],
        started_at=_parse_dt(row["started_at"]),
        ended_at=_parse_dt(row["ended_at"]),
        duration_seconds=row["duration_seconds"],
        rounded_to_minutes=row["rounded_to_minutes"],
        is_manual=bool(row["is_manual"]),
        external_worklog_id=row["external_worklog_id"] if "external_worklog_id" in keys else None,
        external_worklog_url=row["external_worklog_url"] if "external_worklog_url" in keys else None,
        external_synced_at=_parse_dt(row["external_synced_at"]) if "external_synced_at" in keys else None,
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        project_name=row["project_name"] if "project_name" in keys else None,
        customer_name=row["customer_name"] if "customer_name" in keys else None,
        project_color=row["project_color"] if "project_color" in keys else None,
        customer_booking_system=row["customer_booking_system"] if "customer_booking_system" in keys else None,
    )


# ---------- Customers ----------

def list_customers(conn: sqlite3.Connection, *, include_archived: bool = False) -> list[Customer]:
    if include_archived:
        rows = conn.execute("SELECT * FROM customer ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT * FROM customer WHERE archived = 0 ORDER BY name").fetchall()
    return [_row_to_customer(r) for r in rows]


def get_customer(conn: sqlite3.Connection, customer_id: int) -> Optional[Customer]:
    row = conn.execute("SELECT * FROM customer WHERE id = ?", (customer_id,)).fetchone()
    return _row_to_customer(row) if row else None


def create_customer(
    conn: sqlite3.Connection,
    name: str,
    *,
    booking_system: Optional[str] = None,
    external_ref: Optional[str] = None,
) -> Customer:
    cur = conn.execute(
        "INSERT INTO customer(name, booking_system, external_ref, created_at) VALUES (?, ?, ?, ?)",
        (name, booking_system, external_ref, _now_iso()),
    )
    cid = cur.lastrowid
    return _row_to_customer(conn.execute("SELECT * FROM customer WHERE id = ?", (cid,)).fetchone())


def update_customer(
    conn: sqlite3.Connection,
    customer_id: int,
    *,
    name: str,
    archived: bool,
    booking_system: Optional[str] = None,
    external_ref: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE customer SET name = ?, booking_system = ?, external_ref = ?, archived = ? WHERE id = ?",
        (name, booking_system, external_ref, int(archived), customer_id),
    )


def delete_customer(conn: sqlite3.Connection, customer_id: int) -> None:
    """Hard delete. Cascades to projects; logs lose project FK reference (we don't allow this if logs exist)."""
    conn.execute("DELETE FROM customer WHERE id = ?", (customer_id,))


def set_customer_salesforce_account(
    conn: sqlite3.Connection,
    customer_id: int,
    *,
    account_id: str,
    account_name: str,
) -> None:
    """Connect the Kunde with a Salesforce-Account; sets the Buchungssystem to Salesforce.

    Raises sqlite3.IntegrityError if the Account-ID already hangs on another Kunde.
    """
    conn.execute(
        "UPDATE customer SET booking_system = 'salesforce', external_ref = ?, external_name = ? WHERE id = ?",
        (account_id, account_name or None, customer_id),
    )


# ---------- Projects ----------

PROJECT_SELECT = """
SELECT p.*, c.name AS customer_name, c.booking_system AS customer_booking_system
FROM project p
JOIN customer c ON c.id = p.customer_id
"""


def list_projects(conn: sqlite3.Connection, *, include_archived: bool = False) -> list[Project]:
    sql = PROJECT_SELECT
    if not include_archived:
        sql += " WHERE p.archived = 0 AND c.archived = 0"
    sql += " ORDER BY c.name, p.name"
    return [_row_to_project(r) for r in conn.execute(sql).fetchall()]


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[Project]:
    row = conn.execute(PROJECT_SELECT + " WHERE p.id = ?", (project_id,)).fetchone()
    return _row_to_project(row) if row else None


def create_project(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    name: str,
    color: Optional[str] = None,
    round_minutes: Optional[int] = None,
    external_ref: Optional[str] = None,
) -> Project:
    cur = conn.execute(
        "INSERT INTO project(customer_id, name, color, round_minutes, external_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (customer_id, name, color, round_minutes, external_ref, _now_iso()),
    )
    pid = cur.lastrowid
    proj = get_project(conn, pid)
    assert proj is not None
    return proj


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    name: str,
    color: Optional[str],
    round_minutes: Optional[int],
    archived: bool,
    external_ref: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE project SET name = ?, color = ?, round_minutes = ?, external_ref = ?, archived = ? WHERE id = ?",
        (name, color, round_minutes, external_ref, int(archived), project_id),
    )


def set_project_salesforce_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    salesforce_project_id: str,
    salesforce_project_name: str,
) -> None:
    """Connect the Projekt with a Salesforce-Projekt.

    Raises sqlite3.IntegrityError if the ID already hangs on another Projekt of a Salesforce-Kunde.
    """
    conn.execute(
        "UPDATE project SET external_ref = ?, external_name = ? WHERE id = ?",
        (salesforce_project_id, salesforce_project_name or None, project_id),
    )


def set_project_booking_defaults(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    default_service_type: Optional[str],
    customer_request_type: Optional[str],
) -> None:
    """Service Type and Customer Request Type that Buchungen of this Projekt start with."""
    conn.execute(
        "UPDATE project SET default_service_type = ?, customer_request_type = ? WHERE id = ?",
        (default_service_type or None, customer_request_type or None, project_id),
    )


# ---------- Log entries ----------

LOG_SELECT = """
SELECT l.*,
       p.name AS project_name, p.color AS project_color,
       c.name AS customer_name, c.booking_system AS customer_booking_system
FROM log_entry l
JOIN project p ON p.id = l.project_id
JOIN customer c ON c.id = p.customer_id
"""


def get_log(conn: sqlite3.Connection, log_id: int) -> Optional[LogEntry]:
    row = conn.execute(LOG_SELECT + " WHERE l.id = ?", (log_id,)).fetchone()
    if row is None:
        return None
    log = _row_to_log(row)
    log.flags = _load_flags_for_logs(conn, [log.id]).get(log.id, [])
    return log


def list_logs(
    conn: sqlite3.Connection,
    *,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[LogEntry]:
    where = ["1=1"]
    params: list = []
    if from_iso:
        where.append("l.started_at >= ?")
        params.append(from_iso)
    if to_iso:
        where.append("l.started_at < ?")
        params.append(to_iso)
    if project_id is not None:
        where.append("l.project_id = ?")
        params.append(project_id)
    sql = LOG_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY l.started_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    logs = [_row_to_log(r) for r in conn.execute(sql, params).fetchall()]
    if logs:
        flag_map = _load_flags_for_logs(conn, [l.id for l in logs])
        for l in logs:
            l.flags = flag_map.get(l.id, [])
    return logs


def list_running_logs(conn: sqlite3.Connection) -> list[LogEntry]:
    """Laufende Einträge (ohne Ende), ältester Start zuerst."""
    rows = conn.execute(
        LOG_SELECT + " WHERE l.ended_at IS NULL ORDER BY l.started_at, l.id"
    ).fetchall()
    logs = [_row_to_log(r) for r in rows]
    if logs:
        flag_map = _load_flags_for_logs(conn, [l.id for l in logs])
        for l in logs:
            l.flags = flag_map.get(l.id, [])
    return logs


def create_log(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    task: Optional[str],
    description: Optional[str],
    started_at: str,
    ended_at: Optional[str],
    duration_seconds: Optional[int],
    rounded_to_minutes: Optional[int],
    is_manual: bool,
) -> int:
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO log_entry(project_id, task, description, started_at, ended_at,
                              duration_seconds, rounded_to_minutes, is_manual, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, task, description, started_at, ended_at,
         duration_seconds, rounded_to_minutes, int(is_manual), now, now),
    )
    return cur.lastrowid


def update_log(
    conn: sqlite3.Connection,
    log_id: int,
    *,
    project_id: int,
    task: Optional[str],
    description: Optional[str],
    started_at: str,
    ended_at: Optional[str],
    duration_seconds: Optional[int],
    rounded_to_minutes: Optional[int],
) -> None:
    conn.execute(
        """
        UPDATE log_entry
        SET project_id = ?, task = ?, description = ?, started_at = ?, ended_at = ?,
            duration_seconds = ?, rounded_to_minutes = ?, updated_at = ?
        WHERE id = ?
        """,
        (project_id, task, description, started_at, ended_at,
         duration_seconds, rounded_to_minutes, _now_iso(), log_id),
    )


def delete_log(conn: sqlite3.Connection, log_id: int) -> None:
    conn.execute("DELETE FROM log_entry WHERE id = ?", (log_id,))


def set_log_external_ref(
    conn: sqlite3.Connection,
    log_id: int,
    *,
    worklog_id: Optional[str],
    worklog_url: Optional[str] = None,
    synced_at_iso: Optional[str] = None,
) -> None:
    """Persist the external system's worklog-id (idempotency) after a successful sync.

    Pass worklog_id=None to clear the reference (e.g. after the user undid the booking).
    """
    conn.execute(
        """
        UPDATE log_entry
        SET external_worklog_id = ?, external_worklog_url = ?, external_synced_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (worklog_id, worklog_url, synced_at_iso, _now_iso(), log_id),
    )


# ---------- App state ----------

def get_app_state(conn: sqlite3.Connection) -> AppState:
    row = conn.execute("SELECT * FROM app_state WHERE id = 1").fetchone()
    return AppState(
        running_log_id=row["running_log_id"],
        last_project_id=row["last_project_id"],
        default_round_minutes=row["default_round_minutes"],
    )


def set_running_log(conn: sqlite3.Connection, log_id: Optional[int]) -> None:
    conn.execute("UPDATE app_state SET running_log_id = ? WHERE id = 1", (log_id,))


def set_last_project(conn: sqlite3.Connection, project_id: Optional[int]) -> None:
    conn.execute("UPDATE app_state SET last_project_id = ? WHERE id = 1", (project_id,))


def set_default_round_minutes(conn: sqlite3.Connection, minutes: int) -> None:
    conn.execute("UPDATE app_state SET default_round_minutes = ? WHERE id = 1", (minutes,))


# ---------- Suggestions for autocomplete ----------

def task_suggestions(
    conn: sqlite3.Connection, *, project_id: Optional[int] = None, limit: int = 100
) -> list[str]:
    if project_id is not None:
        rows = conn.execute(
            """
            SELECT task, MAX(started_at) AS last
            FROM log_entry
            WHERE task IS NOT NULL AND task != '' AND project_id = ?
            GROUP BY task
            ORDER BY last DESC LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT task, MAX(started_at) AS last
            FROM log_entry
            WHERE task IS NOT NULL AND task != ''
            GROUP BY task
            ORDER BY last DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [r["task"] for r in rows]


def description_suggestions(
    conn: sqlite3.Connection,
    *,
    project_id: Optional[int] = None,
    task: Optional[str] = None,
    limit: int = 100,
) -> list[str]:
    where = ["description IS NOT NULL", "description != ''"]
    params: list = []
    if project_id is not None:
        where.append("project_id = ?")
        params.append(project_id)
    if task:
        where.append("task = ?")
        params.append(task)
    params.append(limit)
    sql = (
        "SELECT description, MAX(started_at) AS last FROM log_entry WHERE "
        + " AND ".join(where)
        + " GROUP BY description ORDER BY last DESC LIMIT ?"
    )
    return [r["description"] for r in conn.execute(sql, params).fetchall()]


def recent_unique_tasks(
    conn: sqlite3.Connection, *, days: int = 7, limit: int = 5
) -> list[tuple[str, int, str]]:
    """Return list of (task, project_id, project_display_name) for recent restart-menu."""
    rows = conn.execute(
        """
        SELECT l.task, l.project_id,
               c.name || ' · ' || p.name AS proj_name,
               MAX(l.started_at) AS last
        FROM log_entry l
        JOIN project p ON p.id = l.project_id
        JOIN customer c ON c.id = p.customer_id
        WHERE l.task IS NOT NULL AND l.task != ''
          AND l.started_at >= datetime('now', ?)
        GROUP BY l.task, l.project_id
        ORDER BY last DESC LIMIT ?
        """,
        (f"-{int(days)} days", limit),
    ).fetchall()
    return [(r["task"], r["project_id"], r["proj_name"]) for r in rows]


def last_log(conn: sqlite3.Connection) -> Optional[LogEntry]:
    row = conn.execute(
        LOG_SELECT + " WHERE l.ended_at IS NOT NULL ORDER BY l.ended_at DESC LIMIT 1"
    ).fetchone()
    return _row_to_log(row) if row else None


# ---------- Aggregations for the timer-tab summary ----------

def sum_duration(conn: sqlite3.Connection, *, from_iso: str, to_iso: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_seconds), 0) AS total
        FROM log_entry
        WHERE started_at >= ? AND started_at < ?
          AND duration_seconds IS NOT NULL
        """,
        (from_iso, to_iso),
    ).fetchone()
    return int(row["total"] or 0)


# ---------- Flags ----------

def _row_to_flag(row: sqlite3.Row) -> Flag:
    return Flag(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        sort_order=row["sort_order"],
        created_at=_parse_dt(row["created_at"]),
    )


def list_flags(conn: sqlite3.Connection) -> list[Flag]:
    rows = conn.execute("SELECT * FROM flag ORDER BY sort_order, name").fetchall()
    return [_row_to_flag(r) for r in rows]


def create_flag(conn: sqlite3.Connection, *, name: str, color: Optional[str] = None,
                sort_order: int = 0) -> Flag:
    cur = conn.execute(
        "INSERT INTO flag(name, color, sort_order, created_at) VALUES (?, ?, ?, ?)",
        (name, color, sort_order, _now_iso()),
    )
    fid = cur.lastrowid
    return _row_to_flag(conn.execute("SELECT * FROM flag WHERE id = ?", (fid,)).fetchone())


def update_flag(conn: sqlite3.Connection, flag_id: int, *, name: str,
                color: Optional[str], sort_order: int) -> None:
    conn.execute(
        "UPDATE flag SET name = ?, color = ?, sort_order = ? WHERE id = ?",
        (name, color, sort_order, flag_id),
    )


def delete_flag(conn: sqlite3.Connection, flag_id: int) -> None:
    conn.execute("DELETE FROM flag WHERE id = ?", (flag_id,))


def _load_flags_for_logs(conn: sqlite3.Connection, log_ids: list[int]) -> dict[int, list[Flag]]:
    if not log_ids:
        return {}
    placeholders = ",".join("?" * len(log_ids))
    rows = conn.execute(
        f"""
        SELECT lf.log_id, f.id, f.name, f.color, f.sort_order, f.created_at
        FROM log_entry_flag lf
        JOIN flag f ON f.id = lf.flag_id
        WHERE lf.log_id IN ({placeholders})
        ORDER BY f.sort_order, f.name
        """,
        log_ids,
    ).fetchall()
    out: dict[int, list[Flag]] = {}
    for r in rows:
        out.setdefault(r["log_id"], []).append(_row_to_flag(r))
    return out


def get_log_flag_ids(conn: sqlite3.Connection, log_id: int) -> set[int]:
    rows = conn.execute("SELECT flag_id FROM log_entry_flag WHERE log_id = ?", (log_id,)).fetchall()
    return {r["flag_id"] for r in rows}


def set_log_flag(conn: sqlite3.Connection, log_id: int, flag_id: int, enabled: bool) -> None:
    if enabled:
        conn.execute(
            "INSERT OR IGNORE INTO log_entry_flag(log_id, flag_id) VALUES (?, ?)",
            (log_id, flag_id),
        )
    else:
        conn.execute(
            "DELETE FROM log_entry_flag WHERE log_id = ? AND flag_id = ?",
            (log_id, flag_id),
        )


def toggle_log_flag(conn: sqlite3.Connection, log_id: int, flag_id: int) -> bool:
    """Toggle a flag on/off. Returns the new state."""
    row = conn.execute(
        "SELECT 1 FROM log_entry_flag WHERE log_id = ? AND flag_id = ?",
        (log_id, flag_id),
    ).fetchone()
    if row:
        conn.execute(
            "DELETE FROM log_entry_flag WHERE log_id = ? AND flag_id = ?",
            (log_id, flag_id),
        )
        return False
    conn.execute(
        "INSERT INTO log_entry_flag(log_id, flag_id) VALUES (?, ?)",
        (log_id, flag_id),
    )
    return True


def set_log_flag_bulk(
    conn: sqlite3.Connection, log_ids: list[int], flag_id: int, enabled: bool
) -> None:
    """Apply or remove a single flag for many logs in one transaction."""
    if not log_ids:
        return
    if enabled:
        conn.executemany(
            "INSERT OR IGNORE INTO log_entry_flag(log_id, flag_id) VALUES (?, ?)",
            [(lid, flag_id) for lid in log_ids],
        )
    else:
        placeholders = ",".join("?" * len(log_ids))
        conn.execute(
            f"DELETE FROM log_entry_flag WHERE log_id IN ({placeholders}) AND flag_id = ?",
            (*log_ids, flag_id),
        )


def count_logs_with_flag(
    conn: sqlite3.Connection, log_ids: list[int]
) -> dict[int, int]:
    """Return {flag_id: how_many_of_log_ids_have_it}."""
    if not log_ids:
        return {}
    placeholders = ",".join("?" * len(log_ids))
    rows = conn.execute(
        f"""
        SELECT flag_id, COUNT(*) AS cnt
        FROM log_entry_flag
        WHERE log_id IN ({placeholders})
        GROUP BY flag_id
        """,
        log_ids,
    ).fetchall()
    return {r["flag_id"]: int(r["cnt"]) for r in rows}


def delete_logs_bulk(conn: sqlite3.Connection, log_ids: list[int]) -> None:
    if not log_ids:
        return
    placeholders = ",".join("?" * len(log_ids))
    conn.execute(f"DELETE FROM log_entry WHERE id IN ({placeholders})", log_ids)


# ---------- Generic key/value settings ----------

def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Optional[str]) -> None:
    if value is None or value == "":
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ---------- Snippets ----------

def _row_to_snippet(row: sqlite3.Row) -> Snippet:
    return Snippet(
        id=row["id"],
        text=row["text"],
        sort_order=row["sort_order"],
        created_at=_parse_dt(row["created_at"]),
    )


class SnippetTextError(ValueError):
    """Snippet text is empty or already exists (case-insensitive)."""


def _checked_snippet_text(
    conn: sqlite3.Connection, text: str, *, ignore_id: Optional[int] = None
) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise SnippetTextError("Snippet-Text darf nicht leer sein.")
    for other in list_snippets(conn):
        if other.id != ignore_id and other.text.casefold() == cleaned.casefold():
            raise SnippetTextError("Snippet mit diesem Text existiert bereits.")
    return cleaned


def list_snippets(conn: sqlite3.Connection) -> list[Snippet]:
    rows = conn.execute("SELECT * FROM snippet ORDER BY sort_order, id").fetchall()
    return [_row_to_snippet(r) for r in rows]


def create_snippet(conn: sqlite3.Connection, *, text: str) -> Snippet:
    """Create a snippet at the end of the list."""
    cleaned = _checked_snippet_text(conn, text)
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM snippet"
    ).fetchone()["next_order"]
    cur = conn.execute(
        "INSERT INTO snippet(text, sort_order, created_at) VALUES (?, ?, ?)",
        (cleaned, next_order, _now_iso()),
    )
    sid = cur.lastrowid
    return _row_to_snippet(conn.execute("SELECT * FROM snippet WHERE id = ?", (sid,)).fetchone())


def rename_snippet(conn: sqlite3.Connection, snippet_id: int, *, text: str) -> None:
    """Change the text. Existing descriptions are untouched: snippets are plain text."""
    cleaned = _checked_snippet_text(conn, text, ignore_id=snippet_id)
    conn.execute("UPDATE snippet SET text = ? WHERE id = ?", (cleaned, snippet_id))


def reorder_snippets(conn: sqlite3.Connection, snippet_ids: list[int]) -> None:
    """Persist the given order (first id first)."""
    conn.executemany(
        "UPDATE snippet SET sort_order = ? WHERE id = ?",
        [(order, sid) for order, sid in enumerate(snippet_ids)],
    )


def delete_snippet(conn: sqlite3.Connection, snippet_id: int) -> None:
    conn.execute("DELETE FROM snippet WHERE id = ?", (snippet_id,))
