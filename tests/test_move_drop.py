"""Drag & Drop im Baum: which day a drop means, and whether it moves anything.

The move itself (time of day, atomicity, …) is covered in test_move.py.
"""
from datetime import date

from worklog.services.move import drop_changes_anything, drop_target_day

MON = date(2026, 5, 4)
TUE = date(2026, 5, 5)


def test_drop_on_day_or_entry_row_targets_that_day():
    assert drop_target_day(TUE, [MON]) == TUE


def test_month_row_and_empty_area_are_no_drop_target():
    assert drop_target_day(None, [MON]) is None


def test_nothing_dragged_is_no_drop():
    assert drop_target_day(TUE, []) is None


def test_drop_on_own_day_is_accepted_but_changes_nothing():
    assert drop_target_day(MON, [MON, MON]) == MON
    assert not drop_changes_anything(MON, [MON, MON])


def test_drop_on_other_day_changes_something():
    assert drop_changes_anything(TUE, [MON])


def test_mixed_selection_dropped_on_one_of_its_days_still_moves_the_rest():
    assert drop_changes_anything(TUE, [MON, TUE])
