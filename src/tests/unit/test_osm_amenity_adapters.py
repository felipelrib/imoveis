"""Unit tests for OSM POI GeoJSON loader and Overpass parsing (BIN-88)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from shapely.geometry import Polygon

from adapters.geo.osm_overpass import (
    OverpassClient,
    build_overpass_query,
    parse_overpass_elements,
    polygon_bbox,
)
from adapters.geo.osm_poi_loader import load_pois_from_geojson, parse_poi_feature_collection
from core.osm_amenities import classify_poi

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geo"


class TestOsmPoiLoader:
    def test_loads_fixture_points(self):
        pois = load_pois_from_geojson(FIXTURES / "osm_pois_tiny.geojson")
        assert len(pois) == 7
        categories = {classify_poi(p) for p in pois}
        assert "shop" in categories
        assert "park" in categories
        assert None in categories  # cafe ignored at classify time

    def test_skips_non_point(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"shop": "supermarket"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                }
            ],
        }
        assert parse_poi_feature_collection(data) == []


class TestOverpassParse:
    def test_parse_node_and_way_center(self):
        payload = {
            "elements": [
                {
                    "type": "node",
                    "lat": -19.9175,
                    "lon": -43.9375,
                    "tags": {"shop": "supermarket"},
                },
                {
                    "type": "way",
                    "center": {"lat": -19.918, "lon": -43.938},
                    "tags": {"leisure": "park"},
                },
                {"type": "node", "tags": {"amenity": "cafe"}},  # missing coords
            ]
        }
        pois = parse_overpass_elements(payload)
        assert len(pois) == 2
        assert classify_poi(pois[0]) == "shop"
        assert classify_poi(pois[1]) == "park"

    def test_bbox_and_query_contain_bounds(self):
        poly = Polygon(
            [
                (-43.94, -19.92),
                (-43.935, -19.92),
                (-43.935, -19.915),
                (-43.94, -19.915),
                (-43.94, -19.92),
            ]
        )
        south, west, north, east = polygon_bbox(poly)
        assert south == pytest.approx(-19.92)
        assert west == pytest.approx(-43.94)
        query = build_overpass_query(poly)
        assert "shop" in query
        assert f"{south},{west},{north},{east}" in query

    def test_client_uses_cache(self, tmp_path):
        poly = Polygon(
            [
                (-43.94, -19.92),
                (-43.935, -19.92),
                (-43.935, -19.915),
                (-43.94, -19.915),
                (-43.94, -19.92),
            ]
        )
        payload = {
            "elements": [
                {
                    "type": "node",
                    "lat": -19.9175,
                    "lon": -43.9375,
                    "tags": {"amenity": "school"},
                }
            ]
        }
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
        http = httpx.Client(transport=transport)
        sleeps: list[float] = []
        with OverpassClient(
            client=http,
            cache_dir=tmp_path,
            cache_ttl_hours=24,
            rate_limit_per_minute=60,
            sleep_fn=sleeps.append,
        ) as client:
            first = client.fetch_pois_for_polygon(poly)
            second = client.fetch_pois_for_polygon(poly)
        assert len(first) == 1
        assert len(second) == 1
        assert classify_poi(first[0]) == "school"
        # Second hit should be cache — no extra throttle after first request pair
        assert any(tmp_path.iterdir())


class TestAmenityRefresh:
    def test_refresh_geojson_updates_row(self):
        from geoalchemy2.shape import from_shape

        from adapters.geo.amenity_refresh import refresh_neighbourhood_amenities

        poly = Polygon(
            [
                (-43.9400, -19.9200),
                (-43.9350, -19.9200),
                (-43.9350, -19.9150),
                (-43.9400, -19.9150),
                (-43.9400, -19.9200),
            ]
        )
        row = MagicMock()
        row.id = "nid"
        row.name = "FixtureA"
        row.geometry = from_shape(poly, srid=4326)
        row.quality_meta = {"provider": "curated-yaml"}
        row.amenity_score = None

        session = MagicMock()
        query = session.query.return_value
        query.filter.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.all.return_value = [row]

        result = refresh_neighbourhood_amenities(
            session,
            mode="geojson",
            poi_geojson_path=str(FIXTURES / "osm_pois_tiny.geojson"),
            batch_size=10,
        )
        assert result.status == "ok"
        assert result.updated == 1
        assert row.amenity_score is not None
        assert 0.0 <= row.amenity_score <= 1.0
        assert row.quality_meta["source"] == "osm"
        assert row.quality_meta["provider"] == "curated-yaml"
        session.commit.assert_called_once()

    def test_refresh_missing_geojson_path(self):
        from adapters.geo.amenity_refresh import refresh_neighbourhood_amenities

        session = MagicMock()
        result = refresh_neighbourhood_amenities(session, mode="geojson", poi_geojson_path="")
        assert result.status == "error"
        session.query.assert_not_called()


class TestAmenityRefreshTask:
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_task_skips_when_disabled(self, mock_get_config, mock_session_local):
        from types import SimpleNamespace

        from adapters.queue import tasks as tasks_mod

        mock_get_config.return_value = SimpleNamespace(
            neighbourhood_quality=SimpleNamespace(
                osm_amenities=SimpleNamespace(enabled=False),
            )
        )
        result = tasks_mod.refresh_neighbourhood_amenities.run()
        assert result == {"status": "skipped", "updated": 0}
        mock_session_local.assert_not_called()

    @patch("adapters.geo.amenity_refresh.refresh_neighbourhood_amenities")
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_task_runs_when_enabled(self, mock_get_config, mock_session_local, mock_refresh):
        from types import SimpleNamespace

        from adapters.geo.amenity_refresh import AmenityRefreshResult
        from adapters.queue import tasks as tasks_mod

        mock_get_config.return_value = SimpleNamespace(
            neighbourhood_quality=SimpleNamespace(
                osm_amenities=SimpleNamespace(
                    enabled=True,
                    mode="geojson",
                    poi_geojson_path="/tmp/pois.geojson",
                    buffer_m=0,
                    category_targets={"shop": 3},
                    batch_size=25,
                    overpass_url="https://overpass-api.de/api/interpreter",
                    request_timeout_sec=60,
                    rate_limit_per_minute=8,
                    cache_dir="",
                    cache_ttl_hours=24,
                ),
            )
        )
        session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session
        mock_refresh.return_value = AmenityRefreshResult(
            status="ok", updated=2, skipped=0, errors=0, mode="geojson"
        )

        result = tasks_mod.refresh_neighbourhood_amenities.run(batch_size=10)
        assert result["status"] == "ok"
        assert result["updated"] == 2
        mock_refresh.assert_called_once()
        assert mock_refresh.call_args.kwargs["batch_size"] == 10
