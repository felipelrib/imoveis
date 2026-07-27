"""Unit tests for OSM amenity density scoring (BIN-88)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, shape

from core.osm_amenities import (
    DEFAULT_CATEGORY_TARGETS,
    AmenityPOI,
    build_amenity_quality_meta,
    classify_amenity_tags,
    count_amenities_by_category,
    merge_amenity_quality_meta,
    score_from_counts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geo"


def _fixture_a_polygon() -> Polygon:
    data = json.loads((FIXTURES / "bh_neighbourhoods_tiny.geojson").read_text(encoding="utf-8"))
    for feature in data["features"]:
        if feature["properties"].get("name") == "FixtureA":
            geom = shape(feature["geometry"])
            assert isinstance(geom, Polygon)
            return geom
    raise AssertionError("FixtureA missing")


def _load_pois() -> list[AmenityPOI]:
    data = json.loads((FIXTURES / "osm_pois_tiny.geojson").read_text(encoding="utf-8"))
    pois: list[AmenityPOI] = []
    for feature in data["features"]:
        coords = feature["geometry"]["coordinates"]
        props = {k: v for k, v in feature["properties"].items() if k != "name"}
        pois.append(AmenityPOI(lon=float(coords[0]), lat=float(coords[1]), tags=props))
    return pois


class TestClassifyAmenityTags:
    def test_shop_supermarket(self):
        assert classify_amenity_tags({"shop": "supermarket"}) == "shop"

    def test_park_leisure(self):
        assert classify_amenity_tags({"leisure": "park"}) == "park"

    def test_school(self):
        assert classify_amenity_tags({"amenity": "school"}) == "school"

    def test_healthcare_pharmacy(self):
        assert classify_amenity_tags({"amenity": "pharmacy"}) == "healthcare"

    def test_ignored_cafe(self):
        assert classify_amenity_tags({"amenity": "cafe"}) is None

    def test_preclassified_category(self):
        assert classify_amenity_tags({"category": "park"}) == "park"


class TestCountAndScore:
    def test_counts_inside_fixture_a(self):
        counts = count_amenities_by_category(_load_pois(), _fixture_a_polygon(), buffer_m=0)
        assert counts == {
            "shop": 2,
            "park": 1,
            "school": 1,
            "healthcare": 1,
        }

    def test_outside_poi_excluded(self):
        counts = count_amenities_by_category(_load_pois(), _fixture_a_polygon())
        # Clinic is in FixtureB bbox, not FixtureA
        assert counts["healthcare"] == 1  # pharmacy only

    def test_buffer_includes_nearby_outside_point(self):
        # Point just west of FixtureA: lon=-43.9405, lat=-19.9175
        near = [
            AmenityPOI(
                lon=-43.9405,
                lat=-19.9175,
                tags={"amenity": "hospital"},
            )
        ]
        poly = _fixture_a_polygon()
        without = count_amenities_by_category(near, poly, buffer_m=0)
        with_buf = count_amenities_by_category(near, poly, buffer_m=100)
        assert without["healthcare"] == 0
        assert with_buf["healthcare"] == 1

    def test_score_saturates_at_targets(self):
        perfect = {
            "shop": 3,
            "park": 1,
            "school": 1,
            "healthcare": 2,
        }
        assert score_from_counts(perfect) == pytest.approx(1.0)

    def test_score_partial_mean(self):
        # shop 0/3, park 1/1, school 0/1, healthcare 0/2 → mean 0.25
        counts = {"shop": 0, "park": 1, "school": 0, "healthcare": 0}
        assert score_from_counts(counts) == pytest.approx(0.25)

    def test_score_uses_custom_targets(self):
        counts = {"shop": 1, "park": 0, "school": 0, "healthcare": 0}
        score = score_from_counts(counts, targets={"shop": 1, "park": 1, "school": 1, "healthcare": 1})
        assert score == pytest.approx(0.25)

    def test_fixture_a_score_matches_formula(self):
        counts = count_amenities_by_category(_load_pois(), _fixture_a_polygon())
        # shop 2/3, park 1/1, school 1/1, healthcare 1/2
        expected = (2 / 3 + 1.0 + 1.0 + 0.5) / 4
        assert score_from_counts(counts, DEFAULT_CATEGORY_TARGETS) == pytest.approx(expected)


class TestQualityMeta:
    def test_build_meta_shape(self):
        counts = {"shop": 2, "park": 1, "school": 1, "healthcare": 1}
        meta = build_amenity_quality_meta(
            counts,
            mode="geojson",
            refreshed_at="2026-07-27T12:00:00+00:00",
        )
        assert meta["source"] == "osm"
        assert meta["mode"] == "geojson"
        assert meta["refreshed_at"] == "2026-07-27T12:00:00+00:00"
        assert meta["amenity_counts"]["shop"] == 2
        assert "amenity_category_scores" in meta

    def test_merge_preserves_unrelated_keys(self):
        existing = {"provider": "curated-yaml", "notes": "keep"}
        empty_counts = {"shop": 0, "park": 0, "school": 0, "healthcare": 0}
        amenity = build_amenity_quality_meta(
            empty_counts,
            mode="overpass",
            refreshed_at="2026-07-27T00:00:00+00:00",
        )
        merged = merge_amenity_quality_meta(existing, amenity)
        assert merged["provider"] == "curated-yaml"
        assert merged["notes"] == "keep"
        assert merged["source"] == "osm"
