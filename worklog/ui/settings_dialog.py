from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.paths import is_autostart_enabled, set_autostart
from worklog.services import credentials, jira as jira_client, salesforce as sf_client
from worklog.services import llm_cleanup
from worklog.services.llm_settings import (
    SETTINGS_LLM_DEPLOYMENT,
    SETTINGS_LLM_ENDPOINT,
    load_system_prompt,
    save_system_prompt,
)
from worklog.services.salesforce_settings import (
    SETTINGS_SF_CONSUMER_KEY,
    SETTINGS_SF_INSTANCE_URL,
    SERVICE_TYPES,
    LeistendePerson,
    load_default_service_type,
    load_leistende_person,
    save_default_service_type,
    save_leistende_person,
)
from worklog.ui.llm_cleanup import LlmCall, start_llm_call
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call
from worklog.ui.theme import (
    ACCENTS,
    DEFAULT_UI_THEME,
    SETTINGS_UI_ACCENT,
    SETTINGS_UI_THEME,
    THEMES,
    apply_theme,
    resolve_accent,
    set_role,
    set_status,
)

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

        self.accent_combo = QComboBox()
        for val, (label, _light, _dark) in ACCENTS.items():
            self.accent_combo.addItem(label, val)
        current_accent = resolve_accent(current_theme, repo.get_setting(conn, SETTINGS_UI_ACCENT))
        self.accent_combo.setCurrentIndex(self.accent_combo.findData(current_accent))

        self.autostart_check = QCheckBox("Worklog beim Login starten")
        self.autostart_check.setChecked(is_autostart_enabled())

        form = QFormLayout()
        form.addRow("Theme:", self.theme_combo)
        form.addRow("Akzentfarbe:", self.accent_combo)
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
        set_role(self.jira_status, "hint")
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
        set_role(jira_hint, "hint")
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
        self._sf_test: SalesforceCall | None = None
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

        # Leistende Person: chosen via search, shown by name, stored on "Speichern".
        self._sf_person: LeistendePerson | None = None
        self._sf_search: SalesforceCall | None = None
        self.sf_person_label = QLabel("")
        self.sf_person_label.setWordWrap(True)
        self.sf_person_remove_btn = QPushButton("Entfernen")
        self.sf_person_remove_btn.setAutoDefault(False)
        self.sf_person_remove_btn.clicked.connect(lambda: self._set_sf_person(None))
        self.sf_person_query = QLineEdit()
        self.sf_person_query.setPlaceholderText("Name oder E-Mail suchen…")
        self.sf_person_search_btn = QPushButton("Suchen")
        self.sf_person_search_btn.setAutoDefault(False)
        self.sf_person_search_btn.clicked.connect(self._search_sf_person)
        self.sf_person_results = QListWidget()
        self.sf_person_results.setMaximumHeight(110)
        self.sf_person_results.setVisible(False)
        self.sf_person_results.itemClicked.connect(self._choose_sf_person)
        self.sf_person_results.itemActivated.connect(self._choose_sf_person)
        self.sf_person_status = QLabel("")
        self.sf_person_status.setWordWrap(True)

        sf_person_row = QHBoxLayout()
        sf_person_row.addWidget(self.sf_person_label, 1)
        sf_person_row.addWidget(self.sf_person_remove_btn)
        sf_search_row = QHBoxLayout()
        sf_search_row.addWidget(self.sf_person_query, 1)
        sf_search_row.addWidget(self.sf_person_search_btn)
        sf_form.addRow("Leistende Person:", sf_person_row)
        sf_form.addRow("", sf_search_row)
        sf_form.addRow("", self.sf_person_results)
        sf_form.addRow("", self.sf_person_status)
        self.sf_default_service_type = QComboBox()
        self.sf_default_service_type.addItems(SERVICE_TYPES)
        self.sf_default_service_type.setCurrentText(load_default_service_type(conn))
        self.sf_default_service_type.setToolTip(
            "Vorbelegung beim Registrieren von Projekten; pro Projekt änderbar."
        )
        sf_form.addRow("Default Service Type:", self.sf_default_service_type)
        for sf_field in (self.sf_instance_url, self.sf_consumer_key, self.sf_consumer_secret):
            sf_field.textChanged.connect(self._update_sf_person_search_enabled)
        self._set_sf_person(load_leistende_person(conn))
        self._update_sf_person_search_enabled()
        sf_hint = QLabel(
            "Anmeldung über die External Client App mit dem gemeinsamen Integrations-User "
            "(Client-Credentials). Das Consumer Secret wird im OS-Keyring gespeichert, nicht in der DB."
        )
        set_role(sf_hint, "hint")
        sf_hint.setWordWrap(True)
        sf_form.addRow("", sf_hint)
        sf_group = QGroupBox("Salesforce")
        sf_group.setLayout(sf_form)

        # ---- LLM ----
        self.llm_endpoint = QLineEdit(repo.get_setting(conn, SETTINGS_LLM_ENDPOINT, "") or "")
        self.llm_endpoint.setPlaceholderText("https://your-resource.openai.azure.com")
        self.llm_deployment = QLineEdit(repo.get_setting(conn, SETTINGS_LLM_DEPLOYMENT, "") or "")
        self.llm_deployment.setPlaceholderText("Name des Modell-Deployments")
        self.llm_api_key = QLineEdit()
        self.llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        llm_keyring_problem = ""
        try:
            existing_llm_key = credentials.get_llm_api_key()
        except credentials.CredentialsUnavailableError as exc:
            existing_llm_key = None
            llm_keyring_problem = str(exc)
        self._existing_llm_key = existing_llm_key
        self.llm_api_key.setPlaceholderText(
            "(unverändert)" if existing_llm_key else "API-Key der Azure-OpenAI/Foundry-Ressource"
        )
        self.llm_prompt = QPlainTextEdit(load_system_prompt(conn))
        self.llm_prompt.setFixedHeight(180)
        self.llm_prompt.setTabChangesFocus(True)
        self.llm_prompt_reset_btn = QPushButton("Auf Standard zurücksetzen")
        self.llm_prompt_reset_btn.setAutoDefault(False)
        self.llm_prompt_reset_btn.clicked.connect(self._reset_llm_prompt)
        self.llm_test_btn = QPushButton("Verbindung testen")
        self.llm_test_btn.setAutoDefault(False)
        self.llm_test_btn.clicked.connect(self._test_llm)
        self.llm_status = QLabel("")
        self.llm_status.setWordWrap(True)
        self._llm_test: LlmCall | None = None
        self._llm_test_connection = llm_cleanup.test_connection
        if llm_keyring_problem:
            self._set_llm_status(f"OS-Keyring nicht erreichbar: {llm_keyring_problem}", "error")
        else:
            self._set_llm_status("", "neutral")

        llm_form = QFormLayout()
        llm_form.addRow("Endpoint-URL:", self.llm_endpoint)
        llm_form.addRow("Deployment-Name:", self.llm_deployment)
        llm_form.addRow("API-Key:", self.llm_api_key)
        llm_form.addRow("Systemprompt:", self.llm_prompt)
        llm_button_row = QHBoxLayout()
        llm_button_row.addWidget(self.llm_prompt_reset_btn)
        llm_button_row.addWidget(self.llm_test_btn)
        llm_button_row.addStretch(1)
        llm_form.addRow("", llm_button_row)
        llm_form.addRow("", self.llm_status)
        llm_hint = QLabel(
            "Azure OpenAI / Foundry (v1-Schnittstelle). Gesendet werden nur Systemprompt, Task und "
            "Beschreibung. Der API-Key wird im OS-Keyring gespeichert, nicht in der DB."
        )
        set_role(llm_hint, "hint")
        llm_hint.setWordWrap(True)
        llm_form.addRow("", llm_hint)
        llm_group = QGroupBox("LLM")
        llm_group.setLayout(llm_form)

        self.setMinimumWidth(460)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        # One tab per section: stacked, the sections no longer fit on a laptop screen.
        tabs = QTabWidget()
        for title, content in (
            ("Allgemein", form), ("Jira", jira_group), ("Salesforce", sf_group), ("LLM", llm_group),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            if isinstance(content, QFormLayout):
                page_layout.addLayout(content)
            else:
                page_layout.addWidget(content)
            page_layout.addStretch(1)
            tabs.addTab(page, title)

        outer = QVBoxLayout(self)
        outer.addWidget(tabs)
        outer.addWidget(buttons)

    def _save(self) -> None:
        theme = self.theme_combo.currentData()
        accent = self.accent_combo.currentData()
        repo.set_setting(self.conn, SETTINGS_UI_THEME, theme)
        repo.set_setting(self.conn, SETTINGS_UI_ACCENT, accent)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme, accent)
        repo.set_default_round_minutes(self.conn, int(self.round_combo.currentData()))
        default_project = self.default_project.currentData()
        if default_project is not None:
            repo.set_last_project(self.conn, int(default_project))
        repo.set_setting(self.conn, SETTINGS_JIRA_BASE_URL, self.jira_base_url.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_JIRA_EMAIL, self.jira_email.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_SF_INSTANCE_URL, self.sf_instance_url.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_SF_CONSUMER_KEY, self.sf_consumer_key.text().strip() or None)
        save_leistende_person(self.conn, self._sf_person)
        save_default_service_type(self.conn, self.sf_default_service_type.currentText())

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

        repo.set_setting(self.conn, SETTINGS_LLM_ENDPOINT, self.llm_endpoint.text().strip() or None)
        repo.set_setting(self.conn, SETTINGS_LLM_DEPLOYMENT, self.llm_deployment.text().strip() or None)
        # Only a deviation from the default is stored; after "Zurücksetzen" it is deleted.
        save_system_prompt(self.conn, self.llm_prompt.toPlainText())
        new_llm_key = self.llm_api_key.text()
        if new_llm_key:
            try:
                credentials.set_llm_api_key(new_llm_key)
            except credentials.CredentialsUnavailableError as exc:
                QMessageBox.warning(
                    self, "Keyring",
                    f"Konnte LLM-API-Key nicht im OS-Keyring speichern: {exc}",
                )

        try:
            set_autostart(self.autostart_check.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Autostart", f"Konnte Autostart-Eintrag nicht schreiben: {exc}")
        self.accept()

    def _test_jira(self) -> None:
        base_url = self.jira_base_url.text().strip()
        email = self.jira_email.text().strip()
        token = self.jira_token.text() or self._existing_jira_token
        if not (base_url and email and token):
            self.jira_status.setText("Base-URL, Email und Token erforderlich.")
            set_status(self.jira_status, "error")
            return
        self.jira_status.setText("Teste…")
        set_role(self.jira_status, "hint")
        self.jira_test_btn.setEnabled(False)
        try:
            who = jira_client.test_connection(
                jira_client.JiraCredentials(base_url=base_url, email=email, api_token=token)
            )
            self.jira_status.setText(f"OK — angemeldet als {who}.")
            set_status(self.jira_status, "ok")
        except jira_client.JiraError as exc:
            self.jira_status.setText(f"Fehler: {exc}")
            set_status(self.jira_status, "error")
        finally:
            self.jira_test_btn.setEnabled(True)

    def _set_sf_status(self, text: str, kind: str) -> None:
        self.sf_status.setText(text)
        set_status(self.sf_status, kind)

    def _sf_connection_input(self) -> tuple[sf_client.SalesforceCredentials | None, list[str]]:
        """What is typed into the dialog right now — saved or not — and what is missing."""
        instance_url = self.sf_instance_url.text().strip()
        consumer_key = self.sf_consumer_key.text().strip()
        secret = self.sf_consumer_secret.text() or self._existing_sf_secret
        missing = [name for name, value in (
            ("Instance-URL", instance_url), ("Consumer Key", consumer_key), ("Consumer Secret", secret),
        ) if not value]
        if missing:
            return None, missing
        return sf_client.SalesforceCredentials(instance_url, consumer_key, secret), []

    def _start_sf_call(self, creds: sf_client.SalesforceCredentials, work, on_finished) -> SalesforceCall:
        return start_salesforce_call(creds, self._sf_client_factory, work, on_finished)

    def _test_salesforce(self) -> None:
        creds, _missing = self._sf_connection_input()
        if creds is None:
            self._set_sf_status("Instance-URL, Consumer Key und Consumer Secret erforderlich.", "error")
            return
        self._set_sf_status("Teste…", "neutral")
        self.sf_test_btn.setEnabled(False)
        self._sf_test = self._start_sf_call(
            creds, lambda client: client.test_connection(), self._on_sf_test_finished
        )

    def _on_sf_test_finished(self, ok: bool, result) -> None:
        if self.sender() is not self._sf_test:
            return
        self._sf_test = None
        self.sf_test_btn.setEnabled(True)
        if ok:
            self._set_sf_status("OK — Anmeldung mit dem Integrations-User erfolgreich.", "ok")
        else:
            self._set_sf_status(f"Fehler: {result}", "error")

    # ---- leistende Person ----

    def _set_sf_person_status(self, text: str, kind: str = "neutral") -> None:
        self.sf_person_status.setText(text)
        set_status(self.sf_person_status, kind)

    def _set_sf_person(self, person: LeistendePerson | None) -> None:
        self._sf_person = person
        self.sf_person_label.setText(person.display_text if person else "(nicht hinterlegt)")
        self.sf_person_remove_btn.setEnabled(person is not None)

    def _update_sf_person_search_enabled(self) -> None:
        _creds, missing = self._sf_connection_input()
        searching = self._sf_search is not None
        self.sf_person_query.setEnabled(not missing)
        self.sf_person_search_btn.setEnabled(not missing and not searching)
        if missing:
            self.sf_person_results.setVisible(False)
            self._set_sf_person_status(
                "Suche nicht möglich, solange die Verbindung unvollständig ist. Es fehlt: "
                + ", ".join(missing) + "."
            )
        elif self.sf_person_status.text().startswith("Suche nicht möglich"):
            self._set_sf_person_status("")

    def _search_sf_person(self) -> None:
        creds, _missing = self._sf_connection_input()
        if creds is None or self._sf_search is not None:
            return
        text = self.sf_person_query.text().strip()
        if not text:
            self._set_sf_person_status("Bitte Name oder E-Mail eingeben.", "error")
            return
        self._set_sf_person_status("Suche…")
        self._sf_search = self._start_sf_call(
            creds, lambda client: client.search_users(text), self._on_sf_search_finished
        )
        self._update_sf_person_search_enabled()

    def _on_sf_search_finished(self, ok: bool, result) -> None:
        if self.sender() is not self._sf_search:
            return
        self._sf_search = None
        self._update_sf_person_search_enabled()
        self.sf_person_results.clear()
        if not ok:
            self.sf_person_results.setVisible(False)
            self._set_sf_person_status(f"Fehler: {result}", "error")
            return
        for user in result:
            person = LeistendePerson(id=user.id, name=user.name, email=user.email)
            item = QListWidgetItem(person.display_text)
            item.setData(Qt.ItemDataRole.UserRole, person)
            self.sf_person_results.addItem(item)
        self.sf_person_results.setVisible(bool(result))
        if result:
            self._set_sf_person_status("Person in der Liste anklicken, um sie zu übernehmen.")
        else:
            self._set_sf_person_status("Keine Person zu dieser Eingabe gefunden.")

    def _choose_sf_person(self, item: QListWidgetItem) -> None:
        person = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(person, LeistendePerson):
            self._set_sf_person(person)
            self._set_sf_person_status(
                f"Ausgewählt: {person.display_text} — wird mit „Speichern“ hinterlegt.", "ok"
            )

    # ---- LLM ----

    def _set_llm_status(self, text: str, kind: str) -> None:
        self.llm_status.setText(text)
        set_status(self.llm_status, kind)

    def _reset_llm_prompt(self) -> None:
        self.llm_prompt.setPlainText(llm_cleanup.DEFAULT_SYSTEM_PROMPT)
        self._set_llm_status("Standardprompt eingesetzt — wird mit „Speichern“ übernommen.", "neutral")

    def _test_llm(self) -> None:
        # What is typed into the dialog right now — saved or not.
        endpoint = self.llm_endpoint.text().strip()
        deployment = self.llm_deployment.text().strip()
        api_key = self.llm_api_key.text() or self._existing_llm_key
        if not (endpoint and deployment and api_key):
            self._set_llm_status("Endpoint-URL, Deployment-Name und API-Key erforderlich.", "error")
            return
        creds = llm_cleanup.LlmCredentials(endpoint, deployment, api_key)
        test_connection = self._llm_test_connection
        self._set_llm_status("Teste…", "neutral")
        self.llm_test_btn.setEnabled(False)
        self._llm_test = start_llm_call(lambda: test_connection(creds), self._on_llm_test_finished)

    def _on_llm_test_finished(self, ok: bool, result) -> None:
        if self.sender() is not self._llm_test:
            return
        self._llm_test = None
        self.llm_test_btn.setEnabled(True)
        if ok:
            self._set_llm_status(f"OK — das Modell antwortet ({result}).", "ok")
        else:
            self._set_llm_status(f"Fehler: {result}", "error")

    def keyPressEvent(self, event) -> None:
        # Enter in the search field searches; it must not trigger "Speichern".
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.sf_person_query.hasFocus():
            self._search_sf_person()
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # A still-running call may finish after the dialog is gone; it must not call back into us.
        if self._sf_test is not None:
            self._sf_test.finished_with.disconnect(self._on_sf_test_finished)
            self._sf_test = None
        if self._sf_search is not None:
            self._sf_search.finished_with.disconnect(self._on_sf_search_finished)
            self._sf_search = None
        if self._llm_test is not None:
            self._llm_test.finished_with.disconnect(self._on_llm_test_finished)
            self._llm_test = None
        super().done(result)

