"""Auswahldialog: einen Salesforce-Account mit offenen Projekten wählen (Registrieren / Verbinden).

The dialog only shows and picks. Which Accounts are already registriert and
what happens with the chosen one is decided by the registration service; the
list is loaded in a background thread. Salesforce IDs are never displayed.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from worklog.services import salesforce as sf_client
from worklog.services import salesforce_registration as registration
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call


class SalesforceAccountDialog(QDialog):
    """`apply(account)` does the actual Registrieren/Verbinden; a RegistrationError
    it raises is shown here and the dialog stays open."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        creds: sf_client.SalesforceCredentials,
        apply: Callable[[sf_client.SalesforceAccount], object],
        *,
        title: str = "Salesforce-Account registrieren",
        action_label: str = "Registrieren",
        client_factory=sf_client.SalesforceClient,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self._creds = creds
        self._apply = apply
        self._client_factory = client_factory
        self._loading: SalesforceCall | None = None
        self.setWindowTitle(title)
        self.setMinimumSize(460, 420)

        intro = QLabel("Accounts mit mindestens einem offenen Projekt:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Nach Name filtern…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.account_list = QListWidget()
        self.account_list.itemSelectionChanged.connect(self._update_buttons)
        self.account_list.itemDoubleClicked.connect(lambda _item: self._apply_selected())
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.reload_btn = QPushButton("Erneut laden")
        self.reload_btn.setAutoDefault(False)
        self.reload_btn.clicked.connect(self._load)
        self.apply_btn = QPushButton(action_label)
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._apply_selected)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reload_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(cancel_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(intro)
        outer.addWidget(self.filter_edit)
        outer.addWidget(self.account_list, 1)
        outer.addWidget(self.status)
        outer.addLayout(buttons)

        self._load()

    # ------------------ loading ------------------

    def _set_status(self, text: str, kind: str = "neutral") -> None:
        color = {"ok": "#15803d", "error": "#b91c1c"}.get(kind, "gray")
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _load(self) -> None:
        if self._loading is not None:
            return
        self.account_list.clear()
        self._set_status("Lade Accounts aus Salesforce…")
        self._loading = start_salesforce_call(
            self._creds,
            self._client_factory,
            lambda client: client.list_accounts_with_open_projects(),
            self._on_loaded,
        )
        self._update_buttons()

    def _on_loaded(self, ok: bool, result) -> None:
        if self.sender() is not self._loading:
            return
        self._loading = None
        if not ok:
            self._set_status(f"Fehler: {result}", "error")
            self._update_buttons()
            return
        for choice in registration.account_choices(self.conn, result):
            item = QListWidgetItem(choice.account.name)
            item.setData(Qt.ItemDataRole.UserRole, choice.account)
            if choice.is_registered:
                item.setText(f"{choice.account.name} — bereits registriert (Kunde „{choice.registered_as}“)")
                item.setFlags(Qt.ItemFlag.NoItemFlags)   # greyed out, not selectable
            self.account_list.addItem(item)
        self._apply_filter()
        self._update_buttons()

    # ------------------ filter / selection ------------------

    def _apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().casefold()
        visible = 0
        for row in range(self.account_list.count()):
            item = self.account_list.item(row)
            account = item.data(Qt.ItemDataRole.UserRole)
            hidden = bool(needle) and needle not in account.name.casefold()
            item.setHidden(hidden)
            if hidden and item.isSelected():
                item.setSelected(False)
            visible += not hidden
        if self._loading is None and not self.status.text().startswith("Fehler"):
            total = self.account_list.count()
            if total == 0:
                self._set_status("Kein Account mit offenen Projekten gefunden.")
            elif visible == 0:
                self._set_status("Kein Account passt zu dieser Eingabe.")
            else:
                self._set_status(f"{visible} von {total} Accounts")

    def _selected_account(self) -> sf_client.SalesforceAccount | None:
        items = [i for i in self.account_list.selectedItems() if not i.isHidden()]
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _update_buttons(self) -> None:
        loading = self._loading is not None
        self.reload_btn.setEnabled(not loading)
        self.apply_btn.setEnabled(not loading and self._selected_account() is not None)

    def _apply_selected(self) -> None:
        account = self._selected_account()
        if account is None or self._loading is not None:
            return
        try:
            self._apply(account)
        except registration.RegistrationError as exc:
            self._set_status(str(exc), "error")
            return
        self.accept()

    def keyPressEvent(self, event) -> None:
        # Enter in the filter field must not trigger the default button by accident.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.filter_edit.hasFocus():
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # A still-running call may finish after the dialog is gone; it must not call back into us.
        if self._loading is not None:
            self._loading.finished_with.disconnect(self._on_loaded)
            self._loading = None
        super().done(result)
