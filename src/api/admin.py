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
from api.auth import verify_api_key
from core.entities import ScoringWeights
from infra.config import get_config
from infra.db import get_session
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_api_key)])


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
    paused = r.exists("workers:ai:paused") > 0  # fixed: was r.get() is not None
    return {"ai_workers_paused": paused}


@router.post("/workers/pause")
def pause_workers():
    r = get_redis()
    r.set("workers:ai:paused", "1")
    logger.info("ai_workers_paused")
    return {"paused": True}


@router.post("/workers/resume")
def resume_workers():
    r = get_redis()
    r.delete("workers:ai:paused")
    logger.info("ai_workers_resumed")
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
    return {"weights": weights.model_dump(), "status": "saved"}


@router.post("/scoring/recalculate")
def recalculate_scores(weights: Optional[ScoringWeights] = None):
    """Recompute all neighbourhood stats then bulk-update combined scores.

    This is a two-step operation:
      1. Recompute per-neighbourhood z-scores and percentile ranks (stat_score).
      2. Bulk-update combined_score = stat_score * w_stat + ai_score * w_ai.

    Step 2 is a single SQL UPDATE and is effectively instantaneous even for
    millions of rows.
    """
    session = next(get_session())
    try:
        stat_rows = compute_neighborhood_stats(session)
        count = recalculate_all_combined_scores(session, weights)
        session.commit()
        return {
            "stat_rows_updated": stat_rows,
            "combined_rows_updated": count,
            "weights": weights.model_dump() if weights else "config_defaults",
        }
    except Exception as exc:
        session.rollback()
        logger.error("recalculate_scores_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        session.close()


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
        })

    return {"schedules": schedules}


@router.post("/schedule")
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
    return {
        "platform": payload.platform,
        "interval_minutes": payload.interval_minutes,
        "note": "Changes take effect when the beat process restarts.",
    }
