"""Qt-free rules behind the entry context menu (see ui/entry_context_menu.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from worklog.models import LogEntry


@dataclass(frozen=True, slots=True)
class EntryMenuPlan:
    header: str
    can_continue: bool
    can_edit: bool
    jira_action: Optional[str]  # "book" | "unbook" | None
    delete_label: str


@dataclass(frozen=True, slots=True)
class FlagMenuState:
    label: str
    checked: bool
    new_state: bool  # state applied to all affected entries on click


def target_log_ids(clicked_id: int, selected_ids: list[int]) -> list[int]:
    """Right-click on an unselected entry acts on just that one (selection stays
    untouched); right-click on a selected entry acts on the whole selection."""
    if clicked_id in selected_ids:
        return list(selected_ids)
    return [clicked_id]


def plan_entry_menu(logs: list[LogEntry]) -> EntryMenuPlan:
    n = len(logs)
    jira_action = None
    # Booking is always exactly one entry of a Jira customer.
    if n == 1 and logs[0].customer_booking_system == "jira":
        jira_action = "unbook" if logs[0].external_worklog_id else "book"
    return EntryMenuPlan(
        header=f"{n} Eintrag ausgewählt" if n == 1 else f"{n} Einträge ausgewählt",
        # Fortsetzen: exactly one entry, and not one that is still running.
        can_continue=n == 1 and logs[0].ended_at is not None,
        can_edit=n == 1,
        jira_action=jira_action,
        delete_label="⌫  Löschen" if n == 1 else f"⌫  {n} Einträge löschen",
    )


def flag_menu_state(name: str, *, have: int, total: int) -> FlagMenuState:
    if have == total:
        return FlagMenuState(label=name, checked=True, new_state=False)
    if have == 0:
        return FlagMenuState(label=name, checked=False, new_state=True)
    return FlagMenuState(
        label=f"{name}  (gemischt: {have}/{total})", checked=False, new_state=True
    )
