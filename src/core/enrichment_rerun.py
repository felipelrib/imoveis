"""Selective AI enrichment re-run candidate selection (BIN-95).

Operators can enqueue AI with mode/filters/stages without wiping scores.
Enqueue never clears existing ``ai_score`` / meta — failures only skip.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Sequence
from uuid import UUID

from core.photo_gate import passes_photo_gate

MODE_MISSING = "missing"
MODE_FORCE = "force"
MODE_STALE_BEFORE = "stale_before"
MODES = frozenset({MODE_MISSING, MODE_FORCE, MODE_STALE_BEFORE})

STAGES_ALL = "all"
STAGES_VISUAL_SENTIMENT = "visual+sentiment"
STAGES_VERDICT_ONLY = "verdict_only"
STAGES = frozenset({STAGES_ALL, STAGES_VISUAL_SENTIMENT, STAGES_VERDICT_ONLY})

NEEDS_PHOTOS = frozenset({STAGES_ALL, STAGES_VISUAL_SENTIMENT})


@dataclass
class EnrichmentRerunParams:
    """Operator options for selective AI re-run."""

    mode: str = MODE_MISSING
    stages: str = STAGES_ALL
    dry_run: bool = False
    city: Optional[str] = None
    neighbourhood_ids: Optional[list[UUID]] = None
    platform: Optional[str] = None
    limit: Optional[int] = None
    active_only: bool = True
    stale_before: Optional[datetime] = None

    def filters_echo(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "neighbourhood_ids": [str(x) for x in self.neighbourhood_ids]
            if self.neighbourhood_ids
            else None,
            "platform": self.platform,
            "limit": self.limit,
            "active_only": self.active_only,
            "stale_before": self.stale_before.isoformat() if self.stale_before else None,
        }


@dataclass
class EnrichmentRerunResult:
    """Counts returned to admin API + audit log."""

    mode: str
    stages: str
    dry_run: bool
    queued: int = 0
    would_queue: int = 0
    skipped_no_images: int = 0
    skipped_too_few_photos: int = 0
    skipped_missing_prior_enrichment: int = 0
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def has_prior_visual_sentiment(meta: Any) -> bool:
    """True when meta already has visual + sentiment blobs for verdict_only."""
    if not isinstance(meta, dict):
        return False
    visual = meta.get("visual")
    sentiment = meta.get("sentiment")
    return isinstance(visual, dict) and bool(visual) and isinstance(sentiment, dict) and bool(
        sentiment
    )


def mode_is_missing_ai(metrics: Any) -> bool:
    """Match Dashboard enriched semantics: no row or ai_score NULL/0."""
    if metrics is None:
        return True
    score = getattr(metrics, "ai_score", None)
    return score is None or score == 0 or score == 0.0


def _parse_enriched_at(meta: Any) -> Optional[datetime]:
    if not isinstance(meta, dict):
        return None
    raw = meta.get("enriched_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def mode_matches_row(
    mode: str,
    metrics: Any,
    *,
    stale_before: Optional[datetime],
) -> bool:
    """Return whether a (property, metrics) row matches the selected mode."""
    if mode == MODE_FORCE:
        return True
    if mode == MODE_MISSING:
        return mode_is_missing_ai(metrics)
    if mode == MODE_STALE_BEFORE:
        if stale_before is None:
            raise ValueError("stale_before is required when mode=stale_before")
        cutoff = stale_before
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        if metrics is None:
            return True
        enriched_at = _parse_enriched_at(getattr(metrics, "meta", None))
        if enriched_at is None:
            return True
        return enriched_at < cutoff
    raise ValueError(f"unknown mode: {mode}")


def evaluate_candidate(
    prop: Any,
    metrics: Any,
    stages: str,
    gate_kwargs: dict[str, Any],
) -> tuple[str, Optional[str]]:
    """Return ``(action, detail)`` where action is queue or skip_*.

    Photo gate applies only to visual stages. ``verdict_only`` requires prior
    visual+sentiment meta and does not require images.
    """
    if stages not in STAGES:
        raise ValueError(f"unknown stages: {stages}")

    if stages == STAGES_VERDICT_ONLY:
        meta = getattr(metrics, "meta", None) if metrics is not None else None
        if not has_prior_visual_sentiment(meta):
            return ("skip_prior", "missing visual/sentiment meta")
        return ("queue", None)

    image_urls = prop.image_urls if isinstance(getattr(prop, "image_urls", None), list) else []
    if not image_urls:
        return ("skip_images", "no images")
    ok, reason, _, _ = passes_photo_gate(prop, **gate_kwargs)
    if not ok:
        return ("skip_photos", reason or "too few photos")
    return ("queue", None)


EnqueueFn = Callable[..., None]


def run_enrichment_rerun(
    rows: Iterable[tuple[Any, Any]],
    params: EnrichmentRerunParams,
    *,
    gate_kwargs: dict[str, Any],
    enqueue_fn: EnqueueFn,
) -> EnrichmentRerunResult:
    """Filter candidate rows and optionally enqueue ``ai_enrich``.

    ``enqueue_fn`` receives keyword args:
    ``property_id``, ``image_urls``, ``description``, ``stages``.
    """
    if params.mode not in MODES:
        raise ValueError(f"unknown mode: {params.mode}")
    if params.stages not in STAGES:
        raise ValueError(f"unknown stages: {params.stages}")
    if params.mode == MODE_STALE_BEFORE and params.stale_before is None:
        raise ValueError("stale_before is required when mode=stale_before")

    result = EnrichmentRerunResult(
        mode=params.mode,
        stages=params.stages,
        dry_run=params.dry_run,
        filters=params.filters_echo(),
    )
    limit = params.limit

    for prop, metrics in rows:
        if not mode_matches_row(params.mode, metrics, stale_before=params.stale_before):
            continue
        # ``limit`` caps successful queue/would_queue, not skip counters.
        if limit is not None and result.would_queue >= limit:
            break

        action, _ = evaluate_candidate(prop, metrics, params.stages, gate_kwargs)
        if action == "skip_images":
            result.skipped_no_images += 1
            continue
        if action == "skip_photos":
            result.skipped_too_few_photos += 1
            continue
        if action == "skip_prior":
            result.skipped_missing_prior_enrichment += 1
            continue

        result.would_queue += 1
        if params.dry_run:
            continue

        image_urls = prop.image_urls if isinstance(getattr(prop, "image_urls", None), list) else []
        description = getattr(prop, "description", None) or ""
        enqueue_fn(
            property_id=str(prop.id),
            image_urls=image_urls,
            description=description,
            stages=params.stages,
        )
        result.queued += 1

    return result


def fetch_candidate_rows(session: Any, params: EnrichmentRerunParams) -> Sequence[tuple[Any, Any]]:
    """Load ``(Property, MetricsScoring|None)`` rows matching property filters.

    Mode filtering (missing / force / stale) is applied in Python via
    :func:`run_enrichment_rerun` so unit tests can exercise the same path
    without SQL dialect coupling. Property-level filters run in SQL.
    """
    from sqlalchemy import or_

    from adapters.db.models import MetricsScoring, Neighborhood, Property

    query = session.query(Property, MetricsScoring).outerjoin(
        MetricsScoring, Property.id == MetricsScoring.property_id
    )

    if params.active_only:
        query = query.filter(Property.active.is_(True))

    if params.platform:
        query = query.filter(Property.platform == params.platform)

    if params.neighbourhood_ids:
        query = query.filter(Property.neighborhood_id.in_(params.neighbourhood_ids))

    if params.city:
        query = query.join(
            Neighborhood, Property.neighborhood_id == Neighborhood.id
        ).filter(Neighborhood.city == params.city)

    # Push missing-mode filter into SQL for efficiency on large tables.
    if params.mode == MODE_MISSING:
        query = query.filter(
            or_(
                MetricsScoring.id.is_(None),
                MetricsScoring.ai_score.is_(None),
                MetricsScoring.ai_score == 0,
            )
        )

    # Over-fetch slightly when limit set so Python-side skips can fill the quota.
    if params.limit is not None:
        # Fetch more than limit to account for photo/prior skips; cap multiplier.
        fetch_cap = min(max(params.limit * 5, params.limit), 25000)
        query = query.limit(fetch_cap)

    return query.all()
