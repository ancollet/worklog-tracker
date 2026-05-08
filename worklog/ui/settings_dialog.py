from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
)

from worklog import repository as repo
from worklog.paths import autostart_desktop_path

ROUNDING_CHOICES = [
    ("Aus", 0),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("30 min", 30),
    ("60 min", 60),
]


class SettingsDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(360)

        state = repo.get_app_state(conn)

        self.round_combo = QComboBox()
        for label, val in ROUNDING_CHOICES:
            self.round_combo.addItem(label, val)
        idx = self.round_combo.findData(state.default_round_minutes)
        self.round_combo.setCurrentIndex(idx if idx >= 0 else 3)

        self.default_project = QComboBox()
        self.default_project.addItem("(zuletzt benutzt)", None)
        for proj in repo.list_projects(conn):
            self.default_project.addItem(proj.display_name, proj.id)
        if state.last_project_id is not None:
            i = self.default_project.findData(state.last_project_id)
            if i >= 0:
                self.default_project.setCurrentIndex(i)

        self.autostart_check = QCheckBox("Worklog beim Login starten")
        self.autostart_check.setChecked(autostart_desktop_path().exists())

        form = QFormLayout()
        form.addRow("Default-Rundung:", self.round_combo)
        form.addRow("Default-Projekt:", self.default_project)
        form.addRow(self.autostart_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addWidget(buttons)

    def _save(self) -> None:
        repo.set_default_round_minutes(self.conn, int(self.round_combo.currentData()))
        default_project = self.default_project.currentData()
        if default_project is not None:
            repo.set_last_project(self.conn, int(default_project))
        try:
            self._apply_autostart(self.autostart_check.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Autostart", f"Konnte Autostart-Datei nicht schreiben: {exc}")
        self.accept()

    def _apply_autostart(self, enable: bool) -> None:
        path: Path = autostart_desktop_path()
        if enable:
            exec_cmd = f"{sys.executable} -m worklog"
            path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Worklog\n"
                f"Exec={exec_cmd}\n"
                "X-GNOME-Autostart-enabled=true\n"
                "NoDisplay=false\n"
                "Terminal=false\n"
            )
        else:
            path.unlink(missing_ok=True)
