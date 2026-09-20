"""Buchung stornieren: undo the Buchung of an entry and unlock it again.

What happens in the Buchungssystem differs per system, decided on
`log.customer_booking_system`: for a Jira worklog only the local reference is
removed; for Salesforce the Kostenposition is deleted there first, and only then
the entry is unlocked. Qt-free.

Also: what the column "Gebucht" shows for a Buchung of either system.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.salesforce import CostItemNotFoundError, SalesforceClient


def booked_cell_text(log: LogEntry) -> str:
    """What the column "Gebucht" shows. A Kostenposition shows its Nummer — never its Salesforce ID."""
    if log.is_booked:
        if log.customer_booking_system == "salesforce":
            return f"✓ {log.external_worklog_number or 'gebucht'}"
        return f"✓ {log.external_worklog_id}"
    if log.customer_booking_system in ("jira", "salesforce"):
        return "—"
    return ""


def booked_cell_tooltip(log: LogEntry) -> str:
    """Tooltip of the column "Gebucht". The link of a Kostenposition holds its ID, so it is not shown."""
    if not log.is_booked or not log.external_worklog_url:
        return ""
    if log.customer_booking_system == "salesforce":
        name = f"Kostenposition {log.external_worklog_number}" if log.external_worklog_number else "Kostenposition"
        return f"{name} — Strg+Klick öffnet den Datensatz in Salesforce"
    return log.external_worklog_url


def cancel_booking_hint(log: LogEntry) -> str:
    """What "Buchung stornieren" will do for this entry, for the confirmation."""
    if log.customer_booking_system == "salesforce":
        name = f"Kostenposition {log.external_worklog_number}" if log.external_worklog_number else "Kostenposition"
        return (
            f"Die {name} wird in Salesforce gelöscht und der Eintrag wieder freigegeben. "
            "Seine aufgerundete Dauer bleibt stehen."
        )
    return (
        "Nur die lokale Buchungs-Referenz wird entfernt. Der Worklog in Jira bleibt bestehen "
        "und muss dort manuell entfernt werden."
    )


# ---------- Buchung stornieren ----------
#
# For Salesforce one Storno runs in three phases, like Buchen, so a view can keep the
# network off the UI thread (the database connection belongs to the UI thread):
#
#     prepare_cancellation  (database)  what is to be storniert
#     delete_cost_item      (network)   delete the Kostenposition in Salesforce
#     record_cancellation   (database)  remove the Buchung from the Eintrag
#
# `cancel_booking` runs all three in a row.

CANCELLED = "cancelled"
# Salesforce only: the Kostenposition was already gone there; the Eintrag is free all the same.
CANCELLED_COST_ITEM_MISSING = "cancelled_cost_item_missing"


class CancelRefusedError(RuntimeError):
    """Stornieren is not possible; the Eintrag stays gebucht. Readable, never holds a Salesforce ID."""


@dataclass(slots=True, frozen=True)
class Cancellation:
    """The Buchung that is to be storniert. Not meant for display: the reference may be a Salesforce ID."""

    log_id: int
    booking_system: Optional[str]
    reference: str
    number: str = ""

    @property
    def needs_salesforce(self) -> bool:
        return self.booking_system == "salesforce"


def prepare_cancellation(conn: sqlite3.Connection, log_id: int) -> Optional[Cancellation]:
    """What "Buchung stornieren" is about — None when the entry has no Buchung.

    Raises LookupError when the entry does not exist.
    """
    log = repo.get_log(conn, log_id)
    if log is None:
        raise LookupError(f"Eintrag {log_id} existiert nicht")
    if not log.is_booked:
        return None
    return Cancellation(
        log_id=log_id,
        booking_system=log.customer_booking_system,
        reference=log.external_worklog_id or "",
        number=log.external_worklog_number or "",
    )


def delete_cost_item(client: SalesforceClient, cancellation: Cancellation) -> str:
    """The network part: delete the Kostenposition in Salesforce. Returns the outcome.

    Touches no database, so it may run off the UI thread. Raises the SalesforceError of
    the client (not Open any more, refused by the org, Netz, Anmeldung); then the
    Kostenposition still exists and the Eintrag must stay gebucht.
    """
    try:
        client.delete_cost_item(cancellation.reference)
    except CostItemNotFoundError:
        return CANCELLED_COST_ITEM_MISSING
    return CANCELLED


def cost_item_missing_notice(cancellation: Cancellation) -> str:
    """What I am told after CANCELLED_COST_ITEM_MISSING."""
    name = f"Kostenposition {cancellation.number}" if cancellation.number else "Kostenposition"
    return (
        f"Die {name} existierte in Salesforce nicht mehr (dort bereits gelöscht). "
        "Der Eintrag wurde trotzdem freigegeben."
    )


def record_cancellation(conn: sqlite3.Connection, cancellation: Cancellation) -> None:
    """Remove reference, link, Nummer and Buchungszeitpunkt; the entry is fully editable again.

    The duration stays as it is (for Salesforce: the gebuchte Menge). Does nothing when the
    entry is gone or carries another Buchung by now.
    """
    log = repo.get_log(conn, cancellation.log_id)
    if log is None or (log.external_worklog_id or "") != cancellation.reference:
        return
    repo.set_log_external_ref(
        conn, cancellation.log_id, worklog_id=None, worklog_url=None, synced_at_iso=None, worklog_number=None,
    )


def cancel_booking(
    conn: sqlite3.Connection, log_id: int, *, salesforce_client: Optional[SalesforceClient] = None
) -> Optional[str]:
    """Storniert the Buchung of the entry; afterwards it is fully editable again.

    Jira: only the local reference goes, the worklog stays in Jira. Salesforce: the
    Kostenposition is deleted there first (`salesforce_client` is required); if that
    fails the error is raised and the entry stays gebucht and locked.

    Returns the outcome (CANCELLED, CANCELLED_COST_ITEM_MISSING), or None for an entry
    without a Buchung, which is left as it is. Raises LookupError when the entry does not exist.
    """
    cancellation = prepare_cancellation(conn, log_id)
    if cancellation is None:
        return None
    outcome = CANCELLED
    if cancellation.needs_salesforce:
        if salesforce_client is None:
            raise CancelRefusedError(
                "Ohne Verbindung zu Salesforce kann die Kostenposition nicht gelöscht werden."
            )
        outcome = delete_cost_item(salesforce_client, cancellation)
    record_cancellation(conn, cancellation)
    return outcome
