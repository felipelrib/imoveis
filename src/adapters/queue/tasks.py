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
import dataclasses
import json
from typing import List, Optional

from pydantic import ValidationError

import adapters.scrapers.quintoandar  # Force registry registration
from adapters.ai.client import create_ai_client
from adapters.ai.image_store import ImageStore
from adapters.ai.prompts import build_sentiment_prompt, build_visual_condition_prompt
from adapters.metrics.scoring import score_single_property
from adapters.queue.celery_app import make_celery
from adapters.queue.gpu_semaphore import GPUSemaphore
from adapters.scrapers.checkpoint_store import CheckpointStore
from adapters.scrapers.registry import ScraperRegistry
from core.dedupe import match_or_create_property
from core.entities import PropertyCandidate
from infra.config import get_config
from infra.db import SessionLocal
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)
celery = make_celery()


# ---------------------------------------------------------------------------
# Scrape task
# ---------------------------------------------------------------------------


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
    platform_cfg_obj = cfg.platforms.get(platform_name)
    if platform_cfg_obj is None:
        raise ValueError(f"Platform '{platform_name}' not found in config.")
    platform_cfg = dataclasses.asdict(platform_cfg_obj)

    session = SessionLocal()
    try:
        store = CheckpointStore(session)
        cp = store.get(platform_name) or {}
        if checkpoint is not None:
            cp.update(checkpoint)

        scraper = ScraperRegistry.get(platform_name, platform_cfg)
        scraper.start()

        processed = skipped = errors = 0
        r = get_redis()
        status_key = f"pipeline:scraper:{platform_name}:status"

        with scraper:
            for raw in scraper.fetch_pages(cp):
                try:
                    normalized = scraper.normalize(raw)
                    candidate = PropertyCandidate(**normalized)
                except ValidationError as exc:
                    logger.warning(
                        "scrape_validation_skipped",
                        platform=platform_name,
                        errors=exc.error_count(),
                    )
                    skipped += 1
                    continue
                except Exception as exc:
                    import traceback

                    logger.error(
                        "scrape_normalize_error",
                        platform=platform_name,
                        error=str(exc),
                        trace=traceback.format_exc(),
                    )
                    errors += 1
                    continue

                try:
                    result = match_or_create_property(session, candidate)
                    session.commit()

                    # Enqueue AI enrichment if images are present and property
                    # is new or updated (not a noop duplicate)
                    if candidate.image_urls and result.action != "noop":
                        ai_enrich.apply_async(
                            args=[
                                str(result.property_id),
                                candidate.image_urls,
                                candidate.description or "",
                            ],
                            queue="ai",
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

                # Update telemetry
                r.set(
                    status_key,
                    json.dumps(
                        {
                            "processed": processed,
                            "skipped": skipped,
                            "errors": errors,
                            "status": "running",
                        }
                    ),
                    ex=3600,
                )

        # Mark as completed
        r.set(
            status_key,
            json.dumps(
                {
                    "processed": processed,
                    "skipped": skipped,
                    "errors": errors,
                    "status": "completed",
                }
            ),
            ex=3600,
        )

        # Record last-run timestamp for schedule display
        import time as _ts

        r.set(
            f"pipeline:scraper:{platform_name}:last_run",
            str(int(_ts.time())),
            ex=86400 * 7,  # keep for 7 days
        )

        logger.info(
            "scrape_completed",
            platform=platform_name,
            processed=processed,
            skipped=skipped,
            errors=errors,
        )
    except Exception as exc:
        # Persist checkpoint before retry so we resume from last page
        try:
            store.set(platform_name, cp)
            session.commit()
        except Exception:
            pass
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# AI enrichment task
# ---------------------------------------------------------------------------


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
):
    """Download images, run VLM visual + sentiment analysis, persist scores.

    Args:
        property_id: UUID of the property to enrich.
        image_urls: List of remote image URLs from the listing.
        description: Property description text for sentiment analysis.
    """
    r = get_redis()
    cfg = get_config()

    # Respect admin pause flag
    if r.exists("workers:ai:paused"):
        logger.info("ai_enrich_paused", property_id=property_id)
        raise self.retry(countdown=60, exc=Exception("AI workers paused"))

    sem = GPUSemaphore()
    acquired = sem.acquire(timeout=30)
    if not acquired:
        logger.warning("ai_enrich_gpu_busy", property_id=property_id)
        raise self.retry(countdown=30, exc=Exception("GPU semaphore timeout"))

    import time

    start_time = time.time()
    client = None
    try:
        # --- Image pipeline ------------------------------------------------
        image_store = ImageStore()
        local_paths: List[str] = asyncio.run(image_store.download_images(property_id, image_urls, max_images=5))

        # --- Build prompts -------------------------------------------------
        visual_prompt = build_visual_condition_prompt(len(local_paths))
        sentiment_prompt = build_sentiment_prompt(description)

        # --- AI inference --------------------------------------------------
        client = create_ai_client()

        async def run_ai():
            v = await client.analyze_visuals(local_paths, visual_prompt)
            t = await client.analyze_text(description, sentiment_prompt)
            return v, t

        visual_result, sentiment_result = asyncio.run(run_ai())

        # Weighted blend: visual condition 60%, location sentiment 40%
        ai_score = visual_result.condition_score * 0.6 + sentiment_result.sentiment_score * 0.4

        # --- Persist -------------------------------------------------------
        from adapters.db.models import MetricsScoring  # local import avoids circular

        session = SessionLocal()
        try:
            ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
            meta = dict(ms.meta or {}) if ms is not None else {}
            meta.update(
                {
                    "visual": visual_result.model_dump(),
                    "sentiment": sentiment_result.model_dump(),
                }
            )
            if ms is None:
                ms = MetricsScoring(
                    property_id=property_id,
                    stat_score=0.0,
                    ai_score=ai_score,
                    combined_score=ai_score * cfg.scoring.ai_weight,
                    meta=meta,
                )
                session.add(ms)
            else:
                ms.ai_score = ai_score
                ms.meta = meta
                # Recompute combined using existing stat_score
                stat = float(ms.stat_score or 0.0)
                ms.combined_score = stat * cfg.scoring.stat_weight + ai_score * cfg.scoring.ai_weight
            session.flush()

            # Recompute neighbourhood-relative stat_score for this property
            score_single_property(session, property_id)
            session.commit()
        finally:
            session.close()

        duration = time.time() - start_time
        r.lpush(
            "pipeline:ai:telemetry",
            json.dumps(
                {
                    "property_id": property_id,
                    "duration": duration,
                    "timestamp": time.time(),
                }
            ),
        )
        r.ltrim("pipeline:ai:telemetry", 0, 999)  # Keep last 1000

        logger.info(
            "ai_enrich_completed",
            property_id=property_id,
            ai_score=round(ai_score, 4),
            condition_score=visual_result.condition_score,
            sentiment_score=sentiment_result.sentiment_score,
            images_processed=len(local_paths),
            duration_sec=round(duration, 2),
        )
        return {"status": "completed", "ai_score": ai_score, "duration": duration}

    except Exception as exc:
        logger.error("ai_enrich_error", property_id=property_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60)
    finally:
        if client is not None:
            asyncio.run(client.close())
        sem.release()
