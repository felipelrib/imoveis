"""Unit tests for neighbourhood quality profile mapping (BIN-86)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.schemas import NeighborhoodModel
from core.neighbourhood_quality import (
    normalize_quality_score,
    normalize_risk_flags,
    quality_profile_fields,
)


class TestNormalizeQualityScore:
    def test_none_is_unknown(self):
        assert normalize_quality_score(None) is None

    def test_accepts_boundary_floats(self):
        assert normalize_quality_score(0.0) == 0.0
        assert normalize_quality_score(1.0) == 1.0
        assert normalize_quality_score(0.75) == pytest.approx(0.75)

    def test_rejects_out_of_range(self):
        assert normalize_quality_score(-0.01) is None
        assert normalize_quality_score(1.01) is None

    def test_rejects_non_numeric(self):
        assert normalize_quality_score("good") is None


class TestNormalizeRiskFlags:
    def test_none_and_empty(self):
        assert normalize_risk_flags(None) == []
        assert normalize_risk_flags([]) == []
        assert normalize_risk_flags("") == []

    def test_list_and_single_string(self):
        assert normalize_risk_flags(["flood", " industrial "]) == ["flood", "industrial"]
        assert normalize_risk_flags("flood") == ["flood"]


class TestQualityProfileFields:
    def test_all_null_profile(self):
        fields = quality_profile_fields(
            {
                "id": None,
                "amenity_score": None,
                "transit_score": None,
                "access_score": None,
                "safety_score": None,
                "risk_flags": None,
                "quality_meta": None,
                "quality_notes": None,
            }
        )
        assert fields["id"] is None
        assert fields["amenity_score"] is None
        assert fields["risk_flags"] == []
        assert fields["quality_meta"] is None

    def test_partial_fill_with_meta(self):
        nid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        fields = quality_profile_fields(
            {
                "id": nid,
                "amenity_score": 0.8,
                "transit_score": None,
                "access_score": 0.4,
                "safety_score": None,
                "risk_flags": ["flood"],
                "quality_meta": {"provider": "curated-yaml", "refreshed_at": "2026-07-27"},
                "quality_notes": " MVP notes ",
            }
        )
        assert fields["id"] == nid
        assert fields["amenity_score"] == pytest.approx(0.8)
        assert fields["transit_score"] is None
        assert fields["access_score"] == pytest.approx(0.4)
        assert fields["risk_flags"] == ["flood"]
        assert fields["quality_meta"]["provider"] == "curated-yaml"
        assert fields["quality_notes"] == "MVP notes"


class TestNeighborhoodModelSchema:
    def test_accepts_legacy_filter_shape(self):
        model = NeighborhoodModel.model_validate(
            {"name": "Savassi", "count": 12, "city": "Belo Horizonte"}
        )
        assert model.name == "Savassi"
        assert model.count == 12
        assert model.amenity_score is None
        assert model.risk_flags == []

    def test_accepts_fractional_profile_scores(self):
        model = NeighborhoodModel.model_validate(
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "Savassi",
                "count": 3,
                "city": "Belo Horizonte",
                "amenity_score": 0.85,
                "transit_score": 0.7,
                "access_score": 0.6,
                "safety_score": 0.55,
                "risk_flags": ["flood"],
                "quality_meta": {"provider": "curated-yaml"},
                "quality_notes": "High amenity density",
            }
        )
        assert model.amenity_score == pytest.approx(0.85)
        assert model.safety_score == pytest.approx(0.55)
        assert model.risk_flags == ["flood"]
        assert model.quality_meta["provider"] == "curated-yaml"

    def test_rejects_out_of_range_score(self):
        with pytest.raises(ValidationError):
            NeighborhoodModel.model_validate(
                {"name": "Savassi", "count": 1, "amenity_score": 1.5}
            )
