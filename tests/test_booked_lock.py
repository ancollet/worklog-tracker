"""Sperr-Regel: a gebuchter Eintrag is locked until its Buchung is storniert."""
import pytest

from worklog import repository as repo


def _project(conn, booking_system="jira") -> int:
    c = repo.create_customer(conn, "Acme", booking_system=booking_system)
    return repo.create_project(conn, customer_id=c.id, name="Web").id


def _entry(conn, project_id: int, *, booked: bool = False, description: str = "Arbeit") -> int:
    log_id = repo.create_log(
        conn, project_id=project_id, task="ACME-1", description=description,
        started_at="2026-06-10T09:00:00+02:00", ended_at="2026-06-10T10:00:00+02:00",
        duration_seconds=3600, rounded_to_minutes=15, is_manual=False,
    )
    if booked:
        repo.set_log_external_ref(
            conn, log_id, worklog_id="10042", worklog_url="https://jira/ACME-1",
            synced_at_iso="2026-06-10T10:05:00+02:00",
        )
    return log_id


def _edit(conn, log_id: int, **changes) -> None:
    log = repo.get_log(conn, log_id)
    values = dict(
        project_id=log.project_id, task=log.task, description=log.description,
        started_at=log.started_at.isoformat(timespec="seconds"),
        ended_at=log.ended_at.isoformat(timespec="seconds"),
        duration_seconds=log.duration_seconds, rounded_to_minutes=log.rounded_to_minutes,
    )
    values.update(changes)
    repo.update_log(conn, log_id, **values)


def _snapshot(conn) -> list[tuple]:
    rows = conn.execute("SELECT * FROM log_entry ORDER BY id").fetchall()
    return [tuple(r) for r in rows]


def test_editing_a_booked_entry_is_rejected(conn):
    booked = _entry(conn, _project(conn), booked=True)
    before = _snapshot(conn)

    with pytest.raises(repo.EntryBookedError) as exc:
        _edit(conn, booked, description="nachträglich geändert")

    assert str(exc.value) == "Eintrag ist gebucht, erst Buchung stornieren"
    assert exc.value.log_ids == [booked]
    assert _snapshot(conn) == before


def test_deleting_a_booked_entry_is_rejected(conn):
    booked = _entry(conn, _project(conn), booked=True)

    with pytest.raises(repo.EntryBookedError):
        repo.delete_log(conn, booked)

    assert repo.get_log(conn, booked) is not None


def test_bulk_delete_with_a_booked_entry_deletes_nothing_and_names_the_count(conn):
    p = _project(conn)
    free_a = _entry(conn, p)
    booked_a = _entry(conn, p, booked=True)
    free_b = _entry(conn, p)
    booked_b = _entry(conn, p, booked=True)
    before = _snapshot(conn)

    with pytest.raises(repo.EntryBookedError) as exc:
        repo.delete_logs_bulk(conn, [free_a, booked_a, free_b, booked_b])

    assert exc.value.count == 2
    assert exc.value.log_ids == [booked_a, booked_b]
    assert str(exc.value) == "2 von 4 Einträgen sind gebucht, erst Buchung stornieren"
    assert _snapshot(conn) == before


def test_flags_can_be_set_and_removed_on_booked_entries(conn):
    p = _project(conn)
    booked = _entry(conn, p, booked=True)
    other = _entry(conn, p, booked=True)
    flag = repo.create_flag(conn, name="abgerechnet")

    repo.set_log_flag(conn, booked, flag.id, True)
    assert [f.id for f in repo.get_log(conn, booked).flags] == [flag.id]
    repo.set_log_flag(conn, booked, flag.id, False)
    assert repo.get_log(conn, booked).flags == []

    repo.set_log_flag_bulk(conn, [booked, other], flag.id, True)
    assert repo.count_logs_with_flag(conn, [booked, other]) == {flag.id: 2}
    repo.set_log_flag_bulk(conn, [booked, other], flag.id, False)
    assert repo.count_logs_with_flag(conn, [booked, other]) == {}

    assert repo.toggle_log_flag(conn, booked, flag.id) is True


def test_a_booked_entry_can_be_continued(conn):
    from worklog.services.timer import TimerService

    booked = _entry(conn, _project(conn), booked=True)

    new = TimerService(conn).continue_entry(booked)

    assert new.id != booked
    assert new.ended_at is None
    assert new.is_booked is False
    assert repo.get_log(conn, booked).is_booked is True


# ---------- Buchung stornieren ----------

def test_cancelling_a_jira_booking_unlocks_the_entry(conn):
    from worklog.services.booking import cancel_booking

    booked = _entry(conn, _project(conn, "jira"), booked=True)

    cancel_booking(conn, booked)

    log = repo.get_log(conn, booked)
    assert log.is_booked is False
    assert (log.external_worklog_id, log.external_worklog_url, log.external_synced_at) == (
        None, None, None,
    )
    _edit(conn, booked, description="wieder änderbar")
    assert repo.get_log(conn, booked).description == "wieder änderbar"
    repo.delete_log(conn, booked)
    assert repo.get_log(conn, booked) is None


def test_cancelling_keeps_the_flags(conn):
    from worklog.services.booking import cancel_booking

    booked = _entry(conn, _project(conn), booked=True)
    flag = repo.create_flag(conn, name="abgerechnet")
    repo.set_log_flag(conn, booked, flag.id, True)

    cancel_booking(conn, booked)

    assert [f.id for f in repo.get_log(conn, booked).flags] == [flag.id]


def test_cancelling_an_unbooked_or_missing_entry(conn):
    from worklog.services.booking import cancel_booking

    free = _entry(conn, _project(conn))
    before = _snapshot(conn)

    cancel_booking(conn, free)  # nothing to do

    assert _snapshot(conn) == before
    with pytest.raises(LookupError):
        cancel_booking(conn, 9999)


def test_cancel_hint_for_jira_says_the_worklog_stays_in_jira(conn):
    from worklog.services.booking import cancel_booking_hint

    booked = repo.get_log(conn, _entry(conn, _project(conn, "jira"), booked=True))

    assert "Worklog in Jira bleibt bestehen" in cancel_booking_hint(booked)
