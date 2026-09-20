from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
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
from worklog.services.entry_menu import target_log_ids
from worklog.services.rounding import format_hm_short
from worklog.services.timer import TimerService
from worklog.ui.entry_context_menu import (
    build_entry_context_menu,
    delete_entries,
    keep_selection_on_right_click,
)


class LogsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, timer: TimerService, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.timer = timer

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Datum", "Projekt", "Task", "Beschreibung", "Dauer", "Manuell", "Gebucht"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.cellDoubleClicked.connect(self._edit_row)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        keep_selection_on_right_click(self.table)

        self.add_btn = QPushButton("+ Add Log")
        self.add_btn.clicked.connect(self._add_log)
        self.resume_btn = QPushButton("▶ Fortsetzen")
        self.resume_btn.setToolTip("Neuen Timer mit Projekt/Task/Beschreibung dieses Eintrags starten")
        self.resume_btn.clicked.connect(self._resume_selected)
        self.edit_btn = QPushButton("✎ Bearbeiten")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = QPushButton("⌫ Löschen")
        self.delete_btn.clicked.connect(self._delete_selected)

        outer = QVBoxLayout(self)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.resume_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        outer.addLayout(row)

        # row -> LogEntry, so context menu can act without re-fetching.
        self._row_logs: list = []

        self.refresh()

    def refresh(self) -> None:
        logs = repo.list_logs(self.conn, limit=500)
        self._row_logs = list(logs)
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
            booked = _booked_cell(log)
            cells = [date_str, project, log.task or "", log.description or "", duration, manual, booked]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, log.id)
                if col in (4, 5, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 6 and log.external_worklog_id:
                    item.setForeground(QColor("#15803d"))
                    if log.external_worklog_url:
                        item.setToolTip(log.external_worklog_url)
                self.table.setItem(r, col, item)

    def _selected_logs(self) -> list:
        """Selected entries in visual (top-to-bottom) order."""
        rows = sorted(idx.row() for idx in self.table.selectionModel().selectedRows())
        return [self._row_logs[r] for r in rows if 0 <= r < len(self._row_logs)]

    def _selected_log(self):
        logs = self._selected_logs()
        return logs[0] if logs else None

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
        log = self._selected_log()
        if log is None:
            return
        self._edit(log.id)

    def _edit(self, log_id: int) -> None:
        from worklog.ui.log_dialog import LogDialog
        dlg = LogDialog(self.conn, parent=self, log_id=log_id)
        if dlg.exec():
            self.refresh()
            self.changed.emit()

    def _resume_selected(self) -> None:
        """Fortsetzen: start a new running entry from the selected one."""
        log = self._selected_log()
        if log is None:
            return
        self._resume(log)

    def _resume(self, log) -> None:
        # Starting never stops another entry (ADR-0001), so there is nothing to confirm.
        already_running = {entry.id for entry in self.timer.running_entries()}
        new_log = self.timer.start(
            project_id=log.project_id, task=log.task, description=log.description
        )
        if new_log.id in already_running:
            QMessageBox.information(self, "Läuft bereits", "Dieser Eintrag läuft bereits.")
            return
        # Carry over the flags so the continuation keeps the original's tags.
        for flag in log.flags:
            repo.set_log_flag(self.conn, new_log.id, flag.id, True)
        self.refresh()
        self.changed.emit()

    def _delete_selected(self) -> None:
        if delete_entries(self, self.conn, [log.id for log in self._selected_logs()]):
            self._after_change()

    # ------------------ context menu ------------------

    def _show_context_menu(self, pos: QPoint) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid() or not (0 <= idx.row() < len(self._row_logs)):
            return
        clicked = self._row_logs[idx.row()]
        by_id = {log.id: log for log in self._selected_logs()}
        target_ids = target_log_ids(clicked.id, list(by_id))
        by_id[clicked.id] = clicked
        logs = [by_id[i] for i in target_ids]

        resume_action = QAction("Fortsetzen ▶", self)
        resume_action.setEnabled(len(logs) == 1)
        resume_action.triggered.connect(lambda _checked=False: self._resume(logs[0]))
        menu = build_entry_context_menu(
            self, self.conn, logs,
            on_edit=self._edit,
            on_changed=self._after_change,
            leading_actions=[resume_action],
        )
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()


def _booked_cell(log) -> str:
    if log.external_worklog_id:
        return f"✓ {log.external_worklog_id}"
    if log.customer_booking_system == "jira":
        return "—"
    return ""
