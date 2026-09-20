import time

import pytest

from worklog import repository as repo
from worklog.services.timer import AlreadyRunningError, TimerService, manual_log


def test_start_creates_running_log(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    log = svc.start_entry(project_id=p.id, task="ACME-1", description="Work")
    assert log.ended_at is None
    state = repo.get_app_state(conn)
    assert state.last_project_id == p.id
    assert [entry.id for entry in svc.running_entries()] == [log.id]


def test_stop_applies_default_rounding(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    log = svc.start_entry(project_id=p.id, task="X", description=None)
    time.sleep(0.05)  # tiny duration, should round up to default 15min = 900s
    stopped = svc.stop_entry(log.id)
    assert stopped is not None
    assert stopped.duration_seconds == 15 * 60
    assert stopped.rounded_to_minutes == 15
    assert svc.running_entries() == []


def test_starting_while_running_keeps_previous_running(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description=None)
    second = svc.start_entry(project_id=p.id, task="B", description=None)
    assert first.id != second.id
    assert repo.get_log(conn, first.id).ended_at is None
    assert repo.get_log(conn, second.id).ended_at is None
    assert [log.id for log in svc.running_entries()] == [first.id, second.id]


def test_per_project_rounding_override(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web", round_minutes=30)
    svc = TimerService(conn)
    log = svc.start_entry(project_id=p.id, task="X", description=None)
    time.sleep(0.05)
    stopped = svc.stop_entry(log.id)
    assert stopped.duration_seconds == 30 * 60
    assert stopped.rounded_to_minutes == 30


def test_manual_log_applies_rounding(conn):
    from datetime import datetime, timezone
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    started = datetime(2026, 5, 8, 9, 0, tzinfo=timezone.utc)
    log_id = manual_log(
        conn,
        project_id=p.id,
        task="M-1",
        description="manual",
        started_at=started,
        duration_seconds=14 * 60,  # 14 min, default round 15
        round_minutes=None,
    )
    log = repo.get_log(conn, log_id)
    assert log.duration_seconds == 15 * 60
    assert log.is_manual is True


def _project(conn, **kwargs):
    c = repo.create_customer(conn, "Acme")
    return repo.create_project(conn, customer_id=c.id, name="Web", **kwargs)


def test_stop_entry_by_id_leaves_others_running(conn):
    p = _project(conn)
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description=None)
    second = svc.start_entry(project_id=p.id, task="B", description=None)
    stopped = svc.stop_entry(first.id)
    assert stopped is not None
    assert stopped.id == first.id
    assert stopped.ended_at is not None
    assert [log.id for log in svc.running_entries()] == [second.id]


def test_stop_all_stops_every_running_entry(conn):
    p = _project(conn)
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description=None)
    second = svc.start_entry(project_id=p.id, task="B", description=None)
    stopped = svc.stop_all()
    assert sorted(log.id for log in stopped) == [first.id, second.id]
    assert all(log.ended_at is not None for log in stopped)
    assert svc.running_entries() == []
    assert svc.stop_all() == []


def test_start_entry_rejects_identical_running_entry(conn):
    p = _project(conn)
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description="Doku")
    with pytest.raises(AlreadyRunningError) as exc:
        svc.start_entry(project_id=p.id, task="A", description="Doku")
    assert exc.value.entry.id == first.id
    assert [log.id for log in svc.running_entries()] == [first.id]


def test_duplicate_check_trims_and_treats_empty_as_unset(conn):
    p = _project(conn)
    svc = TimerService(conn)
    svc.start_entry(project_id=p.id, task="A", description=None)
    with pytest.raises(AlreadyRunningError):
        svc.start_entry(project_id=p.id, task="  A ", description="   ")
    with pytest.raises(AlreadyRunningError):
        svc.start_entry(project_id=p.id, task="A", description="")
    assert len(svc.running_entries()) == 1


def test_duplicate_check_only_blocks_identical_running_entries(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    other = repo.create_project(conn, customer_id=c.id, name="App")
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description="Doku")
    svc.start_entry(project_id=other.id, task="A", description="Doku")
    svc.start_entry(project_id=p.id, task="B", description="Doku")
    svc.start_entry(project_id=p.id, task="A", description="Review")
    assert len(svc.running_entries()) == 4
    # ein gestoppter Eintrag blockiert nicht mehr
    svc.stop_entry(first.id)
    again = svc.start_entry(project_id=p.id, task="A", description="Doku")
    assert again.id != first.id


def test_each_stopped_entry_uses_its_own_rounding(conn):
    c = repo.create_customer(conn, "Acme")
    default_proj = repo.create_project(conn, customer_id=c.id, name="Web")
    half_hour_proj = repo.create_project(conn, customer_id=c.id, name="App", round_minutes=30)
    svc = TimerService(conn)
    a = svc.start_entry(project_id=default_proj.id, task="A", description=None)
    b = svc.start_entry(project_id=half_hour_proj.id, task="B", description=None)
    time.sleep(0.05)
    stopped_b = svc.stop_entry(b.id)
    stopped_a = svc.stop_entry(a.id)
    assert (stopped_a.duration_seconds, stopped_a.rounded_to_minutes) == (15 * 60, 15)
    assert (stopped_b.duration_seconds, stopped_b.rounded_to_minutes) == (30 * 60, 30)


def test_stop_all_rounds_each_entry_with_its_own_rounding(conn):
    c = repo.create_customer(conn, "Acme")
    default_proj = repo.create_project(conn, customer_id=c.id, name="Web")
    half_hour_proj = repo.create_project(conn, customer_id=c.id, name="App", round_minutes=30)
    svc = TimerService(conn)
    a = svc.start_entry(project_id=default_proj.id, task="A", description=None)
    b = svc.start_entry(project_id=half_hour_proj.id, task="B", description=None)
    time.sleep(0.05)
    svc.stop_all()
    assert repo.get_log(conn, a.id).duration_seconds == 15 * 60
    assert repo.get_log(conn, b.id).duration_seconds == 30 * 60


def test_new_service_instance_sees_all_running_entries(conn):
    p = _project(conn)
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description=None)
    second = svc.start_entry(project_id=p.id, task="B", description=None)
    restarted = TimerService(conn)
    assert [log.id for log in restarted.running_entries()] == [first.id, second.id]
    restarted.stop_entry(first.id)
    assert [log.id for log in TimerService(conn).running_entries()] == [second.id]


def test_running_is_derived_from_data_not_from_app_state_pointer(conn):
    p = _project(conn)
    svc = TimerService(conn)
    first = svc.start_entry(project_id=p.id, task="A", description=None)
    assert repo.get_app_state(conn).running_log_id is None
    # ein veralteter Zeiger (Alt-DB) ändert nichts
    repo.set_running_log(conn, first.id)
    second = svc.start_entry(project_id=p.id, task="B", description=None)
    svc.stop_entry(first.id)
    assert [log.id for log in svc.running_entries()] == [second.id]


def test_sums_count_every_parallel_entry_with_full_duration(conn):
    p = _project(conn)
    svc = TimerService(conn)
    svc.start_entry(project_id=p.id, task="A", description=None)
    svc.start_entry(project_id=p.id, task="B", description=None)
    svc.stop_all()
    total = repo.sum_duration(conn, from_iso="0000", to_iso="9999")
    assert total == 2 * 15 * 60


def test_single_timer_interface_is_gone(conn):
    # Contract-Schritt (Ticket 03): kein "aktueller Eintrag", kein Wechseln,
    # kein Aktualisieren des laufenden Eintrags, kein Stoppen ohne ID; seit
    # Ticket 04 auch kein start() mehr (Starten = start_entry, Fortsetzen = continue_entry).
    svc = TimerService(conn)
    for name in ("current", "is_running", "start", "stop", "update_running", "switch"):
        assert not hasattr(svc, name), name


def test_start_entry_refuses_an_archived_project(conn):
    from worklog.services.timer import ProjectArchivedError

    p = _project(conn)
    repo.update_project(
        conn, p.id, name=p.name, color=p.color, round_minutes=p.round_minutes, archived=True
    )
    with pytest.raises(ProjectArchivedError):
        TimerService(conn).start_entry(project_id=p.id, task="A", description=None)
    assert TimerService(conn).running_entries() == []
