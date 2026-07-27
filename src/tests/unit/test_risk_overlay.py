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


class TestMergeHelpers:
    def test_merge_risk_flags_preserves_unapplied_managed(self):
        from core.risk_overlay import merge_risk_flags

        out = merge_risk_flags(
            ["flood_zone", "seller_noise"],
            ["industrial_adjacent"],
            layers_applied=["industrial_adjacent"],
        )
        assert out == ["flood_zone", "seller_noise", "industrial_adjacent"]

    def test_merge_risk_flags_clears_applied_when_no_hit(self):
        from core.risk_overlay import merge_risk_flags

        out = merge_risk_flags(
            ["flood_zone", "other"],
            [],
            layers_applied=["flood_zone"],
        )
        assert out == ["other"]

    def test_merge_quality_meta_overwrites_risk_only(self):
        from core.risk_overlay import merge_quality_meta_risk

        meta = merge_quality_meta_risk(
            {"provider": "curated-yaml", "risk": {"old": True}},
            severity={"flood_zone": "high"},
            layers_applied=["flood_zone"],
            refreshed_at="2026-07-27T00:00:00+00:00",
        )
        assert meta["provider"] == "curated-yaml"
        assert meta["risk"]["severity"] == {"flood_zone": "high"}
        assert meta["risk"]["layers_applied"] == ["flood_zone"]

    def test_merge_quality_meta_non_dict_existing(self):
        from core.risk_overlay import merge_quality_meta_risk

        meta = merge_quality_meta_risk(
            "nope",
            severity={},
            layers_applied=[],
            refreshed_at="t",
        )
        assert meta["risk"]["refreshed_at"] == "t"


class TestParseEdgeCases:
    def test_invalid_default_risk_type(self):
        with pytest.raises(RiskOverlayError, match="Unsupported risk_type"):
            parse_risk_feature_collection(
                {"type": "FeatureCollection", "features": []},
                default_risk_type="volcano",
            )

    def test_wrong_root_and_features(self):
        with pytest.raises(RiskOverlayError, match="FeatureCollection"):
            parse_risk_feature_collection({"type": "Feature"})
        with pytest.raises(RiskOverlayError, match="features"):
            parse_risk_feature_collection(
                {"type": "FeatureCollection", "features": "nope"}
            )

    def test_bad_feature_shape_and_state(self):
        with pytest.raises(RiskOverlayError, match="must be an object"):
            parse_risk_feature_collection(
                {"type": "FeatureCollection", "features": ["x"]}
            )
        with pytest.raises(RiskOverlayError, match="type must be Feature"):
            parse_risk_feature_collection(
                {
                    "type": "FeatureCollection",
                    "features": [{"type": "NotFeature", "properties": {}}],
                }
            )
        with pytest.raises(RiskOverlayError, match="2-letter"):
            parse_risk_feature_collection(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "risk_type": "flood_zone",
                                "state": "MGG",
                            },
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [0, 0],
                                        [1, 0],
                                        [1, 1],
                                        [0, 1],
                                        [0, 0],
                                    ]
                                ],
                            },
                        }
                    ],
                }
            )

    def test_point_geometry_rejected(self):
        with pytest.raises(RiskOverlayError, match="Unsupported geometry"):
            parse_risk_feature_collection(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"risk_type": "flood_zone"},
                            "geometry": {
                                "type": "Point",
                                "coordinates": [0, 0],
                            },
                        }
                    ],
                }
            )

    def test_empty_polygon_and_missing_geometry(self):
        with pytest.raises(RiskOverlayError, match="missing geometry"):
            parse_risk_feature_collection(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"risk_type": "flood_zone"},
                            "geometry": None,
                        }
                    ],
                }
            )

    def test_numeric_severity_out_of_range(self):
        assert normalize_severity(1.5) is None
        assert normalize_severity(True) is None


class TestFlagsEdgeCases:
    def test_empty_neighbourhood(self):
        flags, severity = flags_for_neighbourhood(
            Polygon(), parse_risk_feature_collection(FLOOD_FIXTURE)
        )
        assert flags == []
        assert severity == {}


class TestApplyWithMocks:
    def test_apply_updates_and_skips_no_geometry(self):
        from unittest.mock import MagicMock, patch

        from shapely.geometry import box

        from core.risk_overlay import apply_risk_overlays

        flood = parse_risk_feature_collection(FLOOD_FIXTURE)
        nhood_hit = box(-43.9395, -19.9195, -43.9355, -19.9155)
        row_hit = MagicMock()
        row_hit.geometry = object()
        row_hit.risk_flags = []
        row_hit.quality_meta = None

        row_none = MagicMock()
        row_none.geometry = None
        row_none.risk_flags = []
        row_none.quality_meta = None

        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = [
            row_hit,
            row_none,
        ]

        with patch(
            "geoalchemy2.shape.to_shape", return_value=nhood_hit
        ):
            result = apply_risk_overlays(
                session,
                flood,
                city="Belo Horizonte",
                state="mg",
                refreshed_at="t0",
            )

        assert result.updated == 1
        assert result.skipped_no_geometry == 1
        assert row_hit.risk_flags == ["flood_zone"]
        assert row_hit.quality_meta["risk"]["severity"]["flood_zone"] == "high"
        session.flush.assert_called()

    def test_apply_unchanged_when_same(self):
        from unittest.mock import MagicMock, patch

        from shapely.geometry import box

        from core.risk_overlay import (
            apply_risk_overlays,
            merge_quality_meta_risk,
        )

        flood = parse_risk_feature_collection(FLOOD_FIXTURE)
        nhood_hit = box(-43.9395, -19.9195, -43.9355, -19.9155)
        meta = merge_quality_meta_risk(
            None,
            severity={"flood_zone": "high"},
            layers_applied=["flood_zone"],
            refreshed_at="t0",
        )
        row = MagicMock()
        row.geometry = object()
        row.risk_flags = ["flood_zone"]
        row.quality_meta = meta

        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = [
            row
        ]

        with patch("geoalchemy2.shape.to_shape", return_value=nhood_hit):
            result = apply_risk_overlays(
                session,
                flood,
                city="Belo Horizonte",
                state="MG",
                layers_applied=["flood_zone"],
                refreshed_at="t0",
            )

        assert result.updated == 0
        assert result.unchanged == 1
        session.flush.assert_not_called()

    def test_load_and_apply_all_missing(self, caplog):
        import logging
        from unittest.mock import MagicMock

        from core.risk_overlay import load_and_apply_risk_overlays

        session = MagicMock()
        with caplog.at_level(logging.WARNING):
            result = load_and_apply_risk_overlays(
                session,
                [
                    RiskOverlayLayer(
                        path=Path("/missing.geojson"), risk_type="flood_zone"
                    )
                ],
                city="Belo Horizonte",
                state="MG",
            )
        assert result.layers_skipped_missing == 1
        assert result.updated == 0
        session.query.assert_not_called()

    def test_load_and_apply_happy_path(self):
        from unittest.mock import MagicMock, patch

        from shapely.geometry import box

        from core.risk_overlay import load_and_apply_risk_overlays

        nhood_hit = box(-43.9395, -19.9195, -43.9355, -19.9155)
        row = MagicMock()
        row.geometry = object()
        row.risk_flags = []
        row.quality_meta = {"keep": True}

        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = [
            row
        ]

        with patch("geoalchemy2.shape.to_shape", return_value=nhood_hit):
            result = load_and_apply_risk_overlays(
                session,
                [RiskOverlayLayer(path=FLOOD_FIXTURE, risk_type="flood_zone")],
                city="Belo Horizonte",
                state="MG",
                refreshed_at="t1",
            )

        assert result.updated == 1
        assert result.layers_skipped_missing == 0
        assert row.quality_meta["keep"] is True
        assert "flood_zone" in row.risk_flags
