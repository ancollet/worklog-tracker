from __future__ import annotations

import io
import json
import urllib.error

import pytest

from worklog import repository as repo
from worklog.services import llm_cleanup as llm


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _completion(content) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def _answering(content, captured: dict | None = None):
    def fake_opener(req, timeout=30):
        if captured is not None:
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["raw"] = req.data.decode("utf-8")
            captured["body"] = json.loads(captured["raw"])
        return _FakeResponse(_completion(content))

    return fake_opener


def _creds(endpoint="https://acme.openai.azure.com"):
    return llm.LlmCredentials(endpoint=endpoint, deployment="gpt-worklog", api_key="k-123")


def test_clean_description_returns_the_cleaned_text():
    captured: dict = {}

    result = llm.clean_description(
        _creds("https://acme.openai.azure.com/"),  # trailing slash is normalized
        task="DIS-1234",
        description="login form gefixt + bissl recherche wg oauth",
        opener=_answering("Login-Formular korrigiert, Recherche zu OAuth", captured),
    )

    assert result == "Login-Formular korrigiert, Recherche zu OAuth"
    assert captured["url"] == "https://acme.openai.azure.com/openai/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["headers"]["api-key"] == "k-123"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"]["model"] == "gpt-worklog"


def test_payload_is_system_prompt_task_and_description_only():
    captured: dict = {}

    llm.clean_description(
        _creds(),
        task="DIS-1234",
        description="login form gefixt",
        system_prompt="Mein Prompt",
        opener=_answering("Login-Formular korrigiert", captured),
    )

    body = captured["body"]
    assert set(body) == {"model", "messages"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "Mein Prompt"
    user = body["messages"][1]["content"]
    assert "DIS-1234" in user
    assert "login form gefixt" in user


def test_default_prompt_is_sent_when_none_is_given():
    captured: dict = {}

    llm.clean_description(
        _creds(), task=None, description="login form gefixt",
        opener=_answering("Login-Formular korrigiert", captured),
    )

    assert captured["body"]["messages"][0]["content"] == llm.DEFAULT_SYSTEM_PROMPT
    assert "Task:" not in captured["body"]["messages"][1]["content"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://acme.openai.azure.com",
        " https://acme.openai.azure.com/ ",
        "https://acme.openai.azure.com/openai/v1",
        "https://acme.openai.azure.com/openai/v1/",
        "https://acme.openai.azure.com/openai/v1/chat/completions",
    ],
)
def test_endpoint_may_be_pasted_with_or_without_the_v1_path(endpoint):
    assert (
        llm.chat_completions_url(endpoint)
        == "https://acme.openai.azure.com/openai/v1/chat/completions"
    )


def test_test_connection_succeeds_when_the_model_answers():
    captured: dict = {}

    llm.test_connection(_creds(), opener=_answering("OK", captured))

    assert captured["url"] == "https://acme.openai.azure.com/openai/v1/chat/completions"
    assert captured["body"]["model"] == "gpt-worklog"


def test_test_connection_reports_a_rejected_key():
    with pytest.raises(llm.LlmAuthError):
        llm.test_connection(_creds(), opener=_raising(_http_error(401)))


def _http_error(code: int, body: bytes = b""):
    return urllib.error.HTTPError(
        url="https://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body),
    )


def _raising(exc):
    def fake_opener(req, timeout=30):
        raise exc

    return fake_opener


def _clean(opener, description="login form gefixt"):
    return llm.clean_description(_creds(), task="DIS-1", description=description, opener=opener)


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_key_raises_auth_error(code):
    with pytest.raises(llm.LlmAuthError) as excinfo:
        _clean(_raising(_http_error(code, b'{"error":{"message":"Access denied"}}')))

    assert "API-Key" in str(excinfo.value)


def test_unreachable_endpoint_raises_network_error():
    with pytest.raises(llm.LlmNetworkError) as excinfo:
        _clean(_raising(urllib.error.URLError("Name or service not known")))

    assert "Name or service not known" in str(excinfo.value)


def test_timeout_raises_network_error():
    with pytest.raises(llm.LlmNetworkError):
        _clean(_raising(TimeoutError("timed out")))


def test_unknown_deployment_raises_model_error_with_the_providers_message():
    body = b'{"error":{"code":"DeploymentNotFound","message":"The API deployment does not exist."}}'

    with pytest.raises(llm.LlmModelError) as excinfo:
        _clean(_raising(_http_error(404, body)))

    assert "404" in str(excinfo.value)
    assert "The API deployment does not exist." in str(excinfo.value)
    assert not isinstance(excinfo.value, (llm.LlmAuthError, llm.LlmNetworkError))


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("  Login-Formular korrigiert \n", "Login-Formular korrigiert"),
        ('"Login-Formular korrigiert"', "Login-Formular korrigiert"),
        ("'Login-Formular korrigiert'", "Login-Formular korrigiert"),
        ("„Login-Formular korrigiert“", "Login-Formular korrigiert"),
        ("“Login-Formular korrigiert”", "Login-Formular korrigiert"),
        ("»Login-Formular korrigiert«", "Login-Formular korrigiert"),
        (' "  Login-Formular korrigiert " ', "Login-Formular korrigiert"),
        # quotes inside the text are content, not wrapping
        ('Fehler "Login failed" behoben', 'Fehler "Login failed" behoben'),
        ('"Login" und "Logout" korrigiert', '"Login" und "Logout" korrigiert'),
    ],
)
def test_answer_is_trimmed_and_freed_from_wrapping_quotes(answer, expected):
    assert _clean(_answering(answer)) == expected


@pytest.mark.parametrize("answer", ["", "   \n", '""', None])
def test_empty_answer_is_an_error(answer):
    with pytest.raises(llm.LlmEmptyResponseError):
        _clean(_answering(answer))


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_answer_without_text_is_an_error(payload):
    def fake_opener(req, timeout=30):
        return _FakeResponse(payload)

    with pytest.raises(llm.LlmEmptyResponseError):
        _clean(fake_opener)


def test_answer_that_is_not_json_is_a_readable_error():
    class _Html(_FakeResponse):
        def read(self) -> bytes:
            return b"<html>Bad gateway</html>"

    with pytest.raises(llm.LlmCleanupError) as excinfo:
        _clean(lambda req, timeout=30: _Html({}))

    assert "Bad gateway" in str(excinfo.value)


def test_neither_customer_nor_project_name_is_sent(conn):
    customer = repo.create_customer(conn, "Geheimkunde GmbH")
    project = repo.create_project(conn, customer_id=customer.id, name="Projekt Morgenröte")
    log_id = repo.create_log(
        conn, project_id=project.id, task="DIS-1234", description="login form gefixt",
        started_at="2026-05-13T10:00:00+02:00", ended_at="2026-05-13T11:00:00+02:00",
        duration_seconds=3600, rounded_to_minutes=None, is_manual=True,
    )
    entry = repo.get_log(conn, log_id)
    assert entry.customer_name == "Geheimkunde GmbH"  # the entry does carry the names
    assert entry.project_name == "Projekt Morgenröte"
    captured: dict = {}

    result = llm.clean_entry_description(
        _creds(), entry, opener=_answering("Login-Formular korrigiert", captured)
    )

    assert result == "Login-Formular korrigiert"
    sent = json.dumps(captured["body"], ensure_ascii=False)
    assert "DIS-1234" in sent
    assert "login form gefixt" in sent
    assert "Geheimkunde" not in sent
    assert "Morgenröte" not in sent
    assert "Geheimkunde" not in captured["url"]
    assert all("Geheimkunde" not in v for v in captured["headers"].values())
