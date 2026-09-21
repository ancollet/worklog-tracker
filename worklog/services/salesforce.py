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

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Optional

API_VERSION = "v64.0"

# ---- Org-Namen des Salesforce-Projekts: am 21.09.2026 per describe gegen die Sandbox bestätigt ----
# Nothing else in the app knows these names; correcting them means changing exactly these lines.
# A Projekt has two Account lookups (BillingAccount__c, EndCustomer__c); the Kunde in Worklog is
# the Billing Account. Status values are Planned | In Progress | Done; all but Done count as offen.
PROJECT_OBJECT = "Project__c"                # API name of the Salesforce-Projekt object
PROJECT_NAME_FIELD = "Name"                  # display name of the Projekt
PROJECT_ACCOUNT_FIELD = "BillingAccount__c"  # lookup from the Projekt to its Account
PROJECT_STATUS_FIELD = "Status__c"           # status picklist on the Projekt
PROJECT_OPEN_STATUSES = ("Planned", "In Progress")  # status values that mean "offen"

# ---- Org-Namen der Kostenposition: am 21.09.2026 per describe gegen die Sandbox bestätigt ----
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
COST_ITEM_TEXT_MAX_LENGTH = 255  # length of Description__c and CustomerRequestType__c in the org

# Picklist API values: am 21.09.2026 per describe gegen die Sandbox bestätigt.
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

    maybe_delivered = False  # True: the request may have reached Salesforce although no answer came back


# What can go wrong after the request left: the answer is lost, not necessarily the request.
_MAYBE_DELIVERED = (TimeoutError, ConnectionResetError, ConnectionAbortedError, http.client.HTTPException)


class SalesforceAuthError(SalesforceError):
    """Anmeldung abgelehnt — Consumer Key/Secret wrong, or the Integrations-User may not sign in."""


class SalesforceOrgError(SalesforceError):
    """The org answered with an error (validation rule, missing permission, ...).

    The message is the text Salesforce sent, so the user can act on it.
    """

    http_status: Optional[int] = None


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


# IDs per query of open_projects_among: about 28 URL characters each, far below Salesforce's
# limit of 16,384 bytes for the URL of a GET.
_OPEN_CHECK_BLOCK_SIZE = 200


def _is_salesforce_id(text: str) -> bool:
    """Salesforce IDs are 15 or 18 ASCII letters and digits."""
    return len(text) in (15, 18) and text.isascii() and text.isalnum()


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
    error = SalesforceOrgError(f"Salesforce meldet (HTTP {exc.code}): {detail}".rstrip(": "))
    error.http_status = exc.code
    return error


# ---- Kostenposition löschen (Ticket 10, Stornieren): outcomes other than "deleted" ----

class CostItemOutcomeUnknownError(SalesforceError):
    """The answer to creating a Kostenposition got lost: it may exist or not.

    Never to be retried blindly — a second attempt could create a second Kostenposition.
    """

    def __init__(self) -> None:
        super().__init__(
            "Unklar, ob die Kostenposition angelegt wurde (keine Antwort von Salesforce). "
            "Bitte in Salesforce prüfen, bevor erneut gebucht wird."
        )


class CostItemNotFoundError(SalesforceError):
    """The Kostenposition does not exist in Salesforce (any more) — e.g. deleted there by hand."""

    def __init__(self) -> None:
        super().__init__("Die Kostenposition existiert in Salesforce nicht mehr.")


class CostItemNotOpenError(SalesforceError):
    """The Kostenposition is no longer in status Open (e.g. invoiced); it was not deleted."""

    def __init__(self, status: str) -> None:
        super().__init__(
            f"Die Kostenposition hat in Salesforce den Status \"{status or 'unbekannt'}\" und nicht mehr "
            f"\"{COST_ITEM_STATUS_OPEN}\". Sie wurde nicht gelöscht."
        )
        self.status = status


class CostItemDeleteRefusedError(SalesforceOrgError):
    """The org refused the DELETE itself (validation rule, trigger, missing permission).

    ANNAHME, in Ticket 03 zu bestätigen: whether and how the org prevents deleting a
    Kostenposition in another status is unknown, so every 4xx answer to the DELETE
    counts as a refusal and carries the text Salesforce sent.
    """

    def __init__(self, org_error: SalesforceOrgError) -> None:
        super().__init__(f"Salesforce hat das Löschen der Kostenposition abgelehnt; sie wurde nicht gelöscht. {org_error}")
        self.http_status = org_error.http_status


# ---- Ende Löschen-Fehlertypen ----


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

    # ---- Abgleich / Prüfung vor dem Buchen: welche Salesforce-Projekte sind noch offen? ----

    def open_projects_among(self, project_ids: list[str]) -> set[str]:
        """Those of the given Salesforce-Projekte that are still offen — in the caller's spelling.

        Everything else counts as geschlossen: closed Projekte, deleted ones, and
        references that are no Salesforce ID at all.
        """
        asked = [str(project_id).strip() for project_id in project_ids]
        # One malformed ID makes Salesforce refuse the whole query, so only real IDs are asked for.
        # IDs exist in a 15- and an 18-character form; the first 15 identify the record.
        ids = list({project_id[:15]: project_id for project_id in asked if _is_salesforce_id(project_id)}.values())
        open_keys: set[str] = set()
        # The query travels in the URL of a GET, so many IDs are asked for block by block.
        # Any error fails the whole check — a Projekt is never reported as geschlossen by accident.
        for start in range(0, len(ids), _OPEN_CHECK_BLOCK_SIZE):
            id_list = ", ".join(f"'{_escape_soql(i)}'" for i in ids[start:start + _OPEN_CHECK_BLOCK_SIZE])
            records = self._query(
                f"SELECT Id FROM {PROJECT_OBJECT} WHERE Id IN ({id_list}) AND {_open_project_condition()}"
            )
            open_keys.update(str(r.get("Id") or "")[:15] for r in records)
        return {i for i in asked if _is_salesforce_id(i) and i[:15] in open_keys}

    # ---- Ende Abgleich-Block ----

    # ---- Kostenposition (Ticket 08) ----

    def is_project_open(self, salesforce_project_id: str) -> bool:
        """Is this one Salesforce-Projekt still offen? Asked right before Buchen."""
        return bool(self.open_projects_among([salesforce_project_id]))

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
        try:
            data = self._call("POST", f"/services/data/{API_VERSION}/sobjects/{COST_ITEM_OBJECT}", body=fields)
        except SalesforceNetworkError as exc:
            if exc.maybe_delivered:
                raise CostItemOutcomeUnknownError() from exc
            raise
        record_id = str(data.get("id") or "") if isinstance(data, dict) else ""
        if not record_id:
            # Salesforce answered 2xx without an ID: it may exist all the same.
            raise CostItemOutcomeUnknownError()
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

    # ---- Kostenposition löschen (Ticket 10, Stornieren) ----

    def delete_cost_item(self, cost_item_id: str) -> None:
        """Delete the Kostenposition — only while its status is Open. Returns when it is gone.

        Raises CostItemNotFoundError (it does not exist any more), CostItemNotOpenError
        (status checked BEFORE deleting; the app does not rely on the org refusing),
        CostItemDeleteRefusedError (the org refused the DELETE, with its text), or the
        usual SalesforceError for Netz, Anmeldung and other org errors. In every case
        but the first the Kostenposition still exists.

        ANNAHMEN, in Ticket 03 zu bestätigen: the Integrations-User sees every Kostenposition
        (a record hidden from him would look "not found"), may delete those in status Open,
        and a successful DELETE answers 204 without a body.
        """
        cost_item_id = cost_item_id.strip()
        if not _is_salesforce_id(cost_item_id):
            raise CostItemNotFoundError()   # such a reference cannot exist in Salesforce
        records = self._query(
            f"SELECT Id, {COST_ITEM_STATUS_FIELD} FROM {COST_ITEM_OBJECT} "
            f"WHERE Id = '{_escape_soql(cost_item_id)}' LIMIT 1"
        )
        if not records:
            raise CostItemNotFoundError()
        status = str(records[0].get(COST_ITEM_STATUS_FIELD) or "")
        if status != COST_ITEM_STATUS_OPEN:
            raise CostItemNotOpenError(status)
        try:
            self._call(
                "DELETE",
                f"/services/data/{API_VERSION}/sobjects/{COST_ITEM_OBJECT}/{urllib.parse.quote(cost_item_id, safe='')}",
            )
        except SalesforceOrgError as exc:
            if exc.http_status == 404:
                # Deleted by someone else since the check (NOT_FOUND / ENTITY_IS_DELETED).
                raise CostItemNotFoundError() from exc
            if exc.http_status is not None and 400 <= exc.http_status < 500:
                raise CostItemDeleteRefusedError(exc) from exc
            raise

    # ---- Ende Löschen-Block ----

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
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            error = SalesforceNetworkError(f"Salesforce ist nicht erreichbar: {reason}")
            # Timeout, reset or a broken answer: the request may well have arrived.
            error.maybe_delivered = isinstance(reason, _MAYBE_DELIVERED)
            raise error from exc
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise SalesforceError(f"Unerwartete Antwort von Salesforce: {body[:200]}") from exc
