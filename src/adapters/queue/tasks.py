"""Celery task definitions — scraping and AI enrichment.

Changes from original:
- ScraperRegistry.get() replaces hard-coded if/else platform dispatch
- PropertyCandidate Pydantic validation between scraper output and DB
- Real AI scoring (visual + sentiment) replaces hardcoded ai_score = 0.5
- Images downloaded to local storage before VLM call
- asyncio.run() instead of new_event_loop() + set_event_loop()
- All config/Redis imported from centralized infra modules
- Structured logging throughout
- Celery bind=True + self.retry() for proper retry semantics
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import List, Optional

from pydantic import ValidationError

import adapters.scrapers.olx  # noqa: F401
import adapters.scrapers.quintoandar  # Force registry registration  # noqa: F401 — triggers registry
from adapters.ai.client import create_ai_client
from adapters.ai.enrich_pipeline import analyze_visual_and_sentiment
from adapters.ai.image_store import ImageStore
from adapters.ai.prompts import build_sentiment_prompt, build_visual_condition_prompt
from adapters.metrics.scoring import score_single_property
from adapters.queue.celery_app import make_celery
from adapters.queue.gpu_semaphore import GPUSemaphore
from adapters.scrapers.checkpoint_store import CheckpointStore
from adapters.scrapers.listing_description import candidate_listing_url
from adapters.scrapers.registry import ScraperRegistry
from core.dedupe import match_or_create_property
from core.entities import PropertyCandidate
from core.exceptions import CircuitBreakerOpenError
from core.geo_allowlist import passes_geo_allowlist
from core.neighbourhood_assignment import (
    assign_property_neighbourhood,
    assign_property_neighbourhood_by_name,
    load_neighborhood_names,
)
from core.olx_location import (
    apply_reconcile_to_candidate,
    humanize_neighborhood_slugs,
    reconcile_olx_location,
    sync_ai_extract,
)
from core.photo_gate import passes_photo_gate, photo_gate_kwargs_from_config
from infra.config import get_config
from infra.db import SessionLocal
from infra.logging import get_logger
from infra.redis_client import get_redis
from infra.ui_locale import resolve_ai_output_language

logger = get_logger(__name__)

REDIS_KEY_SCRAPERS_PAUSED = "workers:scrapers:paused"
REDIS_KEY_AI_PAUSED = "workers:ai:paused"
REDIS_KEY_SCRAPER_TELEMETRY = "pipeline:scraper:telemetry"
SCRAPER_TELEMETRY_MAX = 100

celery = make_celery()


def _existing_property_description(
    session, *, platform: str, platform_id: str
) -> str:
    """Return stored description for an exact platform id match (may be empty)."""
    from sqlalchemy import text

    row = session.execute(
        text(
            "SELECT COALESCE(description, '') FROM properties "
            "WHERE platform = :platform AND platform_id = :platform_id "
            "LIMIT 1"
        ),
        {"platform": platform, "platform_id": str(platform_id)},
    ).fetchone()
    if not row:
        return ""
    return (row[0] or "").strip()


def _enrich_candidate_description(session, scraper, candidate: PropertyCandidate) -> None:
    """Fill empty candidate.description from detail HTML when DB is also empty.

    Search cards omit body text on QuintoAndar/OLX; detail pages carry remarks /
    ad body. Skip the HTTP round-trip when the DB already has text (BIN-105).
    """
    if (candidate.description or "").strip():
        return
    existing = _existing_property_description(
        session, platform=candidate.platform, platform_id=candidate.platform_id
    )
    if existing:
        candidate.description = existing
        return
    fetch = getattr(scraper, "fetch_description", None)
    if not callable(fetch):
        return
    url = candidate_listing_url(candidate)
    if not url:
        return
    try:
        text = (fetch(url) or "").strip()
    except Exception as exc:  # noqa: BLE001 — never abort scrape for detail enrich
        logger.warning(
            "scrape_description_enrich_error",
            platform=candidate.platform,
            platform_id=candidate.platform_id,
            error=str(exc),
        )
        return
    if text:
        candidate.description = text
        logger.info(
            "scrape_description_enriched",
            platform=candidate.platform,
            platform_id=candidate.platform_id,
            chars=len(text),
        )


# ---------------------------------------------------------------------------
# Scrape task
# ---------------------------------------------------------------------------


def _record_scrape_run(
    r,
    *,
    platform: str,
    processed: int,
    skipped: int,
    errors: int,
    status: str,
    run_id: str | None = None,
) -> str:
    """Persist a durable scrape-run summary for the Activity Log (newest first)."""
    rid = run_id or str(uuid.uuid4())
    payload = {
        "run_id": rid,
        "platform": platform,
        "processed": int(processed),
        "skipped": int(skipped),
        "errors": int(errors),
        "status": status,
        "timestamp": time.time(),
    }
    with r.pipeline() as pipe:
        pipe.lpush(REDIS_KEY_SCRAPER_TELEMETRY, json.dumps(payload))
        pipe.ltrim(REDIS_KEY_SCRAPER_TELEMETRY, 0, SCRAPER_TELEMETRY_MAX - 1)
        pipe.execute()
    return rid


def _normalize_scrape_item(scraper, raw, platform_name: str):
    """Normalize one raw listing; return (candidate|None, outcome).

    outcome is one of: ok, skipped, error, circuit_open.
    """
    try:
        normalized = scraper.normalize(raw)
        return PropertyCandidate(**normalized), "ok"
    except CircuitBreakerOpenError:
        logger.warning("circuit_breaker_open_stopping", platform=platform_name)
        return None, "circuit_open"
    except ValidationError as exc:
        logger.warning(
            "scrape_validation_skipped",
            platform=platform_name,
            errors=exc.error_count(),
        )
        return None, "skipped"
    except Exception as exc:
        import traceback
        logger.error(
            "scrape_normalize_error",
            platform=platform_name,
            error=str(exc),
            trace=traceback.format_exc(),
        )
        return None, "error"


def _enqueue_post_scrape_jobs(candidate, result, *, skip_ai_enrich: bool = False) -> None:
    if result.action == "noop":
        return
    if candidate.image_urls and not skip_ai_enrich:
        ai_enrich.apply_async(
            args=[str(result.property_id), candidate.image_urls, candidate.description or ""],
            queue="ai",
        )
    if (candidate.title or "").strip() or (candidate.description or "").strip():
        embed_property.apply_async(args=[str(result.property_id)], queue="ai")


def _set_property_active(session, property_id: str, active: bool) -> None:
    """Flip ``properties.active`` after ingest (photo gate / reactivation)."""
    from adapters.db.models import Property

    prop = session.get(Property, property_id)
    if prop is not None and prop.active is not active:
        prop.active = active


def _write_scraper_status(
    r,
    status_key: str,
    processed: int,
    skipped: int,
    errors: int,
    status: str,
    proxy: dict | None = None,
) -> None:
    payload = {"processed": processed, "skipped": skipped, "errors": errors, "status": status}
    if proxy:
        payload.update(proxy)
    r.set(status_key, json.dumps(payload), ex=3600)


def _olx_neighborhood_catalog(
    session,
    cities: list[str],
    scraper_config: dict,
) -> list[str]:
    """Merge DB neighbourhood names with OLX YAML slugs for AI/heuristic catalog."""
    names = list(load_neighborhood_names(session, cities))
    # Always include common BH barrios that titles mention but polygons may lack.
    extras = ["Itapoã", "Itapoa", "São Tomáz", "Sao Tomaz", "Ponta da Praia"]
    extra = scraper_config.get("extra") or {}
    slugs = [
        item.get("slug")
        for item in (extra.get("neighborhoods") or [])
        if isinstance(item, dict) and item.get("slug")
    ]
    names.extend(humanize_neighborhood_slugs(slugs))
    names.extend(extras)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _reconcile_olx_candidate(
    candidate: PropertyCandidate,
    *,
    allowed_cities: list[str],
    allowed_states: list[str],
    known_neighborhoods: list[str],
) -> tuple[PropertyCandidate, str]:
    """Run OLX location reconcile; return (candidate, action)."""
    props = candidate.props_json or {}
    result = reconcile_olx_location(
        title=candidate.title,
        description=candidate.description,
        scraped_city=props.get("city"),
        scraped_neighborhood=props.get("neighborhood"),
        scraped_state=props.get("state"),
        scraped_address=candidate.address,
        allowed_cities=allowed_cities,
        allowed_states=allowed_states,
        known_neighborhoods=known_neighborhoods,
        ai_extract=sync_ai_extract,
    )
    apply_reconcile_to_candidate(candidate, result)
    return candidate, result.action


@celery.task(
    name="tasks.scrape_listings",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def scrape_listings(self, platform_name: str, checkpoint: Optional[dict] = None):
    """Scrape a platform, deduplicate each listing, and enqueue AI enrichment.

    Args:
        platform_name: Registered scraper name (e.g. 'quintoandar').
        checkpoint: Optional override checkpoint; otherwise loaded from DB.
    """
    cfg = get_config()

    # Resolve platform config — dataclass → dict for scraper constructor
    platform_cfg = cfg.scraping.platforms.get(platform_name)
    if platform_cfg is None:
        raise ValueError(f"Unknown platform: {platform_name!r}")
    scraper_config = platform_cfg.model_dump()

    session = SessionLocal()
    r = get_redis()
    processed = skipped = errors = 0

    # Check paused flag (TD-06-A)
    if r.exists(REDIS_KEY_SCRAPERS_PAUSED):
        logger.info("scrapers_paused", platform=platform_name)
        raise self.retry(countdown=120, exc=Exception("Scrapers paused due to high AI queue depth"))

    try:
        store = CheckpointStore(session)
        cp = store.get(platform_name) or {}
        if checkpoint is not None:
            cp.update(checkpoint)

        scraper = ScraperRegistry.get(platform_name, scraper_config)
        scraper.start()

        status_key = f"pipeline:scraper:{platform_name}:status"
        proxy_signal = getattr(scraper, "proxy_summary", None) or {}
        _write_scraper_status(
            r, status_key, processed, skipped, errors, "running", proxy=proxy_signal
        )

        geo = cfg.scraping.geo_allowlist
        olx_neighborhood_catalog: list[str] | None = None
        if platform_name == "olx":
            olx_neighborhood_catalog = _olx_neighborhood_catalog(
                session, geo.cities, scraper_config
            )

        with scraper:
            for raw in scraper.fetch_pages(cp):
                candidate, outcome = _normalize_scrape_item(scraper, raw, platform_name)
                if outcome == "circuit_open":
                    break
                if outcome == "skipped":
                    skipped += 1
                    continue
                if outcome == "error":
                    errors += 1
                    continue

                if platform_name == "olx" and olx_neighborhood_catalog is not None:
                    candidate, loc_action = _reconcile_olx_candidate(
                        candidate,
                        allowed_cities=geo.cities,
                        allowed_states=geo.states,
                        known_neighborhoods=olx_neighborhood_catalog,
                    )
                    if loc_action == "out_of_geo":
                        logger.info(
                            "olx_location_out_of_geo",
                            platform=platform_name,
                            platform_id=candidate.platform_id,
                            city=(candidate.props_json or {}).get("city"),
                            address=candidate.address,
                        )
                        skipped += 1
                        continue
                    if loc_action == "corrected":
                        logger.info(
                            "olx_location_corrected",
                            platform=platform_name,
                            platform_id=candidate.platform_id,
                            neighborhood=(candidate.props_json or {}).get(
                                "neighborhood"
                            ),
                            address=candidate.address,
                        )

                allowed, reject_reason = passes_geo_allowlist(
                    candidate,
                    cities=geo.cities,
                    states=geo.states,
                    enabled=geo.enabled,
                )
                if not allowed:
                    logger.info(
                        "scrape_geo_rejected",
                        platform=platform_name,
                        reason=reject_reason,
                        address=getattr(candidate, "address", None),
                    )
                    skipped += 1
                    continue

                photo_ok, photo_reason, photo_count, photo_min = passes_photo_gate(
                    candidate,
                    **photo_gate_kwargs_from_config(cfg.scraping.photo_gate, cfg.ai),
                )

                _enrich_candidate_description(session, scraper, candidate)

                try:
                    result = match_or_create_property(
                        session,
                        candidate,
                        text_threshold=cfg.dedup.text_similarity_threshold,
                        algorithm=cfg.dedup.text_similarity_algorithm,
                        radius_m=cfg.dedup.radius_m,
                        area_tol=cfg.dedup.area_tolerance_m2,
                    )
                    # AD-10 geo stage: assign neighbourhood before AI enqueue
                    if result.action != "noop":
                        props = candidate.props_json or {}
                        if candidate.location is None and props.get("neighborhood"):
                            assign_property_neighbourhood_by_name(
                                session,
                                result.property_id,
                                name=props.get("neighborhood"),
                                city=props.get("city"),
                            )
                        else:
                            assign_property_neighbourhood(session, result.property_id)
                    # BIN-78: keep thin galleries for offline stats, hide from deal feed.
                    _set_property_active(session, result.property_id, photo_ok)
                    if not photo_ok:
                        logger.info(
                            "scrape_photo_gate_deactivated",
                            platform=platform_name,
                            property_id=result.property_id,
                            reason=photo_reason,
                            photo_count=photo_count,
                            required_min=photo_min,
                        )
                    session.commit()
                    _enqueue_post_scrape_jobs(
                        candidate, result, skip_ai_enrich=not photo_ok
                    )
                    processed += 1
                except Exception as exc:
                    session.rollback()
                    logger.error(
                        "scrape_persist_error",
                        platform=platform_name,
                        error=str(exc),
                    )
                    errors += 1

                # Persist checkpoint after every item so we can resume mid-run
                store.set(platform_name, cp)
                _write_scraper_status(
                    r, status_key, processed, skipped, errors, "running", proxy=proxy_signal
                )

        _write_scraper_status(
            r, status_key, processed, skipped, errors, "completed", proxy=proxy_signal
        )

        # Record last-run timestamp for schedule display
        r.set(
            f"pipeline:scraper:{platform_name}:last_run",
            str(int(time.time())),
            ex=86400 * 7,  # keep for 7 days
        )

        logger.info(
            "scrape_completed",
            platform=platform_name,
            processed=processed,
            skipped=skipped,
            errors=errors,
        )
        _record_scrape_run(
            r,
            platform=platform_name,
            processed=processed,
            skipped=skipped,
            errors=errors,
            status="completed",
        )
    except Exception as exc:
        logger.error("scrape_task_error", error=str(exc))
        # Persist checkpoint before retry so we resume from last page
        try:
            store.set(platform_name, cp)
            session.commit()
        except Exception as cp_exc:
            logger.error("checkpoint_save_failed_in_error_handler", error=str(cp_exc))
        try:
            _record_scrape_run(
                r,
                platform=platform_name,
                processed=processed,
                skipped=skipped,
                errors=errors,
                status="failed",
            )
        except Exception as tel_exc:
            logger.error("scrape_telemetry_record_failed", error=str(tel_exc))
        raise
    finally:
        session.close()
        try:
            get_redis().delete(f"pipeline:scraper:{platform_name}:status")
        except Exception as redis_exc:
            logger.error("redis_cleanup_failed", error=str(redis_exc))


# ---------------------------------------------------------------------------
# AI enrichment task
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AI enrichment
# ---------------------------------------------------------------------------


def _enriched_at_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _neighbourhood_verdict_context(session, property_id: str):
    """Return ``(neighborhood_name, neighbourhood_quality)`` for deal verdict."""
    from sqlalchemy import text

    from adapters.db.models import Property as _Prop
    from core.neighbourhood_quality import quality_profile_fields

    neighborhood_name = "Unknown"
    neighbourhood_quality = None
    _prop = session.get(_Prop, property_id)
    if _prop is None:
        return neighborhood_name, neighbourhood_quality

    if _prop.neighborhood_id:
        nb = session.execute(
            text(
                "SELECT name, amenity_score, transit_score, "
                "access_score, safety_score, risk_flags, "
                "quality_meta, quality_notes "
                "FROM neighborhoods WHERE id = :nid"
            ),
            {"nid": _prop.neighborhood_id},
        ).mappings().fetchone()
        if nb:
            neighborhood_name = nb["name"]
            profile = quality_profile_fields(
                {
                    "id": _prop.neighborhood_id,
                    "amenity_score": nb["amenity_score"],
                    "transit_score": nb["transit_score"],
                    "access_score": nb["access_score"],
                    "safety_score": nb["safety_score"],
                    "risk_flags": nb["risk_flags"],
                    "quality_meta": nb["quality_meta"],
                    "quality_notes": nb["quality_notes"],
                }
            )
            profile.pop("id", None)
            neighbourhood_quality = profile

    if neighborhood_name == "Unknown" and _prop.props_json:
        neighborhood_name = _prop.props_json.get("neighborhood", "Unknown")
    return neighborhood_name, neighbourhood_quality


async def _write_deal_verdict(client, session, property_id: str, meta: dict) -> dict:
    """Persist ``meta.deal_verdict`` from existing visual/sentiment (+ nhood)."""
    from adapters.db.models import MetricsScoring

    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
    if ms is None:
        return meta

    updated_meta = dict(ms.meta or {})
    updated_meta.update(meta)
    neighborhood_name, neighbourhood_quality = _neighbourhood_verdict_context(
        session, property_id
    )
    verdict_res = await client.summarize_deal(
        stat_analysis=updated_meta.get("stat_analysis", {}),
        visual=updated_meta.get("visual", {}),
        sentiment=updated_meta.get("sentiment", {}),
        neighborhood_name=neighborhood_name,
        neighbourhood_quality=neighbourhood_quality,
    )
    updated_meta["deal_verdict"] = {
        "verdict": verdict_res.verdict,
        "confidence": verdict_res.confidence,
    }
    updated_meta["enriched_at"] = _enriched_at_now()
    ms.meta = updated_meta
    session.flush()
    return updated_meta


def _persist_ai_scores(session, property_id: str, a_score: float, meta: dict, cfg) -> None:
    """Create/update MetricsScoring ai_score + meta, then refresh geo/stat."""
    from adapters.db.models import MetricsScoring
    from adapters.db.models import Property as _PropTmp
    from adapters.metrics.scoring import (
        _neighbourhood_score_for_property,
        blend_combined_score,
    )
    from core.entities import ScoringWeights

    weights = ScoringWeights(
        stat_weight=getattr(getattr(cfg, "scoring", None), "stat_weight", 0.4),
        ai_weight=getattr(getattr(cfg, "scoring", None), "ai_weight", 0.4),
        neighbourhood_weight=getattr(
            getattr(cfg, "scoring", None), "neighbourhood_weight", 0.2
        ),
    )
    meta = dict(meta)
    meta["enriched_at"] = _enriched_at_now()

    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
    if ms is None:
        ms = MetricsScoring(
            property_id=property_id,
            stat_score=0.0,
            ai_score=a_score,
            combined_score=a_score * weights.ai_weight,
            meta=meta,
        )
        session.add(ms)
    else:
        ms.ai_score = a_score
        ms.meta = meta
        _tmp = session.get(_PropTmp, property_id)
        nhood = (
            _neighbourhood_score_for_property(session, _tmp)
            if _tmp is not None
            else 0.5
        )
        stat = float(ms.stat_score or 0.0)
        ms.combined_score = blend_combined_score(stat, a_score, nhood, weights)
    session.flush()
    assign_property_neighbourhood(session, property_id)
    score_single_property(session, property_id)


@celery.task(
    name="tasks.ai_enrich",
    bind=True,
    max_retries=5,
)
def ai_enrich(
    self,
    property_id: str,
    image_urls: List[str],
    description: str,
    stages: str = "all",
):
    """Download images, run VLM visual + sentiment analysis, persist scores.

    Args:
        property_id: UUID of the property to enrich.
        image_urls: List of remote image URLs from the listing.
        description: Property description text for sentiment analysis.
        stages: ``all`` | ``visual+sentiment`` | ``verdict_only`` (BIN-95).
    """
    from core.enrichment_rerun import (
        STAGES,
        STAGES_ALL,
        STAGES_VERDICT_ONLY,
        STAGES_VISUAL_SENTIMENT,
    )

    if stages not in STAGES:
        stages = STAGES_ALL

    r = get_redis()
    cfg = get_config()

    if r.exists(REDIS_KEY_AI_PAUSED):
        logger.info("ai_enrich_paused", property_id=property_id)
        raise self.retry(countdown=60, exc=Exception("AI workers paused"))

    sem = GPUSemaphore(max_concurrent=cfg.gpu.semaphore_limit)
    acquired = sem.acquire(timeout=30)
    if not acquired:
        logger.warning("ai_enrich_gpu_busy", property_id=property_id)
        raise self.retry(countdown=30, exc=Exception("GPU semaphore timeout"))

    start_time = time.time()
    try:
        image_store = ImageStore()
        client = create_ai_client()

        async def _run_verdict_only():
            async with client.session_context():
                from adapters.db.models import MetricsScoring

                session = SessionLocal()
                try:
                    ms = (
                        session.query(MetricsScoring)
                        .filter_by(property_id=property_id)
                        .one_or_none()
                    )
                    meta = dict(ms.meta or {}) if ms is not None else {}
                    await _write_deal_verdict(client, session, property_id, meta)
                    session.commit()
                finally:
                    session.close()
                return meta.get("visual", {}), meta.get("sentiment", {})

        async def _run_enrichment():
            async with client.session_context():
                paths: List[str] = await image_store.download_images(
                    property_id, image_urls, max_images=cfg.ai.max_images_per_property
                )
                visual_prompt = build_visual_condition_prompt(
                    len(paths), output_language=resolve_ai_output_language()
                )
                sentiment_prompt = build_sentiment_prompt(
                    description,
                    max_chars=cfg.ai.max_description_chars,
                    output_language=resolve_ai_output_language(),
                )
                v_res, s_res = await analyze_visual_and_sentiment(
                    client,
                    paths,
                    description,
                    visual_prompt,
                    sentiment_prompt,
                )
                a_score = (
                    v_res.condition_score * cfg.ai.visual_weight
                    + s_res.sentiment_score * cfg.ai.text_weight
                )
                session = SessionLocal()
                try:
                    from adapters.db.models import MetricsScoring

                    ms = (
                        session.query(MetricsScoring)
                        .filter_by(property_id=property_id)
                        .one_or_none()
                    )
                    meta = dict(ms.meta or {}) if ms is not None else {}
                    meta.update(
                        {
                            "visual": v_res.model_dump(),
                            "sentiment": s_res.model_dump(),
                        }
                    )
                    _persist_ai_scores(session, property_id, a_score, meta, cfg)

                    if stages == STAGES_ALL:
                        await _write_deal_verdict(client, session, property_id, meta)

                    session.commit()
                finally:
                    session.close()

                return a_score, v_res, s_res, paths

        if stages == STAGES_VERDICT_ONLY:
            visual_meta, sentiment_meta = asyncio.run(_run_verdict_only())
            duration = time.time() - start_time
            logger.info(
                "ai_enrich_completed",
                property_id=property_id,
                stages=stages,
                duration_sec=round(duration, 2),
            )
            return {
                "status": "completed",
                "stages": stages,
                "duration": duration,
                "visual": visual_meta,
                "sentiment": sentiment_meta,
            }

        ai_score, visual_result, sentiment_result, local_paths = asyncio.run(
            _run_enrichment()
        )

        duration = time.time() - start_time
        with r.pipeline() as pipe:
            pipe.lpush(
                "pipeline:ai:telemetry",
                json.dumps(
                    {
                        "property_id": property_id,
                        "duration": duration,
                        "timestamp": time.time(),
                        "stages": stages,
                    }
                ),
            )
            pipe.ltrim("pipeline:ai:telemetry", 0, 999)
            pipe.execute()

        logger.info(
            "ai_enrich_completed",
            property_id=property_id,
            stages=stages,
            ai_score=round(ai_score, 4),
            condition_score=visual_result.condition_score,
            sentiment_score=sentiment_result.sentiment_score,
            images_processed=len(local_paths),
            duration_sec=round(duration, 2),
            skipped_verdict=stages == STAGES_VISUAL_SENTIMENT,
        )
        return {
            "status": "completed",
            "ai_score": ai_score,
            "duration": duration,
            "stages": stages,
        }

    except Exception as exc:
        logger.error("ai_enrich_error", property_id=property_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60)
    finally:
        sem.release()


# ---------------------------------------------------------------------------
# Embedding task (semantic search) — no GPU semaphore
# ---------------------------------------------------------------------------


@celery.task(
    name="tasks.embed_property",
    bind=True,
    max_retries=5,
)
def embed_property(self, property_id: str):
    """Generate and store a pgvector embedding for a property's title+description."""
    from sqlalchemy import text

    from adapters.ai.embeddings import build_embedding_text, vector_literal

    cfg = get_config()
    r = get_redis()

    if r.exists(REDIS_KEY_AI_PAUSED):
        logger.info("embed_property_paused", property_id=property_id)
        raise self.retry(countdown=60, exc=Exception("AI workers paused"))

    try:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT title, description FROM properties WHERE id = CAST(:id AS uuid)"
                ),
                {"id": property_id},
            ).mappings().first()
            if not row:
                logger.warning("embed_property_missing", property_id=property_id)
                return {"status": "missing"}

            text_in = build_embedding_text(
                row["title"],
                row["description"],
                cfg.ai.max_description_chars,
            )
            if not text_in:
                logger.info("embed_property_empty_text", property_id=property_id)
                return {"status": "skipped_empty"}

            client = create_ai_client()

            async def _run():
                async with client:
                    return await client.embed(text_in)

            embedding = asyncio.run(_run())
            literal = vector_literal(embedding)
            session.execute(
                text(
                    "UPDATE properties SET embedding = CAST(:emb AS vector) "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"emb": literal, "id": property_id},
            )
            session.commit()

        logger.info("embed_property_completed", property_id=property_id, dims=len(embedding))
        return {"status": "completed", "dims": len(embedding)}
    except Exception as exc:
        logger.error("embed_property_error", property_id=property_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60)


# ---------------------------------------------------------------------------
# Watchlist Evaluation task
# ---------------------------------------------------------------------------


@celery.task(name="tasks.evaluate_watchlist_alerts", bind=True)
def evaluate_watchlist_alerts(self):
    """
    Periodic task: compare current prices against watchlist thresholds.
    Should run every N minutes via Celery beat.
    """
    from sqlalchemy import text

    from adapters.notify import get_notifiers
    from adapters.notify.base import PriceDropAlert

    logger = get_logger("evaluate_watchlist_alerts")

    with SessionLocal() as session:
        # Get all watchlist entries with current price
        rows = session.execute(text("""
            SELECT
                w.id,
                w.property_id,
                w.min_drop_pct,
                w.last_notified_price,
                pl.price AS current_price,
                pl.listing_type,
                pl.platform,
                p.props_json->>'title' AS title
            FROM watchlist w
            JOIN properties p ON p.id = w.property_id
            JOIN LATERAL (
                SELECT price, listing_type, platform
                FROM property_listings
                WHERE property_id = w.property_id
                ORDER BY price ASC
                LIMIT 1
            ) pl ON true
        """)).fetchall()

        notifiers = get_notifiers()

        for row in rows:
            reference = row.last_notified_price or row.current_price
            if reference is None or reference <= 0:
                continue

            drop_pct = (float(reference) - float(row.current_price)) / float(reference) * 100

            if drop_pct >= row.min_drop_pct:
                alert = PriceDropAlert(
                    property_id=str(row.property_id),
                    title=row.title or "Property",
                    listing_type=row.listing_type,
                    platform=row.platform,
                    old_price=float(reference),
                    new_price=float(row.current_price),
                    drop_pct=drop_pct,
                )
                for notifier in notifiers:
                    try:
                        notifier.send(alert)
                    except Exception as exc:
                        logger.error("notifier_error", notifier=type(notifier).__name__, error=str(exc))

                # Update last_notified_price
                session.execute(
                    text("UPDATE watchlist SET last_notified_price = :price WHERE id = :id"),
                    {"price": row.current_price, "id": row.id}
                )

        session.commit()
        logger.info("watchlist_evaluation_complete", evaluated=len(rows))


@celery.task(name="tasks.send_price_drop_alert")
def send_price_drop_alert(alert_dict: dict):
    import json

    from adapters.notify import get_notifiers
    from adapters.notify.base import PriceDropAlert
    from infra.redis_client import get_redis

    r = get_redis()
    property_id = alert_dict.get("property_id")

    # Alert Debouncing (TD-05-D)
    debounce_key = f"alerts:debounce:{property_id}"
    if r.exists(debounce_key):
        logger.info("alert_debounced", property_id=property_id)
        return

    alert = PriceDropAlert(**alert_dict)

    # Store in Redis for frontend Alerts Panel (TD-05-B)
    alert_list_key = "alerts:price_drops"
    r.lpush(alert_list_key, json.dumps(alert_dict))
    r.ltrim(alert_list_key, 0, 99)  # Keep last 100 alerts

    for notifier in get_notifiers():
        try:
            notifier.send(alert)
        except Exception as exc:
            logger.error("notifier_error", notifier=type(notifier).__name__, error=str(exc))

    # Set debounce key to prevent spam
    r.setex(debounce_key, 3600, "1")


# ---------------------------------------------------------------------------
# Queue Monitoring
# ---------------------------------------------------------------------------


@celery.task(name="tasks.monitor_queues")
def monitor_queues():
    """Monitor queue depths and dynamically throttle scrapers."""
    from infra.redis_client import get_redis
    r = get_redis()

    # Threshold could be configurable
    BATCH_THRESHOLD = 50

    # LLEN gives pending items in Celery list queues (when using redis broker)
    ai_len = r.llen("ai")

    logger.info("queue_monitor", ai_queue=ai_len)

    if ai_len > BATCH_THRESHOLD:
        if not r.exists(REDIS_KEY_SCRAPERS_PAUSED):
            logger.warning("queue_monitor_pause_scrapers", ai_queue=ai_len, threshold=BATCH_THRESHOLD)
            r.set(REDIS_KEY_SCRAPERS_PAUSED, "1")
    else:
        if r.exists(REDIS_KEY_SCRAPERS_PAUSED):
            logger.info("queue_monitor_resume_scrapers", ai_queue=ai_len, threshold=BATCH_THRESHOLD)
            r.delete(REDIS_KEY_SCRAPERS_PAUSED)


@celery.task(name="tasks.snapshot_pipeline_metrics")
def snapshot_pipeline_metrics():
    """Persist a pipeline metrics snapshot and prune past retention (BIN-61)."""
    from adapters.metrics.pipeline_snapshots import snapshot_and_prune
    from infra.config import get_config
    from infra.db import SessionLocal

    retention = 7
    try:
        retention = int(get_config().pipeline_metrics.retention_days)
    except Exception:
        retention = 7

    with SessionLocal() as session:
        return snapshot_and_prune(session, retention_days=retention)


@celery.task(bind=True, name="tasks.send_daily_digest")
def send_daily_digest(self):
    """Batch process queued email digest alerts and send them."""
    r = get_redis()
    alerts_json = r.lrange("alerts:email_digest", 0, -1)
    if not alerts_json:
        return {"sent": 0}

    r.delete("alerts:email_digest")

    import json
    alerts = []
    for item in alerts_json:
        try:
            alerts.append(json.loads(item))
        except Exception:
            pass

    if not alerts:
        return {"sent": 0}

    from adapters.notify.email_notifier import EmailNotifier
    notifier = EmailNotifier()
    notifier.send_batch(alerts)
    return {"sent": len(alerts)}


@celery.task(bind=True, name="tasks.send_top_deals_digest")
def send_top_deals_digest(self):
    """Select top new deals (AD-12) and deliver via the notifier registry (AD-9).

    Distinct from ``send_daily_digest`` (price-drop email batching).
    Gated by ``alerts.top_deals.enabled``; subscriber is ``auth.principal_id`` (AD-11).
    """
    from datetime import datetime, timezone

    from adapters.notify import get_notifiers
    from adapters.notify.base import TopDealsDigest
    from core.top_deals_digest import select_top_deals, top_deals_rule

    cfg = get_config()
    top_deals = cfg.alerts.top_deals
    if not top_deals.enabled:
        logger.info("top_deals_digest_skipped", reason="disabled")
        return {"status": "skipped", "sent": 0}

    score_target = top_deals.score_target
    with SessionLocal() as session:
        properties = select_top_deals(
            session,
            lookback_hours=top_deals.lookback_hours,
            min_combined_score=top_deals.min_combined_score,
            limit=top_deals.limit,
            score_target=score_target,
        )

    if not properties:
        logger.info("top_deals_digest_empty")
        return {"status": "empty", "sent": 0}

    digest = TopDealsDigest(
        principal_id=cfg.auth.principal_id,
        generated_at=datetime.now(timezone.utc),
        properties=properties,
        rule=top_deals_rule(score_target),
    )
    for notifier in get_notifiers():
        try:
            notifier.send_digest(digest)
        except Exception as exc:
            logger.error(
                "top_deals_digest_notifier_error",
                notifier=type(notifier).__name__,
                error=str(exc),
            )

    logger.info(
        "top_deals_digest_sent",
        principal_id=digest.principal_id,
        count=len(properties),
    )
    return {"status": "sent", "sent": len(properties)}


# ---------------------------------------------------------------------------
# Listing availability recheck (BIN-80)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    name="tasks.recheck_listing_availability",
    max_retries=2,
    default_retry_delay=60,
)
def recheck_listing_availability(self, batch_size: int | None = None):
    """Probe stale active listing URLs and soft-deactivate unavailable ones.

    Never flips ``active=false`` on ``unknown`` (proxy / Cloudflare / timeout).
    Property rows deactivate only when zero active listings remain.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from adapters.scrapers.availability import (
        AvailabilityStatus,
        check_listing,
        deactivate_listing_and_maybe_property,
    )
    from adapters.scrapers.http_client import create_scraper_http_client

    cfg = get_config()
    recheck = cfg.scraping.availability_recheck
    if not recheck.enabled:
        logger.info("availability_recheck_skipped", reason="disabled")
        return {"status": "skipped", "checked": 0}

    limit = int(batch_size) if batch_size is not None else int(recheck.batch_size)
    stale_hours = int(recheck.stale_after_hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)

    checked = 0
    unavailable = 0
    available = 0
    unknown = 0
    properties_deactivated = 0

    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT id, property_id, platform, listing_type, url "
                "FROM property_listings "
                "WHERE active = true "
                "AND url IS NOT NULL AND url <> '' "
                "AND (last_seen IS NULL OR last_seen < :cutoff) "
                "ORDER BY last_seen ASC NULLS FIRST "
                "LIMIT :limit"
            ),
            {"cutoff": cutoff, "limit": limit},
        ).fetchall()

        if not rows:
            logger.info("availability_recheck_empty")
            return {
                "status": "empty",
                "checked": 0,
                "unavailable": 0,
                "available": 0,
                "unknown": 0,
            }

        client = create_scraper_http_client(
            timeout=float(recheck.request_timeout_sec),
            follow_redirects=True,
            headers={"User-Agent": cfg.scraping.user_agent},
        )
        try:
            for row in rows:
                listing_id, _property_id, platform, listing_type, url = row
                checked += 1
                result = check_listing(
                    str(platform),
                    str(url),
                    listing_type=str(listing_type) if listing_type else None,
                    client=client,
                    timeout=float(recheck.request_timeout_sec),
                )

                if result.status == AvailabilityStatus.UNAVAILABLE:
                    summary = deactivate_listing_and_maybe_property(
                        session, str(listing_id)
                    )
                    unavailable += 1
                    if summary.get("property_deactivated"):
                        properties_deactivated += 1
                    logger.info(
                        "listing_unavailable",
                        listing_id=str(listing_id),
                        platform=str(platform),
                        listing_type=str(listing_type),
                        reason=result.reason,
                        property_deactivated=summary.get("property_deactivated"),
                    )
                elif result.status == AvailabilityStatus.AVAILABLE:
                    available += 1
                    session.execute(
                        text(
                            "UPDATE property_listings SET last_seen = :now "
                            "WHERE id = :id"
                        ),
                        {
                            "now": datetime.now(timezone.utc),
                            "id": str(listing_id),
                        },
                    )
                    logger.info(
                        "listing_still_available",
                        listing_id=str(listing_id),
                        platform=str(platform),
                        reason=result.reason,
                    )
                else:
                    unknown += 1
                    logger.info(
                        "recheck_unknown",
                        listing_id=str(listing_id),
                        platform=str(platform),
                        reason=result.reason,
                    )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("availability_recheck_failed", error=str(exc))
            raise
        finally:
            client.close()

    payload = {
        "status": "ok",
        "checked": checked,
        "unavailable": unavailable,
        "available": available,
        "unknown": unknown,
        "properties_deactivated": properties_deactivated,
    }
    logger.info("availability_recheck_complete", **payload)
    return payload


# ---------------------------------------------------------------------------
# Neighbourhood OSM amenity density (BIN-88)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    name="tasks.refresh_neighbourhood_amenities",
    max_retries=2,
    default_retry_delay=120,
)
def refresh_neighbourhood_amenities(self, batch_size: int | None = None):
    """Refresh ``neighborhoods.amenity_score`` from OSM POIs (geojson or Overpass)."""
    from adapters.geo.amenity_refresh import refresh_neighbourhood_amenities as run_refresh

    cfg = get_config()
    osm = cfg.neighbourhood_quality.osm_amenities
    if not osm.enabled:
        logger.info("amenity_refresh_skipped", reason="disabled")
        return {"status": "skipped", "updated": 0}

    limit = int(batch_size) if batch_size is not None else int(osm.batch_size)
    with SessionLocal() as session:
        result = run_refresh(
            session,
            mode=osm.mode,
            poi_geojson_path=osm.poi_geojson_path,
            buffer_m=float(osm.buffer_m),
            category_targets=dict(osm.category_targets),
            batch_size=limit,
            overpass_url=osm.overpass_url,
            request_timeout_sec=float(osm.request_timeout_sec),
            rate_limit_per_minute=float(osm.rate_limit_per_minute),
            cache_dir=osm.cache_dir,
            cache_ttl_hours=float(osm.cache_ttl_hours),
        )
    return result.as_dict()


# ---------------------------------------------------------------------------
# Neighbourhood access / travel-time to hubs (BIN-90)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    name="tasks.refresh_neighbourhood_access",
    max_retries=2,
    default_retry_delay=60,
)
def refresh_neighbourhood_access_task(self):
    """Fill ``access_score`` + ``quality_meta.access`` from YAML hubs (OSRM/haversine)."""
    from adapters.geo.access_refresh import refresh_neighbourhood_access

    cfg = get_config().neighbourhood_access
    if cfg.enabled is not True:
        logger.info("neighbourhood_access_skipped", reason="disabled")
        return {"status": "skipped", "processed": 0, "updated": 0, "skipped": 0, "errors": 0}

    with SessionLocal() as session:
        try:
            stats = refresh_neighbourhood_access(session, cfg)
        except Exception as exc:
            logger.error("neighbourhood_access_failed", error=str(exc))
            raise

    payload = {"status": "ok", **stats}
    logger.info("neighbourhood_access_complete", **payload)
    return payload


# ---------------------------------------------------------------------------
# Listing LLM sentiment flag aggregates by neighbourhood (BIN-93)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    name="tasks.refresh_listing_claim_stats",
    max_retries=2,
    default_retry_delay=60,
)
def refresh_listing_claim_stats_task(self):
    """Fill nested ``quality_meta.listing_claim_stats`` from listing sentiment flags."""
    from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

    cfg = get_config().neighbourhood_quality.listing_claim_stats
    if cfg.enabled is not True:
        logger.info("listing_claim_stats_skipped", reason="disabled")
        return {
            "status": "skipped",
            "processed": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }

    with SessionLocal() as session:
        try:
            stats = refresh_listing_claim_stats(session, cfg)
        except Exception as exc:
            logger.error("listing_claim_stats_failed", error=str(exc))
            raise

    payload = {"status": "ok", **stats}
    logger.info("listing_claim_stats_complete", **payload)
    return payload
