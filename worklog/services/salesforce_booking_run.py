"""Sammelbuchung: book several Einträge in Salesforce, row by row, in one Buchungsdialog.

Qt-free. The rules of one Buchung stay in `salesforce_booking.py`; this module only
knows the run: the order of the rows, what happens to the others when one fails,
and that no row ever creates a second Kostenposition.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from worklog import repository as repo
from worklog.services import salesforce_booking as booking
from worklog.services.salesforce import (
    CostItem,
    SalesforceAuthError,
    SalesforceError,
    SalesforceNetworkError,
)
from worklog.services.salesforce_reconciliation import (
    OpenProjectsCheck,
    check_open_projects,
    record_open_projects_check,
    salesforce_project_ids,
)
from worklog.services.salesforce_settings import SalesforceConfiguration

# State of a row
OPEN = "open"            # buchbar, not tried yet
BLOCKED = "blocked"      # not buchbar, `message` says why; never sent
FAILED = "failed"        # tried without success, `message` says why; may be corrected and sent again
NOT_RUN = "not_run"      # the run stopped before this row; nothing was sent for it
UNSAVED = "unsaved"      # the Kostenposition exists, but is not written to the Eintrag yet; never sent again
BOOKED = "booked"        # gebucht and written to the Eintrag; `message` is the Nummer of the Kostenposition


@dataclass(slots=True)
class BookingRow:
    """One Eintrag of the Sammelbuchung. No Salesforce ID in here — everything may be shown."""

    proposal: booking.BookingProposal
    state: str = OPEN
    message: str = ""

    @property
    def log_id(self) -> int:
        return self.proposal.log_id

    @property
    def is_open(self) -> bool:
        """May be changed and sent."""
        return self.state in (OPEN, FAILED, NOT_RUN)


class BookingRun:
    """The rows of one Buchungsdialog, from the Buchungsvorschlag to "gebucht"."""

    def __init__(
        self, conn: sqlite3.Connection, configuration: SalesforceConfiguration, log_ids: Iterable[int]
    ) -> None:
        self._conn = conn
        self._configuration = configuration
        self.is_checked = False   # Salesforce said which of the affected Projekte are still offen
        self.booked_log_ids: list[int] = []
        self._run_size = 0
        self.aborted_reason: Optional[str] = None   # why the last run stopped before its end
        self._queue: list[tuple[BookingRow, Optional[booking.ConfirmedBooking]]] = []
        self._in_flight: Optional[BookingRow] = None   # its Kostenposition is being created right now
        # Kostenpositionen that exist in Salesforce but not at their Eintrag, by Eintrag. Kept
        # apart from the rows: these hold Salesforce IDs.
        self._unsaved: dict[int, booking.BookingNotRecordedError] = {}
        self.rows: list[BookingRow] = [
            self._proposed(log_id) for log_id in self._by_date(dict.fromkeys(int(i) for i in log_ids))
        ]

    def _by_date(self, log_ids: Iterable[int]) -> list[int]:
        """Oldest first; Einträge that no longer exist go last."""
        def key(log_id: int):
            log = repo.get_log(self._conn, log_id)
            return (log is None, log.started_at if log else datetime.min, log_id)

        return sorted(log_ids, key=key)

    def _proposed(self, log_id: int) -> BookingRow:
        proposal = booking.propose_booking(
            self._conn, log_id, self._configuration, closed_known=self.is_checked
        )
        if proposal.is_bookable:
            return BookingRow(proposal)
        return BookingRow(proposal, BLOCKED, proposal.blocked_reason or "")

    # ---------- Abgleich before Buchen ----------
    #
    # Two halves, like the Abgleich itself: the database belongs to the UI thread,
    # the question to Salesforce must not run there.

    def projects_to_check(self) -> list[str]:
        """What to ask Salesforce about (`check_open_projects`): the Projekte of all rows
        that are buchbar so far. Not for display."""
        project_ids = set()
        for row in self.rows:
            log = repo.get_log(self._conn, row.log_id) if row.is_open else None
            if log is not None:
                project_ids.add(log.project_id)
        return salesforce_project_ids(self._conn, project_ids)

    def record_check(self, check: OpenProjectsCheck) -> None:
        """Remember the answer at the Projekte; rows of geschlossene Projekte are no longer buchbar."""
        record_open_projects_check(self._conn, check)
        self.is_checked = True
        for row in self.rows:   # in place: the dialog holds on to its rows
            if row.state in (OPEN, BLOCKED):
                fresh = self._proposed(row.log_id)
                row.proposal, row.state, row.message = fresh.proposal, fresh.state, fresh.message

    def check_projects(self, client) -> None:
        """Both halves in one go, for callers that may block. Raises SalesforceError —
        then nothing is checked and nothing can be gebucht."""
        self.record_check(check_open_projects(client, self.projects_to_check()))

    # ---------- The run ----------
    #
    #     run.start(confirmed)
    #     while (prepared := run.next_submission()) is not None:        # database
    #         outcome = submit(client, prepared)                        # network only, any thread
    #         run.finish_submission(prepared, outcome)                  # database
    #
    # `book` is exactly this loop for callers that may block.

    def start(self, confirmed: Iterable[booking.ConfirmedBooking]) -> None:
        """Queue the confirmed rows, in the order of the rows. Rows that are not open
        (not buchbar, gebucht already) are never queued, whatever was confirmed."""
        if self.is_running:
            raise booking.BookingError("Die Buchung läuft noch.")   # a second click must never book twice
        if not self.is_checked:
            raise booking.BookingError(
                "Es wurde noch nicht geprüft, ob die Projekte in Salesforce offen sind — es wird nichts gebucht."
            )
        by_log_id = {c.log_id: c for c in confirmed}
        self.aborted_reason = None
        self._queue = [
            (row, by_log_id.get(row.log_id)) for row in self.rows
            # A Kostenposition that is not saved yet is always tried again — saving only.
            if row.state == UNSAVED or (row.is_open and row.log_id in by_log_id)
        ]
        self._run_size = len(self._queue)

    def next_submission(self) -> Optional[booking.PreparedBooking]:
        """The next Buchung to hand to `submit` — None when the run is over.

        Rows that fail without Salesforce are settled here and cost no call."""
        if self._in_flight is not None:
            raise booking.BookingError("Die Buchung läuft noch.")
        while self._queue:
            row, confirmed = self._queue.pop(0)
            if row.state == UNSAVED:
                unsaved = self._unsaved[row.log_id]
                self._record(row, unsaved.prepared, unsaved.cost_item)
                continue
            try:
                prepared = booking.prepare_booking(
                    self._conn, self._configuration, confirmed, closed_known=True
                )
            except booking.BookingRefusedError as exc:
                if exc.code == booking.INVALID_VALUES:
                    row.state, row.message = FAILED, str(exc)      # can be corrected in the dialog
                else:
                    row.state, row.message = BLOCKED, str(exc)     # the Eintrag changed meanwhile
                continue
            self._in_flight = row
            return prepared
        return None

    def finish_submission(self, prepared: booking.PreparedBooking, outcome) -> BookingRow:
        """What `submit` returned for `prepared`: the Kostenposition, or the error."""
        row = self._in_flight
        if row is None or row.log_id != prepared.log_id:
            raise booking.BookingError("Diese Buchung wurde nicht von diesem Lauf ausgegeben.")
        self._in_flight = None
        if isinstance(outcome, CostItem):
            self._record(row, prepared, outcome)
        else:
            row.state, row.message = FAILED, _error_text(outcome)
            if isinstance(outcome, _CONCERNS_EVERY_ROW):
                # Anmeldung or Netz: the next row would fail the same way, so it is not even tried.
                self._stop(row.message)
        return row

    def _stop(self, reason: str) -> None:
        self.aborted_reason = reason
        for row, _confirmed in self._queue:
            if row.state != UNSAVED:
                row.state, row.message = NOT_RUN, "Nicht ausgeführt."
        self._run_size -= len(self._queue)
        self._queue = []

    @property
    def progress(self) -> tuple[int, int]:
        """(settled rows, rows) of the current or last run."""
        waiting = len(self._queue) + (1 if self._in_flight is not None else 0)
        return self._run_size - waiting, self._run_size

    @property
    def is_running(self) -> bool:
        return self._in_flight is not None or bool(self._queue)

    def _record(self, row: BookingRow, prepared: booking.PreparedBooking, cost_item: CostItem) -> None:
        try:
            booking.record_booking(self._conn, prepared, cost_item)
        except booking.BookingNotRecordedError as exc:
            self._unsaved[row.log_id] = exc
            row.state, row.message = UNSAVED, str(exc)
            return
        self._unsaved.pop(row.log_id, None)
        row.state, row.message = BOOKED, cost_item.number
        self.booked_log_ids.append(row.log_id)

    @property
    def has_unsaved(self) -> bool:
        """A Kostenposition exists in Salesforce that no Eintrag knows about."""
        return bool(self._unsaved)

    def stop(self) -> None:
        """Abbrechen: the row on its way is still finished and saved, the rest is not sent."""
        if self.is_running:
            self._stop("Der Lauf wurde angehalten.")

    def book(self, client, confirmed: Iterable[booking.ConfirmedBooking]) -> None:
        self.start(confirmed)
        while (prepared := self.next_submission()) is not None:
            self.finish_submission(prepared, submit(client, prepared))


def submit(client, prepared: booking.PreparedBooking):
    """The network part of one row: the Kostenposition, or the error as a value (so its
    kind survives the way back from a background thread). Touches no database."""
    try:
        return booking.submit_booking(client, prepared, closed_known=True)
    except Exception as exc:  # the run decides what an error means for the other rows
        return exc


_CONCERNS_EVERY_ROW = (SalesforceAuthError, SalesforceNetworkError)


def _error_text(outcome) -> str:
    if isinstance(outcome, (SalesforceError, booking.BookingError)):
        return str(outcome)
    return f"Unerwarteter Fehler: {outcome}"
