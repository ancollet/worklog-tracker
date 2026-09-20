"""LLM-Bereinigung: bring the description of an Eintrag into a terse, billable style.

Provider: the OpenAI-compatible chat completions of the Azure OpenAI v1 API
(Azure OpenAI / Microsoft Foundry):

    POST {endpoint}/openai/v1/chat/completions
    api-key: <key>
    {"model": "<deployment name>", "messages": [...]}

The v1 API needs no `api-version` query parameter; the deployment name goes
into `model`. Like the Jira client we use the stdlib (urllib) — no new dependency.

Only the system prompt, the task and the description are ever sent — never a
customer or project name. The function signatures make that structural: there
is no parameter through which such a name could get in.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from worklog.models import LogEntry

_V1_PATH = "/openai/v1"
_CHAT_COMPLETIONS = "/chat/completions"

# The user may replace all of it in the settings; "Zurücksetzen" brings this text back.
DEFAULT_SYSTEM_PROMPT = """\
Du bereinigst Tätigkeitsbeschreibungen aus einer Zeiterfassung, die später dem Kunden in Rechnung gestellt werden.

Du erhältst optional eine Zeile "Task:" (nur als Kontext) und danach unter "Beschreibung:" den zu bereinigenden Text.

Regeln:
- Schreibe knapp, sachlich und abrechnungstauglich: Stichpunkt-Stil ohne "ich", ohne Füllwörter und Umgangssprache; korrigiere Tippfehler, Grammatik und Groß-/Kleinschreibung; schreibe gängige Abkürzungen wie "wg", "bzgl" oder "bissl" aus oder ersetze sie.
- Erfinde nichts: keine Tätigkeiten, Details, Ergebnisse oder Zeitangaben ergänzen, die nicht im Text stehen. Lasse nichts Inhaltliches weg.
- Behalte die Sprache der Eingabe bei; übersetze nicht.
- Ein Präfix am Anfang der Beschreibung, das mit einem Doppelpunkt endet (z.B. "Codereview, Recherche: …"), bleibt wörtlich und unverändert am Anfang stehen; bereinige nur den Text dahinter.
- Ticket-Keys (z.B. DIS-1234), Bezeichner, Dateinamen, URLs, Versionsnummern und Zahlen bleiben wörtlich erhalten.
- Wiederhole den Task nicht in der Antwort, wenn er nicht schon in der Beschreibung steht.
- Ist die Beschreibung bereits sauber, gib sie unverändert zurück.
- Antworte ausschließlich mit dem bereinigten Text: keine Anführungszeichen, keine Einleitung, keine Erklärung, kein "Beschreibung:".
"""


class LlmCleanupError(RuntimeError):
    """Generic failure of the LLM-Bereinigung. The message is readable for the user."""


class LlmNetworkError(LlmCleanupError):
    """The endpoint could not be reached (DNS, offline, timeout)."""


class LlmAuthError(LlmCleanupError):
    """401/403 — the API key was rejected."""


class LlmModelError(LlmCleanupError):
    """Any other HTTP error: unknown deployment, rate limit, content filter, server error."""


class LlmEmptyResponseError(LlmCleanupError):
    """The model answered, but with no usable text."""


@dataclass(slots=True, frozen=True)
class LlmCredentials:
    endpoint: str     # e.g. "https://your-resource.openai.azure.com"
    deployment: str   # deployment name, sent as "model"
    api_key: str


def chat_completions_url(endpoint: str) -> str:
    """Full URL of the chat completions call for whatever form of endpoint was pasted."""
    base = endpoint.strip().rstrip("/")
    if base.endswith(_CHAT_COMPLETIONS):
        return base
    if base.endswith(_V1_PATH):
        return base + _CHAT_COMPLETIONS
    return base + _V1_PATH + _CHAT_COMPLETIONS


def _user_message(task: Optional[str], description: str) -> str:
    """The only entry data that leaves the machine: task and description."""
    task = (task or "").strip()
    lines = [f"Task: {task}"] if task else []
    lines += ["Beschreibung:", description.strip()]
    return "\n".join(lines)


_QUOTE_PAIRS = {'"': '"', "'": "'", "„": "“”\"", "“": "”", "‚": "‘’", "‘": "’", "»": "«", "«": "»"}


def postprocess_answer(answer: str) -> str:
    """Trim, and drop quotes that wrap the whole answer (models like to add them).

    Quotes that belong to the text — `"Login" und "Logout" korrigiert` — stay.
    """
    text = answer.strip()
    while len(text) >= 2 and text[-1] in _QUOTE_PAIRS.get(text[0], ""):
        inner = text[1:-1]
        if text[0] in inner or text[-1] in inner:
            break
        text = inner.strip()
    return text


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The provider's own message ({"error": {"message": ...}}) if there is one."""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    try:
        message = json.loads(raw)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = ""
    return str(message or raw[:200] or exc.reason)


def _chat(creds: LlmCredentials, messages: list[dict], opener) -> dict:
    """One chat completions call; returns the decoded response or raises LlmCleanupError."""
    payload = {"model": creds.deployment, "messages": messages}
    req = urllib.request.Request(
        chat_completions_url(creds.endpoint),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "api-key": creds.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with opener(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise LlmAuthError(
                f"Anmeldung am LLM fehlgeschlagen ({exc.code}): Der API-Key wurde abgelehnt."
            ) from exc
        detail = _error_detail(exc)
        raise LlmModelError(f"Das LLM meldet einen Fehler (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise LlmNetworkError(f"LLM-Endpoint nicht erreichbar: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise LlmNetworkError(f"LLM-Endpoint nicht erreichbar: {exc}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LlmCleanupError(f"Unverständliche Antwort vom LLM: {body[:200]}") from exc
    if not isinstance(data, dict):
        raise LlmCleanupError(f"Unverständliche Antwort vom LLM: {body[:200]}")
    return data


def clean_description(
    creds: LlmCredentials,
    *,
    task: Optional[str],
    description: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    opener=urllib.request.urlopen,
) -> str:
    """Send task and description to the model; return the cleaned description.

    `opener` is injectable for tests. Raises LlmCleanupError (or a subclass that
    tells network, auth, model and empty answer apart) with a readable message.
    """
    data = _chat(
        creds,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_message(task, description)},
        ],
        opener,
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    cleaned = postprocess_answer(content if isinstance(content, str) else "")
    if not cleaned:
        raise LlmEmptyResponseError("Das LLM hat eine leere Antwort geliefert.")
    return cleaned


def test_connection(creds: LlmCredentials, opener=urllib.request.urlopen) -> str:
    """Send a tiny request to verify endpoint, deployment and key. Returns the model's name."""
    data = _chat(creds, [{"role": "user", "content": "Antworte nur mit: OK"}], opener)
    return str(data.get("model") or creds.deployment)


def clean_entry_description(
    creds: LlmCredentials,
    entry: LogEntry,
    *,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    opener=urllib.request.urlopen,
) -> str:
    """Clean the description of one Eintrag. Of the entry, only task and description are sent."""
    return clean_description(
        creds,
        task=entry.task,
        description=entry.description or "",
        system_prompt=system_prompt,
        opener=opener,
    )
