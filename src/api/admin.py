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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from adapters.metrics.scoring import compute_neighborhood_stats, recalculate_all_combined_scores
from adapters.queue.gpu_semaphore import GPUSemaphore
from api.auth import verify_admin_access
from core.entities import ScoringWeights
from infra.config import get_config
from infra.db import SessionLocal
from infra.logging import get_logger
from infra.redis_client import get_redis

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
    limit: int


@router.post("/gpu/scale")
def set_gpu_limit(payload: GPUScaleRequest):
    sem = GPUSemaphore()
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
            logger.error("recalculate_scores_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))


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
# Deal Verdict Recomputation
# ---------------------------------------------------------------------------

@router.post("/verdict/recompute", responses=_RESP_500)
def recompute_verdicts():
    """Query properties where metrics_scoring.meta->'deal_verdict' IS NULL
    and dispatch ai_enrich for each.
    """
    from sqlalchemy import text

    from adapters.db.models import MetricsScoring, Property
    from adapters.queue.tasks import ai_enrich

    count = 0
    with SessionLocal() as session:
        try:
            # Find properties that need deal verdict recomputation
            query = session.query(Property, MetricsScoring).join(
                MetricsScoring, Property.id == MetricsScoring.property_id
            ).filter(
                text("metrics_scoring.meta->'deal_verdict' IS NULL")
            )

            for prop, ms in query:
                image_urls = prop.image_urls or []
                description = prop.description or ""
                ai_enrich.delay(str(prop.id), image_urls, description)
                count += 1
        except Exception as exc:
            logger.error("verdict_recompute_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    logger.info("verdicts_recompute_queued", count=count)
    log_audit_action("recompute_verdicts", {"queued": count})
    return {"queued_recomputations": count}


@router.post("/embeddings/backfill", responses=_RESP_500)
def backfill_embeddings():
    """Enqueue embed_property for active properties missing an embedding."""
    from sqlalchemy import text

    from adapters.queue.tasks import embed_property

    count = 0
    with SessionLocal() as session:
        try:
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
            logger.error("embeddings_backfill_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    logger.info("embeddings_backfill_queued", count=count)
    log_audit_action("embeddings_backfill", {"queued": count})
    return {"queued_embeddings": count}


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
