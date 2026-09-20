from __future__ import annotations

import sqlite3

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from worklog import repository as repo


class SnippetsDialog(QDialog):
    """CRUD dialog for snippets (Codereview, Recherche, …).

    Snippets are plain text: renaming or deleting one never touches the
    descriptions of existing entries.
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Snippets verwalten")
        self.resize(420, 360)

        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())

        self.add_btn = QPushButton("+ Neues Snippet")
        self.add_btn.clicked.connect(self._add)
        self.rename_btn = QPushButton("Umbenennen")
        self.rename_btn.clicked.connect(self._rename)
        self.up_btn = QPushButton("▲")
        self.up_btn.setToolTip("Nach oben")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("▼")
        self.down_btn.setToolTip("Nach unten")
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.delete_btn = QPushButton("⌫ Löschen")
        self.delete_btn.clicked.connect(self._delete)

        outer = QVBoxLayout(self)
        outer.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.rename_btn)
        row.addWidget(self.up_btn)
        row.addWidget(self.down_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        outer.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

        self._loading = False
        self.refresh()

    def refresh(self, select_id: int | None = None) -> None:
        self._loading = True
        self.list.clear()
        for snippet in repo.list_snippets(self.conn):
            item = QListWidgetItem(snippet.text)
            item.setData(Qt.ItemDataRole.UserRole, snippet.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.list.addItem(item)
            if snippet.id == select_id:
                self.list.setCurrentItem(item)
        self._loading = False
        self._update_buttons()

    # ------------------ actions ------------------

    def _add(self) -> None:
        text, ok = QInputDialog.getText(self, "Neues Snippet", "Text:")
        if not ok:
            return
        try:
            snippet = repo.create_snippet(self.conn, text=text)
        except repo.SnippetTextError as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        self.refresh(select_id=snippet.id)

    def _rename(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.list.editItem(item)

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.list.count():
            return
        ids = self._ids()
        ids[row], ids[target] = ids[target], ids[row]
        repo.reorder_snippets(self.conn, ids)
        self.refresh(select_id=ids[target])

    def _delete(self) -> None:
        snippet_id = self._selected_snippet_id()
        if snippet_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Löschen?",
            "Snippet wirklich löschen? Bestehende Beschreibungen bleiben unverändert.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        repo.delete_snippet(self.conn, snippet_id)
        self.refresh()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        snippet_id = item.data(Qt.ItemDataRole.UserRole)
        if snippet_id is None:
            return
        try:
            repo.rename_snippet(self.conn, int(snippet_id), text=item.text())
        except repo.SnippetTextError as e:
            QMessageBox.warning(self, "Fehler", str(e))
        # Deferred: rebuilding the list while the editor is still committing
        # would pull the item out from under it.
        QTimer.singleShot(0, lambda: self.refresh(select_id=int(snippet_id)))

    # ------------------ helpers ------------------

    def _ids(self) -> list[int]:
        return [
            int(self.list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.list.count())
        ]

    def _selected_snippet_id(self) -> int | None:
        item = self.list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _update_buttons(self) -> None:
        row = self.list.currentRow()
        has_selection = row >= 0
        self.rename_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self.up_btn.setEnabled(has_selection and row > 0)
        self.down_btn.setEnabled(has_selection and row < self.list.count() - 1)
