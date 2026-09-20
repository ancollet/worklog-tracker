"""Keyring failures of any kind surface as CredentialsUnavailableError."""
import keyring
import pytest
from keyring.errors import KeyringLocked

from worklog.services import credentials


@pytest.mark.parametrize(
    "failure",
    [KeyringLocked("locked"), RuntimeError("D-Bus is gone"), OSError("no secret service")],
    ids=["keyring-error", "runtime-error", "os-error"],
)
def test_any_backend_failure_becomes_credentials_unavailable(monkeypatch, failure):
    def broken(*_args):
        raise failure

    monkeypatch.setattr(keyring, "get_password", broken)
    monkeypatch.setattr(keyring, "set_password", broken)

    with pytest.raises(credentials.CredentialsUnavailableError):
        credentials.get_secret(credentials.LLM_API_KEY)
    with pytest.raises(credentials.CredentialsUnavailableError):
        credentials.set_secret(credentials.LLM_API_KEY, "k")
