import logging
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_revoked

from infra.config import get_config
from infra.redis_client import get_redis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Beat schedule builder
# ---------------------------------------------------------------------------


def build_beat_schedule() -> dict:
    """Build a Celery beat schedule from the app config.

    Reads per-platform ``scrape_interval`` (minutes) from the YAML config and
    checks Redis for runtime overrides (``scheduler:interval:<platform>``).
    Platforms with interval <= 0 or ``enabled: false`` are excluded.

    Returns a dict suitable for ``celery_app.conf.beat_schedule``.
    """
    schedule: dict = {}
    digest_mode = False
    top_deals_enabled = False
    top_deals_cfg = None
    cfg = None
    try:
        cfg = get_config()
        r = get_redis()
        digest_mode = bool(getattr(cfg.alerts, "digest_mode", False))
        top_deals_cfg = getattr(cfg.alerts, "top_deals", None)
        top_deals_enabled = (
            getattr(top_deals_cfg, "enabled", False) is True
            if top_deals_cfg is not None
            else False
        )

        for name, platform_cfg in cfg.scraping.platforms.items():
            if not platform_cfg.enabled:
                continue

            # Redis override takes precedence over config
            override = r.get(f"scheduler:interval:{name}")
            interval = int(override) if override is not None else platform_cfg.scrape_interval

            if interval <= 0:
                continue

            schedule[f"scrape-{name}"] = {
                "task": "tasks.scrape_listings",
                "schedule": interval * 60,  # convert minutes to seconds (Celery periodic task)
                "args": [name],
                "kwargs": {},
            }
    except Exception:
        logger.warning("beat_schedule_build_failed", exc_info=True)

    # Always-on maintenance jobs (independent of scraper platform config)
    schedule["evaluate-watchlist-alerts"] = {
        "task": "tasks.evaluate_watchlist_alerts",
        "schedule": 300.0,
    }

    schedule["monitor-queues"] = {
        "task": "tasks.monitor_queues",
        "schedule": 60.0,
    }

    # Pipeline metric snapshots (Dashboard history). Interval from YAML; default 30s.
    snapshot_interval = 30.0
    try:
        pipeline_cfg = getattr(cfg, "pipeline_metrics", None) if cfg is not None else None
        if pipeline_cfg is not None:
            raw_interval = getattr(pipeline_cfg, "snapshot_interval_sec", 30)
            if isinstance(raw_interval, (int, float)) and not isinstance(raw_interval, bool):
                snapshot_interval = float(raw_interval)
    except (TypeError, ValueError):
        snapshot_interval = 30.0
    if snapshot_interval > 0:
        schedule["snapshot-pipeline-metrics"] = {
            "task": "tasks.snapshot_pipeline_metrics",
            "schedule": snapshot_interval,
        }

    if digest_mode:
        schedule["send-daily-digest"] = {
            "task": "tasks.send_daily_digest",
            "schedule": crontab(hour=8, minute=0),
        }

    if top_deals_enabled and top_deals_cfg is not None:
        schedule["send-top-deals-digest"] = {
            "task": "tasks.send_top_deals_digest",
            "schedule": crontab(
                hour=int(getattr(top_deals_cfg, "crontab_hour", 8)),
                minute=int(getattr(top_deals_cfg, "crontab_minute", 0)),
                day_of_week=str(getattr(top_deals_cfg, "crontab_day_of_week", "0")),
            ),
        }

    # Soft-deactivate dead source URLs (BIN-80). Explicit ``is True`` so MagicMock
    # stubs in unit tests do not accidentally enable the job.
    recheck_cfg = None
    try:
        scraping = getattr(cfg, "scraping", None) if cfg is not None else None
        recheck_cfg = getattr(scraping, "availability_recheck", None) if scraping else None
    except Exception:
        recheck_cfg = None
    if recheck_cfg is not None and getattr(recheck_cfg, "enabled", False) is True:
        interval_min = int(getattr(recheck_cfg, "interval_minutes", 360) or 0)
        if interval_min > 0:
            schedule["recheck-listing-availability"] = {
                "task": "tasks.recheck_listing_availability",
                "schedule": interval_min * 60,
            }

    # OSM amenity density for neighbourhoods (BIN-88). Explicit ``is True`` so
    # MagicMock stubs in unit tests do not accidentally enable the job.
    osm_cfg = None
    try:
        nq = getattr(cfg, "neighbourhood_quality", None) if cfg is not None else None
        osm_cfg = getattr(nq, "osm_amenities", None) if nq is not None else None
    except Exception:
        osm_cfg = None
    if osm_cfg is not None and getattr(osm_cfg, "enabled", False) is True:
        interval_hours = float(getattr(osm_cfg, "interval_hours", 168) or 0)
        if interval_hours > 0:
            schedule["refresh-neighbourhood-amenities"] = {
                "task": "tasks.refresh_neighbourhood_amenities",
                "schedule": interval_hours * 3600,
            }

    # Neighbourhood access / travel-time to hubs (BIN-90). Explicit ``is True`` so
    # MagicMock stubs in unit tests do not accidentally enable the job.
    access_cfg = None
    try:
        access_cfg = getattr(cfg, "neighbourhood_access", None) if cfg is not None else None
    except Exception:
        access_cfg = None
    if access_cfg is not None and getattr(access_cfg, "enabled", False) is True:
        access_interval = int(getattr(access_cfg, "interval_minutes", 1440) or 0)
        if access_interval > 0:
            schedule["refresh-neighbourhood-access"] = {
                "task": "tasks.refresh_neighbourhood_access",
                "schedule": access_interval * 60,
            }

    # Listing LLM flag aggregates by neighbourhood (BIN-93). Explicit ``is True``.
    listing_claim_cfg = None
    try:
        nq = getattr(cfg, "neighbourhood_quality", None) if cfg is not None else None
        listing_claim_cfg = (
            getattr(nq, "listing_claim_stats", None) if nq is not None else None
        )
    except Exception:
        listing_claim_cfg = None
    if listing_claim_cfg is not None and getattr(
        listing_claim_cfg, "enabled", False
    ) is True:
        claim_interval = float(getattr(listing_claim_cfg, "interval_hours", 24) or 0)
        if claim_interval > 0:
            schedule["refresh-listing-claim-stats"] = {
                "task": "tasks.refresh_listing_claim_stats",
                "schedule": claim_interval * 3600,
            }

    return schedule


def make_celery() -> Celery:
    """Create and configure Celery app."""
    celery_app = Celery("real_estate_scraper")

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Configurações básicas do Celery
    celery_app.conf.update(
        broker_url=redis_url,
        result_backend=redis_url,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        # Configurações de retry
        task_reject_on_worker_lost=True,
        task_track_started=True,
    )

    # Configuração de retries para tarefas críticas
    celery_app.conf.task_default_retry_delay = 30
    celery_app.conf.task_default_max_retries = 3

    # Task routes (TD-06-C). Workers only consume `scrapers` and `ai` — anything
    # left on the default `celery` queue never runs (BIN-76: empty Dashboard history).
    celery_app.conf.task_routes = {
        'tasks.scrape_listings': {'queue': 'scrapers'},
        'tasks.ai_enrich': {'queue': 'ai'},
        'tasks.embed_property': {'queue': 'ai'},
        'tasks.send_price_drop_alert': {'queue': 'scrapers'},
        'tasks.snapshot_pipeline_metrics': {'queue': 'scrapers'},
        'tasks.monitor_queues': {'queue': 'scrapers'},
        'tasks.evaluate_watchlist_alerts': {'queue': 'scrapers'},
        'tasks.send_daily_digest': {'queue': 'scrapers'},
        'tasks.send_top_deals_digest': {'queue': 'scrapers'},
        'tasks.recheck_listing_availability': {'queue': 'scrapers'},
        'tasks.refresh_neighbourhood_amenities': {'queue': 'scrapers'},
        'tasks.refresh_neighbourhood_access': {'queue': 'scrapers'},
        'tasks.refresh_listing_claim_stats': {'queue': 'scrapers'},
    }

    # Build and apply the beat schedule from config
    celery_app.conf.beat_schedule = build_beat_schedule()

    return celery_app


# Sinal para tratamento de falhas em tarefas
@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    """Handle task failures with detailed logging."""
    try:
        logger.error(
            "Task failed",
            extra={
                "task_id": task_id,
                "task_name": sender.name if sender else "unknown",
                "exception": str(exception),
                "traceback": traceback,
                "args": kwargs.get("args", []),
                "kwargs": kwargs.get("kwargs", {}),
            },
        )
    except Exception:
        logger.exception("Error in task failure handler")


# Sinal para tratamento de tarefas revogadas
@task_revoked.connect
def handle_task_revoked(sender=None, request=None, terminated=None, signum=None, expired=None, **kwargs):
    """Handle revoked tasks."""
    try:
        logger.warning(
            "Task revoked",
            extra={
                "task_id": request.id if request else "unknown",
                "task_name": sender.name if sender else "unknown",
                "terminated": terminated,
                "signum": signum,
                "expired": expired,
            },
        )
    except Exception:
        logger.exception("Error in task revoked handler")
