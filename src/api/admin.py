"""Admin control API — worker pause/resume, GPU scaling, scoring recalculation.

Fixes from gap analysis:
- workers_status used r.get() is not None (broken) → fixed to r.exists()
- GPU scale imported hardcoded Redis → now uses centralized get_redis()
- Added POST /admin/scoring/recalculate for dynamic weight recalculation
- Added POST /admin/scoring/weights to persist weights to Redis
- Added GET/POST /admin/schedule for beat schedule management
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from adapters.metrics.scoring import compute_neighborhood_stats, recalculate_all_combined_scores
from adapters.queue.gpu_semaphore import GPUSemaphore
from api.auth import verify_admin_access
from api.errors import raise_api_error
from core.enrichment_rerun import (
    MODE_MISSING,
    MODE_STALE_BEFORE,
    STAGES_ALL,
    STAGES_VERDICT_ONLY,
    EnrichmentRerunParams,
    fetch_candidate_rows,
    run_enrichment_rerun,
)
from core.entities import ScoringWeights
from core.photo_gate import photo_gate_kwargs_from_config
from infra.config import get_config
from infra.db import SessionLocal
from infra.logging import get_logger
from infra.redis_client import get_redis
from infra.ui_locale import REDIS_KEY_UI_LOCALE, resolve_active_locale

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_access)])

REDIS_KEY_AI_PAUSED = "workers:ai:paused"
_RESP_400 = {400: {"description": "Bad request"}}
_RESP_500 = {500: {"description": "Internal server error"}}


# ---------------------------------------------------------------------------
# Audit Log Helper
# ---------------------------------------------------------------------------

def log_audit_action(action: str, payload: dict = None):
    from adapters.db.models import AdminAudit
    with SessionLocal() as session:
        try:
            audit = AdminAudit(action=action, payload=payload or {})
            session.add(audit)
            session.commit()
        except Exception as exc:
            logger.error("admin_audit_log_failed", error=str(exc))

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
def admin_health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Worker management
# ---------------------------------------------------------------------------


@router.get("/workers/status")
def workers_status():
    r = get_redis()
    paused = r.exists(REDIS_KEY_AI_PAUSED) > 0  # fixed: was r.get() is not None
    return {"ai_workers_paused": paused}


@router.post("/workers/pause")
def pause_workers():
    r = get_redis()
    r.set(REDIS_KEY_AI_PAUSED, "1")
    logger.info("ai_workers_paused")
    log_audit_action("workers_pause")
    return {"paused": True}


@router.post("/workers/resume")
def resume_workers():
    r = get_redis()
    r.delete(REDIS_KEY_AI_PAUSED)
    logger.info("ai_workers_resumed")
    log_audit_action("workers_resume")
    return {"paused": False}


# ---------------------------------------------------------------------------
# GPU resource control
# ---------------------------------------------------------------------------


class GPUScaleRequest(BaseModel):
    # Lower bound at the schema level: a limit of 0 or negative would wedge the
    # semaphore so no GPU task could ever acquire a slot (BIN-159).
    limit: int = Field(..., ge=1)


@router.post("/gpu/scale")
def set_gpu_limit(payload: GPUScaleRequest):
    cfg = get_config()
    # Upper bound from config: never let an operator scale past what the Ollama
    # server can actually serve concurrently (BIN-159).
    if payload.limit > cfg.gpu.max_semaphore_limit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"gpu limit {payload.limit} exceeds max_semaphore_limit "
                f"{cfg.gpu.max_semaphore_limit}"
            ),
        )
    sem = GPUSemaphore(max_concurrent=cfg.gpu.semaphore_limit)
    sem.scale(payload.limit)
    logger.info("gpu_limit_scaled", new_limit=payload.limit)
    log_audit_action("gpu_scale", {"limit": payload.limit})
    return {"gpu_limit": payload.limit}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@router.post("/scoring/weights")
def set_scoring_weights(weights: ScoringWeights):
    """Persist new scoring weights to Redis for fast retrieval."""
    r = get_redis()
    r.set("scoring:weights", json.dumps(weights.model_dump()))
    logger.info("scoring_weights_updated", **weights.model_dump())
    log_audit_action("set_scoring_weights", weights.model_dump())
    return {"weights": weights.model_dump(), "status": "saved"}


@router.post("/scoring/recalculate", responses=_RESP_500)
def recalculate_scores(weights: Optional[ScoringWeights] = None):
    """Recompute all neighbourhood stats then bulk-update combined scores.

    This is a two-step operation:
      1. Recompute per-neighbourhood z-scores and percentile ranks (stat_score).
      2. Bulk-update combined_score = stat_score * w_stat + ai_score * w_ai.

    Step 2 is a single SQL UPDATE and is effectively instantaneous even for
    millions of rows.
    """
    with SessionLocal() as session:
        try:
            stat_rows = compute_neighborhood_stats(session)
            count = recalculate_all_combined_scores(session, weights)
            session.commit()

            payload = weights.model_dump() if weights else {}
            log_audit_action("recalculate_scores", payload)

            return {
                "stat_rows_updated": stat_rows,
                "combined_rows_updated": count,
                "weights": payload or "config_defaults",
            }
        except Exception as exc:
            session.rollback()
            raise_api_error(logger, "recalculate_scores_failed", exc)


# ---------------------------------------------------------------------------
# Schedule management (Celery beat)
# ---------------------------------------------------------------------------


class ScheduleUpdateRequest(BaseModel):
    platform: str
    interval_minutes: int  # 0 = disable scheduling


@router.get("/schedule")
def get_schedule():
    """Return per-platform scheduling info: interval, last_run, next_run."""
    cfg = get_config()
    r = get_redis()
    now = int(time.time())
    schedules = []

    for name, platform_cfg in cfg.scraping.platforms.items():
        if not platform_cfg.enabled:
            continue

        # Redis override takes precedence
        override = r.get(f"scheduler:interval:{name}")
        interval = int(override) if override is not None else platform_cfg.scrape_interval

        # Read last_run timestamp
        last_run_raw = r.get(f"pipeline:scraper:{name}:last_run")
        last_run = int(last_run_raw) if last_run_raw else None

        # Compute next_run
        next_run = None
        if interval > 0 and last_run:
            next_run = last_run + (interval * 60)
        elif interval > 0:
            next_run = now  # hasn't run yet; would run immediately on beat start

        schedules.append({
            "platform": name,
            "interval_minutes": interval,
            "last_run": last_run,
            "next_run": next_run,
            "estimated": True if next_run else False,
        })

    return {"schedules": schedules}


@router.post("/schedule", responses=_RESP_400)
def update_schedule(payload: ScheduleUpdateRequest):
    """Update the scrape interval for a platform (persisted in Redis).

    Changes take effect when the beat process restarts.
    """
    cfg = get_config()
    platform_names = list(cfg.scraping.platforms.keys())
    if payload.platform not in platform_names:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform '{payload.platform}'. Valid: {platform_names}",
        )

    if payload.interval_minutes < 0:
        raise HTTPException(status_code=400, detail="interval_minutes must be >= 0")

    r = get_redis()
    r.set(f"scheduler:interval:{payload.platform}", str(payload.interval_minutes))
    logger.info(
        "schedule_updated",
        platform=payload.platform,
        interval_minutes=payload.interval_minutes,
    )
    log_audit_action("update_schedule", {"platform": payload.platform, "interval_minutes": payload.interval_minutes})
    return {
        "platform": payload.platform,
        "interval_minutes": payload.interval_minutes,
        "effective": "next_beat_restart",
        "workaround": "Restart Celery beat with: docker-compose restart celery-beat"
    }


# ---------------------------------------------------------------------------
# UI locale preference (BIN-98 / BIN-101)
# ---------------------------------------------------------------------------


class LocaleUpdateRequest(BaseModel):
    """Body for ``POST /admin/locale``."""

    locale: str


def _locale_response(active: str, cfg) -> dict:
    return {
        "locale": active,
        "default": cfg.ui.locale,
        "supported": list(cfg.ui.supported_locales),
    }


@router.get("/locale")
def get_locale():
    """Return active UI locale (Redis override ?? AppConfig ui.locale)."""
    cfg = get_config()
    r = get_redis()
    active = resolve_active_locale(cfg, r)
    return _locale_response(active, cfg)


@router.post("/locale", responses=_RESP_400)
def update_locale(payload: LocaleUpdateRequest):
    """Persist operator UI locale preference in Redis.

    AI free-text generation also reads this active locale (BIN-101); closed
    vocab labels flip via the SPA catalog without touching stored codes.
    """
    cfg = get_config()
    supported = list(cfg.ui.supported_locales)
    if payload.locale not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported locale '{payload.locale}'. Valid: {supported}",
        )

    r = get_redis()
    r.set(REDIS_KEY_UI_LOCALE, payload.locale)
    logger.info("ui_locale_updated", locale=payload.locale)
    log_audit_action("update_locale", {"locale": payload.locale})
    return _locale_response(payload.locale, cfg)


# ---------------------------------------------------------------------------
# AI enrichment backfill / selective re-run (BIN-95)
# ---------------------------------------------------------------------------


class EnrichmentRerunRequest(BaseModel):
    """Body for ``POST /admin/enrichment/rerun``."""

    mode: Literal["missing", "force", "stale_before"] = MODE_MISSING
    stages: Literal["all", "visual+sentiment", "verdict_only"] = STAGES_ALL
    dry_run: bool = False
    city: Optional[str] = None
    neighbourhood_ids: Optional[list[UUID]] = None
    platform: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=5000)
    active_only: bool = True
    stale_before: Optional[datetime] = None

    @model_validator(mode="after")
    def _stale_before_required(self) -> EnrichmentRerunRequest:
        if self.mode == MODE_STALE_BEFORE and self.stale_before is None:
            raise ValueError("stale_before is required when mode=stale_before")
        return self


def _enqueue_ai_enrich(
    *,
    property_id: str,
    image_urls: list,
    description: str,
    stages: str,
) -> None:
    from adapters.queue.tasks import ai_enrich

    ai_enrich.apply_async(
        args=[property_id, image_urls, description],
        kwargs={"stages": stages},
        queue="ai",
    )


def enqueue_enrichment_rerun(
    req: EnrichmentRerunRequest,
    *,
    audit_action: str = "enrichment_rerun",
) -> dict:
    """Select candidates and optionally enqueue ``ai_enrich`` (shared helper).

    Raises ``ValueError`` for bad params and ``RuntimeError`` for unexpected
    failures; route handlers map these to HTTP 400/500.
    """
    params = EnrichmentRerunParams(
        mode=req.mode,
        stages=req.stages,
        dry_run=req.dry_run,
        city=req.city,
        neighbourhood_ids=req.neighbourhood_ids,
        platform=req.platform,
        limit=req.limit,
        active_only=req.active_only,
        stale_before=req.stale_before,
    )
    cfg = get_config()
    gate_kwargs = photo_gate_kwargs_from_config(cfg.scraping.photo_gate, cfg.ai)
    with SessionLocal() as session:
        try:
            rows = fetch_candidate_rows(session, params)
            result = run_enrichment_rerun(
                rows,
                params,
                gate_kwargs=gate_kwargs,
                enqueue_fn=_enqueue_ai_enrich,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error("enrichment_rerun_failed", error=str(exc), action=audit_action)
            raise RuntimeError(str(exc)) from exc

    payload = result.to_dict()
    logger.info("enrichment_rerun_done", **{k: v for k, v in payload.items() if k != "filters"})
    log_audit_action(audit_action, payload)
    return payload


@router.post("/enrichment/rerun", responses={**_RESP_400, **_RESP_500})
def enrichment_rerun(body: EnrichmentRerunRequest):
    """Selective AI enrichment enqueue with mode / filters / stages / dry-run."""
    try:
        return enqueue_enrichment_rerun(body, audit_action="enrichment_rerun")
    except ValueError as exc:
        raise_api_error(logger, "enrichment_rerun_invalid", exc, status_code=400)
    except RuntimeError as exc:
        raise_api_error(logger, "enrichment_rerun_failed", exc)


@router.post("/enrichment/missing", responses={**_RESP_400, **_RESP_500})
def enrich_missing():
    """Enqueue ``ai_enrich`` for active properties that are not yet AI-enriched.

    Thin wrapper around ``/enrichment/rerun`` with ``mode=missing`` (BIN-54/95).
    Response shape stays backward-compatible for the Dashboard one-click button.
    """
    try:
        result = enqueue_enrichment_rerun(
            EnrichmentRerunRequest(mode=MODE_MISSING, stages=STAGES_ALL),
            audit_action="enrich_missing",
        )
    except ValueError as exc:
        raise_api_error(logger, "enrich_missing_invalid", exc, status_code=400)
    except RuntimeError as exc:
        raise_api_error(logger, "enrich_missing_failed", exc)
    return {
        "queued_enrichments": result["queued"],
        "skipped_no_images": result["skipped_no_images"],
        "skipped_too_few_photos": result["skipped_too_few_photos"],
    }


@router.post("/availability/recheck", responses=_RESP_500)
def enqueue_availability_recheck(batch_size: Optional[int] = None):
    """Enqueue one batch of listing URL rechecks (BIN-80)."""
    from adapters.queue.tasks import recheck_listing_availability

    cfg = get_config().scraping.availability_recheck
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="availability_recheck is disabled")

    limit = int(batch_size) if batch_size is not None else int(cfg.batch_size)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="batch_size must be 1..500")

    async_result = recheck_listing_availability.apply_async(
        kwargs={"batch_size": limit},
        queue="scrapers",
    )
    log_audit_action("availability_recheck", {"batch_size": limit, "task_id": async_result.id})
    return {"queued": True, "task_id": async_result.id, "batch_size": limit}


@router.post("/neighbourhoods/access/refresh", responses=_RESP_500)
def enqueue_neighbourhood_access_refresh():
    """Enqueue neighbourhood access_score refresh (BIN-90)."""
    from adapters.queue.tasks import refresh_neighbourhood_access_task

    cfg = get_config().neighbourhood_access
    if cfg.enabled is not True:
        raise HTTPException(status_code=400, detail="neighbourhood_access is disabled")

    async_result = refresh_neighbourhood_access_task.apply_async(queue="scrapers")
    log_audit_action(
        "neighbourhood_access_refresh",
        {"task_id": async_result.id},
    )
    return {"queued": True, "task_id": async_result.id}


@router.post("/neighbourhoods/listing-claims/refresh", responses=_RESP_500)
def enqueue_listing_claim_stats_refresh():
    """Enqueue listing LLM flag aggregation by neighbourhood (BIN-93)."""
    from adapters.queue.tasks import refresh_listing_claim_stats_task

    cfg = get_config().neighbourhood_quality.listing_claim_stats
    if cfg.enabled is not True:
        raise HTTPException(
            status_code=400, detail="listing_claim_stats is disabled"
        )

    async_result = refresh_listing_claim_stats_task.apply_async(queue="scrapers")
    log_audit_action(
        "listing_claim_stats_refresh",
        {"task_id": async_result.id},
    )
    return {"queued": True, "task_id": async_result.id}


# ---------------------------------------------------------------------------
# Deal Verdict Recomputation
# ---------------------------------------------------------------------------

@router.post("/verdict/recompute", responses=_RESP_500)
def recompute_verdicts():
    """Queue ``verdict_only`` AI for rows missing ``meta.deal_verdict``.

    Uses the selective re-run path (no VLM) so existing visual/sentiment scores
    are reused. Requires prior visual+sentiment meta (skipped otherwise).
    """
    from sqlalchemy import text

    from adapters.db.models import MetricsScoring, Property

    cfg = get_config()
    gate_kwargs = photo_gate_kwargs_from_config(cfg.scraping.photo_gate, cfg.ai)
    count = 0
    skipped_prior = 0
    with SessionLocal() as session:
        try:
            query = (
                session.query(Property, MetricsScoring)
                .join(MetricsScoring, Property.id == MetricsScoring.property_id)
                .filter(Property.active.is_(True))
                .filter(text("metrics_scoring.meta->'deal_verdict' IS NULL"))
            )
            rows = query.all()
            params = EnrichmentRerunParams(
                mode="force",
                stages=STAGES_VERDICT_ONLY,
                active_only=True,
            )
            result = run_enrichment_rerun(
                rows,
                params,
                gate_kwargs=gate_kwargs,
                enqueue_fn=_enqueue_ai_enrich,
            )
            count = result.queued
            skipped_prior = result.skipped_missing_prior_enrichment
        except Exception as exc:
            raise_api_error(logger, "verdict_recompute_failed", exc)

    logger.info("verdicts_recompute_queued", count=count, skipped_prior=skipped_prior)
    log_audit_action(
        "recompute_verdicts",
        {"queued": count, "skipped_missing_prior_enrichment": skipped_prior, "stages": STAGES_VERDICT_ONLY},
    )
    return {
        "queued_recomputations": count,
        "skipped_missing_prior_enrichment": skipped_prior,
    }


@router.post("/embeddings/backfill", responses=_RESP_500)
def backfill_embeddings(force: bool = False):
    """Enqueue embed_property for active properties missing an embedding.

    Pass ``force=true`` to clear all embeddings first (e.g. after changing
    embedding model / dimension), then queue a full re-embed.
    """
    from sqlalchemy import text

    from adapters.queue.tasks import embed_property

    count = 0
    with SessionLocal() as session:
        try:
            if force:
                session.execute(text("UPDATE properties SET embedding = NULL"))
                session.commit()
            rows = session.execute(
                text(
                    "SELECT id FROM properties "
                    "WHERE active = true AND embedding IS NULL "
                    "AND (COALESCE(title, '') <> '' OR COALESCE(description, '') <> '')"
                )
            ).fetchall()
            for (prop_id,) in rows:
                embed_property.apply_async(args=[str(prop_id)], queue="ai")
                count += 1
        except Exception as exc:
            raise_api_error(logger, "embeddings_backfill_failed", exc)

    logger.info("embeddings_backfill_queued", count=count, force=force)
    log_audit_action("embeddings_backfill", {"queued": count, "force": force})
    return {"queued_embeddings": count, "force": force}


@router.post("/neighbourhoods/quality/load", responses=_RESP_500)
def load_neighbourhood_quality():
    """Apply curated YAML quality scores onto existing neighbourhoods (BIN-87).

    Reads ``configs/neighbourhood_quality.yaml``. Unknown names are skipped;
    matching rows get ``quality_meta.source = curated``. Does not invent rows.
    """
    from core.neighbourhood_quality_yaml import (
        DEFAULT_YAML_PATH,
        NeighbourhoodQualityYamlError,
        load_curated_neighbourhood_quality,
    )

    try:
        with SessionLocal() as session:
            result = load_curated_neighbourhood_quality(session, DEFAULT_YAML_PATH)
            session.commit()
    except (OSError, NeighbourhoodQualityYamlError) as exc:
        raise_api_error(logger, "neighbourhood_quality_load_failed", exc)
    except Exception as exc:
        raise_api_error(logger, "neighbourhood_quality_load_failed", exc)

    logger.info(
        "neighbourhood_quality_loaded",
        updated=result.updated,
        skipped=result.skipped,
        yaml=str(DEFAULT_YAML_PATH),
    )
    log_audit_action(
        "neighbourhood_quality_load",
        {"updated": result.updated, "skipped": result.skipped},
    )
    return {"updated": result.updated, "skipped": result.skipped}


@router.get("/audit")
def get_audit_log():
    from adapters.db.models import AdminAudit
    with SessionLocal() as session:
        from sqlalchemy import desc
        logs = session.query(AdminAudit).order_by(desc(AdminAudit.performed_at)).limit(100).all()
        return [
            {
                "id": str(log.id),
                "action": log.action,
                "payload": log.payload,
                "performed_at": log.performed_at.isoformat() if log.performed_at else None,
            }
            for log in logs
        ]
