from worklog.services.rounding import (
    format_hm_short,
    format_hms,
    format_hours_decimal,
    round_up_seconds,
)


def test_round_up_zero_input():
    assert round_up_seconds(0, 15) == 0


def test_round_up_disabled_with_none():
    assert round_up_seconds(123, None) == 123


def test_round_up_disabled_with_zero():
    assert round_up_seconds(123, 0) == 123


def test_round_up_exact_multiple_unchanged():
    assert round_up_seconds(15 * 60, 15) == 15 * 60
    assert round_up_seconds(60 * 60, 15) == 60 * 60


def test_round_up_one_second_over_rounds_to_next_step():
    assert round_up_seconds(15 * 60 + 1, 15) == 30 * 60


def test_round_up_typical_cases():
    # 14 min @ 15 → 15 min
    assert round_up_seconds(14 * 60, 15) == 15 * 60
    # 16 min @ 15 → 30 min
    assert round_up_seconds(16 * 60, 15) == 30 * 60
    # 31 min @ 30 → 60 min
    assert round_up_seconds(31 * 60, 30) == 60 * 60


def test_round_up_negative_clamps_to_zero():
    assert round_up_seconds(-5, 15) == 0


def test_format_hms():
    assert format_hms(0) == "00:00:00"
    assert format_hms(59) == "00:00:59"
    assert format_hms(3600) == "01:00:00"
    assert format_hms(3661) == "01:01:01"


def test_format_hm_short():
    assert format_hm_short(0) == "0min"
    assert format_hm_short(45 * 60) == "45min"
    assert format_hm_short(2 * 3600) == "2h"
    assert format_hm_short(2 * 3600 + 30 * 60) == "2h 30min"


def test_format_hours_decimal():
    assert format_hours_decimal(3600) == "1.00"
    assert format_hours_decimal(5400) == "1.50"
    assert format_hours_decimal(0) == "0.00"
