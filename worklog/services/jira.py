"""Minimal Jira Cloud REST API client for adding worklogs.

We deliberately use the stdlib (urllib) instead of pulling in `requests`, because
the surface is tiny and we don't want extra deps for a single endpoint.

Auth: HTTP Basic with email + Atlassian API token. API tokens are issued via
https://id.atlassian.com/manage-profile/security/api-tokens.

Note: Clockwork-Free (the user-facing Jira app) has no API of its own, but its
worklogs are stored as native Jira worklogs — so creating a Jira worklog via this
client will show up in Clockwork.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


class JiraError(RuntimeError):
    """Generic failure talking to Jira (network, auth, HTTP error)."""


class JiraAuthError(JiraError):
    """401/403 — credentials are wrong or token lacks permission."""


class JiraNotFoundError(JiraError):
    """404 — issue key does not exist (or the user can't see it)."""


@dataclass(slots=True)
class JiraCredentials:
    base_url: str   # e.g. "https://your-domain.atlassian.net"
    email: str
    api_token: str


@dataclass(slots=True)
class JiraWorklogResult:
    worklog_id: str
    issue_key: str
    self_url: str
    issue_browse_url: str


def extract_issue_key(text: Optional[str]) -> Optional[str]:
    """Pull the first JIRA-style issue key (PROJ-123) out of a free-text task field."""
    if not text:
        return None
    m = ISSUE_KEY_RE.search(text)
    return m.group(1) if m else None


def format_started(dt: datetime) -> str:
    """Jira expects ISO 8601 with millis and ±HHMM offset (no colon in offset).

    Example: 2026-05-13T10:00:00.000+0200
    """
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attach local tz
    # %z gives "+0200"; isoformat with timespec("milliseconds") gives "+02:00" — Jira wants no colon.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + dt.strftime("%z")


def _auth_header(email: str, api_token: str) -> str:
    raw = f"{email}:{api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def add_worklog(
    creds: JiraCredentials,
    *,
    issue_key: str,
    started: datetime,
    time_spent_seconds: int,
    comment: Optional[str] = None,
    opener=urllib.request.urlopen,
) -> JiraWorklogResult:
    """Create a worklog on a Jira issue. Returns the new worklog ID.

    `opener` is injectable for tests (so we can mock urlopen without monkeypatching).
    """
    if time_spent_seconds <= 0:
        raise ValueError("time_spent_seconds must be > 0")
    base = _normalize_base_url(creds.base_url)
    url = f"{base}/rest/api/3/issue/{issue_key}/worklog"

    payload: dict = {
        "started": format_started(started),
        "timeSpentSeconds": int(time_spent_seconds),
    }
    if comment:
        # Jira Cloud /api/3 requires ADF (Atlassian Document Format) for the comment.
        payload["comment"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": comment}]}
            ],
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": _auth_header(creds.email, creds.api_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with opener(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code in (401, 403):
            raise JiraAuthError(f"Auth failed ({exc.code}): {detail or exc.reason}") from exc
        if exc.code == 404:
            raise JiraNotFoundError(f"Issue '{issue_key}' not found or not visible.") from exc
        raise JiraError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise JiraError(f"Network error: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise JiraError(f"Invalid JSON from Jira: {body[:200]}") from exc

    worklog_id = str(data.get("id") or "")
    if not worklog_id:
        raise JiraError(f"Jira response did not include a worklog id: {body[:200]}")
    self_url = data.get("self") or ""
    issue_browse = f"{base}/browse/{issue_key}"
    return JiraWorklogResult(
        worklog_id=worklog_id,
        issue_key=issue_key,
        self_url=self_url,
        issue_browse_url=issue_browse,
    )


def test_connection(creds: JiraCredentials, opener=urllib.request.urlopen) -> str:
    """Hit /rest/api/3/myself to verify credentials. Returns the account's display name."""
    base = _normalize_base_url(creds.base_url)
    req = urllib.request.Request(
        f"{base}/rest/api/3/myself",
        method="GET",
        headers={
            "Authorization": _auth_header(creds.email, creds.api_token),
            "Accept": "application/json",
        },
    )
    try:
        with opener(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise JiraAuthError(f"Auth failed ({exc.code})") from exc
        raise JiraError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise JiraError(f"Network error: {exc.reason}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise JiraError("Invalid JSON from Jira") from exc
    return str(data.get("displayName") or data.get("emailAddress") or "OK")
