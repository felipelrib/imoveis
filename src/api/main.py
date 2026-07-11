"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.admin import router as admin_router
from api.favourites import router as favourites_router
from api.properties import router as properties_router
from api.saved_searches import router as saved_searches_router
from api.system import router as system_router
from api.watchlist import router as watchlist_router
from infra.logging import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="Local Real-Estate Ingestor",
    description="Scrape, deduplicate, and score real-estate listings with local VLM enrichment.",
    version="2.0.0",
)

# CORS — allow the Vite dev server and any local origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(favourites_router)
app.include_router(properties_router)
app.include_router(saved_searches_router)
app.include_router(system_router)
app.include_router(watchlist_router)


@app.get("/", tags=["meta"])
def index():
    return {"service": "local-realestate", "version": "2.0.0", "status": "running"}


@app.get("/health", tags=["meta"])
def health():
    status: dict = {"db": "unknown", "redis": "unknown"}
    try:
        import sqlalchemy

        from infra.db import engine

        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        status["db"] = "ok"
    except Exception as exc:
        status["db"] = f"error: {exc}"
    try:
        from infra.redis_client import get_redis

        get_redis().ping()
        status["redis"] = "ok"
    except Exception as exc:
        status["redis"] = f"error: {exc}"
    overall = "ok" if all(v == "ok" for v in status.values()) else "degraded"
    return {"status": overall, **status}


class ScrapeRequest(BaseModel):
    platform: str
    checkpoint: dict = {}
    scrape_type: str = "both"


@app.post("/scrape", tags=["ingestion"])
def trigger_scrape(req: ScrapeRequest):
    try:
        # Import scrapers so they self-register
        import adapters.scrapers.quintoandar  # noqa: F401
        from adapters.queue.tasks import scrape_listings
        from adapters.scrapers.registry import ScraperRegistry

        available = ScraperRegistry.available()
        if req.platform not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown platform '{req.platform}'. Available: {available}",
            )
        checkpoint = req.checkpoint or {}
        checkpoint["scrape_type"] = req.scrape_type
        task = scrape_listings.delay(req.platform, checkpoint)
        logger.info(
            "scrape_enqueued",
            platform=req.platform,
            scrape_type=req.scrape_type,
            task_id=task.id,
        )
        return {"task_id": task.id, "platform": req.platform, "status": "queued"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("scrape_trigger_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/platforms", tags=["ingestion"])
def list_platforms():
    """Return registered scraper platforms for the GUI dropdown."""
    import adapters.scrapers.quintoandar  # noqa: F401 — triggers registration
    from adapters.scrapers.registry import ScraperRegistry
    from infra.config import get_config

    cfg = get_config()
    result = []
    for name in ScraperRegistry.available():
        pcfg = cfg.scraping.platforms.get(name)
        result.append(
            {
                "name": name,
                "enabled": pcfg.enabled if pcfg else True,
                "rate_limit": getattr(pcfg, "rate_limit", None) if pcfg else None,
            }
        )
    return result
