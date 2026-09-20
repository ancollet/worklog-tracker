"""Salesforce client: sign-in as the shared Integrations-User (ADR-0002).

Auth is the OAuth 2.0 client-credentials flow of the External Client App:
POST {instance_url}/services/oauth2/token with grant_type=client_credentials,
client_id (Consumer Key) and client_secret (Consumer Secret), form-encoded.
There is no refresh token; a new access token is simply requested again.

Like the Jira client we use the stdlib (urllib) — no extra dependency.

Everything org-specific (API version, object and field names) lives in this
module only. Callers talk in domain terms, never in SOQL.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

API_VERSION = "v64.0"

_TOKEN_PATH = "/services/oauth2/token"
_TIMEOUT_SECONDS = 15


class SalesforceError(RuntimeError):
    """Generic failure talking to Salesforce. The message is readable for the user."""


class SalesforceNetworkError(SalesforceError):
    """Netz nicht erreichbar — DNS, no connection, timeout."""


class SalesforceAuthError(SalesforceError):
    """Anmeldung abgelehnt — Consumer Key/Secret wrong, or the Integrations-User may not sign in."""


class SalesforceOrgError(SalesforceError):
    """The org answered with an error (validation rule, missing permission, ...).

    The message is the text Salesforce sent, so the user can act on it.
    """


@dataclass(slots=True)
class SalesforceCredentials:
    instance_url: str      # e.g. "https://your-domain.my.salesforce.com"
    consumer_key: str
    consumer_secret: str


@dataclass(slots=True, frozen=True)
class ActiveUser:
    """An active user of the org — a candidate for the leistende Person."""

    id: str
    name: str
    email: str = ""


_MAX_SEARCH_HITS = 200

# SOQL "Quoted String Escape Sequences": the backslash is the escape character.
# It must be replaced first, otherwise the backslashes we add would be doubled.
_SOQL_ESCAPES = (
    ("\\", "\\\\"),
    ("'", "\\'"),
    ('"', '\\"'),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
    ("\b", "\\b"),
    ("\f", "\\f"),
)


def _escape_soql(text: str) -> str:
    """Make user input safe inside a single-quoted SOQL string literal."""
    for char, escaped in _SOQL_ESCAPES:
        text = text.replace(char, escaped)
    return text


def _escape_like(text: str) -> str:
    """Like _escape_soql, and the LIKE wildcards _ and % are taken literally."""
    return _escape_soql(text).replace("_", "\\_").replace("%", "\\%")


def _error_body(exc: urllib.error.HTTPError):
    try:
        return json.loads(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _oauth_error_text(exc: urllib.error.HTTPError) -> str:
    data = _error_body(exc)
    if isinstance(data, dict):
        return str(data.get("error_description") or data.get("error") or "")
    return ""


def _org_error_text(exc: urllib.error.HTTPError) -> str:
    """REST errors come as a list of {"message": ..., "errorCode": ...}."""
    data = _error_body(exc)
    if isinstance(data, list):
        messages = [str(item.get("message") or item.get("errorCode") or "")
                    for item in data if isinstance(item, dict)]
        return " / ".join(m for m in messages if m)
    return ""


def _org_error(exc: urllib.error.HTTPError) -> SalesforceOrgError:
    detail = _org_error_text(exc) or str(exc.reason or "")
    return SalesforceOrgError(f"Salesforce meldet (HTTP {exc.code}): {detail}".rstrip(": "))


class SalesforceClient:
    """One signed-in conversation with the org. The access token lives in memory only.

    `opener` is injectable for tests (fake HTTP at the transport boundary).
    """

    def __init__(self, creds: SalesforceCredentials, opener=urllib.request.urlopen) -> None:
        self._creds = creds
        self._base = creds.instance_url.strip().rstrip("/")
        if not self._base.lower().startswith(("https://", "http://")):
            raise SalesforceError(
                "Instance-URL ist ungültig — erwartet wird z.B. https://your-domain.my.salesforce.com"
            )
        self._opener = opener
        self._access_token: Optional[str] = None

    def test_connection(self) -> None:
        """Sign in and make one authenticated call."""
        self._call("GET", f"/services/data/{API_VERSION}/")

    def search_active_users(self, text: str, limit: int = 20) -> list[ActiveUser]:
        """Active users whose name or e-mail contains `text`, at most `limit` of them."""
        text = text.strip()
        if not text:
            return []
        limit = max(1, min(int(limit), _MAX_SEARCH_HITS))
        pattern = "%" + _escape_like(text) + "%"
        records = self._query(
            "SELECT Id, Name, Email FROM User "
            f"WHERE IsActive = true AND (Name LIKE '{pattern}' OR Email LIKE '{pattern}') "
            f"ORDER BY Name LIMIT {limit}"
        )
        return [
            ActiveUser(id=str(r["Id"]), name=str(r.get("Name") or ""), email=str(r.get("Email") or ""))
            for r in records
        ]

    def _query(self, soql: str) -> list[dict]:
        """Run one SOQL query (GET .../query?q=...) and return its records."""
        data = self._call("GET", f"/services/data/{API_VERSION}/query?" + urllib.parse.urlencode({"q": soql}))
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise SalesforceError("Unerwartete Antwort von Salesforce auf eine Abfrage.")
        return [r for r in records if isinstance(r, dict)]

    def _fetch_token(self) -> str:
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self._creds.consumer_key,
            "client_secret": self._creds.consumer_secret,
        })
        req = urllib.request.Request(
            self._base + _TOKEN_PATH,
            data=form.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            data = self._open(req)
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                # Salesforce is down, not the credentials wrong.
                raise _org_error(exc) from exc
            # The token endpoint answers {"error": "...", "error_description": "..."}.
            detail = _oauth_error_text(exc) or f"HTTP {exc.code}"
            raise SalesforceAuthError(f"Salesforce hat die Anmeldung abgelehnt: {detail}") from exc
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise SalesforceError("Salesforce hat kein Zugriffstoken geliefert.")
        return str(token)

    def _call(self, method: str, path: str):
        """Authenticated call. On 401 the token is renewed exactly once and the call repeated."""
        if self._access_token is None:
            self._access_token = self._fetch_token()
        try:
            return self._send(method, path)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise _org_error(exc) from exc
        self._access_token = self._fetch_token()
        try:
            return self._send(method, path)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise _org_error(exc) from exc
            self._access_token = None
            raise SalesforceAuthError(
                "Salesforce hat die Anmeldung abgelehnt (Zugriffstoken auch nach Erneuerung ungültig)."
            ) from exc

    def _send(self, method: str, path: str):
        req = urllib.request.Request(
            self._base + path,
            method=method,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            },
        )
        return self._open(req)

    def _open(self, req: urllib.request.Request):
        """Transport boundary. HTTP status errors pass through; everything below HTTP is 'Netz'."""
        try:
            with self._opener(req, timeout=_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise SalesforceNetworkError(f"Salesforce ist nicht erreichbar: {reason}") from exc
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise SalesforceError(f"Unerwartete Antwort von Salesforce: {body[:200]}") from exc
