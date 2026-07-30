"""Scoring engine — per-neighborhood statistics with dynamic weight recalculation.

Replaces the original global in-memory approach with:
- SQL window functions for per-neighbourhood stats (no OOM risk)
- Mean, median, stddev, z-score, percentile rank stored per property
- Rent and sale price/m² cohorts kept separate (BIN-84)
- Single-query bulk recalculation when weights change (instantaneous)
- score_single_property() for post-AI-enrichment updates
"""

from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from adapters.db.models import MetricsScoring, Neighborhood, Property, PropertyListing
from core.entities import ScoringWeights
from core.neighbourhood_quality import aggregate_neighbourhood_score
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

# Cohort identity: spatial neighbourhood name wins over props_json string.
# Used by bulk stats SQL and single-property scoring so preference cannot drift.
_COHORT_KEY_SQL = "COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')"
_COHORT_KEY_SQL_P2 = "COALESCE(n2.name, p2.props_json->>'neighborhood', 'Unknown')"

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


def _neighbourhood_score_for_property(session: Session, prop: Property) -> float:
    """Load linked neighbourhood quality aggregate (neutral 0.5 when missing)."""
    if not prop.neighborhood_id:
        return aggregate_neighbourhood_score({})
    nhood = session.get(Neighborhood, prop.neighborhood_id)
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


def compute_neighborhood_stats(
    session: Session,
    neighborhood_key: Optional[str] = None,
) -> int:
    """Compute per-neighbourhood price statistics using SQL window functions.

    Rent and sale $/m² are cohorted separately from active property_listings
    (BIN-84). Legacy columns use the primary listing type (rent preferred).

    Args:
        session: Active SQLAlchemy session.
        neighborhood_key: If provided, only recompute for that neighbourhood key.

    Returns:
        Number of property rows processed.
    """
    weights = _scoring_weights()

    # where_clause/_COHORT_KEY_SQL are fixed module constants (never
    # user-supplied text); :nkey is a bound parameter. Assembled via plain
    # concatenation (not an f-string) per BIN-135.
    where_clause = (
        ("AND " + _COHORT_KEY_SQL + " = :nkey")
        if neighborhood_key is not None
        else ""
    )

    sql = text(
        """
        WITH listing_min AS (
            SELECT
                pl.property_id,
                pl.listing_type,
                MIN(pl.price) AS price
            FROM property_listings pl
            WHERE pl.active = true
              AND pl.price > 0
              AND pl.listing_type IN ('rent', 'sale')
            GROUP BY pl.property_id, pl.listing_type
        ),
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
                lm.price / NULLIF(p.area_m2, 0) AS price_per_m2
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
                p.price / NULLIF(p.area_m2, 0) AS price_per_m2
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
        stats AS (
            SELECT
                t.property_id,
                t.n_key,
                t.listing_type,
                t.price_per_m2,
                AVG(t.price_per_m2)
                    OVER (PARTITION BY t.n_key, t.listing_type) AS neighborhood_mean,
                (
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t2.price_per_m2)
                    FROM typed t2
                    WHERE t2.n_key = t.n_key AND t2.listing_type = t.listing_type
                ) AS neighborhood_median,
                STDDEV(t.price_per_m2)
                    OVER (PARTITION BY t.n_key, t.listing_type) AS neighborhood_stddev,
                PERCENT_RANK()
                    OVER (
                        PARTITION BY t.n_key, t.listing_type
                        ORDER BY t.price_per_m2
                    ) AS percentile_rank
            FROM typed t
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
                    AS percentile_rank_sale
            FROM stats
            GROUP BY property_id
        )
        SELECT
            property_id,
            price_per_m2_rent,
            price_per_m2_sale,
            neighborhood_mean_rent,
            neighborhood_mean_sale,
            neighborhood_median_rent,
            neighborhood_median_sale,
            neighborhood_stddev_rent,
            neighborhood_stddev_sale,
            percentile_rank_rent,
            percentile_rank_sale
        FROM pivoted
        """
    )

    params: dict = {}
    if neighborhood_key is not None:
        params["nkey"] = str(neighborhood_key)

    rows = session.execute(sql, params).fetchall()
    count = len(rows)

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

        primary = primary_listing_type_for_ppm(ppm_rent, ppm_sale)
        if primary is None:
            continue

        ai = 0.0
        ms = session.query(MetricsScoring).filter_by(property_id=prop_id).one_or_none()
        if ms is not None:
            ai = float(ms.ai_score or 0.0)

        prop = session.get(Property, prop_id)
        nhood_score = (
            _neighbourhood_score_for_property(session, prop)
            if prop is not None
            else aggregate_neighbourhood_score({})
        )

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

    session.flush()
    logger.info(
        "neighborhood_stats_computed",
        rows=count,
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

    # _COHORT_KEY_SQL is a fixed module constant (never user-supplied text);
    # :nkey/:lt are bound parameters. Assembled via plain concatenation
    # (not an f-string) per BIN-135.
    sql = text(
        """
        WITH listing_min AS (
            SELECT
                pl.property_id,
                pl.listing_type,
                MIN(pl.price) AS price
            FROM property_listings pl
            WHERE pl.active = true
              AND pl.price > 0
              AND pl.listing_type = :lt
            GROUP BY pl.property_id, pl.listing_type
        ),
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


def _min_listing_prices(session: Session, property_id) -> dict[str, float]:
    """Return {listing_type: min_price} for active listings on a property."""
    rows = (
        session.query(PropertyListing.listing_type, PropertyListing.price)
        .filter(
            PropertyListing.property_id == property_id,
            PropertyListing.active.is_(True),
            PropertyListing.price > 0,
            PropertyListing.listing_type.in_(("rent", "sale")),
        )
        .all()
    )
    out: dict[str, float] = {}
    for listing_type, price in rows:
        lt = str(listing_type)
        val = float(price)
        if lt not in out or val < out[lt]:
            out[lt] = val
    return out


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
    listing_prices = _min_listing_prices(session, prop.id)

    ppm_rent = None
    ppm_sale = None
    if prop.area_m2 and prop.area_m2 > 0:
        if "rent" in listing_prices:
            ppm_rent = listing_prices["rent"] / prop.area_m2
        if "sale" in listing_prices:
            ppm_sale = listing_prices["sale"] / prop.area_m2
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
