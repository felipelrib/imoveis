"""Unit tests for selective AI enrichment re-run (BIN-95)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.enrichment_rerun import (
    STAGES_ALL,
    STAGES_VERDICT_ONLY,
    STAGES_VISUAL_SENTIMENT,
    EnrichmentRerunParams,
    evaluate_candidate,
    has_prior_visual_sentiment,
    mode_is_missing_ai,
    run_enrichment_rerun,
)
from infra.config import AIConfig, AuthConfig, PhotoGateConfig, ScrapingConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_config(*, api_key: str = "test-valid-key") -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )


@pytest.fixture
def client_with_auth(monkeypatch: pytest.MonkeyPatch):
    auth = _auth_config()
    cfg = MagicMock()
    cfg.auth = auth
    cfg.scraping = ScrapingConfig(photo_gate=PhotoGateConfig())
    cfg.ai = AIConfig()
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


def _prop(*, image_urls, description="Nice flat", platform="zap", neighborhood_id=None):
    return SimpleNamespace(
        id=uuid4(),
        image_urls=image_urls,
        description=description,
        active=True,
        platform=platform,
        neighborhood_id=neighborhood_id,
    )


def _metrics(*, ai_score=0.8, meta=None):
    return SimpleNamespace(id=uuid4(), ai_score=ai_score, meta=meta or {})


GATE = {
    "enabled": True,
    "floor_min": 8,
    "max_images_per_property": 8,
    "coverage_ratio": 1.0,
}


@pytest.mark.unit
def test_has_prior_visual_sentiment():
    assert has_prior_visual_sentiment({"visual": {"c": 1}, "sentiment": {"s": 1}})
    assert not has_prior_visual_sentiment({"visual": {}, "sentiment": {"s": 1}})
    assert not has_prior_visual_sentiment(None)
    assert not has_prior_visual_sentiment({})


@pytest.mark.unit
def test_mode_is_missing_ai():
    assert mode_is_missing_ai(None) is True
    assert mode_is_missing_ai(_metrics(ai_score=None)) is True
    assert mode_is_missing_ai(_metrics(ai_score=0)) is True
    assert mode_is_missing_ai(_metrics(ai_score=0.0)) is True
    assert mode_is_missing_ai(_metrics(ai_score=0.5)) is False


@pytest.mark.unit
def test_evaluate_candidate_photo_gate_for_visual_stages():
    enough = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    too_few = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(3)])
    no_images = _prop(image_urls=[])

    assert evaluate_candidate(enough, None, STAGES_ALL, GATE) == ("queue", None)
    assert evaluate_candidate(too_few, None, STAGES_VISUAL_SENTIMENT, GATE)[0] == "skip_photos"
    assert evaluate_candidate(no_images, None, STAGES_ALL, GATE)[0] == "skip_images"


@pytest.mark.unit
def test_evaluate_candidate_verdict_only_requires_prior_meta():
    prop = _prop(image_urls=[])
    ok_ms = _metrics(meta={"visual": {"condition_score": 0.7}, "sentiment": {"sentiment_score": 0.6}})
    bad_ms = _metrics(meta={"visual": {"condition_score": 0.7}})

    assert evaluate_candidate(prop, ok_ms, STAGES_VERDICT_ONLY, GATE) == ("queue", None)
    assert evaluate_candidate(prop, bad_ms, STAGES_VERDICT_ONLY, GATE)[0] == "skip_prior"
    assert evaluate_candidate(prop, None, STAGES_VERDICT_ONLY, GATE)[0] == "skip_prior"


@pytest.mark.unit
def test_run_enrichment_rerun_force_vs_missing():
    unenriched = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    enriched = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    rows = [
        (unenriched, None),
        (enriched, _metrics(ai_score=0.9, meta={"enriched_at": "2026-01-01T00:00:00+00:00"})),
    ]

    enqueue = MagicMock()
    missing = run_enrichment_rerun(
        rows,
        EnrichmentRerunParams(mode="missing", stages=STAGES_ALL),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    assert missing.queued == 1
    assert missing.would_queue == 1
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["stages"] == STAGES_ALL

    enqueue.reset_mock()
    forced = run_enrichment_rerun(
        rows,
        EnrichmentRerunParams(mode="force", stages=STAGES_ALL),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    assert forced.queued == 2
    assert enqueue.call_count == 2


@pytest.mark.unit
def test_run_enrichment_rerun_stale_before():
    fresh = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    stale = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    never = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [
        (fresh, _metrics(meta={"enriched_at": "2026-07-01T00:00:00+00:00"})),
        (stale, _metrics(meta={"enriched_at": "2026-01-01T00:00:00+00:00"})),
        (never, _metrics(meta={})),
    ]
    enqueue = MagicMock()
    result = run_enrichment_rerun(
        rows,
        EnrichmentRerunParams(mode="stale_before", stages=STAGES_ALL, stale_before=cutoff),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    assert result.queued == 2
    queued_ids = {c.kwargs["property_id"] for c in enqueue.call_args_list}
    assert str(stale.id) in queued_ids
    assert str(never.id) in queued_ids
    assert str(fresh.id) not in queued_ids


@pytest.mark.unit
def test_run_enrichment_rerun_dry_run_does_not_enqueue():
    prop = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    enqueue = MagicMock()
    result = run_enrichment_rerun(
        [(prop, None)],
        EnrichmentRerunParams(mode="missing", dry_run=True),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    assert result.dry_run is True
    assert result.would_queue == 1
    assert result.queued == 0
    enqueue.assert_not_called()


@pytest.mark.unit
def test_run_enrichment_rerun_passes_stages_and_limit():
    props = [
        _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
        for _ in range(5)
    ]
    rows = [(p, None) for p in props]
    enqueue = MagicMock()
    result = run_enrichment_rerun(
        rows,
        EnrichmentRerunParams(mode="force", stages=STAGES_VERDICT_ONLY, limit=2),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    # verdict_only skips without prior meta; limit never fills so all rows skip
    assert result.queued == 0
    assert result.skipped_missing_prior_enrichment == 5

    ok_meta = {"visual": {"c": 1}, "sentiment": {"s": 1}}
    rows2 = [(p, _metrics(meta=ok_meta)) for p in props]
    enqueue.reset_mock()
    result2 = run_enrichment_rerun(
        rows2,
        EnrichmentRerunParams(mode="force", stages=STAGES_VERDICT_ONLY, limit=2),
        gate_kwargs=GATE,
        enqueue_fn=enqueue,
    )
    assert result2.queued == 2
    assert enqueue.call_count == 2
    assert enqueue.call_args.kwargs["stages"] == STAGES_VERDICT_ONLY


@pytest.mark.unit
def test_post_enrichment_rerun_force_dry_run(client_with_auth):
    client, auth = client_with_auth
    enough = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])
    ms = _metrics(ai_score=0.9)

    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)

    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.limit.return_value = query
    query.all.return_value = [(enough, ms)]

    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch("adapters.queue.tasks.ai_enrich") as mock_enrich,
        patch("api.admin.log_audit_action") as mock_audit,
    ):
        response = client.post(
            "/admin/enrichment/rerun",
            headers={"X-API-Key": auth.api_key},
            json={"mode": "force", "dry_run": True, "stages": "all"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["mode"] == "force"
    assert body["would_queue"] == 1
    assert body["queued"] == 0
    mock_enrich.apply_async.assert_not_called()
    mock_audit.assert_called_once()
    assert mock_audit.call_args.args[0] == "enrichment_rerun"


@pytest.mark.unit
def test_post_enrichment_rerun_queues_with_stages_kwargs(client_with_auth):
    client, auth = client_with_auth
    enough = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])

    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.limit.return_value = query
    query.all.return_value = [(enough, None)]

    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch("adapters.queue.tasks.ai_enrich") as mock_enrich,
        patch("api.admin.log_audit_action"),
    ):
        response = client.post(
            "/admin/enrichment/rerun",
            headers={"X-API-Key": auth.api_key},
            json={"mode": "missing", "stages": "visual+sentiment"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] == 1
    mock_enrich.apply_async.assert_called_once()
    call_kwargs = mock_enrich.apply_async.call_args.kwargs
    assert call_kwargs["queue"] == "ai"
    assert call_kwargs["kwargs"] == {"stages": "visual+sentiment"}


@pytest.mark.unit
def test_post_enrichment_rerun_stale_before_requires_timestamp(client_with_auth):
    client, auth = client_with_auth
    response = client.post(
        "/admin/enrichment/rerun",
        headers={"X-API-Key": auth.api_key},
        json={"mode": "stale_before"},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_enrich_missing_wrapper_still_works(client_with_auth):
    client, auth = client_with_auth
    enough = _prop(image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)])

    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.limit.return_value = query
    query.all.return_value = [(enough, None)]

    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch("adapters.queue.tasks.ai_enrich") as mock_enrich,
        patch("api.admin.log_audit_action") as mock_audit,
    ):
        response = client.post(
            "/admin/enrichment/missing",
            headers={"X-API-Key": auth.api_key},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["queued_enrichments"] == 1
    mock_enrich.apply_async.assert_called_once()
    mock_audit.assert_called_once()
    assert mock_audit.call_args.args[0] == "enrich_missing"
