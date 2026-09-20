""""Buchung stornieren" for a Kostenposition: delete it in Salesforce, then unlock the Eintrag.

The rules live in `services/booking.py`; this module only asks, waits and tells.
Salesforce is only ever called off the UI thread; the database is only touched in it.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from worklog import repository as repo
from worklog.services import booking
from worklog.services import salesforce as sf_client
from worklog.services.salesforce_settings import SalesforceConfiguration, load_configuration
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call

_STAYS_BOOKED = "Der Eintrag bleibt gebucht."


class _DeletingDialog(QDialog):
    """Modal "please wait" while the Kostenposition is deleted in the background.

    Afterwards `ok` and `result` hold what the call reported: (True, outcome) or (False, error text).
    """

    def __init__(
        self, cancellation: booking.Cancellation, credentials: sf_client.SalesforceCredentials,
        client_factory, parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buchung stornieren")
        self.ok = False
        self.result: object = "Das Storno wurde nicht ausgeführt."
        name = f"Kostenposition {cancellation.number}" if cancellation.number else "Kostenposition"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Die {name} wird in Salesforce gelöscht…"))
        self._call: SalesforceCall | None = start_salesforce_call(
            credentials, client_factory,
            lambda client: booking.delete_cost_item(client, cancellation),
            self._on_finished,
        )

    def _on_finished(self, ok: bool, result) -> None:
        self._call = None
        self.ok, self.result = ok, result
        self.accept()

    def done(self, result: int) -> None:
        # Closing now would lose the answer: the Kostenposition might be deleted, the Eintrag still gebucht.
        if self._call is not None:
            return
        super().done(result)


def cancel_salesforce_booking(
    parent: QWidget, conn: sqlite3.Connection, log_id: int,
    *, configuration: Optional[SalesforceConfiguration] = None,
    client_factory=sf_client.SalesforceClient,
) -> bool:
    """Ask, delete the Kostenposition, unlock the Eintrag. Returns True when data changed."""
    log = repo.get_log(conn, log_id)
    cancellation = booking.prepare_cancellation(conn, log_id) if log is not None else None
    if cancellation is None:
        return False
    # Deleting needs the connection only, not the leistende Person.
    configuration = configuration if configuration is not None else load_configuration(conn)
    if not configuration.is_connection_complete:
        QMessageBox.warning(
            parent, "Buchung stornieren",
            f"{configuration.connection_missing_text}\n\nOhne Verbindung kann die Kostenposition nicht "
            f"in Salesforce gelöscht werden. {_STAYS_BOOKED}",
        )
        return False
    confirm = QMessageBox.question(
        parent, "Buchung stornieren?", f"{booking.cancel_booking_hint(log)} Fortfahren?"
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return False

    waiting = _DeletingDialog(cancellation, configuration.credentials, client_factory, parent)
    waiting.exec()
    if not waiting.ok:
        QMessageBox.warning(parent, "Storno nicht möglich", f"{waiting.result}\n\n{_STAYS_BOOKED}")
        return False
    try:
        booking.record_cancellation(conn, cancellation)
    except sqlite3.Error as exc:
        QMessageBox.warning(
            parent, "Storno nicht gespeichert",
            f"Die Kostenposition wurde in Salesforce gelöscht, der Eintrag konnte aber nicht freigegeben "
            f"werden (Datenbankfehler: {exc}). Bitte \"Buchung stornieren\" wiederholen.",
        )
        return False
    if waiting.result == booking.CANCELLED_COST_ITEM_MISSING:
        QMessageBox.information(parent, "Buchung storniert", booking.cost_item_missing_notice(cancellation))
    return True
