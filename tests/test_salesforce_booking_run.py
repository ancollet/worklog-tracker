"""Sammelbuchung: several Einträge in one run, row by row.

Seam (spec.md, Testing Decisions): the service over the in-memory database, with a
real Salesforce client over fake HTTP at the transport boundary.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error
from dataclasses import replace

import pytest

from tests.test_salesforce_booking import _client, _configuration
from tests.test_salesforce_client import _FakeResponse, _FakeTransport, _http_error, _query_result, _token
from worklog import repository as repo
from worklog.services import salesforce as sf
from worklog.services import salesforce_booking as booking
from worklog.services import salesforce_booking_run as run_service
from worklog.services.salesforce_booking_run import BookingRun

_ROLLOUT = "a01AA0000000ro1AAA"
_SUPPORT = "a01AA0000000su2AAA"   # the first 15 characters identify the record


def _projects(conn):
    """Two registrierte Projekte of one Salesforce-Kunde."""
    customer = repo.create_customer(conn, "Acme", booking_system="salesforce")
    projects = []
    for name, salesforce_id in (("Rollout", _ROLLOUT), ("Support", _SUPPORT)):
        project = repo.create_project(conn, customer_id=customer.id, name=name)
        repo.set_project_salesforce_project(
            conn, project.id, salesforce_project_id=salesforce_id, salesforce_project_name=name,
        )
        projects.append(repo.get_project(conn, project.id))
    return projects


def _entry(conn, project, *, day=8, task="SOT-1", description="Flow gebaut", minutes=70, running=False) -> int:
    return repo.create_log(
        conn, project_id=project.id, task=task, description=description,
        started_at=f"2026-05-{day:02d}T09:00:00+02:00",
        ended_at=None if running else f"2026-05-{day:02d}T10:10:00+02:00",
        duration_seconds=None if running else minutes * 60,
        rounded_to_minutes=15, is_manual=False,
    )


def _created(n: int):
    return _FakeResponse({"id": f"a0BAA000000cost{n}AA", "success": True, "errors": []}, status=201)


def _number(n: int):
    return _query_result({"Name": f"PCI-{n:05d}"})


def _open(*salesforce_ids):
    return _query_result(*({"Id": i} for i in salesforce_ids))


def _creates(transport) -> list[dict]:
    return [
        json.loads(r.data.decode("utf-8")) for r in transport.requests
        if r.get_method() == "POST" and "/sobjects/" in r.full_url
    ]


def _confirm(run: BookingRun) -> list[booking.ConfirmedBooking]:
    return [booking.ConfirmedBooking.from_proposal(row.proposal) for row in run.rows if row.is_open]


# ---------- Buchungsvorschläge ----------

def test_rows_are_sorted_by_date_whatever_the_order_of_the_selection(conn):
    rollout, support = _projects(conn)
    late, early, middle = _entry(conn, rollout, day=12), _entry(conn, support, day=5), _entry(conn, rollout, day=8)

    run = BookingRun(conn, _configuration(), [late, early, middle, late])

    assert [row.log_id for row in run.rows] == [early, middle, late]
    assert all(row.state == run_service.OPEN and row.is_open for row in run.rows)


def test_every_reason_why_a_row_is_not_bookable(conn):
    rollout, support = _projects(conn)
    jira = repo.create_project(
        conn, customer_id=repo.create_customer(conn, "Igus", booking_system="jira").id, name="Shop")
    unregistered = repo.create_project(conn, customer_id=rollout.customer_id, name="Intern")
    booked = _entry(conn, rollout, day=1)
    repo.set_log_external_ref(conn, booked, worklog_id="a0Bold", worklog_number="PCI-1")
    log_ids = {
        "booked": booked,
        "running": _entry(conn, rollout, day=2, running=True),
        "no_duration": _entry(conn, rollout, day=3, minutes=0),
        "nothing_to_describe": _entry(conn, rollout, day=4, task=None, description=" "),
        "unregistered": _entry(conn, unregistered, day=5),
        "jira": _entry(conn, jira, day=6),
        "closed": _entry(conn, support, day=7),
        "fine": _entry(conn, rollout, day=8),
        "gone": 99999,
    }
    transport = _FakeTransport(_token(), _open(_ROLLOUT))   # Support is no longer offen

    run = BookingRun(conn, _configuration(), log_ids.values())
    run.check_projects(_client(transport))

    rows = {name: next(r for r in run.rows if r.log_id == log_id) for name, log_id in log_ids.items()}
    assert {name: row.message for name, row in rows.items() if row.state == run_service.BLOCKED} == {
        "booked": "Eintrag ist bereits gebucht.",
        "running": "Eintrag läuft noch.",
        "no_duration": "Eintrag hat keine Dauer.",
        "nothing_to_describe": "Eintrag hat weder Task noch Beschreibung.",
        "unregistered": "Projekt ist nicht registriert (mit keinem Salesforce-Projekt verbunden).",
        "jira": "Der Kunde dieses Eintrags bucht nicht in Salesforce.",
        "closed": "Projekt ist in Salesforce geschlossen.",
        "gone": "Eintrag existiert nicht mehr.",
    }
    assert [name for name, row in rows.items() if row.is_open] == ["fine"]


def test_the_affected_projects_are_checked_with_one_single_question(conn):
    rollout, support = _projects(conn)
    ids = [_entry(conn, rollout, day=1), _entry(conn, support, day=2), _entry(conn, rollout, day=3)]
    transport = _FakeTransport(_token(), _open(_ROLLOUT, _SUPPORT))

    run = BookingRun(conn, _configuration(), ids)
    assert not run.is_checked
    run.check_projects(_client(transport))

    assert run.is_checked
    (question,) = transport.requests[1:]
    assert _ROLLOUT[:15] in question.full_url and _SUPPORT[:15] in question.full_url
    assert repo.get_project(conn, support.id).salesforce_checked_at is not None


# ---------- Der Lauf ----------

def _checked_run(conn, log_ids, *, still_open=(_ROLLOUT, _SUPPORT)):
    run = BookingRun(conn, _configuration(), log_ids)
    run.check_projects(_client(_FakeTransport(_token(), _open(*still_open))))
    return run


def test_every_row_becomes_exactly_one_cost_item_in_date_order(conn):
    rollout, support = _projects(conn)
    second, first = _entry(conn, support, day=9, description="Zweiter"), _entry(conn, rollout, day=8, description="Erster")
    run = _checked_run(conn, [second, first])
    transport = _FakeTransport(_token(), _created(1), _number(1), _created(2), _number(2))

    run.book(_client(transport), _confirm(run))

    assert [item["Description__c"] for item in _creates(transport)] == ["SOT-1: Erster", "SOT-1: Zweiter"]
    assert len(transport.requests) == 5   # no further "still offen?" per row
    assert [(row.state, row.message) for row in run.rows] == [
        (run_service.BOOKED, "PCI-00001"), (run_service.BOOKED, "PCI-00002"),
    ]
    assert run.booked_log_ids == [first, second]
    log = repo.get_log(conn, first)
    assert (log.external_worklog_id, log.external_worklog_number) == ("a0BAA000000cost1AA", "PCI-00001")
    assert log.duration_seconds == 90 * 60   # 1h10 was gebucht as 1,5 h
    assert not any(row.is_open for row in run.rows)


_VALIDATION = [{"message": "Service Type passt nicht zum Projekt.", "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION"}]


def test_a_failing_row_in_the_middle_does_not_stop_the_others(conn):
    rollout, _support = _projects(conn)
    first, middle, last = (_entry(conn, rollout, day=day) for day in (5, 6, 7))
    run = _checked_run(conn, [first, middle, last])
    before = repo.get_log(conn, middle)
    transport = _FakeTransport(
        _token(), _created(1), _number(1), _http_error(400, _VALIDATION), _created(3), _number(3),
    )

    run.book(_client(transport), _confirm(run))

    states = {row.log_id: row for row in run.rows}
    assert states[first].state == states[last].state == run_service.BOOKED
    assert states[middle].state == run_service.FAILED and states[middle].is_open
    assert "Service Type passt nicht" in states[middle].message
    assert run.booked_log_ids == [first, last]
    assert repo.get_log(conn, middle) == before
    assert repo.get_log(conn, last).is_booked
    assert run.aborted_reason is None


def test_booking_again_sends_only_the_failed_row_with_its_corrected_values(conn):
    rollout, _support = _projects(conn)
    first, middle = _entry(conn, rollout, day=5), _entry(conn, rollout, day=6)
    run = _checked_run(conn, [first, middle])
    run.book(_client(_FakeTransport(_token(), _created(1), _number(1), _http_error(400, _VALIDATION))), _confirm(run))
    transport = _FakeTransport(_token(), _created(2), _number(2))

    # Everything is confirmed again — the gebuchte row must not be sent a second time.
    again = [
        booking.ConfirmedBooking.from_proposal(row.proposal) for row in run.rows
    ]
    again = [replace(c, service_type="Consulting") if c.log_id == middle else c for c in again]
    run.book(_client(transport), again)

    (created,) = _creates(transport)
    assert created["ServiceType__c"] == "Consulting"
    assert [row.state for row in run.rows] == [run_service.BOOKED, run_service.BOOKED]
    assert run.booked_log_ids == [first, middle]
    assert repo.get_log(conn, first).external_worklog_number == "PCI-00001"
    assert repo.get_log(conn, middle).external_worklog_number == "PCI-00002"


# ---------- Errors that concern every row ----------

_SESSION_EXPIRED = [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}]


@pytest.mark.parametrize(
    "answers",
    [
        # Anmeldung abgelehnt: the token is refused right at the second row
        (_http_error(401, _SESSION_EXPIRED), _http_error(400, {"error": "invalid_client"})),
        (urllib.error.URLError("Network is unreachable"),),
    ],
    ids=["anmeldung", "netz"],
)
def test_an_error_that_concerns_all_rows_stops_the_run_without_further_calls(conn, answers):
    rollout, _support = _projects(conn)
    first, second, third = (_entry(conn, rollout, day=day) for day in (5, 6, 7))
    run = _checked_run(conn, [first, second, third])
    transport = _FakeTransport(_token(), _created(1), _number(1), *answers)

    run.book(_client(transport), _confirm(run))

    assert transport.answers == []                # nothing was asked for the third row
    assert len(_creates(transport)) == 2          # the first one, and the attempt of the second
    assert [row.state for row in run.rows] == [run_service.BOOKED, run_service.FAILED, run_service.NOT_RUN]
    assert run.rows[2].message == "Nicht ausgeführt."
    assert run.rows[1].message == run.aborted_reason
    assert all(row.is_open for row in run.rows[1:])
    assert repo.get_log(conn, first).is_booked and not repo.get_log(conn, third).is_booked
    assert not run.is_running


# ---------- Abgleich before Buchen ----------

def test_nothing_is_booked_when_the_projects_could_not_be_checked(conn):
    rollout, _support = _projects(conn)
    run = BookingRun(conn, _configuration(), [_entry(conn, rollout)])
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"), _created(1), _number(1))
    client = _client(transport)

    with pytest.raises(sf.SalesforceNetworkError):
        run.check_projects(client)
    with pytest.raises(booking.BookingError, match="geprüft"):
        run.book(client, _confirm(run))

    assert not run.is_checked
    assert _creates(transport) == []
    assert repo.get_project(conn, rollout.id).salesforce_checked_at is None


def test_a_row_of_a_closed_project_is_never_sent_even_when_confirmed(conn):
    rollout, support = _projects(conn)
    fine, closed = _entry(conn, rollout, day=5), _entry(conn, support, day=6)
    run = _checked_run(conn, [fine, closed], still_open=[_ROLLOUT])
    transport = _FakeTransport(_token(), _created(1), _number(1))
    everything = [booking.ConfirmedBooking.from_proposal(row.proposal) for row in run.rows]

    run.book(_client(transport), everything)

    assert len(_creates(transport)) == 1
    assert [row.state for row in run.rows] == [run_service.BOOKED, run_service.BLOCKED]
    assert not repo.get_log(conn, closed).is_booked
    assert repo.get_project(conn, support.id).closed_in_salesforce


# ---------- Rows that fail without Salesforce ----------

def test_a_row_refused_locally_costs_no_call_and_the_next_row_is_still_booked(conn):
    rollout, _support = _projects(conn)
    invalid, booked_elsewhere, fine = (_entry(conn, rollout, day=day) for day in (5, 6, 7))
    run = _checked_run(conn, [invalid, booked_elsewhere, fine])
    confirmed = _confirm(run)
    confirmed[0] = replace(confirmed[0], quantity_hours=0.75)
    repo.set_log_external_ref(conn, booked_elsewhere, worklog_id="a0Bother", worklog_number="PCI-7")
    transport = _FakeTransport(_token(), _created(3), _number(3))

    run.book(_client(transport), confirmed)

    assert len(_creates(transport)) == 1
    assert [row.state for row in run.rows] == [run_service.FAILED, run_service.BLOCKED, run_service.BOOKED]
    assert "Vielfaches von 0,5" in run.rows[0].message
    assert run.rows[1].message == "Eintrag ist bereits gebucht."
    assert repo.get_log(conn, booked_elsewhere).external_worklog_number == "PCI-7"


# ---------- Never twice ----------

def test_a_second_start_while_the_run_is_going_is_refused(conn):
    rollout, _support = _projects(conn)
    run = _checked_run(conn, [_entry(conn, rollout, day=5), _entry(conn, rollout, day=6)])
    confirmed = _confirm(run)
    run.start(confirmed)
    prepared = run.next_submission()

    with pytest.raises(booking.BookingError, match="läuft"):
        run.start(confirmed)   # the double click

    with pytest.raises(booking.BookingError, match="läuft"):
        run.next_submission()   # no second row is handed out while one is on its way
    assert run.is_running and prepared.log_id == run.rows[0].log_id


def test_booking_everything_twice_creates_nothing_the_second_time(conn):
    rollout, _support = _projects(conn)
    run = _checked_run(conn, [_entry(conn, rollout, day=5)])
    confirmed = _confirm(run)
    run.book(_client(_FakeTransport(_token(), _created(1), _number(1))), confirmed)
    transport = _FakeTransport()

    run.book(_client(transport), confirmed)

    assert transport.requests == []
    assert run.booked_log_ids == [run.rows[0].log_id]


def test_a_cost_item_that_could_not_be_saved_is_saved_later_and_never_created_again(conn, monkeypatch):
    rollout, _support = _projects(conn)
    unlucky, fine = _entry(conn, rollout, day=5), _entry(conn, rollout, day=6)
    run = _checked_run(conn, [unlucky, fine])
    save = repo.set_log_booked_duration
    failures = [sqlite3.OperationalError("database is locked")]

    def save_failing_once(*args, **kwargs):
        if failures:
            raise failures.pop()
        return save(*args, **kwargs)

    monkeypatch.setattr(repo, "set_log_booked_duration", save_failing_once)
    transport = _FakeTransport(_token(), _created(1), _number(1), _created(2), _number(2))
    run.book(_client(transport), _confirm(run))

    assert [row.state for row in run.rows] == [run_service.UNSAVED, run_service.BOOKED]
    assert "PCI-00001" in run.rows[0].message and "a0BAA" not in run.rows[0].message
    assert not run.rows[0].is_open               # its values cannot be changed any more
    assert run.has_unsaved
    assert not repo.get_log(conn, unlucky).is_booked

    again = _FakeTransport()
    run.book(_client(again), [booking.ConfirmedBooking.from_proposal(row.proposal) for row in run.rows])

    assert again.requests == []                  # only the saving was repeated
    assert [row.state for row in run.rows] == [run_service.BOOKED, run_service.BOOKED]
    assert repo.get_log(conn, unlucky).external_worklog_id == "a0BAA000000cost1AA"
    assert not run.has_unsaved


# ---------- Abbrechen ----------

def test_stopping_lets_the_row_on_its_way_finish_and_leaves_the_rest_unsent(conn):
    rollout, _support = _projects(conn)
    first, second = _entry(conn, rollout, day=5), _entry(conn, rollout, day=6)
    run = _checked_run(conn, [first, second])
    transport = _FakeTransport(_token(), _created(1), _number(1))
    client = _client(transport)
    run.start(_confirm(run))
    prepared = run.next_submission()

    run.stop()
    assert run.is_running                        # the first Kostenposition is still being created
    run.finish_submission(prepared, run_service.submit(client, prepared))

    assert run.next_submission() is None and not run.is_running
    assert [row.state for row in run.rows] == [run_service.BOOKED, run_service.NOT_RUN]
    assert repo.get_log(conn, first).is_booked and not repo.get_log(conn, second).is_booked


def test_progress_counts_the_rows_of_the_current_run(conn):
    rollout, _support = _projects(conn)
    run = _checked_run(conn, [_entry(conn, rollout, day=5), _entry(conn, rollout, day=6)])
    client = _client(_FakeTransport(_token(), _created(1), _number(1), _created(2), _number(2)))
    seen = [run.progress]

    run.start(_confirm(run))
    while (prepared := run.next_submission()) is not None:
        seen.append(run.progress)
        run.finish_submission(prepared, run_service.submit(client, prepared))
    seen.append(run.progress)

    assert seen == [(0, 0), (0, 2), (1, 2), (2, 2)]
