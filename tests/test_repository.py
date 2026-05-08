from datetime import datetime, timezone

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
