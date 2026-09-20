"""TimerService: laufende Einträge starten/stoppen; "laufend" = Eintrag ohne Ende in der DB."""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from worklog import repository as repo
from worklog.db import transaction
from worklog.models import LogEntry
from worklog.services.rounding import round_up_seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class AlreadyRunningError(Exception):
    """Ein Eintrag mit identischem Projekt, Task und Beschreibung läuft bereits."""

    def __init__(self, entry: LogEntry) -> None:
        super().__init__("läuft bereits")
        self.entry = entry


def _norm(value: Optional[str]) -> str:
    """Vergleichsform für die Duplikat-Prüfung: getrimmt; leer == nicht gesetzt."""
    return (value or "").strip()


class TimerService:
    """Mehrere laufende Einträge (ADR-0001), source of truth = DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---- mehrere laufende Einträge (ADR-0001) ----

    def running_entries(self) -> list[LogEntry]:
        """Alle laufenden Einträge (ohne Ende), ältester Start zuerst."""
        return repo.list_running_logs(self.conn)

    def start_entry(
        self, *, project_id: int, task: Optional[str], description: Optional[str]
    ) -> LogEntry:
        """Startet einen neuen laufenden Eintrag; stoppt nie einen anderen.

        Wirft AlreadyRunningError, wenn ein laufender Eintrag mit identischem
        Projekt, Task und identischer Beschreibung existiert.
        """
        with transaction(self.conn):
            for running in self.running_entries():
                if (
                    running.project_id == project_id
                    and _norm(running.task) == _norm(task)
                    and _norm(running.description) == _norm(description)
                ):
                    raise AlreadyRunningError(running)
            log_id = repo.create_log(
                self.conn,
                project_id=project_id,
                task=task,
                description=description,
                started_at=_now_iso(),
                ended_at=None,
                duration_seconds=None,
                rounded_to_minutes=None,
                is_manual=False,
            )
            repo.set_last_project(self.conn, project_id)
        log = repo.get_log(self.conn, log_id)
        assert log is not None
        return log

    def stop_entry(self, log_id: int) -> Optional[LogEntry]:
        """Stoppt genau diesen laufenden Eintrag; andere laufen weiter.

        Gibt None zurück, wenn der Eintrag nicht existiert oder nicht läuft.
        """
        log = repo.get_log(self.conn, log_id)
        if log is None or log.ended_at is not None:
            return None
        with transaction(self.conn):
            self._stop_locked(log_id)
        return repo.get_log(self.conn, log_id)

    def stop_all(self) -> list[LogEntry]:
        """Stoppt alle laufenden Einträge und gibt die gestoppten zurück."""
        ids = [log.id for log in self.running_entries()]
        with transaction(self.conn):
            for log_id in ids:
                self._stop_locked(log_id)
        stopped = [repo.get_log(self.conn, log_id) for log_id in ids]
        return [log for log in stopped if log is not None]

    # ---- alte Ein-Timer-Schnittstelle (Tray, Quick-Add; Umstellung in Ticket 03) ----
    # Bezieht sich auf den zuletzt gestarteten laufenden Eintrag.

    def current(self) -> Optional[LogEntry]:
        # Höchste ID statt spätester Start: der Start ist nachträglich editierbar.
        running = self.running_entries()
        return max(running, key=lambda log: log.id) if running else None

    def is_running(self) -> bool:
        return self.current() is not None

    def start(self, *, project_id: int, task: Optional[str], description: Optional[str]) -> LogEntry:
        """Wie start_entry (stoppt nie); läuft der identische Eintrag bereits,
        wird dieser zurückgegeben statt eines Fehlers."""
        try:
            return self.start_entry(project_id=project_id, task=task, description=description)
        except AlreadyRunningError as exc:
            return exc.entry

    def stop(self) -> Optional[LogEntry]:
        current = self.current()
        if current is None:
            return None
        return self.stop_entry(current.id)

    def _stop_locked(self, log_id: int) -> None:
        log = repo.get_log(self.conn, log_id)
        if log is None or log.ended_at is not None:
            return
        ended_at = datetime.now(timezone.utc).astimezone()
        raw_seconds = max(0, math.ceil((ended_at - log.started_at).total_seconds()))
        proj = repo.get_project(self.conn, log.project_id)
        state = repo.get_app_state(self.conn)
        round_minutes = (
            proj.round_minutes if proj and proj.round_minutes is not None else state.default_round_minutes
        )
        rounded = round_up_seconds(raw_seconds, round_minutes)
        repo.update_log(
            self.conn,
            log_id,
            project_id=log.project_id,
            task=log.task,
            description=log.description,
            started_at=log.started_at.isoformat(timespec="seconds"),
            ended_at=ended_at.isoformat(timespec="seconds"),
            duration_seconds=rounded,
            rounded_to_minutes=round_minutes,
        )

    def update_running(
        self, *, project_id: int, task: Optional[str], description: Optional[str]
    ) -> Optional[LogEntry]:
        """Edit the in-flight entry without stopping it."""
        current = self.current()
        if current is None:
            return None
        repo.update_log(
            self.conn,
            current.id,
            project_id=project_id,
            task=task,
            description=description,
            started_at=current.started_at.isoformat(timespec="seconds"),
            ended_at=None,
            duration_seconds=None,
            rounded_to_minutes=None,
        )
        repo.set_last_project(self.conn, project_id)
        return repo.get_log(self.conn, current.id)

    def switch(self, *, project_id: int, task: Optional[str], description: Optional[str]) -> LogEntry:
        """Stop the most recently started entry and start a new one."""
        self.stop()
        return self.start(project_id=project_id, task=task, description=description)


def manual_log(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    task: Optional[str],
    description: Optional[str],
    started_at: datetime,
    duration_seconds: int,
    round_minutes: Optional[int],
) -> int:
    """Create a manual log; rounding applied to duration; ended_at = started_at + rounded."""
    state = repo.get_app_state(conn)
    proj = repo.get_project(conn, project_id)
    effective_round = (
        round_minutes
        if round_minutes is not None
        else (proj.round_minutes if proj and proj.round_minutes is not None else state.default_round_minutes)
    )
    rounded = round_up_seconds(duration_seconds, effective_round)
    from datetime import timedelta
    ended_at = started_at + timedelta(seconds=rounded)
    return repo.create_log(
        conn,
        project_id=project_id,
        task=task,
        description=description,
        started_at=started_at.isoformat(timespec="seconds"),
        ended_at=ended_at.isoformat(timespec="seconds"),
        duration_seconds=rounded,
        rounded_to_minutes=effective_round,
        is_manual=True,
    )
