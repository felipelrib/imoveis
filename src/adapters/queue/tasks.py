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
from adapters.ai.image_store import ImageStore
from adapters.ai.prompts import build_sentiment_prompt, build_visual_condition_prompt
from adapters.metrics.scoring import score_single_property
from adapters.queue.celery_app import make_celery
from core.geo_allowlist import passes_geo_allowlist
from adapters.queue.gpu_semaphore import GPUSemaphore
from adapters.scrapers.checkpoint_store import CheckpointStore
from adapters.scrapers.registry import ScraperRegistry
from core.dedupe import match_or_create_property
from core.entities import PropertyCandidate
from core.exceptions import CircuitBreakerOpenError
from core.neighbourhood_assignment import assign_property_neighbourhood
from infra.config import get_config
from infra.db import SessionLocal
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)

REDIS_KEY_SCRAPERS_PAUSED = "workers:scrapers:paused"
REDIS_KEY_AI_PAUSED = "workers:ai:paused"
REDIS_KEY_SCRAPER_TELEMETRY = "pipeline:scraper:telemetry"
SCRAPER_TELEMETRY_MAX = 100

celery = make_celery()


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


def _enqueue_post_scrape_jobs(candidate, result) -> None:
    if result.action == "noop":
        return
    if candidate.image_urls:
        ai_enrich.apply_async(
            args=[str(result.property_id), candidate.image_urls, candidate.description or ""],
            queue="ai",
        )
    if (candidate.title or "").strip() or (candidate.description or "").strip():
        embed_property.apply_async(args=[str(result.property_id)], queue="ai")


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

                geo = cfg.scraping.geo_allowlist
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
                        assign_property_neighbourhood(session, result.property_id)
                    session.commit()
                    _enqueue_post_scrape_jobs(candidate, result)
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
    if r.exists(REDIS_KEY_AI_PAUSED):
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
        image_store = ImageStore()
        client = create_ai_client()

        async def _run_enrichment():
            async with client.session_context():
                # --- Image pipeline ------------------------------------------------
                paths: List[str] = await image_store.download_images(
                    property_id, image_urls, max_images=cfg.ai.max_images_per_property
                )

                # --- Build prompts -------------------------------------------------
                visual_prompt = build_visual_condition_prompt(len(paths))
                sentiment_prompt = build_sentiment_prompt(description, max_chars=cfg.ai.max_description_chars)

                # --- AI inference (Parallelized) ---
                import asyncio
                v_res, s_res = await asyncio.gather(
                    client.analyze_visuals(paths, visual_prompt),
                    client.analyze_text(description, sentiment_prompt)
                )

                # Weighted blend: visual condition 60%, location sentiment 40%
                a_score = v_res.condition_score * cfg.ai.visual_weight + s_res.sentiment_score * cfg.ai.text_weight

                # --- Persist -------------------------------------------------------
                from adapters.db.models import MetricsScoring  # local import avoids circular
                session = SessionLocal()
                try:
                    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
                    meta = dict(ms.meta or {}) if ms is not None else {}
                    meta.update(
                        {
                            "visual": v_res.model_dump(),
                            "sentiment": s_res.model_dump(),
                        }
                    )

                    stat_weight = getattr(getattr(cfg, "scoring", None), "stat_weight", 0.5)
                    ai_weight = getattr(getattr(cfg, "scoring", None), "ai_weight", 0.5)

                    if ms is None:
                        ms = MetricsScoring(
                            property_id=property_id,
                            stat_score=0.0,
                            ai_score=a_score,
                            combined_score=a_score * ai_weight,
                            meta=meta,
                        )
                        session.add(ms)
                    else:
                        ms.ai_score = a_score
                        ms.meta = meta
                        # Recompute combined using existing stat_score
                        stat = float(ms.stat_score or 0.0)
                        ms.combined_score = stat * stat_weight + a_score * ai_weight
                    session.flush()

                    # AD-10 geo stage: refresh spatial neighbourhood before scoring
                    assign_property_neighbourhood(session, property_id)

                    # Recompute neighbourhood-relative stat_score for this property
                    score_single_property(session, property_id)

                    # --- Deal verdict synthesis ---
                    ms = session.query(MetricsScoring).filter_by(property_id=property_id).one_or_none()
                    updated_meta = dict(ms.meta or {}) if ms is not None else {}
                    stat_analysis = updated_meta.get("stat_analysis", {})
                    neighborhood_name = "Unknown"
                    from adapters.db.models import Property as _Prop
                    _prop = session.get(_Prop, property_id)
                    if _prop is not None:
                        if _prop.neighborhood_id:
                            from sqlalchemy import text
                            nb = session.execute(
                                text("SELECT name FROM neighborhoods WHERE id = :nid"),
                                {"nid": _prop.neighborhood_id}
                            ).fetchone()
                            if nb:
                                neighborhood_name = nb.name

                        if neighborhood_name == "Unknown" and _prop.props_json:
                            neighborhood_name = _prop.props_json.get("neighborhood", "Unknown")

                    verdict_res = await client.summarize_deal(
                        stat_analysis=stat_analysis,
                        visual=meta.get("visual", {}),
                        sentiment=meta.get("sentiment", {}),
                        neighborhood_name=neighborhood_name,
                    )
                    if ms is not None:
                        updated_meta = dict(ms.meta or {})
                        updated_meta["deal_verdict"] = {
                            "verdict": verdict_res.verdict,
                            "confidence": verdict_res.confidence,
                        }
                        ms.meta = updated_meta
                        session.flush()

                    session.commit()
                finally:
                    session.close()

                return a_score, v_res, s_res, paths

        ai_score, visual_result, sentiment_result, local_paths = asyncio.run(_run_enrichment())

        duration = time.time() - start_time
        with r.pipeline() as pipe:
            pipe.lpush(
                "pipeline:ai:telemetry",
                json.dumps(
                    {
                        "property_id": property_id,
                        "duration": duration,
                        "timestamp": time.time(),
                    }
                ),
            )
            pipe.ltrim("pipeline:ai:telemetry", 0, 999)  # Keep last 1000
            pipe.execute()

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
    from core.top_deals_digest import TOP_DEALS_RULE, select_top_deals

    cfg = get_config()
    top_deals = cfg.alerts.top_deals
    if not top_deals.enabled:
        logger.info("top_deals_digest_skipped", reason="disabled")
        return {"status": "skipped", "sent": 0}

    with SessionLocal() as session:
        properties = select_top_deals(
            session,
            lookback_hours=top_deals.lookback_hours,
            min_combined_score=top_deals.min_combined_score,
            limit=top_deals.limit,
        )

    if not properties:
        logger.info("top_deals_digest_empty")
        return {"status": "empty", "sent": 0}

    digest = TopDealsDigest(
        principal_id=cfg.auth.principal_id,
        generated_at=datetime.now(timezone.utc),
        properties=properties,
        rule=TOP_DEALS_RULE,
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
