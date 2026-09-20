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
from datetime import date
from typing import Optional

API_VERSION = "v64.0"

# ---- Org-Namen des Salesforce-Projekts: ANNAHMEN, in Ticket 03 gegen die Sandbox zu bestätigen ----
# (spec.md, offener Recherchepunkt 2). Nothing else in the app knows these names;
# correcting them means changing exactly these lines.
PROJECT_OBJECT = "Project__c"                # API name of the Salesforce-Projekt object
PROJECT_NAME_FIELD = "Name"                  # display name of the Projekt
PROJECT_ACCOUNT_FIELD = "Account__c"         # lookup from the Projekt to its Account
PROJECT_STATUS_FIELD = "Status__c"           # status picklist on the Projekt
PROJECT_OPEN_STATUSES = ("Open",)            # status values that mean "offen"

# ---- Org-Namen der Kostenposition: ANNAHMEN, in Ticket 03 gegen die Sandbox zu bestätigen ----
# (spec.md, offene Recherchepunkte 1 und 4). Object and field names follow CONTEXT.md
# (`ProjectCostItem__c`, `Person__c`); the rest is guessed from the field labels.
COST_ITEM_OBJECT = "ProjectCostItem__c"                  # API name of the Kostenposition object
COST_ITEM_NUMBER_FIELD = "Name"                          # Nummer of the Kostenposition (auto-number)
COST_ITEM_PROJECT_FIELD = "Project__c"                   # lookup to the Salesforce-Projekt
COST_ITEM_PERSON_FIELD = "Person__c"                     # lookup to the leistende Person (User)
COST_ITEM_QUANTITY_FIELD = "Quantity__c"                 # Menge in hours
COST_ITEM_DELIVERY_DATE_FIELD = "DeliveryDate__c"        # Delivery Date (date only)
COST_ITEM_DESCRIPTION_FIELD = "Description__c"           # Beschreibung
COST_ITEM_SERVICE_TYPE_FIELD = "ServiceType__c"          # Service Type picklist
COST_ITEM_REQUEST_TYPE_FIELD = "CustomerRequestType__c"  # Customer Request Type (free text)
COST_ITEM_STATUS_FIELD = "Status__c"                     # status picklist
COST_ITEM_SKILL_LEVEL_FIELD = "SkillLevel__c"            # Skill Level picklist
COST_ITEM_LOCATION_FIELD = "Location__c"                 # Location picklist
COST_ITEM_COUNT_AGAINST_BUDGET_FIELD = "CountAgainstBudget__c"  # Count against Budget checkbox

# Picklist API values: ANNAHMEN, in Ticket 03 gegen die Sandbox zu bestätigen.
# Key = Service Type in domain terms (salesforce_settings.SERVICE_TYPES), value = API value of the org.
COST_ITEM_SERVICE_TYPE_VALUES = {"Consulting": "Consulting", "Development": "Development"}
COST_ITEM_STATUS_OPEN = "Open"
COST_ITEM_SKILL_LEVEL_STANDARD = "Standard"
COST_ITEM_LOCATION_REMOTE = "Remote"

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


@dataclass(slots=True, frozen=True)
class SalesforceAccount:
    """An Account of the org that can be registriert as a Kunde."""

    id: str
    name: str


@dataclass(slots=True, frozen=True)
class SalesforceProject:
    """An offenes Salesforce-Projekt of an Account that can be registriert as a Projekt."""

    id: str
    name: str


@dataclass(slots=True, frozen=True)
class CostItemDraft:
    """What a Kostenposition is created from — in domain terms, never in org field names.

    Status, Skill Level, Location and Count against Budget are fixed and therefore not
    part of it; Tagessatz, prices and calculated fields are left to the org.
    """

    salesforce_project_id: str
    person_id: str                    # the leistende Person
    quantity_hours: float             # Menge, already rounded up to half hours
    delivery_date: date
    description: str
    service_type: str                 # "Consulting" | "Development" (domain value)
    customer_request_type: str = ""   # only sent when not empty


@dataclass(slots=True, frozen=True)
class CostItem:
    """A Kostenposition that exists in Salesforce."""

    id: str        # Buchungsreferenz — never shown in the UI
    number: str    # Nummer for display; empty when Salesforce did not tell it
    url: str       # link to the record


_MAX_SEARCH_HITS = 200
_MAX_QUERY_BATCHES = 50   # safety net against an endless "nextRecordsUrl" chain

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


def _open_project_condition() -> str:
    """SOQL condition "this Salesforce-Projekt is offen"."""
    values = ", ".join(f"'{_escape_soql(v)}'" for v in PROJECT_OPEN_STATUSES)
    return f"{PROJECT_STATUS_FIELD} IN ({values})"


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

    def list_accounts_with_open_projects(self) -> list[SalesforceAccount]:
        """All Accounts that have at least one offenes Projekt, sorted by name."""
        records = self._query(
            "SELECT Id, Name FROM Account "
            f"WHERE Id IN (SELECT {PROJECT_ACCOUNT_FIELD} FROM {PROJECT_OBJECT} "
            f"WHERE {_open_project_condition()}) "
            "ORDER BY Name"
        )
        return [SalesforceAccount(id=str(r["Id"]), name=str(r.get("Name") or "")) for r in records]

    def list_open_projects(self, account_id: str) -> list[SalesforceProject]:
        """The offenen Salesforce-Projekte of one Account, sorted by name."""
        account_id = account_id.strip()
        if not account_id:
            return []
        records = self._query(
            f"SELECT Id, {PROJECT_NAME_FIELD} FROM {PROJECT_OBJECT} "
            f"WHERE {PROJECT_ACCOUNT_FIELD} = '{_escape_soql(account_id)}' "
            f"AND {_open_project_condition()} "
            f"ORDER BY {PROJECT_NAME_FIELD}"
        )
        return [
            SalesforceProject(id=str(r["Id"]), name=str(r.get(PROJECT_NAME_FIELD) or ""))
            for r in records
        ]

    # ---- Kostenposition (Ticket 08) ----

    def is_project_open(self, salesforce_project_id: str) -> bool:
        """Is this one Salesforce-Projekt still offen? Asked right before Buchen.

        Minimal single-project check of Ticket 08; to be merged with the reusable
        "which of these Projekte are still offen" check of Ticket 06.
        """
        salesforce_project_id = salesforce_project_id.strip()
        if not salesforce_project_id:
            return False
        records = self._query(
            f"SELECT Id FROM {PROJECT_OBJECT} "
            f"WHERE Id = '{_escape_soql(salesforce_project_id)}' AND {_open_project_condition()} LIMIT 1"
        )
        return bool(records)

    def create_cost_item(self, draft: CostItemDraft) -> CostItem:
        """Create the Kostenposition and return its ID, Nummer and link.

        Once Salesforce has created it, this method no longer fails: if the Nummer
        cannot be read afterwards it stays empty, so the Buchungsreferenz is never lost.
        """
        if draft.service_type not in COST_ITEM_SERVICE_TYPE_VALUES:
            raise SalesforceError(f"Unbekannter Service Type: {draft.service_type}")
        fields = {
            COST_ITEM_PROJECT_FIELD: draft.salesforce_project_id,
            COST_ITEM_PERSON_FIELD: draft.person_id,
            COST_ITEM_QUANTITY_FIELD: draft.quantity_hours,
            COST_ITEM_DELIVERY_DATE_FIELD: draft.delivery_date.isoformat(),
            COST_ITEM_DESCRIPTION_FIELD: draft.description,
            COST_ITEM_SERVICE_TYPE_FIELD: COST_ITEM_SERVICE_TYPE_VALUES[draft.service_type],
            COST_ITEM_STATUS_FIELD: COST_ITEM_STATUS_OPEN,
            COST_ITEM_SKILL_LEVEL_FIELD: COST_ITEM_SKILL_LEVEL_STANDARD,
            COST_ITEM_LOCATION_FIELD: COST_ITEM_LOCATION_REMOTE,
            COST_ITEM_COUNT_AGAINST_BUDGET_FIELD: True,
        }
        if draft.customer_request_type.strip():
            fields[COST_ITEM_REQUEST_TYPE_FIELD] = draft.customer_request_type.strip()
        data = self._call("POST", f"/services/data/{API_VERSION}/sobjects/{COST_ITEM_OBJECT}", body=fields)
        record_id = str(data.get("id") or "") if isinstance(data, dict) else ""
        if not record_id:
            raise SalesforceError("Salesforce hat das Anlegen der Kostenposition nicht bestätigt.")
        return CostItem(id=record_id, number=self._cost_item_number(record_id), url=self.cost_item_url(record_id))

    def cost_item_url(self, cost_item_id: str) -> str:
        """Link to the record of the Kostenposition in the org."""
        return f"{self._base}/lightning/r/{COST_ITEM_OBJECT}/{urllib.parse.quote(cost_item_id, safe='')}/view"

    def _cost_item_number(self, cost_item_id: str) -> str:
        try:
            records = self._query(
                f"SELECT Id, {COST_ITEM_NUMBER_FIELD} FROM {COST_ITEM_OBJECT} "
                f"WHERE Id = '{_escape_soql(cost_item_id)}' LIMIT 1"
            )
        except SalesforceError:
            return ""
        return str(records[0].get(COST_ITEM_NUMBER_FIELD) or "") if records else ""

    def _query(self, soql: str) -> list[dict]:
        """Run one SOQL query (GET .../query?q=...) and return all its records.

        Salesforce answers in batches; while "done" is false, "nextRecordsUrl"
        (a path on the same instance) leads to the next one.
        """
        path = f"/services/data/{API_VERSION}/query?" + urllib.parse.urlencode({"q": soql})
        result: list[dict] = []
        for _batch in range(_MAX_QUERY_BATCHES):
            data = self._call("GET", path)
            records = data.get("records") if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise SalesforceError("Unerwartete Antwort von Salesforce auf eine Abfrage.")
            result.extend(r for r in records if isinstance(r, dict))
            next_path = data.get("nextRecordsUrl")
            if data.get("done", True) or not isinstance(next_path, str) or not next_path.startswith("/"):
                break
            path = next_path
        return result

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

    def _call(self, method: str, path: str, body: Optional[dict] = None):
        """Authenticated call. On 401 the token is renewed exactly once and the call repeated."""
        if self._access_token is None:
            self._access_token = self._fetch_token()
        try:
            return self._send(method, path, body)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise _org_error(exc) from exc
        self._access_token = self._fetch_token()
        try:
            return self._send(method, path, body)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise _org_error(exc) from exc
            self._access_token = None
            raise SalesforceAuthError(
                "Salesforce hat die Anmeldung abgelehnt (Zugriffstoken auch nach Erneuerung ungültig)."
            ) from exc

    def _send(self, method: str, path: str, body: Optional[dict] = None):
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._base + path, data=data, method=method, headers=headers)
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
