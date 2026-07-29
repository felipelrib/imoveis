"""Top-new-deals digest selection (BIN-52 / FR-21, BIN-107).

Selection rule (documented for operators and feature docs)::

    Properties with first_seen within the lookback window, target
    combined_score column IS NOT NULL and >= min_combined_score, ordered
    by that column DESC then first_seen DESC, capped at limit. Rows are
    projected with the AD-12 list serializer (map_property_list_item).

    ``score_target`` selects primary / rent / sale combined_score column
    (no COALESCE fallback — typed targets require that typed score).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.property_projection import LIST_SELECT_COLUMNS, map_property_list_item

_SCORE_COLUMNS = {
    "primary": "ms.combined_score",
    "rent": "ms.combined_score_rent",
    "sale": "ms.combined_score_sale",
}

TOP_DEALS_RULE = (
    "first_seen within lookback_hours; combined_score IS NOT NULL and "
    ">= min_combined_score; order by combined_score DESC, first_seen DESC; limit N"
)


def score_column_for_target(score_target: str) -> str:
    """Return the fully-qualified SQL column for a digest score target."""
    try:
        return _SCORE_COLUMNS[score_target]
    except KeyError as exc:
        raise ValueError(
            f"score_target must be one of {sorted(_SCORE_COLUMNS)}; got {score_target!r}"
        ) from exc


def top_deals_rule(score_target: str = "primary") -> str:
    """Human-readable selection rule reflecting the active score column."""
    if score_target == "primary":
        return TOP_DEALS_RULE
    column = score_column_for_target(score_target)
    short = column.removeprefix("ms.")
    return (
        f"first_seen within lookback_hours; {short} IS NOT NULL and "
        f">= min_combined_score; order by {short} DESC, first_seen DESC; limit N"
    )


def select_top_deals(
    session: Session,
    *,
    lookback_hours: int = 168,
    min_combined_score: float = 0.0,
    limit: int = 10,
    score_target: str = "primary",
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return AD-12 projected properties matching the top-deals rule."""
    if limit <= 0:
        return []

    column = score_column_for_target(score_target)

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
          AND {column} IS NOT NULL
          AND {column} >= :min_score
        ORDER BY {column} DESC, p.first_seen DESC
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
