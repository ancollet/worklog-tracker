from __future__ import annotations

import json

import pytest

from worklog import repository as repo
from worklog.services import credentials
from worklog.services import llm_settings as ls
from worklog.services.llm_cleanup import DEFAULT_SYSTEM_PROMPT, LlmCleanupError


def _configure(conn, endpoint="https://acme.openai.azure.com", deployment="gpt-worklog"):
    repo.set_setting(conn, ls.SETTINGS_LLM_ENDPOINT, endpoint)
    repo.set_setting(conn, ls.SETTINGS_LLM_DEPLOYMENT, deployment)


def test_nothing_configured_names_everything_that_is_missing(conn):
    config = ls.load_configuration(conn, get_secret=lambda: None)

    assert not config.is_complete
    assert config.missing == ["Endpoint-URL", "Deployment-Name", "API-Key"]
    assert config.credentials is None
    assert "API-Key" in config.missing_text


def test_complete_configuration_yields_credentials_and_the_default_prompt(conn):
    _configure(conn, endpoint="  https://acme.openai.azure.com ")

    config = ls.load_configuration(conn, get_secret=lambda: "k-123")

    assert config.is_complete
    assert config.missing_text == ""
    assert config.credentials.endpoint == "https://acme.openai.azure.com"
    assert config.credentials.deployment == "gpt-worklog"
    assert config.credentials.api_key == "k-123"
    assert config.system_prompt == DEFAULT_SYSTEM_PROMPT


def test_only_the_key_missing_is_named(conn):
    _configure(conn)

    config = ls.load_configuration(conn, get_secret=lambda: None)

    assert config.missing == ["API-Key"]
    assert config.credentials is None


def test_unreachable_keyring_is_reported_as_missing_with_reason(conn):
    _configure(conn)

    def unreachable():
        raise credentials.CredentialsUnavailableError("no backend")

    config = ls.load_configuration(conn, get_secret=unreachable)

    assert not config.is_complete
    assert len(config.missing) == 1
    assert "no backend" in config.missing_text


def test_default_prompt_is_not_stored(conn):
    assert ls.load_system_prompt(conn) == DEFAULT_SYSTEM_PROMPT

    ls.save_system_prompt(conn, DEFAULT_SYSTEM_PROMPT)

    assert repo.get_setting(conn, ls.SETTINGS_LLM_SYSTEM_PROMPT) is None


def test_deviating_prompt_is_stored_and_used(conn):
    _configure(conn)

    ls.save_system_prompt(conn, "Mein eigener Prompt")

    assert repo.get_setting(conn, ls.SETTINGS_LLM_SYSTEM_PROMPT) == "Mein eigener Prompt"
    assert ls.load_system_prompt(conn) == "Mein eigener Prompt"
    assert ls.load_configuration(conn, get_secret=lambda: "k").system_prompt == "Mein eigener Prompt"


def test_reset_deletes_the_deviation_and_yields_the_default(conn):
    ls.save_system_prompt(conn, "Mein eigener Prompt")

    ls.reset_system_prompt(conn)

    assert repo.get_setting(conn, ls.SETTINGS_LLM_SYSTEM_PROMPT) is None
    assert ls.load_system_prompt(conn) == DEFAULT_SYSTEM_PROMPT


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sent_system_prompt(config) -> str:
    captured: dict = {}

    def fake_opener(req, timeout=30):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"choices": [{"message": {"content": "Login-Formular korrigiert"}}]})

    result = config.clean_description(
        task="DIS-1", description="login form gefixt", opener=fake_opener
    )
    assert result == "Login-Formular korrigiert"
    return captured["body"]["messages"][0]["content"]


def test_cleaning_uses_the_customized_prompt_and_after_reset_the_default(conn):
    _configure(conn)
    ls.save_system_prompt(conn, "Mein eigener Prompt")

    assert _sent_system_prompt(ls.load_configuration(conn, get_secret=lambda: "k")) == "Mein eigener Prompt"

    ls.reset_system_prompt(conn)

    assert _sent_system_prompt(ls.load_configuration(conn, get_secret=lambda: "k")) == DEFAULT_SYSTEM_PROMPT


def test_cleaning_without_complete_configuration_is_refused_without_a_call(conn):
    config = ls.load_configuration(conn, get_secret=lambda: None)

    def must_not_be_called(req, timeout=30):
        raise AssertionError("no call without configuration")

    with pytest.raises(LlmCleanupError) as excinfo:
        config.clean_description(task=None, description="x", opener=must_not_be_called)

    assert "API-Key" in str(excinfo.value)


def test_empty_prompt_falls_back_to_the_default(conn):
    ls.save_system_prompt(conn, "   \n")

    assert repo.get_setting(conn, ls.SETTINGS_LLM_SYSTEM_PROMPT) is None
    assert ls.load_system_prompt(conn) == DEFAULT_SYSTEM_PROMPT
