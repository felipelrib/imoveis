"""Scoring engine — per-neighborhood statistics with dynamic weight recalculation.

Replaces the original global in-memory approach with:
- SQL window functions for per-neighbourhood stats (no OOM risk)
- Mean, median, stddev, z-score, percentile rank stored per property
- Rent and sale price/m² cohorts kept separate (BIN-84)
- The price a Listing contributes to a cohort comes from core.price_basis
  (Story 1.3): this module never selects a Listing price itself
- Cohort price/m² percentiles per listing type (Story 1.6): SQL counts the
  city x neighbourhood x listing-type cohort, core.cohort_percentile divides
  and applies the minimum cohort size; this module is their only writer
- Single-query bulk recalculation when weights change (instantaneous)
- score_single_property() for post-AI-enrichment updates
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from adapters.db.models import MetricsScoring, Neighborhood, Property, PropertyListing
from core.cohort_percentile import (
    COHORT_CITY_SQL,
    COHORT_NEIGHBOURHOOD_SQL,
    cohort_percentile,
)
from core.entities import ScoringWeights
from core.neighbourhood_quality import aggregate_neighbourhood_score
from core.price_basis import (
    COHORT_PRICE_FOR_TYPE_SQL,
    COHORT_PRICE_SQL,
    PRICE_BASIS_HEADLINE_SQL,
    CohortPrice,
    property_cohort_prices,
    row_price_basis,
)
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

# Cohort identity: spatial neighbourhood name wins over props_json string.
# Used by bulk stats SQL and single-property scoring so preference cannot drift.
_COHORT_KEY_SQL = "COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')"
_COHORT_KEY_SQL_P2 = "COALESCE(n2.name, p2.props_json->>'neighborhood', 'Unknown')"

# --- Cohort percentile SQL (Story 1.6) ---------------------------------------
# Fixed module constants built from core.cohort_percentile / core.price_basis
# by plain concatenation (BIN-135). Aliases: p = properties, n = neighborhoods,
# lm = the COHORT_PRICE_SQL relation. The stat cohort key above is not used:
# the percentile cohort is listing type x city x neighbourhood.
_PCT_PARTITION_SQL = (
    "lm.listing_type, " + COHORT_CITY_SQL + ", " + COHORT_NEIGHBOURHOOD_SQL
)
# The price/m² a member is ranked on: the Story 1.3 cohort price over the area.
_PCT_PRICE_PER_M2_SQL = "lm.price / NULLIF(p.area_m2, 0)"
# Cohort members: active, with an area, an assigned neighbourhood and a row in
# the cohort price relation. ``_PCT_MEMBERS_FROM_CTE_SQL`` reads the bulk
# statement's ``listing_min`` CTE; ``_PCT_MEMBERS_FROM_SQL`` inlines the
# relation so a filter on one Property is pushed into it.
_PCT_MEMBERS_JOIN_WHERE_SQL = (
    """ lm ON lm.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.active = true
              AND p.area_m2 > 0
              AND """
    + COHORT_NEIGHBOURHOOD_SQL
    + " IS NOT NULL"
)
_PCT_MEMBERS_FROM_CTE_SQL = (
    """
            FROM properties p
            JOIN listing_min"""
    + _PCT_MEMBERS_JOIN_WHERE_SQL
)
_PCT_MEMBERS_FROM_SQL = (
    """
            FROM properties p
            JOIN ("""
    + COHORT_PRICE_SQL
    + ")"
    + _PCT_MEMBERS_JOIN_WHERE_SQL
)

# SQL expression: mean of available neighbourhood quality scores, else 0.5.
_NHOOD_SCORE_SQL = """
COALESCE(
    (
        SELECT AVG(v)
        FROM (VALUES
            (n.amenity_score),
            (n.transit_score),
            (n.access_score),
            (n.safety_score)
        ) AS t(v)
        WHERE v IS NOT NULL
    ),
    0.5
)
"""


def primary_listing_type_for_ppm(
    price_per_m2_rent: Optional[float],
    price_per_m2_sale: Optional[float],
) -> Optional[str]:
    """Rent preferred when both exist (matches decisioning / primary listing)."""
    if price_per_m2_rent is not None:
        return "rent"
    if price_per_m2_sale is not None:
        return "sale"
    return None


def _sigmoid_undervalued(z_score: float) -> float:
    """Map z-score to 0..1 stat_score.

    Negative z = cheaper than neighbourhood average = HIGHER score (undervalued).
    We negate z so lower prices produce higher scores.
    """
    return 1.0 / (1.0 + math.exp(z_score))


def _stat_analysis(z_score: float) -> dict:
    """Return a locale-stable stat band code (BIN-101).

    Display labels/reasoning live in the SPA catalog; reasoning is empty on
    new writes so operators are not stuck with English prose after a locale flip.
    """
    bands = (
        (-1.0, "highly_undervalued"),
        (-0.2, "slightly_undervalued"),
        (0.2, "average"),
        (1.0, "slightly_overvalued"),
    )
    for threshold, category in bands:
        if z_score < threshold:
            return {"category": category, "reasoning": ""}
    return {"category": "highly_overvalued", "reasoning": ""}


def _scoring_weights() -> ScoringWeights:
    cfg = get_config()
    return ScoringWeights(
        stat_weight=cfg.scoring.stat_weight,
        ai_weight=cfg.scoring.ai_weight,
        neighbourhood_weight=cfg.scoring.neighbourhood_weight,
    )


def blend_combined_score(
    stat_score: float,
    ai_score: float,
    neighbourhood_score: float,
    weights: ScoringWeights,
) -> float:
    """Blend stat / AI / neighbourhood into combined_score."""
    return (
        float(stat_score) * weights.stat_weight
        + float(ai_score or 0.0) * weights.ai_weight
        + float(neighbourhood_score) * weights.neighbourhood_weight
    )


def _neighbourhood_score(nhood: Optional[Neighborhood]) -> float:
    """Aggregate a (possibly missing) neighbourhood's quality scores (neutral 0.5)."""
    if nhood is None:
        return aggregate_neighbourhood_score({})
    return aggregate_neighbourhood_score(
        {
            "amenity_score": nhood.amenity_score,
            "transit_score": nhood.transit_score,
            "access_score": nhood.access_score,
            "safety_score": nhood.safety_score,
        }
    )


def _neighbourhood_score_for_property(session: Session, prop: Property) -> float:
    """Load linked neighbourhood quality aggregate (neutral 0.5 when missing)."""
    if not prop.neighborhood_id:
        return _neighbourhood_score(None)
    nhood = session.get(Neighborhood, prop.neighborhood_id)
    return _neighbourhood_score(nhood)


def _compute_type_scores(
    *,
    ppm: Optional[float],
    mean: Optional[float],
    stddev: Optional[float],
    pct_rank: Optional[float],
    ai_score: float,
    weights: ScoringWeights,
    neighbourhood_score: float = 0.5,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (stat_score, z_score, percentile_rank, combined_score) for one type."""
    if ppm is None:
        return None, None, None, None
    z = (
        (ppm - mean) / stddev
        if mean is not None and stddev and stddev > 0
        else 0.0
    )
    z = float(z)
    stat_score = _sigmoid_undervalued(z)
    pct = pct_rank if pct_rank is not None else 0.5
    combined = blend_combined_score(stat_score, ai_score, neighbourhood_score, weights)
    return stat_score, z, pct, combined


def _update_metrics_score(
    ms, stat_score, price_per_m2, stats, z_score, weights, stat_analysis, neighbourhood_score=0.5
) -> None:
    ms.stat_score, ms.price_per_m2 = stat_score, price_per_m2
    ms.neighborhood_mean, ms.neighborhood_median, ms.z_score = stats["mean"], stats["median"], z_score
    ms.combined_score = blend_combined_score(
        stat_score, float(ms.ai_score or 0.0), neighbourhood_score, weights
    )
    meta = dict(ms.meta or {})
    meta["stat_analysis"] = stat_analysis
    ms.meta = meta


def _apply_type_fields(
    ms: MetricsScoring,
    *,
    price_basis: str,
    price_per_m2_rent: Optional[float],
    price_per_m2_sale: Optional[float],
    neighborhood_mean_rent: Optional[float],
    neighborhood_mean_sale: Optional[float],
    neighborhood_median_rent: Optional[float],
    neighborhood_median_sale: Optional[float],
    stat_score_rent: Optional[float] = None,
    stat_score_sale: Optional[float] = None,
    z_score_rent: Optional[float] = None,
    z_score_sale: Optional[float] = None,
    percentile_rank_rent: Optional[float] = None,
    percentile_rank_sale: Optional[float] = None,
    combined_score_rent: Optional[float] = None,
    combined_score_sale: Optional[float] = None,
) -> None:
    ms.price_basis = price_basis
    ms.price_per_m2_rent = price_per_m2_rent
    ms.price_per_m2_sale = price_per_m2_sale
    ms.neighborhood_mean_rent = neighborhood_mean_rent
    ms.neighborhood_mean_sale = neighborhood_mean_sale
    ms.neighborhood_median_rent = neighborhood_median_rent
    ms.neighborhood_median_sale = neighborhood_median_sale
    ms.stat_score_rent = stat_score_rent
    ms.stat_score_sale = stat_score_sale
    ms.z_score_rent = z_score_rent
    ms.z_score_sale = z_score_sale
    ms.percentile_rank_rent = percentile_rank_rent
    ms.percentile_rank_sale = percentile_rank_sale
    ms.combined_score_rent = combined_score_rent
    ms.combined_score_sale = combined_score_sale


def _utcnow() -> datetime:
    """Naive UTC, like the ``now()`` server defaults of the DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _percentile_min_cohort_size() -> int:
    return get_config().scoring.percentile_min_cohort_size


def _apply_percentile_fields(
    ms: MetricsScoring,
    counts: Mapping[str, tuple[int, int]],
    *,
    min_cohort_size: int,
    evaluated_at: datetime,
) -> None:
    """Write the cohort percentile columns of one evaluated row (Story 1.6).

    ``counts`` is ``{listing_type: (at_or_below, cohort_size)}`` for the types
    in which the Property is a cohort member. A missing type clears both of
    its columns; a cohort below the minimum keeps its size and has no
    percentile. The row is stamped either way.
    """
    values: dict[str, tuple[Optional[float], Optional[int]]] = {}
    for listing_type in ("rent", "sale"):
        pair = counts.get(listing_type)
        if pair is None:
            values[listing_type] = (None, None)
            continue
        at_or_below, cohort_size = pair
        values[listing_type] = (
            cohort_percentile(at_or_below, cohort_size, min_cohort_size),
            cohort_size,
        )
    ms.price_per_m2_percentile_rent, ms.percentile_cohort_size_rent = values["rent"]
    ms.price_per_m2_percentile_sale, ms.percentile_cohort_size_sale = values["sale"]
    ms.percentile_evaluated_at = evaluated_at


def _row_percentile_counts(
    size_rent, at_or_below_rent, size_sale, at_or_below_sale
) -> dict[str, tuple[int, int]]:
    """Counts of one bulk row as ``{listing_type: (at_or_below, cohort_size)}``."""
    counts: dict[str, tuple[int, int]] = {}
    if size_rent is not None:
        counts["rent"] = (int(at_or_below_rent), int(size_rent))
    if size_sale is not None:
        counts["sale"] = (int(at_or_below_sale), int(size_sale))
    return counts


def _clear_percentiles_of_non_members(session: Session, evaluated_at: datetime) -> int:
    """Null the percentile and cohort size of rows whose Property left every cohort.

    Run after a full bulk recalculation: rows the stage processed are already
    correct, so this only reaches rows it did not return (inactive Property,
    no area, no active priced Listing). One set-based statement.
    """
    result = session.execute(
        text(
            """
            UPDATE metrics_scoring AS ms
            SET price_per_m2_percentile_rent = NULL,
                price_per_m2_percentile_sale = NULL,
                percentile_cohort_size_rent = NULL,
                percentile_cohort_size_sale = NULL,
                percentile_evaluated_at = :evaluated_at,
                updated_at = NOW()
            WHERE (
                    ms.price_per_m2_percentile_rent IS NOT NULL
                    OR ms.price_per_m2_percentile_sale IS NOT NULL
                    OR ms.percentile_cohort_size_rent IS NOT NULL
                    OR ms.percentile_cohort_size_sale IS NOT NULL
                  )
              AND NOT EXISTS (
                  SELECT 1"""
            + _PCT_MEMBERS_FROM_SQL
            + """
                    AND p.id = ms.property_id
              )
            """
        ),
        {"evaluated_at": evaluated_at},
    )
    return int(result.rowcount or 0)


def _single_property_percentile_counts(
    session: Session, property_id
) -> dict[str, tuple[int, int]]:
    """``{listing_type: (at_or_below, cohort_size)}`` for one Property.

    Two statements: the Property's own cohort key and price/m² per type (empty
    when it is not a cohort member), then the counts of the *other* members of
    that cohort with those values bound. The Property itself is added here, so
    the pair is consistent (1 <= at_or_below <= cohort_size) even when its
    Listing changes between the two statements. Same expressions as the bulk
    statement, so both writers agree on the same rows.
    """
    own = session.execute(
        text(
            "SELECT lm.listing_type, "
            + COHORT_CITY_SQL
            + " AS cohort_city, "
            + COHORT_NEIGHBOURHOOD_SQL
            + " AS cohort_neighbourhood, "
            + _PCT_PRICE_PER_M2_SQL
            + " AS price_per_m2"
            + _PCT_MEMBERS_FROM_SQL
            + """
              AND p.id = :pid"""
        ),
        {"pid": property_id},
    ).fetchall()
    if not own:
        return {}
    own_ppm = {row[0]: float(row[3]) for row in own}

    rows = session.execute(
        text(
            "SELECT lm.listing_type, COUNT(*) AS cohort_size, COUNT(*) FILTER (WHERE "
            + _PCT_PRICE_PER_M2_SQL
            + """ <= CASE lm.listing_type
                    WHEN 'rent' THEN CAST(:ppm_rent AS double precision)
                    ELSE CAST(:ppm_sale AS double precision)
                END) AS at_or_below"""
            + _PCT_MEMBERS_FROM_SQL
            + """
              AND p.id <> :pid
              AND """
            + COHORT_CITY_SQL
            + """ = :cohort_city
              AND """
            + COHORT_NEIGHBOURHOOD_SQL
            + """ = :cohort_neighbourhood
            GROUP BY lm.listing_type"""
        ),
        {
            "ppm_rent": own_ppm.get("rent"),
            "ppm_sale": own_ppm.get("sale"),
            "pid": property_id,
            "cohort_city": own[0][1],
            "cohort_neighbourhood": own[0][2],
        },
    ).fetchall()
    others = {row[0]: (int(row[2]), int(row[1])) for row in rows}
    counts: dict[str, tuple[int, int]] = {}
    for listing_type in own_ppm:
        others_at_or_below, others_size = others.get(listing_type, (0, 0))
        counts[listing_type] = (others_at_or_below + 1, others_size + 1)
    return counts


def compute_neighborhood_stats(
    session: Session,
    neighborhood_key: Optional[str] = None,
) -> int:
    """Compute per-neighbourhood price statistics using SQL window functions.

    Rent and sale $/m² are cohorted separately from active property_listings
    (BIN-84). Legacy columns use the primary listing type (rent preferred).
    Listing prices come from core.price_basis (Story 1.3); each row is stamped
    with the basis of its rent price/m².

    The same statement counts each cohort member's city x neighbourhood x
    listing-type cohort (Story 1.6). Those counts are never restricted by
    ``neighborhood_key``: a restricted run still ranks against whole cohorts.
    A full run also clears the percentiles of rows whose Property is no longer
    a cohort member.

    Args:
        session: Active SQLAlchemy session.
        neighborhood_key: If provided, only recompute for that neighbourhood key.

    Returns:
        Number of property rows processed.
    """
    weights = _scoring_weights()
    min_cohort_size = _percentile_min_cohort_size()
    evaluated_at = _utcnow()

    # where_clause/_COHORT_KEY_SQL/COHORT_PRICE_SQL are fixed module constants
    # (never user-supplied text); :nkey is a bound parameter. Assembled via
    # plain concatenation (not an f-string) per BIN-135.
    where_clause = (
        ("AND " + _COHORT_KEY_SQL + " = :nkey")
        if neighborhood_key is not None
        else ""
    )

    sql = text(
        """
        WITH listing_min AS ("""
        + COHORT_PRICE_SQL
        + """        ),
        has_listing AS (
            SELECT DISTINCT property_id FROM listing_min
        ),
        typed AS (
            SELECT
                p.id AS property_id,
                """
        + _COHORT_KEY_SQL
        + """ AS n_key,
                lm.listing_type,
                lm.price / NULLIF(p.area_m2, 0) AS price_per_m2,
                lm.price_basis
            FROM properties p
            JOIN listing_min lm ON lm.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.area_m2 IS NOT NULL
              AND p.area_m2 > 0
              AND p.active = true
              """
        + where_clause
        + """
            UNION ALL
            SELECT
                p.id AS property_id,
                """
        + _COHORT_KEY_SQL
        + """ AS n_key,
                CASE
                    WHEN COALESCE((p.props_json->>'available_for_rent')::boolean, false)
                        THEN 'rent'
                    WHEN COALESCE((p.props_json->>'available_for_sale')::boolean, false)
                        THEN 'sale'
                    ELSE 'rent'
                END AS listing_type,
                p.price / NULLIF(p.area_m2, 0) AS price_per_m2,
                """
        + PRICE_BASIS_HEADLINE_SQL
        + """ AS price_basis
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.area_m2 IS NOT NULL
              AND p.area_m2 > 0
              AND p.active = true
              AND p.price > 0
              AND NOT EXISTS (
                  SELECT 1 FROM has_listing hl WHERE hl.property_id = p.id
              )
              """
        + where_clause
        + """
        ),
        medians AS (
            -- One median per stat cohort, joined back. A subquery per row
            -- over ``typed`` returned the same values and took the stage
            -- from seconds to an hour on about 240,000 rows.
            SELECT
                n_key,
                listing_type,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2)
                    AS neighborhood_median
            FROM typed
            GROUP BY n_key, listing_type
        ),
        stats AS (
            SELECT
                t.property_id,
                t.n_key,
                t.listing_type,
                t.price_per_m2,
                t.price_basis,
                AVG(t.price_per_m2)
                    OVER (PARTITION BY t.n_key, t.listing_type) AS neighborhood_mean,
                md.neighborhood_median,
                STDDEV(t.price_per_m2)
                    OVER (PARTITION BY t.n_key, t.listing_type) AS neighborhood_stddev,
                PERCENT_RANK()
                    OVER (
                        PARTITION BY t.n_key, t.listing_type
                        ORDER BY t.price_per_m2
                    ) AS percentile_rank
            FROM typed t
            JOIN medians md
              ON md.n_key = t.n_key AND md.listing_type = t.listing_type
        ),
        pivoted AS (
            SELECT
                property_id,
                MAX(price_per_m2) FILTER (WHERE listing_type = 'rent') AS price_per_m2_rent,
                MAX(price_per_m2) FILTER (WHERE listing_type = 'sale') AS price_per_m2_sale,
                MAX(neighborhood_mean) FILTER (WHERE listing_type = 'rent')
                    AS neighborhood_mean_rent,
                MAX(neighborhood_mean) FILTER (WHERE listing_type = 'sale')
                    AS neighborhood_mean_sale,
                MAX(neighborhood_median) FILTER (WHERE listing_type = 'rent')
                    AS neighborhood_median_rent,
                MAX(neighborhood_median) FILTER (WHERE listing_type = 'sale')
                    AS neighborhood_median_sale,
                MAX(neighborhood_stddev) FILTER (WHERE listing_type = 'rent')
                    AS neighborhood_stddev_rent,
                MAX(neighborhood_stddev) FILTER (WHERE listing_type = 'sale')
                    AS neighborhood_stddev_sale,
                MAX(percentile_rank) FILTER (WHERE listing_type = 'rent')
                    AS percentile_rank_rent,
                MAX(percentile_rank) FILTER (WHERE listing_type = 'sale')
                    AS percentile_rank_sale,
                MAX(price_basis) FILTER (WHERE listing_type = 'rent')
                    AS price_basis_rent
            FROM stats
            GROUP BY property_id
        ),
        pct_members AS (
            SELECT
                p.id AS property_id,
                lm.listing_type,
                COUNT(*) OVER (PARTITION BY """
        + _PCT_PARTITION_SQL
        + """) AS cohort_size,
                COUNT(*) OVER (
                    PARTITION BY """
        + _PCT_PARTITION_SQL
        + """
                    ORDER BY """
        + _PCT_PRICE_PER_M2_SQL
        + """
                ) AS at_or_below"""
        + _PCT_MEMBERS_FROM_CTE_SQL
        + """
        ),
        pct_pivoted AS (
            SELECT
                property_id,
                MAX(cohort_size) FILTER (WHERE listing_type = 'rent') AS pct_cohort_size_rent,
                MAX(at_or_below) FILTER (WHERE listing_type = 'rent') AS pct_at_or_below_rent,
                MAX(cohort_size) FILTER (WHERE listing_type = 'sale') AS pct_cohort_size_sale,
                MAX(at_or_below) FILTER (WHERE listing_type = 'sale') AS pct_at_or_below_sale
            FROM pct_members
            GROUP BY property_id
        )
        SELECT
            pivoted.property_id,
            price_per_m2_rent,
            price_per_m2_sale,
            neighborhood_mean_rent,
            neighborhood_mean_sale,
            neighborhood_median_rent,
            neighborhood_median_sale,
            neighborhood_stddev_rent,
            neighborhood_stddev_sale,
            percentile_rank_rent,
            percentile_rank_sale,
            price_basis_rent,
            pp.pct_cohort_size_rent,
            pp.pct_at_or_below_rent,
            pp.pct_cohort_size_sale,
            pp.pct_at_or_below_sale
        FROM pivoted
        LEFT JOIN pct_pivoted pp ON pp.property_id = pivoted.property_id
        """
    )

    params: dict = {}
    if neighborhood_key is not None:
        params["nkey"] = str(neighborhood_key)

    rows = session.execute(sql, params).fetchall()
    count = len(rows)

    # Batch-load MetricsScoring/Property/Neighborhood once for every property
    # in this recalculation instead of one round trip per row (BIN-151).
    prop_ids = [row[0] for row in rows]
    ms_by_property: dict = {}
    props_by_id: dict = {}
    neighborhoods_by_id: dict = {}
    if prop_ids:
        ms_by_property = {
            ms.property_id: ms
            for ms in session.query(MetricsScoring)
            .filter(MetricsScoring.property_id.in_(prop_ids))
            .all()
        }
        props_by_id = {
            p.id: p
            for p in session.query(Property).filter(Property.id.in_(prop_ids)).all()
        }
        neighborhood_ids = {
            p.neighborhood_id for p in props_by_id.values() if p.neighborhood_id
        }
        if neighborhood_ids:
            neighborhoods_by_id = {
                n.id: n
                for n in session.query(Neighborhood)
                .filter(Neighborhood.id.in_(neighborhood_ids))
                .all()
            }

    for row in rows:
        prop_id = row[0]
        ppm_rent = float(row[1]) if row[1] is not None else None
        ppm_sale = float(row[2]) if row[2] is not None else None
        mean_rent = float(row[3]) if row[3] is not None else None
        mean_sale = float(row[4]) if row[4] is not None else None
        median_rent = float(row[5]) if row[5] is not None else None
        median_sale = float(row[6]) if row[6] is not None else None
        std_rent = float(row[7]) if row[7] is not None else None
        std_sale = float(row[8]) if row[8] is not None else None
        pct_rent = float(row[9]) if row[9] is not None else None
        pct_sale = float(row[10]) if row[10] is not None else None
        price_basis = row_price_basis(row[11])
        percentile_counts = _row_percentile_counts(row[12], row[13], row[14], row[15])

        primary = primary_listing_type_for_ppm(ppm_rent, ppm_sale)
        if primary is None:
            continue

        ai = 0.0
        ms = ms_by_property.get(prop_id)
        if ms is not None:
            ai = float(ms.ai_score or 0.0)

        prop = props_by_id.get(prop_id)
        nhood = (
            neighborhoods_by_id.get(prop.neighborhood_id)
            if prop is not None and prop.neighborhood_id
            else None
        )
        nhood_score = _neighbourhood_score(nhood)

        stat_rent, z_rent, pct_rent_out, combined_rent = _compute_type_scores(
            ppm=ppm_rent,
            mean=mean_rent,
            stddev=std_rent,
            pct_rank=pct_rent,
            ai_score=ai,
            weights=weights,
            neighbourhood_score=nhood_score,
        )
        stat_sale, z_sale, pct_sale_out, combined_sale = _compute_type_scores(
            ppm=ppm_sale,
            mean=mean_sale,
            stddev=std_sale,
            pct_rank=pct_sale,
            ai_score=ai,
            weights=weights,
            neighbourhood_score=nhood_score,
        )

        if primary == "rent":
            price_per_m2, n_mean, n_median = ppm_rent, mean_rent, median_rent
            stat_score, z, pct_rank = stat_rent, z_rent, pct_rent_out
        else:
            price_per_m2, n_mean, n_median = ppm_sale, mean_sale, median_sale
            stat_score, z, pct_rank = stat_sale, z_sale, pct_sale_out

        assert stat_score is not None and z is not None and pct_rank is not None
        combined_score = blend_combined_score(stat_score, ai, nhood_score, weights)
        stat_analysis = _stat_analysis(z)

        if ms is None:
            ms = MetricsScoring(
                property_id=prop_id,
                stat_score=stat_score,
                ai_score=ai,
                combined_score=combined_score,
                price_per_m2=price_per_m2,
                neighborhood_mean=n_mean,
                neighborhood_median=n_median,
                z_score=z,
                percentile_rank=pct_rank,
                meta={"stat_analysis": stat_analysis},
            )
            session.add(ms)
        else:
            ms.stat_score = stat_score
            ms.price_per_m2 = price_per_m2
            ms.neighborhood_mean = n_mean
            ms.neighborhood_median = n_median
            ms.z_score = z
            ms.percentile_rank = pct_rank
            ms.combined_score = combined_score
            meta = dict(ms.meta or {})
            meta["stat_analysis"] = stat_analysis
            ms.meta = meta

        _apply_type_fields(
            ms,
            price_basis=price_basis,
            price_per_m2_rent=ppm_rent,
            price_per_m2_sale=ppm_sale,
            neighborhood_mean_rent=mean_rent,
            neighborhood_mean_sale=mean_sale,
            neighborhood_median_rent=median_rent,
            neighborhood_median_sale=median_sale,
            stat_score_rent=stat_rent,
            stat_score_sale=stat_sale,
            z_score_rent=z_rent,
            z_score_sale=z_sale,
            percentile_rank_rent=pct_rent_out,
            percentile_rank_sale=pct_sale_out,
            combined_score_rent=combined_rent,
            combined_score_sale=combined_sale,
        )
        _apply_percentile_fields(
            ms,
            percentile_counts,
            min_cohort_size=min_cohort_size,
            evaluated_at=evaluated_at,
        )

    session.flush()
    percentiles_cleared = 0
    if neighborhood_key is None:
        percentiles_cleared = _clear_percentiles_of_non_members(session, evaluated_at)
    logger.info(
        "neighborhood_stats_computed",
        rows=count,
        percentiles_cleared=percentiles_cleared,
        neighborhood_key=str(neighborhood_key) if neighborhood_key else "all",
    )
    return count


def recalculate_all_combined_scores(
    session: Session,
    weights: Optional[ScoringWeights] = None,
) -> int:
    """Instantly bulk-update combined_score for the entire table using a single SQL UPDATE.

    Joins live neighbourhood quality scores so geo profile updates do not need AI.
    This is O(1) in application memory regardless of table size.

    Args:
        session: Active SQLAlchemy session.
        weights: Weight config.  Defaults to values in app_config.yaml.

    Returns:
        Number of rows updated.
    """
    if weights is None:
        weights = _scoring_weights()

    # _NHOOD_SCORE_SQL is a fixed module constant (never user-supplied text).
    # Assembled via plain concatenation (not an f-string) per BIN-135.
    result = session.execute(
        text(
            """
            UPDATE metrics_scoring AS ms
            SET combined_score =
                    COALESCE(ms.stat_score, 0) * :w_stat
                    + COALESCE(ms.ai_score, 0) * :w_ai
                    + ("""
            + _NHOOD_SCORE_SQL
            + """) * :w_nhood,
                combined_score_rent = CASE
                    WHEN ms.stat_score_rent IS NOT NULL THEN
                        COALESCE(ms.stat_score_rent, 0) * :w_stat
                        + COALESCE(ms.ai_score, 0) * :w_ai
                        + ("""
            + _NHOOD_SCORE_SQL
            + """) * :w_nhood
                    ELSE NULL
                END,
                combined_score_sale = CASE
                    WHEN ms.stat_score_sale IS NOT NULL THEN
                        COALESCE(ms.stat_score_sale, 0) * :w_stat
                        + COALESCE(ms.ai_score, 0) * :w_ai
                        + ("""
            + _NHOOD_SCORE_SQL
            + """) * :w_nhood
                    ELSE NULL
                END,
                updated_at = NOW()
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE ms.property_id = p.id
            """
        ),
        {
            "w_stat": weights.stat_weight,
            "w_ai": weights.ai_weight,
            "w_nhood": weights.neighbourhood_weight,
        },
    )
    count = result.rowcount
    session.flush()
    logger.info(
        "bulk_scores_recalculated",
        rows=count,
        stat_weight=weights.stat_weight,
        ai_weight=weights.ai_weight,
        neighbourhood_weight=weights.neighbourhood_weight,
    )
    return count


def get_neighborhood_stats_cached(
    session: Session,
    n_key: str,
    listing_type: str = "rent",
) -> dict:
    """Return mean/median/stddev for one neighbourhood × listing_type cohort."""
    import json

    from infra.redis_client import get_redis
    r = get_redis()
    cache_key = f"n_stats:{n_key}:{listing_type}"
    cached = r.get(cache_key)
    if cached:
        return json.loads(cached)

    # _COHORT_KEY_SQL/COHORT_PRICE_FOR_TYPE_SQL are fixed module constants
    # (never user-supplied text); :nkey/:lt are bound parameters. Assembled
    # via plain concatenation (not an f-string) per BIN-135.
    sql = text(
        """
        WITH listing_min AS ("""
        + COHORT_PRICE_FOR_TYPE_SQL
        + """        ),
        typed AS (
            SELECT
                lm.price / NULLIF(p.area_m2, 0) AS price_per_m2
            FROM properties p
            JOIN listing_min lm ON lm.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.area_m2 > 0 AND p.active = true
              AND """
        + _COHORT_KEY_SQL
        + """ = :nkey
            UNION ALL
            SELECT
                p.price / NULLIF(p.area_m2, 0) AS price_per_m2
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.area_m2 > 0 AND p.active = true AND p.price > 0
              AND """
        + _COHORT_KEY_SQL
        + """ = :nkey
              AND NOT EXISTS (
                  SELECT 1 FROM property_listings pl
                  WHERE pl.property_id = p.id AND pl.active = true
              )
              AND (
                  (:lt = 'rent' AND (
                      COALESCE((p.props_json->>'available_for_rent')::boolean, false)
                      OR NOT COALESCE((p.props_json->>'available_for_sale')::boolean, false)
                  ))
                  OR
                  (:lt = 'sale' AND COALESCE((p.props_json->>'available_for_sale')::boolean, false)
                      AND NOT COALESCE((p.props_json->>'available_for_rent')::boolean, false))
              )
        )
        SELECT
            AVG(price_per_m2) AS mean,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2) AS median,
            STDDEV(price_per_m2) AS stddev,
            COUNT(*) AS count
        FROM typed
        WHERE price_per_m2 IS NOT NULL
    """
    )
    row = session.execute(sql, {"nkey": n_key, "lt": listing_type}).mappings().fetchone()
    stats = {
        "mean": float(row["mean"]) if row and row["mean"] else 0.0,
        "median": float(row["median"]) if row and row["median"] else 0.0,
        "stddev": float(row["stddev"]) if row and row["stddev"] else 0.0,
        "count": int(row["count"]) if row and row["count"] else 0,
    }
    r.setex(cache_key, 60, json.dumps(stats))
    return stats


def _listing_cohort_prices(session: Session, property_id) -> dict[str, CohortPrice]:
    """Return {listing_type: CohortPrice} for a property's Listings.

    Loads the raw columns only; which Listings count and which price each one
    contributes is decided by core.price_basis (the mirror of the SQL the bulk
    path runs).
    """
    rows = (
        session.query(
            PropertyListing.listing_type,
            PropertyListing.price,
            PropertyListing.rent_monthly,
            PropertyListing.active,
        )
        .filter(PropertyListing.property_id == property_id)
        .all()
    )
    return property_cohort_prices(row._mapping for row in rows)


def score_single_property(session: Session, property_id: str) -> None:
    """Recompute combined_score for a single property after AI enrichment.

    Fetches neighbourhood context from existing MetricsScoring peers, then
    recomputes the z-score relative to them and updates the single row.

    Args:
        session: Active SQLAlchemy session.
        property_id: UUID string of the property to score.
    """
    prop = session.get(Property, property_id)
    if prop is None:
        logger.warning("score_single_property_not_found", property_id=property_id)
        return

    n_key = _property_neighborhood_key(session, prop)
    listing_prices = _listing_cohort_prices(session, prop.id)

    ppm_rent = None
    ppm_sale = None
    rent_basis = None  # set only when a Listing supplies the rent price
    if prop.area_m2 and prop.area_m2 > 0:
        if "rent" in listing_prices:
            ppm_rent = listing_prices["rent"].price / prop.area_m2
            rent_basis = listing_prices["rent"].price_basis
        if "sale" in listing_prices:
            ppm_sale = listing_prices["sale"].price / prop.area_m2
        if ppm_rent is None and ppm_sale is None and prop.price and prop.price > 0:
            # Legacy row with no listings — treat like decisioning (rent preferred).
            props = prop.props_json or {}
            if props.get("available_for_sale") and not props.get("available_for_rent"):
                ppm_sale = prop.price / prop.area_m2
            else:
                ppm_rent = prop.price / prop.area_m2

    primary = primary_listing_type_for_ppm(ppm_rent, ppm_sale)
    if primary is None:
        logger.warning("score_single_property_no_price", property_id=property_id)
        # Not a cohort member: an existing row must not keep a percentile.
        stale = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
        if stale is not None:
            _apply_percentile_fields(
                stale,
                {},
                min_cohort_size=_percentile_min_cohort_size(),
                evaluated_at=_utcnow(),
            )
            session.flush()
        return

    price_per_m2 = ppm_rent if primary == "rent" else ppm_sale
    assert price_per_m2 is not None

    rent_stats = get_neighborhood_stats_cached(session, n_key, listing_type="rent") if ppm_rent is not None else None
    sale_stats = get_neighborhood_stats_cached(session, n_key, listing_type="sale") if ppm_sale is not None else None

    weights = _scoring_weights()
    ai = 0.0
    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
    if ms is not None:
        ai = float(ms.ai_score or 0.0)

    nhood_score = _neighbourhood_score_for_property(session, prop)

    mean_rent = rent_stats["mean"] if rent_stats and rent_stats["count"] else None
    median_rent = rent_stats["median"] if rent_stats and rent_stats["count"] else None
    std_rent = rent_stats["stddev"] if rent_stats and rent_stats["count"] else None
    mean_sale = sale_stats["mean"] if sale_stats and sale_stats["count"] else None
    median_sale = sale_stats["median"] if sale_stats and sale_stats["count"] else None
    std_sale = sale_stats["stddev"] if sale_stats and sale_stats["count"] else None

    stat_rent, z_rent, pct_rent, combined_rent = _compute_type_scores(
        ppm=ppm_rent,
        mean=mean_rent,
        stddev=std_rent,
        pct_rank=0.5,
        ai_score=ai,
        weights=weights,
        neighbourhood_score=nhood_score,
    )
    stat_sale, z_sale, pct_sale, combined_sale = _compute_type_scores(
        ppm=ppm_sale,
        mean=mean_sale,
        stddev=std_sale,
        pct_rank=0.5,
        ai_score=ai,
        weights=weights,
        neighbourhood_score=nhood_score,
    )

    if primary == "rent":
        stat_score, z, pct_rank = stat_rent, z_rent, pct_rent
        n_mean, n_median = mean_rent, median_rent
    else:
        stat_score, z, pct_rank = stat_sale, z_sale, pct_sale
        n_mean, n_median = mean_sale, median_sale

    assert stat_score is not None and z is not None
    stat_analysis = _stat_analysis(z)
    combined_score = blend_combined_score(stat_score, ai, nhood_score, weights)

    if ms is None:
        ms = MetricsScoring(
            property_id=property_id,
            stat_score=stat_score,
            ai_score=ai,
            combined_score=combined_score,
            price_per_m2=price_per_m2,
            neighborhood_mean=n_mean,
            neighborhood_median=n_median,
            z_score=z,
            percentile_rank=pct_rank if pct_rank is not None else 0.5,
            meta={"stat_analysis": stat_analysis},
        )
        session.add(ms)
    else:
        _update_metrics_score(
            ms,
            stat_score,
            price_per_m2,
            {"mean": n_mean, "median": n_median},
            z,
            weights,
            stat_analysis,
            neighbourhood_score=nhood_score,
        )

    _apply_type_fields(
        ms,
        price_basis=row_price_basis(rent_basis),
        price_per_m2_rent=ppm_rent,
        price_per_m2_sale=ppm_sale,
        neighborhood_mean_rent=mean_rent if ppm_rent is not None else None,
        neighborhood_mean_sale=mean_sale if ppm_sale is not None else None,
        neighborhood_median_rent=median_rent if ppm_rent is not None else None,
        neighborhood_median_sale=median_sale if ppm_sale is not None else None,
        stat_score_rent=stat_rent,
        stat_score_sale=stat_sale,
        z_score_rent=z_rent,
        z_score_sale=z_sale,
        percentile_rank_rent=pct_rent,
        percentile_rank_sale=pct_sale,
        combined_score_rent=combined_rent,
        combined_score_sale=combined_sale,
    )
    _apply_percentile_fields(
        ms,
        _single_property_percentile_counts(session, prop.id),
        min_cohort_size=_percentile_min_cohort_size(),
        evaluated_at=_utcnow(),
    )

    session.flush()

    logger.info("single_property_scored", property_id=property_id)


def _property_neighborhood_key(session: Session, prop: Property) -> str:
    """Resolve cohort key: spatial FK name preferred over props_json string."""
    if prop.neighborhood_id:
        from adapters.db.models import Neighborhood

        neighborhood = session.get(Neighborhood, prop.neighborhood_id)
        if neighborhood is not None:
            return neighborhood.name
    return (prop.props_json or {}).get("neighborhood") or "Unknown"
