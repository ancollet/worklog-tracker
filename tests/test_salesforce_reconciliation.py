"""Abgleich: registrierte Projekte, die in Salesforce geschlossen wurden, werden markiert.

Seam: the service layer over the in-memory database, with a real Salesforce client
over fake HTTP at the transport boundary.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from worklog import db as db_module
from worklog import repository as repo
from worklog.services import salesforce as sf
from worklog.services import salesforce_reconciliation as abgleich
from worklog.services import salesforce_registration as reg
from worklog.services.salesforce import SalesforceAccount, SalesforceProject
from worklog.services.timer import TimerService

ACME = SalesforceAccount(id="001AA000001AAAAIA2", name="Acme GmbH")
RELAUNCH = SalesforceProject(id="a0XAA000001AAAAIA2", name="Relaunch")
WARTUNG = SalesforceProject(id="a0XAA000001BBBBIA2", name="Wartung")

NOON = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeSalesforce:
    """Stand-in for urlopen: signs in and answers every query with the offenen Projekte among those asked for."""

    def __init__(self, open_ids=(), failure: Exception | None = None) -> None:
        self.open_ids = set(open_ids)
        self.failure = failure
        self.queries: list[str] = []

    def __call__(self, req, timeout=15):
        if req.full_url.endswith("/services/oauth2/token"):
            return _FakeResponse({"access_token": "tok"})
        if self.failure is not None:
            raise self.failure
        soql = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)["q"][0]
        self.queries.append(soql)
        records = [{"Id": i} for i in sorted(self.open_ids) if f"'{i}'" in soql or f"'{i[:15]}'" in soql]
        return _FakeResponse({"totalSize": len(records), "done": True, "records": records})


def _client(transport) -> sf.SalesforceClient:
    return sf.SalesforceClient(
        sf.SalesforceCredentials("https://acme.my.salesforce.com", "key", "secret"), opener=transport
    )


def _registered(conn, *salesforce_projects):
    customer = reg.register_account(conn, ACME)
    return reg.register_projects(
        conn, customer.id, [reg.ProjectRegistration(p, "Consulting") for p in salesforce_projects]
    )


def test_a_project_that_is_still_open_stays_unmarked_and_gets_the_time_of_the_check(conn):
    relaunch, = _registered(conn, RELAUNCH)

    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), at=NOON)

    project = repo.get_project(conn, relaunch.id)
    assert project.closed_in_salesforce is False
    assert project.salesforce_checked_at == NOON


def test_a_project_closed_in_salesforce_is_marked(conn):
    relaunch, wartung = _registered(conn, RELAUNCH, WARTUNG)

    result = abgleich.reconcile_registered_projects(
        conn, _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), at=NOON
    )

    assert repo.get_project(conn, relaunch.id).closed_in_salesforce is False
    closed = repo.get_project(conn, wartung.id)
    assert closed.closed_in_salesforce is True
    assert closed.salesforce_checked_at == NOON
    assert [p.name for p in result.closed] == ["Wartung"]
    assert sorted(p.name for p in result.checked) == ["Relaunch", "Wartung"]


def test_a_project_deleted_in_salesforce_is_marked_too(conn):
    # Salesforce does not tell "closed" from "gone": neither is among the offenen Projekte
    relaunch, = _registered(conn, RELAUNCH)

    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

    assert repo.get_project(conn, relaunch.id).closed_in_salesforce is True


def test_a_project_reopened_in_salesforce_loses_the_mark_with_the_next_check(conn):
    relaunch, = _registered(conn, RELAUNCH)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)
    later = NOON + timedelta(hours=3)

    result = abgleich.reconcile_registered_projects(
        conn, _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), at=later
    )

    project = repo.get_project(conn, relaunch.id)
    assert project.closed_in_salesforce is False
    assert project.salesforce_checked_at == later
    assert result.closed == []


def test_a_closed_project_is_not_archived_and_can_still_be_tracked_on(conn):
    relaunch, = _registered(conn, RELAUNCH)
    timer = TimerService(conn)
    before = timer.start_entry(project_id=relaunch.id, task="T", description="vorher")
    timer.stop_entry(before.id)

    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

    project = repo.get_project(conn, relaunch.id)
    assert project.closed_in_salesforce is True
    assert project.archived is False
    assert [p.id for p in repo.list_projects(conn)] == [relaunch.id]   # still offered for tracking
    assert (project.external_ref, project.default_service_type) == (RELAUNCH.id, "Consulting")
    assert repo.get_log(conn, before.id).description == "vorher"
    after = timer.start_entry(project_id=relaunch.id, task="T", description="nachher")
    assert repo.get_log(conn, after.id).project_id == relaunch.id


# ---------- Fehler: der letzte bekannte Stand bleibt stehen ----------


def _state(conn):
    return [(p.name, p.closed_in_salesforce, p.salesforce_checked_at, p.archived)
            for p in repo.list_projects(conn, include_archived=True)]


@pytest.mark.parametrize("failure, error", [
    (urllib.error.URLError("Network is unreachable"), sf.SalesforceNetworkError),
    (urllib.error.HTTPError("https://x", 400, "err", None, None), sf.SalesforceOrgError),
])
def test_when_salesforce_cannot_be_asked_nothing_changes(conn, failure, error):
    _registered(conn, RELAUNCH, WARTUNG)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), at=NOON)
    known = _state(conn)

    with pytest.raises(error):
        abgleich.reconcile_registered_projects(
            conn, _client(_FakeSalesforce(failure=failure)), at=NOON + timedelta(hours=1)
        )

    assert _state(conn) == known   # Wartung stays marked, Relaunch unmarked, both with the old time


def test_rejected_sign_in_changes_nothing_either(conn):
    _registered(conn, RELAUNCH)
    known = _state(conn)

    def rejecting(req, timeout=15):
        raise urllib.error.HTTPError("https://x", 400, "err", None, None)

    with pytest.raises(sf.SalesforceAuthError):
        abgleich.reconcile_registered_projects(conn, _client(rejecting), at=NOON)

    assert _state(conn) == known


# ---------- Wen der Abgleich betrifft ----------


def test_projects_outside_salesforce_are_neither_asked_about_nor_touched(conn):
    _registered(conn, RELAUNCH)
    jira = repo.create_customer(conn, "Jira-Kunde")
    repo.update_customer(conn, jira.id, name=jira.name, archived=False, booking_system="jira", external_ref="DIS")
    jira_project = repo.create_project(conn, customer_id=jira.id, name="Jira A", external_ref=WARTUNG.id)
    plain = repo.create_project(conn, customer_id=repo.create_customer(conn, "Ohne").id, name="Frei",
                                external_ref="irgendwas")
    unconnected = repo.create_project(conn, customer_id=reg.registered_customer(conn, ACME.id).id, name="Von Hand")
    transport = _FakeSalesforce(open_ids=[])

    result = abgleich.reconcile_registered_projects(conn, _client(transport), at=NOON)

    assert [p.name for p in result.checked] == ["Relaunch"]
    for untouched in (jira_project, plain, unconnected):
        project = repo.get_project(conn, untouched.id)
        assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, None)
    assert len(transport.queries) == 1
    assert WARTUNG.id not in transport.queries[0] and "irgendwas" not in transport.queries[0]


def test_without_registered_projects_salesforce_is_not_asked_at_all(conn):
    repo.create_project(conn, customer_id=repo.create_customer(conn, "Ohne").id, name="Frei")
    calls = []

    result = abgleich.reconcile_registered_projects(conn, _client(lambda req, timeout=15: calls.append(req)))

    assert result.checked == [] and calls == []


def test_archived_registered_projects_are_checked_too(conn):
    relaunch, = _registered(conn, RELAUNCH)
    repo.update_project(conn, relaunch.id, name=relaunch.name, color=None, round_minutes=None,
                        archived=True, external_ref=relaunch.external_ref)

    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

    project = repo.get_project(conn, relaunch.id)
    assert (project.closed_in_salesforce, project.archived) == (True, True)


def test_a_hand_typed_15_character_reference_is_checked_like_the_full_id(conn):
    customer = reg.register_account(conn, ACME)
    typed = repo.create_project(conn, customer_id=customer.id, name="Getippt", external_ref=RELAUNCH.id[:15])

    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), at=NOON)

    project = repo.get_project(conn, typed.id)
    assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, NOON)


def test_the_check_can_be_limited_to_some_projects_for_booking(conn):
    relaunch, wartung = _registered(conn, RELAUNCH, WARTUNG)
    transport = _FakeSalesforce(open_ids=[])

    result = abgleich.reconcile_registered_projects(
        conn, _client(transport), project_ids=[wartung.id], at=NOON
    )

    assert [p.name for p in result.closed] == ["Wartung"]
    assert RELAUNCH.id not in transport.queries[0]
    assert repo.get_project(conn, relaunch.id).salesforce_checked_at is None


# ---------- Zwei Hälften: Netz im Hintergrund, Datenbank im UI-Thread ----------


def test_the_network_half_needs_no_database_and_the_database_half_no_network(conn):
    relaunch, wartung = _registered(conn, RELAUNCH, WARTUNG)
    asked = abgleich.salesforce_project_ids(conn)

    check = abgleich.check_open_projects(_client(_FakeSalesforce(open_ids=[WARTUNG.id])), asked)
    result = abgleich.record_open_projects_check(conn, check, at=NOON)

    assert sorted(asked) == [RELAUNCH.id, WARTUNG.id]
    assert [p.name for p in result.closed] == ["Relaunch"]
    assert result.at == NOON


def test_a_project_connected_while_the_check_was_running_is_left_alone(conn):
    relaunch, = _registered(conn, RELAUNCH)
    check = abgleich.check_open_projects(
        _client(_FakeSalesforce(open_ids=[RELAUNCH.id])), abgleich.salesforce_project_ids(conn)
    )
    late, = reg.register_projects(
        conn, relaunch.customer_id, [reg.ProjectRegistration(WARTUNG, "Consulting")]
    )

    abgleich.record_open_projects_check(conn, check, at=NOON)

    project = repo.get_project(conn, late.id)   # Salesforce said nothing about it: not "geschlossen"
    assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, None)


def test_connecting_a_closed_project_to_another_salesforce_project_removes_the_mark(conn):
    relaunch, = _registered(conn, RELAUNCH)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

    reg.connect_project(conn, relaunch.id, WARTUNG)   # only offene Salesforce-Projekte can be chosen

    project = repo.get_project(conn, relaunch.id)
    assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, None)


def test_connecting_the_same_salesforce_project_again_keeps_what_the_check_said(conn):
    relaunch, = _registered(conn, RELAUNCH)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

    reg.connect_project(conn, relaunch.id, RELAUNCH)

    project = repo.get_project(conn, relaunch.id)
    assert (project.closed_in_salesforce, project.salesforce_checked_at) == (True, NOON)


# ---------- Migration (Schritt 9) ----------


def _legacy_v8_db(path) -> None:
    """A database as version 8 left it: registrierte Projekte, but nothing about an Abgleich."""
    raw = sqlite3.connect(str(path))
    raw.row_factory = sqlite3.Row
    raw.executescript(db_module.INITIAL_SCHEMA)
    raw.execute("INSERT INTO schema_version(version) VALUES (8)")
    raw.execute("INSERT INTO app_state(id, default_round_minutes) VALUES (1, 15)")
    raw.executescript(db_module.SNIPPET_SCHEMA)
    db_module._migrate_to_7_salesforce_account(raw)
    db_module._migrate_to_8_salesforce_projects(raw)
    now = datetime.now(timezone.utc).isoformat()
    raw.execute(
        "INSERT INTO customer(id, name, booking_system, external_ref, created_at) VALUES (1, 'Acme', 'salesforce', ?, ?)",
        (ACME.id, now),
    )
    raw.execute(
        "INSERT INTO project(id, customer_id, name, external_ref, external_name, default_service_type, created_at) "
        "VALUES (1, 1, 'Relaunch', ?, 'Relaunch', 'Development', ?)",
        (RELAUNCH.id, now),
    )
    raw.execute(
        "INSERT INTO log_entry(project_id, started_at, created_at, updated_at) VALUES (1, ?, ?, ?)", (now, now, now)
    )
    raw.commit()
    raw.close()


def test_migration_from_v8_adds_the_mark_and_the_time_of_the_check_without_marking_anything(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v8_db(db_file)

    conn = db_module.connect(str(db_file))
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db_module.SCHEMA_VERSION
        assert db_module.SCHEMA_VERSION >= 9
        project = repo.get_project(conn, 1)
        assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, None)
        assert (project.external_ref, project.default_service_type) == (RELAUNCH.id, "Development")
        assert conn.execute("SELECT COUNT(*) AS n FROM log_entry WHERE project_id = 1").fetchone()["n"] == 1

        abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)
        assert repo.get_project(conn, 1).closed_in_salesforce is True
    finally:
        conn.close()


def test_migration_step_9_is_harmless_when_run_again(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v8_db(db_file)
    conn = db_module.connect(str(db_file))
    try:
        abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)

        db_module._migrate_to_9_salesforce_closed_projects(conn)

        project = repo.get_project(conn, 1)
        assert (project.closed_in_salesforce, project.salesforce_checked_at) == (True, NOON)
    finally:
        conn.close()


def test_a_fresh_database_knows_the_mark_too(conn):
    project = repo.create_project(conn, customer_id=repo.create_customer(conn, "Neu").id, name="P")

    assert (project.closed_in_salesforce, project.salesforce_checked_at) == (False, None)


# ---------- Was der Kunden-Tab zeigt ----------


def test_a_closed_project_gets_a_marker_and_a_tooltip_with_the_time_of_the_check(conn):
    relaunch, wartung = _registered(conn, RELAUNCH, WARTUNG)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[WARTUNG.id])), at=NOON)

    closed, still_open = repo.get_project(conn, relaunch.id), repo.get_project(conn, wartung.id)

    assert abgleich.closed_marker(closed) == "in Salesforce geschlossen"
    tooltip = abgleich.closed_tooltip(closed)
    assert "geschlossen" in tooltip and "20.09.2026" in tooltip
    assert RELAUNCH.id not in tooltip and RELAUNCH.id[:15] not in tooltip   # never a Salesforce ID
    assert abgleich.closed_marker(still_open) == "" and abgleich.closed_tooltip(still_open) == ""


def test_the_marker_disappears_when_the_customer_leaves_salesforce(conn):
    relaunch, = _registered(conn, RELAUNCH)
    abgleich.reconcile_registered_projects(conn, _client(_FakeSalesforce(open_ids=[])), at=NOON)
    customer = repo.get_customer(conn, relaunch.customer_id)

    repo.update_customer(conn, customer.id, name=customer.name, archived=False, booking_system=None,
                         external_ref=None)

    assert abgleich.closed_marker(repo.get_project(conn, relaunch.id)) == ""


# ---------- Nicht häufiger als nötig ----------


def test_the_check_is_due_at_first_and_then_only_after_the_interval():
    assert abgleich.is_reconciliation_due(None, NOON) is True
    assert abgleich.is_reconciliation_due(NOON, NOON + timedelta(seconds=5)) is False
    assert abgleich.is_reconciliation_due(NOON, NOON + abgleich.RECONCILIATION_INTERVAL) is True
