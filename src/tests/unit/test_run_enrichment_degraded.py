"""``run_enrichment`` must never persist a score built from a degraded result.

The regression (DW-17): a revoked ``GEMINI_API_KEY`` (401), a retired model id
(404) or a DNS/proxy outage is none of ``_RETRY_STATUS`` or
``_QUOTA_BODY_MARKERS``, so ``analyze_visuals`` / ``analyze_text`` returned their
``0.5`` fallback, ``run_enrichment`` blended it into ``ai_score = 0.5``,
persisted and committed it — and ``mode_is_missing_ai`` (``not score``) never
re-queued the row again, because ``0.5`` is truthy.

The gate raises **before** ``SessionLocal()``, which is what makes "nothing was
persisted, nothing was committed" provable rather than argued: every test here
hands ``run_enrichment`` a session factory that fails loudly if it is called at
all. Hermetic — no DB, no network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.ai.client import AIResultDegradedError, SentimentResult, VisualResult
from adapters.ai.enrich_pipeline import neutral_sentiment_no_description

pytestmark = pytest.mark.unit


def _cfg():
    return SimpleNamespace(
        ai=SimpleNamespace(
            max_images_per_property=8,
            max_description_chars=2000,
            visual_weight=0.6,
            text_weight=0.4,
        ),
        scoring=SimpleNamespace(
            stat_weight=0.4, ai_weight=0.4, neighbourhood_weight=0.2
        ),
    )


def _image_store():
    store = MagicMock()
    store.download_images = AsyncMock(return_value=["/tmp/a.jpg"])
    return store


class _ForbiddenSessionLocal:
    """Session factory that proves the gate raised before any DB work started."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError(
            "run_enrichment opened a DB session for a degraded result — the "
            "fabricated score would have been persisted and committed"
        )


def _run(tasks_mod, session_local, *, visual, sentiment, description="nice flat",
         stages="all", client=None):
    client = client or MagicMock()
    with (
        patch.object(tasks_mod, "SessionLocal", session_local),
        patch.object(
            tasks_mod,
            "analyze_visual_and_sentiment",
            new=AsyncMock(return_value=(visual, sentiment)),
        ),
        patch.object(tasks_mod, "build_visual_condition_prompt", return_value="vp"),
        patch.object(tasks_mod, "build_sentiment_prompt", return_value="sp"),
        patch.object(tasks_mod, "resolve_ai_output_language", return_value="pt-BR"),
        patch.object(tasks_mod, "assign_property_neighbourhood"),
        patch.object(tasks_mod, "score_single_property"),
    ):
        return asyncio.run(
            tasks_mod.run_enrichment(
                client,
                _image_store(),
                "11111111-1111-1111-1111-111111111111",
                ["https://cdn.example/1.jpg"],
                description,
                stages,
                _cfg(),
            )
        )


# ---------------------------------------------------------------------------
# Degraded in → nothing out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "visual,sentiment",
    [
        pytest.param(
            VisualResult(condition_score=0.5, analysis="Error", degraded=True),
            SentimentResult(sentiment_score=0.8, analysis="ok"),
            id="visual-degraded",
        ),
        pytest.param(
            VisualResult(condition_score=0.7, analysis="ok"),
            SentimentResult(sentiment_score=0.5, analysis="Error", degraded=True),
            id="sentiment-degraded",
        ),
        pytest.param(
            VisualResult(condition_score=0.5, analysis="Error", degraded=True),
            SentimentResult(sentiment_score=0.5, analysis="Error", degraded=True),
            id="both-degraded",
        ),
    ],
)
def test_a_degraded_result_raises_and_opens_no_session(visual, sentiment):
    from adapters.queue import tasks as tasks_mod

    session_local = _ForbiddenSessionLocal()

    with pytest.raises(AIResultDegradedError):
        _run(tasks_mod, session_local, visual=visual, sentiment=sentiment)

    assert session_local.calls == 0


def test_the_raised_error_carries_the_duck_typed_marker_the_runner_reads():
    """``src/core`` must not import adapters (AD-1), so the runner keys on the
    attribute — and the message must stay clear of the quota markers, or the
    quota predicate's text safety net would misread it as a 429."""
    from adapters.queue import tasks as tasks_mod
    from core.backfill_runner import _QUOTA_MARKERS, is_degraded_result, is_quota_exhausted

    with pytest.raises(AIResultDegradedError) as exc:
        _run(
            tasks_mod,
            _ForbiddenSessionLocal(),
            visual=VisualResult(condition_score=0.5, analysis="Error", degraded=True),
            sentiment=SentimentResult(sentiment_score=0.5, analysis="Error"),
        )

    assert is_degraded_result(exc.value) is True
    assert is_quota_exhausted(exc.value) is False
    message = str(exc.value).lower()
    assert not any(marker in message for marker in _QUOTA_MARKERS)


# ---------------------------------------------------------------------------
# Honest results still persist exactly as they did
# ---------------------------------------------------------------------------


def _persisting_session(ms):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = ms
    session.get.return_value = SimpleNamespace(neighborhood_id=None, props_json=None)
    return session


def test_an_undegraded_result_persists_and_commits_as_before():
    from adapters.queue import tasks as tasks_mod

    ms = SimpleNamespace(meta={}, ai_score=None, stat_score=0.5, combined_score=0.0)
    session = _persisting_session(ms)

    a_score, _v, _s, _paths = _run(
        tasks_mod,
        MagicMock(return_value=session),
        visual=VisualResult(condition_score=0.7, analysis="ok"),
        sentiment=SentimentResult(sentiment_score=0.6, analysis="ok"),
        stages="visual+sentiment",
    )

    assert a_score == pytest.approx(0.7 * 0.6 + 0.6 * 0.4)
    assert ms.ai_score == pytest.approx(a_score)
    session.commit.assert_called_once()


def test_a_property_with_no_description_is_not_a_degraded_result():
    """``neutral_sentiment_no_description()`` is an honest 0.5 (BIN-243) — the
    marker distinguishes it from a fabricated one, not the score value."""
    from adapters.queue import tasks as tasks_mod

    neutral = neutral_sentiment_no_description()
    assert neutral.degraded is False

    ms = SimpleNamespace(meta={}, ai_score=None, stat_score=0.5, combined_score=0.0)
    session = _persisting_session(ms)

    a_score, _v, s_res, _paths = _run(
        tasks_mod,
        MagicMock(return_value=session),
        visual=VisualResult(condition_score=0.8, analysis="ok"),
        sentiment=neutral,
        description="",
        stages="visual+sentiment",
    )

    assert s_res.sentiment_score == 0.5
    assert a_score == pytest.approx(0.8 * 0.6 + 0.5 * 0.4)
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# A degraded *verdict* is recorded, not refused
# ---------------------------------------------------------------------------


def test_a_degraded_verdict_is_marked_in_meta_and_still_persists():
    """The verdict never touches ``ai_score``, so a template fallback cannot
    retire a row — it is recorded honestly instead of blocking the write."""
    from adapters.ai.client import DealVerdictResult
    from adapters.queue import tasks as tasks_mod

    ms = SimpleNamespace(meta={}, ai_score=None, stat_score=0.5, combined_score=0.0)
    session = _persisting_session(ms)
    client = MagicMock()
    client.summarize_deal = AsyncMock(
        return_value=DealVerdictResult(
            verdict="Template verdict", confidence=0.0, degraded=True
        )
    )

    _run(
        tasks_mod,
        MagicMock(return_value=session),
        visual=VisualResult(condition_score=0.7, analysis="ok"),
        sentiment=SentimentResult(sentiment_score=0.6, analysis="ok"),
        stages="all",
        client=client,
    )

    assert ms.meta["deal_verdict"] == {
        "verdict": "Template verdict",
        "confidence": 0.0,
        "degraded": True,
    }
    session.commit.assert_called_once()


def test_the_live_celery_path_retries_instead_of_committing_a_fabricated_score():
    """The gate is in the single write authority (AD-10), so the live
    ``ai_enrich`` task stops fabricating too — through its existing retry policy
    (``max_retries=5``), which this change does not touch."""
    from adapters.queue import tasks as tasks_mod

    session_local = _ForbiddenSessionLocal()
    redis = MagicMock()
    redis.exists.return_value = False
    sem = MagicMock()
    sem.acquire.return_value = True
    client = MagicMock()
    client.session_context = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=None)
        )
    )
    degraded = (
        VisualResult(condition_score=0.5, analysis="Error", degraded=True),
        SentimentResult(sentiment_score=0.5, analysis="Error", degraded=True),
    )

    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "get_config") as mock_cfg,
        patch.object(tasks_mod, "GPUSemaphore", return_value=sem),
        patch.object(tasks_mod, "ImageStore", return_value=_image_store()),
        patch.object(tasks_mod, "create_enrichment_client", return_value=client),
        patch.object(tasks_mod, "SessionLocal", session_local),
        patch.object(
            tasks_mod,
            "analyze_visual_and_sentiment",
            new=AsyncMock(return_value=degraded),
        ),
        patch.object(tasks_mod, "build_visual_condition_prompt", return_value="vp"),
        patch.object(tasks_mod, "build_sentiment_prompt", return_value="sp"),
    ):
        mock_cfg.return_value.gpu.semaphore_limit = 1
        mock_cfg.return_value.ai.max_images_per_property = 8
        mock_cfg.return_value.ai.max_description_chars = 2000
        mock_cfg.return_value.ai.visual_weight = 0.6
        mock_cfg.return_value.ai.text_weight = 0.4

        # Called directly (no worker), Celery's ``retry`` re-raises the original
        # exception rather than scheduling — so this *is* the retry branch.
        with pytest.raises(AIResultDegradedError):
            tasks_mod.ai_enrich.run(
                "44444444-4444-4444-4444-444444444444",
                ["https://cdn.example/1.jpg"],
                "nice",
                stages="visual+sentiment",
            )

    assert session_local.calls == 0
    sem.release.assert_called_once()  # the retry path still frees the GPU slot


def test_an_honest_verdict_is_marked_undegraded():
    from adapters.ai.client import DealVerdictResult
    from adapters.queue import tasks as tasks_mod

    ms = SimpleNamespace(meta={}, ai_score=None, stat_score=0.5, combined_score=0.0)
    session = _persisting_session(ms)
    client = MagicMock()
    client.summarize_deal = AsyncMock(
        return_value=DealVerdictResult(verdict="Good deal", confidence=0.8)
    )

    _run(
        tasks_mod,
        MagicMock(return_value=session),
        visual=VisualResult(condition_score=0.7, analysis="ok"),
        sentiment=SentimentResult(sentiment_score=0.6, analysis="ok"),
        stages="all",
        client=client,
    )

    assert ms.meta["deal_verdict"]["degraded"] is False
