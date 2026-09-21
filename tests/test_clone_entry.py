"""Klonen: aus einem beendeten Eintrag eine ungebuchte Kopie mit derselben Zeit erzeugen."""
from datetime import datetime, timezone

import pytest

from worklog import repository as repo
from worklog.services.timer import SourceEntryRunningError, TimerService, clone_entry, manual_log


def _project(conn, name="Web"):
    c = repo.create_customer(conn, f"Acme {name}")
    return repo.create_project(conn, customer_id=c.id, name=name)


def _finished_entry(conn, project_id):
    return manual_log(
        conn,
        project_id=project_id,
        task="ACME-1",
        description="Doku",
        started_at=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        duration_seconds=30 * 60,
        round_minutes=None,
    )


def test_clone_copies_project_task_description_and_time(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    source = repo.get_log(conn, source_id)
    clone = repo.get_log(conn, clone_entry(conn, source_id))
    assert clone.id != source_id
    assert (clone.project_id, clone.task, clone.description) == (p.id, "ACME-1", "Doku")
    assert (clone.started_at, clone.ended_at) == (source.started_at, source.ended_at)
    assert clone.duration_seconds == source.duration_seconds
    assert clone.rounded_to_minutes == source.rounded_to_minutes


def test_clone_leaves_source_unchanged(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    before = repo.get_log(conn, source_id)
    clone_entry(conn, source_id)
    assert repo.get_log(conn, source_id) == before


def test_clone_takes_neither_flags_nor_booking(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    flag = repo.create_flag(conn, name="abgerechnet", color="#10B981")
    repo.set_log_flag(conn, source_id, flag.id, True)
    repo.set_log_external_ref(conn, source_id, worklog_id="10001", worklog_url="https://x/10001")
    clone = repo.get_log(conn, clone_entry(conn, source_id))
    assert clone.flags == []
    assert clone.is_booked is False


def test_clone_refuses_running_entry(conn):
    p = _project(conn)
    running = TimerService(conn).start_entry(project_id=p.id, task=None, description=None)
    with pytest.raises(SourceEntryRunningError):
        clone_entry(conn, running.id)


def test_clone_of_missing_entry_raises_lookup_error(conn):
    with pytest.raises(LookupError):
        clone_entry(conn, 999)
