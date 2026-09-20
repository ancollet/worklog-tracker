"""UI building blocks of the LLM-Bereinigung: the background call, the
Vorher/Nachher preview and the "Bereinigen" button for a description field.

Nothing here ever starts a call on its own — only a click does.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Optional, Union

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)

from worklog.services.llm_cleanup import LlmCleanupError
from worklog.services.llm_settings import LlmConfiguration, load_configuration

DescriptionField = Union[QLineEdit, QPlainTextEdit, QTextEdit]

# Calls that outlive their dialog are parked here until they finish,
# so a running QThread is never garbage-collected.
_running_calls: set = set()


class LlmCall(QThread):
    """Runs one blocking LLM call off the UI thread.

    `work` takes no arguments and returns the result. Emits (True, result) or
    (False, error text).
    """

    finished_with = pyqtSignal(bool, object)

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except LlmCleanupError as exc:
            self.finished_with.emit(False, str(exc))
        except Exception as exc:  # never let a worker thread die silently
            self.finished_with.emit(False, f"Unerwarteter Fehler: {exc}")
        else:
            self.finished_with.emit(True, result)


def start_llm_call(work: Callable[[], object], on_finished) -> LlmCall:
    """Start `work` in the background; `on_finished(ok, result_or_error_text)` runs in the UI thread.

    The call is kept alive until it has finished, even if its starter is gone
    by then. To ignore the outcome, disconnect `call.finished_with`.
    """
    call = LlmCall(work)
    call.finished_with.connect(on_finished)
    call.finished.connect(lambda c=call: _running_calls.discard(c))
    _running_calls.add(call)
    call.start()
    return call


class CleanupPreviewDialog(QDialog):
    """Vorher/Nachher of one description; accepted means "Übernehmen"."""

    def __init__(self, before: str, after: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Beschreibung bereinigen")
        self.setMinimumWidth(460)
        self.after = after

        layout = QVBoxLayout(self)
        for title, text in (("Vorher:", before), ("Nachher:", after)):
            layout.addWidget(QLabel(title))
            view = QPlainTextEdit(text)
            view.setReadOnly(True)
            view.setFixedHeight(84)
            layout.addWidget(view)

        buttons = QDialogButtonBox()
        self.apply_btn = buttons.addButton("Übernehmen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.discard_btn = buttons.addButton("Verwerfen", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def is_already_clean(before: str, after: str) -> bool:
    return before.strip() == after.strip()


class CleanupButton(QToolButton):
    """"Bereinigen" for one description field.

    Disabled (with a tooltip saying why) while the LLM-Bereinigung is not fully
    configured or the description is empty. A click sends task and description
    in the background, then offers the preview; "Übernehmen" only replaces the
    text of the field — saving stays with the surrounding dialog.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        field: DescriptionField,
        task: Callable[[], Optional[str]],
        parent=None,
        *,
        load_config: Optional[Callable[[], LlmConfiguration]] = None,
    ) -> None:
        super().__init__(parent)
        self.field = field
        self._task = task
        self._config = (load_config or (lambda: load_configuration(conn)))()
        self._call: Optional[LlmCall] = None
        self._before = ""
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self.start)
        field.textChanged.connect(self._update_state)
        self._update_state()

    # ------------------ state ------------------

    @property
    def is_running(self) -> bool:
        return self._call is not None

    def _update_state(self, *_args) -> None:
        if self.is_running:
            self.setText("Bereinige…")
            self.setEnabled(False)
            self.setToolTip("Die Beschreibung wird gerade bereinigt…")
            return
        self.setText("Bereinigen")
        if not self._config.is_complete:
            self.setEnabled(False)
            self.setToolTip(self._config.missing_text)
        elif not self._field_text().strip():
            self.setEnabled(False)
            self.setToolTip("Die Beschreibung ist leer – es gibt nichts zu bereinigen.")
        else:
            self.setEnabled(True)
            self.setToolTip("Beschreibung per LLM bereinigen (mit Vorher/Nachher-Vorschau)")

    # ------------------ call ------------------

    def start(self) -> None:
        before = self._field_text()
        if self.is_running or not self._config.is_complete or not before.strip():
            return
        config, task = self._config, self._task()
        # The preview compares against what was sent, so the text must not change meanwhile.
        self.field.setReadOnly(True)
        self._before = before
        self._call = start_llm_call(
            lambda: config.clean_description(task=task, description=before),
            self._on_finished,
        )
        self._update_state()

    def cancel(self) -> None:
        """Forget a running call: its outcome no longer reaches this button."""
        if self._call is None:
            return
        self._call.finished_with.disconnect(self._on_finished)
        self._call = None
        self.field.setReadOnly(False)
        self._update_state()

    def _on_finished(self, ok: bool, result) -> None:
        if self._call is None or self.sender() is not self._call:
            return
        self._call = None
        self.field.setReadOnly(False)
        self._update_state()
        before = self._before
        if not ok:
            QMessageBox.warning(
                self.window(), "Bereinigen",
                f"Die Beschreibung konnte nicht bereinigt werden und bleibt unverändert.\n\n{result}",
            )
            return
        after = str(result)
        if is_already_clean(before, after):
            QMessageBox.information(
                self.window(), "Bereinigen", "Die Beschreibung ist bereits sauber – keine Änderung."
            )
            return
        if CleanupPreviewDialog(before, after, self.window()).exec() == QDialog.DialogCode.Accepted:
            self._replace_field_text(after)

    # ------------------ field access ------------------

    def _field_text(self) -> str:
        if isinstance(self.field, QLineEdit):
            return self.field.text()
        return self.field.toPlainText()

    def _replace_field_text(self, text: str) -> None:
        # Through the editing API, so "Übernehmen" stays on the field's undo stack.
        if isinstance(self.field, QLineEdit):
            self.field.selectAll()
            self.field.insert(text)
            return
        cursor = self.field.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
