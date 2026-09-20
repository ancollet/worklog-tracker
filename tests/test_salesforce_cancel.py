"""Buchung stornieren for Salesforce: delete the Kostenposition there, then unlock the Eintrag.

Seam (spec.md, Testing Decisions): the service over the in-memory database, with a
real Salesforce client over fake HTTP at the transport boundary.
"""
from __future__ import annotations

import urllib.error

import pytest

from tests.test_salesforce_booking import _configuration, _entry, _happy_transport, _project
from tests.test_salesforce_client import _FakeTransport, _creds, _http_error, _query_result, _token
from tests.test_salesforce_cost_item_delete import _NoContent
from worklog import repository as repo
from worklog.services import booking as cancel
from worklog.services import salesforce as sf
from worklog.services import salesforce_booking as booking

_COST_ITEM_ID = "a0BAA000000cost1AA"


def _booked_entry(conn, *, minutes=70) -> int:
    """An Eintrag of 1h10, gebucht as Kostenposition PCI-00042 with 1,5 h."""
    log_id = _entry(conn, _project(conn), minutes=minutes)
    client = sf.SalesforceClient(_creds(), opener=_happy_transport())
    proposal = booking.propose_booking(conn, log_id, _configuration())
    booking.book_entry(conn, client, _configuration(), booking.ConfirmedBooking.from_proposal(proposal))
    assert repo.get_log(conn, log_id).is_booked
    return log_id


def _client(*answers) -> tuple[sf.SalesforceClient, _FakeTransport]:
    transport = _FakeTransport(_token(), *answers)
    return sf.SalesforceClient(_creds(), opener=transport), transport


def _status(value: str):
    return _query_result({"Id": _COST_ITEM_ID, "Status__c": value})


def _snapshot(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT * FROM log_entry ORDER BY id").fetchall()]


def test_cancelling_deletes_the_cost_item_and_unlocks_the_entry(conn):
    log_id = _booked_entry(conn)
    client, transport = _client(_status("Open"), _NoContent())

    outcome = cancel.cancel_booking(conn, log_id, salesforce_client=client)

    assert outcome == cancel.CANCELLED
    delete = transport.requests[-1]
    assert delete.get_method() == "DELETE" and delete.full_url.endswith(f"/ProjectCostItem__c/{_COST_ITEM_ID}")
    log = repo.get_log(conn, log_id)
    assert log.is_booked is False
    assert (log.external_worklog_id, log.external_worklog_url,
            log.external_worklog_number, log.external_synced_at) == (None, None, None, None)


def test_cost_item_that_is_no_longer_open_refuses_the_cancellation(conn):
    log_id = _booked_entry(conn)
    before = _snapshot(conn)
    client, transport = _client(_status("Invoiced"))

    with pytest.raises(sf.CostItemNotOpenError) as excinfo:
        cancel.cancel_booking(conn, log_id, salesforce_client=client)

    assert _snapshot(conn) == before
    assert repo.get_log(conn, log_id).is_booked is True
    assert "DELETE" not in [r.get_method() for r in transport.requests]
    assert _COST_ITEM_ID not in str(excinfo.value)


@pytest.mark.parametrize("failure, error_type", [
    (_http_error(400, [{"message": "Abgerechnet: Löschen nicht erlaubt.",
                        "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION"}]), sf.CostItemDeleteRefusedError),
    (urllib.error.URLError("no route to host"), sf.SalesforceNetworkError),
    (_http_error(500), sf.SalesforceOrgError),
])
def test_failed_delete_leaves_the_entry_booked_and_unchanged(conn, failure, error_type):
    log_id = _booked_entry(conn)
    before = _snapshot(conn)
    client, _transport = _client(_status("Open"), failure)

    with pytest.raises(error_type):
        cancel.cancel_booking(conn, log_id, salesforce_client=client)

    assert _snapshot(conn) == before
    with pytest.raises(repo.EntryBookedError):
        repo.delete_log(conn, log_id)


def test_rejected_sign_in_leaves_the_entry_booked(conn):
    log_id = _booked_entry(conn)
    before = _snapshot(conn)
    transport = _FakeTransport(_http_error(400, {"error": "invalid_client", "error_description": "invalid client"}))

    with pytest.raises(sf.SalesforceAuthError):
        cancel.cancel_booking(conn, log_id, salesforce_client=sf.SalesforceClient(_creds(), opener=transport))

    assert _snapshot(conn) == before


def test_cost_item_already_deleted_in_salesforce_unlocks_the_entry_and_says_so(conn):
    log_id = _booked_entry(conn)
    client, transport = _client(_query_result())

    outcome = cancel.cancel_booking(conn, log_id, salesforce_client=client)

    assert outcome == cancel.CANCELLED_COST_ITEM_MISSING
    assert "DELETE" not in [r.get_method() for r in transport.requests]
    log = repo.get_log(conn, log_id)
    assert log.is_booked is False
    assert log.external_worklog_number is None


def test_notice_for_a_missing_cost_item_names_its_number_and_never_its_id(conn):
    cancellation = cancel.prepare_cancellation(conn, _booked_entry(conn))

    notice = cancel.cost_item_missing_notice(cancellation)

    assert "Kostenposition PCI-00042" in notice and "Salesforce" in notice and "freigegeben" in notice
    assert _COST_ITEM_ID not in notice


def test_salesforce_booking_is_never_cancelled_without_salesforce(conn):
    log_id = _booked_entry(conn)
    before = _snapshot(conn)

    with pytest.raises(cancel.CancelRefusedError):
        cancel.cancel_booking(conn, log_id)

    assert _snapshot(conn) == before


def test_rounded_up_duration_stays_and_can_be_changed_by_hand(conn):
    log_id = _booked_entry(conn, minutes=70)       # gebucht with 1,5 h
    client, _transport = _client(_status("Open"), _NoContent())

    cancel.cancel_booking(conn, log_id, salesforce_client=client)

    log = repo.get_log(conn, log_id)
    assert log.duration_seconds == 90 * 60
    repo.update_log(
        conn, log_id, project_id=log.project_id, task=log.task, description="von Hand geändert",
        started_at=log.started_at.isoformat(timespec="seconds"),
        ended_at="2026-05-09T00:40:00+02:00", duration_seconds=70 * 60,
        rounded_to_minutes=log.rounded_to_minutes,
    )
    changed = repo.get_log(conn, log_id)
    assert (changed.duration_seconds, changed.description) == (70 * 60, "von Hand geändert")


def test_cancelled_entry_can_be_booked_again_as_a_new_cost_item(conn):
    from tests.test_salesforce_booking import _FakeResponse, _PROJECT_ID

    log_id = _booked_entry(conn)
    client, _transport = _client(_status("Open"), _NoContent())
    cancel.cancel_booking(conn, log_id, salesforce_client=client)
    new_id = "a0BAA000000cost2AA"
    rebook = sf.SalesforceClient(_creds(), opener=_FakeTransport(
        _token(), _query_result({"Id": _PROJECT_ID}),
        _FakeResponse({"id": new_id, "success": True, "errors": []}, status=201),
        _query_result({"Name": "PCI-00043"}),
    ))

    proposal = booking.propose_booking(conn, log_id, _configuration())
    assert proposal.is_bookable
    booking.book_entry(conn, rebook, _configuration(), booking.ConfirmedBooking.from_proposal(proposal))

    log = repo.get_log(conn, log_id)
    assert (log.external_worklog_id, log.external_worklog_number) == (new_id, "PCI-00043")


def test_jira_cancellation_stays_local_and_never_talks_to_salesforce(conn):
    from tests.test_booked_lock import _entry as _jira_entry, _project as _jira_project

    log_id = _jira_entry(conn, _jira_project(conn, "jira"), booked=True)
    client, transport = _client()

    outcome = cancel.cancel_booking(conn, log_id, salesforce_client=client)

    assert outcome == cancel.CANCELLED
    assert transport.requests == []
    assert repo.get_log(conn, log_id).is_booked is False


def test_recording_does_nothing_when_the_entry_carries_another_booking_by_now(conn):
    log_id = _booked_entry(conn)
    stale = cancel.Cancellation(log_id=log_id, booking_system="salesforce", reference="a0BAA000000otherAA")
    before = _snapshot(conn)

    cancel.record_cancellation(conn, stale)

    assert _snapshot(conn) == before
