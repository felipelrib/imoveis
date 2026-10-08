"""Top-new-deals digest selection (BIN-52 / FR-21, BIN-107).

Selection rule (documented for operators and feature docs)::

    Properties with first_seen within the lookback window, target
    combined_score column IS NOT NULL and >= min_combined_score, ordered
    by that column DESC then first_seen DESC, capped at limit. Rows are
    projected with the AD-12 list serializer (map_property_list_item).

    ``score_target`` selects primary / rent / sale combined_score column
    (no COALESCE fallback — typed targets require that typed score).

    With ``alerted_owner`` (Story 1.9), a Property that a saved-search
    new-match email already told that owner about - or is about to, under a
    search that still notifies - is left out: the digest does not repeat it.
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

# Already alerted to this owner (``sent``), or waiting for the daily window of
# a search that still notifies (``pending``). The LEFT JOIN keeps ``sent`` rows
# of a deleted search (``saved_search_id`` NULL).
_NOT_ALREADY_ALERTED = (
    "NOT EXISTS ("
    "SELECT 1 FROM saved_search_new_matches a "
    "LEFT JOIN saved_searches s ON s.id = a.saved_search_id "
    "WHERE a.property_id = p.id AND a.owner = :alerted_owner "
    "AND (a.status = 'sent' OR (a.status = 'pending' AND s.notify_new_matches))"
    ")"
)

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
    alerted_owner: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return AD-12 projected properties matching the top-deals rule.

    ``alerted_owner``: leave out Properties already alerted to that owner by a
    saved-search new-match email (see the module docstring).
    """
    if limit <= 0:
        return []

    column = score_column_for_target(score_target)

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    since = clock - timedelta(hours=lookback_hours)

    # column is enum-mapped via score_column_for_target()/_SCORE_COLUMNS — never
    # touches string interpolation of arbitrary/user-supplied text (BIN-135).
    sql = text(
        "SELECT " + LIST_SELECT_COLUMNS + " "
        "FROM properties p "
        "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
        "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
        "WHERE p.first_seen >= :since "
        "  AND " + column + " IS NOT NULL "
        "  AND " + column + " >= :min_score "
        + ("  AND " + _NOT_ALREADY_ALERTED + " " if alerted_owner is not None else "")
        + "ORDER BY " + column + " DESC, p.first_seen DESC "
        "LIMIT :limit"
    )
    params: Dict[str, Any] = {
        "since": since,
        "min_score": min_combined_score,
        "limit": limit,
    }
    if alerted_owner is not None:
        params["alerted_owner"] = alerted_owner
    rows = session.execute(sql, params).mappings().fetchall()
    return [map_property_list_item(row) for row in rows]
