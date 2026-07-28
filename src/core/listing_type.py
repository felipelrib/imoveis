"""Canonical listing_type / price_type codes and PT synonym resolution (BIN-100).

Persisted wire stays English (``rent`` / ``sale``). Filter APIs may accept
documented Portuguese aliases which normalize before query building.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Folded alias → canonical listing_type (includes filter sentinel ``both``).
_LISTING_ALIAS_TO_CANONICAL: dict[str, str] = {
    "rent": "rent",
    "aluguel": "rent",
    "alugar": "rent",
    "sale": "sale",
    "venda": "sale",
    "vender": "sale",
    "comprar": "sale",
    "both": "both",
    "ambos": "both",
}

# price_type has no ``both`` sentinel.
_PRICE_ALIAS_TO_CANONICAL: dict[str, str] = {
    "rent": "rent",
    "aluguel": "rent",
    "alugar": "rent",
    "sale": "sale",
    "venda": "sale",
    "vender": "sale",
    "comprar": "sale",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
    folded = re.sub(r"[\s\-]+", "_", folded)
    return folded


def normalize_listing_type(value: Optional[str]) -> Optional[str]:
    """Map a raw / PT alias to canonical ``rent`` | ``sale`` | ``both``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    folded = _fold(text)
    if folded in _LISTING_ALIAS_TO_CANONICAL:
        return _LISTING_ALIAS_TO_CANONICAL[folded]
    compact = folded.replace("_", "")
    return _LISTING_ALIAS_TO_CANONICAL.get(compact)


def normalize_price_type(value: Optional[str]) -> Optional[str]:
    """Map a raw / PT alias to canonical ``rent`` | ``sale`` (no ``both``)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    folded = _fold(text)
    if folded in _PRICE_ALIAS_TO_CANONICAL:
        return _PRICE_ALIAS_TO_CANONICAL[folded]
    compact = folded.replace("_", "")
    return _PRICE_ALIAS_TO_CANONICAL.get(compact)
