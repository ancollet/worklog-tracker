from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
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
from worklog.services import credentials, jira as jira_client, salesforce as sf_client
from worklog.services.salesforce_settings import (
    SETTINGS_SF_CONSUMER_KEY,
    SETTINGS_SF_INSTANCE_URL,
)
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

# Connection tests that outlive their dialog are parked here until they finish,
# so a running QThread is never garbage-collected.
_running_connection_tests: set = set()


class _SalesforceConnectionTest(QThread):
    """Runs "Verbindung testen" off the UI thread. Emits (ok, text)."""

    finished_with = pyqtSignal(bool, str)

    def __init__(self, creds: sf_client.SalesforceCredentials, client_factory) -> None:
        super().__init__()
        self._creds = creds
        self._client_factory = client_factory

    def run(self) -> None:
        try:
            self._client_factory(self._creds).test_connection()
        except sf_client.SalesforceError as exc:
            self.finished_with.emit(False, str(exc))
        except Exception as exc:  # never let a worker thread die silently
            self.finished_with.emit(False, f"Unerwarteter Fehler: {exc}")
        else:
            self.finished_with.emit(True, "")


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

        # ---- Salesforce ----
        self.sf_instance_url = QLineEdit(repo.get_setting(conn, SETTINGS_SF_INSTANCE_URL, "") or "")
        self.sf_instance_url.setPlaceholderText("https://your-domain.my.salesforce.com")
        self.sf_consumer_key = QLineEdit(repo.get_setting(conn, SETTINGS_SF_CONSUMER_KEY, "") or "")
        self.sf_consumer_key.setPlaceholderText("Consumer Key der External Client App")
        self.sf_consumer_secret = QLineEdit()
        self.sf_consumer_secret.setEchoMode(QLineEdit.EchoMode.Password)
        sf_keyring_problem = ""
        try:
            existing_secret = credentials.get_salesforce_secret()
        except credentials.CredentialsUnavailableError as exc:
            existing_secret = None
            sf_keyring_problem = str(exc)
        self._existing_sf_secret = existing_secret
        self.sf_consumer_secret.setPlaceholderText(
            "(unverändert)" if existing_secret else "Consumer Secret der External Client App"
        )

        self.sf_test_btn = QPushButton("Verbindung testen")
        self.sf_test_btn.clicked.connect(self._test_salesforce)
        self.sf_status = QLabel("")
        self.sf_status.setWordWrap(True)
        self._sf_test: _SalesforceConnectionTest | None = None
        self._sf_client_factory = sf_client.SalesforceClient
        if sf_keyring_problem:
            self._set_sf_status(f"OS-Keyring nicht erreichbar: {sf_keyring_problem}", "error")
        else:
            self._set_sf_status("", "neutral")

        sf_form = QFormLayout()
        sf_form.addRow("Instance-URL:", self.sf_instance_url)
        sf_form.addRow("Consumer Key:", self.sf_consumer_key)
        sf_form.addRow("Consumer Secret:", self.sf_consumer_secret)
        sf_test_row = QHBoxLayout()
        sf_test_row.addWidget(self.sf_test_btn)
        sf_test_row.addStretch(1)
        sf_form.addRow("", sf_test_row)
        sf_form.addRow("", self.sf_status)
        sf_hint = QLabel(
            "Anmeldung über die External Client App mit dem gemeinsamen Integrations-User "
            "(Client-Credentials). Das Consumer Secret wird im OS-Keyring gespeichert, nicht in der DB."
        )
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
        repo.set_setting(self.conn, SETTINGS_SF_CONSUMER_KEY, self.sf_consumer_key.text().strip() or None)

        new_token = self.jira_token.text()
        if new_token:
            try:
                credentials.set_jira_token(new_token)
            except credentials.CredentialsUnavailableError as exc:
                QMessageBox.warning(
                    self, "Keyring",
                    f"Konnte Jira-Token nicht im OS-Keyring speichern: {exc}",
                )

        new_secret = self.sf_consumer_secret.text()
        if new_secret:
            try:
                credentials.set_salesforce_secret(new_secret)
            except credentials.CredentialsUnavailableError as exc:
                QMessageBox.warning(
                    self, "Keyring",
                    f"Konnte Salesforce Consumer Secret nicht im OS-Keyring speichern: {exc}",
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

    def _set_sf_status(self, text: str, kind: str) -> None:
        color = {"ok": "#15803d", "error": "#b91c1c"}.get(kind, "gray")
        self.sf_status.setText(text)
        self.sf_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _test_salesforce(self) -> None:
        """Test with what is typed into the dialog right now — saved or not."""
        instance_url = self.sf_instance_url.text().strip()
        consumer_key = self.sf_consumer_key.text().strip()
        secret = self.sf_consumer_secret.text() or self._existing_sf_secret
        if not (instance_url and consumer_key and secret):
            self._set_sf_status("Instance-URL, Consumer Key und Consumer Secret erforderlich.", "error")
            return
        self._set_sf_status("Teste…", "neutral")
        self.sf_test_btn.setEnabled(False)
        test = _SalesforceConnectionTest(
            sf_client.SalesforceCredentials(instance_url, consumer_key, secret),
            self._sf_client_factory,
        )
        test.finished_with.connect(self._on_sf_test_finished)
        test.finished.connect(lambda t=test: _running_connection_tests.discard(t))
        _running_connection_tests.add(test)
        self._sf_test = test
        test.start()

    def _on_sf_test_finished(self, ok: bool, text: str) -> None:
        if self.sender() is not self._sf_test:
            return
        self._sf_test = None
        self.sf_test_btn.setEnabled(True)
        if ok:
            self._set_sf_status("OK — Anmeldung mit dem Integrations-User erfolgreich.", "ok")
        else:
            self._set_sf_status(f"Fehler: {text}", "error")

    def done(self, result: int) -> None:
        # A still-running test may finish after the dialog is gone; it must not call back into us.
        if self._sf_test is not None:
            self._sf_test.finished_with.disconnect(self._on_sf_test_finished)
            self._sf_test = None
        super().done(result)

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
