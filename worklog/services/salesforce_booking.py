"""Buchen in Salesforce: from an Eintrag to exactly one Kostenposition (CONTEXT.md).

Qt-free, and the only place that knows the rules: the Menge (always rounded UP
to half hours), the Beschreibung ("Task: Beschreibung"), why an Eintrag cannot be
gebucht, and what is written to the Eintrag afterwards. The dialog only shows.

One Buchung runs in three phases, so a dialog can keep the network off the UI
thread (the database connection belongs to the UI thread):

    prepare_booking  (database)  checks everything that can be checked locally
    submit_booking   (network)   "is the Projekt still offen?", then creates the Kostenposition
    record_booking   (database)  writes Buchungsreferenz and gebuchte Menge to the Eintrag

`book_entry` runs all three in a row. Every function takes exactly one Eintrag;
a Sammelbuchung (`salesforce_booking_run.py`) calls them row by row.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from worklog import repository as repo
from worklog.db import transaction
from worklog.models import LogEntry
from worklog.services.salesforce import (
    COST_ITEM_TEXT_MAX_LENGTH,
    CostItem,
    CostItemDraft,
    SalesforceClient,
)
from worklog.services.salesforce_reconciliation import is_closed_in_salesforce
from worklog.services.salesforce_registration import service_type_of
from worklog.services.salesforce_settings import SERVICE_TYPES, SalesforceConfiguration

QUANTITY_STEP_HOURS = 0.5  # a Kostenposition counts in half hours, and is never smaller


def booking_quantity_hours(duration_seconds: int) -> float:
    """The Menge of the Kostenposition: the duration in hours, rounded UP to the next
    half hour, at least 0,5. An exact half or full hour stays as it is."""
    half_hours = math.ceil(max(int(duration_seconds), 0) / 1800)
    return max(half_hours, 1) * QUANTITY_STEP_HOURS


def booking_description(task: str | None, description: str | None) -> str:
    """The Beschreibung of the Kostenposition: "Task: Beschreibung", or whichever of
    the two exists. Empty when there is neither — such an Eintrag is not buchbar."""
    parts = [part.strip() for part in (task, description) if part and part.strip()]
    return ": ".join(parts)


# ---------- Why an Eintrag cannot be gebucht ----------

NOT_CONFIGURED = "not_configured"                    # connection or leistende Person missing
ENTRY_MISSING = "entry_missing"
NOT_A_SALESFORCE_CUSTOMER = "not_a_salesforce_customer"
ALREADY_BOOKED = "already_booked"
ENTRY_RUNNING = "entry_running"
NO_DURATION = "no_duration"
NOTHING_TO_DESCRIBE = "nothing_to_describe"          # neither Task nor Beschreibung
PROJECT_NOT_REGISTERED = "project_not_registered"
PROJECT_CLOSED = "project_closed"                    # only known after asking Salesforce
INVALID_VALUES = "invalid_values"                    # confirmed values break a rule

_PROJECT_CLOSED_TEXT = "Projekt ist in Salesforce geschlossen."


class BookingError(RuntimeError):
    """Buchen did not work. The message is readable for the user and never holds a Salesforce ID."""


class BookingRefusedError(BookingError):
    """A precondition is not met; no Kostenposition was created. `code` says which one."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BookingNotRecordedError(BookingError):
    """The Kostenposition exists in Salesforce, but could not be written to the Eintrag.

    Buchen again would create a second one. `cost_item` and `prepared` allow to
    repeat `record_booking` alone.
    """

    def __init__(self, prepared: "PreparedBooking", cost_item: CostItem, detail: str) -> None:
        name = f"Kostenposition {cost_item.number}" if cost_item.number else "Kostenposition"
        super().__init__(
            f"Die {name} wurde in Salesforce angelegt, konnte aber nicht am Eintrag gespeichert "
            f"werden: {detail} Bitte nicht erneut buchen, sondern das Speichern wiederholen oder die "
            "Kostenposition in Salesforce löschen."
        )
        self.prepared = prepared
        self.cost_item = cost_item


def booking_block(
    conn: sqlite3.Connection, log: Optional[LogEntry], configuration: SalesforceConfiguration,
    *, closed_known: bool = False,
) -> Optional[BookingRefusedError]:
    """Why this Eintrag cannot be gebucht in Salesforce right now — None when it can.

    Everything that is known without asking Salesforce; menu, Buchungsvorschlag and
    Buchen itself all ask here. (The error is returned, not raised.)

    `closed_known`: the Projekt was abgeglichen a moment ago, so its Kennzeichen
    "in Salesforce geschlossen" counts too. Without a fresh Abgleich it does not — the
    Projekt may have been reopened since.
    """
    if log is None:
        return BookingRefusedError(ENTRY_MISSING, "Eintrag existiert nicht mehr.")
    if log.customer_booking_system != "salesforce":
        return BookingRefusedError(
            NOT_A_SALESFORCE_CUSTOMER, "Der Kunde dieses Eintrags bucht nicht in Salesforce."
        )
    if not configuration.is_complete:
        return BookingRefusedError(NOT_CONFIGURED, configuration.missing_text)
    if log.is_booked:
        return BookingRefusedError(ALREADY_BOOKED, "Eintrag ist bereits gebucht.")
    if log.ended_at is None:
        return BookingRefusedError(ENTRY_RUNNING, "Eintrag läuft noch.")
    if (log.duration_seconds or 0) <= 0:
        return BookingRefusedError(NO_DURATION, "Eintrag hat keine Dauer.")
    if not booking_description(log.task, log.description):
        return BookingRefusedError(NOTHING_TO_DESCRIBE, "Eintrag hat weder Task noch Beschreibung.")
    project = repo.get_project(conn, log.project_id)
    if project is None or not (project.external_ref or "").strip():
        return BookingRefusedError(
            PROJECT_NOT_REGISTERED,
            "Projekt ist nicht registriert (mit keinem Salesforce-Projekt verbunden).",
        )
    if closed_known and is_closed_in_salesforce(project):
        return BookingRefusedError(PROJECT_CLOSED, _PROJECT_CLOSED_TEXT)
    return None


# ---------- Buchungsvorschlag ----------

@dataclass(slots=True, frozen=True)
class BookingProposal:
    """What would land in Salesforce for one Eintrag — shown in the Buchungsdialog. No IDs."""

    log_id: int
    delivery_date: Optional[date]       # local calendar day of the start
    project_name: str
    quantity_hours: float
    service_type: str
    customer_request_type: str
    description: str
    blocked_reason: Optional[str] = None   # why it is not buchbar, else None

    @property
    def is_bookable(self) -> bool:
        return self.blocked_reason is None


@dataclass(slots=True, frozen=True)
class ConfirmedBooking:
    """The values I confirmed in the Buchungsdialog. They apply to this Buchung only."""

    log_id: int
    quantity_hours: float
    service_type: str
    customer_request_type: str
    description: str

    @classmethod
    def from_proposal(cls, proposal: BookingProposal) -> "ConfirmedBooking":
        return cls(
            log_id=proposal.log_id,
            quantity_hours=proposal.quantity_hours,
            service_type=proposal.service_type,
            customer_request_type=proposal.customer_request_type,
            description=proposal.description,
        )


def propose_booking(
    conn: sqlite3.Connection, log_id: int, configuration: SalesforceConfiguration,
    *, closed_known: bool = False,
) -> BookingProposal:
    log = repo.get_log(conn, log_id)
    block = booking_block(conn, log, configuration, closed_known=closed_known)
    if log is None:
        return BookingProposal(log_id, None, "", QUANTITY_STEP_HOURS, SERVICE_TYPES[0], "", "", str(block))
    project = repo.get_project(conn, log.project_id)
    return BookingProposal(
        log_id=log_id,
        delivery_date=_delivery_date(log),
        project_name=project.display_name if project else (log.project_name or ""),
        quantity_hours=booking_quantity_hours(log.duration_seconds or 0),
        service_type=service_type_of(conn, project) if project else SERVICE_TYPES[0],
        customer_request_type=((project.customer_request_type if project else "") or "").strip(),
        description=booking_description(log.task, log.description),
        blocked_reason=str(block) if block else None,
    )


def _delivery_date(log: LogEntry) -> date:
    """Delivery Date = the calendar day of the start as the app shows it (start times are stored as local time)."""
    return log.started_at.date()


# ---------- Buchen ----------

@dataclass(slots=True, frozen=True)
class PreparedBooking:
    """A checked Buchung, ready for Salesforce. Not meant for display: the draft holds IDs."""

    log_id: int
    draft: CostItemDraft


def prepare_booking(
    conn: sqlite3.Connection, configuration: SalesforceConfiguration, confirmed: ConfirmedBooking,
    *, closed_known: bool = False,
) -> PreparedBooking:
    """Check everything that can be checked without Salesforce. Raises BookingRefusedError."""
    log = repo.get_log(conn, confirmed.log_id)
    block = booking_block(conn, log, configuration, closed_known=closed_known)
    if block is not None:
        raise block
    half_hours = confirmed.quantity_hours / QUANTITY_STEP_HOURS
    if half_hours < 1 or half_hours != int(half_hours):
        raise BookingRefusedError(
            INVALID_VALUES, "Die Menge muss ein Vielfaches von 0,5 Stunden sein, mindestens 0,5."
        )
    if confirmed.service_type not in SERVICE_TYPES:
        raise BookingRefusedError(
            INVALID_VALUES, "Service Type fehlt — möglich sind: " + ", ".join(SERVICE_TYPES) + "."
        )
    if not confirmed.description.strip():
        raise BookingRefusedError(INVALID_VALUES, "Die Beschreibung darf nicht leer sein.")
    for label, text in (
        ("Die Beschreibung", confirmed.description),
        ("Der Customer Request Type", confirmed.customer_request_type),
    ):
        if len(text.strip()) > COST_ITEM_TEXT_MAX_LENGTH:
            raise BookingRefusedError(
                INVALID_VALUES,
                f"{label} ist zu lang — Salesforce nimmt höchstens {COST_ITEM_TEXT_MAX_LENGTH} Zeichen "
                f"(aktuell {len(text.strip())}).",
            )
    project = repo.get_project(conn, log.project_id)
    return PreparedBooking(
        log_id=confirmed.log_id,
        draft=CostItemDraft(
            salesforce_project_id=project.external_ref.strip(),
            person_id=configuration.leistende_person.id,
            quantity_hours=float(confirmed.quantity_hours),
            delivery_date=_delivery_date(log),
            description=confirmed.description.strip(),
            service_type=confirmed.service_type,
            customer_request_type=confirmed.customer_request_type.strip(),
        ),
    )


def submit_booking(
    client: SalesforceClient, prepared: PreparedBooking, *, closed_known: bool = False
) -> CostItem:
    """The network part: create the Kostenposition, unless the Projekt was closed in Salesforce.

    Touches no database, so it may run off the UI thread. Raises BookingRefusedError
    (Projekt closed) or the SalesforceError of the client; then nothing was created.

    `closed_known`: a Sammelbuchung asked Salesforce once for all its Projekte and
    prepared with that answer, so the question is not repeated row by row.
    """
    if not closed_known and not client.is_project_open(prepared.draft.salesforce_project_id):
        raise BookingRefusedError(PROJECT_CLOSED, _PROJECT_CLOSED_TEXT)
    return client.create_cost_item(prepared.draft)


def record_booking(
    conn: sqlite3.Connection, prepared: PreparedBooking, cost_item: CostItem,
    *, now: Optional[datetime] = None,
) -> LogEntry:
    """Write the Buchung to the Eintrag: reference, Nummer, link, time — and the duration
    becomes the gebuchte Menge (Ende = Start + Dauer). All or nothing.

    Raises BookingNotRecordedError when that fails; it can be repeated with the same arguments.
    """
    booked_at = (now or datetime.now(timezone.utc).astimezone()).isoformat(timespec="seconds")
    duration_seconds = round(prepared.draft.quantity_hours * 3600)
    try:
        with transaction(conn):
            log = repo.get_log(conn, prepared.log_id)
            if log is None:
                raise _NotRecorded("Der Eintrag existiert nicht mehr.")
            if log.is_booked and log.external_worklog_id != cost_item.id:
                raise _NotRecorded("Der Eintrag wurde inzwischen anderweitig gebucht.")
            repo.set_log_external_ref(
                conn, log.id,
                worklog_id=cost_item.id,
                worklog_url=cost_item.url,
                synced_at_iso=booked_at,
                worklog_number=cost_item.number or None,
            )
            ended_at = log.started_at + timedelta(seconds=duration_seconds)
            repo.set_log_booked_duration(
                conn, log.id,
                duration_seconds=duration_seconds,
                ended_at=ended_at.isoformat(timespec="seconds"),
            )
    except _NotRecorded as exc:
        raise BookingNotRecordedError(prepared, cost_item, str(exc)) from exc
    except sqlite3.Error as exc:
        raise BookingNotRecordedError(prepared, cost_item, f"Datenbankfehler ({exc}).") from exc
    return repo.get_log(conn, prepared.log_id)


class _NotRecorded(Exception):
    pass


def book_entry(
    conn: sqlite3.Connection,
    client: SalesforceClient,
    configuration: SalesforceConfiguration,
    confirmed: ConfirmedBooking,
) -> LogEntry:
    """Book one Eintrag as exactly one Kostenposition and return the gebuchten Eintrag.

    If creating fails, the Eintrag stays untouched and ungebucht.
    """
    prepared = prepare_booking(conn, configuration, confirmed)
    cost_item = submit_booking(client, prepared)
    return record_booking(conn, prepared, cost_item)
