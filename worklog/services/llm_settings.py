"""Where the settings of the LLM-Bereinigung live, and the one question every
Bereinigen feature asks first: "ist die LLM-Bereinigung vollständig konfiguriert?"

Endpoint, deployment and a system prompt that deviates from the default sit in
the settings table; the API key only in the OS keyring. The default prompt
lives in the code and is never stored. Loading the configuration never touches
the network.
"""
from __future__ import annotations

import sqlite3
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from worklog import repository as repo
from worklog.services import credentials, llm_cleanup
from worklog.services.llm_cleanup import DEFAULT_SYSTEM_PROMPT, LlmCleanupError, LlmCredentials

SETTINGS_LLM_ENDPOINT = "llm.endpoint"
SETTINGS_LLM_DEPLOYMENT = "llm.deployment"
SETTINGS_LLM_SYSTEM_PROMPT = "llm.system_prompt"


def load_system_prompt(conn: sqlite3.Connection) -> str:
    """The stored deviation, or the default from the code."""
    stored = repo.get_setting(conn, SETTINGS_LLM_SYSTEM_PROMPT, "") or ""
    return stored if stored.strip() else DEFAULT_SYSTEM_PROMPT


def save_system_prompt(conn: sqlite3.Connection, prompt: str) -> None:
    """Store the prompt only if it deviates from the default; an empty one means the default."""
    deviates = prompt.strip() and prompt.strip() != DEFAULT_SYSTEM_PROMPT.strip()
    repo.set_setting(conn, SETTINGS_LLM_SYSTEM_PROMPT, prompt if deviates else None)


def reset_system_prompt(conn: sqlite3.Connection) -> None:
    """Delete the stored deviation; the default applies again."""
    repo.set_setting(conn, SETTINGS_LLM_SYSTEM_PROMPT, None)


@dataclass(slots=True)
class LlmConfiguration:
    """Answer to "is the LLM-Bereinigung fully configured?" — and if not, what is missing."""

    credentials: Optional[LlmCredentials] = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def missing_text(self) -> str:
        """Readable one-liner for tooltips and messages; empty when complete."""
        if not self.missing:
            return ""
        return (
            "Die LLM-Bereinigung ist nicht vollständig eingerichtet (Einstellungen → LLM). "
            "Es fehlt: " + ", ".join(self.missing) + "."
        )

    def clean_description(
        self, *, task: Optional[str], description: str, opener=urllib.request.urlopen
    ) -> str:
        """Clean one description with these settings (one blocking call — run it off the UI thread).

        Raises LlmCleanupError; without a complete configuration nothing is sent.
        """
        if self.credentials is None:
            raise LlmCleanupError(self.missing_text)
        return llm_cleanup.clean_description(
            self.credentials,
            task=task,
            description=description,
            system_prompt=self.system_prompt,
            opener=opener,
        )


def load_configuration(
    conn: sqlite3.Connection,
    get_secret: Callable[[], Optional[str]] = credentials.get_llm_api_key,
) -> LlmConfiguration:
    endpoint = (repo.get_setting(conn, SETTINGS_LLM_ENDPOINT, "") or "").strip()
    deployment = (repo.get_setting(conn, SETTINGS_LLM_DEPLOYMENT, "") or "").strip()
    keyring_problem = ""
    try:
        api_key = get_secret()
    except credentials.CredentialsUnavailableError as exc:
        api_key = None
        keyring_problem = str(exc)

    missing: list[str] = []
    if not endpoint:
        missing.append("Endpoint-URL")
    if not deployment:
        missing.append("Deployment-Name")
    if keyring_problem:
        missing.append(f"API-Key (OS-Keyring nicht erreichbar: {keyring_problem})")
    elif not api_key:
        missing.append("API-Key")
    creds = None if missing else LlmCredentials(endpoint, deployment, api_key)
    return LlmConfiguration(
        credentials=creds, system_prompt=load_system_prompt(conn), missing=missing
    )
