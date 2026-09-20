"""Where the Salesforce connection settings live, and the one question every
Salesforce feature asks first: "ist Salesforce vollständig konfiguriert?"

Instance-URL, Consumer Key and the leistende Person (ID and display name) sit
in the settings table; the Consumer Secret only in the OS keyring. Loading the
configuration never touches the network.

Two levels: the connection alone is enough for Registrieren and Abgleich;
Buchen additionally needs the leistende Person.
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
SETTINGS_SF_PERSON_ID = "salesforce.person_id"
SETTINGS_SF_PERSON_NAME = "salesforce.person_name"
SETTINGS_SF_PERSON_EMAIL = "salesforce.person_email"
SETTINGS_SF_DEFAULT_SERVICE_TYPE = "salesforce.default_service_type"

# The Service Types in domain terms (CONTEXT.md). The picklist values of the org
# belong to the Salesforce client, not here.
SERVICE_TYPES = ("Consulting", "Development")

_MISSING_PERSON = "Leistende Person"


def load_default_service_type(conn: sqlite3.Connection) -> str:
    """My global default for the Service Type; the first one until I choose."""
    value = (repo.get_setting(conn, SETTINGS_SF_DEFAULT_SERVICE_TYPE, "") or "").strip()
    return value if value in SERVICE_TYPES else SERVICE_TYPES[0]


def save_default_service_type(conn: sqlite3.Connection, service_type: str) -> None:
    if service_type not in SERVICE_TYPES:
        raise ValueError(f"Unbekannter Service Type: {service_type}")
    repo.set_setting(conn, SETTINGS_SF_DEFAULT_SERVICE_TYPE, service_type)


@dataclass(slots=True, frozen=True)
class LeistendePerson:
    """The Salesforce user in whose name Kostenpositionen are created (CONTEXT.md)."""

    id: str
    name: str
    email: str = ""

    @property
    def display_text(self) -> str:
        """What the user sees — never the ID."""
        return f"{self.name} ({self.email})" if self.email else self.name


def load_leistende_person(conn: sqlite3.Connection) -> Optional[LeistendePerson]:
    person_id = (repo.get_setting(conn, SETTINGS_SF_PERSON_ID, "") or "").strip()
    if not person_id:
        return None
    return LeistendePerson(
        id=person_id,
        name=(repo.get_setting(conn, SETTINGS_SF_PERSON_NAME, "") or "").strip(),
        email=(repo.get_setting(conn, SETTINGS_SF_PERSON_EMAIL, "") or "").strip(),
    )


def save_leistende_person(conn: sqlite3.Connection, person: Optional[LeistendePerson]) -> None:
    """Store the chosen person; None removes it."""
    repo.set_setting(conn, SETTINGS_SF_PERSON_ID, person.id if person else None)
    repo.set_setting(conn, SETTINGS_SF_PERSON_NAME, person.name if person else None)
    repo.set_setting(conn, SETTINGS_SF_PERSON_EMAIL, person.email if person else None)


@dataclass(slots=True)
class SalesforceConfiguration:
    """Answer to "is Salesforce fully configured?" — and if not, what is missing.

    `missing` / `is_complete` / `missing_text` ask for everything Buchen needs,
    including the leistende Person. The `*connection*` variants ask only for the
    connection, which is all that Registrieren and Abgleich need.
    `credentials` is set as soon as the connection is complete.
    """

    credentials: Optional[SalesforceCredentials] = None
    missing: list[str] = field(default_factory=list)
    leistende_person: Optional[LeistendePerson] = None

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def missing_connection(self) -> list[str]:
        return [m for m in self.missing if m != _MISSING_PERSON]

    @property
    def is_connection_complete(self) -> bool:
        return not self.missing_connection

    @property
    def missing_text(self) -> str:
        """Readable one-liner for tooltips and messages; empty when complete."""
        return _missing_text(self.missing)

    @property
    def connection_missing_text(self) -> str:
        """Like missing_text, for features that only need the connection."""
        return _missing_text(self.missing_connection)


def _missing_text(missing: list[str]) -> str:
    if not missing:
        return ""
    return "Salesforce ist nicht vollständig eingerichtet. Es fehlt: " + ", ".join(missing) + "."


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
    creds = None if missing else SalesforceCredentials(instance_url, consumer_key, secret)
    person = load_leistende_person(conn)
    if person is None:
        missing.append(_MISSING_PERSON)
    return SalesforceConfiguration(credentials=creds, missing=missing, leistende_person=person)
