"""Buchungsdialog "In Salesforce buchen…", shared by every view that offers it.

One row per Eintrag (a Sammelbuchung hands over several), each with what will
land in Salesforce. The dialog only shows and collects: every rule lives in
`services/salesforce_booking.py`, the course of a run in `services/salesforce_booking_run.py`.
Salesforce is only ever called off the UI thread; the database only ever in it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog.services import salesforce as sf_client
from worklog.services import salesforce_booking as booking
from worklog.services import salesforce_booking_run as booking_run
from worklog.services.salesforce_reconciliation import check_open_projects
from worklog.services.salesforce_settings import (
    SERVICE_TYPES,
    SalesforceConfiguration,
    load_configuration,
)
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call

(_COL_SELECTED, _COL_DATE, _COL_PROJECT, _COL_QUANTITY, _COL_SERVICE_TYPE, _COL_REQUEST_TYPE,
 _COL_DESCRIPTION, _COL_STATUS) = range(8)
_HEADERS = ["", "Datum", "Projekt", "Menge (h)", "Service Type", "Customer Request Type", "Beschreibung", "Status"]


@dataclass(slots=True)
class _Row:
    """The widgets of one row; what happens to it lives in `entry` (the Buchungs-Service)."""

    entry: booking_run.BookingRow
    selected: QCheckBox
    quantity: QDoubleSpinBox
    service_type: QComboBox
    request_type: QLineEdit
    description: QLineEdit
    labels: tuple[QTableWidgetItem, ...]
    status: QTableWidgetItem

    def editors(self) -> tuple[QWidget, ...]:
        return (self.quantity, self.service_type, self.request_type, self.description)

    def confirmed(self) -> booking.ConfirmedBooking:
        return booking.ConfirmedBooking(
            log_id=self.entry.log_id,
            quantity_hours=self.quantity.value(),
            service_type=self.service_type.currentText(),
            customer_request_type=self.request_type.text(),
            description=self.description.text(),
        )


class SalesforceBookingDialog(QDialog):
    """Shows the Buchungsvorschläge of `log_ids`, oldest first, and books the confirmed rows
    one after another (`BookingRun`).

    A failed row keeps the dialog open for correction; a gebuchte row is done and locked.
    `booked_log_ids` tells the caller afterwards whether data changed.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        log_ids: list[int],
        *,
        configuration: Optional[SalesforceConfiguration] = None,
        client_factory=sf_client.SalesforceClient,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._configuration = configuration if configuration is not None else load_configuration(conn)
        self._client_factory = client_factory
        self._client = None                       # one client (one Anmeldung) for the whole dialog
        self._call: SalesforceCall | None = None
        self._closed = False
        self._run = booking_run.BookingRun(conn, self._configuration, log_ids)
        self._in_flight: Optional[booking_run.BookingRow] = None   # its Kostenposition is being created
        self._rows: list[_Row] = []
        self.setWindowTitle("In Salesforce buchen")
        self.setMinimumSize(1020, 260)

        person = self._configuration.leistende_person
        intro = QLabel(
            "Das landet als Kostenposition in Salesforce"
            + (f", im Namen von {person.display_text}" if person else "")
            + ". Änderungen hier gelten nur für diese Buchung. Beim Buchen wird die Dauer des "
            "Eintrags auf die gebuchte Menge gesetzt."
        )
        intro.setWordWrap(True)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Stretch)
        for entry in self._run.rows:
            self._add_row(entry)
        # Abwählen only makes sense in a Sammelbuchung.
        self.table.setColumnHidden(_COL_SELECTED, len(self._rows) <= 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: gray; font-size: 11px;")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.book_btn = QPushButton("Buchen")
        self.book_btn.setDefault(True)
        self.book_btn.clicked.connect(self._book)
        self.close_btn = QPushButton("Abbrechen")
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.summary)
        buttons.addStretch(1)
        buttons.addWidget(self.book_btn)
        buttons.addWidget(self.close_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(intro)
        outer.addWidget(self.table, 1)
        outer.addWidget(self.progress)
        outer.addWidget(self.status)
        outer.addLayout(buttons)
        self._refresh()
        self._check_projects()

    @property
    def booked_log_ids(self) -> list[int]:
        return self._run.booked_log_ids

    # ------------------ rows ------------------

    def _add_row(self, entry: booking_run.BookingRow) -> None:
        proposal = entry.proposal
        r = self.table.rowCount()
        self.table.insertRow(r)
        date_text = proposal.delivery_date.strftime("%d.%m.%Y") if proposal.delivery_date else "—"
        labels = (QTableWidgetItem(date_text), QTableWidgetItem(proposal.project_name))
        for col, item in zip((_COL_DATE, _COL_PROJECT), labels):
            self.table.setItem(r, col, item)

        selected = QCheckBox()
        selected.setChecked(True)
        selected.setToolTip("Diesen Eintrag mitbuchen")
        selected.toggled.connect(lambda _on: self._refresh())
        quantity = QDoubleSpinBox()
        quantity.setDecimals(1)
        quantity.setSingleStep(booking.QUANTITY_STEP_HOURS)
        quantity.setRange(booking.QUANTITY_STEP_HOURS, 24.0)
        quantity.setValue(proposal.quantity_hours)
        # Typed values snap to the half-hour grid, UP like the Mengenregel.
        quantity.editingFinished.connect(
            lambda box=quantity: box.setValue(booking.booking_quantity_hours(round(box.value() * 3600)))
        )
        quantity.valueChanged.connect(lambda _value: self._update_summary())
        service_type = QComboBox()
        service_type.addItems(SERVICE_TYPES)
        service_type.setCurrentText(proposal.service_type)
        request_type = QLineEdit(proposal.customer_request_type)
        request_type.setPlaceholderText("optional")
        description = QLineEdit(proposal.description)
        status = QTableWidgetItem("")
        status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)

        row = _Row(entry, selected, quantity, service_type, request_type, description, labels, status)
        for col, widget in zip(
            (_COL_SELECTED, _COL_QUANTITY, _COL_SERVICE_TYPE, _COL_REQUEST_TYPE, _COL_DESCRIPTION),
            (selected, *row.editors()),
        ):
            self.table.setCellWidget(r, col, widget)
        self.table.setItem(r, _COL_STATUS, status)
        self._rows.append(row)

    def _set_row_status(self, row: _Row, text: str, kind: str = "neutral") -> None:
        row.status.setText(text)
        row.status.setToolTip(text)
        color = {"ok": "#15803d", "error": "#b91c1c", "blocked": "gray"}.get(kind)
        row.status.setForeground(QBrush(QColor(color)) if color else QBrush())

    def _set_status(self, text: str, kind: str = "neutral") -> None:
        color = {"ok": "#15803d", "error": "#b91c1c"}.get(kind, "gray")
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _is_busy(self) -> bool:
        return self._call is not None or self._run.is_running

    def _selected_rows(self) -> list[_Row]:
        return [row for row in self._rows if row.entry.is_open and row.selected.isChecked()]

    def _refresh(self) -> None:
        """Bring every row and the buttons in line with the run. The run decides, this only shows."""
        busy = self._is_busy()
        for row in self._rows:
            entry = row.entry
            editable = entry.is_open and self._run.is_checked and not busy
            row.selected.setEnabled(editable)
            if not entry.is_open:
                # Rows that are not buchbar take no part; settled ones stay ticked, as a record.
                row.selected.blockSignals(True)
                row.selected.setChecked(entry.state in (booking_run.BOOKED, booking_run.UNSAVED))
                row.selected.blockSignals(False)
            for widget in row.editors():
                widget.setEnabled(editable and row.selected.isChecked())
            greyed = entry.state == booking_run.BLOCKED
            for item in row.labels:
                item.setForeground(QBrush(QColor("gray")) if greyed else QBrush())
            if entry is self._in_flight:
                self._set_row_status(row, "Wird gebucht…")
            elif entry.state == booking_run.BLOCKED:
                self._set_row_status(row, f"Nicht buchbar: {entry.message}", "blocked")
            elif entry.state == booking_run.BOOKED:
                self._set_row_status(row, f"✓ gebucht als {entry.message}" if entry.message else "✓ gebucht", "ok")
            elif entry.state in (booking_run.FAILED, booking_run.UNSAVED, booking_run.UNKNOWN):
                self._set_row_status(row, entry.message, "error")
            elif entry.state == booking_run.NOT_RUN:
                self._set_row_status(row, entry.message, "blocked")
            elif not self._run.is_checked:
                self._set_row_status(row, "Projekt wird geprüft…" if busy else "Projekt nicht geprüft", "blocked")
            else:
                self._set_row_status(row, "")
        self._update_summary()
        self._update_buttons()

    def _update_summary(self) -> None:
        """Footer: how many buchbare rows will be sent, and their hours."""
        bookable = [row for row in self._rows if row.entry.is_open]
        selected = self._selected_rows()
        hours = f"{sum(row.quantity.value() for row in selected):.1f}".replace(".", ",")
        text = ("1 Eintrag" if len(selected) == 1 else f"{len(selected)} Einträge") + f" zu buchen · {hours} h"
        if len(selected) != len(bookable):
            text += f"  ({len(bookable) - len(selected)} abgewählt)"
        self.summary.setText(text if bookable else "Kein Eintrag zu buchen")

    def _update_buttons(self) -> None:
        busy = self._is_busy()
        selected = self._selected_rows()
        if not self._run.is_checked:
            self.book_btn.setText("Erneut prüfen")
            self.book_btn.setEnabled(not busy and any(row.entry.is_open for row in self._rows))
        elif self._run.has_unsaved and not selected:
            self.book_btn.setText("Speichern wiederholen")
            self.book_btn.setEnabled(not busy)
        else:
            tried = any(row.entry.state in (booking_run.FAILED, booking_run.NOT_RUN) for row in self._rows)
            self.book_btn.setText("Erneut buchen" if tried else "Buchen")
            self.book_btn.setEnabled(not busy and bool(selected or self._run.has_unsaved))
        # While a run is going, "Abbrechen" stops it after the row that is on its way.
        self.close_btn.setText("Schließen" if self.booked_log_ids and not self._run.is_running else "Abbrechen")

    def _start_call(self, work, on_finished) -> None:
        self._call = start_salesforce_call(
            self._configuration.credentials, self._shared_client, work, on_finished
        )

    def _shared_client(self, creds):
        """Runs off the UI thread, one call at a time: every row uses the same Anmeldung."""
        if self._client is None:
            self._client = self._client_factory(creds)
        return self._client

    # ------------------ Abgleich before Buchen ------------------

    def _check_projects(self) -> None:
        """Ask Salesforce once which of the affected Projekte are still offen. Without an
        answer nothing is gebucht."""
        salesforce_project_ids = self._run.projects_to_check()
        if not salesforce_project_ids:
            return   # no buchbare row, nothing to ask
        self._set_status("Prüfe, ob die Projekte in Salesforce noch offen sind…")
        self._start_call(
            lambda client: check_open_projects(client, salesforce_project_ids), self._on_projects_checked
        )
        self._refresh()

    def _on_projects_checked(self, ok: bool, result) -> None:
        self._call = None
        if self._closed:
            return
        if ok:
            self._run.record_check(result)
            self._set_status("")
        else:
            self._set_status(
                f"Die Projekte konnten nicht geprüft werden, es wird nichts gebucht. {result}", "error"
            )
        self._refresh()

    # ------------------ booking ------------------

    def _book(self) -> None:
        if self._is_busy():
            return   # a second click must never book twice
        if not self._run.is_checked:
            self._check_projects()
            return
        self._run.start([row.confirmed() for row in self._selected_rows()])
        self._set_status("")
        self._book_next()

    def _book_next(self) -> None:
        prepared = self._run.next_submission()   # settles rows that fail without Salesforce
        if prepared is None:
            self._finish()
            return
        self._in_flight = next(row.entry for row in self._rows if row.entry.log_id == prepared.log_id)
        done, total = self._run.progress
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setVisible(True)
        self._set_status(f"Buche Eintrag {done + 1} von {total}…")
        self._start_call(
            lambda client: booking_run.submit(client, prepared),
            lambda ok, result: self._on_submitted(prepared, ok, result),
        )
        self._refresh()

    def _on_submitted(self, prepared: booking.PreparedBooking, ok: bool, result) -> None:
        self._call = None
        self._in_flight = None
        # `submit` hands errors back as values; only a client that could not be built arrives as text.
        self._run.finish_submission(prepared, result if ok else sf_client.SalesforceError(str(result)))
        self._book_next()

    def _finish(self) -> None:
        self.progress.setVisible(False)
        self._refresh()
        left = [
            row for row in self._rows
            if row.entry.state in (
                booking_run.FAILED, booking_run.NOT_RUN, booking_run.UNSAVED, booking_run.UNKNOWN
            )
        ]
        booked = len(self.booked_log_ids)
        if self._run.aborted_reason is not None:
            not_run = sum(1 for row in left if row.entry.state == booking_run.NOT_RUN)
            self._set_status(
                f"Abgebrochen: {self._run.aborted_reason} Gebucht: {booked}, nicht ausgeführt: {not_run}.",
                "error",
            )
        elif len(self._rows) == 1 and left:
            # One row: the full text below the table, where it wraps instead of being cut off.
            self._set_status(left[0].status.text(), "error")
        elif left:
            self._set_status(f"{booked} gebucht, {len(left)} nicht — korrigieren und erneut buchen.", "error")
        elif len(self._rows) == 1 and booked:
            self.accept()
        elif booked:
            # A Sammelbuchung stays open: every row shows the Nummer of its Kostenposition.
            self._set_status("1 Eintrag gebucht." if booked == 1 else f"{booked} Einträge gebucht.", "ok")

    def keyPressEvent(self, event) -> None:
        # Enter in a text field must not trigger the default button by accident.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and isinstance(self.focusWidget(), (QLineEdit, QDoubleSpinBox))):
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # While Salesforce is creating a Kostenposition the dialog stays: closing now would lose its
        # reference. The rows after it are not sent any more.
        if self._run.is_running:
            self._run.stop()
            self._set_status("Wird abgebrochen — die laufende Buchung wird noch abgeschlossen.")
            return
        if self._run.has_unsaved:
            numbers = ", ".join(self._run.unsaved_numbers)
            confirm = QMessageBox.warning(
                self, "Buchung nicht gespeichert",
                "Mindestens eine Kostenposition wurde in Salesforce angelegt, steht aber nicht am Eintrag. "
                "Wird der Dialog geschlossen, muss sie in Salesforce von Hand gelöscht werden.\n\n"
                + (f"Betroffen: {numbers}\n\n" if numbers else "")
                + "Trotzdem schließen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        self._closed = True   # an answer of the Abgleich that arrives later is ignored
        super().done(result)


def book_salesforce(
    parent: QWidget, conn: sqlite3.Connection, log_ids: list[int],
    *, client_factory=sf_client.SalesforceClient,
) -> bool:
    """Open the Buchungsdialog for `log_ids`. Returns True when at least one Eintrag was gebucht."""
    dlg = SalesforceBookingDialog(conn, log_ids, client_factory=client_factory, parent=parent)
    dlg.exec()
    return bool(dlg.booked_log_ids)
