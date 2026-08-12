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
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from adapters.ai.client import (
    AIClientError,
    AIQuotaExhaustedError,
    AIResultDegradedError,
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
    # v0.13-s3.2: the *value* is unchanged — what is new is that the result says
    # it was fabricated, so ``run_enrichment`` can refuse to persist it (DW-17).
    assert result.degraded is True


def test_non_quota_failure_still_returns_the_template_verdict():
    client = LMStudioClient()
    client.chat_completions = AsyncMock(side_effect=AIClientError("LM Studio API error: 500"))

    result = asyncio.run(client.summarize_deal(stat_analysis={"category": "average"}))

    assert result.confidence == 0.0
    assert result.verdict  # deterministic template, not an exception
    assert result.degraded is True


def test_invalid_json_still_falls_back_not_raises():
    client = LMStudioClient()
    client.chat_completions = AsyncMock(return_value=_chat("not json"))

    result = asyncio.run(client.analyze_text("description", "prompt"))

    assert result.sentiment_score == 0.5
    assert result.degraded is True


def test_happy_path_is_untouched():
    client = GeminiClient(api_key="k")
    client.chat_completions = AsyncMock(
        return_value=_chat(json.dumps({"sentiment_score": 0.8, "category": "good"}))
    )

    result = asyncio.run(client.analyze_text("nice place", "prompt"))

    assert result.sentiment_score == 0.8
    assert result.degraded is False


# ---------------------------------------------------------------------------
# The two markers never overlap: a quota refusal is not a degraded result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [LMStudioClient, GeminiClient, GemmaClient])
def test_a_quota_refusal_raises_instead_of_returning_a_degraded_result(cls):
    """``_reraise_if_quota`` fires first, so the two paths can never both run:
    a quota error must reach the runner as quota (back off, blame nobody), not
    as a degraded row (charge an error, feed the breaker)."""
    client = cls(api_key="k") if cls is not LMStudioClient else cls()
    client.chat_completions = AsyncMock(side_effect=AIQuotaExhaustedError("429 quota"))

    with pytest.raises(AIQuotaExhaustedError) as exc:
        asyncio.run(client.analyze_text("description", "prompt"))

    assert getattr(exc.value, "is_degraded_result", False) is False


def test_the_degraded_error_is_recognised_by_the_core_predicate():
    """Mirror of the quota contract: duck-typed, never an adapters import."""
    from core.backfill_runner import is_degraded_result

    assert AIResultDegradedError.is_degraded_result is True
    assert is_degraded_result(AIResultDegradedError("visual fell back"))
    assert not is_degraded_result(AIClientError("Gemini API error: 500"))
    assert not is_degraded_result(AIQuotaExhaustedError("Gemini quota exhausted: 429"))
    # …and it is not read as a quota refusal, which would trigger a 24h back-off.
    assert not is_quota_exhausted(AIResultDegradedError("visual fell back"))


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


# ---------------------------------------------------------------------------
# Transport-shaped throttles (DW-7 / v0.13-fu8)
#
# A provider throttle does not always arrive as a 429 body: past the ceiling the
# endpoint can simply stop answering, so every attempt dies as a connection reset
# or a timeout. That used to re-raise untagged, the runner read it as a hard row
# error, and the attempt charged before launch stood — burning ``max_attempts``
# on good rows inside one throttle window. Inference is deliberately narrow: EVERY
# attempt failed with the SAME transport signature AND the provider itself said
# 429/quota inside the recency window. Everything else stays a hard error.
# ---------------------------------------------------------------------------


def _transport_client(
    effects,
    *,
    cls=GeminiClient,
    max_retries=None,
    window=300.0,
    throttled_ago=None,
):
    """Client whose ``session.post`` replays ``effects`` (exceptions or ctxs).

    ``throttled_ago`` stamps the recency clock as if the provider had answered
    429 that many seconds ago; ``None`` means no throttle was ever observed.
    """
    client = cls(
        api_key="k",
        max_retries=max_retries if max_retries is not None else len(effects),
        transport_quota_window_seconds=window,
    )
    client._sleep_backoff = AsyncMock(return_value=0.0)  # no real backoff sleep
    client.session = MagicMock()
    client.session.post.side_effect = list(effects)
    if throttled_ago is not None:
        client.last_rate_limit_at = time.monotonic() - throttled_ago
    return client


def _reset(message="Connection reset by peer"):
    return aiohttp.ClientConnectionError(message)


def _call(client):
    return asyncio.run(client.chat_completions("m", [{"role": "user", "content": "hi"}]))


def _http_response(status, body):
    response = AsyncMock(status=status)
    response.text.return_value = body
    return _ctx(response)


@pytest.mark.parametrize("cls", [GeminiClient, GemmaClient])
def test_identical_connection_storm_inside_the_window_is_read_as_quota(cls):
    """The DW-7 bug: this used to propagate untagged and charge the row."""
    client = _transport_client([_reset(), _reset(), _reset()], cls=cls, throttled_ago=10.0)

    with pytest.raises(AIQuotaExhaustedError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is True
    # The runner's text net is the backstop for anything the adapter fails to
    # tag, so the message must match it even though the flag already does.
    assert any(
        marker in str(exc.value).lower()
        for marker in ("quota exhausted", "quota exceeded", "resource_exhausted")
    )
    # The raw transport error stays attached for the operator.
    assert isinstance(exc.value.__cause__, aiohttp.ClientError)


def test_identical_timeout_storm_inside_the_window_is_read_as_quota():
    client = _transport_client(
        [asyncio.TimeoutError(), asyncio.TimeoutError()], throttled_ago=10.0
    )

    with pytest.raises(AIQuotaExhaustedError):
        _call(client)


def test_inference_is_audited_and_never_counts_as_an_observed_rate_limit(caplog):
    """``rate_limit_hits`` means "the provider said 429" — inference is separate."""
    client = _transport_client([_reset(), _reset()], throttled_ago=10.0)
    hits_before = client.rate_limit_hits

    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        with pytest.raises(AIQuotaExhaustedError):
            _call(client)

    assert client.transport_quota_inferences == 1
    assert client.rate_limit_hits == hits_before
    warning = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    )
    assert "gemini_transport_quota_inferred" in warning
    assert "ClientConnectionError" in warning  # the repeated failure signature
    assert "300.0" in warning  # ...and the window it was judged against
    # ``last_error`` distinguishes an inference from a plain connection failure.
    assert "connection:" not in client.last_error
    assert "quota" in client.last_error.lower()


def test_genuine_outage_with_no_observed_throttle_stays_a_hard_error():
    client = _transport_client([_reset(), _reset(), _reset()], throttled_ago=None)

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0
    assert client.last_error.startswith("connection:")


def test_storm_after_a_stale_throttle_stays_a_hard_error():
    """A 429 seen an hour ago licenses nothing — the quota window has rolled."""
    client = _transport_client(
        [_reset(), _reset(), _reset()], window=300.0, throttled_ago=3600.0
    )

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_mixed_failure_shapes_stay_a_hard_error():
    """A connect error decaying into a timeout is the shape of a real outage."""
    client = _transport_client(
        [_reset("reset by peer"), asyncio.TimeoutError()], throttled_ago=10.0
    )

    with pytest.raises((aiohttp.ClientError, asyncio.TimeoutError)) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_differing_messages_of_one_exception_type_stay_a_hard_error():
    client = _transport_client([_reset("reset A"), _reset("reset B")], throttled_ago=10.0)

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_messages_that_differ_only_past_a_truncation_point_stay_distinct():
    """Signatures are compared in full; a shared long prefix must not collapse."""
    shared = "Cannot connect to host generativelanguage.googleapis.com:443 " + "x" * 160
    client = _transport_client(
        [_reset(shared + "-errno-104"), _reset(shared + "-errno-110")], throttled_ago=10.0
    )

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_storm_that_followed_a_real_http_response_stays_a_hard_error():
    """Attempt 0 got a 503 — the endpoint was answering, so this is not a throttle."""
    client = _transport_client(
        [_http_response(503, "unavailable"), _reset(), _reset()],
        max_retries=3,
        throttled_ago=10.0,
    )

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_single_attempt_client_stays_a_hard_error():
    """With ``max_retries=1`` "every attempt failed identically" is vacuous."""
    client = _transport_client([_reset()], max_retries=1, throttled_ago=10.0)

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_zero_window_disables_the_inference_entirely():
    client = _transport_client(
        [_reset(), _reset(), _reset()], window=0.0, throttled_ago=1.0
    )

    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_a_negative_window_is_floored_to_disabled_and_says_so(caplog):
    """Flooring silently would disable a safety feature with no signal."""
    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        client = _transport_client([_reset(), _reset()], window=-5.0, throttled_ago=1.0)

    assert client.transport_quota_window_seconds == 0.0
    assert "gemini_transport_quota_window_clamped" in caplog.text
    with pytest.raises(aiohttp.ClientError):
        _call(client)
    assert client.transport_quota_inferences == 0


def test_an_observed_429_stamps_the_recency_clock():
    """The HTTP path is unchanged except that it now licenses the inference."""
    client = _client_with_status(429, "rate limited")
    assert client.last_rate_limit_at is None

    with pytest.raises(AIQuotaExhaustedError):
        _call(client)

    assert client.rate_limit_hits >= 1
    assert client.last_rate_limit_at is not None
    assert time.monotonic() - client.last_rate_limit_at < 5.0


def test_a_retried_429_also_stamps_the_clock_for_a_later_storm():
    """The 429 that licenses a storm is usually the *retry* hit, not the final one.

    One long-lived client serves every concurrent backfill row, so a throttle
    observed on row A is the evidence for row B's storm — the quota is
    per-project, not per-call.
    """
    throttled = _client_with_status(429, "rate limited")
    with pytest.raises(AIQuotaExhaustedError):
        _call(throttled)

    # Same client, next call: the endpoint has stopped answering entirely.
    throttled.session.post.side_effect = [_reset(), _reset()]
    throttled.max_retries = 2

    with pytest.raises(AIQuotaExhaustedError):
        _call(throttled)

    assert throttled.transport_quota_inferences == 1


def test_a_successful_response_cancels_the_throttle_recency():
    """A 200 proves the provider is answering — the licence must lapse with it.

    A paced free-tier run collects retried 429s routinely and recovers from
    them. Without this, every one of those would license the inference for the
    next window, so an unrelated local network drop would read as quota.
    """
    client = _transport_client([], max_retries=2, throttled_ago=10.0)
    ok = AsyncMock(status=200)
    ok.json.return_value = _chat("{}")
    client.session.post.side_effect = [_ctx(ok)]

    _call(client)
    assert client.last_rate_limit_at is None

    # Now the endpoint dies. With no live throttle this is an outage.
    client.session.post.side_effect = [_reset(), _reset()]
    with pytest.raises(aiohttp.ClientError) as exc:
        _call(client)

    assert is_quota_exhausted(exc.value) is False
    assert client.transport_quota_inferences == 0


def test_a_failed_body_read_is_not_a_dead_socket():
    """``ContentTypeError``/``ClientPayloadError`` are ``ClientError`` subclasses.

    They are raised *after* the endpoint answered — by ``response.text()`` /
    ``.json()`` — so they land in the transport arm and leave no gap in the
    signature list. Only the explicit "did any attempt reach the endpoint" flag
    keeps an HTML throttle page or a truncated body out of the inference.
    """
    answered = AsyncMock(status=503)
    answered.text.side_effect = aiohttp.ClientPayloadError("response payload truncated")
    client = _transport_client(
        [_ctx(answered), _ctx(answered)], max_retries=2, throttled_ago=10.0
    )

    with pytest.raises(aiohttp.ClientPayloadError):
        _call(client)

    assert client.transport_quota_inferences == 0


def test_recency_is_judged_at_the_first_failure_not_at_call_end(monkeypatch):
    """Five attempts at ``ai.timeout`` each can outlive the whole window.

    A *timeout* storm — half of what DW-7 describes — would therefore never
    qualify if recency were measured when the last attempt finally gave up.

    The elapsed retry ladder is driven by a fake clock rather than a real sleep:
    a real one raced the fixture's own stamp against a deliberately tiny window,
    failing as a confusing "quota was not inferred" on a loaded box, and it was
    the only new test to cost wall-clock time. Only the client module's ``time``
    name is replaced, so asyncio's own clock is untouched.
    """
    import time as real_time

    import adapters.ai.client as client_module

    class _FakeClock:
        """Fakes ``monotonic`` and delegates the rest of the ``time`` module.

        Delegation matters: this stands in for the module's whole ``time``
        name, so without it the first unrelated ``time.time()`` added to
        ``client.py`` would break this test with an ``AttributeError`` far
        from its cause.
        """

        def __init__(self, now):
            self.now = now

        def monotonic(self):
            return self.now

        def __getattr__(self, name):
            return getattr(real_time, name)

    clock = _FakeClock(1_000.0)
    monkeypatch.setattr(client_module, "time", clock)

    # Stamped against the fake clock, so ``throttled_ago`` (which uses the test
    # module's real clock) cannot be used here.
    client = _transport_client([_reset(), _reset()], max_retries=2, window=300.0)
    client.last_rate_limit_at = clock.now - 1.0

    async def _advance_past_the_window(_backoff):
        # The ladder itself outlives the window, between the first failure and
        # the last. Judged at the first failure the throttle is 1 s old and the
        # inference holds; judged at call end it is 10 000 s stale and declines.
        clock.now += 10_000.0
        return 0.0

    client._sleep_backoff = _advance_past_the_window

    with pytest.raises(AIQuotaExhaustedError):
        _call(client)

    assert client.transport_quota_inferences == 1


def test_an_over_wide_or_non_finite_window_is_clamped_and_says_so(caplog):
    """``AIConfig`` bounds this knob; a hand-built client must not escape it.

    The high end is the dangerous direction — an unbounded window lets one 429
    license the inference indefinitely, so a dead key stops producing row errors
    at all. ``inf``/``NaN`` are wiring bugs rather than intents (``NaN`` would
    disable the inference invisibly, failing every comparison), so both resolve
    to the documented "off" value.
    """
    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        over = GeminiClient(api_key="k", transport_quota_window_seconds=86_400.0)
    assert over.transport_quota_window_seconds == GeminiClient._MAX_TRANSPORT_QUOTA_WINDOW_SECONDS
    assert "gemini_transport_quota_window_clamped" in caplog.text

    for bad in (float("inf"), float("nan")):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
            client = GeminiClient(api_key="k", transport_quota_window_seconds=bad)
        assert client.transport_quota_window_seconds == 0.0
        assert "gemini_transport_quota_window_clamped" in caplog.text

    # An in-range value is untouched and unannounced.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        ok = GeminiClient(api_key="k", transport_quota_window_seconds=300.0)
    assert ok.transport_quota_window_seconds == 300.0
    assert "gemini_transport_quota_window_clamped" not in caplog.text


def test_an_inferred_throttle_does_not_also_log_a_hard_error_traceback(caplog):
    """An inference is not a row error, so it must not read as one in the logs.

    The transport arm's ``logger.exception`` runs on the hard-error path only —
    otherwise triage sees an ERROR traceback for the storm alongside the WARNING
    that reclassifies it as quota.
    """
    client = _transport_client([_reset(), _reset()], throttled_ago=10.0)

    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        with pytest.raises(AIQuotaExhaustedError):
            _call(client)

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []

    # The hard-error path still reports the traceback it always did.
    outage = _transport_client([_reset(), _reset()], throttled_ago=None)
    with caplog.at_level(logging.WARNING, logger="adapters.ai.client"):
        with pytest.raises(aiohttp.ClientError):
            _call(outage)
    assert any(
        "Error calling Gemini API" in r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR
    )
