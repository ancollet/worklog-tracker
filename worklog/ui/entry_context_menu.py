"""The one place that builds the right-click menu for entries.

The tree in the Timer tab and the table in the Logs tab both hand over the
ordered list of affected entries; new menu items are added here only.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Optional, Sequence

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QMessageBox, QWidget

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.entry_menu import flag_menu_state, plan_entry_menu
from worklog.ui.jira_booking import book_jira, clear_jira_booking


class _KeepSelectionOnRightClick(QObject):
    """Swallow right-button presses so Qt does not re-select the clicked row."""

    def eventFilter(self, _obj, event) -> bool:  # noqa: N802 (Qt)
        return (
            event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
            and event.button() == Qt.MouseButton.RightButton
        )


def keep_selection_on_right_click(view: QAbstractItemView) -> None:
    """A right-click opens the menu but leaves the view's selection untouched."""
    view.viewport().installEventFilter(_KeepSelectionOnRightClick(view))


def delete_entries(parent: QWidget, conn: sqlite3.Connection, log_ids: list[int]) -> bool:
    """Ask, then delete. Returns True when entries were deleted."""
    if not log_ids:
        return False
    msg = (
        "Diesen Eintrag wirklich löschen?"
        if len(log_ids) == 1
        else f"{len(log_ids)} Einträge wirklich löschen?"
    )
    confirm = QMessageBox.question(parent, "Löschen?", msg)
    if confirm != QMessageBox.StandardButton.Yes:
        return False
    repo.delete_logs_bulk(conn, log_ids)
    return True


def build_entry_context_menu(
    parent: QWidget,
    conn: sqlite3.Connection,
    logs: list[LogEntry],
    *,
    on_edit: Callable[[int], None],
    on_changed: Callable[[], None],
    leading_actions: Sequence[QAction] = (),
    move_anchor_id: Optional[int] = None,
) -> QMenu:
    """Build the menu for `logs` (ordered, at least one entry).

    `on_edit` opens the edit dialog of the calling view; `on_changed` is called
    after every action that changed data. `leading_actions` are view-specific
    items placed above "Bearbeiten". `move_anchor_id` (the clicked entry) adds
    "Verschieben auf…", with the date picker preset to that entry's day.
    """
    plan = plan_entry_menu(logs)
    log_ids = [int(log.id) for log in logs]
    n = len(log_ids)

    menu = QMenu(parent)
    header = QAction(plan.header, menu)
    header.setEnabled(False)
    menu.addAction(header)
    menu.addSeparator()

    for act in leading_actions:
        act.setParent(menu)
        menu.addAction(act)

    edit_act = QAction("✎  Bearbeiten…", menu)
    edit_act.setEnabled(plan.can_edit)
    if plan.can_edit:
        edit_act.triggered.connect(lambda _checked=False: on_edit(log_ids[0]))
    menu.addAction(edit_act)

    anchor = next((log for log in logs if log.id == move_anchor_id), None)
    if anchor is not None:
        move_act = QAction("⇥  Verschieben auf…", menu)

        def move(_checked=False, preset=anchor.started_at.date()) -> None:
            from worklog.ui.move_dialog import move_entries
            if move_entries(parent, conn, log_ids, preset):
                on_changed()

        move_act.triggered.connect(move)
        menu.addAction(move_act)

    flags_menu = menu.addMenu("⚑  Flags")
    flags = repo.list_flags(conn)
    if not flags:
        empty = QAction("(keine Flags – verwalten…)", flags_menu)
        empty.setEnabled(False)
        flags_menu.addAction(empty)
    else:
        counts = repo.count_logs_with_flag(conn, log_ids)
        for flag in flags:
            state = flag_menu_state(flag.name, have=counts.get(flag.id, 0), total=n)
            act = QAction(state.label, flags_menu)
            act.setCheckable(True)
            act.setChecked(state.checked)

            def apply_flag(_checked=False, fid=flag.id, enabled=state.new_state) -> None:
                repo.set_log_flag_bulk(conn, log_ids, int(fid), enabled)
                on_changed()

            act.triggered.connect(apply_flag)
            flags_menu.addAction(act)
    flags_menu.addSeparator()
    manage = QAction("⚙  Flags verwalten…", flags_menu)

    def manage_flags(_checked=False) -> None:
        from worklog.ui.flags_dialog import FlagsDialog
        dlg = FlagsDialog(conn, parent=parent)
        if dlg.exec():
            on_changed()

    manage.triggered.connect(manage_flags)
    flags_menu.addAction(manage)

    if plan.jira_action is not None:
        menu.addSeparator()
        if plan.jira_action == "unbook":
            jira_act = QAction("Jira-Buchung lokal entfernen…", menu)
            jira_fn = clear_jira_booking
        else:
            jira_act = QAction("In Jira buchen…", menu)
            jira_fn = book_jira

        def run_jira(_checked=False) -> None:
            if jira_fn(parent, conn, log_ids[0]):
                on_changed()

        jira_act.triggered.connect(run_jira)
        menu.addAction(jira_act)

    menu.addSeparator()
    del_act = QAction(plan.delete_label, menu)

    def delete(_checked=False) -> None:
        if delete_entries(parent, conn, log_ids):
            on_changed()

    del_act.triggered.connect(delete)
    menu.addAction(del_act)
    return menu
