"""System status and control API — used by the GUI control panel."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from api.schemas import PipelineResponse, SystemStatusResponse
from infra.config import get_config
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

REDIS_KEY_AI_PAUSED = "workers:ai:paused"


# ---------------------------------------------------------------------------
# Health / status aggregation
# ---------------------------------------------------------------------------


def _check_db_and_counts() -> tuple[dict, int, int]:
    try:
        import sqlalchemy

        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(sqlalchemy.text("SELECT 1"))
            total = session.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM properties")
            ).scalar()
            enriched = session.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM metrics_scoring WHERE ai_score > 0")
            ).scalar()
        return {"status": "ok"}, (total or 0), (enriched or 0)
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}, 0, 0


def _check_redis() -> dict:
    try:
        get_redis().ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_ollama() -> dict:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{get_config().ai.ollama_url}/api/tags")
        models = [m["name"] for m in (r.json().get("models") or [])]
        return {"status": "ok", "models": models}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_workers() -> dict:
    try:
        from adapters.queue.celery_app import make_celery
        app = make_celery()
        i = app.control.inspect()
        ping_res = i.ping()
        if not ping_res:
            return {"status": "error", "detail": "No workers responding"}
        return {"status": "ok", "nodes": list(ping_res.keys())}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/status", response_model=SystemStatusResponse)
async def system_status() -> Dict[str, Any]:
    """Return health of all system components — polled by the GUI dashboard."""
    r = get_redis()
    ai_paused = r.exists(REDIS_KEY_AI_PAUSED) > 0
    db_status, total_props, enriched = _check_db_and_counts()

    return {
        "database": db_status,
        "redis": _check_redis(),
        "ollama": await _check_ollama(),
        "workers": _check_workers(),
        "ai_workers_paused": ai_paused,
        "stats": {
            "total_properties": total_props,
            "enriched_properties": enriched,
        },
    }


# ---------------------------------------------------------------------------
# Ollama control (start serve from API — useful when not using start.ps1)
# ---------------------------------------------------------------------------


@router.get("/ollama/status")
async def ollama_status():
    """Check ollama connectivity."""
    return await _check_ollama()


# ---------------------------------------------------------------------------
# Pipeline Tracking
# ---------------------------------------------------------------------------


@router.get("/pipeline", response_model=PipelineResponse)
def system_pipeline() -> Dict[str, Any]:
    """Return live status of the ingestion pipeline (queues and active tasks)."""
    r = get_redis()
    return {
        "queues": _pipeline_queue_lengths(r),
        "scrapers_status": _scraper_pipeline_statuses(r),
        "ai_metrics": _ai_pipeline_metrics(r.lrange("pipeline:ai:telemetry", 0, -1)),
        "recent_scrape_runs": _recent_scrape_runs(r),
    }


def _pipeline_queue_lengths(redis) -> dict:
    return {"scrapers": redis.llen("scrapers"), "ai": redis.llen("ai")}


def _scraper_pipeline_statuses(redis) -> dict:
    import json

    statuses = {}
    for platform in get_config().scraping.platforms:
        raw = redis.get(f"pipeline:scraper:{platform}:status")
        try:
            statuses[platform] = json.loads(raw) if raw else {"status": "idle"}
        except (TypeError, json.JSONDecodeError):
            statuses[platform] = {"status": "idle"}
    return statuses


def _recent_scrape_runs(redis) -> list:
    """Newest-first scrape run summaries from Redis telemetry."""
    import json

    runs = []
    for item in redis.lrange("pipeline:scraper:telemetry", 0, -1) or []:
        try:
            data = json.loads(item)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("run_id"):
            runs.append(data)
    return runs


def _ai_pipeline_metrics(telemetry: list) -> dict:
    import json
    import time

    durations, recent_count = [], 0
    now = time.time()
    for item in telemetry:
        try:
            data = json.loads(item)
            durations.append(data["duration"])
            recent_count += now - data["timestamp"] <= 300
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return {
        "throughput_per_min": round(recent_count / 5.0, 1),
        "avg_duration_sec": round(sum(durations) / len(durations), 2) if durations else 0,
        "total_recorded": len(telemetry),
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@router.get("/alerts")
def get_alerts() -> List[Dict[str, Any]]:
    """Return the last 100 price drop alerts from Redis."""
    import json
    r = get_redis()

    raw_alerts = r.lrange("alerts:price_drops", 0, 99)
    alerts = []
    for raw in raw_alerts:
        try:
            alerts.append(json.loads(raw))
        except Exception:
            pass

    return alerts
