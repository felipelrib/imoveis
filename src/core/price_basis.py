"""Cohort price basis (Story 1.3, AD-3) — the one definition of "the price a
Listing contributes to a price/m² cohort".

Platforms disagree on what a rent Listing's headline ``price`` is: QuintoAndar
and OLX fold condo fee and IPTU into it, ZapImóveis does not. A cohort built
on the headline therefore mixes two prices. The basis rule:

* Per active Listing with ``price > 0`` and type ``rent`` or ``sale``:
  a rent Listing contributes its fee-exclusive ``rent_monthly`` when that is
  not NULL and above zero (basis ``rent_monthly``); otherwise its headline
  ``price`` (basis ``headline``). A sale Listing always contributes ``price``.
* Per Property × listing type: the lowest cohort price among its Listings.
  The stamp is the basis of the Listing that supplied it; on an exact tie
  ``rent_monthly`` wins.
* Nothing is excluded or imputed: a cohort may hold both bases.

The rule is written twice, side by side, because the bulk and cached scoring
paths are SQL and the single-property path is Python: ``COHORT_PRICE_SQL`` /
``COHORT_PRICE_FOR_TYPE_SQL`` and ``property_cohort_prices``. An integration
test pins the two to each other on the same rows. Consumers import these and
never read ``property_listings.price`` for a cohort themselves.

Total Monthly Cost is a different comparable and is never the cohort basis.

Pure: standard library only, no ``adapters`` / ``api`` / ``infra`` import
(AD-1). The SQL is static text; the only bound parameter is ``:lt``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, NamedTuple, Optional

PRICE_BASIS_RENT_MONTHLY = "rent_monthly"
PRICE_BASIS_HEADLINE = "headline"
PRICE_BASES: tuple[str, ...] = (PRICE_BASIS_RENT_MONTHLY, PRICE_BASIS_HEADLINE)

# SQL literal for rows whose price does not come from a Listing (the legacy
# ``properties.price`` fallback).
PRICE_BASIS_HEADLINE_SQL = "'headline'"

COHORT_LISTING_TYPES: tuple[str, ...] = ("rent", "sale")

# --- SQL expression of the rule -------------------------------------------

# True for a Listing that contributes its unbundled rent.
_USES_RENT_SQL = "(pl.listing_type = 'rent' AND pl.rent_monthly IS NOT NULL AND pl.rent_monthly > 0)"
# The price one Listing contributes.
_LISTING_PRICE_SQL = "(CASE WHEN " + _USES_RENT_SQL + " THEN pl.rent_monthly ELSE pl.price END)"

_SELECT_SQL = (
    """
            SELECT
                pl.property_id,
                pl.listing_type,
                MIN("""
    + _LISTING_PRICE_SQL
    + """) AS price,
                CASE
                    WHEN MIN("""
    + _LISTING_PRICE_SQL
    + """) FILTER (WHERE """
    + _USES_RENT_SQL
    + """)
                         = MIN("""
    + _LISTING_PRICE_SQL
    + """)
                        THEN 'rent_monthly'
                    ELSE 'headline'
                END AS price_basis
            FROM property_listings pl
            WHERE pl.active = true
              AND pl.price > 0
              AND pl.listing_type IN ('rent', 'sale')"""
)
_GROUP_SQL = """
            GROUP BY pl.property_id, pl.listing_type
"""

# Relation ``(property_id, listing_type, price, price_basis)``: one row per
# Property × listing type that has an active priced Listing. Use it as the
# body of a CTE or a subquery.
COHORT_PRICE_SQL = _SELECT_SQL + _GROUP_SQL

# The same relation restricted to one listing type, bound as ``:lt``.
COHORT_PRICE_FOR_TYPE_SQL = (
    _SELECT_SQL
    + """
              AND pl.listing_type = :lt"""
    + _GROUP_SQL
)


# --- Python mirror of the rule --------------------------------------------


class CohortPrice(NamedTuple):
    """The price a Listing or a Property contributes, and where it came from."""

    price: float
    price_basis: str


def listing_cohort_price(
    *,
    listing_type: Any,
    price: Any,
    rent_monthly: Any = None,
    active: Any = True,
) -> Optional[CohortPrice]:
    """The price one Listing contributes; ``None`` when it contributes nothing.

    Mirrors the ``WHERE`` and the per-Listing ``CASE`` of ``COHORT_PRICE_SQL``.
    """
    if active is not True or listing_type not in COHORT_LISTING_TYPES:
        return None
    if price is None or not price > 0:
        return None
    if listing_type == "rent" and rent_monthly is not None and rent_monthly > 0:
        return CohortPrice(float(rent_monthly), PRICE_BASIS_RENT_MONTHLY)
    return CohortPrice(float(price), PRICE_BASIS_HEADLINE)


def property_cohort_prices(listings: Iterable[Mapping[str, Any]]) -> dict[str, CohortPrice]:
    """``{listing_type: CohortPrice}`` for one Property's Listings.

    Each mapping carries ``listing_type``, ``price``, ``rent_monthly`` and
    ``active`` (extra keys are ignored). Mirrors the ``GROUP BY`` of
    ``COHORT_PRICE_SQL``: the lowest contributed price per type, and
    ``rent_monthly`` on an exact tie.
    """
    best: dict[str, CohortPrice] = {}
    for listing in listings:
        candidate = listing_cohort_price(
            listing_type=listing.get("listing_type"),
            price=listing.get("price"),
            rent_monthly=listing.get("rent_monthly"),
            active=listing.get("active"),
        )
        if candidate is None:
            continue
        listing_type = str(listing.get("listing_type"))
        current = best.get(listing_type)
        if (
            current is None
            or candidate.price < current.price
            or (
                candidate.price == current.price
                and candidate.price_basis == PRICE_BASIS_RENT_MONTHLY
            )
        ):
            best[listing_type] = candidate
    return best


def row_price_basis(rent_basis: Optional[str]) -> str:
    """The ``metrics_scoring.price_basis`` stamp for one scored row.

    The stamp describes the row's rent price/m². ``rent_basis`` is the basis
    of the Listing that supplied it, or ``None`` when no Listing did: a
    sale-only row, or a row scored from the legacy ``properties.price``
    fallback. Those are ``headline``.
    """
    if rent_basis is None:
        return PRICE_BASIS_HEADLINE
    if rent_basis not in PRICE_BASES:
        raise ValueError(f"unknown price basis: {rent_basis!r}")
    return rent_basis
