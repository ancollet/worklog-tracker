import time

from worklog import repository as repo
from worklog.services.timer import TimerService, manual_log


def test_start_creates_running_log(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    log = svc.start(project_id=p.id, task="ACME-1", description="Work")
    assert log.ended_at is None
    state = repo.get_app_state(conn)
    assert state.running_log_id == log.id
    assert state.last_project_id == p.id
    assert svc.is_running()


def test_stop_applies_default_rounding(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    svc.start(project_id=p.id, task="X", description=None)
    time.sleep(0.05)  # tiny duration, should round up to default 15min = 900s
    stopped = svc.stop()
    assert stopped is not None
    assert stopped.duration_seconds == 15 * 60
    assert stopped.rounded_to_minutes == 15
    assert not svc.is_running()


def test_starting_while_running_stops_previous(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    svc = TimerService(conn)
    first = svc.start(project_id=p.id, task="A", description=None)
    second = svc.start(project_id=p.id, task="B", description=None)
    assert first.id != second.id
    first_after = repo.get_log(conn, first.id)
    assert first_after.ended_at is not None
    state = repo.get_app_state(conn)
    assert state.running_log_id == second.id


def test_per_project_rounding_override(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web", round_minutes=30)
    svc = TimerService(conn)
    svc.start(project_id=p.id, task="X", description=None)
    time.sleep(0.05)
    stopped = svc.stop()
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
