"""Salesforce client: Kostenposition anlegen, and "is this Salesforce-Projekt still offen?"."""
from __future__ import annotations

import json
import urllib.error
from datetime import date

import pytest

from tests.test_salesforce_client import (
    _FakeResponse,
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


def _draft(**overrides) -> sf.CostItemDraft:
    values = dict(
        salesforce_project_id="a01AA000000proj1AA",
        person_id="005AA000000pers1AA",
        quantity_hours=1.5,
        delivery_date=date(2026, 5, 8),
        description="SOT-1: Flow gebaut",
        service_type="Consulting",
    )
    values.update(overrides)
    return sf.CostItemDraft(**values)


def _created(record_id: str = _COST_ITEM_ID):
    return _FakeResponse({"id": record_id, "success": True, "errors": []}, status=201)


def _payload(req) -> dict:
    return json.loads(req.data.decode("utf-8"))


def test_create_cost_item_returns_id_number_and_link():
    transport = _FakeTransport(_token(), _created(), _query_result({"Id": _COST_ITEM_ID, "Name": "PCI-00042"}))

    item = sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    assert item.id == _COST_ITEM_ID
    assert item.number == "PCI-00042"
    assert item.url == (
        f"https://acme.my.salesforce.com/lightning/r/ProjectCostItem__c/{_COST_ITEM_ID}/view"
    )


def test_cost_item_payload_carries_the_draft_and_the_fixed_values():
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    create = transport.requests[1]
    assert create.get_method() == "POST"
    assert create.full_url == (
        f"https://acme.my.salesforce.com/services/data/{sf.API_VERSION}/sobjects/ProjectCostItem__c"
    )
    assert _headers(create)["content-type"] == "application/json"
    assert _headers(create)["authorization"] == "Bearer tok-1"
    assert _payload(create) == {
        "Project__c": "a01AA000000proj1AA",
        "Person__c": "005AA000000pers1AA",
        "Quantity__c": 1.5,
        "DeliveryDate__c": "2026-05-08",
        "Description__c": "SOT-1: Flow gebaut",
        "ServiceType__c": "Consulting",
        "Status__c": "Open",
        "SkillLevel__c": "Standard",
        "Location__c": "Remote",
        "CountAgainstBudget__c": True,
    }


def test_cost_item_payload_never_carries_price_or_calculated_fields():
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    sent = " ".join(_payload(transport.requests[1])).lower()
    for forbidden in ("rate", "price", "amount", "total", "tagessatz"):
        assert forbidden not in sent


def test_customer_request_type_is_sent_only_when_set():
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(
        _draft(customer_request_type=" SOT-00348 ")
    )

    assert _payload(transport.requests[1])["CustomerRequestType__c"] == "SOT-00348"


def test_blank_customer_request_type_is_not_sent():
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft(customer_request_type="  "))

    assert "CustomerRequestType__c" not in _payload(transport.requests[1])


def test_service_type_is_mapped_to_the_picklist_value_of_the_org(monkeypatch):
    monkeypatch.setitem(sf.COST_ITEM_SERVICE_TYPE_VALUES, "Development", "DEV")
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft(service_type="Development"))

    assert _payload(transport.requests[1])["ServiceType__c"] == "DEV"


def test_unknown_service_type_is_refused_without_asking_salesforce():
    transport = _FakeTransport()

    with pytest.raises(sf.SalesforceError):
        sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft(service_type="Support"))

    assert transport.requests == []


def test_number_is_read_from_the_created_cost_item():
    transport = _FakeTransport(_token(), _created(), _query_result({"Name": "PCI-1"}))

    sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    soql = _soql(transport.requests[2])
    assert "SELECT Id, Name FROM ProjectCostItem__c" in soql
    assert f"WHERE Id = '{_COST_ITEM_ID}'" in soql


def test_cost_item_stays_created_when_its_number_cannot_be_read():
    transport = _FakeTransport(_token(), _created(), urllib.error.URLError("Network is unreachable"))

    item = sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    assert item.id == _COST_ITEM_ID
    assert item.number == ""


def test_validation_rule_of_the_org_is_raised_with_the_salesforce_text():
    transport = _FakeTransport(_token(), _http_error(400, [{
        "message": "Delivery Date darf nicht in einem abgeschlossenen Monat liegen.",
        "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION",
        "fields": ["DeliveryDate__c"],
    }]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    assert "abgeschlossenen Monat" in str(excinfo.value)
    assert len(transport.requests) == 2   # no attempt to read a number


def test_network_error_while_creating_raises_network_error():
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())


def test_create_answer_without_id_is_a_readable_error():
    transport = _FakeTransport(_token(), _FakeResponse({"success": False, "errors": []}))

    with pytest.raises(sf.SalesforceError):
        sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())


def test_expired_token_is_renewed_once_and_the_create_repeated_with_its_payload():
    transport = _FakeTransport(
        _token("old"), _http_error(401, [{"message": "Session expired", "errorCode": "INVALID_SESSION_ID"}]),
        _token("new"), _created(), _query_result({"Name": "PCI-1"}),
    )

    item = sf.SalesforceClient(_creds(), opener=transport).create_cost_item(_draft())

    assert item.number == "PCI-1"
    assert _payload(transport.requests[3]) == _payload(transport.requests[1])
    assert _headers(transport.requests[3])["authorization"] == "Bearer new"


# ---------- Ist das Salesforce-Projekt noch offen? ----------

def test_open_project_is_reported_as_open():
    transport = _FakeTransport(_token(), _query_result({"Id": "a01AA000000proj1AA"}))

    assert sf.SalesforceClient(_creds(), opener=transport).is_project_open("a01AA000000proj1AA") is True

    soql = _soql(transport.requests[1])
    assert "FROM Project__c" in soql
    assert "Id = 'a01AA000000proj1AA'" in soql
    assert "Status__c IN ('Open')" in soql


def test_closed_or_deleted_project_is_reported_as_not_open():
    transport = _FakeTransport(_token(), _query_result())

    assert sf.SalesforceClient(_creds(), opener=transport).is_project_open("a01AA000000proj1AA") is False


def test_project_id_cannot_break_out_of_the_string_literal():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).is_project_open("x' OR Id != '")

    assert "Id = 'x\\' OR Id != \\''" in _soql(transport.requests[1])
