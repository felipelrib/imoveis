"""Canonical enrichment vocabulary — the single source of truth for the
enrichment task classes and their backends.

This module defines the shared, framework-free vocabulary that everything which
reasons about enrichment draws on: per-task-class backend routing (FR-27, wired
live in story 1.2), backfill scope (FR-28, story 1.3), and coverage telemetry
(FR-29, story 1.4). Keeping the enums here (in ``core``) means adapters, the
API, config validation, and the backfill runner all agree on the same
task-class and backend names instead of re-deriving them from scattered string
literals. Only the vocabulary and its local/cloud classification live here; the
consuming behaviour lives in those stories.

The live/incremental path is always local; cloud backends are backfill-only and
are only ever selected via the per-task-class routing map — never on the scalar
live-path ``ai.backend`` selector.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "EnrichmentTaskClass",
    "EnrichmentBackend",
    "LOCAL_BACKENDS",
    "CLOUD_BACKENDS",
    "is_cloud_backend",
    "is_valid_backend",
    "is_valid_task_class",
]


class EnrichmentTaskClass(str, Enum):
    """A class of enrichment work that can be routed to a backend."""

    VISUAL = "visual"
    SENTIMENT = "sentiment"
    DEAL_VERDICT = "deal_verdict"
    VALUATION = "valuation"
    EMBEDDING = "embedding"


class EnrichmentBackend(str, Enum):
    """An AI backend an enrichment task class can be routed to."""

    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    GEMINI = "gemini"
    GEMMA = "gemma"


# Local (on-device / self-hosted) backends — the only ones allowed on the live
# path. Cloud backends are backfill-eligible only.
LOCAL_BACKENDS = frozenset({EnrichmentBackend.OLLAMA, EnrichmentBackend.LMSTUDIO})
CLOUD_BACKENDS = frozenset({EnrichmentBackend.GEMINI, EnrichmentBackend.GEMMA})


def is_cloud_backend(backend: EnrichmentBackend | str) -> bool:
    """Return True iff ``backend`` is a cloud (backfill-only) backend.

    Accepts either an :class:`EnrichmentBackend` member or a raw string value.
    Unknown values return ``False`` — the unknown-backend case is caught
    separately by the config validator, not here.
    """
    try:
        return EnrichmentBackend(backend) in CLOUD_BACKENDS
    except ValueError:
        return False


def is_valid_backend(backend: EnrichmentBackend | str) -> bool:
    """Return True iff ``backend`` is a known :class:`EnrichmentBackend` value."""
    try:
        EnrichmentBackend(backend)
        return True
    except ValueError:
        return False


def is_valid_task_class(task_class: EnrichmentTaskClass | str) -> bool:
    """Return True iff ``task_class`` is a known :class:`EnrichmentTaskClass`."""
    try:
        EnrichmentTaskClass(task_class)
        return True
    except ValueError:
        return False
