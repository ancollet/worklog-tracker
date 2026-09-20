"""Auswahldialog fürs Registrieren / Verbinden: Salesforce-Accounts oder offene Salesforce-Projekte.

The dialog only shows and picks. What is already registriert and what happens
with the chosen rows is decided by the registration service; the list is loaded
in a background thread. Salesforce IDs are never displayed.

Two modes: pick exactly one row (Account registrieren, Verbinden), or tick
several rows and set Service Type and Customer Request Type per row (Projekte
registrieren).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from worklog.services import salesforce as sf_client
from worklog.services import salesforce_registration as registration
from worklog.services.salesforce_settings import SERVICE_TYPES
from worklog.ui.salesforce_call import SalesforceCall, start_salesforce_call

_COL_NAME, _COL_SERVICE_TYPE, _COL_REQUEST_TYPE = range(3)


@dataclass(slots=True, frozen=True)
class ChoiceTexts:
    """The words of one use of the dialog."""

    title: str
    action_label: str
    intro: str
    loading: str
    nothing_found: str
    nothing_matches: str
    noun_plural: str


def account_texts(*, title: str, action_label: str) -> ChoiceTexts:
    return ChoiceTexts(
        title=title,
        action_label=action_label,
        intro="Accounts mit mindestens einem offenen Projekt:",
        loading="Lade Accounts aus Salesforce…",
        nothing_found="Kein Account mit offenen Projekten gefunden.",
        nothing_matches="Kein Account passt zu dieser Eingabe.",
        noun_plural="Accounts",
    )


def project_texts(customer_name: str, *, title: str, action_label: str) -> ChoiceTexts:
    return ChoiceTexts(
        title=title,
        action_label=action_label,
        intro=f"Offene Salesforce-Projekte von „{customer_name}“:",
        loading="Lade offene Projekte aus Salesforce…",
        nothing_found="Dieser Account hat keine offenen Projekte.",
        nothing_matches="Kein Projekt passt zu dieser Eingabe.",
        noun_plural="Projekten",
    )


class SalesforceChoiceDialog(QDialog):
    """`load(client)` fetches the records in the background; `choices(records)` marks
    what is already registriert (rows with `record`, `name`, `is_registered`,
    `registered_text`).

    `apply(...)` does the actual Registrieren/Verbinden; a RegistrationError it
    raises is shown here and the dialog stays open. Without `new_registration`
    it gets the one chosen record. With it (Mehrfachauswahl) every row starts
    from `new_registration(record)` and `apply` gets the list of
    ProjectRegistrations of the ticked rows.
    """

    def __init__(
        self,
        creds: sf_client.SalesforceCredentials,
        *,
        load: Callable[[object], list],
        choices: Callable[[list], list],
        apply: Callable[[object], object],
        texts: ChoiceTexts,
        new_registration: Optional[Callable[[object], registration.ProjectRegistration]] = None,
        client_factory=sf_client.SalesforceClient,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._creds = creds
        self._load_records = load
        self._choices = choices
        self._apply = apply
        self._texts = texts
        self._new_registration = new_registration
        self._multi = new_registration is not None
        self._client_factory = client_factory
        self._loading: SalesforceCall | None = None
        self._failed = False
        self.setWindowTitle(texts.title)
        self.setMinimumSize(640 if self._multi else 460, 420)

        intro = QLabel(texts.intro)
        intro.setWordWrap(True)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Nach Name filtern…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.choice_list = QTreeWidget()
        self.choice_list.setRootIsDecorated(False)
        self.choice_list.setUniformRowHeights(True)
        if self._multi:
            self.choice_list.setHeaderLabels(["Projekt", "Service Type", "Customer Request Type"])
            self.choice_list.setColumnWidth(_COL_NAME, 300)
            self.choice_list.setColumnWidth(_COL_SERVICE_TYPE, 130)
            self.choice_list.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
            self.choice_list.itemChanged.connect(self._on_item_changed)
        else:
            self.choice_list.setHeaderHidden(True)
            self.choice_list.itemSelectionChanged.connect(self._update_buttons)
            self.choice_list.itemDoubleClicked.connect(lambda _item, _col: self._apply_selected())
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.reload_btn = QPushButton("Erneut laden")
        self.reload_btn.setAutoDefault(False)
        self.reload_btn.clicked.connect(self._load)
        self.apply_btn = QPushButton(texts.action_label)
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
        outer.addWidget(self.choice_list, 1)
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
        self.choice_list.clear()
        self._failed = False
        self._set_status(self._texts.loading)
        self._loading = start_salesforce_call(
            self._creds,
            self._client_factory,
            self._load_records,
            self._on_loaded,
        )
        self._update_buttons()

    def _on_loaded(self, ok: bool, result) -> None:
        if self.sender() is not self._loading:
            return
        self._loading = None
        if not ok:
            self._failed = True
            self._set_status(f"Fehler: {result}", "error")
            self._update_buttons()
            return
        self.choice_list.blockSignals(True)
        for choice in self._choices(result):
            self._add_row(choice)
        self.choice_list.blockSignals(False)
        self._apply_filter()
        self._update_buttons()

    def _add_row(self, choice) -> None:
        item = QTreeWidgetItem([choice.name])
        item.setData(_COL_NAME, Qt.ItemDataRole.UserRole, choice.record)
        self.choice_list.addTopLevelItem(item)
        if choice.is_registered:
            item.setText(_COL_NAME, f"{choice.name} — {choice.registered_text}")
            item.setFlags(Qt.ItemFlag.NoItemFlags)   # greyed out, neither selectable nor tickable
            return
        if not self._multi:
            return
        start = self._new_registration(choice.record)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(_COL_NAME, Qt.CheckState.Unchecked)
        service_type = QComboBox()
        service_type.addItems(SERVICE_TYPES)
        service_type.setCurrentText(start.service_type)
        request_type = QLineEdit(start.customer_request_type)
        request_type.setPlaceholderText("optional, z.B. SOT-00348")
        for widget in (service_type, request_type):
            widget.setEnabled(False)   # only the ticked rows are filled in
        self.choice_list.setItemWidget(item, _COL_SERVICE_TYPE, service_type)
        self.choice_list.setItemWidget(item, _COL_REQUEST_TYPE, request_type)

    # ------------------ filter / selection ------------------

    def _items(self) -> list[QTreeWidgetItem]:
        return [self.choice_list.topLevelItem(row) for row in range(self.choice_list.topLevelItemCount())]

    def _apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().casefold()
        visible = 0
        for item in self._items():
            record = item.data(_COL_NAME, Qt.ItemDataRole.UserRole)
            hidden = bool(needle) and needle not in record.name.casefold()
            item.setHidden(hidden)
            if hidden and item.isSelected():
                item.setSelected(False)
            visible += not hidden
        if self._loading is None and not self._failed:
            total = self.choice_list.topLevelItemCount()
            if total == 0:
                self._set_status(self._texts.nothing_found)
            elif visible == 0:
                self._set_status(self._texts.nothing_matches)
            else:
                text = f"{visible} von {total} {self._texts.noun_plural}"
                ticked = len(self._ticked_items())
                self._set_status(text + (f" · {ticked} ausgewählt" if ticked else ""))

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        ticked = item.checkState(_COL_NAME) == Qt.CheckState.Checked
        for column in (_COL_SERVICE_TYPE, _COL_REQUEST_TYPE):
            widget = self.choice_list.itemWidget(item, column)
            if widget is not None:
                widget.setEnabled(ticked)
        self._apply_filter()
        self._update_buttons()

    def _ticked_items(self) -> list[QTreeWidgetItem]:
        # A ticked row stays chosen while the filter hides it.
        return [
            item for item in self._items()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            and item.checkState(_COL_NAME) == Qt.CheckState.Checked
        ]

    def _selected_record(self):
        items = [i for i in self.choice_list.selectedItems() if not i.isHidden()]
        return items[0].data(_COL_NAME, Qt.ItemDataRole.UserRole) if items else None

    def _registrations(self) -> list[registration.ProjectRegistration]:
        return [
            registration.ProjectRegistration(
                item.data(_COL_NAME, Qt.ItemDataRole.UserRole),
                self.choice_list.itemWidget(item, _COL_SERVICE_TYPE).currentText(),
                self.choice_list.itemWidget(item, _COL_REQUEST_TYPE).text(),
            )
            for item in self._ticked_items()
        ]

    def _chosen(self):
        """What `apply` gets; None/empty while nothing is chosen."""
        return self._registrations() if self._multi else self._selected_record()

    def _update_buttons(self) -> None:
        loading = self._loading is not None
        self.reload_btn.setEnabled(not loading)
        self.apply_btn.setEnabled(not loading and bool(self._chosen()))

    def _apply_selected(self) -> None:
        chosen = self._chosen()
        if not chosen or self._loading is not None:
            return
        try:
            self._apply(chosen)
        except registration.RegistrationError as exc:
            self._set_status(str(exc), "error")
            return
        self.accept()

    def keyPressEvent(self, event) -> None:
        # Enter in a text field must not trigger the default button by accident.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and isinstance(self.focusWidget(), QLineEdit)):
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # A still-running call may finish after the dialog is gone; it must not call back into us.
        if self._loading is not None:
            self._loading.finished_with.disconnect(self._on_loaded)
            self._loading = None
        super().done(result)
