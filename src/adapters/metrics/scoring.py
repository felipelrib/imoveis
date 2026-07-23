"""Scoring engine — per-neighborhood statistics with dynamic weight recalculation.

Replaces the original global in-memory approach with:
- SQL window functions for per-neighborhood stats (no OOM risk)
- Mean, median, stddev, z-score, percentile rank stored per property
- Single-query bulk recalculation when weights change (instantaneous)
- score_single_property() for post-AI-enrichment updates
"""

from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from adapters.db.models import MetricsScoring, Property
from core.entities import ScoringWeights
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)


def _sigmoid_undervalued(z_score: float) -> float:
    """Map z-score to 0..1 stat_score.

    Negative z = cheaper than neighbourhood average = HIGHER score (undervalued).
    We negate z so lower prices produce higher scores.
    """
    return 1.0 / (1.0 + math.exp(z_score))


def _stat_analysis(z_score: float) -> dict:
    bands = (
        (-1.0, "Highly Undervalued", "Significantly cheaper than similar properties in the area."),
        (-0.2, "Slightly Undervalued", "Priced slightly below the neighborhood average."),
        (0.2, "Average", "Priced closely to the neighborhood average."),
        (1.0, "Slightly Overvalued", "Priced slightly above the neighborhood average."),
    )
    for threshold, category, reasoning in bands:
        if z_score < threshold:
            return {"category": category, "reasoning": reasoning}
    return {"category": "Highly Overvalued", "reasoning": "Significantly more expensive than similar properties in the area."}


def _scoring_weights() -> ScoringWeights:
    cfg = get_config()
    return ScoringWeights(stat_weight=cfg.scoring.stat_weight, ai_weight=cfg.scoring.ai_weight)


def _update_metrics_score(ms, stat_score, price_per_m2, stats, z_score, weights, stat_analysis) -> None:
    ms.stat_score, ms.price_per_m2 = stat_score, price_per_m2
    ms.neighborhood_mean, ms.neighborhood_median, ms.z_score = stats["mean"], stats["median"], z_score
    ms.combined_score = stat_score * weights.stat_weight + float(ms.ai_score or 0.0) * weights.ai_weight
    meta = dict(ms.meta or {})
    meta["stat_analysis"] = stat_analysis
    ms.meta = meta


def compute_neighborhood_stats(
    session: Session,
    neighborhood_key: Optional[str] = None,
) -> int:
    """Compute per-neighbourhood price statistics using SQL window functions.

    Uses a single round-trip to the database.  Results are upserted into
    metrics_scoring.  Caller is responsible for committing the transaction.

    Args:
        session: Active SQLAlchemy session.
        neighborhood_key: If provided, only recompute for that neighbourhood key.

    Returns:
        Number of property rows processed.
    """
    weights = _scoring_weights()

    where_clause = (
        "AND COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown') = :nkey"
        if neighborhood_key is not None
        else ""
    )

    sql = text(f"""
        stats AS (
            SELECT
                p.id                                                  AS property_id,
                COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown') as n_key,
                p.price / NULLIF(p.area_m2, 0)                       AS price_per_m2,
                AVG(p.price / NULLIF(p.area_m2, 0))
                    OVER (PARTITION BY
                        COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')
                    ) AS neighborhood_mean,
                (
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p2.price / NULLIF(p2.area_m2, 0))
                    FROM properties p2
                    LEFT JOIN neighborhoods n2 ON n2.id = p2.neighborhood_id
                    WHERE p2.area_m2 > 0 AND p2.active = true
                      AND COALESCE(n2.name, p2.props_json->>'neighborhood', 'Unknown')
                          = COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')
                ) AS neighborhood_median,
                STDDEV(p.price / NULLIF(p.area_m2, 0))
                    OVER (PARTITION BY
                        COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')
                    ) AS neighborhood_stddev,
                PERCENT_RANK()
                    OVER (
                        PARTITION BY COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')
                        ORDER BY p.price / NULLIF(p.area_m2, 0)
                    )                                                 AS percentile_rank
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.area_m2 IS NOT NULL
              AND p.area_m2 > 0
              AND p.active = true
              {where_clause}
        )
        SELECT
            property_id,
            price_per_m2,
            neighborhood_mean,
            neighborhood_median,
            CASE
                WHEN neighborhood_stddev > 0
                    THEN (price_per_m2 - neighborhood_mean) / neighborhood_stddev
                ELSE 0
            END AS z_score,
            percentile_rank
        FROM stats
        """)

    params: dict = {}
    if neighborhood_key is not None:
        params["nkey"] = str(neighborhood_key)

    rows = session.execute(sql, params).fetchall()
    count = len(rows)

    for row in rows:
        prop_id = row[0]
        price_per_m2 = row[1]
        n_mean = row[2]
        n_median = row[3]
        z = float(row[4]) if row[4] is not None else 0.0
        pct_rank = float(row[5]) if row[5] is not None else 0.5

        stat_score = _sigmoid_undervalued(z)

        stat_analysis = _stat_analysis(z)

        ms = session.query(MetricsScoring).filter_by(property_id=prop_id).one_or_none()
        if ms is None:
            ms = MetricsScoring(
                property_id=prop_id,
                stat_score=stat_score,
                ai_score=0.0,
                combined_score=stat_score * weights.stat_weight,
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
            ai = float(ms.ai_score or 0.0)
            ms.combined_score = stat_score * weights.stat_weight + ai * weights.ai_weight

            meta = dict(ms.meta or {})
            meta["stat_analysis"] = stat_analysis
            ms.meta = meta

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

    This is O(1) in application memory regardless of table size.

    Args:
        session: Active SQLAlchemy session.
        weights: Weight config.  Defaults to values in app_config.yaml.

    Returns:
        Number of rows updated.
    """
    if weights is None:
        cfg = get_config()
        weights = ScoringWeights(
            stat_weight=cfg.scoring.stat_weight,
            ai_weight=cfg.scoring.ai_weight,
        )

    result = session.execute(
        text("""
            UPDATE metrics_scoring
            SET combined_score =
                    COALESCE(stat_score, 0) * :w_stat
                    + COALESCE(ai_score, 0)  * :w_ai,
                updated_at = NOW()
            """),
        {"w_stat": weights.stat_weight, "w_ai": weights.ai_weight},
    )
    count = result.rowcount
    session.flush()
    logger.info(
        "bulk_scores_recalculated",
        rows=count,
        stat_weight=weights.stat_weight,
        ai_weight=weights.ai_weight,
    )
    return count


def get_neighborhood_stats_cached(session: Session, n_key: str) -> dict:
    import json

    from infra.redis_client import get_redis
    r = get_redis()
    cache_key = f"n_stats:{n_key}"
    cached = r.get(cache_key)
    if cached:
        return json.loads(cached)

    sql = text("""
        SELECT
            AVG(p.price / NULLIF(p.area_m2, 0)) AS mean,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.price / NULLIF(p.area_m2, 0)) AS median,
            STDDEV(p.price / NULLIF(p.area_m2, 0)) AS stddev,
            COUNT(p.id) AS count
        FROM properties p
        LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
        WHERE p.area_m2 > 0 AND p.active = true
          AND COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown') = :nkey
    """)
    row = session.execute(sql, {"nkey": n_key}).mappings().fetchone()
    stats = {
        "mean": float(row["mean"]) if row and row["mean"] else 0.0,
        "median": float(row["median"]) if row and row["median"] else 0.0,
        "stddev": float(row["stddev"]) if row and row["stddev"] else 0.0,
        "count": int(row["count"]) if row and row["count"] else 0
    }
    r.setex(cache_key, 60, json.dumps(stats))
    return stats


def score_single_property(session: Session, property_id: str) -> None:
    """Recompute combined_score for a single property after AI enrichment.

    Fetches neighbourhood context from existing MetricsScoring peers, then
    recomputes the z-score relative to them and updates the single row.

    Args:
        session: Active SQLAlchemy session.
        property_id: UUID string of the property to score.
    """
    # Fetch the property to get neighbourhood context
    prop = session.get(Property, property_id)
    if prop is None:
        logger.warning("score_single_property_not_found", property_id=property_id)
        return

    n_key = _property_neighborhood_key(session, prop)

    stats = get_neighborhood_stats_cached(session, n_key)

    price_per_m2 = prop.price / prop.area_m2 if prop.area_m2 and prop.area_m2 > 0 else 0.0
    z = (price_per_m2 - stats["mean"]) / stats["stddev"] if stats["stddev"] > 0 else 0.0

    stat_score = _sigmoid_undervalued(z)

    stat_analysis = _stat_analysis(z)
    weights = _scoring_weights()

    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
    if ms is None:
        ms = MetricsScoring(
            property_id=property_id,
            stat_score=stat_score,
            ai_score=0.0,
            combined_score=stat_score * weights.stat_weight,
            price_per_m2=price_per_m2,
            neighborhood_mean=stats["mean"],
            neighborhood_median=stats["median"],
            z_score=z,
            percentile_rank=0.5,  # Approximation
            meta={"stat_analysis": stat_analysis},
        )
        session.add(ms)
    else:
        _update_metrics_score(ms, stat_score, price_per_m2, stats, z, weights, stat_analysis)

    session.flush()

    logger.info("single_property_scored", property_id=property_id)


def _property_neighborhood_key(session: Session, prop: Property) -> str:
    if not prop.neighborhood_id:
        return (prop.props_json or {}).get("neighborhood", "Unknown")
    from adapters.db.models import Neighborhood
    neighborhood = session.get(Neighborhood, prop.neighborhood_id)
    return neighborhood.name if neighborhood else "Unknown"
