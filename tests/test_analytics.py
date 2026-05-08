from datetime import datetime, timezone

from worklog import repository as repo
from worklog.services.analytics import Bucket, GroupBy, aggregate


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def test_aggregate_by_day_and_project(conn):
    c = repo.create_customer(conn, "Acme")
    p1 = repo.create_project(conn, customer_id=c.id, name="Web")
    p2 = repo.create_project(conn, customer_id=c.id, name="Mob")

    monday = datetime(2026, 5, 4, 9, tzinfo=timezone.utc)
    tuesday = datetime(2026, 5, 5, 9, tzinfo=timezone.utc)
    for project, day, dur in [
        (p1, monday, 3600),
        (p1, monday, 1800),
        (p2, monday, 900),
        (p1, tuesday, 7200),
    ]:
        repo.create_log(
            conn, project_id=project.id, task="T", description=None,
            started_at=_iso(day), ended_at=_iso(day),
            duration_seconds=dur, rounded_to_minutes=15, is_manual=False,
        )

    rows = aggregate(
        conn,
        from_iso=_iso(datetime(2026, 5, 4, tzinfo=timezone.utc)),
        to_iso=_iso(datetime(2026, 5, 6, tzinfo=timezone.utc)),
        bucket=Bucket.DAY,
        group_by=GroupBy.PROJECT,
    )

    by_key = {(r.bucket, r.group_label): r.seconds for r in rows}
    assert by_key[(monday.strftime("%Y-%m-%d"), "Acme · Web")] == 5400
    assert by_key[(monday.strftime("%Y-%m-%d"), "Acme · Mob")] == 900
    assert by_key[(tuesday.strftime("%Y-%m-%d"), "Acme · Web")] == 7200


def test_aggregate_filters_by_customer(conn):
    c1 = repo.create_customer(conn, "Acme")
    c2 = repo.create_customer(conn, "Beta")
    p1 = repo.create_project(conn, customer_id=c1.id, name="Web")
    p2 = repo.create_project(conn, customer_id=c2.id, name="Backoffice")
    day = datetime(2026, 5, 8, 9, tzinfo=timezone.utc)
    repo.create_log(conn, project_id=p1.id, task=None, description=None,
                    started_at=_iso(day), ended_at=_iso(day),
                    duration_seconds=3600, rounded_to_minutes=15, is_manual=False)
    repo.create_log(conn, project_id=p2.id, task=None, description=None,
                    started_at=_iso(day), ended_at=_iso(day),
                    duration_seconds=1800, rounded_to_minutes=15, is_manual=False)

    rows = aggregate(
        conn,
        from_iso=_iso(datetime(2026, 5, 8, tzinfo=timezone.utc)),
        to_iso=_iso(datetime(2026, 5, 9, tzinfo=timezone.utc)),
        bucket=Bucket.DAY,
        group_by=GroupBy.CUSTOMER,
        customer_id=c1.id,
    )
    assert [(r.group_label, r.seconds) for r in rows] == [("Acme", 3600)]
