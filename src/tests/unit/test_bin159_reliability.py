"""BIN-159 reliability follow-ups.

Covers the three items with observable behaviour:
  1. embed_property gates the Ollama embed call through the GPU semaphore.
  2. /admin/gpu/scale rejects a limit above the configured ceiling.
  4. scrape_listings persists the checkpoint once per run, not once per item.

(Item 3 — zapimoveis checkpoint model — lives in test_checkpoint_store.py.)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.dedupe import DedupeMatchResult
from infra.config import get_config

# ---------------------------------------------------------------------------
# Item 1 — embed_property GPU semaphore
# ---------------------------------------------------------------------------


def _patch_embed(tasks_mod, sem, *, acquire=True):
    sem.acquire.return_value = acquire
    fake_redis = MagicMock()
    fake_redis.exists.return_value = False
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.execute.return_value.mappings.return_value.first.return_value = {
        "title": "T",
        "description": "D",
    }
    return patch.multiple(
        tasks_mod,
        get_config=MagicMock(return_value=get_config()),
        get_redis=MagicMock(return_value=fake_redis),
        SessionLocal=MagicMock(return_value=session),
        GPUSemaphore=MagicMock(return_value=sem),
        create_ai_client=MagicMock(),
        run_coro=MagicMock(return_value=[0.1, 0.2, 0.3]),
    )


@pytest.mark.unit
def test_embed_property_acquires_and_releases_semaphore():
    from adapters.queue import tasks as tasks_mod

    sem = MagicMock()
    with _patch_embed(tasks_mod, sem, acquire=True):
        with patch(
            "adapters.ai.embeddings.build_embedding_text", return_value="T D"
        ), patch("adapters.ai.embeddings.vector_literal", return_value="[0.1]"):
            result = tasks_mod.embed_property.run("11111111-1111-1111-1111-111111111111")

    assert result["status"] == "completed"
    sem.acquire.assert_called_once()
    # Held slot must always be released, even on the happy path.
    sem.release.assert_called_once()


@pytest.mark.unit
def test_embed_property_retries_when_semaphore_busy():
    from adapters.queue import tasks as tasks_mod

    sem = MagicMock()
    with _patch_embed(tasks_mod, sem, acquire=False):
        with patch.object(
            tasks_mod.embed_property, "retry", side_effect=RuntimeError("retry")
        ) as retry:
            with pytest.raises(RuntimeError, match="retry"):
                tasks_mod.embed_property.run("22222222-2222-2222-2222-222222222222")

    retry.assert_called_once()
    # Never entered the work body, so nothing to release.
    sem.release.assert_not_called()


# ---------------------------------------------------------------------------
# Item 2 — /admin/gpu/scale upper bound
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_gpu_scale_rejects_limit_above_ceiling():
    from fastapi import HTTPException

    from api import admin as admin_mod

    cfg = get_config()
    over = cfg.gpu.max_semaphore_limit + 1
    sem = MagicMock()
    with patch.object(admin_mod, "GPUSemaphore", return_value=sem), patch.object(
        admin_mod, "log_audit_action"
    ):
        with pytest.raises(HTTPException) as exc:
            admin_mod.set_gpu_limit(admin_mod.GPUScaleRequest(limit=over))
    assert exc.value.status_code == 400
    sem.scale.assert_not_called()


@pytest.mark.unit
def test_gpu_scale_accepts_limit_within_ceiling():
    from api import admin as admin_mod

    cfg = get_config()
    ok = cfg.gpu.max_semaphore_limit
    sem = MagicMock()
    with patch.object(admin_mod, "GPUSemaphore", return_value=sem), patch.object(
        admin_mod, "log_audit_action"
    ):
        result = admin_mod.set_gpu_limit(admin_mod.GPUScaleRequest(limit=ok))
    assert result == {"gpu_limit": ok}
    sem.scale.assert_called_once_with(ok)


@pytest.mark.unit
def test_gpu_scale_request_rejects_zero_or_negative():
    from pydantic import ValidationError

    from api import admin as admin_mod

    for bad in (0, -3):
        with pytest.raises(ValidationError):
            admin_mod.GPUScaleRequest(limit=bad)


# ---------------------------------------------------------------------------
# Item 4 — checkpoint persisted once per run, not per item
# ---------------------------------------------------------------------------


def _normalized(platform_id: str) -> dict:
    return {
        "platform": "olx",
        "platform_id": platform_id,
        "title": "Apto",
        "description": "",
        "price": 2500.0,
        "area_m2": 70.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 1,
        "location": None,
        "address": "Savassi, Belo Horizonte",
        "image_urls": [f"https://cdn.example/{i}.jpg" for i in range(1, 9)],
        "props_json": {"neighborhood": "Savassi", "city": "Belo Horizonte", "state": "MG"},
        "listings": [
            {
                "platform": "olx",
                "platform_listing_id": platform_id,
                "listing_type": "rent",
                "price": 2500.0,
                "currency": "BRL",
                "url": f"https://www.olx.com.br/detalhes/{platform_id}",
            }
        ],
    }


@pytest.mark.unit
def test_scrape_listings_persists_checkpoint_once_per_run():
    """Two processed items → a single store.set (BIN-159), not one per item."""
    from adapters.queue import tasks as tasks_mod

    real_cfg = get_config()

    scraper = MagicMock()
    scraper.proxy_summary = {}
    scraper.fetch_pages.return_value = iter(
        [{"list_id": "cp-1"}, {"list_id": "cp-2"}]
    )
    scraper.normalize.side_effect = [_normalized("cp-1"), _normalized("cp-2")]
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
            side_effect=[
                DedupeMatchResult(property_id="p1", action="created"),
                DedupeMatchResult(property_id="p2", action="created"),
            ],
        ),
        patch.object(tasks_mod, "assign_property_neighbourhood"),
        patch.object(tasks_mod, "assign_property_neighbourhood_by_name"),
        patch.object(tasks_mod, "apply_neighbourhood_representative_point"),
        patch.object(tasks_mod, "_enqueue_post_scrape_jobs"),
        patch.object(tasks_mod, "sync_ai_extract", return_value=None),
        patch.object(tasks_mod, "load_neighborhood_names", return_value=["Savassi"]),
    ):
        store = store_cls.return_value
        store.get.return_value = {}
        registry.get.return_value = scraper
        tasks_mod.scrape_listings.run("olx")

    assert store.set.call_count == 1
