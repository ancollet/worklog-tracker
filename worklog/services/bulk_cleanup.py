"""Sammelaktion "Beschreibungen bereinigen…" — the Qt-free part.

`CleanupRun` holds one row per selected Eintrag and knows which rows take part,
which row is next, what came back and what the user wants to keep. The dialog
(ui/bulk_cleanup_dialog.py) only drives it: `next_pending()` → one background
call with `clean_entry()` → `record()`, and in the end `apply_accepted()`.

Calls run strictly one after another. That keeps the rows filling from top to
bottom, stays clear of the rate limit of small Azure deployments (HTTP 429),
lets an auth error end the run after a single call instead of once per
parallel call, and makes "Stoppen" trivial: there is at most one call in flight.

Nothing is written before `apply_accepted`, and that writes only descriptions.
"""
from __future__ import annotations

import sqlite3
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.llm_cleanup import (
    LlmAuthError,
    LlmCleanupError,
    clean_entry_description,
    is_already_clean,
)
from worklog.services.llm_settings import LlmConfiguration

# Row states
SKIPPED = "skipped"              # takes no part, see `skip_reason`
PENDING = "pending"              # waits for its call
RUNNING = "running"              # its call is in flight
CLEANED = "cleaned"              # a changed description came back
ALREADY_CLEAN = "already_clean"  # the answer equals the description
ERROR = "error"                  # the call failed; the description stays as it is
NOT_RUN = "not_run"              # the run was stopped or aborted before this row


# ---------- Auswahlregel ----------

def _booked(entry: LogEntry) -> Optional[str]:
    return "gebucht – erst Buchung stornieren" if entry.is_booked else None


def _no_description(entry: LogEntry) -> Optional[str]:
    return None if (entry.description or "").strip() else "keine Beschreibung"


# THE place for reasons that keep an Eintrag out of the Sammelaktion; the first hit wins.
_SKIP_RULES: tuple[Callable[[LogEntry], Optional[str]], ...] = (_booked, _no_description)


def skip_reason(entry: LogEntry) -> Optional[str]:
    """Why `entry` cannot be cleaned (shown in its greyed-out row), or None if it can."""
    for rule in _SKIP_RULES:
        reason = rule(entry)
        if reason:
            return reason
    return None


# ---------- one call ----------

@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """Result of the call for one Eintrag: either `after` or `error`."""

    after: Optional[str] = None
    error: Optional[str] = None
    aborts_run: bool = False  # configuration/auth problem: every further call would fail alike


def clean_entry(
    config: LlmConfiguration, entry: LogEntry, *, opener=urllib.request.urlopen
) -> CleanupOutcome:
    """One blocking LLM call for one Eintrag (run it off the UI thread). Never raises
    LlmCleanupError — a failure is part of the outcome and belongs to that row."""
    if config.credentials is None:
        return CleanupOutcome(error=config.missing_text, aborts_run=True)
    try:
        after = clean_entry_description(
            config.credentials, entry, system_prompt=config.system_prompt, opener=opener
        )
    except LlmAuthError as exc:
        return CleanupOutcome(error=str(exc), aborts_run=True)
    except LlmCleanupError as exc:
        return CleanupOutcome(error=str(exc))
    return CleanupOutcome(after=after)


# ---------- the run ----------

@dataclass(slots=True)
class CleanupRow:
    entry: LogEntry
    skip_reason: Optional[str] = None
    status: str = PENDING
    after: Optional[str] = None
    error: Optional[str] = None
    accepted: bool = False  # "Übernehmen"; only a CLEANED row can be accepted

    @property
    def before(self) -> str:
        return self.entry.description or ""


@dataclass(slots=True)
class CleanupRun:
    logs: list[LogEntry]
    rows: list[CleanupRow] = field(init=False)
    abort_message: Optional[str] = field(init=False, default=None)
    _stopped: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.rows = []
        for entry in self.logs:
            reason = skip_reason(entry)
            self.rows.append(CleanupRow(entry, reason, SKIPPED if reason else PENDING))

    # ----- driving the calls -----

    def next_pending(self) -> Optional[CleanupRow]:
        """The next row to send, marked RUNNING — or None when there is nothing (more) to do."""
        if self._stopped or any(row.status == RUNNING for row in self.rows):
            return None
        row = next((row for row in self.rows if row.status == PENDING), None)
        if row is not None:
            row.status = RUNNING
        return row

    def record(self, row: CleanupRow, outcome: CleanupOutcome) -> None:
        """Take the outcome of `row`'s call. After `stop()` it is ignored."""
        if row.status != RUNNING:
            return
        if outcome.after is None:
            row.status, row.error = ERROR, outcome.error or "Unbekannter Fehler"
            if outcome.aborts_run:
                self.abort_message = row.error
                self._end()
        elif is_already_clean(row.before, outcome.after):
            row.status = ALREADY_CLEAN
        else:
            # Preselected — but nothing is saved before the user confirms the dialog.
            row.status, row.after, row.accepted = CLEANED, outcome.after, True

    def stop(self) -> None:
        """No further calls; a call in flight no longer counts."""
        self._end()

    def _end(self) -> None:
        self._stopped = True
        for row in self.rows:
            if row.status in (PENDING, RUNNING):
                row.status = NOT_RUN

    # ----- progress -----

    @property
    def total_count(self) -> int:
        """Rows that take part (everything but the skipped ones)."""
        return sum(row.status != SKIPPED for row in self.rows)

    @property
    def done_count(self) -> int:
        return sum(row.status in (CLEANED, ALREADY_CLEAN, ERROR) for row in self.rows)

    @property
    def is_finished(self) -> bool:
        return not any(row.status in (PENDING, RUNNING) for row in self.rows)

    # ----- Übernehmen / Verwerfen -----

    def set_accepted(self, row: CleanupRow, accepted: bool) -> None:
        row.accepted = accepted and row.status == CLEANED

    def accept_all(self) -> None:
        for row in self.rows:
            self.set_accepted(row, True)

    def reject_all(self) -> None:
        for row in self.rows:
            self.set_accepted(row, False)

    def accepted_rows(self) -> list[CleanupRow]:
        return [row for row in self.rows if row.accepted and row.status == CLEANED]


# ---------- saving ----------

@dataclass(slots=True)
class ApplyResult:
    saved_ids: list[int] = field(default_factory=list)
    rejected: list[tuple[CleanupRow, str]] = field(default_factory=list)  # row, readable reason


def apply_accepted(conn: sqlite3.Connection, run: CleanupRun) -> ApplyResult:
    """Write the accepted descriptions — only the description, nothing else.

    Each Eintrag stands for itself: one that was gebucht, edited or deleted since
    the dialog opened is left alone and reported; the others are saved.
    """
    result = ApplyResult()
    for row in run.accepted_rows():
        log_id = int(row.entry.id)
        current = repo.get_log(conn, log_id)
        if current is None:
            result.rejected.append((row, "Eintrag existiert nicht mehr"))
            continue
        if (current.description or "") != row.before:
            result.rejected.append((row, "Beschreibung wurde inzwischen geändert"))
            continue
        try:
            repo.set_log_description(conn, log_id, row.after)
        except repo.EntryBookedError as exc:
            result.rejected.append((row, str(exc)))
        except LookupError:
            result.rejected.append((row, "Eintrag existiert nicht mehr"))
        else:
            result.saved_ids.append(log_id)
    return result
