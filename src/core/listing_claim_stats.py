"""Aggregate listing LLM sentiment flags by neighbourhood (BIN-93).

Weak secondary signal only — seller ad copy is biased. Never treat high
green-flag rates as neighbourhood ground truth. Writes nested
``quality_meta.listing_claim_stats`` without touching amenity/safety scores.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

LISTING_CLAIM_SOURCE = "listing_llm_aggregate"

LISTING_CLAIM_DISCLAIMER = (
    "Seller listing copy is biased: ads omit problems and overstate amenities. "
    "A high green-flag rate does not mean a good neighbourhood — treat these "
    "aggregates as a weak secondary signal, never as ground truth."
)


@dataclass
class NeighbourhoodFlagAgg:
    """Per-neighbourhood flag counters from listing sentiment meta."""

    sample_size: int = 0
    green_counts: Counter = field(default_factory=Counter)
    red_counts: Counter = field(default_factory=Counter)


def normalize_flag(value: Any) -> Optional[str]:
    """Strip, collapse whitespace, and casefold a flag string (or None)."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).casefold()
    return text or None


def extract_flags_from_sentiment(
    sentiment: Any,
) -> tuple[list[str], list[str]]:
    """Return ``(green_flags, red_flags)`` normalized lists from sentiment meta."""
    if not isinstance(sentiment, Mapping):
        return [], []
    green_raw = sentiment.get("green_flags")
    red_raw = sentiment.get("red_flags")
    green = (
        [f for f in (normalize_flag(x) for x in green_raw) if f]
        if isinstance(green_raw, list)
        else []
    )
    red = (
        [f for f in (normalize_flag(x) for x in red_raw) if f]
        if isinstance(red_raw, list)
        else []
    )
    return green, red


def top_flag_frequencies(
    counts: Counter,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Top flags by count desc, flag asc for ties."""
    if limit <= 0 or not counts:
        return []
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"flag": flag, "count": int(count)} for flag, count in ranked[:limit]]


def build_listing_claim_stats(
    *,
    sample_size: int,
    green_counts: Counter,
    red_counts: Counter,
    top_n: int,
    refreshed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build the ``listing_claim_stats`` payload stored under ``quality_meta``."""
    when = refreshed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "source": LISTING_CLAIM_SOURCE,
        "disclaimer": LISTING_CLAIM_DISCLAIMER,
        "sample_size": int(sample_size),
        "top_green_flags": top_flag_frequencies(green_counts, limit=top_n),
        "top_red_flags": top_flag_frequencies(red_counts, limit=top_n),
        "refreshed_at": when,
    }


def merge_listing_claim_stats(
    existing_meta: Any,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge nested ``listing_claim_stats`` without wiping sibling meta keys."""
    meta: dict[str, Any] = (
        dict(existing_meta) if isinstance(existing_meta, Mapping) else {}
    )
    meta["listing_claim_stats"] = dict(stats)
    return meta


def aggregate_sentiment_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, NeighbourhoodFlagAgg]:
    """Group listing ``metrics_scoring.meta`` rows by ``neighborhood_id``."""
    by_nhood: dict[str, NeighbourhoodFlagAgg] = {}
    for row in rows:
        nid = row.get("neighborhood_id")
        if nid is None:
            continue
        nid_key = str(nid).strip()
        if not nid_key:
            continue
        meta = row.get("meta")
        if not isinstance(meta, Mapping):
            continue
        sentiment = meta.get("sentiment")
        if not isinstance(sentiment, Mapping):
            continue
        green, red = extract_flags_from_sentiment(sentiment)
        agg = by_nhood.get(nid_key)
        if agg is None:
            agg = NeighbourhoodFlagAgg()
            by_nhood[nid_key] = agg
        agg.sample_size += 1
        agg.green_counts.update(green)
        agg.red_counts.update(red)
    return by_nhood
