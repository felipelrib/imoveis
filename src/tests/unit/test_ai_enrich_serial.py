"""Regression: AI enrich must not run visual + text generates concurrently."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from adapters.ai.client import SentimentResult, VisualResult
from adapters.ai.enrich_pipeline import analyze_visual_and_sentiment


@pytest.mark.unit
@pytest.mark.asyncio
async def test_analyze_visual_and_sentiment_is_serial():
    """Visual and text must not overlap — max in-flight generates stays at 1."""
    in_flight = 0
    peak = 0
    order: list[str] = []

    async def _visual(_paths, _prompt):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        order.append("visual_start")
        await asyncio.sleep(0.05)
        order.append("visual_end")
        in_flight -= 1
        return VisualResult(condition_score=0.7, analysis="ok", category="Good")

    async def _text(_desc, _prompt):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        order.append("text_start")
        await asyncio.sleep(0.05)
        order.append("text_end")
        in_flight -= 1
        return SentimentResult(sentiment_score=0.6, analysis="ok", category="Good")

    client = AsyncMock()
    client.analyze_visuals = AsyncMock(side_effect=_visual)
    client.analyze_text = AsyncMock(side_effect=_text)

    v, s = await analyze_visual_and_sentiment(
        client,
        ["/tmp/a.jpg"],
        "nice flat",
        "visual prompt",
        "sentiment prompt",
    )

    assert peak == 1
    assert order == ["visual_start", "visual_end", "text_start", "text_end"]
    assert v.condition_score == 0.7
    assert s.sentiment_score == 0.6
    client.analyze_visuals.assert_awaited_once()
    client.analyze_text.assert_awaited_once()
