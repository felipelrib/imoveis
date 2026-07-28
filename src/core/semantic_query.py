"""PT↔EN housing lexicon expansion for semantic search queries (BIN-102).

Corpus titles/descriptions are predominantly Portuguese; English ``q=`` queries
can miss domain terms (``penthouse`` vs ``cobertura``). Expand matched lexicon
entries by *appending* missing counterparts before embedding — never strip the
user's words. Index text stays scraped title+description only.
"""

from __future__ import annotations

import re
import unicodedata

# Synonym groups: if any member matches the query, append every other member
# that is not already present as a surface form (accent-sensitive).
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("penthouse", "cobertura"),
    ("backyard", "quintal"),
    ("doorman", "portaria"),
    ("townhouse", "sobrado"),
    ("luxury", "luxo"),
    ("metro", "subway", "metrô"),
    ("garage", "garagem"),
)


def _fold(value: str) -> str:
    """Lowercase + strip accents for fuzzy match (``metrô`` ≡ ``metro``)."""
    normalized = unicodedata.normalize("NFKD", value.strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _has_surface(haystack: str, term: str) -> bool:
    """True if ``term`` appears as a whole word (case-insensitive, accents kept)."""
    pattern = r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)"
    return re.search(pattern, haystack.casefold(), flags=re.UNICODE) is not None


def _has_folded(haystack_folded: str, term: str) -> bool:
    """True if accent-stripped ``term`` appears as a whole word in folded text."""
    pattern = r"(?<!\w)" + re.escape(_fold(term)) + r"(?!\w)"
    return re.search(pattern, haystack_folded, flags=re.UNICODE) is not None


def normalize_semantic_query(text: str | None) -> str:
    """Append missing PT↔EN housing synonyms for embedding input.

    Returns stripped ``text``, or ``""`` for empty/None. Idempotent when both
    sides of each matched group are already present as surface forms.
    """
    if text is None:
        return ""
    original = str(text).strip()
    if not original:
        return ""

    folded_haystack = _fold(original)
    to_append: list[str] = []
    seen_append: set[str] = set()

    for group in _SYNONYM_GROUPS:
        if not any(_has_folded(folded_haystack, term) for term in group):
            continue
        for term in group:
            if _has_surface(original, term):
                continue
            key = term.casefold()
            if key in seen_append:
                continue
            to_append.append(term)
            seen_append.add(key)

    if not to_append:
        return original
    return f"{original} {' '.join(to_append)}"
