"""Registrieren: einen Salesforce-Account als Kunden in die App übernehmen (CONTEXT.md).

Qt-free. The dialog only shows what this module decides: which Accounts are
already registriert, what is stored, and why something is refused.
The Account-ID stays in the background — nothing here is meant to display it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from worklog import repository as repo
from worklog.db import transaction
from worklog.models import Customer
from worklog.services.salesforce import SalesforceAccount


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
    repo.set_customer_salesforce_account(
        conn, customer.id, account_id=account.id, account_name=account.name
    )
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
