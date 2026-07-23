"""Top-new-deals digest selection (BIN-52 / FR-21).

Selection rule (documented for operators and feature docs)::

    Properties with first_seen within the lookback window, combined_score
    IS NOT NULL and >= min_combined_score, ordered by combined_score DESC
    then first_seen DESC, capped at limit. Rows are projected with the
    AD-12 list serializer (map_property_list_item).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.property_projection import LIST_SELECT_COLUMNS, map_property_list_item

TOP_DEALS_RULE = (
    "first_seen within lookback_hours; combined_score IS NOT NULL and "
    ">= min_combined_score; order by combined_score DESC, first_seen DESC; limit N"
)


def select_top_deals(
    session: Session,
    *,
    lookback_hours: int = 168,
    min_combined_score: float = 0.0,
    limit: int = 10,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return AD-12 projected properties matching the top-deals rule."""
    if limit <= 0:
        return []

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    since = clock - timedelta(hours=lookback_hours)

    sql = text(f"""
        SELECT {LIST_SELECT_COLUMNS}
        FROM properties p
        LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
        LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
        WHERE p.first_seen >= :since
          AND ms.combined_score IS NOT NULL
          AND ms.combined_score >= :min_score
        ORDER BY ms.combined_score DESC, p.first_seen DESC
        LIMIT :limit
    """)
    rows = session.execute(
        sql,
        {
            "since": since,
            "min_score": min_combined_score,
            "limit": limit,
        },
    ).mappings().fetchall()
    return [map_property_list_item(row) for row in rows]
