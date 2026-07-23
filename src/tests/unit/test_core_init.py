"""Unit tests for src.core lazy exports."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_core_getattr_exports():
    import core

    assert callable(core.match_or_create_property)
    assert core.PropertyCandidate is not None
    assert core.ScoringWeights is not None
    with pytest.raises(AttributeError):
        _ = core.does_not_exist
