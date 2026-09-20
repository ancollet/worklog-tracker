"""Buchung stornieren: undo the Buchung of an entry and unlock it again.

What happens in the Buchungssystem differs per system. For a Jira worklog only
the local reference is removed. Salesforce (delete the Kostenposition there, then
remove the reference — Ticket 10) gets its branch in both functions, on
`log.customer_booking_system`; until then its reference is removed locally only.

Also: what the column "Gebucht" shows for a Buchung of either system.
"""
from __future__ import annotations

import sqlite3

from worklog import repository as repo
from worklog.models import LogEntry


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
        # Until Stornieren deletes the Kostenposition in Salesforce (Ticket 10), say honestly that it stays.
        name = f"Kostenposition {log.external_worklog_number}" if log.external_worklog_number else "Kostenposition"
        return (
            f"Nur die lokale Buchungs-Referenz wird entfernt. Die {name} bleibt in Salesforce bestehen "
            "und muss dort manuell gelöscht werden."
        )
    return (
        "Nur die lokale Buchungs-Referenz wird entfernt. Der Worklog in Jira bleibt bestehen "
        "und muss dort manuell entfernt werden."
    )


def cancel_booking(conn: sqlite3.Connection, log_id: int) -> None:
    """Storniert the Buchung of the entry; afterwards it is fully editable again.

    Raises LookupError when the entry does not exist; an entry without a Buchung
    is left as it is.
    """
    log = repo.get_log(conn, log_id)
    if log is None:
        raise LookupError(f"Eintrag {log_id} existiert nicht")
    if not log.is_booked:
        return
    # Jira: the worklog stays in Jira, only the local reference goes.
    repo.set_log_external_ref(conn, log_id, worklog_id=None, worklog_url=None, synced_at_iso=None)
