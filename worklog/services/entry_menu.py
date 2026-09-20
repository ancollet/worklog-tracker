"""Qt-free rules behind the entry context menu (see ui/entry_context_menu.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from worklog.models import LogEntry
from worklog.repository import EntryBookedError
from worklog.services.bulk_cleanup import skip_reason


@dataclass(frozen=True, slots=True)
class EntryMenuPlan:
    header: str
    can_continue: bool
    can_edit: bool
    can_copy_description: bool
    can_move: bool
    can_delete: bool
    # "In … buchen…": the Buchungssystem of the Kunde whose item is shown ("jira" | "salesforce"),
    # None = no such item. With a reason the item is shown disabled, the reason as its tooltip.
    booking_system: Optional[str]
    booking_disabled_reason: Optional[str]
    booking_url: Optional[str]  # "Buchung im Browser öffnen": link of the one gebuchten Eintrag, else None
    can_cancel_booking: bool  # "Buchung stornieren"
    delete_label: str
    # Sperr-Regel: why edit/move/delete are disabled (gebuchte Einträge), else None
    locked_hint: Optional[str]
    # "Beschreibungen bereinigen…": needs a complete LLM configuration and at least
    # one bereinigbaren Eintrag; the hint says why it is disabled, else None
    can_clean_descriptions: bool
    clean_descriptions_hint: Optional[str]


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


def plan_entry_menu(
    logs: list[LogEntry],
    *,
    llm_missing_text: str = "",
    salesforce_block: Optional[Callable[[LogEntry], Optional[str]]] = None,
) -> EntryMenuPlan:
    """`llm_missing_text` is `LlmConfiguration.missing_text`: empty when the
    LLM-Bereinigung is fully configured.

    `salesforce_block` tells why an entry cannot be gebucht in Salesforce right now
    (None = it can); the rules behind it belong to the Buchungs-Service."""
    n = len(logs)
    clean_hint = None
    if llm_missing_text:
        clean_hint = llm_missing_text
    elif all(skip_reason(log) for log in logs):
        clean_hint = "Kein Eintrag der Auswahl ist bereinigbar (gebucht oder ohne Beschreibung)."
    # Sperr-Regel: one gebuchter Eintrag locks the whole selection.
    booked_ids = [int(log.id) for log in logs if log.is_booked]
    locked = bool(booked_ids)
    booking_system = None
    booking_disabled_reason = None
    # Jira: booking is always exactly one, not yet gebuchter, entry of a Jira customer.
    if n == 1 and not locked and logs[0].customer_booking_system == "jira":
        booking_system = "jira"
    # Salesforce: one Eintrag or a Sammelbuchung, as soon as a Salesforce-Kunde is involved.
    elif any(log.customer_booking_system == "salesforce" for log in logs):
        booking_system = "salesforce"
        booking_disabled_reason = _salesforce_disabled_reason(logs, salesforce_block)
    return EntryMenuPlan(
        header=f"{n} Eintrag ausgewählt" if n == 1 else f"{n} Einträge ausgewählt",
        # Fortsetzen: exactly one entry, and not one that is still running.
        can_continue=n == 1 and logs[0].ended_at is not None,
        can_edit=n == 1 and not locked,
        can_copy_description=bool(clipboard_text(logs)),
        can_move=not locked,
        can_delete=not locked,
        booking_system=booking_system,
        booking_disabled_reason=booking_disabled_reason,
        booking_url=(logs[0].external_worklog_url or None) if n == 1 and locked else None,
        # Stornieren is always exactly one entry, whatever its Buchungssystem.
        can_cancel_booking=n == 1 and locked,
        delete_label="⌫  Löschen" if n == 1 else f"⌫  {n} Einträge löschen",
        locked_hint=str(EntryBookedError(booked_ids, n)) if locked else None,
        can_clean_descriptions=clean_hint is None,
        clean_descriptions_hint=clean_hint,
    )


def _salesforce_disabled_reason(
    logs: list[LogEntry], salesforce_block: Optional[Callable[[LogEntry], Optional[str]]]
) -> Optional[str]:
    """Why "In Salesforce buchen…" is disabled for a selection with Salesforce-Kunden, else None.

    A Sammelbuchung only needs one buchbaren Eintrag: the Buchungsdialog greys out the rest."""
    if any(log.customer_booking_system == "jira" for log in logs):
        return (
            "Die Auswahl enthält Einträge von Jira- und Salesforce-Kunden. "
            "Bitte getrennt buchen."
        )
    if salesforce_block is None:
        return None
    reasons = [
        salesforce_block(log) for log in logs if log.customer_booking_system == "salesforce"
    ]
    if all(reasons):
        return reasons[0] if len(set(reasons)) == 1 else "Kein Eintrag der Auswahl ist buchbar."
    return None


def clipboard_text(logs: list[LogEntry]) -> str:
    """Text for "Beschreibung kopieren" of `logs` (in displayed order)."""
    return "\n".join(
        log.description for log in logs if log.description and log.description.strip()
    )


def flag_menu_state(name: str, *, have: int, total: int) -> FlagMenuState:
    if have == total:
        return FlagMenuState(label=name, checked=True, new_state=False)
    if have == 0:
        return FlagMenuState(label=name, checked=False, new_state=True)
    return FlagMenuState(
        label=f"{name}  (gemischt: {have}/{total})", checked=False, new_state=True
    )
