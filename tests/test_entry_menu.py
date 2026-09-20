from dataclasses import replace
from datetime import datetime, timezone

from worklog.models import LogEntry
from worklog.services.entry_menu import (
    clipboard_text,
    flag_menu_state,
    plan_entry_menu,
    target_log_ids,
)


def _entry(log_id: int, *, booking_system=None, worklog_id=None, running=False) -> LogEntry:
    t = datetime(2026, 5, 8, 10, tzinfo=timezone.utc)
    return LogEntry(
        id=log_id, project_id=1, task="DIS-1", description="x",
        started_at=t, ended_at=None if running else t,
        duration_seconds=None if running else 900, rounded_to_minutes=15,
        customer_booking_system=booking_system, external_worklog_id=worklog_id,
    )


# ---------- Rechtsklick-Regel ----------

def test_right_click_on_unselected_entry_targets_only_that_entry():
    assert target_log_ids(7, [1, 2, 3]) == [7]


def test_right_click_on_selected_entry_targets_whole_selection_in_order():
    assert target_log_ids(2, [1, 2, 3]) == [1, 2, 3]


def test_right_click_without_selection_targets_clicked_entry():
    assert target_log_ids(7, []) == [7]


# ---------- Menüpunkte je Auswahl ----------

def test_single_entry_can_be_edited_and_deleted():
    plan = plan_entry_menu([_entry(1)])
    assert plan.header == "1 Eintrag ausgewählt"
    assert plan.can_edit is True
    assert plan.delete_label == "⌫  Löschen"
    assert plan.jira_action is None


def test_multiple_entries_disable_edit_and_offer_bulk_delete():
    plan = plan_entry_menu([_entry(1), _entry(2), _entry(3)])
    assert plan.header == "3 Einträge ausgewählt"
    assert plan.can_edit is False
    assert plan.delete_label == "⌫  3 Einträge löschen"


def test_unbooked_entry_of_jira_customer_offers_booking():
    plan = plan_entry_menu([_entry(1, booking_system="jira")])
    assert plan.jira_action == "book"


def test_booked_entry_offers_buchung_stornieren_instead_of_booking():
    plan = plan_entry_menu([_entry(1, booking_system="jira", worklog_id="4711")])
    assert plan.can_cancel_booking is True
    assert plan.jira_action is None


def test_buchung_stornieren_for_every_booked_entry_whatever_the_booking_system():
    for system in ("jira", "salesforce", None):
        plan = plan_entry_menu([_entry(1, booking_system=system, worklog_id="4711")])
        assert plan.can_cancel_booking is True


def test_buchung_stornieren_only_for_exactly_one_booked_entry():
    assert plan_entry_menu([_entry(1, booking_system="jira")]).can_cancel_booking is False
    booked = [_entry(1, worklog_id="1"), _entry(2, worklog_id="2")]
    assert plan_entry_menu(booked).can_cancel_booking is False


# ---------- Sperr-Regel: gebucht = gesperrt ----------

def test_unbooked_entry_is_not_locked():
    plan = plan_entry_menu([_entry(1)])
    assert (plan.can_edit, plan.can_move, plan.can_delete) == (True, True, True)
    assert plan.locked_hint is None


def test_booked_entry_disables_edit_move_and_delete():
    plan = plan_entry_menu([_entry(1, worklog_id="4711")])
    assert (plan.can_edit, plan.can_move, plan.can_delete) == (False, False, False)
    assert plan.locked_hint == "Eintrag ist gebucht, erst Buchung stornieren"


def test_booked_entry_can_still_be_continued_and_copied():
    plan = plan_entry_menu([_entry(1, worklog_id="4711")])
    assert plan.can_continue is True
    assert plan.can_copy_description is True


def test_mixed_selection_is_locked_as_a_whole_with_the_count():
    logs = [_entry(1), _entry(2, worklog_id="4711"), _entry(3, worklog_id="4712")]
    plan = plan_entry_menu(logs)
    assert (plan.can_move, plan.can_delete) == (False, False)
    assert plan.locked_hint == "2 von 3 Einträgen sind gebucht, erst Buchung stornieren"
    assert plan.can_copy_description is True


def test_jira_actions_only_for_exactly_one_entry():
    logs = [_entry(1, booking_system="jira"), _entry(2, booking_system="jira")]
    assert plan_entry_menu(logs).jira_action is None


# ---------- Fortsetzen ----------

def test_single_finished_entry_can_be_continued():
    assert plan_entry_menu([_entry(1)]).can_continue is True


def test_continue_is_disabled_for_multiple_entries():
    assert plan_entry_menu([_entry(1), _entry(2)]).can_continue is False


def test_continue_is_disabled_on_a_running_entry():
    assert plan_entry_menu([_entry(1, running=True)]).can_continue is False


def test_booked_entry_can_be_continued():
    plan = plan_entry_menu([_entry(1, booking_system="jira", worklog_id="4711")])
    assert plan.can_continue is True


# ---------- Flag-Zustand ----------


def test_flag_on_all_entries_is_checked_and_click_removes_it():
    state = flag_menu_state("abgerechnet", have=3, total=3)
    assert (state.label, state.checked, state.new_state) == ("abgerechnet", True, False)


def test_flag_on_no_entry_is_unchecked_and_click_sets_it():
    state = flag_menu_state("abgerechnet", have=0, total=3)
    assert (state.label, state.checked, state.new_state) == ("abgerechnet", False, True)


def test_flag_on_some_entries_is_shown_as_mixed_and_click_sets_it_everywhere():
    state = flag_menu_state("abgerechnet", have=1, total=3)
    assert state.label == "abgerechnet  (gemischt: 1/3)"
    assert state.checked is False
    assert state.new_state is True


# ---------- Beschreibung kopieren ----------

def _described(log_id: int, description, **kwargs) -> LogEntry:
    return replace(_entry(log_id, **kwargs), description=description)


def test_clipboard_text_of_one_entry_is_its_description_verbatim():
    assert clipboard_text([_described(1, "  Deploy & Review ")]) == "  Deploy & Review "


def test_clipboard_text_of_several_entries_is_one_description_per_line_in_order():
    logs = [_described(3, "Zuerst"), _described(1, "Dann"), _described(2, "Zuletzt")]
    assert clipboard_text(logs) == "Zuerst\nDann\nZuletzt"


def test_clipboard_text_skips_empty_descriptions_in_between():
    logs = [_described(1, "A"), _described(2, None), _described(3, ""),
            _described(4, "  \n "), _described(5, "B")]
    assert clipboard_text(logs) == "A\nB"


def test_clipboard_text_of_only_empty_descriptions_is_empty():
    assert clipboard_text([_described(1, None), _described(2, " ")]) == ""


def test_clipboard_text_keeps_duplicates():
    logs = [_described(1, "Daily"), _described(2, "Daily"), _described(3, "Review")]
    assert clipboard_text(logs) == "Daily\nDaily\nReview"


def test_clipboard_text_keeps_multiline_description_verbatim():
    logs = [_described(1, "Zeile 1\nZeile 2\n"), _described(2, "B")]
    assert clipboard_text(logs) == "Zeile 1\nZeile 2\n\nB"


def test_copy_description_is_enabled_when_any_entry_has_a_description():
    plan = plan_entry_menu([_described(1, None), _described(2, "B")])
    assert plan.can_copy_description is True


def test_copy_description_is_disabled_when_no_entry_has_a_description():
    plan = plan_entry_menu([_described(1, None), _described(2, ""), _described(3, "  ")])
    assert plan.can_copy_description is False


def test_copy_description_stays_enabled_for_booked_and_running_entries():
    booked = _described(1, "A", booking_system="jira", worklog_id="10001")
    running = _described(2, "B", running=True)
    assert plan_entry_menu([booked]).can_copy_description is True
    assert plan_entry_menu([running]).can_copy_description is True
    assert clipboard_text([booked, running]) == "A\nB"


# ---------- Beschreibungen bereinigen… ----------

def test_clean_descriptions_is_offered_for_one_or_several_entries():
    for logs in ([_entry(1)], [_entry(1), _entry(2, running=True)]):
        plan = plan_entry_menu(logs)
        assert plan.can_clean_descriptions is True
        assert plan.clean_descriptions_hint is None


def test_clean_descriptions_is_disabled_without_complete_llm_configuration():
    plan = plan_entry_menu([_entry(1)], llm_missing_text="Es fehlt: API-Key.")
    assert plan.can_clean_descriptions is False
    assert plan.clean_descriptions_hint == "Es fehlt: API-Key."


def test_clean_descriptions_stays_available_when_only_some_entries_are_cleanable():
    logs = [_entry(1), _entry(2, worklog_id="10042"), replace(_entry(3), description="")]
    assert plan_entry_menu(logs).can_clean_descriptions is True


def test_clean_descriptions_is_disabled_when_no_entry_is_cleanable():
    logs = [_entry(1, worklog_id="10042"), replace(_entry(2), description=None)]
    plan = plan_entry_menu(logs)
    assert plan.can_clean_descriptions is False
    assert plan.clean_descriptions_hint == (
        "Kein Eintrag der Auswahl ist bereinigbar (gebucht oder ohne Beschreibung)."
    )
