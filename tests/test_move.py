import os
import time
from datetime import date, datetime

import pytest

from worklog import repository as repo
from worklog.services.move import EntryRunningError, MoveRejectedError, move_entries_to_date

pytestmark = pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="pinning the local timezone needs time.tzset"
)


@pytest.fixture(autouse=True)
def berlin_tz():
    """The app keeps times in the machine's local zone, so moving depends on it.
    Pin it to a zone with daylight saving time to make the offsets predictable."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    yield
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()


def _project(conn) -> int:
    c = repo.create_customer(conn, "Acme")
    return repo.create_project(conn, customer_id=c.id, name="Web").id


def _entry(conn, project_id: int, started: str, ended: str | None, **kw) -> int:
    values = dict(
        project_id=project_id, task="ACME-1", description="Arbeit",
        started_at=started, ended_at=ended,
        duration_seconds=3600 if ended else None,
        rounded_to_minutes=15 if ended else None,
        is_manual=False,
    )
    values.update(kw)
    return repo.create_log(conn, **values)


def test_move_keeps_local_time_and_changes_only_the_date(conn):
    p = _project(conn)
    log_id = _entry(conn, p, "2026-06-10T09:15:00+02:00", "2026-06-10T10:05:00+02:00")

    move_entries_to_date(conn, [log_id], date(2026, 6, 12))

    moved = repo.get_log(conn, log_id)
    assert moved.started_at == datetime.fromisoformat("2026-06-12T09:15:00+02:00")
    assert moved.ended_at == datetime.fromisoformat("2026-06-12T10:05:00+02:00")


def test_move_across_dst_boundary_keeps_wall_clock_and_stored_duration(conn):
    p = _project(conn)
    # Friday in winter time (+01:00) → Monday after the switch to summer time (+02:00)
    log_id = _entry(conn, p, "2026-03-27T09:00:00+01:00", "2026-03-27T10:00:00+01:00")

    move_entries_to_date(conn, [log_id], date(2026, 3, 30))

    row = conn.execute(
        "SELECT started_at, ended_at, duration_seconds FROM log_entry WHERE id = ?", (log_id,)
    ).fetchone()
    assert row["started_at"] == "2026-03-30T09:00:00+02:00"
    assert row["ended_at"] == "2026-03-30T10:00:00+02:00"
    assert row["duration_seconds"] == 3600


def test_move_into_the_spring_forward_gap_keeps_the_entry_its_length(conn):
    p = _project(conn)
    # 02:30 does not exist on 2026-03-29 (02:00 → 03:00): the start lands one hour later,
    # and the end must not collapse onto it.
    log_id = _entry(conn, p, "2026-03-27T02:30:00+01:00", "2026-03-27T03:30:00+01:00")

    move_entries_to_date(conn, [log_id], date(2026, 3, 29))

    row = conn.execute("SELECT started_at, ended_at FROM log_entry WHERE id = ?", (log_id,)).fetchone()
    assert row["started_at"] == "2026-03-29T03:30:00+02:00"
    assert row["ended_at"] == "2026-03-29T04:30:00+02:00"


def _stored_times(conn) -> list[tuple]:
    return [
        tuple(r) for r in conn.execute("SELECT id, started_at, ended_at FROM log_entry ORDER BY id")
    ]


def test_running_entry_in_selection_moves_nothing_and_names_the_reason(conn):
    p = _project(conn)
    done = _entry(conn, p, "2026-06-10T09:00:00+02:00", "2026-06-10T10:00:00+02:00")
    running = _entry(conn, p, "2026-06-10T11:00:00+02:00", None)
    before = _stored_times(conn)

    with pytest.raises(EntryRunningError) as exc:
        move_entries_to_date(conn, [done, running], date(2026, 6, 12))

    assert isinstance(exc.value, MoveRejectedError)
    assert exc.value.entry.id == running
    assert _stored_times(conn) == before


def test_booked_entry_in_selection_moves_nothing_and_names_the_reason(conn):
    p = _project(conn)
    free = _entry(conn, p, "2026-06-10T09:00:00+02:00", "2026-06-10T10:00:00+02:00")
    booked = _entry(conn, p, "2026-06-10T11:00:00+02:00", "2026-06-10T12:00:00+02:00")
    repo.set_log_external_ref(conn, booked, worklog_id="10042")
    before = _stored_times(conn)

    # the central Sperr-Regel rejects it, with the same error as editing and deleting
    with pytest.raises(repo.EntryBookedError) as exc:
        move_entries_to_date(conn, [free, booked], date(2026, 6, 12))

    assert exc.value.log_ids == [booked]
    assert exc.value.total == 2
    assert _stored_times(conn) == before


def test_move_to_the_same_day_changes_nothing(conn):
    p = _project(conn)
    # recorded in another zone: even the stored offset must stay as it is
    _entry(conn, p, "2026-06-10T09:00:00+05:00", "2026-06-10T10:00:00+05:00")
    before = _stored_times(conn)

    move_entries_to_date(conn, [before[0][0]], date(2026, 6, 10))

    assert _stored_times(conn) == before


def test_move_several_entries_from_different_days_to_an_empty_day(conn):
    p = _project(conn)
    a = _entry(conn, p, "2026-06-08T08:00:00+02:00", "2026-06-08T09:00:00+02:00")
    b = _entry(conn, p, "2026-06-15T14:30:00+02:00", "2026-06-15T15:30:00+02:00")
    other = _entry(conn, p, "2026-06-08T10:00:00+02:00", "2026-06-08T11:00:00+02:00")

    move_entries_to_date(conn, [a, b], date(2026, 6, 11))

    assert _stored_times(conn) == [
        (a, "2026-06-11T08:00:00+02:00", "2026-06-11T09:00:00+02:00"),
        (b, "2026-06-11T14:30:00+02:00", "2026-06-11T15:30:00+02:00"),
        (other, "2026-06-08T10:00:00+02:00", "2026-06-08T11:00:00+02:00"),
    ]


def test_entry_across_midnight_keeps_its_length_and_moves_by_its_start_day(conn):
    p = _project(conn)
    log_id = _entry(conn, p, "2026-06-10T23:00:00+02:00", "2026-06-11T01:00:00+02:00",
                    duration_seconds=7200)

    move_entries_to_date(conn, [log_id], date(2026, 6, 20))

    assert _stored_times(conn) == [
        (log_id, "2026-06-20T23:00:00+02:00", "2026-06-21T01:00:00+02:00"),
    ]
    assert repo.get_log(conn, log_id).duration_seconds == 7200


def test_move_leaves_everything_but_start_and_end_untouched(conn):
    p = _project(conn)
    # rounded duration differs from end - start on purpose
    log_id = _entry(conn, p, "2026-06-10T09:00:00+02:00", "2026-06-10T09:40:00+02:00",
                    duration_seconds=2700, rounded_to_minutes=15, is_manual=True)
    flag = repo.create_flag(conn, name="abgerechnet")
    repo.set_log_flag(conn, log_id, flag.id, True)

    move_entries_to_date(conn, [log_id], date(2026, 6, 12))

    moved = repo.get_log(conn, log_id)
    assert (moved.project_id, moved.task, moved.description) == (p, "ACME-1", "Arbeit")
    assert (moved.duration_seconds, moved.rounded_to_minutes, moved.is_manual) == (2700, 15, True)
    assert [f.name for f in moved.flags] == ["abgerechnet"]
