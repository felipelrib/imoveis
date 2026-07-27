"""Neighbourhood quality profile mapping (storage + API read shape).

Scores are floats in ``[0.0, 1.0]``; ``None`` means unknown / not yet filled.
No scoring blend lives here — BIN-86 is storage + read only.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def normalize_quality_score(value: Any) -> Optional[float]:
    """Coerce a score to ``float`` in ``[0, 1]``, or ``None`` if unknown/invalid."""
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0.0 or score > 1.0:
        return None
    return score


def normalize_risk_flags(value: Any) -> list[str]:
    """Return a list of non-empty risk flag strings (empty when unknown)."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def quality_profile_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map a DB/list row to nullable quality profile API fields."""
    meta = row.get("quality_meta")
    if meta is not None and not isinstance(meta, dict):
        meta = None
    notes = row.get("quality_notes")
    if notes is not None:
        notes = str(notes).strip() or None
    neighborhood_id = row.get("id")
    if neighborhood_id is not None:
        neighborhood_id = str(neighborhood_id)
    return {
        "id": neighborhood_id,
        "amenity_score": normalize_quality_score(row.get("amenity_score")),
        "transit_score": normalize_quality_score(row.get("transit_score")),
        "access_score": normalize_quality_score(row.get("access_score")),
        "safety_score": normalize_quality_score(row.get("safety_score")),
        "risk_flags": normalize_risk_flags(row.get("risk_flags")),
        "quality_meta": meta,
        "quality_notes": notes,
    }
