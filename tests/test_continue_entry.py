"""Fortsetzen: aus einem bestehenden Eintrag einen neuen laufenden Eintrag erzeugen."""
from datetime import datetime, timezone

import pytest

from worklog import repository as repo
from worklog.services.timer import (
    AlreadyRunningError,
    ProjectArchivedError,
    SourceEntryRunningError,
    TimerService,
    manual_log,
)


def _project(conn, name="Web"):
    c = repo.create_customer(conn, f"Acme {name}")
    return repo.create_project(conn, customer_id=c.id, name=name)


def _finished_entry(conn, project_id, *, task="ACME-1", description="Doku"):
    return manual_log(
        conn,
        project_id=project_id,
        task=task,
        description=description,
        started_at=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        duration_seconds=30 * 60,
        round_minutes=None,
    )


def test_continue_starts_running_entry_with_same_project_task_description(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    svc = TimerService(conn)
    new = svc.continue_entry(source_id)
    assert new.id != source_id
    assert (new.project_id, new.task, new.description) == (p.id, "ACME-1", "Doku")
    assert new.ended_at is None
    assert new.is_manual is False
    assert [log.id for log in svc.running_entries()] == [new.id]


def test_continue_does_not_take_over_flags(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    flag = repo.create_flag(conn, name="abgerechnet")
    repo.set_log_flag(conn, source_id, flag.id, True)
    new = TimerService(conn).continue_entry(source_id)
    assert repo.get_log(conn, new.id).flags == []


def test_continue_of_booked_entry_is_unbooked(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    repo.set_log_external_ref(
        conn, source_id, worklog_id="4711", worklog_url="https://jira/4711",
        synced_at_iso="2026-05-07T10:00:00+00:00",
    )
    new = TimerService(conn).continue_entry(source_id)
    row = conn.execute("SELECT * FROM log_entry WHERE id = ?", (new.id,)).fetchone()
    booking_columns = [k for k in row.keys() if k.startswith("external_")]
    assert booking_columns
    assert all(row[k] is None for k in booking_columns)


def test_continue_leaves_source_entry_unchanged(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    flag = repo.create_flag(conn, name="abgerechnet")
    repo.set_log_flag(conn, source_id, flag.id, True)
    repo.set_log_external_ref(conn, source_id, worklog_id="4711")
    before = dict(conn.execute("SELECT * FROM log_entry WHERE id = ?", (source_id,)).fetchone())
    TimerService(conn).continue_entry(source_id)
    after = dict(conn.execute("SELECT * FROM log_entry WHERE id = ?", (source_id,)).fetchone())
    assert after == before
    assert [f.id for f in repo.get_log(conn, source_id).flags] == [flag.id]


def test_continue_stops_no_other_running_entry(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    svc = TimerService(conn)
    other = svc.start_entry(project_id=p.id, task="B", description=None)
    new = svc.continue_entry(source_id)
    assert [log.id for log in svc.running_entries()] == [other.id, new.id]


def test_continue_rejects_archived_project(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    repo.update_project(
        conn, p.id, name=p.name, color=p.color, round_minutes=p.round_minutes, archived=True
    )
    svc = TimerService(conn)
    with pytest.raises(ProjectArchivedError) as exc:
        svc.continue_entry(source_id)
    assert str(exc.value) == "Projekt ist archiviert"
    assert svc.running_entries() == []


def test_continue_rejects_project_of_archived_customer(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id)
    customer = repo.get_customer(conn, p.customer_id)
    repo.update_customer(conn, customer.id, name=customer.name, archived=True)
    svc = TimerService(conn)
    with pytest.raises(ProjectArchivedError):
        svc.continue_entry(source_id)
    assert svc.running_entries() == []


def test_continue_rejects_when_identical_entry_already_runs(conn):
    p = _project(conn)
    source_id = _finished_entry(conn, p.id, task="ACME-1", description="Doku")
    svc = TimerService(conn)
    running = svc.start_entry(project_id=p.id, task=" ACME-1 ", description="Doku")
    with pytest.raises(AlreadyRunningError) as exc:
        svc.continue_entry(source_id)
    assert str(exc.value) == "läuft bereits"
    assert exc.value.entry.id == running.id
    assert [log.id for log in svc.running_entries()] == [running.id]


def test_continue_rejects_source_entry_that_is_running_itself(conn):
    p = _project(conn)
    svc = TimerService(conn)
    source = svc.start_entry(project_id=p.id, task="A", description=None)
    with pytest.raises(SourceEntryRunningError):
        svc.continue_entry(source.id)
    assert [log.id for log in svc.running_entries()] == [source.id]


def test_continue_of_unknown_entry_starts_nothing(conn):
    svc = TimerService(conn)
    with pytest.raises(LookupError):
        svc.continue_entry(4711)
    assert svc.running_entries() == []
