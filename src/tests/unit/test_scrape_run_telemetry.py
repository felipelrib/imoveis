"""Unit tests for scrape-run Activity Log telemetry."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from adapters.queue.tasks import (
    REDIS_KEY_SCRAPER_TELEMETRY,
    SCRAPER_TELEMETRY_MAX,
    _record_scrape_run,
)
from api.system import _recent_scrape_runs
from core.dedupe import DedupeMatchResult
from infra.config import get_config


def _fake_redis_with_pipeline():
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value.__enter__.return_value = pipe
    r.pipeline.return_value.__exit__.return_value = False
    return r, pipe


@pytest.mark.unit
def test_record_scrape_run_lpushes_summary():
    r, pipe = _fake_redis_with_pipeline()
    rid = _record_scrape_run(
        r,
        platform="olx",
        processed=42,
        skipped=3,
        errors=1,
        status="completed",
        run_id="run-fixed-1",
    )
    assert rid == "run-fixed-1"
    pipe.lpush.assert_called_once()
    key, raw = pipe.lpush.call_args.args
    assert key == REDIS_KEY_SCRAPER_TELEMETRY
    payload = json.loads(raw)
    assert payload["run_id"] == "run-fixed-1"
    assert payload["platform"] == "olx"
    assert payload["processed"] == 42
    assert payload["skipped"] == 3
    assert payload["errors"] == 1
    assert payload["status"] == "completed"
    assert isinstance(payload["timestamp"], (int, float))
    pipe.ltrim.assert_called_once_with(REDIS_KEY_SCRAPER_TELEMETRY, 0, SCRAPER_TELEMETRY_MAX - 1)
    pipe.execute.assert_called_once()


@pytest.mark.unit
def test_recent_scrape_runs_parses_and_skips_bad_json():
    r = MagicMock()
    r.lrange.return_value = [
        json.dumps(
            {
                "run_id": "a",
                "platform": "olx",
                "processed": 1,
                "skipped": 0,
                "errors": 0,
                "status": "completed",
                "timestamp": 1.0,
            }
        ),
        "not-json",
        json.dumps({"platform": "missing-run-id"}),
    ]
    runs = _recent_scrape_runs(r)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "a"
    r.lrange.assert_called_once_with("pipeline:scraper:telemetry", 0, -1)


@pytest.mark.unit
def test_scrape_listings_records_completed_telemetry():
    from adapters.queue import tasks as tasks_mod

    real_cfg = get_config()
    assert "olx" in real_cfg.scraping.platforms

    normalized = {
        "platform": "olx",
        "platform_id": "telemetry-gate-1",
        "title": "Apartamento teste",
        "description": "",
        "price": 2500.0,
        "area_m2": 70.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 1,
        "location": None,
        "address": "Savassi, Belo Horizonte",
        "image_urls": [],
        "props_json": {"neighborhood": "Savassi"},
        "listings": [
            {
                "platform": "olx",
                "platform_listing_id": "telemetry-gate-1",
                "listing_type": "rent",
                "price": 2500.0,
                "currency": "BRL",
                "url": "https://www.olx.com.br/detalhes/telemetry-gate-1",
            }
        ],
    }

    scraper = MagicMock()
    scraper.proxy_summary = {}
    scraper.fetch_pages.return_value = iter([{"list_id": "telemetry-gate-1"}])
    scraper.normalize.return_value = normalized
    scraper.__enter__ = MagicMock(return_value=scraper)
    scraper.__exit__ = MagicMock(return_value=False)

    fake_redis, pipe = _fake_redis_with_pipeline()
    fake_redis.exists.return_value = False
    session = MagicMock()

    with (
        patch.object(tasks_mod, "get_config", return_value=real_cfg),
        patch.object(tasks_mod, "SessionLocal", return_value=session),
        patch.object(tasks_mod, "get_redis", return_value=fake_redis),
        patch.object(tasks_mod, "CheckpointStore") as store_cls,
        patch.object(tasks_mod, "ScraperRegistry") as registry,
        patch.object(
            tasks_mod,
            "match_or_create_property",
            return_value=DedupeMatchResult(property_id="prop-1", action="created"),
        ),
        patch.object(tasks_mod, "assign_property_neighbourhood"),
        patch.object(tasks_mod, "_enqueue_post_scrape_jobs"),
    ):
        store_cls.return_value.get.return_value = {}
        registry.get.return_value = scraper
        tasks_mod.scrape_listings.run("olx")

    telemetry_calls = [
        call
        for call in pipe.lpush.call_args_list
        if call.args and call.args[0] == REDIS_KEY_SCRAPER_TELEMETRY
    ]
    assert telemetry_calls, "expected scrape telemetry LPUSH"
    payload = json.loads(telemetry_calls[-1].args[1])
    assert payload["platform"] == "olx"
    assert payload["status"] == "completed"
    assert payload["processed"] == 1
    assert payload["skipped"] == 0
    assert payload["errors"] == 0
    assert payload["run_id"]


@pytest.mark.unit
def test_scrape_listings_records_failed_telemetry_on_error():
    from adapters.queue import tasks as tasks_mod

    real_cfg = get_config()
    fake_redis, pipe = _fake_redis_with_pipeline()
    fake_redis.exists.return_value = False
    session = MagicMock()

    with (
        patch.object(tasks_mod, "get_config", return_value=real_cfg),
        patch.object(tasks_mod, "SessionLocal", return_value=session),
        patch.object(tasks_mod, "get_redis", return_value=fake_redis),
        patch.object(tasks_mod, "CheckpointStore") as store_cls,
        patch.object(tasks_mod, "ScraperRegistry") as registry,
        pytest.raises(RuntimeError, match="boom"),
    ):
        store_cls.return_value.get.return_value = {}
        registry.get.side_effect = RuntimeError("boom")
        tasks_mod.scrape_listings.run("olx")

    telemetry_calls = [
        call
        for call in pipe.lpush.call_args_list
        if call.args and call.args[0] == REDIS_KEY_SCRAPER_TELEMETRY
    ]
    assert telemetry_calls, "expected failed scrape telemetry LPUSH"
    payload = json.loads(telemetry_calls[-1].args[1])
    assert payload["platform"] == "olx"
    assert payload["status"] == "failed"
    assert payload["processed"] == 0
