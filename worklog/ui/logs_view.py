from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, QPoint, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services.booking import booked_cell_text, booked_cell_tooltip
from worklog.services.entry_menu import plan_entry_menu, target_log_ids
from worklog.services.rounding import format_hm_short
from worklog.ui.entry_context_menu import (
    build_entry_context_menu,
    continue_entry,
    delete_entries,
    keep_selection_on_right_click,
)
from worklog.ui.theme import color


class LogsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn

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
        self.table.cellClicked.connect(self._open_booking_on_ctrl_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        keep_selection_on_right_click(self.table)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.add_btn = QPushButton("+ Add Log")
        self.add_btn.clicked.connect(self._add_log)
        self.continue_btn = QPushButton("▶ Fortsetzen")
        self.continue_btn.setToolTip(
            "Neuen laufenden Eintrag mit Projekt, Task und Beschreibung dieses Eintrags starten"
        )
        self.continue_btn.clicked.connect(self._continue_selected)
        self.edit_btn = QPushButton("✎ Bearbeiten")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = QPushButton("⌫ Löschen")
        self.delete_btn.clicked.connect(self._delete_selected)

        outer = QVBoxLayout(self)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.continue_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        outer.addLayout(row)

        # row -> LogEntry, so context menu can act without re-fetching.
        self._row_logs: list = []

        self.refresh()
        self._update_buttons()

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
            booked = booked_cell_text(log)
            cells = [date_str, project, log.task or "", log.description or "", duration, manual, booked]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, log.id)
                if col in (4, 5, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 6 and log.is_booked:
                    item.setForeground(QColor(color("success")))
                    item.setToolTip(booked_cell_tooltip(log))
                self.table.setItem(r, col, item)
        self._update_buttons()

    def _open_booking_on_ctrl_click(self, row: int, col: int) -> None:
        """Strg+Klick on "Gebucht" opens the record of the Buchung in the browser."""
        if col != 6 or not 0 <= row < len(self._row_logs):
            return
        if not QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            return
        log = self._row_logs[row]
        if log.is_booked and log.external_worklog_url:
            QDesktopServices.openUrl(QUrl(log.external_worklog_url))

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

    def _update_buttons(self) -> None:
        """Same enabled rules as the menu items, e.g. Fortsetzen: exactly one entry
        that is not running; Bearbeiten/Löschen: no gebuchter Eintrag (Sperr-Regel)."""
        logs = self._selected_logs()
        plan = plan_entry_menu(logs) if logs else None
        self.continue_btn.setEnabled(plan is not None and plan.can_continue)
        self.edit_btn.setEnabled(plan is not None and plan.can_edit)
        self.delete_btn.setEnabled(plan is not None and plan.can_delete)
        hint = (plan.locked_hint if plan is not None else None) or ""
        self.edit_btn.setToolTip(hint)
        self.delete_btn.setToolTip(hint)

    def _continue_selected(self) -> None:
        """Button "Fortsetzen": same operation as the context-menu item."""
        logs = self._selected_logs()
        if len(logs) != 1:
            return
        if continue_entry(self, self.conn, logs[0].id):
            self._after_change()

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

        menu = build_entry_context_menu(
            self, self.conn, logs,
            on_edit=self._edit,
            on_changed=self._after_change,
        )
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()
