"""Unit tests for curated neighbourhood quality YAML parsing (BIN-87)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.neighbourhood_quality_yaml import (
    CuratedProfile,
    NeighbourhoodQualityYamlError,
    parse_curated_yaml,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "neighbourhood_quality_tiny.yaml"
)
SEED = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "neighbourhood_quality.yaml"
)
APP_CONFIG = (
    Path(__file__).resolve().parents[3] / "configs" / "app_config.yaml"
)


class TestParseCuratedYaml:
    def test_parses_tiny_fixture(self):
        rows = parse_curated_yaml(FIXTURE)
        assert len(rows) == 3
        by_name = {r.name: r for r in rows}
        savassi = by_name["Savassi"]
        assert isinstance(savassi, CuratedProfile)
        assert savassi.city == "Belo Horizonte"
        assert savassi.state == "MG"
        assert savassi.amenity_score == pytest.approx(0.90)
        assert savassi.transit_score == pytest.approx(0.85)
        assert savassi.access_score == pytest.approx(0.88)
        assert savassi.safety_score == pytest.approx(0.72)
        assert savassi.risk_flags == ()
        assert savassi.slug == "savassi"
        assert "Central" in (savassi.notes or "")

        efigenia = by_name["Santa Efigênia"]
        assert efigenia.slug == "santa-efigenia"
        assert efigenia.amenity_score == pytest.approx(0.65)

    def test_defaults_city_state_when_omitted(self):
        data = {
            "version": 1,
            "defaults": {"city": "Campinas", "state": "sp"},
            "profiles": [
                {
                    "name": "Cambuí",
                    "amenity_score": 0.8,
                    "transit_score": 0.7,
                    "access_score": 0.75,
                    "safety_score": 0.6,
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].city == "Campinas"
        assert rows[0].state == "SP"

    def test_invalid_score_becomes_none(self):
        data = {
            "version": 1,
            "defaults": {"city": "Belo Horizonte", "state": "MG"},
            "profiles": [
                {
                    "name": "Savassi",
                    "amenity_score": 1.5,
                    "transit_score": "bad",
                    "access_score": 0.5,
                    "safety_score": -0.1,
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].amenity_score is None
        assert rows[0].transit_score is None
        assert rows[0].access_score == pytest.approx(0.5)
        assert rows[0].safety_score is None

    def test_missing_name_raises(self):
        data = {
            "version": 1,
            "profiles": [{"amenity_score": 0.5}],
        }
        with pytest.raises(NeighbourhoodQualityYamlError, match="missing name"):
            parse_curated_yaml(data)

    def test_wrong_root_raises(self):
        with pytest.raises(NeighbourhoodQualityYamlError, match="profiles"):
            parse_curated_yaml({"version": 1})

    def test_risk_flags_normalized(self):
        data = {
            "version": 1,
            "defaults": {"city": "Belo Horizonte", "state": "MG"},
            "profiles": [
                {
                    "name": "Centro",
                    "amenity_score": 0.6,
                    "risk_flags": [" flood ", "industrial"],
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].risk_flags == ("flood", "industrial")


class TestSeedCoversFanOut:
    def test_seed_covers_qa_and_olx_slugs(self):
        assert SEED.is_file(), f"missing seed YAML at {SEED}"
        rows = parse_curated_yaml(SEED)
        seed_slugs = {r.slug for r in rows if r.slug}
        assert len(rows) >= 35
        assert None not in seed_slugs

        app = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))
        platforms = app["scraping"]["platforms"]
        qa_slugs = {
            n["slug"] for n in platforms["quintoandar"]["extra"]["neighborhoods"]
        }
        olx_slugs = {n["slug"] for n in platforms["olx"]["extra"]["neighborhoods"]}
        fan_out = qa_slugs | olx_slugs
        missing = fan_out - seed_slugs
        assert not missing, f"seed missing fan-out slugs: {sorted(missing)}"
        assert "horto" in seed_slugs
        assert len(seed_slugs) >= len(fan_out)
