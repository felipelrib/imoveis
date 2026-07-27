"""Unit tests for flood / environmental risk overlay parsing and intersection."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Polygon

from core.risk_overlay import (
    MANAGED_RISK_FLAGS,
    RiskOverlayError,
    RiskOverlayLayer,
    flags_for_neighbourhood,
    load_risk_layers,
    max_severity,
    normalize_severity,
    parse_risk_feature_collection,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geo"
FLOOD_FIXTURE = FIXTURES / "bh_risk_flood_tiny.geojson"
INDUSTRIAL_FIXTURE = FIXTURES / "bh_risk_industrial_tiny.geojson"
NHOOD_FIXTURE = FIXTURES / "bh_neighbourhoods_tiny.geojson"


class TestNormalizeSeverity:
    def test_labels_and_numeric(self):
        assert normalize_severity("high") == "high"
        assert normalize_severity("MEDIUM") == "medium"
        assert normalize_severity(0.9) == "high"
        assert normalize_severity(0.5) == "medium"
        assert normalize_severity(0.1) == "low"
        assert normalize_severity(None) is None
        assert normalize_severity("nope") is None

    def test_max_severity(self):
        assert max_severity(["low", "high", "medium"]) == "high"
        assert max_severity(["low"]) == "low"
        assert max_severity([]) is None
        assert max_severity([None, "medium"]) == "medium"


class TestParseRiskFeatureCollection:
    def test_parses_flood_fixture(self):
        rows = parse_risk_feature_collection(FLOOD_FIXTURE)
        assert len(rows) == 2
        assert all(r.risk_type == "flood_zone" for r in rows)
        severities = {r.severity for r in rows}
        assert severities == {"high", "low"}
        for row in rows:
            assert isinstance(row.polygon, Polygon)
            assert row.polygon.is_valid

    def test_parses_industrial_fixture(self):
        rows = parse_risk_feature_collection(INDUSTRIAL_FIXTURE)
        assert len(rows) == 1
        assert rows[0].risk_type == "industrial_adjacent"
        assert rows[0].severity == "medium"

    def test_default_risk_type_override(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"severity": "low"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-43.94, -19.92],
                                [-43.93, -19.92],
                                [-43.93, -19.91],
                                [-43.94, -19.91],
                                [-43.94, -19.92],
                            ]
                        ],
                    },
                }
            ],
        }
        rows = parse_risk_feature_collection(
            data, default_risk_type="industrial_adjacent"
        )
        assert rows[0].risk_type == "industrial_adjacent"

    def test_missing_risk_type_raises(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
                        ],
                    },
                }
            ],
        }
        with pytest.raises(RiskOverlayError, match="risk_type"):
            parse_risk_feature_collection(data)

    def test_unknown_risk_type_raises(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"risk_type": "volcano"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
                        ],
                    },
                }
            ],
        }
        with pytest.raises(RiskOverlayError, match="Unsupported risk_type"):
            parse_risk_feature_collection(data)

    def test_multipolygon_keeps_largest_part(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"risk_type": "flood_zone", "severity": "low"},
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [
                                [
                                    [0.0, 0.0],
                                    [0.01, 0.0],
                                    [0.01, 0.01],
                                    [0.0, 0.01],
                                    [0.0, 0.0],
                                ]
                            ],
                            [
                                [
                                    [1.0, 1.0],
                                    [2.0, 1.0],
                                    [2.0, 2.0],
                                    [1.0, 2.0],
                                    [1.0, 1.0],
                                ]
                            ],
                        ],
                    },
                }
            ],
        }
        rows = parse_risk_feature_collection(data)
        minx, _, maxx, _ = rows[0].polygon.bounds
        assert minx == pytest.approx(1.0)
        assert maxx == pytest.approx(2.0)


class TestFlagsForNeighbourhood:
    def test_fixture_a_gets_flood_max_severity(self):
        from core.neighbourhood_geojson import parse_feature_collection

        nhoods = {r.name: r.polygon for r in parse_feature_collection(NHOOD_FIXTURE)}
        flood = parse_risk_feature_collection(FLOOD_FIXTURE)
        flags, severity = flags_for_neighbourhood(nhoods["FixtureA"], flood)
        assert flags == ["flood_zone"]
        assert severity == {"flood_zone": "high"}

    def test_fixture_b_gets_industrial(self):
        from core.neighbourhood_geojson import parse_feature_collection

        nhoods = {r.name: r.polygon for r in parse_feature_collection(NHOOD_FIXTURE)}
        industrial = parse_risk_feature_collection(INDUSTRIAL_FIXTURE)
        flags, severity = flags_for_neighbourhood(nhoods["FixtureB"], industrial)
        assert flags == ["industrial_adjacent"]
        assert severity == {"industrial_adjacent": "medium"}

    def test_fixture_c_no_overlap(self):
        from core.neighbourhood_geojson import parse_feature_collection

        nhoods = {r.name: r.polygon for r in parse_feature_collection(NHOOD_FIXTURE)}
        flood = parse_risk_feature_collection(FLOOD_FIXTURE)
        industrial = parse_risk_feature_collection(INDUSTRIAL_FIXTURE)
        flags, severity = flags_for_neighbourhood(
            nhoods["FixtureC"], flood + industrial
        )
        assert flags == []
        assert severity == {}

    def test_managed_flags_constant(self):
        assert MANAGED_RISK_FLAGS == frozenset(
            {"flood_zone", "industrial_adjacent"}
        )


class TestLoadRiskLayers:
    def test_missing_path_skipped_with_log(self, caplog):
        import logging

        layers = [
            RiskOverlayLayer(
                path=Path("/nonexistent/bh_flood.geojson"),
                risk_type="flood_zone",
            ),
            RiskOverlayLayer(path=FLOOD_FIXTURE, risk_type=None),
        ]
        with caplog.at_level(logging.WARNING):
            features, skipped = load_risk_layers(layers)
        assert skipped == 1
        assert len(features) == 2
        assert any("skipping missing risk layer" in r.message.lower() for r in caplog.records)

    def test_all_missing_returns_empty(self, caplog):
        import logging

        layers = [
            RiskOverlayLayer(
                path=Path("/missing/a.geojson"), risk_type="flood_zone"
            ),
            RiskOverlayLayer(
                path=Path("/missing/b.geojson"),
                risk_type="industrial_adjacent",
            ),
        ]
        with caplog.at_level(logging.WARNING):
            features, skipped = load_risk_layers(layers)
        assert features == []
        assert skipped == 2
