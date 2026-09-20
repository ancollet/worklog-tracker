"""The one place that builds the right-click menu for entries.

The tree in the Timer tab and the table in the Logs tab both hand over the
ordered list of affected entries; new menu items are added here only.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QMessageBox, QWidget

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.booking import cancel_booking, cancel_booking_hint
from worklog.services.entry_menu import clipboard_text, flag_menu_state, plan_entry_menu
from worklog.services.llm_settings import load_configuration as load_llm_configuration
from worklog.services.salesforce_booking import booking_block
from worklog.services.salesforce_settings import load_configuration as load_sf_configuration
from worklog.services.timer import (
    AlreadyRunningError,
    ProjectArchivedError,
    SourceEntryRunningError,
    TimerService,
)
from worklog.ui.jira_booking import book_jira
from worklog.ui.salesforce_booking import book_salesforce


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
    try:
        repo.delete_logs_bulk(conn, log_ids)
    except repo.EntryBookedError as exc:
        QMessageBox.warning(
            parent, "Löschen nicht möglich", f"{exc}.\n\nEs wurde nichts gelöscht."
        )
        return False
    return True


def cancel_entry_booking(parent: QWidget, conn: sqlite3.Connection, log_id: int) -> bool:
    """"Buchung stornieren": ask, then unlock the entry. Returns True when data changed."""
    log = repo.get_log(conn, log_id)
    if log is None or not log.is_booked:
        return False
    confirm = QMessageBox.question(
        parent, "Buchung stornieren?", f"{cancel_booking_hint(log)} Fortfahren?"
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return False
    cancel_booking(conn, log_id)
    return True


def continue_entry(parent: QWidget, conn: sqlite3.Connection, log_id: int) -> bool:
    """Fortsetzen via the timer service; a refusal is shown as a hint.

    The menu item and the button in the Logs tab both end up here. Returns True
    when a new running entry was started.
    """
    try:
        TimerService(conn).continue_entry(log_id)
    except ProjectArchivedError:
        QMessageBox.information(parent, "Fortsetzen", "Projekt ist archiviert.")
    except AlreadyRunningError:
        QMessageBox.information(parent, "Fortsetzen", "Dieser Eintrag läuft bereits.")
    except SourceEntryRunningError:
        QMessageBox.information(parent, "Fortsetzen", "Dieser Eintrag läuft selbst noch.")
    except LookupError:
        QMessageBox.information(parent, "Fortsetzen", "Dieser Eintrag existiert nicht mehr.")
    else:
        return True
    return False


def build_entry_context_menu(
    parent: QWidget,
    conn: sqlite3.Connection,
    logs: list[LogEntry],
    *,
    on_edit: Callable[[int], None],
    on_changed: Callable[[], None],
    move_anchor_id: Optional[int] = None,
) -> QMenu:
    """Build the menu for `logs` (ordered, at least one entry).

    `on_edit` opens the edit dialog of the calling view; `on_changed` is called
    after every action that changed data. `move_anchor_id` (the clicked entry)
    adds "Verschieben auf…", with the date picker preset to that entry's day.
    """
    llm_config = load_llm_configuration(conn)
    sf_configuration = None  # loaded only when a Salesforce-Kunde is involved (touches the keyring)

    def salesforce_block(log: LogEntry) -> Optional[str]:
        nonlocal sf_configuration
        if sf_configuration is None:
            sf_configuration = load_sf_configuration(conn)
        block = booking_block(conn, log, sf_configuration)
        return str(block) if block else None

    plan = plan_entry_menu(
        logs, llm_missing_text=llm_config.missing_text, salesforce_block=salesforce_block
    )
    log_ids = [int(log.id) for log in logs]
    n = len(log_ids)

    menu = QMenu(parent)
    menu.setToolTipsVisible(True)  # a disabled item says why
    header = QAction(plan.header, menu)
    header.setEnabled(False)
    menu.addAction(header)
    if plan.locked_hint is not None:
        locked = QAction(f"🔒  {plan.locked_hint}", menu)
        locked.setEnabled(False)
        menu.addAction(locked)
    menu.addSeparator()

    continue_act = QAction("Fortsetzen ▶", menu)
    continue_act.setEnabled(plan.can_continue)

    def continue_(_checked=False) -> None:
        if continue_entry(parent, conn, log_ids[0]):
            on_changed()

    continue_act.triggered.connect(continue_)
    menu.addAction(continue_act)

    edit_act = QAction("✎  Bearbeiten…", menu)
    edit_act.setEnabled(plan.can_edit)
    if plan.can_edit:
        edit_act.triggered.connect(lambda _checked=False: on_edit(log_ids[0]))
    menu.addAction(edit_act)

    copy_act = QAction("⧉  Beschreibung kopieren", menu)
    copy_act.setEnabled(plan.can_copy_description)
    copy_act.triggered.connect(
        lambda _checked=False: QGuiApplication.clipboard().setText(clipboard_text(logs))
    )
    menu.addAction(copy_act)

    anchor = next((log for log in logs if log.id == move_anchor_id), None)
    if anchor is not None:
        move_act = QAction("⇥  Verschieben auf…", menu)
        move_act.setEnabled(plan.can_move)

        def move(_checked=False, preset=anchor.started_at.date()) -> None:
            from worklog.ui.move_dialog import move_entries
            if move_entries(parent, conn, log_ids, preset):
                on_changed()

        move_act.triggered.connect(move)
        menu.addAction(move_act)

    clean_act = QAction("✦  Beschreibungen bereinigen…", menu)
    clean_act.setEnabled(plan.can_clean_descriptions)
    clean_act.setToolTip(plan.clean_descriptions_hint or "")

    def clean(_checked=False) -> None:
        from worklog.ui.bulk_cleanup_dialog import clean_descriptions
        if clean_descriptions(parent, conn, logs, llm_config):
            on_changed()

    clean_act.triggered.connect(clean)
    menu.addAction(clean_act)

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

    if plan.booking_system is not None or plan.can_cancel_booking:
        menu.addSeparator()

        def add_booking_action(label: str, booking_fn, disabled_reason: Optional[str] = None) -> None:
            booking_act = QAction(label, menu)
            if disabled_reason:
                booking_act.setEnabled(False)
                booking_act.setToolTip(disabled_reason)

            def run_booking(_checked=False) -> None:
                if booking_fn(parent, conn, log_ids[0]):
                    on_changed()

            booking_act.triggered.connect(run_booking)
            menu.addAction(booking_act)

        if plan.booking_system == "jira":
            add_booking_action("In Jira buchen…", book_jira)
        elif plan.booking_system == "salesforce":
            menu.setToolTipsVisible(True)  # the reason why booking is disabled
            add_booking_action(
                "In Salesforce buchen…",
                lambda parent_, conn_, log_id: book_salesforce(parent_, conn_, [log_id]),
                plan.booking_disabled_reason,
            )
        if plan.booking_url is not None:
            open_act = QAction("↗  Buchung im Browser öffnen", menu)
            open_act.triggered.connect(
                lambda _checked=False, url=plan.booking_url: QDesktopServices.openUrl(QUrl(url))
            )
            menu.addAction(open_act)
        if plan.can_cancel_booking:
            add_booking_action("Buchung stornieren…", cancel_entry_booking)

    menu.addSeparator()
    del_act = QAction(plan.delete_label, menu)
    del_act.setEnabled(plan.can_delete)

    def delete(_checked=False) -> None:
        if delete_entries(parent, conn, log_ids):
            on_changed()

    del_act.triggered.connect(delete)
    menu.addAction(del_act)
    return menu
