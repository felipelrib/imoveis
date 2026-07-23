"""Unit tests for scrape status proxy signals (BIN-49 / Story 3.3)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from adapters.queue.tasks import _write_scraper_status


@pytest.mark.unit
def test_write_scraper_status_includes_safe_proxy_fields():
    r = MagicMock()
    proxy = {
        "proxy_enabled": True,
        "proxy_mode": "pool",
        "rotation_strategy": "round_robin",
        "pool_size": 2,
        "proxy_host": "http://a.example:1",
    }
    _write_scraper_status(
        r,
        "pipeline:scraper:olx:status",
        processed=0,
        skipped=0,
        errors=0,
        status="running",
        proxy=proxy,
    )
    r.set.assert_called_once()
    key, raw = r.set.call_args.args[0], r.set.call_args.args[1]
    assert key == "pipeline:scraper:olx:status"
    payload = json.loads(raw)
    assert payload["status"] == "running"
    assert payload["proxy_mode"] == "pool"
    assert payload["proxy_host"] == "http://a.example:1"
    assert "secret" not in raw


@pytest.mark.unit
def test_write_scraper_status_omits_proxy_when_empty():
    r = MagicMock()
    _write_scraper_status(r, "k", 1, 0, 0, "completed")
    payload = json.loads(r.set.call_args.args[1])
    assert payload == {"processed": 1, "skipped": 0, "errors": 0, "status": "completed"}


@pytest.mark.unit
def test_scrape_listings_writes_proxy_summary_at_start():
    """After start(), Redis status includes scraper.proxy_summary (no credentials)."""
    from adapters.queue import tasks as tasks_mod

    scraper = MagicMock()
    scraper.proxy_summary = {
        "proxy_enabled": True,
        "proxy_mode": "single",
        "rotation_strategy": "round_robin",
        "pool_size": 0,
        "proxy_host": "http://proxy.example:8080",
    }
    scraper.fetch_pages.return_value = iter(())
    scraper.__enter__ = MagicMock(return_value=scraper)
    scraper.__exit__ = MagicMock(return_value=False)

    fake_cfg = MagicMock()
    fake_cfg.scraping.platforms = {"olx": MagicMock()}
    fake_cfg.scraping.platforms["olx"].model_dump.return_value = {"name": "olx"}
    fake_redis = MagicMock()
    fake_redis.exists.return_value = False

    with (
        patch.object(tasks_mod, "get_config", return_value=fake_cfg),
        patch.object(tasks_mod, "SessionLocal", return_value=MagicMock()),
        patch.object(tasks_mod, "get_redis", return_value=fake_redis),
        patch.object(tasks_mod, "CheckpointStore") as store_cls,
        patch.object(tasks_mod, "ScraperRegistry") as registry,
    ):
        store_cls.return_value.get.return_value = {}
        registry.get.return_value = scraper
        tasks_mod.scrape_listings.run("olx")

    # First status write after start should include proxy fields
    status_writes = [
        call
        for call in fake_redis.set.call_args_list
        if call.args and str(call.args[0]).endswith(":status")
    ]
    assert status_writes
    first_payload = json.loads(status_writes[0].args[1])
    assert first_payload["proxy_mode"] == "single"
    assert first_payload["proxy_host"] == "http://proxy.example:8080"
    assert "user:" not in status_writes[0].args[1]
