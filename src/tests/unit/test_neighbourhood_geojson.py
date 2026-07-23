"""Unit tests for neighbourhood GeoJSON parsing (no PostGIS required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from core.neighbourhood_geojson import (
    NeighbourhoodGeoJSONError,
    NeighbourhoodPolygon,
    parse_feature_collection,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "geo"
    / "bh_neighbourhoods_tiny.geojson"
)


class TestParseFeatureCollection:
    def test_parses_tiny_fixture(self):
        rows = parse_feature_collection(FIXTURE)
        assert len(rows) == 3
        names = {r.name for r in rows}
        assert names == {"FixtureA", "FixtureB", "FixtureC"}
        for row in rows:
            assert row.city == "Belo Horizonte"
            assert row.state == "MG"
            assert isinstance(row.polygon, Polygon)
            assert row.polygon.is_valid
            assert not row.polygon.is_empty

    def test_multipolygon_keeps_largest_part(self):
        rows = parse_feature_collection(FIXTURE)
        fixture_c = next(r for r in rows if r.name == "FixtureC")
        # Larger rectangle in fixture is ~0.000025 deg² vs tiny ~0.000001
        minx, miny, maxx, maxy = fixture_c.polygon.bounds
        assert minx == pytest.approx(-43.9700)
        assert maxx == pytest.approx(-43.9650)

    def test_default_city_state_when_omitted(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "OnlyName"},
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
        rows = parse_feature_collection(
            data, default_city="Contagem", default_state="mg"
        )
        assert rows[0].city == "Contagem"
        assert rows[0].state == "MG"

    def test_missing_name_raises(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
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
        with pytest.raises(NeighbourhoodGeoJSONError, match="missing properties.name"):
            parse_feature_collection(data)

    def test_wrong_root_type_raises(self):
        with pytest.raises(NeighbourhoodGeoJSONError, match="FeatureCollection"):
            parse_feature_collection({"type": "Feature", "geometry": None})

    def test_point_geometry_raises(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Pointy"},
                    "geometry": {"type": "Point", "coordinates": [-43.9, -19.9]},
                }
            ],
        }
        with pytest.raises(NeighbourhoodGeoJSONError, match="Unsupported geometry"):
            parse_feature_collection(data)

    def test_accepts_dict_and_path(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert len(parse_feature_collection(raw)) == len(parse_feature_collection(FIXTURE))

    def test_invalid_state_length(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "X", "state": "MGG"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                }
            ],
        }
        with pytest.raises(NeighbourhoodGeoJSONError, match="2-letter"):
            parse_feature_collection(data)


class TestNeighbourhoodPolygonDataclass:
    def test_frozen(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        row = NeighbourhoodPolygon(name="A", city="BH", state="MG", polygon=poly)
        with pytest.raises(Exception):
            row.name = "B"  # type: ignore[misc]
