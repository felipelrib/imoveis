"""Unit tests for domain entities (Pydantic validation)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.entities import (
    DedupeResult,
    LocationData,
    PropertyCandidate,
    ScoringWeights,
    SentimentAnalysisResult,
    VisualAnalysisResult,
)


class TestLocationData:
    def test_valid(self):
        loc = LocationData(lat=-23.5, lon=-46.6)
        assert loc.lat == -23.5

    def test_lat_out_of_bounds(self):
        with pytest.raises(ValidationError):
            LocationData(lat=91.0, lon=0.0)

    def test_lon_out_of_bounds(self):
        with pytest.raises(ValidationError):
            LocationData(lat=0.0, lon=181.0)


class TestPropertyCandidate:
    def _valid(self, **overrides):
        data = dict(
            platform="quintoandar",
            platform_id="123",
            price=1500.0,
            location={"lat": -23.5, "lon": -46.6},
        )
        data.update(overrides)
        return PropertyCandidate(**data)

    def test_valid_minimal(self):
        c = self._valid()
        assert c.platform == "quintoandar"

    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._valid(price=0.0)

    def test_platform_id_coerced_to_str(self):
        c = self._valid(platform_id=99)
        assert c.platform_id == "99"

    def test_image_urls_defaults_to_empty(self):
        c = self._valid()
        assert c.image_urls == []

    def test_area_must_be_positive_if_set(self):
        with pytest.raises(ValidationError):
            self._valid(area_m2=-5.0)


class TestScoringWeights:
    def test_valid(self):
        w = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        assert w.stat_weight == 0.6

    def test_weight_must_be_in_range(self):
        with pytest.raises(ValidationError):
            ScoringWeights(stat_weight=1.5, ai_weight=0.5)


class TestDedupeResult:
    def test_created_action(self):
        r = DedupeResult(action="created", property_id="uuid-1")
        assert not r.is_duplicate

    def test_updated_action(self):
        r = DedupeResult(action="updated", property_id="uuid-1", is_duplicate=True, matched_property_id="uuid-2")
        assert r.is_duplicate


class TestVisualAnalysisResult:
    def test_defaults(self):
        v = VisualAnalysisResult()
        assert v.condition_score == 0.5
        assert v.features_detected == []

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            VisualAnalysisResult(condition_score=1.5)


class TestSentimentAnalysisResult:
    def test_defaults(self):
        s = SentimentAnalysisResult()
        assert s.sentiment_score == 0.5
        assert s.green_flags == []
        assert s.red_flags == []
