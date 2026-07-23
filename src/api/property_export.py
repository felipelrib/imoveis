"""Serialize AD-12 property projections to export JSON / CSV (BIN-50 / FR-21).

CSV columns are derived from ``map_property_list_item`` output only — no parallel
flattener over raw DB rows (AD-12).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Mapping, Optional, Sequence

EXPORT_MAX_ROWS = 5000

# Scalar / simple AD-12 fields written as CSV columns (order is stable for clients).
_CSV_SCALAR_COLUMNS: tuple[str, ...] = (
    "id",
    "platform",
    "platform_id",
    "title",
    "price",
    "area_m2",
    "bedrooms",
    "bathrooms",
    "parking",
    "address",
    "created_at",
    "lat",
    "lon",
    "stat_score",
    "ai_score",
    "combined_score",
    "percentile_rank",
    "z_score",
    "price_per_m2",
    "neighborhood_mean",
    "neighborhood_id",
    "neighborhood_name",
    "description",
    "available_for_rent",
    "available_for_sale",
    "condition_score",
    "sentiment_score",
    "stat_category",
    "stat_reasoning",
    "deal_summary",
    "visual_category",
    "visual_reasoning",
    "sentiment_category",
    "sentiment_reasoning",
)

_JSON_LIST_COLUMNS: tuple[str, ...] = (
    "image_urls",
    "ai_features",
    "ai_issues",
    "ai_green_flags",
    "ai_red_flags",
    "listings",
)

_PRIMARY_LISTING_COLUMNS: tuple[str, ...] = (
    "platform",
    "platform_listing_id",
    "listing_type",
    "price",
    "currency",
    "url",
    "is_furnished",
    "accepts_pets",
    "condo_fee",
    "iptu",
)

CSV_COLUMNS: tuple[str, ...] = (
    *_CSV_SCALAR_COLUMNS,
    *(_JSON_LIST_COLUMNS),
    *(f"primary_listing_{c}" for c in _PRIMARY_LISTING_COLUMNS),
)


def properties_to_export_json(
    items: Sequence[Mapping[str, Any]],
    total: int,
) -> Dict[str, Any]:
    """Build the JSON export envelope from AD-12 list items."""
    return {
        "properties": list(items),
        "total": total,
        "truncated": total > len(items),
    }


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, default=str)


def _row_from_projection(item: Mapping[str, Any]) -> Dict[str, str]:
    row: Dict[str, str] = {}
    for col in _CSV_SCALAR_COLUMNS:
        row[col] = _cell(item.get(col))
    for col in _JSON_LIST_COLUMNS:
        row[col] = _json_cell(item.get(col) or [])
    primary: Optional[Mapping[str, Any]] = item.get("primary_listing")
    for col in _PRIMARY_LISTING_COLUMNS:
        key = f"primary_listing_{col}"
        if primary is None:
            row[key] = ""
        else:
            row[key] = _cell(primary.get(col))
    return row


def properties_to_csv(items: Sequence[Mapping[str, Any]]) -> str:
    """Render AD-12 list items as CSV (header-only when empty)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for item in items:
        writer.writerow(_row_from_projection(item))
    return buf.getvalue()
