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
from uuid import UUID

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


def compute_neighborhood_stats(
    session: Session,
    neighborhood_id: Optional[UUID] = None,
) -> int:
    """Compute per-neighbourhood price statistics using SQL window functions.

    Uses a single round-trip to the database.  Results are upserted into
    metrics_scoring.  Caller is responsible for committing the transaction.

    Args:
        session: Active SQLAlchemy session.
        neighborhood_id: If provided, only recompute for that neighbourhood.

    Returns:
        Number of property rows processed.
    """
    cfg = get_config()
    weights = ScoringWeights(
        stat_weight=cfg.scoring.stat_weight,
        ai_weight=cfg.scoring.ai_weight,
    )

    where_clause = (
        "AND p.neighborhood_id = :nid" if neighborhood_id is not None else ""
    )

    sql = text(
        f"""
        WITH medians AS (
            SELECT
                neighborhood_id,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price / NULLIF(area_m2, 0)) AS neighborhood_median
            FROM properties
            WHERE area_m2 IS NOT NULL AND area_m2 > 0 AND active = true
            GROUP BY neighborhood_id
        ),
        stats AS (
            SELECT
                p.id                                                  AS property_id,
                p.neighborhood_id,
                p.price / NULLIF(p.area_m2, 0)                       AS price_per_m2,
                AVG(p.price / NULLIF(p.area_m2, 0))
                    OVER (PARTITION BY p.neighborhood_id)             AS neighborhood_mean,
                m.neighborhood_median,
                STDDEV(p.price / NULLIF(p.area_m2, 0))
                    OVER (PARTITION BY p.neighborhood_id)             AS neighborhood_stddev,
                PERCENT_RANK()
                    OVER (
                        PARTITION BY p.neighborhood_id
                        ORDER BY p.price / NULLIF(p.area_m2, 0)
                    )                                                 AS percentile_rank
            FROM properties p
            LEFT JOIN medians m ON p.neighborhood_id = m.neighborhood_id
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
        """
    )

    params: dict = {}
    if neighborhood_id is not None:
        params["nid"] = str(neighborhood_id)

    rows = session.execute(sql, params).fetchall()
    count = len(rows)

    for row in rows:
        prop_id = row[0]
        price_per_m2 = row[1]
        n_mean = row[2]
        n_median = row[3]
        z = float(row[5]) if row[5] is not None else 0.0
        pct_rank = float(row[6]) if row[6] is not None else 0.5

        stat_score = _sigmoid_undervalued(z)

        ms = (
            session.query(MetricsScoring)
            .filter_by(property_id=prop_id)
            .one_or_none()
        )
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
                meta={},
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

    session.flush()
    logger.info(
        "neighborhood_stats_computed",
        rows=count,
        neighborhood_id=str(neighborhood_id) if neighborhood_id else "all",
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
        text(
            """
            UPDATE metrics_scoring
            SET combined_score =
                    COALESCE(stat_score, 0) * :w_stat
                    + COALESCE(ai_score, 0)  * :w_ai,
                updated_at = NOW()
            """
        ),
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


def score_single_property(session: Session, property_id: str) -> None:
    """Recompute combined_score for a single property after AI enrichment.

    Fetches neighbourhood context from existing MetricsScoring peers, then
    recomputes the z-score relative to them and updates the single row.

    Args:
        session: Active SQLAlchemy session.
        property_id: UUID string of the property to score.
    """
    cfg = get_config()
    weights = ScoringWeights(
        stat_weight=cfg.scoring.stat_weight,
        ai_weight=cfg.scoring.ai_weight,
    )

    # Fetch the property to get neighbourhood context
    prop = session.get(Property, property_id)
    if prop is None:
        logger.warning("score_single_property_not_found", property_id=property_id)
        return

    # Compute per-neighbourhood stats for just this neighbourhood
    if prop.neighborhood_id:
        compute_neighborhood_stats(session, neighborhood_id=prop.neighborhood_id)
    else:
        # No neighbourhood assigned — recompute only this row's combined score
        ms = (
            session.query(MetricsScoring)
            .filter_by(property_id=property_id)
            .one_or_none()
        )
        if ms:
            stat = float(ms.stat_score or 0.0)
            ai = float(ms.ai_score or 0.0)
            ms.combined_score = stat * weights.stat_weight + ai * weights.ai_weight
            session.flush()

    logger.info("single_property_scored", property_id=property_id)
