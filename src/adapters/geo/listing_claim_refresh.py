"""Refresh neighbourhood ``quality_meta.listing_claim_stats`` from listing LLM flags."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.listing_claim_stats import (
    aggregate_sentiment_rows,
    build_listing_claim_stats,
    merge_listing_claim_stats,
)
from infra.config import ListingClaimStatsConfig
from infra.logging import get_logger

logger = get_logger(__name__)

_SENTIMENT_ROWS_ALL = """
    SELECT
        p.neighborhood_id::text AS neighborhood_id,
        ms.meta AS meta
    FROM properties p
    INNER JOIN metrics_scoring ms ON ms.property_id = p.id
    WHERE p.neighborhood_id IS NOT NULL
      AND ms.meta IS NOT NULL
      AND ms.meta->'sentiment' IS NOT NULL
"""

_SENTIMENT_ROWS_ONE = """
    SELECT
        p.neighborhood_id::text AS neighborhood_id,
        ms.meta AS meta
    FROM properties p
    INNER JOIN metrics_scoring ms ON ms.property_id = p.id
    WHERE p.neighborhood_id = CAST(:nid AS uuid)
      AND ms.meta IS NOT NULL
      AND ms.meta->'sentiment' IS NOT NULL
"""


def _load_sentiment_rows(
    session: Session,
    *,
    neighborhood_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Load properties with sentiment meta and a neighbourhood assignment."""
    if neighborhood_id:
        rows = session.execute(
            text(_SENTIMENT_ROWS_ONE),
            {"nid": neighborhood_id},
        ).mappings().all()
    else:
        rows = session.execute(text(_SENTIMENT_ROWS_ALL)).mappings().all()
    return [dict(row) for row in rows]


def _load_neighborhood_meta_row(
    session: Session,
    neighborhood_id: str,
) -> Optional[dict[str, Any]]:
    """Return ``{quality_meta}`` for an existing neighbourhood, else ``None``."""
    row = session.execute(
        text(
            """
            SELECT quality_meta
            FROM neighborhoods
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": neighborhood_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def refresh_listing_claim_stats(
    session: Session,
    cfg: ListingClaimStatsConfig,
    *,
    neighborhood_id: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> dict[str, int]:
    """Aggregate listing sentiment flags into nested ``listing_claim_stats``.

    Updates ``quality_meta`` only — never writes amenity/transit/access/safety
    score columns. Returns counts: ``processed``, ``updated``, ``skipped``,
    ``errors``.
    """
    processed = updated = skipped = errors = 0
    try:
        rows = _load_sentiment_rows(session, neighborhood_id=neighborhood_id)
        by_nhood = aggregate_sentiment_rows(rows)

        for nid, agg in by_nhood.items():
            processed += 1
            if agg.sample_size < int(cfg.min_sample_size):
                skipped += 1
                continue
            try:
                nhood_row = _load_neighborhood_meta_row(session, nid)
                if nhood_row is None:
                    skipped += 1
                    continue
                stats = build_listing_claim_stats(
                    sample_size=agg.sample_size,
                    green_counts=agg.green_counts,
                    red_counts=agg.red_counts,
                    top_n=int(cfg.top_n),
                    refreshed_at=refreshed_at,
                )
                new_meta = merge_listing_claim_stats(
                    nhood_row.get("quality_meta"), stats
                )
                session.execute(
                    text(
                        """
                        UPDATE neighborhoods
                        SET quality_meta = CAST(:meta AS jsonb)
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"meta": json.dumps(new_meta), "id": nid},
                )
                updated += 1
            except Exception:
                errors += 1
                logger.exception(
                    "listing_claim_stats_row_error",
                    neighborhood_id=nid,
                )
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "listing_claim_stats_refresh_done",
        processed=processed,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )
    return {
        "processed": processed,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
