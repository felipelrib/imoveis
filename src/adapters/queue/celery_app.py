"""Celery application factory.

Changes from original:
- Reads redis_url from centralized config (no more hardcoded dict param)
- make_celery() takes no arguments
"""
from __future__ import annotations

from celery import Celery

from infra.config import get_config


def make_celery() -> Celery:
    """Build and return a configured Celery application."""
    cfg = get_config()
    celery = Celery("re_ingest", broker=cfg.redis_url, backend=cfg.redis_url)
    celery.conf.update(
        task_routes={
            "tasks.scrape_*": {"queue": "scrapers"},
            "tasks.ai_*": {"queue": "ai"},
        },
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        worker_prefetch_multiplier=1,
        task_acks_late=True,          # only ack after successful completion
        task_reject_on_worker_lost=True,
    )
    return celery

app = make_celery()
