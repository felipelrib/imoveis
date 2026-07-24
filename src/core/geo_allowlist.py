"""Operator geo allowlist for scrape ingest (BIN-68).

Rejects candidates whose city/state fall outside the configured scrape geo
(default: Belo Horizonte / MG). Missing city/state does not reject — only
explicit out-of-allowlist values do.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional, Sequence


def _fold(value: str) -> str:
    """Lowercase and strip accents for stable city/state comparison."""
    normalized = unicodedata.normalize("NFKD", value.strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


# Common abbreviations seen in platform payloads (BIN-68).
_CITY_ALIASES = {
    "bh": "belo horizonte",
    "b.h.": "belo horizonte",
    "b h": "belo horizonte",
}


def _canonical_city(value: str) -> str:
    folded = _fold(value)
    return _CITY_ALIASES.get(folded, folded)


def _normalize_set(values: Iterable[str]) -> set[str]:
    return {_canonical_city(v) for v in values if v and str(v).strip()}


def extract_city_state(candidate: Any) -> tuple[Optional[str], Optional[str]]:
    """Pull city/state from props_json, then fall back to address tokens."""
    props = getattr(candidate, "props_json", None) or {}
    if not isinstance(props, Mapping):
        props = {}
    city = props.get("city") or props.get("cityName") or props.get("municipality")
    state = props.get("state") or props.get("uf") or props.get("region")
    if city or state:
        return (
            str(city).strip() if city else None,
            str(state).strip() if state else None,
        )

    address = getattr(candidate, "address", None) or ""
    if not address:
        return None, None

    # Prefer ", City - UF" / ", City, UF" tails common in BR listings.
    m = re.search(
        r",\s*([^,]+?)\s*[-–]\s*([A-Za-z]{2})\s*$",
        address,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip().upper()
    m = re.search(r",\s*([^,]+),\s*([A-Za-z]{2})\s*$", address)
    if m:
        return m.group(1).strip(), m.group(2).strip().upper()
    return None, None


def passes_geo_allowlist(
    candidate: Any,
    *,
    cities: Sequence[str],
    states: Sequence[str],
    enabled: bool = True,
) -> tuple[bool, Optional[str]]:
    """Return (ok, reject_reason). When disabled, always allows.

    Reject when an extracted city is outside ``cities`` or an extracted state
    is outside ``states``. Unknown city/state → allow (avoid dropping incomplete
    but otherwise valid BH payloads).
    """
    if not enabled:
        return True, None

    allowed_cities = _normalize_set(cities)
    allowed_states = _normalize_set(states)
    if not allowed_cities and not allowed_states:
        return True, None

    city, state = extract_city_state(candidate)
    if city and allowed_cities and _canonical_city(city) not in allowed_cities:
        return False, f"city_not_allowed:{city}"
    if state and allowed_states and _fold(state) not in allowed_states:
        return False, f"state_not_allowed:{state}"
    return True, None
