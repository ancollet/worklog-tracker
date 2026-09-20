"""Jira booking dialogs, shared by every view that offers them.

Both functions return True when data changed, so the caller can refresh.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from PyQt6.QtWidgets import QMessageBox, QWidget

from worklog import repository as repo
from worklog.services import credentials, jira as jira_client
from worklog.services.rounding import format_hm_short
from worklog.ui.settings_dialog import (
    SETTINGS_JIRA_BASE_URL,
    SETTINGS_JIRA_EMAIL,
)


def book_jira(parent: QWidget, conn: sqlite3.Connection, log_id: int) -> bool:
    log = repo.get_log(conn, log_id)
    if log is None:
        return False
    if log.external_worklog_id:
        QMessageBox.information(
            parent, "Bereits gebucht",
            f"Dieser Eintrag ist bereits gebucht (Worklog-ID {log.external_worklog_id}).",
        )
        return False

    issue_key = jira_client.extract_issue_key(log.task)
    if not issue_key:
        QMessageBox.warning(
            parent, "Kein Issue-Key",
            "Im Task-Feld wurde kein Jira-Issue-Key (z.B. DIS-1234) gefunden.",
        )
        return False

    duration = log.duration_seconds or 0
    if duration <= 0:
        QMessageBox.warning(parent, "Keine Dauer", "Dieser Eintrag hat keine gebuchte Dauer.")
        return False

    base_url = repo.get_setting(conn, SETTINGS_JIRA_BASE_URL, "") or ""
    email = repo.get_setting(conn, SETTINGS_JIRA_EMAIL, "") or ""
    try:
        token = credentials.get_jira_token()
    except credentials.CredentialsUnavailableError as exc:
        QMessageBox.critical(parent, "Keyring", f"Konnte Token nicht laden: {exc}")
        return False
    if not (base_url and email and token):
        QMessageBox.warning(
            parent, "Jira nicht konfiguriert",
            "Bitte zuerst Jira-Base-URL, Email und API-Token in den Einstellungen hinterlegen.",
        )
        return False

    confirm = QMessageBox.question(
        parent, "In Jira buchen?",
        f"{format_hm_short(duration)} auf Issue {issue_key} buchen?",
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return False

    creds = jira_client.JiraCredentials(base_url=base_url, email=email, api_token=token)
    try:
        result = jira_client.add_worklog(
            creds,
            issue_key=issue_key,
            started=log.started_at,
            time_spent_seconds=duration,
            comment=log.description or None,
        )
    except jira_client.JiraError as exc:
        QMessageBox.critical(parent, "Buchung fehlgeschlagen", str(exc))
        return False

    repo.set_log_external_ref(
        conn, log.id,
        worklog_id=result.worklog_id,
        worklog_url=result.issue_browse_url,
        synced_at_iso=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )
    QMessageBox.information(
        parent, "Gebucht",
        f"Worklog {result.worklog_id} auf {result.issue_key} angelegt.",
    )
    return True


def clear_jira_booking(parent: QWidget, conn: sqlite3.Connection, log_id: int) -> bool:
    confirm = QMessageBox.question(
        parent, "Lokal entfernen?",
        "Nur die lokale Buchungs-Referenz löschen. Der Worklog in Jira bleibt bestehen "
        "und muss dort manuell entfernt werden. Fortfahren?",
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return False
    repo.set_log_external_ref(conn, log_id, worklog_id=None, worklog_url=None, synced_at_iso=None)
    return True
