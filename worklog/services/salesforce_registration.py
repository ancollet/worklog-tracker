"""Registrieren: einen Salesforce-Account als Kunden bzw. seine offenen Salesforce-Projekte
als Projekte in die App übernehmen (CONTEXT.md).

Qt-free. The dialog only shows what this module decides: which Accounts and
Salesforce-Projekte are already registriert, what is stored, and why something is refused.
The Salesforce IDs stay in the background — nothing here is meant to display them.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from worklog import repository as repo
from worklog.db import transaction
from worklog.models import Customer, Project
from worklog.services.salesforce import SalesforceAccount, SalesforceProject
from worklog.services.salesforce_settings import SERVICE_TYPES, load_default_service_type


class RegistrationError(RuntimeError):
    """Registrieren or Verbinden was refused. The message is readable for the user (no IDs)."""


class AccountAlreadyRegisteredError(RegistrationError):
    """The Account already hangs on a Kunde."""

    def __init__(self, customer: Customer) -> None:
        super().__init__(f"Dieser Account ist bereits registriert (Kunde „{_display_name(customer)}“).")
        self.customer = customer


class CustomerNameTakenError(RegistrationError):
    """A Kunde with the Account's name exists already (created by hand)."""

    def __init__(self, customer: Customer) -> None:
        super().__init__(
            f"Es gibt bereits einen Kunden „{_display_name(customer)}“. Um ihn mit diesem Account "
            "zu verbinden, den Kunden auswählen und dort „Verbinden…“ wählen."
        )
        self.customer = customer


def _display_name(customer: Customer) -> str:
    return customer.name + (" (archiviert)" if customer.archived else "")


def _same_account(left: str, right: str) -> bool:
    """Salesforce IDs exist in a 15- and an 18-character form; the first 15 identify the record."""
    if left == right:
        return True
    return {len(left), len(right)} == {15, 18} and left[:15] == right[:15]


def registered_customer(conn: sqlite3.Connection, account_id: str) -> Optional[Customer]:
    """The Kunde this Account is registriert as — archived ones count too."""
    for customer in repo.list_customers(conn, include_archived=True):
        if (customer.booking_system == "salesforce" and customer.external_ref
                and _same_account(customer.external_ref, account_id)):
            return customer
    return None


def external_reference_text(customer: Customer) -> str:
    """What the UI shows as the external reference of a Kunde — never a Salesforce ID.

    Salesforce-Kunden show the name of the connected Account; everyone else the
    reference as typed (e.g. the Jira project key).
    """
    if customer.booking_system != "salesforce":
        return customer.external_ref or ""
    if not customer.external_ref:
        return ""
    # Connected by hand before Registrieren existed: the Account's name is unknown.
    return customer.external_name or "Account verbunden"


def external_ref_field_text(customer: Customer) -> str:
    """Initial content of the free text field in the Kunden-Details — empty for Salesforce-Kunden."""
    return "" if customer.booking_system == "salesforce" else (customer.external_ref or "")


def external_ref_to_save(stored: Customer, booking_system: Optional[str], typed_ref: str) -> Optional[str]:
    """The external reference to store when the Kunden-Details are saved.

    For a Salesforce-Kunde the Account-ID only ever comes from Registrieren/Verbinden,
    never from the free text field. (The field in turn is never filled with an
    Account-ID, so switching such a Kunde to another system starts from an empty reference.)
    """
    if booking_system == "salesforce":
        return stored.external_ref if stored.booking_system == "salesforce" else None
    return typed_ref.strip() or None


@dataclass(slots=True, frozen=True)
class AccountChoice:
    """One row of the selection list: an Account and whether it can still be registriert."""

    account: SalesforceAccount
    registered_as: str = ""   # display name of the Kunde it is registriert as; empty if free

    @property
    def is_registered(self) -> bool:
        return bool(self.registered_as)

    # What the selection dialog needs of any kind of choice: record, name, registered_text.
    @property
    def record(self) -> SalesforceAccount:
        return self.account

    @property
    def name(self) -> str:
        return self.account.name

    @property
    def registered_text(self) -> str:
        return f"bereits registriert (Kunde „{self.registered_as}“)" if self.registered_as else ""


def account_choices(conn: sqlite3.Connection, accounts: list[SalesforceAccount]) -> list[AccountChoice]:
    """The Accounts from Salesforce, each marked if it is already registriert."""
    choices = []
    for account in accounts:
        customer = registered_customer(conn, account.id)
        choices.append(AccountChoice(account, _display_name(customer) if customer else ""))
    return choices


def connect_customer(conn: sqlite3.Connection, customer_id: int, account: SalesforceAccount) -> Customer:
    """Connect an existing Kunde with the Account (or change its Account).

    Its Buchungssystem becomes Salesforce; name, Projekte and Einträge stay as they are.
    """
    customer = repo.get_customer(conn, customer_id)
    if customer is None:
        raise RegistrationError("Der Kunde existiert nicht mehr.")
    existing = registered_customer(conn, account.id)
    if existing is not None and existing.id != customer.id:
        raise AccountAlreadyRegisteredError(existing)
    try:
        repo.set_customer_salesforce_account(
            conn, customer.id, account_id=account.id, account_name=account.name
        )
    except repo.BookingSystemLockedError as exc:
        raise RegistrationError(str(exc)) from exc
    return repo.get_customer(conn, customer.id)


def register_account(conn: sqlite3.Connection, account: SalesforceAccount) -> Customer:
    """Register the Account: a new Kunde with its name, Buchungssystem Salesforce and the Account-ID."""
    existing = registered_customer(conn, account.id)
    if existing is not None:
        raise AccountAlreadyRegisteredError(existing)
    for customer in repo.list_customers(conn, include_archived=True):
        if customer.name == account.name:
            raise CustomerNameTakenError(customer)
    with transaction(conn):
        customer = repo.create_customer(conn, account.name)
        repo.set_customer_salesforce_account(
            conn, customer.id, account_id=account.id, account_name=account.name
        )
    return repo.get_customer(conn, customer.id)


# ---------- Projekte registrieren ----------


class ProjectAlreadyRegisteredError(RegistrationError):
    """The Salesforce-Projekt already hangs on a Projekt."""

    def __init__(self, project: Project) -> None:
        super().__init__(
            f"Das Salesforce-Projekt ist bereits registriert (Projekt „{_project_display_name(project)}“)."
        )
        self.project = project


class ProjectNameTakenError(RegistrationError):
    """The Kunde already has a Projekt with the name of the Salesforce-Projekt (created by hand)."""

    def __init__(self, project: Project) -> None:
        super().__init__(
            f"Der Kunde hat bereits ein Projekt „{_project_display_name(project)}“. Um es mit diesem "
            "Salesforce-Projekt zu verbinden, das Projekt auswählen und dort „Verbinden…“ wählen."
        )
        self.project = project


def _project_display_name(project: Project) -> str:
    return project.name + (" (archiviert)" if project.archived else "")


def registered_project(conn: sqlite3.Connection, salesforce_project_id: str) -> Optional[Project]:
    """The Projekt this Salesforce-Projekt is registriert as — archived ones count too."""
    for project in repo.list_projects(conn, include_archived=True):
        if (project.customer_booking_system == "salesforce" and project.external_ref
                and _same_account(project.external_ref, salesforce_project_id)):
            return project
    return None


@dataclass(slots=True, frozen=True)
class ProjectChoice:
    """One row of the selection list: a Salesforce-Projekt and whether it can still be registriert."""

    project: SalesforceProject
    registered_as: str = ""   # display name of the Projekt it is registriert as; empty if free

    @property
    def is_registered(self) -> bool:
        return bool(self.registered_as)

    @property
    def record(self) -> SalesforceProject:
        return self.project

    @property
    def name(self) -> str:
        return self.project.name

    @property
    def registered_text(self) -> str:
        return f"bereits registriert (Projekt „{self.registered_as}“)" if self.registered_as else ""


def project_choices(conn: sqlite3.Connection, projects: list[SalesforceProject]) -> list[ProjectChoice]:
    """The offenen Salesforce-Projekte of an Account, each marked if it is already registriert."""
    choices = []
    for project in projects:
        existing = registered_project(conn, project.id)
        choices.append(ProjectChoice(project, _project_display_name(existing) if existing else ""))
    return choices


@dataclass(slots=True, frozen=True)
class ProjectRegistration:
    """One Salesforce-Projekt chosen for Registrieren, with the settings of the new Projekt."""

    project: SalesforceProject
    service_type: str
    customer_request_type: str = ""


def new_project_registration(conn: sqlite3.Connection, project: SalesforceProject) -> ProjectRegistration:
    """What the selection dialog starts a row with: my global default Service Type, no Customer Request Type."""
    return ProjectRegistration(project, load_default_service_type(conn))


def _salesforce_customer(conn: sqlite3.Connection, customer_id: int) -> Customer:
    customer = repo.get_customer(conn, customer_id)
    if customer is None:
        raise RegistrationError("Der Kunde existiert nicht mehr.")
    if customer.booking_system != "salesforce":
        raise RegistrationError(
            f"„{_display_name(customer)}“ ist kein Salesforce-Kunde. Zuerst den Kunden mit seinem "
            "Salesforce-Account verbinden."
        )
    return customer


def _checked_service_type(service_type: str) -> str:
    if service_type not in SERVICE_TYPES:
        raise RegistrationError(
            f"Unbekannter Service Type „{service_type}“ — möglich sind: " + ", ".join(SERVICE_TYPES) + "."
        )
    return service_type


def register_projects(
    conn: sqlite3.Connection, customer_id: int, registrations: list[ProjectRegistration]
) -> list[Project]:
    """Register the chosen Salesforce-Projekte: exactly one new Projekt each under the Kunde.

    All or nothing — if one of them is refused, none is created.
    """
    customer = _salesforce_customer(conn, customer_id)
    own_projects = {
        p.name: p for p in repo.list_projects(conn, include_archived=True) if p.customer_id == customer.id
    }
    chosen: list[SalesforceProject] = []
    for registration in registrations:
        _checked_service_type(registration.service_type)
        existing = registered_project(conn, registration.project.id)
        if existing is not None:
            raise ProjectAlreadyRegisteredError(existing)
        if any(_same_account(registration.project.id, other.id) for other in chosen):
            raise RegistrationError(f"„{registration.project.name}“ ist doppelt ausgewählt.")
        if registration.project.name in own_projects:
            raise ProjectNameTakenError(own_projects[registration.project.name])
        if any(registration.project.name == other.name for other in chosen):
            raise RegistrationError(
                f"Zwei der gewählten Salesforce-Projekte heißen „{registration.project.name}“. "
                "Bitte einzeln registrieren und das zuerst registrierte Projekt umbenennen."
            )
        chosen.append(registration.project)
    created = []
    with transaction(conn):
        for registration in registrations:
            project = repo.create_project(conn, customer_id=customer.id, name=registration.project.name)
            repo.set_project_salesforce_project(
                conn, project.id,
                salesforce_project_id=registration.project.id,
                salesforce_project_name=registration.project.name,
            )
            repo.set_project_booking_defaults(
                conn, project.id,
                default_service_type=registration.service_type,
                customer_request_type=registration.customer_request_type.strip(),
            )
            created.append(project.id)
    return [repo.get_project(conn, project_id) for project_id in created]


def connect_project(conn: sqlite3.Connection, project_id: int, salesforce_project: SalesforceProject) -> Project:
    """Connect an existing Projekt of a Salesforce-Kunde with the Salesforce-Projekt (or change it).

    Name, colour, rounding and Einträge stay as they are. A Projekt without a
    Service Type yet gets my global default.
    """
    project = repo.get_project(conn, project_id)
    if project is None:
        raise RegistrationError("Das Projekt existiert nicht mehr.")
    _salesforce_customer(conn, project.customer_id)
    existing = registered_project(conn, salesforce_project.id)
    if existing is not None and existing.id != project.id:
        raise ProjectAlreadyRegisteredError(existing)
    with transaction(conn):
        repo.set_project_salesforce_project(
            conn, project.id,
            salesforce_project_id=salesforce_project.id,
            salesforce_project_name=salesforce_project.name,
        )
        if project.default_service_type not in SERVICE_TYPES:
            repo.set_project_booking_defaults(
                conn, project.id,
                default_service_type=load_default_service_type(conn),
                customer_request_type=project.customer_request_type,
            )
    return repo.get_project(conn, project.id)


def change_booking_defaults(
    conn: sqlite3.Connection, project_id: int, service_type: str, customer_request_type: str
) -> Project:
    """Change Service Type and Customer Request Type of a Projekt; an empty Customer Request Type removes it."""
    project = repo.get_project(conn, project_id)
    if project is None:
        raise RegistrationError("Das Projekt existiert nicht mehr.")
    repo.set_project_booking_defaults(
        conn, project.id,
        default_service_type=_checked_service_type(service_type),
        customer_request_type=customer_request_type.strip(),
    )
    return repo.get_project(conn, project.id)


def service_type_of(conn: sqlite3.Connection, project: Project) -> str:
    """The Default-Service-Type of the Projekt; my global default while it has none of its own."""
    if project.default_service_type in SERVICE_TYPES:
        return project.default_service_type
    return load_default_service_type(conn)


def project_reference_text(project: Project) -> str:
    """What the UI shows as the external reference of a Projekt — never a Salesforce ID.

    Projekte of Salesforce-Kunden show the name of the connected Salesforce-Projekt;
    everyone else the reference as typed.
    """
    if project.customer_booking_system != "salesforce":
        return project.external_ref or ""
    if not project.external_ref:
        return ""
    # Typed by hand before Registrieren existed: the name of the Salesforce-Projekt is unknown.
    return project.external_name or "Salesforce-Projekt verbunden"


def project_ref_field_text(project: Project) -> str:
    """Initial content of the free text field in the Projekt-Details — empty for Salesforce-Kunden."""
    return "" if project.customer_booking_system == "salesforce" else (project.external_ref or "")


def project_ref_to_save(stored: Project, typed_ref: str) -> Optional[str]:
    """The external reference to store when the Projekt-Details are saved.

    For a Projekt of a Salesforce-Kunde the ID only ever comes from Registrieren/Verbinden.
    """
    if stored.customer_booking_system == "salesforce":
        return stored.external_ref
    return typed_ref.strip() or None
