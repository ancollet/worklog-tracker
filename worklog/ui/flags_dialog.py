from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from worklog import repository as repo

DEFAULT_COLOR = "#9CA3AF"


class FlagsDialog(QDialog):
    """CRUD dialog for user-defined flags (gebucht, invoiced, canceled, …)."""

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Flags verwalten")
        self.resize(480, 360)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Farbe", "Sortierung"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.add_btn = QPushButton("+ Neuer Flag")
        self.add_btn.clicked.connect(self._add)
        self.color_btn = QPushButton("Farbe wählen…")
        self.color_btn.clicked.connect(self._pick_color)
        self.delete_btn = QPushButton("⌫ Löschen")
        self.delete_btn.clicked.connect(self._delete)

        outer = QVBoxLayout(self)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.color_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        outer.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

        self._loading = False
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for flag in repo.list_flags(self.conn):
            r = self.table.rowCount()
            self.table.insertRow(r)

            name_item = QTableWidgetItem(flag.name)
            name_item.setData(Qt.ItemDataRole.UserRole, flag.id)
            self.table.setItem(r, 0, name_item)

            color_item = QTableWidgetItem(flag.color or "")
            color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if flag.color:
                color_item.setBackground(QColor(flag.color))
            self.table.setItem(r, 1, color_item)

            order_item = QTableWidgetItem(str(flag.sort_order))
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 2, order_item)
        self._loading = False

    # ------------------ actions ------------------

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Neuer Flag", "Name:")
        if not ok or not name.strip():
            return
        try:
            repo.create_flag(self.conn, name=name.strip(), color=DEFAULT_COLOR, sort_order=0)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Flag mit diesem Namen existiert bereits.")
            return
        self.refresh()

    def _delete(self) -> None:
        flag_id = self._selected_flag_id()
        if flag_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Löschen?",
            "Flag wirklich löschen? Alle Markierungen an Einträgen werden ebenfalls entfernt.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        repo.delete_flag(self.conn, flag_id)
        self.refresh()

    def _pick_color(self) -> None:
        flag_id = self._selected_flag_id()
        if flag_id is None:
            return
        flag = next((f for f in repo.list_flags(self.conn) if f.id == flag_id), None)
        if flag is None:
            return
        initial = QColor(flag.color) if flag.color else QColor(DEFAULT_COLOR)
        color = QColorDialog.getColor(initial, self, "Flag-Farbe")
        if not color.isValid():
            return
        repo.update_flag(
            self.conn, flag_id,
            name=flag.name, color=color.name(), sort_order=flag.sort_order,
        )
        self.refresh()

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 1:  # color cell
            name_item = self.table.item(row, 0)
            if name_item:
                self.table.setCurrentItem(name_item)
            self._pick_color()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        name_item = self.table.item(row, 0)
        if name_item is None:
            return
        flag_id = name_item.data(Qt.ItemDataRole.UserRole)
        if flag_id is None:
            return
        flag = next((f for f in repo.list_flags(self.conn) if f.id == flag_id), None)
        if flag is None:
            return
        try:
            new_name = self.table.item(row, 0).text().strip() or flag.name
            new_order_text = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else "0"
            new_order = int(new_order_text) if new_order_text.lstrip("-").isdigit() else flag.sort_order
            repo.update_flag(
                self.conn, int(flag_id),
                name=new_name, color=flag.color, sort_order=new_order,
            )
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Fehler", "Name existiert bereits.")
            self.refresh()

    def _selected_flag_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            cur = self.table.currentRow()
            if cur < 0:
                return None
            row_idx = cur
        else:
            row_idx = rows[0].row()
        item = self.table.item(row_idx, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None
