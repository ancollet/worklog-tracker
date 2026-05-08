from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services.rounding import format_hm_short


class LogsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Datum", "Projekt", "Task", "Beschreibung", "Dauer", "Manuell"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._edit_row)

        self.add_btn = QPushButton("+ Add Log")
        self.add_btn.clicked.connect(self._add_log)
        self.edit_btn = QPushButton("✎ Bearbeiten")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = QPushButton("⌫ Löschen")
        self.delete_btn.clicked.connect(self._delete_selected)

        outer = QVBoxLayout(self)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        outer.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        logs = repo.list_logs(self.conn, limit=500)
        self.table.setRowCount(0)
        for log in logs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            date_str = log.started_at.strftime("%Y-%m-%d %H:%M") if log.started_at else "—"
            project = (
                f"{log.customer_name}/{log.project_name}" if log.customer_name else (log.project_name or "")
            )
            duration = format_hm_short(log.duration_seconds or 0) if log.duration_seconds else "läuft…"
            manual = "✓" if log.is_manual else ""
            for col, text in enumerate([date_str, project, log.task or "", log.description or "", duration, manual]):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, log.id)
                if col in (4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, item)

    def _selected_log_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _add_log(self) -> None:
        from worklog.ui.log_dialog import LogDialog
        dlg = LogDialog(self.conn, parent=self)
        if dlg.exec():
            self.refresh()
            self.changed.emit()

    def _edit_row(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        log_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._edit(log_id)

    def _edit_selected(self) -> None:
        log_id = self._selected_log_id()
        if log_id is None:
            return
        self._edit(log_id)

    def _edit(self, log_id: int) -> None:
        from worklog.ui.log_dialog import LogDialog
        dlg = LogDialog(self.conn, parent=self, log_id=log_id)
        if dlg.exec():
            self.refresh()
            self.changed.emit()

    def _delete_selected(self) -> None:
        log_id = self._selected_log_id()
        if log_id is None:
            return
        confirm = QMessageBox.question(self, "Löschen?", "Diesen Eintrag wirklich löschen?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        repo.delete_log(self.conn, log_id)
        self.refresh()
        self.changed.emit()
