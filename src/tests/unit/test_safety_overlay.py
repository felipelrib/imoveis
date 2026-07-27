"""Unit tests for crime / safety rate overlay (BIN-92)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core.safety_overlay import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_PROVIDER,
    ApplyResult,
    SafetyOverlayError,
    SafetyRateRow,
    apply_safety_rates,
    load_safety_rates_file,
    merge_quality_meta_safety,
    parse_safety_rates,
    safety_score_from_rates,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "safety"
    / "sp_safety_rates_tiny.yaml"
)
FIXED_TS = "2026-07-27T12:00:00+00:00"


def _rate(**overrides) -> SafetyRateRow:
    base = dict(
        name="Pinheiros",
        city="São Paulo",
        state="SP",
        rate_per_100k=100.0,
        period_start="2024-01",
        period_end="2024-12",
        rate_definition="crimes_violentos_per_100k_pop",
        grain="bairro",
        provider=DEFAULT_PROVIDER,
        attribution=DEFAULT_ATTRIBUTION,
    )
    base.update(overrides)
    return SafetyRateRow(**base)


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        name="Pinheiros",
        city="São Paulo",
        state="SP",
        amenity_score=0.8,
        transit_score=0.7,
        access_score=0.6,
        safety_score=None,
        risk_flags=[],
        quality_meta=None,
        quality_notes=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestSafetyScoreFromRates:
    def test_extremes_map_to_one_and_zero(self):
        assert safety_score_from_rates([200.0, 50.0]) == pytest.approx([0.0, 1.0])

    def test_equal_rates_map_to_half(self):
        assert safety_score_from_rates([100.0, 100.0, 100.0]) == [0.5, 0.5, 0.5]

    def test_empty(self):
        assert safety_score_from_rates([]) == []

    def test_midpoint(self):
        scores = safety_score_from_rates([0.0, 50.0, 100.0])
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(0.5)
        assert scores[2] == pytest.approx(0.0)


class TestMergeQualityMetaSafety:
    def test_preserves_sibling_keys(self):
        existing = {
            "risk": {"provider": "geojson-overlay"},
            "access": {"hub_id": "paulista"},
            "transit": {"provider": "osm"},
        }
        merged = merge_quality_meta_safety(
            existing,
            {
                "provider": DEFAULT_PROVIDER,
                "attribution": DEFAULT_ATTRIBUTION,
                "rate_per_100k": 12.0,
            },
        )
        assert merged["risk"]["provider"] == "geojson-overlay"
        assert merged["access"]["hub_id"] == "paulista"
        assert merged["transit"]["provider"] == "osm"
        assert merged["safety"]["provider"] == DEFAULT_PROVIDER
        assert merged["safety"]["rate_per_100k"] == 12.0

    def test_none_existing(self):
        merged = merge_quality_meta_safety(None, {"provider": "x"})
        assert merged == {"safety": {"provider": "x"}}


class TestParseSafetyRates:
    def test_parses_tiny_fixture(self):
        rows = parse_safety_rates(FIXTURE)
        assert len(rows) == 3
        by_name = {r.name: r for r in rows}
        pinheiros = by_name["Pinheiros"]
        assert pinheiros.city == "São Paulo"
        assert pinheiros.state == "SP"
        assert pinheiros.rate_per_100k == pytest.approx(200.0)
        assert pinheiros.provider == DEFAULT_PROVIDER
        assert pinheiros.period_start == "2024-01"
        assert pinheiros.period_end == "2024-12"
        assert "not absolute safety" in pinheiros.attribution
        assert by_name["Moema"].rate_per_100k == pytest.approx(50.0)

    def test_csv_parse(self, tmp_path):
        path = tmp_path / "rates.csv"
        path.write_text(
            "name,city,state,rate_per_100k,period_start,period_end\n"
            "Pinheiros,São Paulo,SP,120.0,2024-01,2024-12\n"
            "Moema,São Paulo,SP,80.0,2024-01,2024-12\n",
            encoding="utf-8",
        )
        rows = parse_safety_rates(path)
        assert len(rows) == 2
        assert rows[0].name == "Pinheiros"
        assert rows[0].rate_per_100k == pytest.approx(120.0)
        assert rows[0].period_start == "2024-01"

    def test_missing_rate_raises(self):
        with pytest.raises(SafetyOverlayError, match="rate_per_100k"):
            parse_safety_rates(
                {
                    "defaults": {"city": "São Paulo", "state": "SP"},
                    "rates": [{"name": "Pinheiros"}],
                }
            )

    def test_negative_rate_raises(self):
        with pytest.raises(SafetyOverlayError, match=">="):
            parse_safety_rates(
                {
                    "defaults": {"city": "São Paulo", "state": "SP"},
                    "rates": [{"name": "Pinheiros", "rate_per_100k": -1}],
                }
            )

    def test_empty_rates_raises(self):
        with pytest.raises(SafetyOverlayError, match="non-empty"):
            parse_safety_rates({"rates": []})


class TestApplySafetyRates:
    def test_sets_relative_scores_and_meta(self):
        pinheiros = _row(name="Pinheiros")
        moema = _row(name="Moema")
        session = MagicMock()
        with patch(
            "core.safety_overlay._neighbourhood_index",
            return_value={
                ("pinheiros", "sao paulo", "SP"): pinheiros,
                ("moema", "sao paulo", "SP"): moema,
            },
        ):
            result = apply_safety_rates(
                session,
                [
                    _rate(name="Pinheiros", rate_per_100k=200.0),
                    _rate(name="Moema", rate_per_100k=50.0),
                ],
                refreshed_at=FIXED_TS,
            )

        assert result.updated == 2
        assert pinheiros.safety_score == pytest.approx(0.0)
        assert moema.safety_score == pytest.approx(1.0)
        assert pinheiros.quality_meta["safety"]["provider"] == DEFAULT_PROVIDER
        assert pinheiros.quality_meta["safety"]["refreshed_at"] == FIXED_TS
        assert pinheiros.quality_meta["safety"]["rate_per_100k"] == 200.0
        assert "not absolute safety" in pinheiros.quality_meta["safety"]["attribution"]
        # Never touch other score columns
        assert pinheiros.amenity_score == 0.8
        assert pinheiros.transit_score == 0.7
        assert pinheiros.access_score == 0.6

    def test_skips_unknown_names(self):
        session = MagicMock()
        with patch(
            "core.safety_overlay._neighbourhood_index",
            return_value={},
        ):
            result = apply_safety_rates(
                session,
                [_rate(name="Unknown")],
                refreshed_at=FIXED_TS,
            )
        assert result == ApplyResult(skipped_unknown=1)

    def test_preserves_sibling_meta_on_apply(self):
        row = _row(
            quality_meta={
                "risk": {"provider": "geojson-overlay"},
                "access": {"hub_id": "paulista"},
            }
        )
        session = MagicMock()
        with patch(
            "core.safety_overlay._neighbourhood_index",
            return_value={("pinheiros", "sao paulo", "SP"): row},
        ):
            apply_safety_rates(
                session,
                [_rate(name="Pinheiros", rate_per_100k=10.0)],
                refreshed_at=FIXED_TS,
            )
        assert row.quality_meta["risk"]["provider"] == "geojson-overlay"
        assert row.quality_meta["access"]["hub_id"] == "paulista"
        assert row.quality_meta["safety"]["provider"] == DEFAULT_PROVIDER

    def test_idempotent_when_unchanged(self):
        meta = merge_quality_meta_safety(
            None,
            {
                "provider": DEFAULT_PROVIDER,
                "refreshed_at": FIXED_TS,
                "rate_definition": "crimes_violentos_per_100k_pop",
                "rate_per_100k": 100.0,
                "grain": "bairro",
                "attribution": DEFAULT_ATTRIBUTION,
                "period_start": "2024-01",
                "period_end": "2024-12",
            },
        )
        row = _row(safety_score=0.5, quality_meta=meta)
        session = MagicMock()
        with patch(
            "core.safety_overlay._neighbourhood_index",
            return_value={("pinheiros", "sao paulo", "SP"): row},
        ):
            # Single row → equal rates within city → 0.5
            result = apply_safety_rates(
                session,
                [_rate(name="Pinheiros", rate_per_100k=100.0)],
                refreshed_at=FIXED_TS,
            )
        assert result.unchanged == 1
        assert result.updated == 0


class TestLoadSafetyRatesFile:
    def test_missing_path(self, tmp_path):
        rows, missing = load_safety_rates_file(tmp_path / "nope.yaml")
        assert rows == []
        assert missing is True

    def test_loads_fixture(self):
        rows, missing = load_safety_rates_file(FIXTURE)
        assert missing is False
        assert len(rows) == 3


def test_fixture_yaml_roundtrip():
    with FIXTURE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["provider"] == DEFAULT_PROVIDER
    assert len(data["rates"]) >= 2
