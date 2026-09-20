from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from worklog import db as db_module
from worklog import repository as repo
from worklog.services import salesforce_registration as reg
from worklog.services.salesforce import SalesforceAccount

ACME = SalesforceAccount(id="001AA000001AAAAIA2", name="Acme GmbH")
BETA = SalesforceAccount(id="001AA000001BBBBIA2", name="Beta AG")


# ---------- Datenebene: eine Account-ID hängt nur an einem Kunden ----------


def test_an_account_id_can_only_hang_on_one_customer(conn):
    repo.create_customer(conn, "Acme", booking_system="salesforce", external_ref=ACME.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.create_customer(conn, "Acme zwei", booking_system="salesforce", external_ref=ACME.id)


def test_empty_account_ids_and_jira_keys_may_repeat(conn):
    repo.create_customer(conn, "SF ohne Account 1", booking_system="salesforce")
    repo.create_customer(conn, "SF ohne Account 2", booking_system="salesforce")
    repo.create_customer(conn, "SF leer 1", booking_system="salesforce", external_ref="")
    repo.create_customer(conn, "SF leer 2", booking_system="salesforce", external_ref="")
    repo.create_customer(conn, "Jira 1", booking_system="jira", external_ref="DIS")
    repo.create_customer(conn, "Jira 2", booking_system="jira", external_ref="DIS")

    assert len(repo.list_customers(conn)) == 6


# ---------- Registrieren ----------


def test_registering_an_account_creates_a_salesforce_customer(conn):
    customer = reg.register_account(conn, ACME)

    stored = repo.get_customer(conn, customer.id)
    assert stored.name == "Acme GmbH"
    assert stored.booking_system == "salesforce"
    assert stored.external_ref == ACME.id
    assert stored.external_name == "Acme GmbH"
    assert stored.archived is False


def test_registering_the_same_account_twice_is_refused(conn):
    first = reg.register_account(conn, ACME)
    repo.update_customer(conn, first.id, name="Acme (umbenannt)", archived=False,
                         booking_system="salesforce", external_ref=ACME.id)

    with pytest.raises(reg.AccountAlreadyRegisteredError) as excinfo:
        reg.register_account(conn, ACME)

    assert "Acme (umbenannt)" in str(excinfo.value)
    assert ACME.id not in str(excinfo.value)
    assert [c.name for c in repo.list_customers(conn)] == ["Acme (umbenannt)"]


def test_a_hand_typed_15_character_id_counts_as_the_same_account(conn):
    repo.create_customer(conn, "Acme von Hand", booking_system="salesforce", external_ref=ACME.id[:15])

    with pytest.raises(reg.AccountAlreadyRegisteredError):
        reg.register_account(conn, ACME)


def test_registering_is_refused_when_a_customer_with_that_name_exists(conn):
    repo.create_customer(conn, "Acme GmbH")

    with pytest.raises(reg.CustomerNameTakenError) as excinfo:
        reg.register_account(conn, ACME)

    assert "Acme GmbH" in str(excinfo.value)
    assert "Verbinden" in str(excinfo.value)
    only = repo.list_customers(conn)
    assert len(only) == 1 and only[0].external_ref is None


def test_account_choices_mark_registered_accounts(conn):
    customer = reg.register_account(conn, ACME)
    repo.update_customer(conn, customer.id, name="Acme intern", archived=True,
                         booking_system="salesforce", external_ref=ACME.id)

    acme, beta = reg.account_choices(conn, [ACME, BETA])

    assert acme.account == ACME
    assert acme.is_registered
    assert acme.registered_as == "Acme intern (archiviert)"
    assert beta.account == BETA
    assert not beta.is_registered
    assert beta.registered_as == ""


# ---------- Bestehenden Kunden verbinden ----------


def _customer_with_history(conn, name="Acme von Hand", **kwargs):
    customer = repo.create_customer(conn, name, **kwargs)
    project = repo.create_project(conn, customer_id=customer.id, name="Wartung")
    start = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    log_id = repo.create_log(conn, project_id=project.id, task="T-1", description="Analyse",
                             started_at=start.isoformat(), ended_at=start.replace(hour=10).isoformat(),
                             duration_seconds=3600, rounded_to_minutes=None, is_manual=True)
    return customer, project, repo.get_log(conn, log_id)


def test_connecting_an_existing_customer_keeps_projects_and_entries(conn):
    customer, project, log = _customer_with_history(conn)

    reg.connect_customer(conn, customer.id, ACME)

    stored = repo.get_customer(conn, customer.id)
    assert stored.name == "Acme von Hand"            # the name I chose stays
    assert stored.booking_system == "salesforce"
    assert stored.external_ref == ACME.id
    assert stored.external_name == "Acme GmbH"
    assert [p.id for p in repo.list_projects(conn)] == [project.id]
    assert repo.get_project(conn, project.id).customer_booking_system == "salesforce"
    kept = repo.get_log(conn, log.id)
    assert (kept.project_id, kept.task, kept.description, kept.duration_seconds) == (
        project.id, "T-1", "Analyse", 3600)


def test_connecting_turns_a_jira_customer_into_a_salesforce_customer(conn):
    customer, _project, _log = _customer_with_history(conn, booking_system="jira", external_ref="DIS")

    reg.connect_customer(conn, customer.id, ACME)

    stored = repo.get_customer(conn, customer.id)
    assert (stored.booking_system, stored.external_ref) == ("salesforce", ACME.id)


def test_connecting_is_refused_when_the_account_hangs_on_another_customer(conn):
    reg.register_account(conn, ACME)
    other = repo.create_customer(conn, "Anderer Kunde")

    with pytest.raises(reg.AccountAlreadyRegisteredError) as excinfo:
        reg.connect_customer(conn, other.id, ACME)

    assert "Acme GmbH" in str(excinfo.value)
    assert repo.get_customer(conn, other.id).external_ref is None
    assert repo.get_customer(conn, other.id).booking_system is None


def test_changing_the_account_of_a_customer_to_another_one(conn):
    customer = reg.register_account(conn, ACME)

    reg.connect_customer(conn, customer.id, BETA)

    stored = repo.get_customer(conn, customer.id)
    assert (stored.external_ref, stored.external_name) == (BETA.id, "Beta AG")
    assert stored.name == "Acme GmbH"
    # Acme is free again
    assert not reg.account_choices(conn, [ACME])[0].is_registered


def test_connecting_the_account_a_customer_already_has_is_fine(conn):
    customer = reg.register_account(conn, ACME)

    reg.connect_customer(conn, customer.id, ACME)

    assert repo.get_customer(conn, customer.id).external_ref == ACME.id


def test_connecting_an_unknown_customer_is_refused(conn):
    with pytest.raises(reg.RegistrationError):
        reg.connect_customer(conn, 4711, ACME)


# ---------- Was die UI zeigt und speichert: nie die Account-ID ----------


def test_external_reference_shown_for_a_customer_never_contains_the_account_id(conn):
    registered = reg.register_account(conn, ACME)
    by_hand = repo.create_customer(conn, "Von Hand", booking_system="salesforce", external_ref=BETA.id)
    unconnected = repo.create_customer(conn, "Ohne Account", booking_system="salesforce")
    jira = repo.create_customer(conn, "Jira", booking_system="jira", external_ref="DIS")
    plain = repo.create_customer(conn, "Ohne System")

    assert reg.external_reference_text(registered) == "Acme GmbH"
    assert reg.external_reference_text(by_hand) == "Account verbunden"
    assert reg.external_reference_text(unconnected) == ""
    assert reg.external_reference_text(jira) == "DIS"          # Jira stays as it is today
    assert reg.external_reference_text(plain) == ""


def test_saving_customer_details_keeps_the_account_of_a_salesforce_customer(conn):
    customer = reg.register_account(conn, ACME)

    # whatever is left in the (hidden) free text field must not replace the Account
    assert reg.external_ref_to_save(customer, "salesforce", "irgendwas") == ACME.id


def test_saving_customer_details_for_other_systems_takes_the_typed_reference(conn):
    jira = repo.create_customer(conn, "Jira", booking_system="jira", external_ref="DIS")

    assert reg.external_ref_to_save(jira, "jira", " ABC ") == "ABC"
    assert reg.external_ref_to_save(jira, "jira", "  ") is None
    assert reg.external_ref_to_save(jira, None, "ABC") == "ABC"


def test_switching_a_customer_to_salesforce_by_hand_does_not_turn_its_old_reference_into_an_account(conn):
    jira = repo.create_customer(conn, "Jira", booking_system="jira", external_ref="DIS")

    assert reg.external_ref_to_save(jira, "salesforce", "DIS") is None


def test_text_field_of_a_salesforce_customer_starts_empty_so_the_id_cannot_leak(conn):
    customer = reg.register_account(conn, ACME)
    jira = repo.create_customer(conn, "Jira", booking_system="jira", external_ref="DIS")

    assert reg.external_ref_field_text(customer) == ""
    assert reg.external_ref_field_text(jira) == "DIS"
    # switched to Jira in the details: what I type then is taken
    assert reg.external_ref_to_save(customer, "jira", "DIS") == "DIS"


def _legacy_v5_db(path) -> None:
    """A database as version 5 left it: no uniqueness, no account name."""
    raw = sqlite3.connect(str(path))
    raw.executescript(db_module.INITIAL_SCHEMA)
    raw.execute("INSERT INTO schema_version(version) VALUES (5)")
    raw.execute("INSERT INTO app_state(id, default_round_minutes) VALUES (1, 15)")
    now = datetime.now(timezone.utc).isoformat()
    raw.executemany(
        "INSERT INTO customer(id, name, booking_system, external_ref, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Acme", "salesforce", ACME.id, now),
            (2, "Acme Duplikat", "salesforce", ACME.id, now),
            (3, "Beta", "salesforce", BETA.id, now),
            (4, "Jira 1", "jira", "DIS", now),
            (5, "Jira 2", "jira", "DIS", now),
        ],
    )
    raw.execute("INSERT INTO project(id, customer_id, name, created_at) VALUES (1, 2, 'Altprojekt', ?)", (now,))
    raw.commit()
    raw.close()


def test_migration_from_v5_enforces_uniqueness_and_keeps_every_customer(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v5_db(db_file)

    conn = db_module.connect(str(db_file))
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 7
        assert db_module.SCHEMA_VERSION >= 7

        by_name = {c.name: c for c in repo.list_customers(conn)}
        assert set(by_name) == {"Acme", "Acme Duplikat", "Beta", "Jira 1", "Jira 2"}
        # the first customer keeps the Account; the duplicate stays, but without it
        assert by_name["Acme"].external_ref == ACME.id
        assert by_name["Acme Duplikat"].external_ref is None
        assert by_name["Acme Duplikat"].booking_system == "salesforce"
        assert by_name["Beta"].external_ref == BETA.id
        assert by_name["Jira 1"].external_ref == by_name["Jira 2"].external_ref == "DIS"
        assert [p.name for p in repo.list_projects(conn)] == ["Altprojekt"]

        with pytest.raises(sqlite3.IntegrityError):
            repo.create_customer(conn, "Beta zwei", booking_system="salesforce", external_ref=BETA.id)
    finally:
        conn.close()


def test_migration_step_is_harmless_when_run_again(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v5_db(db_file)
    db_module.connect(str(db_file)).close()

    conn = db_module.connect(str(db_file))
    try:
        db_module._migrate_to_7_salesforce_account(conn)
        assert len(repo.list_customers(conn)) == 5
    finally:
        conn.close()
