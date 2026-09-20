from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from worklog import repository as repo
from worklog.services.timer import TimerService
from worklog.ui.completers import (
    make_description_completer,
    make_task_completer,
    refresh_description_completer,
    refresh_task_completer,
)


class QuickAddPopup(QDialog):
    """Frameless popup near the tray. Enter starts the timer."""

    MODE_START = "start"
    MODE_EDIT = "edit"
    MODE_SWITCH = "switch"

    def __init__(
        self,
        conn: sqlite3.Connection,
        timer: TimerService,
        parent=None,
        *,
        mode: str = MODE_START,
        anchor_global=None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.timer = timer
        self.mode = mode

        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(False)
        self.setMinimumWidth(420)

        title = {
            self.MODE_START: "⏱  Quick Start",
            self.MODE_EDIT: "✎  Aktuellen Eintrag bearbeiten",
            self.MODE_SWITCH: "↻  Task wechseln",
        }[mode]
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; padding: 4px;")

        self.project_combo = QComboBox()
        for proj in repo.list_projects(conn):
            self.project_combo.addItem(proj.display_name, proj.id)
        state = repo.get_app_state(conn)
        if state.last_project_id is not None:
            idx = self.project_combo.findData(state.last_project_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("z.B. ACME-123")
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Beschreibung")

        self.task_completer = make_task_completer(self, conn)
        self.desc_completer = make_description_completer(self, conn)
        self.task_input.setCompleter(self.task_completer)
        self.desc_input.setCompleter(self.desc_completer)

        self.cancel_btn = QPushButton("Esc · Abbrechen")
        self.start_btn = QPushButton({
            self.MODE_START: "⏎ Start ▶",
            self.MODE_EDIT: "⏎ Speichern",
            self.MODE_SWITCH: "⏎ Wechseln ↻",
        }[mode])
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._submit)
        self.cancel_btn.clicked.connect(self.reject)

        self.stop_btn = QPushButton("⏸ Stop")
        self.stop_btn.clicked.connect(self._stop_timer)
        self.stop_btn.setVisible(self.timer.is_running())

        self.add_hours_btn = QPushButton("⏰ Stunden nachtragen…")
        self.add_hours_btn.clicked.connect(self._open_add_log)

        outer = QVBoxLayout(self)
        outer.addWidget(self.title_label)
        form = QFormLayout()
        form.addRow("Projekt:", self.project_combo)
        form.addRow("Task:", self.task_input)
        form.addRow("Beschr.:", self.desc_input)
        outer.addLayout(form)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.start_btn)
        outer.addLayout(btn_row)
        outer.addWidget(self.add_hours_btn)

        # populate completers
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.task_input.editingFinished.connect(self._refresh_desc_suggestions)
        self._on_project_changed()

        # prefill if edit/switch
        if mode in (self.MODE_EDIT, self.MODE_SWITCH):
            cur = self.timer.current()
            if cur:
                idx = self.project_combo.findData(cur.project_id)
                if idx >= 0:
                    self.project_combo.setCurrentIndex(idx)
                self.task_input.setText(cur.task or "")
                self.desc_input.setText(cur.description or "")

        # enter on either input → submit
        self.task_input.returnPressed.connect(self._submit)
        self.desc_input.returnPressed.connect(self._submit)
        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

        # focus task field
        self.task_input.setFocus()

        if anchor_global is not None:
            self._move_near(anchor_global)

    def _on_project_changed(self) -> None:
        pid = self.project_combo.currentData()
        refresh_task_completer(self.task_completer, int(pid) if pid is not None else None)
        self._refresh_desc_suggestions()

    def _refresh_desc_suggestions(self) -> None:
        pid = self.project_combo.currentData()
        refresh_description_completer(
            self.desc_completer,
            int(pid) if pid is not None else None,
            self.task_input.text().strip() or None,
        )

    def _stop_timer(self) -> None:
        self.timer.stop()
        self.accept()

    def _open_add_log(self) -> None:
        from worklog.ui.log_dialog import LogDialog
        # Hide the popup first so the modal log dialog isn't anchored above it.
        self.hide()
        dlg = LogDialog(self.conn, parent=None)
        if dlg.exec():
            self.accept()
        else:
            self.reject()

    def _submit(self) -> None:
        pid = self.project_combo.currentData()
        if pid is None:
            self.reject()
            return
        task = self.task_input.text().strip() or None
        desc = self.desc_input.text().strip() or None
        if self.mode == self.MODE_EDIT:
            self.timer.update_running(project_id=int(pid), task=task, description=desc)
        else:
            # start or switch (start handles both — stops existing if any)
            self.timer.start(project_id=int(pid), task=task, description=desc)
        self.accept()

    def _move_near(self, global_pos) -> None:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        screen_geo = screen.availableGeometry()
        self.adjustSize()
        w, h = self.width(), self.height()
        x = global_pos.x() - w // 2
        y = global_pos.y() - h - 8 if global_pos.y() > screen_geo.center().y() else global_pos.y() + 8
        x = max(screen_geo.left() + 8, min(x, screen_geo.right() - w - 8))
        y = max(screen_geo.top() + 8, min(y, screen_geo.bottom() - h - 8))
        self.move(x, y)
