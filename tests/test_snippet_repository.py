import sqlite3

import pytest

from worklog import db as db_module
from worklog import repository as repo

START_SNIPPETS = ["Codereview", "Entwicklung", "Istanalyse", "Recherche"]


def test_fresh_database_has_start_snippets(conn):
    assert [s.text for s in repo.list_snippets(conn)] == START_SNIPPETS


def test_deleted_start_snippets_stay_deleted_after_reconnect(tmp_path):
    db_file = tmp_path / "worklog.db"
    conn = db_module.connect(str(db_file))
    for snippet in repo.list_snippets(conn):
        repo.delete_snippet(conn, snippet.id)
    conn.close()

    conn = db_module.connect(str(db_file))
    try:
        assert repo.list_snippets(conn) == []
    finally:
        conn.close()


def test_migration_v5_creates_snippet_table_with_start_snippets_once(tmp_path):
    """Simulate an existing v5 DB (no snippet table) and migrate it."""
    db_file = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_file))
    raw.executescript(db_module.INITIAL_SCHEMA)
    raw.executescript(
        """
        INSERT INTO schema_version(version) VALUES (5);
        INSERT INTO app_state(id, default_round_minutes) VALUES (1, 15);
        INSERT INTO customer(name, archived, created_at) VALUES ('Legacy', 0, '2026-01-01T00:00:00');
        """
    )
    raw.commit()
    assert raw.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'snippet'"
    ).fetchone() is None
    raw.close()

    conn = db_module.connect(str(db_file))
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == db_module.SCHEMA_VERSION >= 6
        assert [s.text for s in repo.list_snippets(conn)] == START_SNIPPETS
        assert [c.name for c in repo.list_customers(conn)] == ["Legacy"]
        repo.delete_snippet(conn, repo.list_snippets(conn)[0].id)
    finally:
        conn.close()

    # Second start: nothing is seeded again.
    conn = db_module.connect(str(db_file))
    try:
        assert [s.text for s in repo.list_snippets(conn)] == START_SNIPPETS[1:]
    finally:
        conn.close()


def test_create_snippet_appends_at_end(conn):
    created = repo.create_snippet(conn, text="  Meeting ")
    assert created.text == "Meeting"
    assert created.created_at is not None
    assert [s.text for s in repo.list_snippets(conn)] == START_SNIPPETS + ["Meeting"]


@pytest.mark.parametrize("text", ["", "   ", "Codereview", "  codeREVIEW "])
def test_create_snippet_rejects_empty_and_duplicate_text(conn, text):
    with pytest.raises(repo.SnippetTextError):
        repo.create_snippet(conn, text=text)
    assert [s.text for s in repo.list_snippets(conn)] == START_SNIPPETS


def test_rename_snippet_keeps_position(conn):
    snippet = repo.list_snippets(conn)[1]
    repo.rename_snippet(conn, snippet.id, text=" Implementierung ")
    assert [s.text for s in repo.list_snippets(conn)] == [
        "Codereview", "Implementierung", "Istanalyse", "Recherche",
    ]


def test_rename_snippet_rejects_empty_and_duplicate_but_allows_own_case_change(conn):
    snippet = repo.list_snippets(conn)[0]
    with pytest.raises(repo.SnippetTextError):
        repo.rename_snippet(conn, snippet.id, text=" ")
    with pytest.raises(repo.SnippetTextError):
        repo.rename_snippet(conn, snippet.id, text="recherche")
    repo.rename_snippet(conn, snippet.id, text="CodeReview")
    assert repo.list_snippets(conn)[0].text == "CodeReview"


def test_reorder_snippets(conn):
    ids = {s.text: s.id for s in repo.list_snippets(conn)}
    repo.reorder_snippets(
        conn, [ids["Recherche"], ids["Codereview"], ids["Istanalyse"], ids["Entwicklung"]]
    )
    assert [s.text for s in repo.list_snippets(conn)] == [
        "Recherche", "Codereview", "Istanalyse", "Entwicklung",
    ]
    # New snippets still land at the end.
    repo.create_snippet(conn, text="Meeting")
    assert repo.list_snippets(conn)[-1].text == "Meeting"


def test_rename_and_delete_leave_existing_descriptions_untouched(conn):
    cust = repo.create_customer(conn, name="Kunde")
    proj = repo.create_project(conn, customer_id=cust.id, name="Projekt")
    now = "2026-01-05T09:00:00+00:00"
    first = repo.create_log(
        conn, project_id=proj.id, task=None, description="Codereview: Login-Formular",
        started_at=now, ended_at=now, duration_seconds=0, rounded_to_minutes=0, is_manual=True,
    )
    second = repo.create_log(
        conn, project_id=proj.id, task=None, description="Recherche: Login-Formular",
        started_at=now, ended_at=now, duration_seconds=0, rounded_to_minutes=0, is_manual=True,
    )
    ids = {s.text: s.id for s in repo.list_snippets(conn)}

    repo.rename_snippet(conn, ids["Codereview"], text="Review")
    repo.delete_snippet(conn, ids["Recherche"])

    assert repo.get_log(conn, first).description == "Codereview: Login-Formular"
    assert repo.get_log(conn, second).description == "Recherche: Login-Formular"
