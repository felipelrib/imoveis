"""Unit tests for scrape_listings pipeline wiring (config + persist path).

Catches regressions where AppConfig silently drops YAML sections that
``tasks.scrape_listings`` still reads (e.g. missing DedupConfig → every
listing errors).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.dedupe import DedupeMatchResult
from infra.config import DedupConfig, get_config


@pytest.mark.unit
def test_scrape_listings_processes_one_item_with_real_dedup_config():
    """Happy path uses real DedupConfig leaves — AttributeError would mean 1 error."""
    from adapters.queue import tasks as tasks_mod

    real_cfg = get_config()
    # Guard: if DedupConfig were missing from AppConfig, this fails before the task.
    assert isinstance(real_cfg.dedup, DedupConfig)
    assert "olx" in real_cfg.scraping.platforms

    normalized = {
        "platform": "olx",
        "platform_id": "regression-gate-1",
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
                "platform_listing_id": "regression-gate-1",
                "listing_type": "rent",
                "price": 2500.0,
                "currency": "BRL",
                "url": "https://www.olx.com.br/detalhes/regression-gate-1",
            }
        ],
    }

    scraper = MagicMock()
    scraper.proxy_summary = {
        "proxy_enabled": False,
        "proxy_mode": "direct",
        "rotation_strategy": "round_robin",
        "pool_size": 0,
        "proxy_host": None,
    }
    scraper.fetch_pages.return_value = iter([{"list_id": "regression-gate-1"}])
    scraper.normalize.return_value = normalized
    scraper.__enter__ = MagicMock(return_value=scraper)
    scraper.__exit__ = MagicMock(return_value=False)

    fake_redis = MagicMock()
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
        ) as match_fn,
        patch.object(tasks_mod, "assign_property_neighbourhood") as assign_fn,
        patch.object(tasks_mod, "_enqueue_post_scrape_jobs") as enqueue_fn,
    ):
        store_cls.return_value.get.return_value = {}
        registry.get.return_value = scraper
        tasks_mod.scrape_listings.run("olx")

    match_fn.assert_called_once()
    # Prove real DedupConfig values were passed (not MagicMock attributes).
    kwargs = match_fn.call_args.kwargs
    assert kwargs["text_threshold"] == real_cfg.dedup.text_similarity_threshold
    assert kwargs["algorithm"] == real_cfg.dedup.text_similarity_algorithm
    assert kwargs["radius_m"] == real_cfg.dedup.radius_m
    assert kwargs["area_tol"] == real_cfg.dedup.area_tolerance_m2
    assign_fn.assert_called_once_with(session, "prop-1")
    enqueue_fn.assert_called_once()

    status_writes = [
        call
        for call in fake_redis.set.call_args_list
        if call.args and str(call.args[0]).endswith(":status")
    ]
    assert status_writes
    completed = [
        json.loads(call.args[1])
        for call in status_writes
        if json.loads(call.args[1]).get("status") == "completed"
    ]
    assert completed, "expected a completed scraper status write"
    assert completed[-1]["processed"] == 1
    assert completed[-1]["errors"] == 0
    assert completed[-1]["skipped"] == 0
