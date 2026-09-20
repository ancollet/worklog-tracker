"""Sammelaktion "Beschreibungen bereinigen…": which entries take part, the run
with one call per Eintrag (HTTP faked at the transport boundary) and what
"Übernehmen" writes."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from worklog import repository as repo
from worklog.services import bulk_cleanup as bulk
from worklog.services.llm_cleanup import LlmCredentials
from worklog.services.llm_settings import LlmConfiguration


def _project(conn) -> int:
    c = repo.create_customer(conn, "Geheimkunde GmbH", booking_system="jira")
    return repo.create_project(conn, customer_id=c.id, name="Geheimprojekt").id


def _entry(conn, project_id: int, description, *, booked=False, running=False, task="DIS-1") -> int:
    log_id = repo.create_log(
        conn, project_id=project_id, task=task, description=description,
        started_at="2026-06-10T09:00:00+02:00",
        ended_at=None if running else "2026-06-10T10:00:00+02:00",
        duration_seconds=None if running else 3600,
        rounded_to_minutes=None if running else 15, is_manual=False,
    )
    if booked:
        repo.set_log_external_ref(
            conn, log_id, worklog_id="10042", worklog_url="https://jira/DIS-1",
            synced_at_iso="2026-06-10T10:05:00+02:00",
        )
    return log_id


def _logs(conn, *log_ids: int):
    return [repo.get_log(conn, log_id) for log_id in log_ids]


def _snapshot(conn, log_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM log_entry WHERE id = ?", (log_id,)).fetchone())


def _config() -> LlmConfiguration:
    return LlmConfiguration(
        credentials=LlmCredentials("https://acme.openai.azure.com", "gpt-worklog", "k-123")
    )


class _FakeResponse:
    def __init__(self, content: str) -> None:
        payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"error": {"message": "kaputt"}}).encode("utf-8"))
    return urllib.error.HTTPError("https://x", code, "Error", {}, body)


class _FakeLlm:
    """Answers by the description that was sent; an Exception as answer is raised."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.sent: list[str] = []

    def __call__(self, req, timeout=30):
        user_message = json.loads(req.data.decode("utf-8"))["messages"][1]["content"]
        description = user_message.split("Beschreibung:\n", 1)[1]
        self.sent.append(description)
        answer = self.answers[description]
        if isinstance(answer, Exception):
            raise answer
        return _FakeResponse(answer)


def _run_all(run: bulk.CleanupRun, opener) -> None:
    """What the dialog does, without threads: one call per row until the run is over."""
    while (row := run.next_pending()) is not None:
        run.record(row, bulk.clean_entry(_config(), row.entry, opener=opener))


# ---------- "Beschreibung eines Eintrags setzen" ----------

def test_set_log_description_changes_only_the_description(conn):
    log_id = _entry(conn, _project(conn), "login gefixt")
    flag = repo.create_flag(conn, name="Wichtig")
    repo.set_log_flag(conn, log_id, flag.id, True)
    before = _snapshot(conn, log_id)

    repo.set_log_description(conn, log_id, "Login korrigiert")

    after = _snapshot(conn, log_id)
    assert after.pop("description") == "Login korrigiert"
    after.pop("updated_at")
    before.pop("description")
    before.pop("updated_at")
    assert after == before
    assert repo.get_log_flag_ids(conn, log_id) == {flag.id}


def test_set_log_description_rejects_a_booked_entry(conn):
    log_id = _entry(conn, _project(conn), "login gefixt", booked=True)
    before = _snapshot(conn, log_id)

    with pytest.raises(repo.EntryBookedError):
        repo.set_log_description(conn, log_id, "Login korrigiert")

    assert _snapshot(conn, log_id) == before


def test_set_log_description_keeps_a_running_entry_running(conn):
    log_id = _entry(conn, _project(conn), "login gefixt", running=True)

    repo.set_log_description(conn, log_id, "Login korrigiert")

    log = repo.get_log(conn, log_id)
    assert log.description == "Login korrigiert"
    assert log.ended_at is None and log.duration_seconds is None
    assert [l.id for l in repo.list_running_logs(conn)] == [log_id]


def test_set_log_description_of_a_missing_entry_raises(conn):
    with pytest.raises(LookupError):
        repo.set_log_description(conn, 999, "x")


# ---------- Auswahlregel: wer ist bereinigbar, und warum nicht ----------

def test_entry_with_description_is_cleanable(conn):
    (log,) = _logs(conn, _entry(conn, _project(conn), "login gefixt"))
    assert bulk.skip_reason(log) is None


def test_running_entry_is_cleanable(conn):
    (log,) = _logs(conn, _entry(conn, _project(conn), "login gefixt", running=True))
    assert bulk.skip_reason(log) is None


@pytest.mark.parametrize("description", [None, "", "   \n"])
def test_entry_without_description_is_skipped_with_reason(conn, description):
    (log,) = _logs(conn, _entry(conn, _project(conn), description))
    assert bulk.skip_reason(log) == "keine Beschreibung"


def test_booked_entry_is_skipped_with_reason(conn):
    (log,) = _logs(conn, _entry(conn, _project(conn), "login gefixt", booked=True))
    assert bulk.skip_reason(log) == "gebucht – erst Buchung stornieren"


def test_booked_wins_over_missing_description(conn):
    (log,) = _logs(conn, _entry(conn, _project(conn), "", booked=True))
    assert bulk.skip_reason(log) == "gebucht – erst Buchung stornieren"


# ---------- Lauf: ein Aufruf pro Eintrag ----------

def test_run_with_partial_success(conn):
    pid = _project(conn)
    dirty = _entry(conn, pid, "login gefixt")
    broken = _entry(conn, pid, "kaputter eintrag")
    clean = _entry(conn, pid, "Release vorbereitet")
    llm = _FakeLlm({
        "login gefixt": "Login korrigiert",
        "kaputter eintrag": _http_error(500),
        "Release vorbereitet": " Release vorbereitet ",
    })
    run = bulk.CleanupRun(_logs(conn, dirty, broken, clean))

    _run_all(run, llm)

    first, second, third = run.rows
    assert (first.status, first.after, first.accepted) == (bulk.CLEANED, "Login korrigiert", True)
    assert second.status == bulk.ERROR and "HTTP 500" in second.error
    assert second.after is None and second.accepted is False
    # an unchanged answer is "bereits sauber", not an empty change
    assert third.status == bulk.ALREADY_CLEAN and third.accepted is False
    assert llm.sent == ["login gefixt", "kaputter eintrag", "Release vorbereitet"]
    assert run.is_finished and run.abort_message is None
    assert (run.done_count, run.total_count) == (3, 3)


def test_skipped_entries_trigger_no_call(conn):
    pid = _project(conn)
    empty = _entry(conn, pid, "")
    booked = _entry(conn, pid, "schon gebucht", booked=True)
    dirty = _entry(conn, pid, "login gefixt")
    llm = _FakeLlm({"login gefixt": "Login korrigiert"})
    run = bulk.CleanupRun(_logs(conn, empty, booked, dirty))

    _run_all(run, llm)

    assert llm.sent == ["login gefixt"]
    assert [row.status for row in run.rows] == [bulk.SKIPPED, bulk.SKIPPED, bulk.CLEANED]
    assert run.rows[0].skip_reason == "keine Beschreibung"
    assert (run.done_count, run.total_count) == (1, 1)


def test_auth_error_aborts_the_run_instead_of_repeating_per_row(conn):
    pid = _project(conn)
    ids = [_entry(conn, pid, f"eintrag {i}") for i in range(3)]
    llm = _FakeLlm({f"eintrag {i}": _http_error(401) for i in range(3)})
    run = bulk.CleanupRun(_logs(conn, *ids))

    _run_all(run, llm)

    assert llm.sent == ["eintrag 0"]
    assert "API-Key" in run.abort_message
    assert [row.status for row in run.rows] == [bulk.ERROR, bulk.NOT_RUN, bulk.NOT_RUN]
    assert run.is_finished


def test_incomplete_configuration_aborts_without_any_call(conn):
    log_id = _entry(conn, _project(conn), "login gefixt")
    run = bulk.CleanupRun(_logs(conn, log_id))
    row = run.next_pending()
    llm = _FakeLlm({})

    run.record(row, bulk.clean_entry(LlmConfiguration(missing=["API-Key"]), row.entry, opener=llm))

    assert llm.sent == []
    assert "API-Key" in run.abort_message and run.next_pending() is None


def test_stop_ends_the_run_and_ignores_the_call_in_flight(conn):
    pid = _project(conn)
    ids = [_entry(conn, pid, f"eintrag {i}") for i in range(3)]
    run = bulk.CleanupRun(_logs(conn, *ids))
    in_flight = run.next_pending()
    assert in_flight.status == bulk.RUNNING

    run.stop()
    run.record(in_flight, bulk.CleanupOutcome(after="zu spät"))

    assert run.next_pending() is None and run.is_finished
    assert [row.status for row in run.rows] == [bulk.NOT_RUN] * 3
    assert run.accepted_rows() == []


def test_only_task_and_description_are_sent(conn):
    log_id = _entry(conn, _project(conn), "login gefixt", task="DIS-77")
    bodies: list[str] = []

    def opener(req, timeout=30):
        bodies.append(req.data.decode("utf-8"))
        return _FakeResponse("Login korrigiert")

    _run_all(bulk.CleanupRun(_logs(conn, log_id)), opener)

    assert "DIS-77" in bodies[0] and "login gefixt" in bodies[0]
    assert "Geheimkunde" not in bodies[0] and "Geheimprojekt" not in bodies[0]


# ---------- Übernehmen / Verwerfen ----------

def test_accept_all_and_reject_all_touch_only_cleaned_rows(conn):
    pid = _project(conn)
    ids = [_entry(conn, pid, "login gefixt"), _entry(conn, pid, "Sauber"), _entry(conn, pid, "")]
    run = bulk.CleanupRun(_logs(conn, *ids))
    _run_all(run, _FakeLlm({"login gefixt": "Login korrigiert", "Sauber": "Sauber"}))

    run.reject_all()
    assert run.accepted_rows() == []
    run.accept_all()
    assert [row.entry.id for row in run.accepted_rows()] == [ids[0]]
    run.set_accepted(run.rows[1], True)  # "bereits sauber" cannot be accepted
    assert [row.entry.id for row in run.accepted_rows()] == [ids[0]]


def test_only_accepted_rows_change_the_database(conn):
    pid = _project(conn)
    taken = _entry(conn, pid, "login gefixt")
    discarded = _entry(conn, pid, "doku geschrieben")
    broken = _entry(conn, pid, "kaputter eintrag")
    run = bulk.CleanupRun(_logs(conn, taken, discarded, broken))
    _run_all(run, _FakeLlm({
        "login gefixt": "Login korrigiert",
        "doku geschrieben": "Dokumentation geschrieben",
        "kaputter eintrag": urllib.error.URLError("offline"),
    }))
    run.set_accepted(run.rows[1], False)
    untouched = [_snapshot(conn, discarded), _snapshot(conn, broken)]

    result = bulk.apply_accepted(conn, run)

    assert result.saved_ids == [taken] and result.rejected == []
    assert repo.get_log(conn, taken).description == "Login korrigiert"
    assert [_snapshot(conn, discarded), _snapshot(conn, broken)] == untouched


def test_running_entry_is_cleaned_and_keeps_running(conn):
    log_id = _entry(conn, _project(conn), "login gefixt", running=True)
    run = bulk.CleanupRun(_logs(conn, log_id))
    _run_all(run, _FakeLlm({"login gefixt": "Login korrigiert"}))

    bulk.apply_accepted(conn, run)

    log = repo.get_log(conn, log_id)
    assert log.description == "Login korrigiert" and log.ended_at is None


def test_apply_reports_entries_that_changed_meanwhile_and_saves_the_rest(conn):
    pid = _project(conn)
    ok = _entry(conn, pid, "login gefixt")
    booked_meanwhile = _entry(conn, pid, "doku geschrieben")
    edited_meanwhile = _entry(conn, pid, "test gebaut")
    deleted_meanwhile = _entry(conn, pid, "meeting")
    run = bulk.CleanupRun(_logs(conn, ok, booked_meanwhile, edited_meanwhile, deleted_meanwhile))
    _run_all(run, _FakeLlm({
        "login gefixt": "Login korrigiert", "doku geschrieben": "Dokumentation geschrieben",
        "test gebaut": "Test erstellt", "meeting": "Besprechung",
    }))
    repo.set_log_external_ref(conn, booked_meanwhile, worklog_id="1")
    repo.set_log_description(conn, edited_meanwhile, "test gebaut und dokumentiert")
    repo.delete_log(conn, deleted_meanwhile)

    result = bulk.apply_accepted(conn, run)

    assert result.saved_ids == [ok]
    assert [(row.entry.id, reason) for row, reason in result.rejected] == [
        (booked_meanwhile, "Eintrag ist gebucht, erst Buchung stornieren"),
        (edited_meanwhile, "Beschreibung wurde inzwischen geändert"),
        (deleted_meanwhile, "Eintrag existiert nicht mehr"),
    ]
    assert repo.get_log(conn, booked_meanwhile).description == "doku geschrieben"
    assert repo.get_log(conn, edited_meanwhile).description == "test gebaut und dokumentiert"
