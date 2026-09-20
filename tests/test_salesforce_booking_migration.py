"""Schema-Schritt "→ 10": the Nummer of the Kostenposition on the Eintrag."""
from __future__ import annotations

from worklog import db as db_module
from worklog import repository as repo


def _log_columns(conn) -> set[str]:
    return {r["name"] for r in conn.execute("PRAGMA table_info(log_entry)").fetchall()}


def test_fresh_database_has_the_booking_number_column(conn):
    assert "external_worklog_number" in _log_columns(conn)
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db_module.SCHEMA_VERSION
    assert db_module.SCHEMA_VERSION >= 10


def test_version_8_database_gets_the_column_and_keeps_its_bookings(tmp_path):
    db_file = tmp_path / "old.sqlite"
    conn = db_module.connect(str(db_file))
    customer = repo.create_customer(conn, "Igus", booking_system="jira")
    project = repo.create_project(conn, customer_id=customer.id, name="Web")
    log_id = repo.create_log(
        conn, project_id=project.id, task="DIS-1", description=None,
        started_at="2026-05-08T10:00:00+02:00", ended_at="2026-05-08T11:00:00+02:00",
        duration_seconds=3600, rounded_to_minutes=15, is_manual=False,
    )
    repo.set_log_external_ref(conn, log_id, worklog_id="10001", worklog_url="https://x/browse/DIS-1")
    # Back to how a version-8 database looks.
    conn.execute("ALTER TABLE log_entry DROP COLUMN external_worklog_number")
    conn.execute("UPDATE schema_version SET version = 8")
    conn.close()

    conn = db_module.connect(str(db_file))
    try:
        assert "external_worklog_number" in _log_columns(conn)
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db_module.SCHEMA_VERSION
        log = repo.get_log(conn, log_id)
        assert log.external_worklog_id == "10001"
        assert log.external_worklog_number is None
        assert log.is_booked
    finally:
        conn.close()


def test_migration_step_is_idempotent(conn):
    db_module._migrate_to_10_booking_number(conn)
    db_module._migrate_to_10_booking_number(conn)

    assert "external_worklog_number" in _log_columns(conn)


def test_booking_number_roundtrip_and_clearing(conn):
    customer = repo.create_customer(conn, "Acme", booking_system="salesforce")
    project = repo.create_project(conn, customer_id=customer.id, name="Rollout")
    log_id = repo.create_log(
        conn, project_id=project.id, task="SOT-1", description=None,
        started_at="2026-05-08T10:00:00+02:00", ended_at="2026-05-08T11:00:00+02:00",
        duration_seconds=3600, rounded_to_minutes=15, is_manual=False,
    )

    repo.set_log_external_ref(
        conn, log_id, worklog_id="a0B1", worklog_url="https://x/a0B1", worklog_number="PCI-00042",
        synced_at_iso="2026-05-08T12:00:00+02:00",
    )
    assert repo.get_log(conn, log_id).external_worklog_number == "PCI-00042"

    repo.set_log_external_ref(conn, log_id, worklog_id=None)
    assert repo.get_log(conn, log_id).external_worklog_number is None
