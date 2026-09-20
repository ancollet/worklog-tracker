""""Verschieben auf…": pick a day, then move the entries there.

`move_entries` returns True when data changed, so the caller can refresh.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from worklog.services.move import MoveRejectedError, move_entries_to_date


class MoveToDateDialog(QDialog):
    def __init__(self, count: int, preset: date, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verschieben auf…")

        label = QLabel(
            "Eintrag verschieben auf:" if count == 1 else f"{count} Einträge verschieben auf:"
        )
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(QDate(preset.year, preset.month, preset.day))
        self.calendar.activated.connect(lambda _date: self.accept())  # double-click / Enter

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Verschieben")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.calendar)
        layout.addWidget(buttons)

    def selected_date(self) -> date:
        return self.calendar.selectedDate().toPyDate()


def move_entries(
    parent: QWidget, conn: sqlite3.Connection, log_ids: list[int], preset: date
) -> bool:
    dlg = MoveToDateDialog(len(log_ids), preset, parent=parent)
    if not dlg.exec():
        return False
    try:
        move_entries_to_date(conn, log_ids, dlg.selected_date())
    except MoveRejectedError as exc:
        show_move_rejected(parent, exc)
        return False
    return True


def show_move_rejected(parent: QWidget, exc: MoveRejectedError) -> None:
    """Tell why nothing was moved (shared by "Verschieben auf…" and Drag & Drop)."""
    entry = exc.entry
    what = " · ".join(
        part for part in (entry.started_at.strftime("%d.%m.%Y %H:%M"), entry.task, entry.description)
        if part
    )
    QMessageBox.warning(
        parent, "Verschieben nicht möglich",
        f"{exc.reason}\n\nBetroffen: {what}\n\nEs wurde nichts verschoben.",
    )
