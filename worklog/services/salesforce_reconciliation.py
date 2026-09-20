"""Abgleich: find out which registrierte Projekte were geschlossen in Salesforce, and remember it.

Qt-free. A Projekt whose Salesforce-Projekt is no longer offen (closed, or gone
altogether) gets the Kennzeichen "in Salesforce geschlossen" plus the time of the
check. Nothing else happens to it: it is not archived, its Einträge stay, tracking
on it stays possible. When Salesforce cannot be asked, nothing changes at all.

The Abgleich has two halves, because the UI must not wait for the network and a
database connection must not travel to another thread:

    check = check_open_projects(client, salesforce_project_ids(conn))   # network only
    record_open_projects_check(conn, check)                             # database only

`reconcile_registered_projects` does both in one go for callers that may block
(tests, and Buchen while it already runs in the background with its own connection).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from worklog import repository as repo
from worklog.db import transaction
from worklog.models import Project


@dataclass(slots=True, frozen=True)
class OpenProjectsCheck:
    """Answer of Salesforce: which of the Salesforce-Projekte asked for are still offen."""

    asked: frozenset[str]
    still_open: frozenset[str]


@dataclass(slots=True, frozen=True)
class ReconciliationResult:
    """What an Abgleich recorded."""

    checked: list[Project]   # every Projekt the Abgleich covered, in its new state
    at: datetime

    @property
    def closed(self) -> list[Project]:
        return [p for p in self.checked if p.closed_in_salesforce]


def _registered_projects(conn: sqlite3.Connection, project_ids: Optional[Iterable[int]] = None) -> list[Project]:
    """Projekte of Salesforce-Kunden that hang on a Salesforce-Projekt — archived ones too."""
    only = None if project_ids is None else set(project_ids)
    return [
        p for p in repo.list_projects(conn, include_archived=True)
        if p.customer_booking_system == "salesforce" and p.external_ref
        and (only is None or p.id in only)
    ]


def salesforce_project_ids(conn: sqlite3.Connection, project_ids: Optional[Iterable[int]] = None) -> list[str]:
    """What to ask Salesforce about: the Salesforce-Projekte of all registrierte Projekte,
    or only of the given Projekte (Buchen: the ones the Einträge belong to)."""
    return [p.external_ref for p in _registered_projects(conn, project_ids)]


def check_open_projects(client, salesforce_project_ids: Iterable[str]) -> OpenProjectsCheck:
    """The network half. Touches no database, so it may run in a background thread.

    Raises SalesforceError (Netz, Anmeldung, Org) — then there is nothing to record.
    """
    asked = frozenset(salesforce_project_ids)
    return OpenProjectsCheck(asked=asked, still_open=frozenset(client.open_projects_among(sorted(asked))))


def record_open_projects_check(
    conn: sqlite3.Connection, check: OpenProjectsCheck, at: Optional[datetime] = None
) -> ReconciliationResult:
    """The database half: Kennzeichen and time for every Projekt the check asked about.

    Projekte that were registriert or connected to another Salesforce-Projekt while
    the check was running are left alone — Salesforce said nothing about them.
    """
    at = at or datetime.now(timezone.utc).astimezone()
    covered = [p for p in _registered_projects(conn) if p.external_ref in check.asked]
    with transaction(conn):
        for project in covered:
            repo.set_project_salesforce_check(
                conn, project.id, closed=project.external_ref not in check.still_open, checked_at=at
            )
    return ReconciliationResult(checked=[repo.get_project(conn, p.id) for p in covered], at=at)


def reconcile_registered_projects(
    conn: sqlite3.Connection,
    client,
    *,
    project_ids: Optional[Iterable[int]] = None,
    at: Optional[datetime] = None,
) -> ReconciliationResult:
    """Registrierte Projekte abgleichen — all of them, or only the given Projekte.

    Raises SalesforceError without having changed anything.
    """
    check = check_open_projects(client, salesforce_project_ids(conn, project_ids))
    return record_open_projects_check(conn, check, at)


# ---------- What the Kunden-Tab shows ----------


def is_closed_in_salesforce(project: Project) -> bool:
    """The Kennzeichen only counts while the Projekt still hangs on a Salesforce-Projekt.

    This is also the question Buchen asks for "Projekt in Salesforce geschlossen".
    """
    return bool(
        project.closed_in_salesforce and project.external_ref and project.customer_booking_system == "salesforce"
    )


def checked_at_text(at: Optional[datetime]) -> str:
    return at.astimezone().strftime("%d.%m.%Y %H:%M") if at else ""


def closed_marker(project: Project) -> str:
    """Short marker next to the name of the Projekt; empty while it is offen (or not registriert)."""
    return "in Salesforce geschlossen" if is_closed_in_salesforce(project) else ""


def closed_tooltip(project: Project) -> str:
    if not is_closed_in_salesforce(project):
        return ""
    return (
        "Dieses Projekt ist in Salesforce geschlossen "
        f"(letzter Abgleich: {checked_at_text(project.salesforce_checked_at)}).\n"
        "Tracken bleibt möglich; es wird nicht automatisch archiviert."
    )


# ---------- Not more often than necessary ----------

RECONCILIATION_INTERVAL = timedelta(minutes=10)


def is_reconciliation_due(
    last_attempt: Optional[datetime], now: datetime, interval: timedelta = RECONCILIATION_INTERVAL
) -> bool:
    """Opening the Kunden-Tab starts an Abgleich only if the last attempt (successful or not) is old enough."""
    return last_attempt is None or now - last_attempt >= interval
