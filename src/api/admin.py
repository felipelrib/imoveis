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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from adapters.metrics.scoring import compute_neighborhood_stats, recalculate_all_combined_scores
from adapters.queue.gpu_semaphore import GPUSemaphore
from api.auth import verify_admin_access
from api.errors import raise_api_error
from api.schemas import (
    BackfillControlResponse,
    BackfillStartResponse,
    BackfillStatusResponse,
)
from core.backfill_runner import (
    BackfillControl,
    BackfillLease,
    BackfillState,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    MigrationGate,
    build_status_snapshot,
    pending_control_requests,
    supervisor_prefix,
)
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
from infra.limiter import limiter
from infra.logging import get_logger
from infra.redis_client import get_redis
from infra.ui_locale import REDIS_KEY_UI_LOCALE, resolve_active_locale

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_access)])

REDIS_KEY_AI_PAUSED = "workers:ai:paused"
_RESP_400 = {400: {"description": "Bad request"}}
_RESP_409 = {409: {"description": "Conflict"}}
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


# ---------------------------------------------------------------------------
# Cloud enrichment backfill control plane (v0.13-s1.5)
#
# A control plane, never a second runner: these routes read and *request*, and
# nothing else. They never enrich, never query the domain database, never spawn
# a process and never beat the runner's ``:active`` heartbeat (a beating
# heartbeat blocks migrate-primary.sh). The one database write they do make is
# the AD-6 audit row every mutation records via ``log_audit_action`` — which
# opens a session and commits, and swallows its own failure, so a mutation can
# be applied with no audit row behind it. Every Redis key access goes through
# the story-1.3 primitives in ``core.backfill_runner``, so the key layout lives
# in exactly one place (AD-13).
#
# "Start" is a *request*: the runner needs GEMINI_API_KEY, which by design lives
# only in the operator's host shell (NFR-3), and driving a multi-day pass from a
# request-serving process would contradict AD-4/AD-10. A host-side
# ``scripts/dev/backfill_gemma.py --serve`` supervisor consumes the request and
# launches the ordinary ``--continuous`` run under the shared lease and pacer.
# ---------------------------------------------------------------------------


_BACKFILL_START_SOURCE = "admin-api"


@dataclass(frozen=True)
class _BackfillPrimitives:
    """The story-1.3 control objects, all bound to the runner's own Redis keys."""

    lease: BackfillLease
    control: BackfillControl
    budget: DailyBudget
    checkpoint: Checkpoint
    heartbeat: Heartbeat
    migration_gate: MigrationGate
    supervisor_heartbeat: Heartbeat
    daily_limit: int
    pacing: dict


def _backfill_primitives() -> _BackfillPrimitives:
    """The single construction site for every backfill control key.

    Scattering ``get_redis()`` + key names across handlers is how an API drifts
    into a second control path; every route below goes through this helper.
    """
    cfg = get_config().backfill
    redis = get_redis()  # one handle for the whole backfill control plane
    prefix = cfg.redis_prefix
    return _BackfillPrimitives(
        # The API never acquires this lease — it only asks who holds it — so the
        # owner string is provenance for a refusal message, nothing more.
        lease=BackfillLease(
            redis,
            prefix=prefix,
            ttl_seconds=int(cfg.lease_ttl_seconds),
            owner=_BACKFILL_START_SOURCE,
        ),
        control=BackfillControl(redis, prefix=prefix),
        budget=DailyBudget(
            redis, prefix=prefix, daily_limit=int(cfg.daily_request_budget)
        ),
        checkpoint=Checkpoint(redis, prefix=prefix),
        heartbeat=Heartbeat(redis, prefix=prefix),
        migration_gate=MigrationGate(redis, prefix=prefix),
        supervisor_heartbeat=Heartbeat(redis, prefix=supervisor_prefix(prefix)),
        daily_limit=int(cfg.daily_request_budget),
        pacing={
            "requests_per_property": int(cfg.requests_per_property),
            "rpm_limit": int(cfg.rpm_limit),
            "concurrency": int(cfg.concurrency),
            "tpm_limit": int(cfg.tpm_limit),
        },
    )


def _backfill_snapshot(prims: _BackfillPrimitives) -> BackfillStatusResponse:
    """Read-only status, aggregated by the core (never re-derived here).

    ``ledger=None`` deliberately: the quarantined count is an
    O(properties-ever-attempted) ``HGETALL`` + sort over ``<prefix>:attempts``
    (~26k fields on a full pass), and this snapshot backs an endpoint story 1.6
    polls every few seconds with no rate limit. ``quarantined`` is therefore null
    on the wire; the CLI's one-shot ``--status`` counts it in its own print-out.
    """
    return BackfillStatusResponse.model_validate(
        build_status_snapshot(
            lease=prims.lease,
            control=prims.control,
            budget=prims.budget,
            checkpoint=prims.checkpoint,
            heartbeat=prims.heartbeat,
            migration_gate=prims.migration_gate,
            ledger=None,
            supervisor_heartbeat=prims.supervisor_heartbeat,
            daily_limit=prims.daily_limit,
            pacing=prims.pacing,
        )
    )


def _snapshot_after_mutation(
    prims: _BackfillPrimitives, *, action: str
) -> Optional[BackfillStatusResponse]:
    """Best-effort status to attach to an *already applied* mutation.

    The snapshot is ~10 further Redis reads. Taken inside the mutation's own
    ``try``, one blip on any of them turned an applied pause into "Internal
    server error" and the operator concluded the pause had not taken — the
    single worst thing this surface can get wrong. So the mutation's outcome is
    the response code, and a failed read only nulls ``status``.
    """
    try:
        return _backfill_snapshot(prims)
    except Exception as exc:  # noqa: BLE001 - the mutation itself succeeded
        logger.warning(
            "backfill_status_after_mutation_failed", action=action, error=str(exc)
        )
        return None


def _format_seconds(seconds: float) -> str:
    total = int(max(0.0, float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _held_for(acquired_at: Optional[str]) -> str:
    """How long the current holder has had the lease, in human terms."""
    if not acquired_at:
        return "held since an unknown time"
    try:
        since = datetime.fromisoformat(acquired_at)
    except ValueError:
        return "held since an unknown time"
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - since).total_seconds()
    return f"held for {_format_seconds(elapsed)}"


def _lease_conflict_detail(
    holder: dict, *, state: Any = None, lease_ttl_seconds: Optional[int] = None
) -> str:
    """Name the live run, so a 409 tells the operator what to do about it.

    The advice has to match the state being refused, or it sends the operator at
    an action that cannot unblock them:

    * **paused** — "pause it" is nonsense; the run is already holding, and the
      way forward is ``POST /admin/backfill/resume``, not another start.
    * **stale holder** (last seen longer ago than two renewal intervals) — the
      process may well be gone, and if it is, nothing the operator does reaches
      it: the lease self-expires, so say that rather than naming a command.
      The threshold is deliberately two intervals and not half the TTL: the
      renewer runs at ``ttl/3`` and the ``last_seen`` write it does is
      best-effort — it swallows its own failure — so a *single* dropped meta
      write ages the stamp to ``2*ttl/3`` under a perfectly healthy run, and at
      ``ttl/2`` that run would be reported as probably dead. For the same
      reason the wording keeps both readings open instead of promising an
      expiry that a live renewer keeps pushing out. An *unknown* last seen is
      not this reading at all: a healthy multi-day run can hold the lease with
      no ``last_seen`` ever written, so it falls through to the advice below.
    * otherwise — a healthy run: pause it, or stop it from the host CLI.

    Every variant still names the owner and how long the lease has been held.
    """
    age = holder.get("seconds_since_last_seen")
    seen = "last seen unknown" if age is None else f"last seen {_format_seconds(age)} ago"
    identity = (
        f"owner {holder.get('owner') or 'unknown'}, "
        f"{_held_for(holder.get('acquired_at'))}, {seen}"
    )
    ttl = int(lease_ttl_seconds or 0)
    stale = ttl > 0 and age is not None and float(age) > (2.0 * ttl) / 3.0
    if stale:
        return (
            f"A backfill run already holds the lease ({identity}), so it has not "
            f"been seen for longer than expected: it may be dead, or it may be "
            f"running with a failing provenance write. If it is dead nothing "
            f"needs stopping — the lease expires on its own within "
            f"{_format_seconds(ttl)} of the last renewal. Check the host before "
            f"waiting it out, then start again."
        )
    if state is not None and str(getattr(state, "value", state)) == BackfillState.PAUSED.value:
        return (
            f"A backfill run already holds the lease and is paused ({identity}). "
            f"Resume it (POST /admin/backfill/resume) rather than starting "
            f"another — a start cannot take a lease this run still holds."
        )
    return (
        f"A backfill run already holds the lease ({identity}). Pause it, or stop "
        f"it from the host CLI (scripts/dev/backfill_gemma.py --stop), before "
        f"starting another."
    )


def _audit_applied(action: str, payload: dict[str, Any]) -> None:
    """Audit an outcome that is already decided — and never change it.

    ``log_audit_action`` opens a DB session, and only the *commit* is guarded
    inside it: an unreachable database raises out of ``SessionLocal()`` itself.
    Called bare, that turns an applied pause into "Internal server error" while
    the runner is quietly halting, and a correct 409 naming the live run into a
    generic 500 — the two things this surface most has to get right, lost to
    bookkeeping on a mutation that already happened. The audit stays best-effort
    (the helper already swallows its own commit failures) and its loss is
    logged, never charged to the caller.
    """
    try:
        log_audit_action(action, payload)
    except Exception as exc:  # noqa: BLE001 - the outcome is already decided
        logger.warning("backfill_audit_failed", action=action, error=str(exc))


def _audit_lease(holder: Optional[dict]) -> dict[str, Any]:
    if not holder:
        return {}
    return {
        "lease_owner": holder.get("owner"),
        "lease_acquired_at": holder.get("acquired_at"),
        "lease_seconds_since_last_seen": holder.get("seconds_since_last_seen"),
    }


@router.get(
    "/backfill/status",
    response_model=BackfillStatusResponse,
    responses=_RESP_500,
)
def backfill_status():
    """Control state, lease holder, today's budget and the resume checkpoint.

    Read-only: every figure comes from the same Redis keys the CLI's
    ``--status`` prints, and the domain database is never queried. No
    coverage/throughput/ETA — that is story 1.4's, and it is computed from the
    database, not from the runner's control state. ``quarantined`` is null on
    purpose: counting it scans every property ever attempted, and this endpoint
    is polled.
    """
    try:
        return _backfill_snapshot(_backfill_primitives())
    except Exception as exc:
        raise_api_error(logger, "backfill_status_failed", exc)


@router.post(
    "/backfill/start",
    response_model=BackfillStartResponse,
    status_code=202,
    responses={**_RESP_409, **_RESP_500},
)
@limiter.limit("30/minute")
def backfill_start(request: Request):
    """Record a start request for the host-side ``--serve`` supervisor.

    202, never 200: nothing has started yet when this returns. A run that
    already holds the lease is refused with 409 rather than queuing a request
    that a second runner would only be refused for anyway.
    """
    try:
        prims = _backfill_primitives()
        holder = prims.lease.holder()
        if holder is not None:
            logger.info("backfill_start_refused", owner=holder.get("owner"))
            _audit_applied("backfill_start_refused", _audit_lease(holder))
            # The refusal is decided by the lease alone; the state only chooses
            # the wording. A blip on this one extra read must not cost the
            # operator the 409 that names the run they are competing with.
            try:
                state = prims.control.state()
            except Exception as exc:  # noqa: BLE001 - wording only
                logger.warning("backfill_conflict_state_read_failed", error=str(exc))
                state = None
            raise HTTPException(
                status_code=409,
                detail=_lease_conflict_detail(
                    holder,
                    state=state,
                    lease_ttl_seconds=prims.lease.ttl_seconds,
                ),
            )

        # Ordering is the whole point here. Read what is pending *first*, then
        # record the start, then drop the stale levels: clearing an operator's
        # pause before the start is recorded means a Redis failure in between
        # loses the pause with no start to show for it, and recording the start
        # after the response is built means telling a caller it failed when it
        # did not.
        discarded = pending_control_requests(prims.control)
        requested = prims.control.request_start(_BACKFILL_START_SOURCE)
        try:
            # A fresh run must not inherit a pause/stop aimed at an earlier one —
            # the CLI does exactly this on start-up. Saying what was dropped is
            # the difference between clearing a stale level and swallowing it.
            if discarded:
                prims.control.clear_requests()
            runner_present = bool(prims.supervisor_heartbeat.is_active())
            payload = {
                "already_requested": requested["already_requested"],
                "requested_at": requested["requested_at"],
                "runner_present": runner_present,
                "discarded_requests": discarded,
            }
            logger.info("backfill_start_requested", **payload)
            # Deliberately *not* best-effort, unlike the refusal/pause/resume
            # audits above: those record an outcome the operator must be told
            # about even if the trail is lost, while this one queues a multi-day
            # cloud spend that AD-6 says must be recorded. An unauditable start
            # is rolled back below rather than fired unrecorded.
            log_audit_action("backfill_start", payload)
            return BackfillStartResponse(requested=True, **payload)
        except Exception:
            # The caller is about to be told this failed, so the queued request
            # must not survive to launch a multi-day cloud run nobody asked for.
            # Best effort, and never allowed to mask the original failure.
            if not requested["already_requested"]:
                try:
                    prims.control.clear_start()
                except Exception as cleanup_exc:  # noqa: BLE001 - key self-expires
                    logger.warning(
                        "backfill_start_rollback_failed", error=str(cleanup_exc)
                    )
            raise
    except HTTPException:
        raise
    except Exception as exc:
        raise_api_error(logger, "backfill_start_failed", exc)


@router.post(
    "/backfill/pause",
    response_model=BackfillControlResponse,
    responses=_RESP_500,
)
@limiter.limit("30/minute")
def backfill_pause(request: Request):
    """Ask a running backfill to hold after its in-flight rows drain.

    Also **withdraws a pending start request** when no run holds the lease:
    pause is a *level*, and a run launching from that request clears pause/stop
    at start-up, so "Start then Pause" would otherwise run unpaused with the
    operator's second command silently void. ``cleared_start=true`` says the
    queued start was cancelled instead of a doomed pause being left behind.
    """
    try:
        prims = _backfill_primitives()
        # Only when nothing holds the lease: under a live run the start request
        # is not what would be paused, and cancelling it would discard an intent
        # aimed at the *next* run.
        cancellable_start = (
            prims.control.start_request() is not None and prims.lease.holder() is None
        )
        prims.control.request_pause()
        if cancellable_start:
            # Everything past the pause is bookkeeping on an *applied* mutation:
            # a blip here must not become a 500 telling the operator their pause
            # failed while it sits set in Redis. And the delete's own answer is
            # what gets reported — a supervisor polling every couple of seconds
            # may have consumed the request since it was read, in which case
            # nothing was cancelled and saying otherwise is a lie the operator
            # would act on.
            try:
                cancellable_start = bool(prims.control.clear_start())
            except Exception as exc:  # noqa: BLE001 - the pause itself is set
                logger.warning("backfill_pause_clear_start_failed", error=str(exc))
                cancellable_start = False
        logger.info("backfill_pause_requested", cleared_start=cancellable_start)
        _audit_applied("backfill_pause", {"cleared_start": cancellable_start})
    except Exception as exc:
        raise_api_error(logger, "backfill_pause_failed", exc)
    return BackfillControlResponse(
        action="pause",
        cleared_start=cancellable_start,
        status=_snapshot_after_mutation(prims, action="pause"),
    )


@router.post(
    "/backfill/resume",
    response_model=BackfillControlResponse,
    responses=_RESP_500,
)
@limiter.limit("30/minute")
def backfill_resume(request: Request):
    """Release a pause — and any pending stop, which is what "resume" means."""
    try:
        prims = _backfill_primitives()
        had_stop = prims.control.should_stop()
        # ``request_resume`` clears pause *and* stop; going through it (rather
        # than clearing the pause key here) keeps the API and the CLI on
        # literally the same code path.
        prims.control.request_resume()
        logger.info("backfill_resume_requested", cleared_stop=had_stop)
        _audit_applied("backfill_resume", {"cleared_stop": had_stop})
    except Exception as exc:
        raise_api_error(logger, "backfill_resume_failed", exc)
    return BackfillControlResponse(
        action="resume",
        cleared_stop=had_stop,
        status=_snapshot_after_mutation(prims, action="resume"),
    )


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
