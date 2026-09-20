"""Buchungsdialog "In Salesforce buchen…", shared by every view that offers it.

One row per Eintrag (a Sammelbuchung hands over several), each with what will
land in Salesforce. The dialog only shows and collects: every rule lives in
`services/salesforce_booking.py`. Salesforce is only ever called off the UI thread.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog.services import salesforce as sf_client
from worklog.services import salesforce_booking as booking
from worklog.services.salesforce_settings import (
    SERVICE_TYPES,
    SalesforceConfiguration,
    load_configuration,
)
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call

_COL_DATE, _COL_PROJECT, _COL_QUANTITY, _COL_SERVICE_TYPE, _COL_REQUEST_TYPE, _COL_DESCRIPTION, _COL_STATUS = range(7)
_HEADERS = ["Datum", "Projekt", "Menge (h)", "Service Type", "Customer Request Type", "Beschreibung", "Status"]

_PENDING, _DONE, _BLOCKED, _UNSAVED = "pending", "done", "blocked", "unsaved"


@dataclass(slots=True)
class _Row:
    proposal: booking.BookingProposal
    quantity: QDoubleSpinBox
    service_type: QComboBox
    request_type: QLineEdit
    description: QLineEdit
    status: QTableWidgetItem
    state: str = _PENDING
    # Kostenposition exists in Salesforce but is not yet saved at the Eintrag (state _UNSAVED).
    unsaved: Optional[booking.BookingNotRecordedError] = None

    def editors(self) -> tuple[QWidget, ...]:
        return (self.quantity, self.service_type, self.request_type, self.description)

    def confirmed(self) -> booking.ConfirmedBooking:
        return booking.ConfirmedBooking(
            log_id=self.proposal.log_id,
            quantity_hours=self.quantity.value(),
            service_type=self.service_type.currentText(),
            customer_request_type=self.request_type.text(),
            description=self.description.text(),
        )


class SalesforceBookingDialog(QDialog):
    """Shows the Buchungsvorschläge of `log_ids` and books the confirmed rows one after another.

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
        self._conn = conn
        self._configuration = configuration if configuration is not None else load_configuration(conn)
        self._client_factory = client_factory
        self._call: SalesforceCall | None = None
        self._queue: list[_Row] = []
        self._rows: list[_Row] = []
        self.booked_log_ids: list[int] = []
        self.setWindowTitle("In Salesforce buchen")
        self.setMinimumSize(980, 260)

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
        for log_id in log_ids:
            self._add_row(booking.propose_booking(conn, log_id, self._configuration))

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.book_btn = QPushButton("Buchen")
        self.book_btn.setDefault(True)
        self.book_btn.clicked.connect(self._book)
        self.close_btn = QPushButton("Abbrechen")
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.book_btn)
        buttons.addWidget(self.close_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(intro)
        outer.addWidget(self.table, 1)
        outer.addWidget(self.status)
        outer.addLayout(buttons)
        self._update_buttons()

    # ------------------ rows ------------------

    def _add_row(self, proposal: booking.BookingProposal) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        date_text = proposal.delivery_date.strftime("%d.%m.%Y") if proposal.delivery_date else "—"
        for col, text in ((_COL_DATE, date_text), (_COL_PROJECT, proposal.project_name)):
            self.table.setItem(r, col, QTableWidgetItem(text))

        quantity = QDoubleSpinBox()
        quantity.setDecimals(1)
        quantity.setSingleStep(booking.QUANTITY_STEP_HOURS)
        quantity.setRange(booking.QUANTITY_STEP_HOURS, 24.0)
        quantity.setValue(proposal.quantity_hours)
        # Typed values snap to the half-hour grid, UP like the Mengenregel.
        quantity.editingFinished.connect(
            lambda box=quantity: box.setValue(booking.booking_quantity_hours(round(box.value() * 3600)))
        )
        service_type = QComboBox()
        service_type.addItems(SERVICE_TYPES)
        service_type.setCurrentText(proposal.service_type)
        request_type = QLineEdit(proposal.customer_request_type)
        request_type.setPlaceholderText("optional")
        description = QLineEdit(proposal.description)
        status = QTableWidgetItem("")
        status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)

        row = _Row(proposal, quantity, service_type, request_type, description, status)
        for col, widget in zip(
            (_COL_QUANTITY, _COL_SERVICE_TYPE, _COL_REQUEST_TYPE, _COL_DESCRIPTION), row.editors()
        ):
            self.table.setCellWidget(r, col, widget)
        self.table.setItem(r, _COL_STATUS, status)
        self._rows.append(row)
        if not proposal.is_bookable:
            row.state = _BLOCKED
            self._set_row_status(row, f"Nicht buchbar: {proposal.blocked_reason}", "blocked")
            for widget in row.editors():
                widget.setEnabled(False)

    def _set_row_status(self, row: _Row, text: str, kind: str = "neutral") -> None:
        row.status.setText(text)
        row.status.setToolTip(text)
        color = {"ok": "#15803d", "error": "#b91c1c", "blocked": "gray"}.get(kind)
        if color:
            row.status.setForeground(QBrush(QColor(color)))

    def _set_status(self, text: str, kind: str = "neutral") -> None:
        color = {"ok": "#15803d", "error": "#b91c1c"}.get(kind, "gray")
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _open_rows(self) -> list[_Row]:
        return [row for row in self._rows if row.state in (_PENDING, _UNSAVED)]

    def _update_buttons(self) -> None:
        busy = self._call is not None or bool(self._queue)
        open_rows = self._open_rows()
        self.book_btn.setEnabled(not busy and bool(open_rows))
        only_unsaved = bool(open_rows) and all(row.state == _UNSAVED for row in open_rows)
        self.book_btn.setText("Speichern wiederholen" if only_unsaved else "Buchen")
        self.close_btn.setEnabled(not busy)
        self.close_btn.setText("Schließen" if self.booked_log_ids else "Abbrechen")

    # ------------------ booking ------------------

    def _book(self) -> None:
        if self._call is not None or self._queue:
            return   # a second click must never book twice
        self._queue = self._open_rows()
        self._set_status("")
        for row in self._queue:
            for widget in row.editors():
                widget.setEnabled(False)
        self._update_buttons()
        self._book_next()

    def _book_next(self) -> None:
        while self._queue:
            row = self._queue[0]
            if row.state == _UNSAVED:
                # The Kostenposition exists already: only the local part is repeated.
                self._record(row, row.unsaved.prepared, row.unsaved.cost_item)
                self._queue.pop(0)
                continue
            try:
                prepared = booking.prepare_booking(self._conn, self._configuration, row.confirmed())
            except booking.BookingRefusedError as exc:
                self._fail(row, str(exc))
                self._queue.pop(0)
                continue
            self._set_row_status(row, "Wird gebucht…")
            self._call = start_salesforce_call(
                self._configuration.credentials,
                self._client_factory,
                lambda client, prepared=prepared: _submit(client, prepared),
                lambda ok, result, row=row, prepared=prepared: self._on_submitted(row, prepared, ok, result),
            )
            return
        self._finish()

    def _on_submitted(self, row: _Row, prepared: booking.PreparedBooking, ok: bool, result) -> None:
        self._call = None
        self._queue.pop(0)
        if ok and isinstance(result, sf_client.CostItem):
            self._record(row, prepared, result)
        else:
            self._fail(row, str(result))
        self._book_next()

    def _record(self, row: _Row, prepared: booking.PreparedBooking, cost_item: sf_client.CostItem) -> None:
        try:
            booking.record_booking(self._conn, prepared, cost_item)
        except booking.BookingNotRecordedError as exc:
            row.state = _UNSAVED
            row.unsaved = exc
            self._set_row_status(row, str(exc), "error")
            return
        row.state = _DONE
        row.unsaved = None
        self.booked_log_ids.append(row.proposal.log_id)
        self._set_row_status(row, f"✓ gebucht als {cost_item.number}" if cost_item.number else "✓ gebucht", "ok")

    def _fail(self, row: _Row, text: str) -> None:
        self._set_row_status(row, text, "error")
        for widget in row.editors():
            widget.setEnabled(True)

    def _finish(self) -> None:
        self._update_buttons()
        open_rows = self._open_rows()
        if len(self._rows) == 1 and open_rows:
            # One row: the full text below the table, where it wraps instead of being cut off.
            self._set_status(open_rows[0].status.text(), "error")
        elif open_rows:
            self._set_status("Nicht alles wurde gebucht — korrigieren und erneut buchen.", "error")
        elif self.booked_log_ids:
            self.accept()

    def keyPressEvent(self, event) -> None:
        # Enter in a text field must not trigger the default button by accident.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and isinstance(self.focusWidget(), (QLineEdit, QDoubleSpinBox))):
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # While Salesforce is creating a Kostenposition the dialog stays: closing now would lose its reference.
        if self._call is not None or self._queue:
            self._set_status("Die Buchung läuft noch — bitte einen Moment warten.")
            return
        unsaved = [row for row in self._rows if row.state == _UNSAVED]
        if unsaved:
            confirm = QMessageBox.warning(
                self, "Buchung nicht gespeichert",
                "Mindestens eine Kostenposition wurde in Salesforce angelegt, steht aber nicht am Eintrag. "
                "Wird der Dialog geschlossen, muss sie in Salesforce von Hand gelöscht werden.\n\n"
                "Trotzdem schließen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        super().done(result)


def _submit(client, prepared: booking.PreparedBooking):
    """Runs off the UI thread. A refusal (Projekt closed) comes back as a value, so its text stays as it is."""
    try:
        return booking.submit_booking(client, prepared)
    except booking.BookingRefusedError as exc:
        return exc


def book_salesforce(
    parent: QWidget, conn: sqlite3.Connection, log_ids: list[int],
    *, client_factory=sf_client.SalesforceClient,
) -> bool:
    """Open the Buchungsdialog for `log_ids`. Returns True when at least one Eintrag was gebucht."""
    dlg = SalesforceBookingDialog(conn, log_ids, client_factory=client_factory, parent=parent)
    dlg.exec()
    return bool(dlg.booked_log_ids)
