from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from worklog import db as db_module
from worklog import repository as repo
from worklog.services import salesforce_registration as reg
from worklog.services import salesforce_settings as sfs
from worklog.services.salesforce import SalesforceAccount, SalesforceProject

ACME = SalesforceAccount(id="001AA000001AAAAIA2", name="Acme GmbH")
BETA = SalesforceAccount(id="001AA000001BBBBIA2", name="Beta AG")
RELAUNCH = SalesforceProject(id="a0XAA000001AAAAIA2", name="Relaunch")
WARTUNG = SalesforceProject(id="a0XAA000001BBBBIA2", name="Wartung")


# ---------- Datenebene: eine Salesforce-Projekt-ID hängt nur an einem Projekt ----------


def test_a_salesforce_project_id_can_only_hang_on_one_project(conn):
    acme = reg.register_account(conn, ACME)
    beta = reg.register_account(conn, BETA)
    repo.create_project(conn, customer_id=acme.id, name="Relaunch", external_ref=RELAUNCH.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.create_project(conn, customer_id=acme.id, name="Relaunch zwei", external_ref=RELAUNCH.id)
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_project(conn, customer_id=beta.id, name="Relaunch", external_ref=RELAUNCH.id)


def test_changing_a_project_to_a_taken_salesforce_project_id_is_refused(conn):
    acme = reg.register_account(conn, ACME)
    repo.create_project(conn, customer_id=acme.id, name="Relaunch", external_ref=RELAUNCH.id)
    other = repo.create_project(conn, customer_id=acme.id, name="Wartung", external_ref=WARTUNG.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.update_project(conn, other.id, name="Wartung", color=None, round_minutes=None,
                            archived=False, external_ref=RELAUNCH.id)
    # saving it unchanged is fine
    repo.update_project(conn, other.id, name="Wartung 2", color=None, round_minutes=None,
                        archived=False, external_ref=WARTUNG.id)


def test_empty_references_and_references_of_other_customers_may_repeat(conn):
    acme = reg.register_account(conn, ACME)
    jira = repo.create_customer(conn, "Jira", booking_system="jira")
    plain = repo.create_customer(conn, "Ohne System")
    repo.create_project(conn, customer_id=acme.id, name="A")
    repo.create_project(conn, customer_id=acme.id, name="B")
    repo.create_project(conn, customer_id=acme.id, name="C", external_ref="")
    repo.create_project(conn, customer_id=acme.id, name="D", external_ref="")
    repo.create_project(conn, customer_id=acme.id, name="E", external_ref="REF")
    repo.create_project(conn, customer_id=jira.id, name="A", external_ref="REF")
    repo.create_project(conn, customer_id=jira.id, name="B", external_ref="REF")
    repo.create_project(conn, customer_id=plain.id, name="A", external_ref="REF")

    assert len(repo.list_projects(conn)) == 8


def test_a_customer_that_becomes_a_salesforce_customer_loses_only_taken_project_references(conn):
    acme = reg.register_account(conn, ACME)
    jira = repo.create_customer(conn, "Beta", booking_system="jira")
    # older than Acme's project, and still it must not win against a registered one
    taken = repo.create_project(conn, customer_id=jira.id, name="Relaunch", external_ref=RELAUNCH.id)
    free = repo.create_project(conn, customer_id=jira.id, name="Wartung", external_ref=WARTUNG.id)
    registered = repo.create_project(conn, customer_id=acme.id, name="Relaunch", external_ref=RELAUNCH.id)

    reg.connect_customer(conn, jira.id, BETA)

    assert repo.get_project(conn, registered.id).external_ref == RELAUNCH.id
    assert repo.get_project(conn, taken.id).external_ref is None
    assert repo.get_project(conn, free.id).external_ref == WARTUNG.id


# ---------- Projekte registrieren ----------


def test_registering_several_projects_creates_one_project_each_with_its_settings(conn):
    acme = reg.register_account(conn, ACME)

    created = reg.register_projects(conn, acme.id, [
        reg.ProjectRegistration(RELAUNCH, "Development", " SOT-00348 "),
        reg.ProjectRegistration(WARTUNG, "Consulting"),
    ])

    assert [p.name for p in created] == ["Relaunch", "Wartung"]
    stored = {p.name: p for p in repo.list_projects(conn)}
    assert set(stored) == {"Relaunch", "Wartung"}
    relaunch, wartung = stored["Relaunch"], stored["Wartung"]
    assert relaunch.customer_id == wartung.customer_id == acme.id
    assert (relaunch.external_ref, relaunch.external_name) == (RELAUNCH.id, "Relaunch")
    assert (relaunch.default_service_type, relaunch.customer_request_type) == ("Development", "SOT-00348")
    assert (wartung.external_ref, wartung.external_name) == (WARTUNG.id, "Wartung")
    assert (wartung.default_service_type, wartung.customer_request_type) == ("Consulting", None)


def test_registering_a_salesforce_project_twice_is_refused_and_creates_nothing(conn):
    acme = reg.register_account(conn, ACME)
    first = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]
    repo.update_project(conn, first.id, name="Relaunch 2026", color=None, round_minutes=None,
                        archived=True, external_ref=first.external_ref)

    with pytest.raises(reg.ProjectAlreadyRegisteredError) as excinfo:
        reg.register_projects(conn, acme.id, [
            reg.ProjectRegistration(WARTUNG, "Consulting"),
            reg.ProjectRegistration(RELAUNCH, "Consulting"),
        ])

    assert "Relaunch 2026 (archiviert)" in str(excinfo.value)
    assert RELAUNCH.id not in str(excinfo.value)
    # all or nothing: Wartung was not created either
    assert [p.name for p in repo.list_projects(conn, include_archived=True)] == ["Relaunch 2026"]


def test_a_salesforce_project_registered_under_another_customer_is_refused_too(conn):
    acme = reg.register_account(conn, ACME)
    beta = reg.register_account(conn, BETA)
    reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])

    with pytest.raises(reg.ProjectAlreadyRegisteredError):
        reg.register_projects(conn, beta.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])


def test_a_hand_typed_15_character_id_counts_as_the_same_salesforce_project(conn):
    acme = reg.register_account(conn, ACME)
    repo.create_project(conn, customer_id=acme.id, name="Von Hand", external_ref=RELAUNCH.id[:15])

    with pytest.raises(reg.ProjectAlreadyRegisteredError):
        reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])


def test_choosing_the_same_salesforce_project_twice_is_refused(conn):
    acme = reg.register_account(conn, ACME)

    with pytest.raises(reg.RegistrationError):
        reg.register_projects(conn, acme.id, [
            reg.ProjectRegistration(RELAUNCH, "Consulting"),
            reg.ProjectRegistration(RELAUNCH, "Development"),
        ])

    assert repo.list_projects(conn) == []


def test_registering_is_refused_when_the_customer_has_a_project_with_that_name(conn):
    acme = reg.register_account(conn, ACME)
    by_hand = repo.create_project(conn, customer_id=acme.id, name="Relaunch")

    with pytest.raises(reg.ProjectNameTakenError) as excinfo:
        reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])

    assert "Verbinden" in str(excinfo.value)
    assert repo.get_project(conn, by_hand.id).external_ref is None


def test_the_same_project_name_under_another_customer_is_no_obstacle(conn):
    acme = reg.register_account(conn, ACME)
    other = repo.create_customer(conn, "Anderer Kunde")
    repo.create_project(conn, customer_id=other.id, name="Relaunch")

    created = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])

    assert created[0].customer_id == acme.id


def test_projects_can_only_be_registered_for_a_salesforce_customer(conn):
    jira = repo.create_customer(conn, "Jira", booking_system="jira")

    with pytest.raises(reg.RegistrationError):
        reg.register_projects(conn, jira.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])
    with pytest.raises(reg.RegistrationError):
        reg.register_projects(conn, 4711, [reg.ProjectRegistration(RELAUNCH, "Consulting")])

    assert repo.list_projects(conn) == []


def test_an_unknown_service_type_is_refused(conn):
    acme = reg.register_account(conn, ACME)

    with pytest.raises(reg.RegistrationError):
        reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Training")])

    assert repo.list_projects(conn) == []


def test_project_choices_mark_registered_salesforce_projects(conn):
    acme = reg.register_account(conn, ACME)
    reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])

    relaunch, wartung = reg.project_choices(conn, [RELAUNCH, WARTUNG])

    assert relaunch.is_registered and relaunch.registered_as == "Relaunch"
    assert not wartung.is_registered
    assert (relaunch.name, wartung.name) == ("Relaunch", "Wartung")
    assert wartung.record is WARTUNG


def test_new_registrations_start_with_my_global_default_service_type(conn):
    assert reg.new_project_registration(conn, RELAUNCH).service_type == "Consulting"

    sfs.save_default_service_type(conn, "Development")

    assert reg.new_project_registration(conn, RELAUNCH) == reg.ProjectRegistration(RELAUNCH, "Development", "")


# ---------- Nachträglich verbinden ----------


def _entry(conn, project_id: int) -> int:
    start = datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc)
    return repo.create_log(
        conn, project_id=project_id, task="T-1", description="Analyse",
        started_at=start.isoformat(), ended_at=start.replace(hour=10).isoformat(),
        duration_seconds=3600, rounded_to_minutes=None, is_manual=True,
    )


def test_connecting_an_existing_project_keeps_its_name_and_entries(conn):
    acme = reg.register_account(conn, ACME)
    by_hand = repo.create_project(conn, customer_id=acme.id, name="Website", color="#ff0000", round_minutes=30)
    entry_id = _entry(conn, by_hand.id)
    sfs.save_default_service_type(conn, "Development")

    connected = reg.connect_project(conn, by_hand.id, RELAUNCH)

    assert connected.id == by_hand.id
    assert (connected.name, connected.color, connected.round_minutes) == ("Website", "#ff0000", 30)
    assert (connected.external_ref, connected.external_name) == (RELAUNCH.id, "Relaunch")
    assert connected.default_service_type == "Development"   # my global default, as nothing was set yet
    assert repo.get_log(conn, entry_id).project_id == by_hand.id


def test_changing_the_salesforce_project_keeps_service_type_and_customer_request_type(conn):
    acme = reg.register_account(conn, ACME)
    project = reg.register_projects(conn, acme.id, [
        reg.ProjectRegistration(RELAUNCH, "Development", "SOT-00348"),
    ])[0]

    changed = reg.connect_project(conn, project.id, WARTUNG)

    assert (changed.external_ref, changed.external_name) == (WARTUNG.id, "Wartung")
    assert (changed.default_service_type, changed.customer_request_type) == ("Development", "SOT-00348")
    assert not reg.project_choices(conn, [RELAUNCH])[0].is_registered


def test_connecting_is_refused_when_the_salesforce_project_hangs_on_another_project(conn):
    acme = reg.register_account(conn, ACME)
    reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])
    by_hand = repo.create_project(conn, customer_id=acme.id, name="Website")

    with pytest.raises(reg.ProjectAlreadyRegisteredError):
        reg.connect_project(conn, by_hand.id, RELAUNCH)

    assert repo.get_project(conn, by_hand.id).external_ref is None


def test_connecting_the_salesforce_project_a_project_already_has_is_fine(conn):
    acme = reg.register_account(conn, ACME)
    project = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]

    assert reg.connect_project(conn, project.id, RELAUNCH).external_ref == RELAUNCH.id


def test_only_projects_of_salesforce_customers_can_be_connected(conn):
    jira = repo.create_customer(conn, "Jira", booking_system="jira")
    project = repo.create_project(conn, customer_id=jira.id, name="Web")

    with pytest.raises(reg.RegistrationError):
        reg.connect_project(conn, project.id, RELAUNCH)
    with pytest.raises(reg.RegistrationError):
        reg.connect_project(conn, 4711, RELAUNCH)

    assert repo.get_project(conn, project.id).external_ref is None


# ---------- Service Type und Customer Request Type ändern ----------


def test_service_type_and_customer_request_type_of_a_registered_project_can_be_changed(conn):
    acme = reg.register_account(conn, ACME)
    project = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]

    changed = reg.change_booking_defaults(conn, project.id, "Development", " SOT-00348 ")

    assert (changed.default_service_type, changed.customer_request_type) == ("Development", "SOT-00348")
    assert (changed.name, changed.external_ref) == ("Relaunch", RELAUNCH.id)

    cleared = reg.change_booking_defaults(conn, project.id, "Development", "  ")

    assert cleared.customer_request_type is None


def test_changing_to_an_unknown_service_type_is_refused(conn):
    acme = reg.register_account(conn, ACME)
    project = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]

    with pytest.raises(reg.RegistrationError):
        reg.change_booking_defaults(conn, project.id, "Training", "")

    assert repo.get_project(conn, project.id).default_service_type == "Consulting"


def test_a_project_without_a_service_type_shows_my_global_default(conn):
    acme = reg.register_account(conn, ACME)
    by_hand = repo.create_project(conn, customer_id=acme.id, name="Website")
    sfs.save_default_service_type(conn, "Development")

    assert reg.service_type_of(conn, by_hand) == "Development"

    registered = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]

    assert reg.service_type_of(conn, registered) == "Consulting"


# ---------- Anzeige: nie eine Salesforce-ID ----------


def test_external_reference_shown_for_a_project_never_contains_the_salesforce_project_id(conn):
    acme = reg.register_account(conn, ACME)
    registered = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]
    repo.update_project(conn, registered.id, name="Relaunch 2026", color=None, round_minutes=None,
                        archived=False, external_ref=registered.external_ref)
    by_hand = repo.create_project(conn, customer_id=acme.id, name="Von Hand", external_ref=WARTUNG.id)
    unconnected = repo.create_project(conn, customer_id=acme.id, name="Ohne")
    jira = repo.create_customer(conn, "Jira", booking_system="jira")
    jira_project = repo.create_project(conn, customer_id=jira.id, name="Web", external_ref="frei getippt")

    # the name of the Salesforce-Projekt, even after the Projekt was renamed
    assert reg.project_reference_text(repo.get_project(conn, registered.id)) == "Relaunch"
    shown = reg.project_reference_text(repo.get_project(conn, by_hand.id))
    assert shown and WARTUNG.id not in shown
    assert reg.project_reference_text(unconnected) == ""
    assert reg.project_reference_text(jira_project) == "frei getippt"


def test_saving_project_details_keeps_the_salesforce_project_and_ignores_typed_text(conn):
    acme = reg.register_account(conn, ACME)
    registered = reg.register_projects(conn, acme.id, [reg.ProjectRegistration(RELAUNCH, "Consulting")])[0]
    jira = repo.create_customer(conn, "Jira", booking_system="jira")
    jira_project = repo.create_project(conn, customer_id=jira.id, name="Web", external_ref="alt")

    assert reg.project_ref_field_text(registered) == ""
    assert reg.project_ref_to_save(registered, "getippt") == RELAUNCH.id
    assert reg.project_ref_field_text(jira_project) == "alt"
    assert reg.project_ref_to_save(jira_project, " neu ") == "neu"
    assert reg.project_ref_to_save(jira_project, "  ") is None


# ---------- Migration (Schritt 8) ----------


def _legacy_v7_db(path) -> None:
    """A database as version 7 left it: no per-Projekt settings, no uniqueness of Salesforce-Projekt-IDs."""
    raw = sqlite3.connect(str(path))
    raw.row_factory = sqlite3.Row
    raw.executescript(db_module.INITIAL_SCHEMA)
    raw.execute("INSERT INTO schema_version(version) VALUES (7)")
    raw.execute("INSERT INTO app_state(id, default_round_minutes) VALUES (1, 15)")
    raw.executescript(db_module.SNIPPET_SCHEMA)
    db_module._migrate_to_7_salesforce_account(raw)
    now = datetime.now(timezone.utc).isoformat()
    raw.executemany(
        "INSERT INTO customer(id, name, booking_system, external_ref, created_at) VALUES (?, ?, ?, ?, ?)",
        [(1, "Acme", "salesforce", ACME.id, now), (2, "Beta", "salesforce", BETA.id, now),
         (3, "Jira", "jira", "DIS", now)],
    )
    raw.executemany(
        "INSERT INTO project(id, customer_id, name, external_ref, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (1, 1, "Relaunch", RELAUNCH.id, now),
            (2, 1, "Relaunch Duplikat", RELAUNCH.id, now),
            (3, 2, "Relaunch bei Beta", RELAUNCH.id, now),
            (4, 2, "Wartung", WARTUNG.id, now),
            (5, 3, "Jira A", "REF", now),
            (6, 3, "Jira B", "REF", now),
        ],
    )
    raw.execute(
        "INSERT INTO log_entry(project_id, started_at, created_at, updated_at) VALUES (2, ?, ?, ?)",
        (now, now, now),
    )
    raw.commit()
    raw.close()


def test_migration_from_v7_adds_project_settings_and_enforces_uniqueness(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v7_db(db_file)

    conn = db_module.connect(str(db_file))
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db_module.SCHEMA_VERSION
        assert db_module.SCHEMA_VERSION >= 8

        by_name = {p.name: p for p in repo.list_projects(conn)}
        assert len(by_name) == 6
        # the oldest Projekt keeps the Salesforce-Projekt; duplicates stay, but without it
        assert by_name["Relaunch"].external_ref == RELAUNCH.id
        assert by_name["Relaunch Duplikat"].external_ref is None
        assert by_name["Relaunch bei Beta"].external_ref is None
        assert by_name["Wartung"].external_ref == WARTUNG.id
        assert by_name["Jira A"].external_ref == by_name["Jira B"].external_ref == "REF"
        assert by_name["Relaunch"].default_service_type is None
        assert by_name["Relaunch"].customer_request_type is None
        assert conn.execute("SELECT COUNT(*) AS n FROM log_entry WHERE project_id = 2").fetchone()["n"] == 1

        with pytest.raises(sqlite3.IntegrityError):
            repo.create_project(conn, customer_id=2, name="Wartung zwei", external_ref=WARTUNG.id)
        reg.change_booking_defaults(conn, 1, "Development", "SOT-00348")
    finally:
        conn.close()


def test_migration_step_8_is_harmless_when_run_again(tmp_path):
    db_file = tmp_path / "legacy.db"
    _legacy_v7_db(db_file)
    db_module.connect(str(db_file)).close()

    conn = db_module.connect(str(db_file))
    try:
        reg.change_booking_defaults(conn, 1, "Development", "SOT-00348")
        db_module._migrate_to_8_salesforce_projects(conn)
        project = repo.get_project(conn, 1)
        assert (project.external_ref, project.default_service_type) == (RELAUNCH.id, "Development")
        assert len(repo.list_projects(conn)) == 6
    finally:
        conn.close()
