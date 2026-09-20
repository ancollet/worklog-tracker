"""Reusable snippet control: a button with a menu, attached to a description field."""
from __future__ import annotations

import sqlite3
from typing import Sequence, Union

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services.snippets import apply_snippet

DescriptionField = Union[QLineEdit, QPlainTextEdit, QTextEdit]


class SnippetButton(QToolButton):
    """Button whose menu inserts a snippet as prefix into ``field``.

    Works with single-line (QLineEdit) and multi-line (QPlainTextEdit,
    QTextEdit) fields. The menu is rebuilt from the database each time it
    opens, so every button shows the current snippets without being told
    about changes. Deliberately no keyboard shortcut.
    """

    def __init__(self, conn: sqlite3.Connection, field: DescriptionField, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.field = field
        self.setText("Snippets")
        self.setToolTip("Snippet als Präfix in die Beschreibung einfügen")
        # Stays out of the tab chain, so Tab still goes from the description
        # straight to the next form control as before.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.aboutToShow.connect(self._rebuild_menu)
        self.setMenu(menu)
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        menu = self.menu()
        menu.clear()
        snippets = repo.list_snippets(self.conn)
        for snippet in snippets:
            action = menu.addAction(snippet.text.replace("&", "&&"))
            action.triggered.connect(lambda _checked=False, text=snippet.text: self.apply(text))
        if snippets:
            menu.addSeparator()
        manage = menu.addAction("Snippets verwalten…")
        manage.triggered.connect(self._open_manage_dialog)

    def apply(self, snippet_text: str) -> None:
        """Insert the snippet into the field; focus the field, cursor at the end."""
        known = [s.text for s in repo.list_snippets(self.conn)]
        old = self._field_text()
        new = apply_snippet(old, snippet_text, known)
        if new != old:
            self._replace_field_text(new)
        self._focus_field_at_end()

    def _open_manage_dialog(self) -> None:
        from worklog.ui.snippets_dialog import SnippetsDialog
        SnippetsDialog(self.conn, parent=self.window()).exec()
        self._focus_field_at_end()

    # ------------------ field access ------------------

    def _field_text(self) -> str:
        if isinstance(self.field, QLineEdit):
            return self.field.text()
        return self.field.toPlainText()

    def _replace_field_text(self, text: str) -> None:
        # Replace through the editing API (not setText/setPlainText) so the
        # change stays on the field's undo stack.
        if isinstance(self.field, QLineEdit):
            self.field.selectAll()
            self.field.insert(text)
            return
        cursor = self.field.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)

    def _focus_field_at_end(self) -> None:
        self.field.setFocus()
        if isinstance(self.field, QLineEdit):
            self.field.end(False)
            return
        cursor = self.field.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.field.setTextCursor(cursor)


def with_snippet_button(
    conn: sqlite3.Connection, field: DescriptionField, extra_buttons: Sequence[QWidget] = ()
) -> QWidget:
    """Wrap ``field`` and a SnippetButton into one row widget for layouts.

    ``extra_buttons`` (e.g. "Bereinigen") join the SnippetButton: stacked below
    it next to a multi-line field, in a row after it next to a single-line one.
    """
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field, 1)
    button = SnippetButton(conn, field, container)
    multiline = not isinstance(field, QLineEdit)
    if multiline and extra_buttons:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        for btn in (button, *extra_buttons):
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            column.addWidget(btn)
        column.addStretch(1)
        layout.addLayout(column)
        return container
    alignment = Qt.AlignmentFlag.AlignTop if multiline else Qt.AlignmentFlag.AlignVCenter
    for btn in (button, *extra_buttons):
        layout.addWidget(btn, 0, alignment)
    return container
