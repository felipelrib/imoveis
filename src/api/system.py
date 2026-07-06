"""System status and control API — used by the GUI control panel."""
from __future__ import annotations

import subprocess
from typing import Any, Dict

from fastapi import APIRouter

from infra.logging import get_logger
from infra.redis_client import get_redis
from infra.config import get_config

logger = get_logger(__name__)
router = APIRouter(prefix="/system", tags=["system"])


# ---------------------------------------------------------------------------
# Health / status aggregation
# ---------------------------------------------------------------------------


def _check_db() -> dict:
    try:
        from infra.db import engine
        import sqlalchemy
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict:
    try:
        get_redis().ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_ollama() -> dict:
    try:
        import httpx
        r = httpx.get(f"{get_config().ai.ollama_url}/api/tags", timeout=3)
        models = [m["name"] for m in (r.json().get("models") or [])]
        return {"status": "ok", "models": models}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _count_properties() -> int:
    try:
        from infra.db import SessionLocal
        import sqlalchemy
        s = SessionLocal()
        try:
            result = s.execute(sqlalchemy.text("SELECT COUNT(*) FROM properties")).scalar()
            return int(result or 0)
        finally:
            s.close()
    except Exception:
        return 0


def _count_enriched() -> int:
    try:
        from infra.db import SessionLocal
        import sqlalchemy
        s = SessionLocal()
        try:
            result = s.execute(
                sqlalchemy.text(
                    "SELECT COUNT(*) FROM metrics_scoring WHERE ai_score IS NOT NULL AND ai_score > 0"
                )
            ).scalar()
            return int(result or 0)
        finally:
            s.close()
    except Exception:
        return 0


@router.get("/status")
def system_status() -> Dict[str, Any]:
    """Return health of all system components — polled by the GUI dashboard."""
    r = get_redis()
    ai_paused = r.exists("workers:ai:paused") > 0

    return {
        "database": _check_db(),
        "redis": _check_redis(),
        "ollama": _check_ollama(),
        "ai_workers_paused": ai_paused,
        "stats": {
            "total_properties": _count_properties(),
            "enriched_properties": _count_enriched(),
        },
    }


# ---------------------------------------------------------------------------
# Ollama control (start serve from API — useful when not using start.ps1)
# ---------------------------------------------------------------------------


@router.post("/ollama/ensure")
def ensure_ollama():
    """Attempt to start ollama serve if not already running."""
    try:
        import httpx
        httpx.get(f"{get_config().ai.ollama_url}/api/tags", timeout=2)
        return {"status": "already_running"}
    except Exception:
        pass

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"status": "started"}
    except FileNotFoundError:
        return {"status": "error", "detail": "ollama not found on PATH"}

# ---------------------------------------------------------------------------
# Pipeline Tracking
# ---------------------------------------------------------------------------


@router.get("/pipeline")
def system_pipeline() -> Dict[str, Any]:
    """Return live status of the ingestion pipeline (queues and active tasks)."""
    import json
    r = get_redis()
    
    # Celery default queue lengths in Redis
    # Note: Using LLEN on the queue names returns the number of pending tasks
    scrapers_queued = r.llen("scrapers")
    ai_queued = r.llen("ai")
    
    # Get active scraper statuses
    # We look for all keys matching pipeline:scraper:*:status
    scrapers_status = {}
    for key in r.scan_iter("pipeline:scraper:*:status"):
        platform_name = key.decode("utf-8").split(":")[2]
        try:
            status_data = json.loads(r.get(key))
            scrapers_status[platform_name] = status_data
        except Exception:
            pass

    # AI Telemetry
    ai_telemetry = r.lrange("pipeline:ai:telemetry", 0, -1)
    ai_metrics = {"throughput_per_min": 0, "avg_duration_sec": 0, "total_recorded": len(ai_telemetry)}
    if ai_telemetry:
        import time
        now = time.time()
        durations = []
        recent_count = 0
        for item in ai_telemetry:
            try:
                data = json.loads(item)
                durations.append(data["duration"])
                if now - data["timestamp"] <= 300: # Last 5 minutes
                    recent_count += 1
            except Exception:
                pass
        
        if durations:
            ai_metrics["avg_duration_sec"] = round(sum(durations) / len(durations), 2)
        # throughput = items in last 5 min / 5
        ai_metrics["throughput_per_min"] = round(recent_count / 5.0, 1)

    return {
        "queues": {
            "scrapers": scrapers_queued,
            "ai": ai_queued,
        },
        "scrapers_status": scrapers_status,
        "ai_metrics": ai_metrics
    }
