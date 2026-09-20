import sqlite3
from datetime import datetime, timezone

from worklog import db as db_module
from worklog import repository as repo


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def test_create_and_list_customers(conn):
    repo.create_customer(conn, "Acme")
    repo.create_customer(conn, "Beta")
    customers = repo.list_customers(conn)
    assert [c.name for c in customers] == ["Acme", "Beta"]


def test_create_project_with_customer_join(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Website", color="#3B82F6")
    assert p.customer_name == "Acme"
    assert p.display_name == "Acme · Website"


def test_archive_excludes_from_default_list(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Old")
    repo.update_project(conn, p.id, name="Old", color=None, round_minutes=None, archived=True)
    assert repo.list_projects(conn) == []
    assert len(repo.list_projects(conn, include_archived=True)) == 1


def test_task_suggestions_ordered_by_recency(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t0 = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 2, 10, tzinfo=timezone.utc)
    repo.create_log(conn, project_id=p.id, task="OLD-1", description=None,
                    started_at=_iso(t0), ended_at=_iso(t0), duration_seconds=900,
                    rounded_to_minutes=15, is_manual=False)
    repo.create_log(conn, project_id=p.id, task="NEW-2", description=None,
                    started_at=_iso(t1), ended_at=_iso(t1), duration_seconds=900,
                    rounded_to_minutes=15, is_manual=False)
    assert repo.task_suggestions(conn, project_id=p.id) == ["NEW-2", "OLD-1"]


def test_customer_booking_system_roundtrip(conn):
    c = repo.create_customer(conn, "Igus", booking_system="jira", external_ref="DIS")
    fetched = repo.get_customer(conn, c.id)
    assert fetched is not None
    assert fetched.booking_system == "jira"
    assert fetched.external_ref == "DIS"

    repo.update_customer(
        conn, c.id, name="Igus GmbH", archived=False,
        booking_system="salesforce", external_ref="0011x000ABCDE",
    )
    fetched = repo.get_customer(conn, c.id)
    assert fetched.name == "Igus GmbH"
    assert fetched.booking_system == "salesforce"
    assert fetched.external_ref == "0011x000ABCDE"


def test_project_external_ref_and_customer_system_join(conn):
    c = repo.create_customer(conn, "Dürr", booking_system="salesforce")
    p = repo.create_project(
        conn, customer_id=c.id, name="MVP2 API",
        external_ref="a0X1x000000abcDEAQ",
    )
    fetched = repo.get_project(conn, p.id)
    assert fetched.external_ref == "a0X1x000000abcDEAQ"
    assert fetched.customer_booking_system == "salesforce"

    repo.update_project(
        conn, p.id, name="MVP2 API", color=None, round_minutes=None,
        archived=False, external_ref="updated-ref",
    )
    assert repo.get_project(conn, p.id).external_ref == "updated-ref"


def test_log_external_worklog_roundtrip(conn):
    c = repo.create_customer(conn, "Igus", booking_system="jira")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 13, 10, tzinfo=timezone.utc)
    lid = repo.create_log(
        conn, project_id=p.id, task="DIS-1234", description=None,
        started_at=_iso(t), ended_at=_iso(t), duration_seconds=3600,
        rounded_to_minutes=15, is_manual=False,
    )
    log = repo.get_log(conn, lid)
    assert log.external_worklog_id is None
    assert log.customer_booking_system == "jira"

    repo.set_log_external_ref(
        conn, lid, worklog_id="10001",
        worklog_url="https://acme.atlassian.net/browse/DIS-1234",
        synced_at_iso="2026-05-13T10:05:00+02:00",
    )
    log = repo.get_log(conn, lid)
    assert log.external_worklog_id == "10001"
    assert log.external_worklog_url.endswith("/DIS-1234")
    assert log.external_synced_at is not None

    repo.set_log_external_ref(conn, lid, worklog_id=None)
    log = repo.get_log(conn, lid)
    assert log.external_worklog_id is None
    assert log.external_synced_at is None


def test_migration_v3_to_latest_adds_columns(tmp_path):
    """Simulate an existing v3 DB and confirm migrations bring it up to current."""
    db_file = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_file))
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    # Manually create v3 schema (no booking_system / external_ref columns).
    raw.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        CREATE TABLE customer (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE project (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            color TEXT,
            round_minutes INTEGER,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(customer_id, name)
        );
        CREATE TABLE log_entry (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES project(id),
            task TEXT, description TEXT,
            started_at TEXT NOT NULL, ended_at TEXT,
            duration_seconds INTEGER, rounded_to_minutes INTEGER,
            is_manual INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE app_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running_log_id INTEGER, last_project_id INTEGER,
            default_round_minutes INTEGER NOT NULL DEFAULT 15
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE flag (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            color TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE log_entry_flag (
            log_id INTEGER NOT NULL REFERENCES log_entry(id) ON DELETE CASCADE,
            flag_id INTEGER NOT NULL REFERENCES flag(id) ON DELETE CASCADE,
            PRIMARY KEY (log_id, flag_id)
        );
        INSERT INTO schema_version(version) VALUES (3);
        INSERT INTO app_state(id, default_round_minutes) VALUES (1, 15);
        INSERT INTO customer(name, archived, created_at) VALUES ('Legacy', 0, '2026-01-01T00:00:00');
        """
    )
    raw.commit()
    raw.close()

    # Now run real connect() — this should trigger migration up to current version.
    conn = db_module.connect(str(db_file))
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == db_module.SCHEMA_VERSION

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(customer)").fetchall()}
        assert "booking_system" in cols
        assert "external_ref" in cols
        proj_cols = {r["name"] for r in conn.execute("PRAGMA table_info(project)").fetchall()}
        assert "external_ref" in proj_cols
        log_cols = {r["name"] for r in conn.execute("PRAGMA table_info(log_entry)").fetchall()}
        assert "external_worklog_id" in log_cols
        assert "external_worklog_url" in log_cols
        assert "external_synced_at" in log_cols

        # Existing customer is still loadable via repo helpers.
        customers = repo.list_customers(conn)
        assert [c.name for c in customers] == ["Legacy"]
        assert customers[0].booking_system is None
        assert customers[0].external_ref is None
    finally:
        conn.close()


def test_settings_get_set_delete(conn):
    assert repo.get_setting(conn, "jira.base_url") is None
    assert repo.get_setting(conn, "jira.base_url", default="fallback") == "fallback"

    repo.set_setting(conn, "jira.base_url", "https://acme.atlassian.net")
    assert repo.get_setting(conn, "jira.base_url") == "https://acme.atlassian.net"

    repo.set_setting(conn, "jira.base_url", "https://updated.atlassian.net")
    assert repo.get_setting(conn, "jira.base_url") == "https://updated.atlassian.net"

    repo.set_setting(conn, "jira.base_url", None)
    assert repo.get_setting(conn, "jira.base_url") is None

    repo.set_setting(conn, "jira.base_url", "x")
    repo.set_setting(conn, "jira.base_url", "")
    assert repo.get_setting(conn, "jira.base_url") is None


def test_sum_duration_window(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, 9, tzinfo=timezone.utc)
    for _ in range(3):
        repo.create_log(conn, project_id=p.id, task="X", description=None,
                        started_at=_iso(t), ended_at=_iso(t), duration_seconds=1800,
                        rounded_to_minutes=15, is_manual=False)
    total = repo.sum_duration(conn, from_iso=_iso(t.replace(hour=0)), to_iso=_iso(t.replace(hour=23)))
    assert total == 3 * 1800
