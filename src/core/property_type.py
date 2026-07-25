"""Canonical property-type codes (English snake_case) and alias matching.

Scrapers persist ``props_json.type`` as one of the canonical codes; the API
filter accepts either the canonical key or a known platform/legacy alias.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

CANONICAL_TYPES = ("apartment", "house", "condo_house", "studio")

# Folded alias → canonical. Keys are lowercase, accent-stripped, with spaces
# and hyphens collapsed to underscores (and also without underscores).
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "apartment": "apartment",
    "apartamento": "apartment",
    "apartamentos": "apartment",
    "apto": "apartment",
    "apt": "apartment",
    "house": "house",
    "casa": "house",
    "casas": "house",
    "condo_house": "condo_house",
    "casa_condominio": "condo_house",
    "casacondominio": "condo_house",
    "casa_em_condominio": "condo_house",
    "casaemcondominio": "condo_house",
    "studio": "studio",
    "kitnet": "studio",
    "kitinete": "studio",
    "kit": "studio",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
    folded = re.sub(r"[\s\-]+", "_", folded)
    return folded


def normalize_property_type(value: Optional[str]) -> Optional[str]:
    """Map a raw platform / UI value to a canonical English snake_case type."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    folded = _fold(text)
    if folded in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[folded]
    compact = folded.replace("_", "")
    return _ALIAS_TO_CANONICAL.get(compact)


def infer_property_type_from_text(text: Optional[str]) -> Optional[str]:
    """Best-effort type from free text (title/subject) via alias token match."""
    if text is None:
        return None
    folded = _fold(str(text))
    if not folded:
        return None
    for alias in sorted(_ALIAS_TO_CANONICAL, key=len, reverse=True):
        if (
            folded == alias
            or folded.startswith(f"{alias}_")
            or folded.endswith(f"_{alias}")
            or f"_{alias}_" in folded
        ):
            return _ALIAS_TO_CANONICAL[alias]
    return None


def match_values_for_filter(raw: str) -> list[str]:
    """Return LOWER() match set for SQL IN — canonical + all known aliases.

    If ``raw`` does not normalize, returns ``[raw.lower()]`` so callers can
    still attempt an exact match on unexpected values.
    """
    canonical = normalize_property_type(raw)
    if canonical is None:
        return [str(raw).strip().lower()]
    aliases = {canonical}
    for alias, target in _ALIAS_TO_CANONICAL.items():
        if target == canonical:
            aliases.add(alias)
    return sorted(aliases)
