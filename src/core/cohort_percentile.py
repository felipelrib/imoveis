"""Cohort price/m² percentile (Story 1.6, FR-30) — the one definition.

"Among the N% cheapest of its neighbourhood": for one Property and one
listing type, the share of its cohort priced at or below it.

* Percentile = (cohort members with price/m² <= this Property's) / cohort
  size. It lies in (0, 1]; lower is cheaper; ``0.25`` reads "among the 25%
  cheapest". Tied members share one value (the inclusive count), so the
  sentence is literally true of every member.
* A cohort smaller than the minimum size has no percentile (``None``). The
  minimum is config-owned (``scoring.percentile_min_cohort_size``) and never
  below ``MIN_COHORT_SIZE_FLOOR``: a cohort of one never has a percentile.
* Nothing is imputed: there is no neutral default for "unknown".

Cohort key: listing type x city x neighbourhood. ``COHORT_NEIGHBOURHOOD_SQL``
and ``COHORT_CITY_SQL`` are the two SQL expressions of that key, written
against the aliases ``p`` (``properties``) and ``n`` (``neighborhoods``,
left-joined on ``p.neighborhood_id``). The spatial assignment wins: name and
city come from the ``neighborhoods`` row when the Property has one, else from
the ``props_json`` labels. Both are compared folded (``_fold_sql``): lower
case, Portuguese accents removed, runs of whitespace collapsed to one space,
trimmed. Platforms spell the same neighbourhood differently (``São Bento`` /
``Sao Bento`` / ``SAO  BENTO``); unfolded, each spelling is its own cohort. A
Property with no assignment and a blank or missing label has no neighbourhood
(``NULL``) and is in no cohort; a missing city is the empty string, which is a
key like any other.

SQL only counts (``cohort_size`` and ``at_or_below`` per member); the division
and the minimum-size rule live in ``cohort_percentile``. The price a member is
ranked on comes from ``core.price_basis.COHORT_PRICE_SQL`` in the caller; this
module names no price column.

Pure: standard library only, no ``adapters`` / ``api`` / ``infra`` import
(AD-1). The SQL is static text with no bound parameter.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Optional, Sequence

# A cohort of one never has a percentile, whatever the configuration says.
MIN_COHORT_SIZE_FLOOR = 2

# --- SQL expressions of the cohort key ---------------------------------------

# Accented letters a label can carry, both cases (LOWER leaves an accented
# capital alone under a C ctype), and the plain letter each one folds to.
_ACCENTED = "áàâãäåéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÅÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_PLAIN = "aaaaaaeeeeiiiiooooouuuucnaaaaaaeeeeiiiiooooouuuucn"
assert len(_ACCENTED) == len(_PLAIN)


def _fold_sql(expression: str) -> str:
    """SQL text folding ``expression``: NFC, lower case, no accents, single spaces, trimmed."""
    return (
        "BTRIM(REGEXP_REPLACE(TRANSLATE(LOWER(NORMALIZE("
        + expression
        + ", NFC)), '"
        + _ACCENTED
        + "', '"
        + _PLAIN
        + "'), '\\s+', ' ', 'g'))"
    )


# NULL when the Property has no spatial assignment and no usable label.
COHORT_NEIGHBOURHOOD_SQL = (
    "NULLIF("
    + _fold_sql("CASE WHEN n.id IS NOT NULL THEN n.name ELSE p.props_json->>'neighborhood' END")
    + ", '')"
)

# Never NULL: an unknown city is the empty string.
COHORT_CITY_SQL = (
    "COALESCE("
    + _fold_sql("CASE WHEN n.id IS NOT NULL THEN n.city ELSE p.props_json->>'city' END")
    + ", '')"
)


# --- The rule -----------------------------------------------------------------


def validate_min_cohort_size(min_cohort_size: int) -> int:
    """Return ``min_cohort_size``; ``ValueError`` when it is below the floor."""
    if min_cohort_size < MIN_COHORT_SIZE_FLOOR:
        raise ValueError(
            "percentile minimum cohort size must be at least "
            f"{MIN_COHORT_SIZE_FLOOR}, got {min_cohort_size!r}"
        )
    return min_cohort_size


def cohort_percentile(
    at_or_below: int,
    cohort_size: int,
    min_cohort_size: int,
) -> Optional[float]:
    """Percentile of one cohort member, or ``None`` below the minimum size.

    ``at_or_below`` counts the cohort members priced at or below this one,
    itself included, so it lies in ``1..cohort_size``. Counts outside that
    range are a caller bug and raise ``ValueError``, whatever the cohort size.
    """
    validate_min_cohort_size(min_cohort_size)
    if cohort_size < 1:
        raise ValueError(f"cohort size must be at least 1, got {cohort_size!r}")
    if not 1 <= at_or_below <= cohort_size:
        raise ValueError(
            f"at-or-below count {at_or_below!r} is outside 1..{cohort_size!r}"
        )
    if cohort_size < min_cohort_size:
        return None
    return at_or_below / cohort_size


def cohort_percentiles(
    values: Sequence[float],
    min_cohort_size: int,
) -> list[Optional[float]]:
    """Whole-cohort reference: the percentile of every member, in input order.

    ``values`` are the price/m² of all members of one cohort. This is the
    definition the SQL counts are checked against.
    """
    validate_min_cohort_size(min_cohort_size)
    ordered = sorted(values)
    size = len(ordered)
    return [
        cohort_percentile(bisect_right(ordered, value), size, min_cohort_size)
        for value in values
    ]
