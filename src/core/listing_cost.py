"""Total Monthly Cost rules for a Listing (Story 1.1, FR-31, AD-3).

One definition of the cost mapping, used by the persist path
(``core.dedupe._upsert_listings``) and by the repopulation of rows stored
before the story. Pure: standard library only, no ``adapters`` / ``api`` /
``infra`` import (AD-1).

Rules
-----
* A missing, zero or negative published component is ``unknown`` (``None``),
  never ``0``. Nothing is imputed, defaulted or estimated.
* ``rent_monthly`` is the platform's unbundled rent; a sale Listing has none.
* A combined condo+IPTU figure with no separately published fee is *bundled*:
  it lands in ``condo_fee_monthly``, ``iptu_monthly`` stays ``None`` and the
  total is still complete.
* IPTU periodicity is taken from the platform when it itemizes monthly;
  otherwise it is classified by magnitude against the Listing's own reference
  (rent for rent, sale price for sale). Between the two thresholds the figure
  is ambiguous: periodicity ``unknown``, no division, no value.
* ``total_monthly_cost`` = rent + condo fee + monthly IPTU, rent Listings
  only, ``None`` whenever a component is unknown and not bundled.
  ``cost_complete`` is true exactly when the total has a value.
"""

from __future__ import annotations

import json
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional

COST_COLUMNS: tuple[str, ...] = (
    "rent_monthly",
    "condo_fee_monthly",
    "iptu_monthly",
    "iptu_periodicity_source",
    "fees_bundled",
    "total_monthly_cost",
    "cost_complete",
)

PERIODICITY_MONTHLY = "monthly"
PERIODICITY_ANNUAL = "annual"
PERIODICITY_UNKNOWN = "unknown"
IPTU_PERIODICITIES: tuple[str, ...] = (
    PERIODICITY_MONTHLY,
    PERIODICITY_ANNUAL,
    PERIODICITY_UNKNOWN,
)

# Key under which scrapers stamp the platform's raw cost figures in a
# listing's stored ``raw_json``.
COST_SOURCE_KEY = "cost_source"

# IPTU periodicity by magnitude. Live probe 2026-10-08 (60 BH ZapImóveis
# listings): monthly IPTU sits at 3-14% of the rent, annual at 51-105%; for
# sale 0.01-0.06% vs 0.33-0.41% of the price. The gap between the clusters is
# the ambiguity band.
RENT_IPTU_MONTHLY_MAX_RATIO = 0.15
RENT_IPTU_ANNUAL_MIN_RATIO = 0.40
SALE_IPTU_MONTHLY_MAX_RATIO = 0.0010
SALE_IPTU_ANNUAL_MIN_RATIO = 0.0025

_CENT = Decimal("0.01")
_MONTHS = Decimal(12)

# Legacy QuintoAndar ``raw_json.fees_note`` that marks a published ``condoIptu``
# figure. Any other note on a bundled row (the ``totalCost - rentPrice``
# remainder) is not a published fee.
_QA_PUBLISHED_BUNDLE_NOTE = "condoIptu is a bundled condo+IPTU field"


def _number(value: Any) -> Optional[float]:
    """Parse a published figure; ``None`` when it is not a finite number."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, ArithmeticError):  # OverflowError is an ArithmeticError
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: Any) -> Optional[float]:
    """A component is known only when it is published and above zero."""
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _cents(value: Decimal) -> float:
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _declared_periodicity(value: Any) -> Optional[str]:
    if value in (PERIODICITY_MONTHLY, PERIODICITY_ANNUAL):
        return value
    return None


def _classify_iptu(iptu: float, reference: Optional[float], listing_type: str) -> str:
    """Infer the periodicity of ``iptu`` from its size against ``reference``."""
    if reference is None:
        return PERIODICITY_UNKNOWN
    if listing_type == "rent":
        monthly_max, annual_min = RENT_IPTU_MONTHLY_MAX_RATIO, RENT_IPTU_ANNUAL_MIN_RATIO
    elif listing_type == "sale":
        monthly_max, annual_min = SALE_IPTU_MONTHLY_MAX_RATIO, SALE_IPTU_ANNUAL_MIN_RATIO
    else:
        return PERIODICITY_UNKNOWN
    amount, base = Decimal(str(iptu)), Decimal(str(reference))
    if amount <= base * Decimal(str(monthly_max)):
        return PERIODICITY_MONTHLY
    if amount >= base * Decimal(str(annual_min)):
        return PERIODICITY_ANNUAL
    return PERIODICITY_UNKNOWN


def compute_listing_cost(
    *,
    listing_type: str,
    rent: Any = None,
    condo_fee: Any = None,
    iptu: Any = None,
    fees_combined: Any = None,
    iptu_periodicity: Any = None,
    sale_price: Any = None,
) -> dict[str, Any]:
    """Map a Listing's published cost figures to the typed cost columns.

    ``rent`` is the platform's unbundled rent, ``fees_combined`` a published
    condo+IPTU figure that cannot be split, ``iptu_periodicity`` the
    periodicity the platform declares (``monthly`` / ``annual``) or ``None``
    when it declares none, ``sale_price`` the reference for a sale Listing.
    """
    is_rent = listing_type == "rent"
    rent_monthly = _positive(rent) if is_rent else None
    condo = _positive(condo_fee)
    iptu_published = _positive(iptu)
    combined = _positive(fees_combined)

    bundled = condo is None and iptu_published is None and combined is not None
    iptu_monthly: Optional[float] = None
    periodicity = PERIODICITY_UNKNOWN

    if bundled:
        condo = combined
    elif iptu_published is not None:
        reference = rent_monthly if is_rent else _positive(sale_price)
        periodicity = _declared_periodicity(iptu_periodicity) or _classify_iptu(
            iptu_published, reference, listing_type
        )
        if periodicity == PERIODICITY_MONTHLY:
            iptu_monthly = iptu_published
        elif periodicity == PERIODICITY_ANNUAL:
            iptu_monthly = _cents(Decimal(str(iptu_published)) / _MONTHS)

    total: Optional[float] = None
    if rent_monthly is not None and condo is not None and (bundled or iptu_monthly is not None):
        total = _cents(
            Decimal(str(rent_monthly))
            + Decimal(str(condo))
            + Decimal(str(iptu_monthly or 0))
        )

    return {
        "rent_monthly": rent_monthly,
        "condo_fee_monthly": condo,
        "iptu_monthly": iptu_monthly,
        "iptu_periodicity_source": periodicity,
        "fees_bundled": bundled,
        "total_monthly_cost": total,
        "cost_complete": total is not None,
    }


def build_cost_source(
    *,
    rent: Any = None,
    condo_fee: Any = None,
    iptu: Any = None,
    fees_combined: Any = None,
    iptu_periodicity: Any = None,
) -> dict[str, Any]:
    """Build the ``raw_json["cost_source"]`` stamp from a platform's raw payload.

    Figures are kept as published (a raw ``0`` stays ``0``; the mapping decides
    it is unknown); anything that is not a finite number becomes ``None`` so
    the stamp is always valid JSON.
    """
    return {
        "rent": _number(rent),
        "condo_fee": _number(condo_fee),
        "iptu": _number(iptu),
        "fees_combined": _number(fees_combined),
        "iptu_periodicity": _declared_periodicity(iptu_periodicity),
    }


def _raw_json_dict(raw_json: Any) -> dict:
    """Stored ``raw_json`` as a dict; anything malformed is ``{}``."""
    if isinstance(raw_json, dict):
        return raw_json
    if isinstance(raw_json, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw_json)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _legacy_cost_source(listing: Mapping[str, Any], raw_json: dict) -> dict[str, Any]:
    """Rebuild the stamp's inputs for a row stored before the stamp existed."""
    platform = listing.get("platform")
    is_rent = listing.get("listing_type") == "rent"
    condo_fee = listing.get("condo_fee")
    iptu = listing.get("iptu")
    fees_combined = None
    periodicity = None

    if platform == "quintoandar":
        # ``partial_price`` is the raw ``rentPrice``; ``price`` is ``totalCost``.
        rent = raw_json.get("partial_price") if is_rent else None
        if _positive(rent) is None and is_rent:
            rent = listing.get("base_price")
        periodicity = PERIODICITY_MONTHLY
        if raw_json.get("fees_bundled"):
            # The legacy ``condo_fee`` holds either the published ``condoIptu``
            # or the ``totalCost - rentPrice`` remainder; only the first is a fee.
            if raw_json.get("fees_note") == _QA_PUBLISHED_BUNDLE_NOTE:
                fees_combined = condo_fee
            condo_fee, iptu = None, None
    elif platform == "olx":
        # ``price`` is rent + condo + IPTU with a missing fee summed as zero.
        rent = listing.get("base_price") if is_rent else None
    elif platform == "zapimoveis":
        rent = listing.get("price") if is_rent else None
    else:
        rent = listing.get("base_price") if is_rent else None

    return build_cost_source(
        rent=rent,
        condo_fee=condo_fee,
        iptu=iptu,
        fees_combined=fees_combined,
        iptu_periodicity=periodicity,
    )


def listing_cost_columns(listing: Mapping[str, Any]) -> dict[str, Any]:
    """Cost columns for a listing dict (normalizer output or a stored row).

    Reads ``raw_json["cost_source"]`` when the scraper stamped it; otherwise
    rebuilds the identical inputs from the stored legacy fields, so a row
    persisted before the stamp yields what a fresh scrape of the same figures
    would.
    """
    raw_json = _raw_json_dict(listing.get("raw_json"))
    source = raw_json.get(COST_SOURCE_KEY)
    if not isinstance(source, dict):
        source = _legacy_cost_source(listing, raw_json)
    listing_type = listing.get("listing_type")
    return compute_listing_cost(
        listing_type=listing_type if isinstance(listing_type, str) else "",
        rent=source.get("rent"),
        condo_fee=source.get("condo_fee"),
        iptu=source.get("iptu"),
        fees_combined=source.get("fees_combined"),
        iptu_periodicity=source.get("iptu_periodicity"),
        sale_price=listing.get("price") if listing_type == "sale" else None,
    )
