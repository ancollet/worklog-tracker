"""Where the Salesforce connection settings live, and the one question every
Salesforce feature asks first: "ist Salesforce vollständig konfiguriert?"

Instance-URL and Consumer Key sit in the settings table; the Consumer Secret
only in the OS keyring. Loading the configuration never touches the network.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Optional

from worklog import repository as repo
from worklog.services import credentials
from worklog.services.salesforce import SalesforceCredentials

SETTINGS_SF_INSTANCE_URL = "salesforce.instance_url"
SETTINGS_SF_CONSUMER_KEY = "salesforce.consumer_key"


@dataclass(slots=True)
class SalesforceConfiguration:
    """Answer to "is Salesforce fully configured?" — and if not, what is missing."""

    credentials: Optional[SalesforceCredentials] = None
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def missing_text(self) -> str:
        """Readable one-liner for tooltips and messages; empty when complete."""
        if not self.missing:
            return ""
        return "Salesforce ist nicht vollständig eingerichtet. Es fehlt: " + ", ".join(self.missing) + "."


def load_configuration(
    conn: sqlite3.Connection,
    get_secret: Callable[[], Optional[str]] = credentials.get_salesforce_secret,
) -> SalesforceConfiguration:
    instance_url = (repo.get_setting(conn, SETTINGS_SF_INSTANCE_URL, "") or "").strip()
    consumer_key = (repo.get_setting(conn, SETTINGS_SF_CONSUMER_KEY, "") or "").strip()
    keyring_problem = ""
    try:
        secret = get_secret()
    except credentials.CredentialsUnavailableError as exc:
        secret = None
        keyring_problem = str(exc)

    missing: list[str] = []
    if not instance_url:
        missing.append("Instance-URL")
    if not consumer_key:
        missing.append("Consumer Key")
    if keyring_problem:
        missing.append(f"Consumer Secret (OS-Keyring nicht erreichbar: {keyring_problem})")
    elif not secret:
        missing.append("Consumer Secret")
    if missing:
        return SalesforceConfiguration(missing=missing)
    return SalesforceConfiguration(
        credentials=SalesforceCredentials(instance_url, consumer_key, secret)
    )
