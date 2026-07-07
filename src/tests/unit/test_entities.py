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
    def _valid(self, **overrides):
        data = dict(
            address="Rua Teste 123",
            neighborhood="Centro",
            city="São Paulo",
            state="SP",
            zip_code="01000-000",
            latitude=-23.5,
            longitude=-46.6,
        )
        data.update(overrides)
        return LocationData(**data)

    def test_valid(self):
        loc = self._valid()
        assert loc.latitude == -23.5
        assert loc.longitude == -46.6
        assert loc.city == "São Paulo"

    def test_address_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            self._valid(address="")

    def test_address_is_stripped(self):
        loc = self._valid(address="  Rua Teste 123  ")
        assert loc.address == "Rua Teste 123"


class TestPropertyCandidate:
    def _valid(self, **overrides):
        data = dict(
            platform="quintoandar",
            platform_id="123",
            price=1500.0,
        )
        data.update(overrides)
        return PropertyCandidate(**data)

    def test_valid_minimal(self):
        c = self._valid()
        assert c.platform == "quintoandar"

    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._valid(price=0.0)

    def test_platform_id_empty_raises(self):
        with pytest.raises(ValidationError):
            self._valid(platform_id="")

    def test_image_urls_defaults_to_empty(self):
        c = self._valid()
        assert c.image_urls == []

    def test_area_m2_optional(self):
        c = self._valid(area_m2=50.0)
        assert c.area_m2 == 50.0

    def test_area_m2_none_by_default(self):
        c = self._valid()
        assert c.area_m2 is None


class TestScoringWeights:
    def test_valid(self):
        w = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        assert w.stat_weight == 0.6

    def test_defaults(self):
        w = ScoringWeights()
        assert w.ai_weight == 0.5
        assert w.stat_weight == 0.5


class TestDedupeResult:
    def test_not_duplicate(self):
        r = DedupeResult(is_duplicate=False)
        assert not r.is_duplicate
        assert r.matched_property_id is None

    def test_duplicate_with_match(self):
        r = DedupeResult(is_duplicate=True, matched_property_id="uuid-2")
        assert r.is_duplicate
        assert r.matched_property_id == "uuid-2"


class TestVisualAnalysisResult:
    def test_defaults(self):
        v = VisualAnalysisResult(sentiment="positive")
        assert v.sentiment == "positive"
        assert v.features == []
        assert v.confidence == 0.0

    def test_with_features(self):
        v = VisualAnalysisResult(sentiment="neutral", features=["pool", "garden"], confidence=0.8)
        assert v.features == ["pool", "garden"]
        assert v.confidence == 0.8


class TestSentimentAnalysisResult:
    def test_defaults(self):
        s = SentimentAnalysisResult(sentiment="positive")
        assert s.sentiment == "positive"
        assert s.confidence == 0.0

    def test_with_confidence(self):
        s = SentimentAnalysisResult(sentiment="negative", confidence=0.9)
        assert s.confidence == 0.9