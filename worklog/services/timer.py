"""TimerService: start/stop a single live timer, persisted in DB."""
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


class TimerService:
    """Single-running-timer logic, source of truth = DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def current(self) -> Optional[LogEntry]:
        state = repo.get_app_state(self.conn)
        if state.running_log_id is None:
            return None
        return repo.get_log(self.conn, state.running_log_id)

    def is_running(self) -> bool:
        return self.current() is not None

    def start(self, *, project_id: int, task: Optional[str], description: Optional[str]) -> LogEntry:
        with transaction(self.conn):
            state = repo.get_app_state(self.conn)
            if state.running_log_id is not None:
                # stop existing first to avoid two running entries
                self._stop_locked(state.running_log_id)
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
            repo.set_running_log(self.conn, log_id)
            repo.set_last_project(self.conn, project_id)
        log = repo.get_log(self.conn, log_id)
        assert log is not None
        return log

    def stop(self) -> Optional[LogEntry]:
        state = repo.get_app_state(self.conn)
        if state.running_log_id is None:
            return None
        log_id = state.running_log_id
        with transaction(self.conn):
            self._stop_locked(log_id)
        return repo.get_log(self.conn, log_id)

    def _stop_locked(self, log_id: int) -> None:
        log = repo.get_log(self.conn, log_id)
        if log is None:
            repo.set_running_log(self.conn, None)
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
        repo.set_running_log(self.conn, None)

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
        """Atomically stop current and start a new entry."""
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
