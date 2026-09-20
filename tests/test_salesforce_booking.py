"""Buchen in Salesforce: the rules, the Buchungsvorschlag and the Buchung itself.

Seam (spec.md, Testing Decisions): the service over the in-memory database, with a
real Salesforce client over fake HTTP at the transport boundary.
"""
from __future__ import annotations

import json
import urllib.error
from dataclasses import replace
from datetime import date

import pytest

from tests.test_salesforce_client import _FakeResponse, _FakeTransport, _creds, _http_error, _query_result, _token
from worklog import repository as repo
from worklog.services import salesforce as sf
from worklog.services import salesforce_booking as booking
from worklog.services import salesforce_settings as sf_settings


# ---------- Mengenregel ----------

@pytest.mark.parametrize(
    ("duration_seconds", "hours"),
    [
        (60, 0.5),            # 1 min
        (30 * 60, 0.5),       # exactly half an hour stays
        (31 * 60, 1.0),
        (70 * 60, 1.5),       # 1h10
        (2 * 3600, 2.0),      # exactly two hours stay
        (2 * 3600 + 1, 2.5),  # one second more is rounded UP
        (0, 0.5),             # never less than 0,5
    ],
)
def test_quantity_is_rounded_up_to_half_hours(duration_seconds, hours):
    assert booking.booking_quantity_hours(duration_seconds) == hours


# ---------- Beschreibungsregel ----------

@pytest.mark.parametrize(
    ("task", "description", "text"),
    [
        ("SOT-1", "Flow gebaut", "SOT-1: Flow gebaut"),
        (None, "Flow gebaut", "Flow gebaut"),
        ("SOT-1", None, "SOT-1"),
        (None, None, ""),             # nothing to say: not buchbar
        ("  ", " \n", ""),            # blanks count as empty
        (" SOT-1 ", "  Flow gebaut ", "SOT-1: Flow gebaut"),
    ],
)
def test_description_is_task_colon_description(task, description, text):
    assert booking.booking_description(task, description) == text


# ---------- Fixtures ----------

_PROJECT_ID = "a01AA000000proj1AA"
_PERSON_ID = "005AA000000pers1AA"
_COST_ITEM_ID = "a0BAA000000cost1AA"


def _configuration(*, person: bool = True, secret: str | None = "s3cret") -> sf_settings.SalesforceConfiguration:
    missing = []
    if not secret:
        missing.append("Consumer Secret")
    if not person:
        missing.append("Leistende Person")
    return sf_settings.SalesforceConfiguration(
        credentials=_creds() if secret else None,
        missing=missing,
        leistende_person=sf_settings.LeistendePerson(_PERSON_ID, "Ada Lovelace") if person else None,
    )


def _project(conn, *, booking_system="salesforce", registered=True, service_type="Development",
             request_type="SOT-00348"):
    customer = repo.create_customer(conn, "Acme", booking_system=booking_system)
    project = repo.create_project(conn, customer_id=customer.id, name="Rollout")
    if registered:
        repo.set_project_salesforce_project(
            conn, project.id, salesforce_project_id=_PROJECT_ID, salesforce_project_name="Rollout 2026",
        )
    repo.set_project_booking_defaults(
        conn, project.id, default_service_type=service_type, customer_request_type=request_type,
    )
    return repo.get_project(conn, project.id)


def _entry(conn, project, *, task="SOT-1", description="Flow gebaut", minutes=70, running=False) -> int:
    return repo.create_log(
        conn, project_id=project.id, task=task, description=description,
        started_at="2026-05-08T23:30:00+02:00",
        ended_at=None if running else "2026-05-09T00:40:00+02:00",
        duration_seconds=None if running else minutes * 60,
        rounded_to_minutes=15, is_manual=False,
    )


def _created():
    return _FakeResponse({"id": _COST_ITEM_ID, "success": True, "errors": []}, status=201)


def _happy_transport():
    """Token, "Projekt is offen", Kostenposition created, its Nummer."""
    return _FakeTransport(
        _token(), _query_result({"Id": _PROJECT_ID}), _created(), _query_result({"Name": "PCI-00042"}),
    )


def _client(transport) -> sf.SalesforceClient:
    return sf.SalesforceClient(_creds(), opener=transport)


def _sent_cost_item(transport) -> dict:
    (create,) = [r for r in transport.requests if r.get_method() == "POST" and "/sobjects/" in r.full_url]
    return json.loads(create.data.decode("utf-8"))


def _confirmed(conn, log_id, **overrides) -> booking.ConfirmedBooking:
    proposal = booking.propose_booking(conn, log_id, _configuration())
    return replace(booking.ConfirmedBooking.from_proposal(proposal), **overrides)


# ---------- Buchungsvorschlag ----------

def test_proposal_takes_everything_from_entry_and_project(conn):
    log_id = _entry(conn, _project(conn))

    proposal = booking.propose_booking(conn, log_id, _configuration())

    assert proposal.log_id == log_id
    assert proposal.delivery_date == date(2026, 5, 8)   # local calendar day of the start
    assert proposal.project_name == "Acme · Rollout"
    assert proposal.quantity_hours == 1.5
    assert proposal.service_type == "Development"
    assert proposal.customer_request_type == "SOT-00348"
    assert proposal.description == "SOT-1: Flow gebaut"
    assert proposal.is_bookable and proposal.blocked_reason is None


def test_proposal_uses_my_global_default_while_the_project_has_no_service_type(conn):
    sf_settings.save_default_service_type(conn, "Development")
    log_id = _entry(conn, _project(conn, service_type=None, request_type=None))

    proposal = booking.propose_booking(conn, log_id, _configuration())

    assert proposal.service_type == "Development"
    assert proposal.customer_request_type == ""


def test_proposal_never_carries_a_salesforce_id(conn):
    log_id = _entry(conn, _project(conn))

    proposal = booking.propose_booking(conn, log_id, _configuration())

    assert _PROJECT_ID not in repr(proposal)
    assert _PERSON_ID not in repr(proposal)


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (dict(configuration=dict(secret=None)), booking.NOT_CONFIGURED),
        (dict(configuration=dict(person=False)), booking.NOT_CONFIGURED),
        (dict(project=dict(booking_system="jira")), booking.NOT_A_SALESFORCE_CUSTOMER),
        (dict(entry=dict(running=True)), booking.ENTRY_RUNNING),
        (dict(entry=dict(minutes=0)), booking.NO_DURATION),
        (dict(entry=dict(task=None, description="  ")), booking.NOTHING_TO_DESCRIBE),
        (dict(project=dict(registered=False)), booking.PROJECT_NOT_REGISTERED),
    ],
)
def test_every_reason_why_an_entry_is_not_bookable(conn, setup, code):
    log_id = _entry(conn, _project(conn, **setup.get("project", {})), **setup.get("entry", {}))
    configuration = _configuration(**setup.get("configuration", {}))

    proposal = booking.propose_booking(conn, log_id, configuration)

    assert not proposal.is_bookable
    assert proposal.blocked_reason
    assert booking.booking_block(conn, repo.get_log(conn, log_id), configuration).code == code
    with pytest.raises(booking.BookingRefusedError) as excinfo:
        booking.book_entry(conn, _client(_FakeTransport()), configuration,
                           booking.ConfirmedBooking.from_proposal(proposal))
    assert excinfo.value.code == code
    assert str(excinfo.value) == proposal.blocked_reason


def test_missing_configuration_says_what_is_missing(conn):
    log_id = _entry(conn, _project(conn))

    proposal = booking.propose_booking(conn, log_id, _configuration(person=False))

    assert "Leistende Person" in proposal.blocked_reason


def test_booked_entry_is_not_bookable(conn):
    log_id = _entry(conn, _project(conn))
    repo.set_log_external_ref(conn, log_id, worklog_id="a0Bold", worklog_number="PCI-1")

    block = booking.booking_block(conn, repo.get_log(conn, log_id), _configuration())

    assert block.code == booking.ALREADY_BOOKED


# ---------- Buchen ----------

def test_booking_creates_the_cost_item_in_the_name_of_my_leistende_person(conn):
    log_id = _entry(conn, _project(conn))
    transport = _happy_transport()

    booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id))

    sent = _sent_cost_item(transport)
    assert sent["Project__c"] == _PROJECT_ID
    assert sent["Person__c"] == _PERSON_ID
    assert sent["Quantity__c"] == 1.5
    assert sent["DeliveryDate__c"] == "2026-05-08"
    assert sent["Description__c"] == "SOT-1: Flow gebaut"
    assert sent["ServiceType__c"] == "Development"
    assert sent["CustomerRequestType__c"] == "SOT-00348"


def test_booking_writes_reference_number_link_and_time_to_the_entry(conn):
    log_id = _entry(conn, _project(conn))

    log = booking.book_entry(conn, _client(_happy_transport()), _configuration(), _confirmed(conn, log_id))

    assert log.is_booked
    assert log.external_worklog_id == _COST_ITEM_ID
    assert log.external_worklog_number == "PCI-00042"
    assert log.external_worklog_url.endswith(f"/{_COST_ITEM_ID}/view")
    assert log.external_synced_at is not None
    assert repo.get_log(conn, log_id) == log


def test_booking_sets_the_duration_to_the_booked_quantity(conn):
    log_id = _entry(conn, _project(conn))   # 1h10

    log = booking.book_entry(conn, _client(_happy_transport()), _configuration(), _confirmed(conn, log_id))

    assert log.duration_seconds == 90 * 60
    assert log.ended_at.isoformat() == "2026-05-09T01:00:00+02:00"   # Start + Dauer


def test_values_changed_in_the_dialog_apply_to_this_booking_only(conn):
    project = _project(conn)
    log_id = _entry(conn, project)
    transport = _happy_transport()
    confirmed = _confirmed(
        conn, log_id, quantity_hours=3.0, service_type="Consulting",
        customer_request_type="", description="Workshop",
    )

    log = booking.book_entry(conn, _client(transport), _configuration(), confirmed)

    sent = _sent_cost_item(transport)
    assert sent["Quantity__c"] == 3.0
    assert sent["ServiceType__c"] == "Consulting"
    assert sent["Description__c"] == "Workshop"
    assert "CustomerRequestType__c" not in sent
    assert log.duration_seconds == 3 * 3600
    # Neither the Projekt defaults nor the texts of the Eintrag change.
    assert (log.task, log.description) == ("SOT-1", "Flow gebaut")
    stored = repo.get_project(conn, project.id)
    assert (stored.default_service_type, stored.customer_request_type) == ("Development", "SOT-00348")


@pytest.mark.parametrize(
    "overrides",
    [dict(quantity_hours=0.0), dict(quantity_hours=1.25), dict(service_type="Support"), dict(description="  ")],
)
def test_invalid_confirmed_values_are_refused_without_asking_salesforce(conn, overrides):
    log_id = _entry(conn, _project(conn))
    transport = _FakeTransport()

    with pytest.raises(booking.BookingRefusedError) as excinfo:
        booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id, **overrides))

    assert excinfo.value.code == booking.INVALID_VALUES
    assert transport.requests == []


def test_already_booked_entry_is_refused_and_not_booked_twice(conn):
    log_id = _entry(conn, _project(conn))
    confirmed = _confirmed(conn, log_id)
    booking.book_entry(conn, _client(_happy_transport()), _configuration(), confirmed)
    transport = _FakeTransport()

    with pytest.raises(booking.BookingRefusedError) as excinfo:
        booking.book_entry(conn, _client(transport), _configuration(), confirmed)

    assert excinfo.value.code == booking.ALREADY_BOOKED
    assert transport.requests == []


def test_project_closed_in_salesforce_is_refused_before_anything_is_created(conn):
    log_id = _entry(conn, _project(conn))
    before = repo.get_log(conn, log_id)
    transport = _FakeTransport(_token(), _query_result())   # the Projekt is no longer offen

    with pytest.raises(booking.BookingRefusedError) as excinfo:
        booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id))

    assert excinfo.value.code == booking.PROJECT_CLOSED
    assert len(transport.requests) == 2
    assert repo.get_log(conn, log_id) == before


def test_error_of_the_org_leaves_the_entry_unchanged_and_carries_the_salesforce_text(conn):
    log_id = _entry(conn, _project(conn))
    before = repo.get_log(conn, log_id)
    transport = _FakeTransport(_token(), _query_result({"Id": _PROJECT_ID}), _http_error(400, [
        {"message": "Service Type passt nicht zum Projekt.", "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id))

    assert "Service Type passt nicht" in str(excinfo.value)
    after = repo.get_log(conn, log_id)
    assert after == before
    assert not after.is_booked


def test_network_error_leaves_the_entry_unbooked(conn):
    log_id = _entry(conn, _project(conn))
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError):
        booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id))

    assert not repo.get_log(conn, log_id).is_booked


def test_booking_without_a_readable_number_is_still_recorded(conn):
    log_id = _entry(conn, _project(conn))
    transport = _FakeTransport(
        _token(), _query_result({"Id": _PROJECT_ID}), _created(), urllib.error.URLError("weg"),
    )

    log = booking.book_entry(conn, _client(transport), _configuration(), _confirmed(conn, log_id))

    assert log.is_booked
    assert log.external_worklog_number is None


# ---------- Die drei Phasen (the dialog runs the middle one off the UI thread) ----------

def test_created_cost_item_is_not_lost_when_the_entry_cannot_be_saved(conn):
    log_id = _entry(conn, _project(conn))
    prepared = booking.prepare_booking(conn, _configuration(), _confirmed(conn, log_id))
    cost_item = booking.submit_booking(_client(_happy_transport()), prepared)
    conn.execute("DELETE FROM log_entry WHERE id = ?", (log_id,))   # gone in the meantime

    with pytest.raises(booking.BookingNotRecordedError) as excinfo:
        booking.record_booking(conn, prepared, cost_item)

    assert excinfo.value.cost_item == cost_item
    assert "PCI-00042" in str(excinfo.value)
    assert _COST_ITEM_ID not in str(excinfo.value)


def test_entry_booked_in_the_meantime_keeps_its_first_booking(conn):
    log_id = _entry(conn, _project(conn))
    prepared = booking.prepare_booking(conn, _configuration(), _confirmed(conn, log_id))
    cost_item = booking.submit_booking(_client(_happy_transport()), prepared)
    repo.set_log_external_ref(conn, log_id, worklog_id="a0Bfirst", worklog_number="PCI-00001")

    with pytest.raises(booking.BookingNotRecordedError):
        booking.record_booking(conn, prepared, cost_item)

    assert repo.get_log(conn, log_id).external_worklog_id == "a0Bfirst"


def test_prepared_booking_carries_what_the_client_needs(conn):
    log_id = _entry(conn, _project(conn))

    prepared = booking.prepare_booking(conn, _configuration(), _confirmed(conn, log_id))

    assert prepared.log_id == log_id
    assert prepared.draft.salesforce_project_id == _PROJECT_ID
    assert prepared.draft.person_id == _PERSON_ID
