"""Buchung stornieren: undo the Buchung of an entry and unlock it again.

What happens in the Buchungssystem differs per system. Today every Buchung is a
Jira worklog, where only the local reference is removed. Salesforce (delete the
Kostenposition there, then remove the reference) gets its branch in both
functions, on `log.customer_booking_system`.
"""
from __future__ import annotations

import sqlite3

from worklog import repository as repo
from worklog.models import LogEntry


def cancel_booking_hint(log: LogEntry) -> str:
    """What "Buchung stornieren" will do for this entry, for the confirmation."""
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
