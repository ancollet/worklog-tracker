"""What the column "Gebucht" shows — never a Salesforce ID."""
from __future__ import annotations

from datetime import datetime, timezone

from worklog.models import LogEntry
from worklog.services.booking import booked_cell_text, booked_cell_tooltip, cancel_booking_hint

_SF_ID = "a0BAA000000cost1AA"
_SF_URL = f"https://acme.my.salesforce.com/lightning/r/ProjectCostItem__c/{_SF_ID}/view"


def _entry(*, system=None, worklog_id=None, number=None, url=None) -> LogEntry:
    t = datetime(2026, 5, 8, 10, tzinfo=timezone.utc)
    return LogEntry(
        id=1, project_id=1, task="T", description="x", started_at=t, ended_at=t,
        duration_seconds=900, rounded_to_minutes=15, customer_booking_system=system,
        external_worklog_id=worklog_id, external_worklog_number=number, external_worklog_url=url,
    )


def test_salesforce_booking_shows_the_number_of_the_cost_item():
    log = _entry(system="salesforce", worklog_id=_SF_ID, number="PCI-00042", url=_SF_URL)
    assert booked_cell_text(log) == "✓ PCI-00042"


def test_salesforce_booking_without_a_number_shows_no_id():
    log = _entry(system="salesforce", worklog_id=_SF_ID, url=_SF_URL)
    assert booked_cell_text(log) == "✓ gebucht"


def test_salesforce_tooltip_leads_to_the_record_without_showing_the_id():
    log = _entry(system="salesforce", worklog_id=_SF_ID, number="PCI-00042", url=_SF_URL)
    tooltip = booked_cell_tooltip(log)
    assert "PCI-00042" in tooltip
    assert "Salesforce" in tooltip
    assert _SF_ID not in tooltip


def test_jira_booking_shows_worklog_id_and_link_as_before():
    log = _entry(system="jira", worklog_id="10001", url="https://acme.atlassian.net/browse/DIS-1")
    assert booked_cell_text(log) == "✓ 10001"
    assert booked_cell_tooltip(log) == "https://acme.atlassian.net/browse/DIS-1"


def test_unbooked_entries_of_customers_with_a_booking_system_show_a_dash():
    assert booked_cell_text(_entry(system="jira")) == "—"
    assert booked_cell_text(_entry(system="salesforce")) == "—"
    assert booked_cell_text(_entry()) == ""
    assert booked_cell_tooltip(_entry(system="salesforce")) == ""


def test_cancel_hint_of_a_salesforce_booking_names_the_number_and_says_it_is_deleted():
    hint = cancel_booking_hint(_entry(system="salesforce", worklog_id=_SF_ID, number="PCI-00042", url=_SF_URL))
    assert "Jira" not in hint
    assert "Kostenposition PCI-00042 wird in Salesforce gelöscht" in hint
    assert _SF_ID not in hint


def test_cancel_hint_of_a_salesforce_booking_without_a_number_shows_no_id():
    hint = cancel_booking_hint(_entry(system="salesforce", worklog_id=_SF_ID, url=_SF_URL))
    assert "Die Kostenposition wird in Salesforce gelöscht" in hint
    assert _SF_ID not in hint
