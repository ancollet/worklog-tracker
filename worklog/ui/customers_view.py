from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services import salesforce as sf_client
from worklog.services import salesforce_registration as registration
from worklog.services.salesforce_settings import SERVICE_TYPES, SalesforceConfiguration, load_configuration

ROUNDING_CHOICES = [
    ("Default", None),
    ("Aus", 0),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("30 min", 30),
    ("60 min", 60),
]

BOOKING_SYSTEM_CHOICES = [
    ("Keins", None),
    ("Jira (Issue-Worklogs)", "jira"),
    ("Salesforce (Project Related List)", "salesforce"),
]


class CustomersView(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        # Injectable for tests; loading the configuration never touches the network.
        self._sf_client_factory = sf_client.SalesforceClient
        self._load_sf_configuration = load_configuration

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kunde / Projekt", "System / Rundung", "Externe Ref."])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 140)
        self.tree.itemSelectionChanged.connect(self._on_select)

        self.show_archived = QCheckBox("Archivierte anzeigen")
        self.show_archived.toggled.connect(self.refresh)

        self.add_customer_btn = QPushButton("+ Kunde")
        self.add_customer_btn.clicked.connect(self.add_customer)
        self.add_project_btn = QPushButton("+ Projekt")
        self.add_project_btn.clicked.connect(self.add_project)
        self.archive_btn = QPushButton("⌫ Archivieren / Aktivieren")
        self.archive_btn.clicked.connect(self.toggle_archive)
        self.register_account_btn = QPushButton("Salesforce-Account registrieren…")
        self.register_account_btn.clicked.connect(self.register_salesforce_account)
        self.register_projects_btn = QPushButton("Projekte registrieren…")
        self.register_projects_btn.clicked.connect(self.register_salesforce_projects)

        # right-side stacked detail: customer / project / empty
        self.detail_stack = QStackedWidget()
        self._empty_page = QLabel("Kunde oder Projekt auswählen, um Details zu bearbeiten.")
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_page.setWordWrap(True)
        self.detail_stack.addWidget(self._empty_page)
        self.detail_stack.addWidget(self._build_customer_panel())
        self.detail_stack.addWidget(self._build_project_panel())

        # layout
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(self.show_archived)
        left.addWidget(self.tree, 1)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_customer_btn)
        btn_row.addWidget(self.add_project_btn)
        btn_row.addWidget(self.archive_btn)
        btn_row.addWidget(self.register_account_btn)
        btn_row.addWidget(self.register_projects_btn)
        btn_row.addStretch(1)
        left.addLayout(btn_row)
        outer.addLayout(left, 2)

        outer.addWidget(self.detail_stack, 1)

        self._current_customer_id: int | None = None
        self._current_project_id: int | None = None
        self._color_value: str | None = None
        self._sf_missing_text = ""   # why Salesforce is unavailable; empty when the connection is complete

        self.refresh()

    # ------------------ panels ------------------

    def _build_customer_panel(self) -> QWidget:
        self.cust_label = QLabel("Kunden-Details")
        self.cust_label.setStyleSheet("font-weight: bold;")
        self.cust_name = QLineEdit()
        self.cust_system = QComboBox()
        for label, val in BOOKING_SYSTEM_CHOICES:
            self.cust_system.addItem(label, val)
        self.cust_system.currentIndexChanged.connect(self._on_cust_system_changed)
        self.cust_external_ref = QLineEdit()
        self.cust_external_ref_label = QLabel("Externe Ref.:")
        # Salesforce-Kunden: the connected Account by name instead of a free text field for its ID.
        self.cust_account_label = QLabel("Salesforce-Account:")
        self.cust_account_name = QLabel("")
        self.cust_account_name.setWordWrap(True)
        self.cust_account_btn = QPushButton("Verbinden…")
        self.cust_account_btn.clicked.connect(self.connect_salesforce_account)
        self.cust_account_hint = QLabel("")
        self.cust_account_hint.setStyleSheet("color: gray; font-size: 11px;")
        self.cust_account_hint.setWordWrap(True)
        account_row = QHBoxLayout()
        account_row.setContentsMargins(0, 0, 0, 0)
        account_row.addWidget(self.cust_account_name, 1)
        account_row.addWidget(self.cust_account_btn)
        self.cust_account_row = QWidget()
        self.cust_account_row.setLayout(account_row)
        self.cust_archived = QCheckBox("Archiviert")
        self.cust_save_btn = QPushButton("Speichern")
        self.cust_save_btn.clicked.connect(self._save_customer)

        form = QFormLayout()
        form.addRow(self.cust_label)
        form.addRow("Name:", self.cust_name)
        form.addRow("Buchungssystem:", self.cust_system)
        form.addRow(self.cust_external_ref_label, self.cust_external_ref)
        form.addRow(self.cust_account_label, self.cust_account_row)
        form.addRow("", self.cust_account_hint)
        form.addRow(self.cust_archived)
        form.addRow(self.cust_save_btn)
        w = QWidget()
        w.setLayout(form)
        return w

    def _build_project_panel(self) -> QWidget:
        self.proj_label = QLabel("Projekt-Details")
        self.proj_label.setStyleSheet("font-weight: bold;")
        self.proj_name = QLineEdit()
        self.color_btn = QPushButton("Farbe wählen…")
        self.color_btn.clicked.connect(self._pick_color)
        self.proj_round = QComboBox()
        for label, val in ROUNDING_CHOICES:
            self.proj_round.addItem(label, val)
        self.proj_external_ref = QLineEdit()
        self.proj_external_ref_label = QLabel("Externe Ref.:")
        self.proj_external_ref_hint = QLabel("")
        self.proj_external_ref_hint.setStyleSheet("color: gray; font-size: 11px;")
        self.proj_external_ref_hint.setWordWrap(True)
        # Projekte of Salesforce-Kunden: the connected Salesforce-Projekt by name instead of a
        # free text field for its ID, plus what Buchungen of this Projekt start with.
        self.proj_sf_label = QLabel("Salesforce-Projekt:")
        self.proj_sf_name = QLabel("")
        self.proj_sf_name.setWordWrap(True)
        self.proj_sf_btn = QPushButton("Verbinden…")
        self.proj_sf_btn.clicked.connect(self.connect_salesforce_project)
        sf_row = QHBoxLayout()
        sf_row.setContentsMargins(0, 0, 0, 0)
        sf_row.addWidget(self.proj_sf_name, 1)
        sf_row.addWidget(self.proj_sf_btn)
        self.proj_sf_row = QWidget()
        self.proj_sf_row.setLayout(sf_row)
        self.proj_service_type_label = QLabel("Service Type:")
        self.proj_service_type = QComboBox()
        self.proj_service_type.addItems(SERVICE_TYPES)
        self.proj_request_type_label = QLabel("Customer Request Type:")
        self.proj_request_type = QLineEdit()
        self.proj_request_type.setPlaceholderText("optional, z.B. SOT-00348")
        self.proj_archived = QCheckBox("Archiviert")
        self.proj_save_btn = QPushButton("Speichern")
        self.proj_save_btn.clicked.connect(self._save_project)

        form = QFormLayout()
        form.addRow(self.proj_label)
        form.addRow("Name:", self.proj_name)
        form.addRow("Farbe:", self.color_btn)
        form.addRow("Rundung:", self.proj_round)
        form.addRow(self.proj_external_ref_label, self.proj_external_ref)
        form.addRow(self.proj_sf_label, self.proj_sf_row)
        form.addRow(self.proj_service_type_label, self.proj_service_type)
        form.addRow(self.proj_request_type_label, self.proj_request_type)
        form.addRow("", self.proj_external_ref_hint)
        form.addRow(self.proj_archived)
        form.addRow(self.proj_save_btn)
        w = QWidget()
        w.setLayout(form)
        return w

    # ------------------ public ------------------

    def refresh(self) -> None:
        include_archived = self.show_archived.isChecked()
        self.tree.clear()
        customers = repo.list_customers(self.conn, include_archived=include_archived)
        projects = repo.list_projects(self.conn, include_archived=include_archived)
        per_customer: dict[int, list] = {c.id: [] for c in customers}
        for p in projects:
            per_customer.setdefault(p.customer_id, []).append(p)
        for c in customers:
            system_label = _booking_system_label(c.booking_system)
            citem = QTreeWidgetItem([
                c.name + (" (archiviert)" if c.archived else ""),
                system_label,
                registration.external_reference_text(c),   # never a Salesforce ID
            ])
            citem.setData(0, Qt.ItemDataRole.UserRole, ("customer", c.id))
            self.tree.addTopLevelItem(citem)
            for p in per_customer.get(c.id, []):
                round_label = "Default"
                if p.round_minutes is not None:
                    round_label = f"{p.round_minutes} min" if p.round_minutes else "Aus"
                pitem = QTreeWidgetItem([
                    p.name + (" (archiviert)" if p.archived else ""),
                    round_label,
                    registration.project_reference_text(p),   # never a Salesforce ID
                ])
                pitem.setData(0, Qt.ItemDataRole.UserRole, ("project", p.id))
                if p.color:
                    pitem.setForeground(0, QColor(p.color))
                citem.addChild(pitem)
            citem.setExpanded(True)
        self._clear_detail()
        self._update_register_projects_button()
        if self.isVisible():   # refresh() runs on every data change; the keyring is only asked when shown
            self._update_salesforce_availability()

    # ------------------ actions ------------------

    def add_customer(self) -> None:
        name, ok = QInputDialog.getText(self, "Neuer Kunde", "Name:")
        if not ok or not name.strip():
            return
        try:
            repo.create_customer(self.conn, name.strip())
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Kunde existiert bereits.")
            return
        self.refresh()
        self.changed.emit()

    def add_project(self) -> None:
        customer_id = self._selected_customer_id()
        if customer_id is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst einen Kunden auswählen.")
            return
        name, ok = QInputDialog.getText(self, "Neues Projekt", "Name:")
        if not ok or not name.strip():
            return
        try:
            repo.create_project(self.conn, customer_id=customer_id, name=name.strip())
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Projektname existiert beim Kunden bereits.")
            return
        self.refresh()
        self.changed.emit()

    def toggle_archive(self) -> None:
        kind, oid = self._selected()
        if kind is None:
            return
        if kind == "customer":
            customer = repo.get_customer(self.conn, oid)
            if customer is None:
                return
            repo.update_customer(
                self.conn, customer.id,
                name=customer.name,
                archived=not customer.archived,
                booking_system=customer.booking_system,
                external_ref=customer.external_ref,
            )
        elif kind == "project":
            proj = repo.get_project(self.conn, oid)
            if proj is None:
                return
            repo.update_project(
                self.conn, proj.id,
                name=proj.name, color=proj.color, round_minutes=proj.round_minutes,
                archived=not proj.archived,
                external_ref=proj.external_ref,
            )
        self.refresh()
        self.changed.emit()

    # ------------------ detail panel ------------------

    def _on_select(self) -> None:
        kind, oid = self._selected()
        if kind == "customer":
            self._load_customer_detail(oid)
        elif kind == "project":
            self._load_project_detail(oid)
        else:
            self._clear_detail()
        self._update_register_projects_button()

    def _load_customer_detail(self, customer_id: int) -> None:
        c = repo.get_customer(self.conn, customer_id)
        if c is None:
            self._clear_detail()
            return
        self._current_customer_id = c.id
        self._current_project_id = None
        self.cust_name.setText(c.name)
        idx = self.cust_system.findData(c.booking_system)
        self.cust_system.setCurrentIndex(idx if idx >= 0 else 0)
        self.cust_external_ref.setText(registration.external_ref_field_text(c))
        account_text = registration.external_reference_text(c) if c.booking_system == "salesforce" else ""
        self.cust_account_name.setText(account_text or "(nicht verbunden)")
        self.cust_account_btn.setText("Ändern…" if account_text else "Verbinden…")
        self.cust_archived.setChecked(c.archived)
        self._apply_customer_system_visibility(c.booking_system)
        self.detail_stack.setCurrentIndex(1)

    def _load_project_detail(self, project_id: int) -> None:
        proj = repo.get_project(self.conn, project_id)
        if proj is None:
            self._clear_detail()
            return
        self._current_project_id = proj.id
        self._current_customer_id = None
        self.proj_name.setText(proj.name)
        self._color_value = proj.color
        self.color_btn.setText(proj.color or "Farbe wählen…")
        idx = self.proj_round.findData(proj.round_minutes)
        self.proj_round.setCurrentIndex(idx if idx >= 0 else 0)
        self.proj_external_ref.setText(registration.project_ref_field_text(proj))
        sf_project_text = (
            registration.project_reference_text(proj) if proj.customer_booking_system == "salesforce" else ""
        )
        self.proj_sf_name.setText(sf_project_text or "(nicht verbunden)")
        self.proj_sf_btn.setText("Ändern…" if sf_project_text else "Verbinden…")
        self.proj_service_type.setCurrentText(registration.service_type_of(self.conn, proj))
        self.proj_request_type.setText(proj.customer_request_type or "")
        self.proj_archived.setChecked(proj.archived)
        self._apply_project_external_ref_hint(proj.customer_booking_system)
        self.detail_stack.setCurrentIndex(2)

    def _clear_detail(self) -> None:
        self._current_customer_id = None
        self._current_project_id = None
        self._color_value = None
        self.detail_stack.setCurrentIndex(0)

    def _on_cust_system_changed(self) -> None:
        system = self.cust_system.currentData()
        self._apply_customer_system_visibility(system)

    def _apply_customer_system_visibility(self, system: str | None) -> None:
        # Jira: freies Textfeld (Default-Project-Key). Salesforce: Anzeige des verbundenen
        # Accounts plus "Verbinden…/Ändern…" — die Account-ID wird nie gezeigt oder getippt.
        show_text = system == "jira"
        self.cust_external_ref.setVisible(show_text)
        self.cust_external_ref_label.setVisible(show_text)
        self.cust_external_ref.setPlaceholderText(
            "z.B. DIS (Jira-Projekt-Key, optional)" if show_text else ""
        )
        show_account = system == "salesforce"
        self.cust_account_label.setVisible(show_account)
        self.cust_account_row.setVisible(show_account)
        self.cust_account_hint.setVisible(show_account and bool(self.cust_account_hint.text()))

    def _apply_project_external_ref_hint(self, customer_system: str | None) -> None:
        # Salesforce-Kunden: Anzeige des verbundenen Salesforce-Projekts plus "Verbinden…/Ändern…",
        # Service Type und Customer Request Type — die Projekt-ID wird nie gezeigt oder getippt.
        is_salesforce = customer_system == "salesforce"
        for widget in (self.proj_external_ref_label, self.proj_external_ref):
            widget.setVisible(not is_salesforce)
        for widget in (self.proj_sf_label, self.proj_sf_row, self.proj_service_type_label,
                       self.proj_service_type, self.proj_request_type_label, self.proj_request_type):
            widget.setVisible(is_salesforce)
        if is_salesforce:
            self.proj_external_ref.setPlaceholderText("")
            self.proj_external_ref_hint.setText(
                self._sf_missing_text
                or "Service Type und Customer Request Type sind die Vorbelegung beim Buchen in Salesforce."
            )
        elif customer_system == "jira":
            self.proj_external_ref.setPlaceholderText("(in Jira nicht nötig — Issue-Key wird im Log gesetzt)")
            self.proj_external_ref_hint.setText(
                "Für Jira-Kunden wird pro Log-Eintrag der Issue-Key (z.B. DIS-1234) im Task-Feld erfasst."
            )
        else:
            self.proj_external_ref.setPlaceholderText("")
            self.proj_external_ref_hint.setText(
                "Kein Buchungssystem am Kunden konfiguriert — externe Referenz optional."
            )

    def _save_customer(self) -> None:
        if self._current_customer_id is None:
            return
        name = self.cust_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehler", "Name darf nicht leer sein.")
            return
        stored = repo.get_customer(self.conn, self._current_customer_id)
        if stored is None:
            self.refresh()
            return
        system = self.cust_system.currentData()
        try:
            repo.update_customer(
                self.conn,
                self._current_customer_id,
                name=name,
                archived=self.cust_archived.isChecked(),
                booking_system=system,
                external_ref=registration.external_ref_to_save(stored, system, self.cust_external_ref.text()),
            )
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Kundenname existiert bereits.")
            return
        self.refresh()
        self.changed.emit()

    def _save_project(self) -> None:
        if self._current_project_id is None:
            return
        name = self.proj_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehler", "Name darf nicht leer sein.")
            return
        stored = repo.get_project(self.conn, self._current_project_id)
        if stored is None:
            self.refresh()
            return
        try:
            repo.update_project(
                self.conn, self._current_project_id,
                name=name,
                color=self._color_value,
                round_minutes=self.proj_round.currentData(),
                archived=self.proj_archived.isChecked(),
                external_ref=registration.project_ref_to_save(stored, self.proj_external_ref.text()),
            )
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Projektname existiert beim Kunden bereits.")
            return
        if stored.customer_booking_system == "salesforce":
            try:
                registration.change_booking_defaults(
                    self.conn, stored.id,
                    self.proj_service_type.currentText(), self.proj_request_type.text(),
                )
            except registration.RegistrationError as exc:
                QMessageBox.warning(self, "Fehler", str(exc))
                return
        self.refresh()
        self.changed.emit()

    # ------------------ Salesforce: Registrieren / Verbinden ------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_salesforce_availability()

    def _update_salesforce_availability(self) -> SalesforceConfiguration:
        """Without a complete connection Registrieren and Verbinden are disabled and say what is missing."""
        config = self._load_sf_configuration(self.conn)
        available = config.is_connection_complete
        missing = config.connection_missing_text
        self.register_account_btn.setEnabled(available)
        self.register_account_btn.setToolTip(
            "Accounts mit offenen Projekten aus Salesforce als Kunden registrieren." if available else missing
        )
        self.cust_account_btn.setEnabled(available)
        self.cust_account_btn.setToolTip("" if available else missing)
        self.cust_account_hint.setText("" if available else missing)
        self._apply_customer_system_visibility(self.cust_system.currentData())
        self._sf_missing_text = missing
        self.proj_sf_btn.setEnabled(available)
        self.proj_sf_btn.setToolTip("" if available else missing)
        self._update_register_projects_button()
        return config

    def _update_register_projects_button(self) -> None:
        """"Projekte registrieren…" belongs to a Salesforce-Kunde and needs the connection."""
        customer_id = self._selected_customer_id()
        customer = repo.get_customer(self.conn, customer_id) if customer_id is not None else None
        if self._sf_missing_text:
            enabled, tip = False, self._sf_missing_text
        elif customer is None or customer.booking_system != "salesforce":
            enabled, tip = False, "Zuerst einen Salesforce-Kunden (oder eines seiner Projekte) auswählen."
        elif not customer.external_ref:
            enabled, tip = False, "Der Kunde ist noch nicht mit einem Salesforce-Account verbunden."
        else:
            enabled, tip = True, f"Offene Salesforce-Projekte von „{customer.name}“ als Projekte registrieren."
        self.register_projects_btn.setEnabled(enabled)
        self.register_projects_btn.setToolTip(tip)

    def _choose_from_salesforce(self, *, load, choices, apply, texts, new_registration=None) -> None:
        config = self._update_salesforce_availability()
        if not config.is_connection_complete or config.credentials is None:
            QMessageBox.information(self, "Salesforce", config.connection_missing_text)
            return
        from worklog.ui.salesforce_choice_dialog import SalesforceChoiceDialog
        dlg = SalesforceChoiceDialog(
            config.credentials,
            load=load, choices=choices, apply=apply, texts=texts, new_registration=new_registration,
            client_factory=self._sf_client_factory, parent=self,
        )
        if dlg.exec():
            self.refresh()
            self.changed.emit()

    def _choose_salesforce_account(self, apply, *, title: str, action_label: str) -> None:
        from worklog.ui.salesforce_choice_dialog import account_texts
        self._choose_from_salesforce(
            load=lambda client: client.list_accounts_with_open_projects(),
            choices=lambda accounts: registration.account_choices(self.conn, accounts),
            apply=apply,
            texts=account_texts(title=title, action_label=action_label),
        )

    def _choose_salesforce_projects(self, customer_id: int, apply, *, title: str, action_label: str,
                                    several: bool) -> None:
        customer = repo.get_customer(self.conn, customer_id)
        if customer is None or customer.booking_system != "salesforce" or not customer.external_ref:
            QMessageBox.information(
                self, "Salesforce",
                "Der Kunde ist noch nicht mit einem Salesforce-Account verbunden. "
                "Zuerst den Kunden auswählen und dort „Verbinden…“ wählen.",
            )
            return
        from worklog.ui.salesforce_choice_dialog import project_texts
        account_id = customer.external_ref   # stays in the background, only the client sees it
        self._choose_from_salesforce(
            load=lambda client: client.list_open_projects(account_id),
            choices=lambda projects: registration.project_choices(self.conn, projects),
            apply=apply,
            texts=project_texts(customer.name, title=title, action_label=action_label),
            new_registration=(
                (lambda project: registration.new_project_registration(self.conn, project)) if several else None
            ),
        )

    def register_salesforce_account(self) -> None:
        self._choose_salesforce_account(
            lambda account: registration.register_account(self.conn, account),
            title="Salesforce-Account registrieren", action_label="Registrieren",
        )

    def connect_salesforce_account(self) -> None:
        customer_id = self._current_customer_id
        if customer_id is None:
            return
        self._choose_salesforce_account(
            lambda account: registration.connect_customer(self.conn, customer_id, account),
            title="Kunde mit Salesforce-Account verbinden", action_label="Verbinden",
        )

    def register_salesforce_projects(self) -> None:
        customer_id = self._selected_customer_id()
        if customer_id is None:
            return
        self._choose_salesforce_projects(
            customer_id,
            lambda registrations: registration.register_projects(self.conn, customer_id, registrations),
            title="Projekte registrieren", action_label="Registrieren", several=True,
        )

    def connect_salesforce_project(self) -> None:
        project = repo.get_project(self.conn, self._current_project_id) if self._current_project_id else None
        if project is None:
            return
        self._choose_salesforce_projects(
            project.customer_id,
            lambda salesforce_project: registration.connect_project(self.conn, project.id, salesforce_project),
            title="Projekt mit Salesforce-Projekt verbinden", action_label="Verbinden", several=False,
        )

    def _pick_color(self) -> None:
        initial = QColor(self._color_value) if self._color_value else QColor("#3B82F6")
        color = QColorDialog.getColor(initial, self, "Farbe wählen")
        if color.isValid():
            self._color_value = color.name()
            self.color_btn.setText(color.name())

    def _selected(self) -> tuple[str | None, int | None]:
        items = self.tree.selectedItems()
        if not items:
            return None, None
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None, None
        return data[0], data[1]

    def _selected_customer_id(self) -> int | None:
        kind, oid = self._selected()
        if kind == "customer":
            return oid
        if kind == "project":
            proj = repo.get_project(self.conn, oid)
            return proj.customer_id if proj else None
        return None


def _booking_system_label(value: str | None) -> str:
    for label, val in BOOKING_SYSTEM_CHOICES:
        if val == value:
            return label
    return value or ""
