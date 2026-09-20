"""Cross-platform credential storage via the OS-native keyring.

Uses python-keyring, which maps to GNOME-Keyring/KWallet/Secret-Service on Linux,
the Credential Manager on Windows, and the Keychain on macOS.

We never persist tokens in the SQLite DB — only in the keyring.

If the keyring backend is unavailable (e.g. headless server with no D-Bus and no
`keyrings.alt` installed), get/set raise CredentialsUnavailableError so the UI
can surface a sensible message instead of crashing.
"""
from __future__ import annotations

from typing import Optional

import keyring
from keyring.errors import KeyringError

SERVICE_NAME = "worklog"

# Keys are stored under a single service name; the username field distinguishes systems.
JIRA_TOKEN_KEY = "jira:api_token"


class CredentialsUnavailableError(RuntimeError):
    """Raised when the OS keyring is not reachable (no backend / locked / etc)."""


def _wrap(call):
    try:
        return call()
    except KeyringError as exc:
        raise CredentialsUnavailableError(str(exc)) from exc


def get_secret(key: str) -> Optional[str]:
    return _wrap(lambda: keyring.get_password(SERVICE_NAME, key))


def set_secret(key: str, value: Optional[str]) -> None:
    if value is None or value == "":
        try:
            _wrap(lambda: keyring.delete_password(SERVICE_NAME, key))
        except CredentialsUnavailableError:
            # delete on a missing key may raise on some backends — that's fine.
            pass
        return
    _wrap(lambda: keyring.set_password(SERVICE_NAME, key, value))


# Convenience wrappers per system. Keep them tiny — the abstraction is just the key name.

def get_jira_token() -> Optional[str]:
    return get_secret(JIRA_TOKEN_KEY)


def set_jira_token(token: Optional[str]) -> None:
    set_secret(JIRA_TOKEN_KEY, token)
