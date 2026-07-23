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
    try:
        cfg = get_config()
        r = get_redis()
        digest_mode = bool(getattr(cfg.alerts, "digest_mode", False))

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

    if digest_mode:
        schedule["send-daily-digest"] = {
            "task": "tasks.send_daily_digest",
            "schedule": crontab(hour=8, minute=0),
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

    # Task routes (TD-06-C)
    celery_app.conf.task_routes = {
        'tasks.scrape_listings': {'queue': 'scrapers'},
        'tasks.ai_enrich': {'queue': 'ai'},
        'tasks.embed_property': {'queue': 'ai'},
        'tasks.send_price_drop_alert': {'queue': 'scrapers'},
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
    except Exception as e:
        logger.error(f"Error in task failure handler: {e}")


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
    except Exception as e:
        logger.error(f"Error in task revoked handler: {e}")
