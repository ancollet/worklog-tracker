"""DB-backed QCompleter for tasks and descriptions."""
from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.QtWidgets import QCompleter

from worklog import repository as repo


def make_task_completer(parent, conn: sqlite3.Connection) -> QCompleter:
    completer = QCompleter(parent)
    completer.setModel(QStringListModel(parent))
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer._conn = conn  # type: ignore[attr-defined]
    return completer


def refresh_task_completer(completer: QCompleter, project_id: Optional[int]) -> None:
    conn = completer._conn  # type: ignore[attr-defined]
    suggestions = repo.task_suggestions(conn, project_id=project_id)
    completer.model().setStringList(suggestions)


def make_description_completer(parent, conn: sqlite3.Connection) -> QCompleter:
    completer = QCompleter(parent)
    completer.setModel(QStringListModel(parent))
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer._conn = conn  # type: ignore[attr-defined]
    return completer


def refresh_description_completer(
    completer: QCompleter, project_id: Optional[int], task: Optional[str]
) -> None:
    conn = completer._conn  # type: ignore[attr-defined]
    suggestions = repo.description_suggestions(conn, project_id=project_id, task=task)
    completer.model().setStringList(suggestions)
