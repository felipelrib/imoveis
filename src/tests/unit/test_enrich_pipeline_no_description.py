"""Sentiment must not be fabricated on an empty listing description (BIN-243).

Every property in the DB predated the description-enrich step, and platforms
like QuintoAndar expose no seller free-text at all. Feeding that empty string to
the text model produced a confident, meaningless sentiment (Ollama: ``good/0.75``)
that silently corrupted the deal verdict. The pipeline must skip the model and
record an explicit neutral, no-signal result instead.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from adapters.ai.client import SentimentResult, VisualResult
from adapters.ai.enrich_pipeline import (
    SENTIMENT_NO_DESCRIPTION_REASON,
    analyze_visual_and_sentiment,
    neutral_sentiment_no_description,
)


def _client() -> AsyncMock:
    client = AsyncMock()
    client.analyze_visuals = AsyncMock(
        return_value=VisualResult(condition_score=0.7, analysis="ok", category="Good")
    )
    client.analyze_text = AsyncMock(
        return_value=SentimentResult(sentiment_score=0.9, category="Good")
    )
    return client


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["", "   ", "\n\t", None])
async def test_blank_description_skips_text_model(description):
    """Blank/whitespace/None description → never call the text model."""
    client = _client()

    visual, sentiment = await analyze_visual_and_sentiment(
        client,
        ["/tmp/a.jpg"],
        description,  # type: ignore[arg-type]
        "visual prompt",
        "sentiment prompt",
    )

    client.analyze_visuals.assert_awaited_once()
    client.analyze_text.assert_not_awaited()
    assert visual.condition_score == 0.7
    # Honest neutral, not the fabricated 0.9 the mock would have returned.
    assert sentiment.sentiment_score == 0.5
    assert sentiment.reasoning == SENTIMENT_NO_DESCRIPTION_REASON
    assert sentiment.green_flags == []
    assert sentiment.red_flags == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nonempty_description_still_calls_text_model():
    """A real description must still reach the text model unchanged."""
    client = _client()

    visual, sentiment = await analyze_visual_and_sentiment(
        client,
        ["/tmp/a.jpg"],
        "Apartamento reformado com vista, aceita pets.",
        "visual prompt",
        "sentiment prompt",
    )

    client.analyze_text.assert_awaited_once()
    assert visual.condition_score == 0.7
    assert sentiment.sentiment_score == 0.9


@pytest.mark.unit
def test_neutral_sentiment_no_description_shape():
    """The neutral result is a valid, no-signal SentimentResult."""
    result = neutral_sentiment_no_description()
    assert result.sentiment_score == 0.5
    assert result.category == "average"
    assert result.reasoning == SENTIMENT_NO_DESCRIPTION_REASON
    assert result.green_flags == [] and result.red_flags == []
