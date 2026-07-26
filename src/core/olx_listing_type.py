"""OLX rent/sale inference helpers (title cues + price band).

Path stamps (``/venda/``, ``/aluguel/``) remain authoritative in the scraper.
These helpers cover category-less detail URLs and backfill scripts — and must
not treat the neighbourhood **Venda Nova** (or slug ``venda-nova``) as a sale cue.
"""

from __future__ import annotations

import re
from typing import Optional

# Phrases that imply rent/sale in titles. Bare ``venda`` is handled separately
# after masking the Venda Nova neighbourhood so it cannot false-positive.
_RENT_TITLE_CUES = (
    "alugo",
    "aluguel",
    "para alugar",
    "aluga-se",
    "aluga se",
    "para locação",
    "para locacao",
    "locação",
    "locacao",
)
_SALE_TITLE_PHRASES = (
    "à venda",
    "a venda",
    "vende-se",
    "vende se",
    "para venda",
)

_VENDA_NOVA_RE = re.compile(r"venda[\s\-]*nova", re.IGNORECASE)
_VENDO_WORD_RE = re.compile(r"\bvendo\b", re.IGNORECASE)
_VENDA_WORD_RE = re.compile(r"\bvenda\b", re.IGNORECASE)

# Price bands used when stamp/path/title are inconclusive (BRL).
_SALE_PRICE_FLOOR = 80_000.0
_RENT_PRICE_CEILING = 30_000.0


def mask_venda_nova(text: str) -> str:
    """Remove Venda Nova neighbourhood mentions so ``venda`` cues stay safe."""
    return _VENDA_NOVA_RE.sub(" ", text or "")


def listing_type_from_title(title: str | None) -> Optional[str]:
    """Return ``rent`` / ``sale`` from title cues, or None if inconclusive.

    Dual titles (``venda ou locação``) return None so the price band can decide.
    """
    if not title:
        return None
    folded = mask_venda_nova(title).casefold()
    has_rent = any(cue in folded for cue in _RENT_TITLE_CUES)
    has_sale = any(cue in folded for cue in _SALE_TITLE_PHRASES)
    if _VENDO_WORD_RE.search(folded) or _VENDA_WORD_RE.search(folded):
        has_sale = True
    if has_rent and has_sale:
        return None
    if has_rent:
        return "rent"
    if has_sale:
        return "sale"
    return None


def listing_type_from_price(price: float | None) -> Optional[str]:
    """Return ``rent`` / ``sale`` from price band, or None if mid-band / missing."""
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value >= _SALE_PRICE_FLOOR:
        return "sale"
    if 0 < value < _RENT_PRICE_CEILING:
        return "rent"
    return None


def infer_olx_listing_type(
    *,
    title: str | None = None,
    price: float | None = None,
    current: str | None = None,
) -> str:
    """Best-effort rent/sale when path stamp is unavailable.

    Order: title cues (Venda Nova–safe; dual titles inconclusive) → price band.
    When title and price disagree, prefer the price band (dual listings often
    mention both rent and sale while storing one price).
    """
    from_title = listing_type_from_title(title)
    from_price = listing_type_from_price(price)
    if from_title and from_price and from_title != from_price:
        return from_price
    if from_title:
        return from_title
    if from_price:
        return from_price
    if current in ("rent", "sale"):
        return current
    return "sale"
