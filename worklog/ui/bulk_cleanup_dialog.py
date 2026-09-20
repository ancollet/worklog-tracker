"""Sammelaktion "Beschreibungen bereinigen…": Vorher/Nachher for several entries.

The dialog only drives `services.bulk_cleanup.CleanupRun`: one background call
per Eintrag, one after another, each filling its row when it comes back. Nothing
is saved before "Speichern", and then only the accepted descriptions.

`clean_descriptions` returns True when data changed, so the caller can refresh.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog.models import LogEntry
from worklog.services import bulk_cleanup as bulk
from worklog.services.llm_settings import LlmConfiguration
from worklog.ui.llm_cleanup import LlmCall, start_llm_call

COL_ACCEPT, COL_DATE, COL_TASK, COL_BEFORE, COL_AFTER, COL_STATUS = range(6)
HEADERS = ["Übernehmen", "Datum", "Task", "Vorher", "Nachher", "Status"]


def _status_text(row: bulk.CleanupRow) -> str:
    if row.status == bulk.SKIPPED:
        return f"Übersprungen: {row.skip_reason}"
    if row.status == bulk.ERROR:
        return f"Fehler – Beschreibung bleibt unverändert.\n{row.error}"
    return {
        bulk.PENDING: "wartet…",
        bulk.RUNNING: "wird bereinigt…",
        bulk.CLEANED: "Vorschlag",
        bulk.ALREADY_CLEAN: "bereits sauber",
        bulk.NOT_RUN: "nicht ausgeführt",
    }[row.status]


class BulkCleanupDialog(QDialog):
    """`clean(config, entry)` is the blocking call for one Eintrag (injectable for smoke tests)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        logs: list[LogEntry],
        config: LlmConfiguration,
        parent=None,
        *,
        clean: Callable[[LlmConfiguration, LogEntry], bulk.CleanupOutcome] = bulk.clean_entry,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Beschreibungen bereinigen")
        self.resize(980, 520)
        self.conn = conn
        self.run = bulk.CleanupRun(logs)
        self.saved_ids: list[int] = []
        self._config = config
        self._clean = clean
        self._call: Optional[LlmCall] = None
        self._call_row: Optional[bulk.CleanupRow] = None
        self._rendering = False

        self.table = QTableWidget(len(self.run.rows), len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        for col in (COL_ACCEPT, COL_DATE, COL_TASK):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for col in (COL_BEFORE, COL_AFTER, COL_STATUS):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        for index in range(len(self.run.rows)):
            for col in range(len(HEADERS)):
                self.table.setItem(index, col, QTableWidgetItem())
        self.table.itemChanged.connect(self._on_item_changed)

        self.progress = QProgressBar()
        self.progress.setRange(0, max(self.run.total_count, 1))
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        self.stop_btn = QPushButton("Stoppen")
        self.stop_btn.setToolTip("Keine weiteren Einträge mehr an das LLM senden")
        self.stop_btn.clicked.connect(self._stop)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.stop_btn)

        self.accept_all_btn = QPushButton("Alle übernehmen")
        self.accept_all_btn.clicked.connect(lambda: self._set_all(True))
        self.reject_all_btn = QPushButton("Alle verwerfen")
        self.reject_all_btn.clicked.connect(lambda: self._set_all(False))
        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("Speichern", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setToolTip("Schließen, ohne etwas zu speichern")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.accept_all_btn)
        bottom.addWidget(self.reject_all_btn)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Vorschläge des LLM – gespeichert wird erst mit „Speichern“, und nur die "
            "Beschreibung der Zeilen mit Haken bei „Übernehmen“."
        ))
        layout.addWidget(self.table, 1)
        layout.addLayout(progress_row)
        layout.addWidget(self.progress_label)
        layout.addLayout(bottom)

        self._render()
        self._start_next()

    # ------------------ the run ------------------

    @property
    def is_running(self) -> bool:
        return self._call is not None

    def _start_next(self) -> None:
        row = self.run.next_pending()
        if row is None:
            self._render()
            return
        config, clean, entry = self._config, self._clean, row.entry
        self._call_row = row
        self._call = start_llm_call(lambda: clean(config, entry), self._on_call_finished)
        self._render()

    def _on_call_finished(self, ok: bool, result) -> None:
        if self._call is None or self.sender() is not self._call:
            return
        row, self._call, self._call_row = self._call_row, None, None
        outcome = result if ok else bulk.CleanupOutcome(error=str(result))
        self.run.record(row, outcome)
        if self.run.abort_message is not None:
            self._render()
            QMessageBox.warning(
                self, "Bereinigen abgebrochen",
                "Der Lauf wurde abgebrochen, weitere Einträge wurden nicht gesendet:\n\n"
                f"{self.run.abort_message}",
            )
            return
        self._start_next()

    def _stop(self) -> None:
        """No further calls; the outcome of one in flight no longer reaches the dialog."""
        self.run.stop()
        if self._call is not None:
            self._call.finished_with.disconnect(self._on_call_finished)
            self._call = self._call_row = None
        self._render()

    def done(self, result: int) -> None:  # every way of closing ends up here
        self._stop()
        super().done(result)

    # ------------------ Übernehmen / Verwerfen ------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering or item.column() != COL_ACCEPT:
            return
        row = self.run.rows[item.row()]
        self.run.set_accepted(row, item.checkState() == Qt.CheckState.Checked)
        self._render()

    def _set_all(self, accepted: bool) -> None:
        if accepted:
            self.run.accept_all()
        else:
            self.run.reject_all()
        self._render()

    def _save(self) -> None:
        if not self.run.is_finished:
            return
        result = bulk.apply_accepted(self.conn, self.run)
        self.saved_ids = result.saved_ids
        if result.rejected:
            lines = "\n".join(
                f"• {row.entry.started_at:%d.%m.%Y} {row.entry.task or ''}: {reason}"
                for row, reason in result.rejected
            )
            QMessageBox.warning(
                self, "Nicht alles gespeichert",
                f"{len(result.saved_ids)} Beschreibung(en) gespeichert. "
                f"Unverändert geblieben:\n\n{lines}",
            )
        self.accept()

    # ------------------ rendering ------------------

    def _render(self) -> None:
        self._rendering = True
        try:
            for index, row in enumerate(self.run.rows):
                self._render_row(index, row)
        finally:
            self._rendering = False
        self.table.resizeRowsToContents()

        run = self.run
        count = {status: sum(r.status == status for r in run.rows) for status in (
            bulk.CLEANED, bulk.ALREADY_CLEAN, bulk.ERROR, bulk.SKIPPED, bulk.NOT_RUN)}
        self.progress.setValue(run.done_count)
        self.stop_btn.setEnabled(not run.is_finished)
        summary = (
            f"{count[bulk.CLEANED]} Vorschläge, {count[bulk.ALREADY_CLEAN]} bereits sauber, "
            f"{count[bulk.ERROR]} Fehler, {count[bulk.SKIPPED]} übersprungen"
        )
        if not run.is_finished:
            text = f"Bereinige… {run.done_count} von {run.total_count} Einträgen fertig ({summary})"
        elif run.abort_message is not None:
            text = f"Abgebrochen: {run.abort_message}"
        elif count[bulk.NOT_RUN]:
            text = f"Gestoppt – {summary}, {count[bulk.NOT_RUN]} nicht ausgeführt"
        else:
            text = f"Fertig – {summary}"
        self.progress_label.setText(text)

        accepted = len(run.accepted_rows())
        self.accept_all_btn.setEnabled(count[bulk.CLEANED] > 0)
        self.reject_all_btn.setEnabled(count[bulk.CLEANED] > 0)
        self.save_btn.setText(f"Speichern ({accepted})")
        self.save_btn.setEnabled(run.is_finished and accepted > 0)
        self.save_btn.setToolTip(
            "" if run.is_finished else "Erst möglich, wenn der Lauf fertig oder gestoppt ist"
        )

    def _render_row(self, index: int, row: bulk.CleanupRow) -> None:
        entry = row.entry
        date_text = f"{entry.started_at:%d.%m.%Y}" + ("" if entry.ended_at else "\n(läuft)")
        texts = {
            COL_ACCEPT: "",
            COL_DATE: date_text,
            COL_TASK: entry.task or "",
            COL_BEFORE: row.before,
            COL_AFTER: row.after or "",
            COL_STATUS: _status_text(row),
        }
        greyed = row.status == bulk.SKIPPED
        for col, text in texts.items():
            item = self.table.item(index, col)
            item.setText(text)
            item.setToolTip(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            item.setFlags(Qt.ItemFlag.NoItemFlags if greyed else Qt.ItemFlag.ItemIsEnabled)

        check = self.table.item(index, COL_ACCEPT)
        if row.status == bulk.CLEANED:
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Checked if row.accepted else Qt.CheckState.Unchecked
            )
            check.setToolTip("Haken = Übernehmen, kein Haken = Verwerfen")
        else:
            # No checkbox at all: there is nothing to accept in this row.
            check.setData(Qt.ItemDataRole.CheckStateRole, None)
            check.setFlags(Qt.ItemFlag.NoItemFlags)


def clean_descriptions(
    parent: QWidget, conn: sqlite3.Connection, logs: list[LogEntry], config: LlmConfiguration
) -> bool:
    """Open the Sammelaktion for `logs`; True when descriptions were saved."""
    dlg = BulkCleanupDialog(conn, logs, config, parent=parent)
    dlg.exec()
    return bool(dlg.saved_ids)
