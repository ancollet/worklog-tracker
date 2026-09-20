"""Snippet anwenden: Präfix-Regeln für Beschreibungen (Qt-frei)."""
from __future__ import annotations

from typing import Iterable

_SEPARATOR = ": "


def _split_prefix(description: str, known_snippets: Iterable[str]) -> tuple[list[str], str]:
    """Split into (snippets in the prefix, rest). No snippet prefix → ([], description).

    The prefix is the part before the first ": " — but only if every
    comma-separated part of it is a known snippet.
    """
    head, sep, rest = description.partition(_SEPARATOR)
    if not sep:
        # A prefix without text is stored trimmed: "Codereview: " comes back as "Codereview:".
        if not description.endswith(_SEPARATOR.strip()):
            return [], description
        head, rest = description[: -len(_SEPARATOR.strip())], ""
    known = {s.strip().casefold() for s in known_snippets}
    parts = [p.strip() for p in head.split(",")]
    if all(p and p.casefold() in known for p in parts):
        return parts, rest
    return [], description


def apply_snippet(description: str, snippet: str, known_snippets: Iterable[str]) -> str:
    """Return the description with the snippet inserted as prefix."""
    parts, rest = _split_prefix(description, known_snippets)
    if snippet.casefold() in {p.casefold() for p in parts}:
        return description
    return f"{', '.join(parts + [snippet])}{_SEPARATOR}{rest}"
