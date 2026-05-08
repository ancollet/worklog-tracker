"""Rounding helpers. Round-up (ceiling) to a multiple of N minutes."""
from __future__ import annotations


def round_up_seconds(seconds: int, minutes: int | None) -> int:
    """Round `seconds` up to the next multiple of `minutes`.

    `minutes` of 0 or None disables rounding (returns input unchanged).
    Negative inputs are clamped to 0.
    """
    if seconds <= 0:
        return 0
    if not minutes or minutes <= 0:
        return seconds
    step = minutes * 60
    remainder = seconds % step
    if remainder == 0:
        return seconds
    return seconds + (step - remainder)


def format_hms(seconds: int) -> str:
    """Format seconds as HH:MM:SS."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_hm_short(seconds: int) -> str:
    """Format seconds as e.g. '2h 30min' or '45min'."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h {m}min"
    if h:
        return f"{h}h"
    return f"{m}min"


def format_hours_decimal(seconds: int) -> str:
    """Format seconds as '2.50' (decimal hours, 2 digits)."""
    return f"{max(0, seconds) / 3600:.2f}"
