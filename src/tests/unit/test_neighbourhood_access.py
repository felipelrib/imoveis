"""Unit tests for neighbourhood access / travel-time scoring (BIN-90)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.neighbourhood_access import (
    HubTravelResult,
    access_meta_from_result,
    access_score_from_minutes,
    haversine_m,
    hubs_for_city,
    merge_access_meta,
    minutes_from_haversine,
    pick_best_hub_result,
    travel_to_hubs,
)


@pytest.mark.unit
class TestAccessScoreFromMinutes:
    def test_zero_minutes_is_one(self):
        assert access_score_from_minutes(0.0, 45.0) == pytest.approx(1.0)

    def test_at_max_is_zero(self):
        assert access_score_from_minutes(45.0, 45.0) == pytest.approx(0.0)

    def test_over_max_clamps_to_zero(self):
        assert access_score_from_minutes(90.0, 45.0) == pytest.approx(0.0)

    def test_midpoint(self):
        assert access_score_from_minutes(22.5, 45.0) == pytest.approx(0.5)

    def test_none_minutes(self):
        assert access_score_from_minutes(None, 45.0) is None

    def test_invalid_max(self):
        assert access_score_from_minutes(10.0, 0.0) is None
        assert access_score_from_minutes(-1.0, 45.0) is None


@pytest.mark.unit
class TestHaversineAndMinutes:
    def test_same_point_is_zero(self):
        assert haversine_m(-19.9, -43.9, -19.9, -43.9) == pytest.approx(0.0)

    def test_minutes_from_distance(self):
        # 15 km at 30 km/h → 30 minutes
        assert minutes_from_haversine(15_000.0, 30.0) == pytest.approx(30.0)

    def test_bad_speed_raises(self):
        with pytest.raises(ValueError):
            minutes_from_haversine(1000.0, 0.0)


@pytest.mark.unit
class TestHubsForCity:
    def test_case_insensitive_match(self):
        hubs = {"Belo Horizonte": [SimpleNamespace(id="a")]}
        found = hubs_for_city(hubs, "  belo horizonte ")
        assert len(found) == 1
        assert found[0].id == "a"

    def test_missing_city(self):
        assert hubs_for_city({"BH": []}, "São Paulo") == []
        assert hubs_for_city({"BH": []}, None) == []
        assert hubs_for_city({}, "BH") == []


@pytest.mark.unit
class TestPickBestAndMeta:
    def test_picks_lowest_minutes(self):
        a = HubTravelResult("far", 40.0, 10000.0, "driving", "osrm")
        b = HubTravelResult("near", 12.0, 3000.0, "driving", "osrm")
        best = pick_best_hub_result([a, b])
        assert best is not None
        assert best.hub_id == "near"

    def test_empty_results(self):
        assert pick_best_hub_result([]) is None

    def test_merge_preserves_siblings(self):
        existing = {"provider": "curated-yaml", "amenity": {"count": 3}}
        merged = merge_access_meta(
            existing,
            {"hub_id": "savassi", "minutes": 10.0, "mode": "driving"},
        )
        assert merged["provider"] == "curated-yaml"
        assert merged["amenity"] == {"count": 3}
        assert merged["access"]["hub_id"] == "savassi"

    def test_merge_none_existing(self):
        merged = merge_access_meta(None, {"hub_id": "x"})
        assert merged == {"access": {"hub_id": "x"}}

    def test_access_meta_from_result(self):
        result = HubTravelResult(
            "praca-sete", 12.345, 3210.55, "driving", "osrm", label="Praça Sete"
        )
        meta = access_meta_from_result(result, refreshed_at="2026-07-27T00:00:00+00:00")
        assert meta["hub_id"] == "praca-sete"
        assert meta["minutes"] == 12.35
        assert meta["distance_m"] == 3210.6
        assert meta["hub_label"] == "Praça Sete"
        assert meta["provider"] == "osrm"


@pytest.mark.unit
class TestTravelToHubs:
    def test_haversine_when_no_route_fn(self):
        hubs = [
            SimpleNamespace(id="h1", lat=-19.92, lon=-43.94, label="A"),
        ]
        results = travel_to_hubs(
            origin_lat=-19.93,
            origin_lon=-43.95,
            hubs=hubs,
            mode="driving",
            avg_speed_kmh=30.0,
        )
        assert len(results) == 1
        assert results[0].provider == "haversine"
        assert results[0].minutes > 0

    def test_route_fn_preferred(self):
        hubs = [SimpleNamespace(id="h1", lat=-19.92, lon=-43.94, label="")]

        def route_fn(_olat, _olon, _hlat, _hlon):
            return (8.5, 2500.0)

        results = travel_to_hubs(
            origin_lat=-19.93,
            origin_lon=-43.95,
            hubs=hubs,
            mode="driving",
            avg_speed_kmh=30.0,
            route_fn=route_fn,
        )
        assert results[0].provider == "osrm"
        assert results[0].minutes == pytest.approx(8.5)
        assert results[0].distance_m == pytest.approx(2500.0)

    def test_route_fn_none_falls_back(self):
        hubs = [SimpleNamespace(id="h1", lat=-19.92, lon=-43.94, label="")]

        def route_fn(_olat, _olon, _hlat, _hlon):
            return None

        results = travel_to_hubs(
            origin_lat=-19.93,
            origin_lon=-43.95,
            hubs=hubs,
            mode="driving",
            avg_speed_kmh=30.0,
            route_fn=route_fn,
        )
        assert results[0].provider == "haversine"
