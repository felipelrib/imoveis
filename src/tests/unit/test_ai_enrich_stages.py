"""Unit tests for ai_enrich stage branching (BIN-95)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.ai.client import DealVerdictResult, SentimentResult, VisualResult


@pytest.mark.unit
def test_ai_enrich_verdict_only_skips_vlm_and_downloads():
    from adapters.queue import tasks as tasks_mod

    property_id = "11111111-1111-1111-1111-111111111111"
    ms = SimpleNamespace(
        meta={
            "visual": {"condition_score": 0.7},
            "sentiment": {"sentiment_score": 0.6},
            "stat_analysis": {},
        },
        ai_score=0.65,
    )

    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = ms
    session.get.return_value = SimpleNamespace(neighborhood_id=None, props_json=None)

    redis = MagicMock()
    redis.exists.return_value = False
    sem = MagicMock()
    sem.acquire.return_value = True

    client = MagicMock()
    client.session_context = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    client.summarize_deal = AsyncMock(
        return_value=DealVerdictResult(verdict="Buy", confidence=0.8)
    )

    image_store = MagicMock()
    image_store.download_images = AsyncMock(return_value=["/tmp/a.jpg"])

    task_self = MagicMock()
    task_self.retry = MagicMock(side_effect=RuntimeError("retry"))

    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "get_config") as mock_cfg,
        patch.object(tasks_mod, "GPUSemaphore", return_value=sem),
        patch.object(tasks_mod, "ImageStore", return_value=image_store),
        patch.object(tasks_mod, "create_ai_client", return_value=client),
        patch.object(tasks_mod, "SessionLocal", return_value=session),
        patch.object(tasks_mod, "analyze_visual_and_sentiment", new_callable=AsyncMock) as mock_vs,
    ):
        mock_cfg.return_value.gpu.semaphore_limit = 1
        mock_cfg.return_value.ai.max_images_per_property = 8
        mock_cfg.return_value.ai.max_description_chars = 2000
        mock_cfg.return_value.ai.visual_weight = 0.6
        mock_cfg.return_value.ai.text_weight = 0.4
        mock_cfg.return_value.scoring = SimpleNamespace(
            stat_weight=0.4, ai_weight=0.4, neighbourhood_weight=0.2
        )

        result = tasks_mod.ai_enrich.run(
            property_id,
            [],
            "",
            stages="verdict_only",
        )

    assert result["status"] == "completed"
    assert result["stages"] == "verdict_only"
    image_store.download_images.assert_not_called()
    mock_vs.assert_not_called()
    client.summarize_deal.assert_awaited()
    assert ms.meta["deal_verdict"]["verdict"] == "Buy"
    assert "enriched_at" in ms.meta
    sem.release.assert_called_once()


@pytest.mark.unit
def test_ai_enrich_visual_sentiment_skips_verdict():
    from adapters.queue import tasks as tasks_mod

    property_id = "22222222-2222-2222-2222-222222222222"
    ms = SimpleNamespace(meta={}, ai_score=None, stat_score=0.5)

    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = ms
    session.get.return_value = SimpleNamespace(neighborhood_id=None, props_json=None)

    redis = MagicMock()
    redis.exists.return_value = False
    pipe = MagicMock()
    redis.pipeline.return_value.__enter__ = MagicMock(return_value=pipe)
    redis.pipeline.return_value.__exit__ = MagicMock(return_value=False)
    sem = MagicMock()
    sem.acquire.return_value = True

    client = MagicMock()
    client.session_context = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    client.summarize_deal = AsyncMock(
        return_value=DealVerdictResult(verdict="Buy", confidence=0.8)
    )

    image_store = MagicMock()
    image_store.download_images = AsyncMock(return_value=["/tmp/a.jpg"])

    v_res = VisualResult(condition_score=0.7, analysis="ok", category="Good")
    s_res = SentimentResult(sentiment_score=0.6, analysis="ok", category="Good")

    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "get_config") as mock_cfg,
        patch.object(tasks_mod, "GPUSemaphore", return_value=sem),
        patch.object(tasks_mod, "ImageStore", return_value=image_store),
        patch.object(tasks_mod, "create_ai_client", return_value=client),
        patch.object(tasks_mod, "SessionLocal", return_value=session),
        patch.object(
            tasks_mod,
            "analyze_visual_and_sentiment",
            new=AsyncMock(return_value=(v_res, s_res)),
        ),
        patch.object(tasks_mod, "assign_property_neighbourhood"),
        patch.object(tasks_mod, "score_single_property"),
        patch.object(
            tasks_mod,
            "build_visual_condition_prompt",
            return_value="vp",
        ),
        patch.object(tasks_mod, "build_sentiment_prompt", return_value="sp"),
    ):
        mock_cfg.return_value.gpu.semaphore_limit = 1
        mock_cfg.return_value.ai.max_images_per_property = 8
        mock_cfg.return_value.ai.max_description_chars = 2000
        mock_cfg.return_value.ai.visual_weight = 0.6
        mock_cfg.return_value.ai.text_weight = 0.4
        mock_cfg.return_value.scoring = SimpleNamespace(
            stat_weight=0.4, ai_weight=0.4, neighbourhood_weight=0.2
        )

        result = tasks_mod.ai_enrich.run(
            property_id,
            ["https://cdn.example/1.jpg"],
            "nice",
            stages="visual+sentiment",
        )

    assert result["status"] == "completed"
    assert result["stages"] == "visual+sentiment"
    client.summarize_deal.assert_not_called()
    assert "enriched_at" in ms.meta
    assert "visual" in ms.meta
    assert "deal_verdict" not in ms.meta
