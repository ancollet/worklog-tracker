"""Salesforce client: Kostenposition löschen (Stornieren) — deleted, not found, not Open, refused."""
from __future__ import annotations

import urllib.error

import pytest

from tests.test_salesforce_client import (
    _FakeTransport,
    _creds,
    _headers,
    _http_error,
    _query_result,
    _soql,
    _token,
)
from worklog.services import salesforce as sf

_COST_ITEM_ID = "a0BAA000000cost1AA"
_RECORD_URL = (
    f"https://acme.my.salesforce.com/services/data/{sf.API_VERSION}/sobjects/ProjectCostItem__c/{_COST_ITEM_ID}"
)


class _NoContent:
    """HTTP 204: what Salesforce answers to a successful DELETE — no body at all."""

    status = 204

    def read(self) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _status(value: str = "Open"):
    return _query_result({"Id": _COST_ITEM_ID, "Status__c": value})


def test_open_cost_item_is_deleted_with_a_delete_request_on_its_record():
    transport = _FakeTransport(_token(), _status("Open"), _NoContent())

    sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    check, delete = transport.requests[1:]
    soql = _soql(check)
    assert "FROM ProjectCostItem__c" in soql and "Status__c" in soql
    assert f"Id = '{_COST_ITEM_ID}'" in soql
    assert delete.get_method() == "DELETE"
    assert delete.full_url == _RECORD_URL
    assert delete.data is None
    assert _headers(delete)["authorization"] == "Bearer tok-1"


def test_cost_item_that_is_no_longer_open_is_not_deleted():
    transport = _FakeTransport(_token(), _status("Invoiced"))

    with pytest.raises(sf.CostItemNotOpenError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert [r.get_method() for r in transport.requests] == ["POST", "GET"]   # no DELETE was sent
    assert excinfo.value.status == "Invoiced"
    assert "Invoiced" in str(excinfo.value) and "Open" in str(excinfo.value)
    assert _COST_ITEM_ID not in str(excinfo.value)
    assert isinstance(excinfo.value, sf.SalesforceError)


def test_cost_item_that_no_longer_exists_is_reported_as_not_found():
    transport = _FakeTransport(_token(), _query_result())

    with pytest.raises(sf.CostItemNotFoundError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert [r.get_method() for r in transport.requests] == ["POST", "GET"]   # nothing to delete
    assert _COST_ITEM_ID not in str(excinfo.value)


@pytest.mark.parametrize("error_code", ["ENTITY_IS_DELETED", "NOT_FOUND"])
def test_cost_item_deleted_between_check_and_delete_is_reported_as_not_found(error_code):
    gone = _http_error(404, [{"message": "entity is deleted", "errorCode": error_code}])
    transport = _FakeTransport(_token(), _status("Open"), gone)

    with pytest.raises(sf.CostItemNotFoundError):
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)


@pytest.mark.parametrize("code, payload", [
    (400, [{"message": "Abgerechnete Kostenpositionen dürfen nicht gelöscht werden.",
            "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION"}]),
    (403, [{"message": "insufficient access rights on object id",
            "errorCode": "INSUFFICIENT_ACCESS_OR_READONLY"}]),
])
def test_refusal_of_the_org_is_raised_with_the_salesforce_text(code, payload):
    transport = _FakeTransport(_token(), _status("Open"), _http_error(code, payload))

    with pytest.raises(sf.CostItemDeleteRefusedError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert payload[0]["message"] in str(excinfo.value)
    assert "nicht gelöscht" in str(excinfo.value)
    assert isinstance(excinfo.value, sf.SalesforceOrgError)
    assert not isinstance(excinfo.value, sf.CostItemNotFoundError)


_SESSION_EXPIRED = [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}]


def test_expired_token_is_renewed_once_and_the_delete_repeated():
    transport = _FakeTransport(
        _token("old"), _status("Open"), _http_error(401, _SESSION_EXPIRED),
        _token("new"), _NoContent(),
    )

    sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert len(transport.token_requests()) == 2
    first, second = [r for r in transport.requests if r.get_method() == "DELETE"]
    assert first.full_url == second.full_url == _RECORD_URL
    assert _headers(second)["authorization"] == "Bearer new"


def test_token_that_stays_invalid_is_an_auth_error_after_exactly_one_renewal():
    transport = _FakeTransport(
        _token("old"), _status("Open"), _http_error(401, _SESSION_EXPIRED),
        _token("new"), _http_error(401, _SESSION_EXPIRED),
    )

    with pytest.raises(sf.SalesforceAuthError):
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert len(transport.token_requests()) == 2
    assert transport.answers == []


def test_network_error_while_deleting_raises_network_error():
    transport = _FakeTransport(_token(), _status("Open"), urllib.error.URLError("no route to host"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)


def test_error_of_the_status_check_means_nothing_is_deleted():
    wrong_field = _http_error(400, [{"message": "No such column 'Status__c'", "errorCode": "INVALID_FIELD"}])
    transport = _FakeTransport(_token(), wrong_field)

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert not isinstance(excinfo.value, (sf.CostItemNotFoundError, sf.CostItemDeleteRefusedError))
    assert [r.get_method() for r in transport.requests] == ["POST", "GET"]


@pytest.mark.parametrize("reference", ["10042", "", "a0B' OR Name != '"])
def test_reference_that_is_no_salesforce_id_is_not_found_without_asking_salesforce(reference):
    transport = _FakeTransport()

    with pytest.raises(sf.CostItemNotFoundError):
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(reference)

    assert transport.requests == []


def test_salesforce_outage_while_deleting_is_not_a_refusal():
    transport = _FakeTransport(_token(), _status("Open"), _http_error(503))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).delete_cost_item(_COST_ITEM_ID)

    assert not isinstance(excinfo.value, sf.CostItemDeleteRefusedError)
