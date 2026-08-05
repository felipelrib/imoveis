"""Unit tests for per-task-class enrichment routing (v0.13-s1.2).

Covers the single routing authority in ``adapters.ai.client``:

- ``resolve_enrichment_backend`` for every I/O-matrix row (local-default,
  local-explicit, cloud-degrade live, cloud-eligible backfill, cloud-unavailable
  backfill).
- ``cloud_available`` true/false.
- ``create_ai_client(task_class=…)`` returns a **local** client even when the
  routing entry is cloud (never Gemini/Gemma on the live path).
- ``RoutingAIClient`` per-task-class dispatch, distinct-backend dedup, and
  never-cloud provisioning.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.ai import client as client_mod
from adapters.ai.client import (
    GeminiClient,
    GemmaClient,
    LMStudioClient,
    OllamaClient,
    RoutingAIClient,
    cloud_available,
    create_ai_client,
    create_enrichment_client,
    resolve_enrichment_backend,
)
from core.enrichment import EnrichmentTaskClass

# Full default routing map (every task class present, as story 1.1 validates).
_DEFAULT_ROUTING = {
    "visual": "ollama",
    "sentiment": "ollama",
    "deal_verdict": "ollama",
    "valuation": "ollama",
    "embedding": "ollama",
}


def _cfg(routing=None, *, backend="ollama", gemini_api_key=""):
    """Build a fake top-level config object with a fully-populated ``.ai``.

    Uses ``SimpleNamespace`` (not the frozen ``AIConfig``) so tests can express
    arbitrary routing/backend combinations without re-running story 1.1's
    load-time validators — routing resolution is the unit under test here.
    """
    ai = SimpleNamespace(
        backend=backend,
        enrichment_routing=dict(routing or _DEFAULT_ROUTING),
        gemini_api_key=gemini_api_key,
        gemini_url="https://example.invalid/openai",
        gemini_model="gemini-2.5-flash",
        gemma_model="gemma-4-31b-it",
        ollama_url="http://ollama:11434",
        lmstudio_url="http://lmstudio:1234",
        visual_model="vlm",
        text_model="txt",
        embedding_model="emb",
        num_ctx=8192,
        max_tokens=1024,
        timeout=60,
    )
    return SimpleNamespace(ai=ai)


# ---------------------------------------------------------------------------
# resolve_enrichment_backend — I/O matrix
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_local_default():
    cfg = _cfg({**_DEFAULT_ROUTING, "visual": "ollama"}, backend="ollama")
    assert (
        resolve_enrichment_backend(EnrichmentTaskClass.VISUAL, cfg) == "ollama"
    )


@pytest.mark.unit
def test_resolve_local_explicit_map_wins():
    # A local routing value that differs from the scalar is honored directly.
    cfg = _cfg({**_DEFAULT_ROUTING, "sentiment": "lmstudio"}, backend="ollama")
    assert (
        resolve_enrichment_backend(EnrichmentTaskClass.SENTIMENT, cfg)
        == "lmstudio"
    )


@pytest.mark.unit
def test_resolve_cloud_degrades_to_scalar_on_live(caplog):
    cfg = _cfg({**_DEFAULT_ROUTING, "visual": "gemma"}, backend="ollama")
    # Live degrade is the designed steady state → DEBUG, not WARNING (no flood).
    with caplog.at_level("DEBUG"):
        got = resolve_enrichment_backend(EnrichmentTaskClass.VISUAL, cfg)
    assert got == "ollama"  # degrade to validated-local scalar, never cloud
    degrade = [rec for rec in caplog.records if "degraded" in rec.message]
    assert degrade and all(rec.levelname == "DEBUG" for rec in degrade)


@pytest.mark.unit
def test_resolve_cloud_degrade_on_live_is_not_warning(caplog):
    cfg = _cfg({**_DEFAULT_ROUTING, "visual": "gemma"}, backend="ollama")
    with caplog.at_level("WARNING"):
        resolve_enrichment_backend(EnrichmentTaskClass.VISUAL, cfg)
    # No WARNING flood for the expected live-path cloud degrade.
    assert not [rec for rec in caplog.records if "degraded" in rec.message]


@pytest.mark.unit
def test_resolve_cloud_honored_for_backfill_with_key():
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "deal_verdict": "gemma"},
        backend="ollama",
        gemini_api_key="secret-key",
    )
    got = resolve_enrichment_backend(
        EnrichmentTaskClass.DEAL_VERDICT, cfg, for_backfill=True
    )
    assert got == "gemma"


@pytest.mark.unit
def test_resolve_cloud_unavailable_for_backfill_degrades(caplog):
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "deal_verdict": "gemma"},
        backend="ollama",
        gemini_api_key="",
    )
    with caplog.at_level("WARNING"):
        got = resolve_enrichment_backend(
            EnrichmentTaskClass.DEAL_VERDICT, cfg, for_backfill=True
        )
    assert got == "ollama"  # no key → degrade, never raise (NFR-4)
    assert any("degraded" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_resolve_local_value_honored_even_for_backfill():
    cfg = _cfg({**_DEFAULT_ROUTING, "visual": "lmstudio"}, backend="ollama")
    assert (
        resolve_enrichment_backend(
            EnrichmentTaskClass.VISUAL, cfg, for_backfill=True
        )
        == "lmstudio"
    )


# ---------------------------------------------------------------------------
# cloud_available
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cloud_available_true_with_key():
    assert cloud_available(_cfg(gemini_api_key="k")) is True


@pytest.mark.unit
def test_cloud_available_false_without_key():
    assert cloud_available(_cfg(gemini_api_key="")) is False


@pytest.mark.unit
def test_cloud_available_false_for_whitespace_key():
    # A whitespace-only key cannot authenticate — treated as absent.
    assert cloud_available(_cfg(gemini_api_key="   ")) is False


@pytest.mark.unit
def test_build_local_client_rejects_cloud_backend():
    from adapters.ai.client import _build_local_client

    with pytest.raises(ValueError):
        _build_local_client("gemma", _cfg())
    with pytest.raises(ValueError):
        _build_local_client("gemini", _cfg())


@pytest.mark.unit
def test_build_local_client_unknown_noncloud_defaults_to_ollama():
    from adapters.ai.client import _build_local_client

    # Historical behavior preserved: an unknown *non-cloud* string → Ollama.
    got = _build_local_client("frobnicate", _cfg())
    assert isinstance(got, OllamaClient)


# ---------------------------------------------------------------------------
# create_ai_client(task_class=…) — local only, even for cloud routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_ai_client_task_class_cloud_entry_returns_local(monkeypatch):
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "gemma"},
        backend="ollama",
        gemini_api_key="secret-key",  # key present, but live path ignores cloud
    )
    monkeypatch.setattr(
        "infra.config.get_config", lambda: cfg, raising=False
    )
    got = create_ai_client(task_class=EnrichmentTaskClass.VISUAL)
    assert isinstance(got, OllamaClient)
    assert not isinstance(got, (GeminiClient, GemmaClient))


@pytest.mark.unit
def test_create_ai_client_task_class_local_map_wins(monkeypatch):
    cfg = _cfg({**_DEFAULT_ROUTING, "sentiment": "lmstudio"}, backend="ollama")
    monkeypatch.setattr(
        "infra.config.get_config", lambda: cfg, raising=False
    )
    got = create_ai_client(task_class=EnrichmentTaskClass.SENTIMENT)
    assert isinstance(got, LMStudioClient)


@pytest.mark.unit
def test_create_ai_client_embedding_local(monkeypatch):
    cfg = _cfg({**_DEFAULT_ROUTING, "embedding": "gemma"}, backend="ollama")
    monkeypatch.setattr(
        "infra.config.get_config", lambda: cfg, raising=False
    )
    got = create_ai_client(task_class=EnrichmentTaskClass.EMBEDDING)
    assert isinstance(got, OllamaClient)
    assert not isinstance(got, (GeminiClient, GemmaClient))


# ---------------------------------------------------------------------------
# RoutingAIClient — dispatch, dedup, never-cloud
# ---------------------------------------------------------------------------


def _tagged_client(backend):
    """A fake local client tagged with its backend and async method spies."""
    m = MagicMock(name=f"client[{backend}]")
    m.backend = backend
    m.analyze_visuals = AsyncMock(return_value=f"visual::{backend}")
    m.analyze_text = AsyncMock(return_value=f"text::{backend}")
    m.summarize_deal = AsyncMock(return_value=f"verdict::{backend}")
    m.embed = AsyncMock(return_value=f"embed::{backend}")
    m.close = AsyncMock()
    return m


def _patch_build_local(monkeypatch):
    """Make ``_build_local_client`` return one tagged client per backend."""
    built: dict[str, MagicMock] = {}

    def fake_build(backend, cfg):
        assert backend in ("ollama", "lmstudio"), (
            f"live path must never build a cloud client, got {backend!r}"
        )
        built.setdefault(backend, _tagged_client(backend))
        return built[backend]

    monkeypatch.setattr(client_mod, "_build_local_client", fake_build)
    return built


@pytest.mark.unit
def test_routing_client_dispatches_each_method_to_its_backend(monkeypatch):
    built = _patch_build_local(monkeypatch)
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "ollama", "sentiment": "lmstudio"},
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (
            EnrichmentTaskClass.VISUAL,
            EnrichmentTaskClass.SENTIMENT,
            EnrichmentTaskClass.DEAL_VERDICT,
        ),
    )

    assert asyncio.run(rc.analyze_visuals(["a"], "p")) == "visual::ollama"
    assert asyncio.run(rc.analyze_text("d", "p")) == "text::lmstudio"

    built["ollama"].analyze_visuals.assert_awaited_once()
    built["lmstudio"].analyze_text.assert_awaited_once()
    # The visual (ollama) client must NOT have handled the sentiment call.
    built["ollama"].analyze_text.assert_not_awaited()


@pytest.mark.unit
def test_routing_client_dedups_shared_backend_to_one_client(monkeypatch):
    _patch_build_local(monkeypatch)
    cfg = _cfg(
        {
            **_DEFAULT_ROUTING,
            "visual": "ollama",
            "sentiment": "lmstudio",
            "deal_verdict": "ollama",
        },
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (
            EnrichmentTaskClass.VISUAL,
            EnrichmentTaskClass.SENTIMENT,
            EnrichmentTaskClass.DEAL_VERDICT,
        ),
    )
    # visual + deal_verdict share the single ollama client; sentiment is its own.
    assert len(rc._clients) == 2
    assert (
        rc._by_task[EnrichmentTaskClass.VISUAL]
        is rc._by_task[EnrichmentTaskClass.DEAL_VERDICT]
    )
    assert (
        rc._by_task[EnrichmentTaskClass.SENTIMENT]
        is not rc._by_task[EnrichmentTaskClass.VISUAL]
    )


@pytest.mark.unit
def test_routing_client_default_all_ollama_builds_one_client(monkeypatch):
    _patch_build_local(monkeypatch)
    rc = create_enrichment_client(_cfg(backend="ollama"))
    assert len(rc._clients) == 1


@pytest.mark.unit
def test_routing_client_never_builds_cloud_client(monkeypatch):
    # Every task class routed to cloud; live path must degrade all to scalar.
    _patch_build_local(monkeypatch)
    cloud_routing = {k: "gemma" for k in _DEFAULT_ROUTING}
    cfg = _cfg(cloud_routing, backend="ollama", gemini_api_key="secret-key")
    rc = RoutingAIClient(
        cfg,
        (
            EnrichmentTaskClass.VISUAL,
            EnrichmentTaskClass.SENTIMENT,
            EnrichmentTaskClass.DEAL_VERDICT,
        ),
    )
    assert list(rc._clients.keys()) == ["ollama"]
    assert all(c.backend == "ollama" for c in rc._clients.values())


@pytest.mark.unit
def test_routing_client_unprovisioned_task_raises(monkeypatch):
    _patch_build_local(monkeypatch)
    cfg = _cfg(backend="ollama")
    rc = RoutingAIClient(cfg, (EnrichmentTaskClass.VISUAL,))
    with pytest.raises(ValueError):
        asyncio.run(rc.embed("x"))


@pytest.mark.unit
def test_routing_client_session_context_opens_each_client(monkeypatch):
    built = _patch_build_local(monkeypatch)

    # Give each tagged client a real async session_context spy.
    entered: list[str] = []

    def _make_ctx(backend):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            entered.append(backend)
            yield None

        return _ctx

    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "ollama", "sentiment": "lmstudio"},
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT),
    )
    for backend, c in built.items():
        c.session_context = _make_ctx(backend)

    async def _run():
        async with rc.session_context() as yielded:
            assert yielded is rc

    asyncio.run(_run())
    assert sorted(entered) == ["lmstudio", "ollama"]


@pytest.mark.unit
def test_routing_client_close_closes_all(monkeypatch):
    built = _patch_build_local(monkeypatch)
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "ollama", "sentiment": "lmstudio"},
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT),
    )
    asyncio.run(rc.close())
    built["ollama"].close.assert_awaited_once()
    built["lmstudio"].close.assert_awaited_once()


@pytest.mark.unit
def test_routing_client_close_is_best_effort(monkeypatch):
    # One client's close() raising must not strand the others' teardown.
    built = _patch_build_local(monkeypatch)
    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "ollama", "sentiment": "lmstudio"},
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT),
    )
    built["ollama"].close = AsyncMock(side_effect=RuntimeError("boom"))
    asyncio.run(rc.close())  # must not raise
    built["lmstudio"].close.assert_awaited_once()


@pytest.mark.unit
def test_routing_client_async_with_opens_and_closes_all(monkeypatch):
    # The ``async with client:`` idiom must manage every underlying session
    # (not leak them by only managing the empty-URL wrapper).
    built = _patch_build_local(monkeypatch)
    entered: list[str] = []
    exited: list[str] = []

    def _make_ctx(backend):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            entered.append(backend)
            try:
                yield None
            finally:
                exited.append(backend)

        return _ctx

    cfg = _cfg(
        {**_DEFAULT_ROUTING, "visual": "ollama", "sentiment": "lmstudio"},
        backend="ollama",
    )
    rc = RoutingAIClient(
        cfg,
        (EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT),
    )
    for backend, c in built.items():
        c.session_context = _make_ctx(backend)

    async def _run():
        async with rc as yielded:
            assert yielded is rc

    asyncio.run(_run())
    assert sorted(entered) == ["lmstudio", "ollama"]
    assert sorted(exited) == ["lmstudio", "ollama"]


@pytest.mark.unit
def test_create_enrichment_client_empty_task_classes_defaults_to_trio(monkeypatch):
    _patch_build_local(monkeypatch)
    # Explicit empty tuple must behave like the default, not provision nothing.
    rc = create_enrichment_client(_cfg(backend="ollama"), task_classes=())
    for tc in (
        EnrichmentTaskClass.VISUAL,
        EnrichmentTaskClass.SENTIMENT,
        EnrichmentTaskClass.DEAL_VERDICT,
    ):
        assert tc in rc._by_task
