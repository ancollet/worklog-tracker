from datetime import datetime, timezone

from worklog import repository as repo


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def test_no_default_flags_seeded(conn):
    """Fresh DBs ship without seeded flags — user defines their own."""
    assert repo.list_flags(conn) == []


def test_create_and_delete_custom_flag(conn):
    f = repo.create_flag(conn, name="urgent", color="#FF0000", sort_order=5)
    assert f.id > 0
    flags_after = [x.name for x in repo.list_flags(conn)]
    assert "urgent" in flags_after
    repo.delete_flag(conn, f.id)
    flags_after_del = [x.name for x in repo.list_flags(conn)]
    assert "urgent" not in flags_after_del


def test_toggle_flag_on_log(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, 10, tzinfo=timezone.utc)
    log_id = repo.create_log(
        conn, project_id=p.id, task="X", description=None,
        started_at=_iso(t), ended_at=_iso(t),
        duration_seconds=900, rounded_to_minutes=15, is_manual=False,
    )
    gebucht = repo.create_flag(conn, name="gebucht", color="#10B981")

    assert gebucht.id not in repo.get_log_flag_ids(conn, log_id)
    new_state = repo.toggle_log_flag(conn, log_id, gebucht.id)
    assert new_state is True
    assert gebucht.id in repo.get_log_flag_ids(conn, log_id)
    new_state = repo.toggle_log_flag(conn, log_id, gebucht.id)
    assert new_state is False
    assert gebucht.id not in repo.get_log_flag_ids(conn, log_id)


def test_list_logs_loads_flags_batch(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, 10, tzinfo=timezone.utc)
    log_a = repo.create_log(
        conn, project_id=p.id, task="A", description=None,
        started_at=_iso(t), ended_at=_iso(t),
        duration_seconds=900, rounded_to_minutes=15, is_manual=False,
    )
    log_b = repo.create_log(
        conn, project_id=p.id, task="B", description=None,
        started_at=_iso(t), ended_at=_iso(t),
        duration_seconds=900, rounded_to_minutes=15, is_manual=False,
    )
    gebucht = repo.create_flag(conn, name="gebucht", color="#10B981")
    invoiced = repo.create_flag(conn, name="invoiced", color="#3B82F6")
    repo.set_log_flag(conn, log_a, gebucht.id, True)
    repo.set_log_flag(conn, log_a, invoiced.id, True)
    repo.set_log_flag(conn, log_b, gebucht.id, True)

    logs = {l.id: l for l in repo.list_logs(conn)}
    assert {f.name for f in logs[log_a].flags} == {"gebucht", "invoiced"}
    assert {f.name for f in logs[log_b].flags} == {"gebucht"}


def test_set_log_flag_bulk_enable(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, tzinfo=timezone.utc)
    ids = []
    for _ in range(3):
        ids.append(repo.create_log(
            conn, project_id=p.id, task=None, description=None,
            started_at=_iso(t), ended_at=_iso(t),
            duration_seconds=900, rounded_to_minutes=15, is_manual=False,
        ))
    f = repo.create_flag(conn, name="gebucht", color="#10B981")
    repo.set_log_flag_bulk(conn, ids, f.id, True)
    for lid in ids:
        assert f.id in repo.get_log_flag_ids(conn, lid)
    repo.set_log_flag_bulk(conn, ids[:2], f.id, False)
    assert f.id not in repo.get_log_flag_ids(conn, ids[0])
    assert f.id not in repo.get_log_flag_ids(conn, ids[1])
    assert f.id in repo.get_log_flag_ids(conn, ids[2])


def test_count_logs_with_flag(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, tzinfo=timezone.utc)
    a = repo.create_log(conn, project_id=p.id, task=None, description=None,
                       started_at=_iso(t), ended_at=_iso(t),
                       duration_seconds=900, rounded_to_minutes=15, is_manual=False)
    b = repo.create_log(conn, project_id=p.id, task=None, description=None,
                       started_at=_iso(t), ended_at=_iso(t),
                       duration_seconds=900, rounded_to_minutes=15, is_manual=False)
    cc = repo.create_log(conn, project_id=p.id, task=None, description=None,
                        started_at=_iso(t), ended_at=_iso(t),
                        duration_seconds=900, rounded_to_minutes=15, is_manual=False)
    f1 = repo.create_flag(conn, name="gebucht", color="#10B981")
    f2 = repo.create_flag(conn, name="invoiced", color="#3B82F6")
    repo.set_log_flag(conn, a, f1.id, True)
    repo.set_log_flag(conn, b, f1.id, True)
    repo.set_log_flag(conn, b, f2.id, True)
    counts = repo.count_logs_with_flag(conn, [a, b, cc])
    assert counts.get(f1.id) == 2
    assert counts.get(f2.id) == 1


def test_delete_logs_bulk(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, tzinfo=timezone.utc)
    a = repo.create_log(conn, project_id=p.id, task=None, description=None,
                       started_at=_iso(t), ended_at=_iso(t),
                       duration_seconds=900, rounded_to_minutes=15, is_manual=False)
    b = repo.create_log(conn, project_id=p.id, task=None, description=None,
                       started_at=_iso(t), ended_at=_iso(t),
                       duration_seconds=900, rounded_to_minutes=15, is_manual=False)
    repo.delete_logs_bulk(conn, [a, b])
    assert repo.get_log(conn, a) is None
    assert repo.get_log(conn, b) is None


def test_delete_flag_cascades(conn):
    c = repo.create_customer(conn, "Acme")
    p = repo.create_project(conn, customer_id=c.id, name="Web")
    t = datetime(2026, 5, 8, tzinfo=timezone.utc)
    log_id = repo.create_log(
        conn, project_id=p.id, task=None, description=None,
        started_at=_iso(t), ended_at=_iso(t),
        duration_seconds=900, rounded_to_minutes=15, is_manual=False,
    )
    f = repo.create_flag(conn, name="temp")
    repo.set_log_flag(conn, log_id, f.id, True)
    assert f.id in repo.get_log_flag_ids(conn, log_id)
    repo.delete_flag(conn, f.id)
    assert f.id not in repo.get_log_flag_ids(conn, log_id)
