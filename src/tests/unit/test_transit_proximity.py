"""Unit tests for transit proximity parse + score (BIN-89)."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Polygon

from core.transit_proximity import (
    TransitScoreParams,
    TransitStop,
    gtfs_route_type_to_mode,
    haversine_m,
    infer_osm_mode,
    merge_stops,
    parse_gtfs_stops,
    parse_osm_transit_geojson,
    score_centroid,
    score_polygon,
)
from src.infra.config import get_config

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transit"
GTFS_DIR = FIXTURES / "gtfs_tiny"
OSM_GEOJSON = FIXTURES / "osm_stops_tiny.geojson"

# FixtureA polygon centroid (~midpoint of tiny BH fixture)
FIXTURE_A = Polygon(
    [
        (-43.9400, -19.9200),
        (-43.9350, -19.9200),
        (-43.9350, -19.9150),
        (-43.9400, -19.9150),
        (-43.9400, -19.9200),
    ]
)


@pytest.mark.unit
def test_haversine_zero_and_known_distance():
    assert haversine_m(-43.9, -19.9, -43.9, -19.9) == pytest.approx(0.0)
    # ~111m per 0.001° latitude near equator; BH ~19°S similar order
    d = haversine_m(-43.9375, -19.9175, -43.9375, -19.9185)
    assert 100 < d < 130


@pytest.mark.unit
def test_gtfs_route_type_to_mode():
    assert gtfs_route_type_to_mode(1) == "metro"
    assert gtfs_route_type_to_mode(3) == "bus"
    assert gtfs_route_type_to_mode(2) == "rail"
    assert gtfs_route_type_to_mode(0) == "brt"
    assert gtfs_route_type_to_mode(99) == "other"


@pytest.mark.unit
def test_infer_osm_mode_from_tags_and_explicit():
    assert infer_osm_mode({"mode": "metro"}) == "metro"
    assert infer_osm_mode({"highway": "bus_stop"}) == "bus"
    assert infer_osm_mode({"railway": "station"}) == "metro"
    assert infer_osm_mode({}) == "other"


@pytest.mark.unit
def test_parse_gtfs_stops_with_route_modes():
    stops = parse_gtfs_stops(GTFS_DIR)
    by_id = {s.stop_id: s for s in stops}
    assert set(by_id) >= {"BUS1", "BUS2", "FAR1"}
    # BUS1 served by bus + metro trips → prefer metro
    assert by_id["BUS1"].mode == "metro"
    assert by_id["BUS2"].mode == "bus"
    assert by_id["FAR1"].mode == "bus"
    assert by_id["BUS1"].source == "gtfs"


@pytest.mark.unit
def test_parse_gtfs_stops_default_bus_without_routes(tmp_path: Path):
    stops_only = tmp_path / "stops.txt"
    stops_only.write_text(
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "X,Only Bus,-19.9,-43.9\n",
        encoding="utf-8",
    )
    stops = parse_gtfs_stops(tmp_path)
    assert len(stops) == 1
    assert stops[0].mode == "bus"


@pytest.mark.unit
def test_parse_osm_transit_geojson():
    stops = parse_osm_transit_geojson(OSM_GEOJSON)
    assert len(stops) == 3
    modes = {s.name: s.mode for s in stops}
    assert modes["FixtureA Metro"] == "metro"
    assert modes["Distant Bus"] == "bus"
    assert modes["BRT Corridor"] == "brt"
    assert all(s.source == "osm" for s in stops)


@pytest.mark.unit
def test_score_no_stops_within_max_radius_is_zero():
    far = TransitStop(lon=-44.5, lat=-20.5, mode="bus", name="far", source="gtfs")
    score, meta = score_centroid(-43.9375, -19.9175, [far])
    assert score == 0.0
    assert meta["stop_count"] == 0
    assert meta["nearest_m"] is None


@pytest.mark.unit
def test_score_metro_near_centroid_beats_bus():
    metro = TransitStop(
        lon=-43.9375, lat=-19.9175, mode="metro", name="m", source="osm"
    )
    bus = TransitStop(
        lon=-43.9375, lat=-19.9175, mode="bus", name="b", source="gtfs"
    )
    params = TransitScoreParams()
    metro_score, metro_meta = score_centroid(
        -43.9375, -19.9175, [metro], params
    )
    bus_score, bus_meta = score_centroid(-43.9375, -19.9175, [bus], params)
    assert metro_score > bus_score
    assert metro_meta["nearest_mode"] == "metro"
    assert bus_meta["nearest_mode"] == "bus"
    assert metro_score == pytest.approx(0.7 * 1.0 + 0.3 * (1.0 / 8.0))


@pytest.mark.unit
def test_score_ignores_stops_beyond_max_radius():
    near = TransitStop(
        lon=-43.9375, lat=-19.9175, mode="bus", name="near", source="gtfs"
    )
    # ~3km away — beyond default 1200m
    far = TransitStop(
        lon=-43.9600, lat=-19.9400, mode="metro", name="far", source="osm"
    )
    score, meta = score_centroid(-43.9375, -19.9175, [near, far])
    assert meta["nearest_mode"] == "bus"
    assert meta["mode_counts"] == {"bus": 1}
    assert score > 0.0


@pytest.mark.unit
def test_score_polygon_uses_centroid():
    stops = parse_osm_transit_geojson(OSM_GEOJSON)
    score, meta = score_polygon(FIXTURE_A, stops)
    assert score > 0.5
    assert meta["nearest_mode"] in {"metro", "brt"}
    assert meta["stop_count"] >= 1


@pytest.mark.unit
def test_merge_stops_concatenates():
    a = [TransitStop(0, 0, "bus", "a", "gtfs")]
    b = [TransitStop(1, 1, "metro", "b", "osm")]
    assert len(merge_stops(a, b)) == 2


@pytest.mark.unit
def test_appconfig_transit_defaults():
    get_config.cache_clear()
    cfg = get_config()
    t = cfg.neighbourhood_quality.transit
    assert t.count_radius_m == 400.0
    assert t.max_radius_m == 1200.0
    assert t.mode_weights["metro"] == 1.0
    assert t.mode_weights["bus"] == 0.55
    assert t.nearest_weight == pytest.approx(0.7)
    assert t.density_weight == pytest.approx(0.3)
