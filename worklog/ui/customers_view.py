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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo

ROUNDING_CHOICES = [
    ("Default", None),
    ("Aus", 0),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("30 min", 30),
    ("60 min", 60),
]


class CustomersView(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kunde / Projekt", "Rundung"])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemSelectionChanged.connect(self._on_select)

        self.show_archived = QCheckBox("Archivierte anzeigen")
        self.show_archived.toggled.connect(self.refresh)

        self.add_customer_btn = QPushButton("+ Kunde")
        self.add_customer_btn.clicked.connect(self.add_customer)
        self.add_project_btn = QPushButton("+ Projekt")
        self.add_project_btn.clicked.connect(self.add_project)
        self.archive_btn = QPushButton("⌫ Archivieren / Aktivieren")
        self.archive_btn.clicked.connect(self.toggle_archive)

        # right-side detail form (project)
        self.detail_label = QLabel("Projekt-Details")
        self.detail_label.setStyleSheet("font-weight: bold;")
        self.name_input = QLineEdit()
        self.color_btn = QPushButton("Farbe wählen…")
        self.color_btn.clicked.connect(self._pick_color)
        self._color_value: str | None = None
        self.round_combo = QComboBox()
        for label, val in ROUNDING_CHOICES:
            self.round_combo.addItem(label, val)
        self.archived_check = QCheckBox("Archiviert")
        self.save_btn = QPushButton("Speichern")
        self.save_btn.clicked.connect(self._save_detail)

        # layout
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(self.show_archived)
        left.addWidget(self.tree, 1)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_customer_btn)
        btn_row.addWidget(self.add_project_btn)
        btn_row.addWidget(self.archive_btn)
        btn_row.addStretch(1)
        left.addLayout(btn_row)
        outer.addLayout(left, 2)

        right = QFormLayout()
        right.addRow(self.detail_label)
        right.addRow("Name:", self.name_input)
        right.addRow("Farbe:", self.color_btn)
        right.addRow("Rundung:", self.round_combo)
        right.addRow(self.archived_check)
        right.addRow(self.save_btn)
        right_w = QWidget()
        right_w.setLayout(right)
        outer.addWidget(right_w, 1)

        self.refresh()

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
            citem = QTreeWidgetItem([c.name + (" (archiviert)" if c.archived else ""), ""])
            citem.setData(0, Qt.ItemDataRole.UserRole, ("customer", c.id))
            self.tree.addTopLevelItem(citem)
            for p in per_customer.get(c.id, []):
                round_label = "Default"
                if p.round_minutes is not None:
                    round_label = f"{p.round_minutes} min" if p.round_minutes else "Aus"
                pitem = QTreeWidgetItem([
                    p.name + (" (archiviert)" if p.archived else ""),
                    round_label,
                ])
                pitem.setData(0, Qt.ItemDataRole.UserRole, ("project", p.id))
                if p.color:
                    pitem.setForeground(0, QColor(p.color))
                citem.addChild(pitem)
            citem.setExpanded(True)
        self._clear_detail()

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
            customer = next((c for c in repo.list_customers(self.conn, include_archived=True) if c.id == oid), None)
            if customer is None:
                return
            repo.update_customer(self.conn, customer.id, name=customer.name, archived=not customer.archived)
        elif kind == "project":
            proj = repo.get_project(self.conn, oid)
            if proj is None:
                return
            repo.update_project(
                self.conn, proj.id,
                name=proj.name, color=proj.color, round_minutes=proj.round_minutes,
                archived=not proj.archived,
            )
        self.refresh()
        self.changed.emit()

    # ------------------ detail panel ------------------

    def _on_select(self) -> None:
        kind, oid = self._selected()
        if kind != "project":
            self._clear_detail()
            return
        proj = repo.get_project(self.conn, oid)
        if proj is None:
            self._clear_detail()
            return
        self.name_input.setText(proj.name)
        self._color_value = proj.color
        self.color_btn.setText(proj.color or "Farbe wählen…")
        idx = self.round_combo.findData(proj.round_minutes)
        self.round_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.archived_check.setChecked(proj.archived)
        self.save_btn.setEnabled(True)
        self.save_btn.setProperty("project_id", proj.id)

    def _clear_detail(self) -> None:
        self.name_input.clear()
        self._color_value = None
        self.color_btn.setText("Farbe wählen…")
        self.round_combo.setCurrentIndex(0)
        self.archived_check.setChecked(False)
        self.save_btn.setEnabled(False)
        self.save_btn.setProperty("project_id", None)

    def _save_detail(self) -> None:
        pid = self.save_btn.property("project_id")
        if pid is None:
            return
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehler", "Name darf nicht leer sein.")
            return
        try:
            repo.update_project(
                self.conn, int(pid),
                name=name,
                color=self._color_value,
                round_minutes=self.round_combo.currentData(),
                archived=self.archived_check.isChecked(),
            )
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Projektname existiert beim Kunden bereits.")
            return
        self.refresh()
        self.changed.emit()

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
