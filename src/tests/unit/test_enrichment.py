"""Unit tests for the canonical enrichment vocabulary (src/core/enrichment.py)."""

from __future__ import annotations

import pytest

from src.core.enrichment import (
    CLOUD_BACKENDS,
    LOCAL_BACKENDS,
    EnrichmentBackend,
    EnrichmentTaskClass,
    is_cloud_backend,
    is_valid_backend,
    is_valid_task_class,
)


@pytest.mark.unit
def test_task_class_values():
    """Each task class carries its canonical string value."""
    assert EnrichmentTaskClass.VISUAL.value == "visual"
    assert EnrichmentTaskClass.SENTIMENT.value == "sentiment"
    assert EnrichmentTaskClass.DEAL_VERDICT.value == "deal_verdict"
    assert EnrichmentTaskClass.VALUATION.value == "valuation"
    assert EnrichmentTaskClass.EMBEDDING.value == "embedding"


@pytest.mark.unit
def test_backend_values():
    """Each backend carries its canonical string value."""
    assert EnrichmentBackend.OLLAMA.value == "ollama"
    assert EnrichmentBackend.LMSTUDIO.value == "lmstudio"
    assert EnrichmentBackend.GEMINI.value == "gemini"
    assert EnrichmentBackend.GEMMA.value == "gemma"


@pytest.mark.unit
def test_local_and_cloud_backends_partition():
    """LOCAL_BACKENDS and CLOUD_BACKENDS partition all backends (disjoint, union == all)."""
    assert LOCAL_BACKENDS.isdisjoint(CLOUD_BACKENDS)
    assert LOCAL_BACKENDS | CLOUD_BACKENDS == set(EnrichmentBackend)
    assert LOCAL_BACKENDS == {EnrichmentBackend.OLLAMA, EnrichmentBackend.LMSTUDIO}
    assert CLOUD_BACKENDS == {EnrichmentBackend.GEMINI, EnrichmentBackend.GEMMA}


@pytest.mark.unit
def test_is_cloud_backend_true_cases():
    """Cloud backends are cloud, by string value and by enum member."""
    assert is_cloud_backend("gemini") is True
    assert is_cloud_backend("gemma") is True
    assert is_cloud_backend(EnrichmentBackend.GEMINI) is True
    assert is_cloud_backend(EnrichmentBackend.GEMMA) is True


@pytest.mark.unit
def test_is_cloud_backend_false_cases():
    """Local backends and unknown values are not cloud."""
    assert is_cloud_backend("ollama") is False
    assert is_cloud_backend("lmstudio") is False
    assert is_cloud_backend(EnrichmentBackend.OLLAMA) is False
    assert is_cloud_backend(EnrichmentBackend.LMSTUDIO) is False
    assert is_cloud_backend("frob") is False


@pytest.mark.unit
def test_is_valid_backend():
    """Known backend values (str or member) are valid; anything else is not."""
    assert is_valid_backend("ollama") is True
    assert is_valid_backend("gemma") is True
    assert is_valid_backend(EnrichmentBackend.LMSTUDIO) is True
    assert is_valid_backend("frob") is False
    assert is_valid_backend("") is False


@pytest.mark.unit
def test_is_valid_task_class():
    """Known task-class values (str or member) are valid; anything else is not."""
    assert is_valid_task_class("visual") is True
    assert is_valid_task_class(EnrichmentTaskClass.EMBEDDING) is True
    assert is_valid_task_class("frobnicate") is False
    assert is_valid_task_class("") is False


@pytest.mark.unit
def test_enum_members_are_str():
    """Members are str-typed and usable directly as strings / dict keys."""
    assert isinstance(EnrichmentTaskClass.VISUAL, str)
    assert isinstance(EnrichmentBackend.OLLAMA, str)
    assert EnrichmentTaskClass.VISUAL == "visual"
    assert EnrichmentBackend.OLLAMA == "ollama"
    routing = {EnrichmentTaskClass.VISUAL: EnrichmentBackend.OLLAMA.value}
    assert routing["visual"] == "ollama"
