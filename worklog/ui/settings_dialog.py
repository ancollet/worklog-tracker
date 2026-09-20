from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from worklog import repository as repo
from worklog.paths import autostart_desktop_path
from worklog.services import credentials, jira as jira_client
from worklog.ui.theme import DEFAULT_UI_THEME, SETTINGS_UI_THEME, THEMES, apply_theme

ROUNDING_CHOICES = [
    ("Aus", 0),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("30 min", 30),
    ("60 min", 60),
]

SETTINGS_JIRA_BASE_URL = "jira.base_url"
SETTINGS_JIRA_EMAIL = "jira.email"
SETTINGS_SF_INSTANCE_URL = "salesforce.instance_url"


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

        self.theme_combo = QComboBox()
        for label, val in THEMES:
            self.theme_combo.addItem(label, val)
        current_theme = repo.get_setting(conn, SETTINGS_UI_THEME, DEFAULT_UI_THEME)
        ti = self.theme_combo.findData(current_theme)
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)

        self.autostart_check = QCheckBox("Worklog beim Login starten")
        self.autostart_check.setChecked(autostart_desktop_path().exists())

        form = QFormLayout()
        form.addRow("Theme:", self.theme_combo)
        form.addRow("Default-Rundung:", self.round_combo)
        form.addRow("Default-Projekt:", self.default_project)
        form.addRow(self.autostart_check)

        # ---- Jira ----
        self.jira_base_url = QLineEdit(repo.get_setting(conn, SETTINGS_JIRA_BASE_URL, "") or "")
        self.jira_base_url.setPlaceholderText("https://your-domain.atlassian.net")
        self.jira_email = QLineEdit(repo.get_setting(conn, SETTINGS_JIRA_EMAIL, "") or "")
        self.jira_email.setPlaceholderText("dein.atlassian@account.email")
        self.jira_token = QLineEdit()
        self.jira_token.setEchoMode(QLineEdit.EchoMode.Password)
        try:
            existing_token = credentials.get_jira_token()
        except credentials.CredentialsUnavailableError:
            existing_token = None
        self._existing_jira_token = existing_token
        self.jira_token.setPlaceholderText(
            "(unverändert)" if existing_token else "Atlassian API-Token (id.atlassian.com)"
        )

        self.jira_test_btn = QPushButton("Verbindung testen")
        self.jira_test_btn.clicked.connect(self._test_jira)
        self.jira_status = QLabel("")
        self.jira_status.setStyleSheet("color: gray; font-size: 11px;")
        self.jira_status.setWordWrap(True)

        jira_form = QFormLayout()
        jira_form.addRow("Base-URL:", self.jira_base_url)
        jira_form.addRow("Email:", self.jira_email)
        jira_form.addRow("API-Token:", self.jira_token)
        test_row = QHBoxLayout()
        test_row.addWidget(self.jira_test_btn)
        test_row.addStretch(1)
        jira_form.addRow("", test_row)
        jira_form.addRow("", self.jira_status)
        jira_hint = QLabel(
            "Token erstellen unter id.atlassian.com → Manage profile → Security → API tokens. "
            "Token wird im OS-Keyring gespeichert, nicht in der DB."
        )
        jira_hint.setStyleSheet("color: gray; font-size: 11px;")
        jira_hint.setWordWrap(True)
        jira_form.addRow("", jira_hint)
        jira_group = QGroupBox("Jira")
        jira_group.setLayout(jira_form)

        # ---- Salesforce (Platzhalter, Auth folgt) ----
        self.sf_instance_url = QLineEdit(repo.get_setting(conn, SETTINGS_SF_INSTANCE_URL, "") or "")
        self.sf_instance_url.setPlaceholderText("https://your-domain.my.salesforce.com")
        sf_form = QFormLayout()
        sf_form.addRow("Instance-URL:", self.sf_instance_url)
        sf_hint = QLabel("Salesforce-Anbindung folgt — hier nur die Instance-URL.")
        sf_hint.setStyleSheet("color: gray; font-size: 11px;")
        sf_hint.setWordWrap(True)
        sf_form.addRow("", sf_hint)
        sf_group = QGroupBox("Salesforce")
        sf_group.setLayout(sf_form)

        self.setMinimumWidth(460)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addWidget(jira_group)
        outer.addWidget(sf_group)
        outer.addWidget(buttons)

    def _save(self) -> None:
        theme = self.theme_combo.currentData()
        repo.set_setting(self.conn, SETTINGS_UI_THEME, theme)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        repo.set_default_round_minutes(self.conn, int(self.round_combo.currentData()))
        default_project = self.default_project.currentData()
        if default_project is not None:
            repo.set_last_project(self.conn, int(default_project))
        repo.set_setting(self.conn, SETTINGS_JIRA_BASE_URL, self.jira_base_url.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_JIRA_EMAIL, self.jira_email.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_SF_INSTANCE_URL, self.sf_instance_url.text().strip() or None)

        new_token = self.jira_token.text()
        if new_token:
            try:
                credentials.set_jira_token(new_token)
            except credentials.CredentialsUnavailableError as exc:
                QMessageBox.warning(
                    self, "Keyring",
                    f"Konnte Jira-Token nicht im OS-Keyring speichern: {exc}",
                )

        try:
            self._apply_autostart(self.autostart_check.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Autostart", f"Konnte Autostart-Datei nicht schreiben: {exc}")
        self.accept()

    def _test_jira(self) -> None:
        base_url = self.jira_base_url.text().strip()
        email = self.jira_email.text().strip()
        token = self.jira_token.text() or self._existing_jira_token
        if not (base_url and email and token):
            self.jira_status.setText("Base-URL, Email und Token erforderlich.")
            self.jira_status.setStyleSheet("color: #b91c1c; font-size: 11px;")
            return
        self.jira_status.setText("Teste…")
        self.jira_status.setStyleSheet("color: gray; font-size: 11px;")
        self.jira_test_btn.setEnabled(False)
        try:
            who = jira_client.test_connection(
                jira_client.JiraCredentials(base_url=base_url, email=email, api_token=token)
            )
            self.jira_status.setText(f"OK — angemeldet als {who}.")
            self.jira_status.setStyleSheet("color: #15803d; font-size: 11px;")
        except jira_client.JiraError as exc:
            self.jira_status.setText(f"Fehler: {exc}")
            self.jira_status.setStyleSheet("color: #b91c1c; font-size: 11px;")
        finally:
            self.jira_test_btn.setEnabled(True)

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
