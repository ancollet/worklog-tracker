"""Verschieben: put entries on another day; time of day and duration stay."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from worklog import repository as repo
from worklog.models import LogEntry


class MoveRejectedError(Exception):
    """The selection contains an entry that must not be moved; nothing was moved."""

    def __init__(self, entry: LogEntry, reason: str) -> None:
        super().__init__(reason)
        self.entry = entry
        self.reason = reason


class EntryRunningError(MoveRejectedError):
    """A laufender Eintrag has no end yet and stays on its day."""

    def __init__(self, entry: LogEntry) -> None:
        super().__init__(entry, "Ein laufender Eintrag kann nicht verschoben werden.")


def _check_movable(conn: sqlite3.Connection, logs: list[LogEntry]) -> None:
    """The one place for reasons that block moving entries."""
    for log in logs:
        if log.ended_at is None:
            raise EntryRunningError(log)
    # Sperr-Regel: raises `repo.EntryBookedError` when an entry is gebucht.
    repo.ensure_not_booked(conn, [int(log.id) for log in logs])


def _shift_days(moment: datetime, days: int) -> datetime:
    """Same wall-clock time `days` later, with the local UTC offset of that day.

    The date is replaced instead of adding multiples of 24 h, so the time of day
    survives a daylight-saving switch. (A wall-clock time that does not exist on
    the new day, inside the spring-forward gap, lands one hour later.)
    """
    wall = moment.replace(tzinfo=None) + timedelta(days=days)
    return wall.astimezone()


def move_entries_to_date(conn: sqlite3.Connection, log_ids: list[int], target: date) -> None:
    """Put every entry on `target` (the day of its start), keeping its time of day.

    Atomic: raises a `MoveRejectedError` (or `repo.EntryBookedError` for gebuchte
    Einträge) before anything is written when one of the entries must not be
    moved. Overlaps on the target day are not checked.
    """
    logs = [log for log in (repo.get_log(conn, i) for i in log_ids) if log is not None]
    _check_movable(conn, logs)
    moves = [(log, (target - log.started_at.date()).days) for log in logs]
    moves = [(log, days) for log, days in moves if days != 0]
    if not moves:
        return
    conn.execute("BEGIN")
    try:
        for log, days in moves:
            repo.update_log(
                conn, int(log.id),
                project_id=log.project_id, task=log.task, description=log.description,
                started_at=_shift_days(log.started_at, days).isoformat(timespec="seconds"),
                ended_at=_shift_days(log.ended_at, days).isoformat(timespec="seconds"),
                duration_seconds=log.duration_seconds,
                rounded_to_minutes=log.rounded_to_minutes,
            )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
