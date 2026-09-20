from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services import credentials, jira as jira_client
from worklog.services.rounding import format_hm_short
from worklog.services.timer import TimerService
from worklog.ui.settings_dialog import (
    SETTINGS_JIRA_BASE_URL,
    SETTINGS_JIRA_EMAIL,
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
        self.table.cellDoubleClicked.connect(self._edit_row)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

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

    def _selected_log_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_log(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._row_logs):
            return self._row_logs[idx]
        return None

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

    def _resume_selected(self) -> None:
        """Clone the selected entry into a fresh, now-running timer."""
        log = self._selected_log()
        if log is None:
            return
        if self.timer.is_running():
            confirm = QMessageBox.question(
                self, "Timer läuft",
                "Es läuft bereits ein Timer. Diesen stoppen und den Eintrag fortsetzen?",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        new_log = self.timer.start(
            project_id=log.project_id, task=log.task, description=log.description
        )
        # Carry over the flags so the continuation keeps the original's tags.
        for flag in log.flags:
            repo.set_log_flag(self.conn, new_log.id, flag.id, True)
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

    # ------------------ context menu ------------------

    def _show_context_menu(self, pos: QPoint) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        # Make sure the clicked row is also selected.
        self.table.selectRow(idx.row())
        log = self._selected_log()
        if log is None:
            return

        menu = QMenu(self)
        resume_action = QAction("Fortsetzen ▶", self)
        resume_action.triggered.connect(self._resume_selected)
        menu.addAction(resume_action)
        edit_action = QAction("Bearbeiten…", self)
        edit_action.triggered.connect(self._edit_selected)
        menu.addAction(edit_action)

        if log.customer_booking_system == "jira":
            menu.addSeparator()
            if log.external_worklog_id:
                unbook = QAction("Jira-Buchung lokal entfernen…", self)
                unbook.triggered.connect(lambda: self._clear_jira_booking(log.id))
                menu.addAction(unbook)
            else:
                book = QAction("In Jira buchen…", self)
                book.triggered.connect(lambda: self._book_jira(log.id))
                menu.addAction(book)

        menu.addSeparator()
        delete = QAction("Löschen", self)
        delete.triggered.connect(self._delete_selected)
        menu.addAction(delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------ jira booking ------------------

    def _book_jira(self, log_id: int) -> None:
        log = repo.get_log(self.conn, log_id)
        if log is None:
            return
        if log.external_worklog_id:
            QMessageBox.information(
                self, "Bereits gebucht",
                f"Dieser Eintrag ist bereits gebucht (Worklog-ID {log.external_worklog_id}).",
            )
            return

        issue_key = jira_client.extract_issue_key(log.task)
        if not issue_key:
            QMessageBox.warning(
                self, "Kein Issue-Key",
                "Im Task-Feld wurde kein Jira-Issue-Key (z.B. DIS-1234) gefunden.",
            )
            return

        duration = log.duration_seconds or 0
        if duration <= 0:
            QMessageBox.warning(self, "Keine Dauer", "Dieser Eintrag hat keine gebuchte Dauer.")
            return

        base_url = repo.get_setting(self.conn, SETTINGS_JIRA_BASE_URL, "") or ""
        email = repo.get_setting(self.conn, SETTINGS_JIRA_EMAIL, "") or ""
        try:
            token = credentials.get_jira_token()
        except credentials.CredentialsUnavailableError as exc:
            QMessageBox.critical(self, "Keyring", f"Konnte Token nicht laden: {exc}")
            return
        if not (base_url and email and token):
            QMessageBox.warning(
                self, "Jira nicht konfiguriert",
                "Bitte zuerst Jira-Base-URL, Email und API-Token in den Einstellungen hinterlegen.",
            )
            return

        confirm = QMessageBox.question(
            self, "In Jira buchen?",
            f"{format_hm_short(duration)} auf Issue {issue_key} buchen?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        creds = jira_client.JiraCredentials(base_url=base_url, email=email, api_token=token)
        try:
            result = jira_client.add_worklog(
                creds,
                issue_key=issue_key,
                started=log.started_at,
                time_spent_seconds=duration,
                comment=log.description or None,
            )
        except jira_client.JiraError as exc:
            QMessageBox.critical(self, "Buchung fehlgeschlagen", str(exc))
            return

        repo.set_log_external_ref(
            self.conn, log.id,
            worklog_id=result.worklog_id,
            worklog_url=result.issue_browse_url,
            synced_at_iso=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        )
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self, "Gebucht",
            f"Worklog {result.worklog_id} auf {result.issue_key} angelegt.",
        )

    def _clear_jira_booking(self, log_id: int) -> None:
        confirm = QMessageBox.question(
            self, "Lokal entfernen?",
            "Nur die lokale Buchungs-Referenz löschen. Der Worklog in Jira bleibt bestehen "
            "und muss dort manuell entfernt werden. Fortfahren?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        repo.set_log_external_ref(self.conn, log_id, worklog_id=None, worklog_url=None, synced_at_iso=None)
        self.refresh()
        self.changed.emit()


def _booked_cell(log) -> str:
    if log.external_worklog_id:
        return f"✓ {log.external_worklog_id}"
    if log.customer_booking_system == "jira":
        return "—"
    return ""
