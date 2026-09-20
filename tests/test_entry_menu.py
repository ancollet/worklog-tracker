from datetime import datetime, timezone

from worklog.models import LogEntry
from worklog.services.entry_menu import flag_menu_state, plan_entry_menu, target_log_ids


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


def test_booked_entry_of_jira_customer_offers_local_removal():
    plan = plan_entry_menu([_entry(1, booking_system="jira", worklog_id="4711")])
    assert plan.jira_action == "unbook"


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
