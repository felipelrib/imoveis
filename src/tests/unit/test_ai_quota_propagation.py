"""Quota exhaustion must propagate, never fabricate a score (v0.13-s1.3).

The bug this locks: ``GeminiClient.chat_completions`` raises after exhausting its
429 retries, but ``analyze_visuals`` / ``analyze_text`` caught *every* exception
and returned ``0.5``. ``run_enrichment`` then persisted that fabricated score and
the backfill checkpointed the row as done — so a quota-exhausted multi-day run
quietly filled the DB with fake 0.5s that ``mode=missing`` would never re-queue.

A quota refusal is not a per-call blip: it affects every subsequent call, so it
has to reach the runner as a distinguished error. Every *other* failure keeps its
template/0.5 fallback, which these tests also pin.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.ai.client import (
    AIClientError,
    AIQuotaExhaustedError,
    GeminiClient,
    GemmaClient,
    LMStudioClient,
    OllamaClient,
)
from core.backfill_runner import is_quota_exhausted

pytestmark = pytest.mark.unit


def _ctx(response):
    return AsyncMock(
        __aenter__=AsyncMock(return_value=response),
        __aexit__=AsyncMock(return_value=None),
    )


def _chat(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _client_with_status(status: int, body: str, *, cls=GeminiClient) -> GeminiClient:
    client = cls(api_key="k", max_retries=2)
    client._sleep_backoff = AsyncMock(return_value=0.0)  # no real backoff sleep
    response = AsyncMock(status=status)
    response.text.return_value = body
    client.session = MagicMock()
    client.session.post.return_value = _ctx(response)
    return client


def _image(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(b"image-bytes")
    return str(path)


# ---------------------------------------------------------------------------
# Transport: a terminal quota refusal raises the distinguished error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [GeminiClient, GemmaClient])
def test_persistent_429_raises_quota_exhausted(cls):
    client = _client_with_status(429, "rate limited", cls=cls)

    with pytest.raises(AIQuotaExhaustedError) as exc:
        asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))

    assert client.rate_limit_hits >= 1
    assert "429" in str(exc.value)
    # Still an AIClientError, so existing `except AIClientError` handlers work.
    assert isinstance(exc.value, AIClientError)


def test_resource_exhausted_body_raises_quota_exhausted_on_any_status():
    client = _client_with_status(
        400, '{"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}'
    )

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))


def test_ordinary_server_error_is_not_a_quota_error():
    client = _client_with_status(500, "boom")

    with pytest.raises(AIClientError) as exc:
        asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))

    assert not isinstance(exc.value, AIQuotaExhaustedError)


def test_quota_error_is_recognised_by_the_core_predicate():
    """``src/core`` duck-types the flag — it must never import adapters (AD-1)."""
    assert AIQuotaExhaustedError.is_quota_exhausted is True
    assert is_quota_exhausted(AIQuotaExhaustedError("Gemini quota exhausted: 429"))
    assert not is_quota_exhausted(AIClientError("Gemini API error: 500"))


# ---------------------------------------------------------------------------
# Fallbacks re-raise a quota error instead of fabricating 0.5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [LMStudioClient, GeminiClient, GemmaClient])
def test_analyze_visuals_reraises_quota_instead_of_scoring_half(cls, tmp_path):
    client = cls(api_key="k") if cls is not LMStudioClient else cls()
    client.chat_completions = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.analyze_visuals([_image(tmp_path)], "prompt"))


@pytest.mark.parametrize("cls", [LMStudioClient, GeminiClient, GemmaClient])
def test_analyze_text_reraises_quota_instead_of_scoring_half(cls):
    client = cls(api_key="k") if cls is not LMStudioClient else cls()
    client.chat_completions = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.analyze_text("description", "prompt"))


@pytest.mark.parametrize("cls", [LMStudioClient, GeminiClient, GemmaClient])
def test_summarize_deal_reraises_quota_instead_of_templating(cls):
    client = cls(api_key="k") if cls is not LMStudioClient else cls()
    client.chat_completions = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.summarize_deal(stat_analysis={"category": "average"}))


def test_ollama_visual_fallback_also_reraises_quota():
    """Ollama shares the fallback shape; the guard must be there too."""
    client = OllamaClient()
    client.generate = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.analyze_text("description", "prompt"))


def test_ollama_verdict_fallback_also_reraises_quota():
    client = OllamaClient()
    client.generate = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.summarize_deal(stat_analysis={"category": "average"}))


# ---------------------------------------------------------------------------
# Non-quota failures keep their fallback (unchanged behaviour)
# ---------------------------------------------------------------------------


def test_non_quota_failure_still_returns_the_half_fallback():
    client = LMStudioClient()
    client.chat_completions = AsyncMock(side_effect=AIClientError("LM Studio API error: 500"))

    result = asyncio.run(client.analyze_text("description", "prompt"))

    assert result.sentiment_score == 0.5
    assert result.analysis == "Error"


def test_non_quota_failure_still_returns_the_template_verdict():
    client = LMStudioClient()
    client.chat_completions = AsyncMock(side_effect=AIClientError("LM Studio API error: 500"))

    result = asyncio.run(client.summarize_deal(stat_analysis={"category": "average"}))

    assert result.confidence == 0.0
    assert result.verdict  # deterministic template, not an exception


def test_invalid_json_still_falls_back_not_raises():
    client = LMStudioClient()
    client.chat_completions = AsyncMock(return_value=_chat("not json"))

    result = asyncio.run(client.analyze_text("description", "prompt"))

    assert result.sentiment_score == 0.5


def test_happy_path_is_untouched():
    client = GeminiClient(api_key="k")
    client.chat_completions = AsyncMock(
        return_value=_chat(json.dumps({"sentiment_score": 0.8, "category": "good"}))
    )

    result = asyncio.run(client.analyze_text("nice place", "prompt"))

    assert result.sentiment_score == 0.8


# ---------------------------------------------------------------------------
# Follow-up review pass (v0.13-s1.3): quota detection breadth + error detail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,body",
    [
        (403, '{"error": {"message": "Quota exceeded for quota metric"}}'),
        (400, '{"error": {"code": "rate_limit_exceeded"}}'),
        (403, "Rate limit exceeded for this project"),
    ],
)
def test_quota_refusals_outside_429_are_still_quota_errors(status, body):
    """Not every quota refusal arrives as 429 with RESOURCE_EXHAUSTED.

    Reading one as an ordinary error resumes fabricating 0.5 scores for every
    remaining row — the exact data corruption this story exists to stop.
    """
    client = _client_with_status(status, body)

    with pytest.raises(AIQuotaExhaustedError):
        asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))


def test_non_quota_error_message_carries_the_response_body():
    """``core``'s text-matching safety net needs something to match on.

    A message carrying only the status code made the last line of defence for an
    untagged quota refusal structurally unreachable.
    """
    client = _client_with_status(500, "upstream said: too many requests, back off")

    with pytest.raises(AIClientError) as exc:
        asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))

    assert "too many requests" in str(exc.value)
    assert is_quota_exhausted(exc.value) is True
