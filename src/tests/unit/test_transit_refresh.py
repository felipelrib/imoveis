"""Unit tests for transit refresh adapter + Celery task (BIN-118)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from adapters.geo.transit_refresh import TransitRefreshResult, refresh_transit_proximity
from core.transit_proximity import TransitStop
from core.transit_stops import LoadResult


@pytest.mark.unit
def test_refresh_errors_without_paths():
    session = MagicMock()
    result = refresh_transit_proximity(session, gtfs_dirs=[], osm_geojson_paths=[])
    assert result.status == "error"
    session.query.assert_not_called()


@pytest.mark.unit
def test_refresh_persist_and_score():
    session = MagicMock()
    n = MagicMock()
    n.id = "nid"
    n.geometry = "GEOM"
    session.query.return_value.filter.return_value.all.return_value = [n]
    stops = [TransitStop(-43.9, -19.9, "bus", "A", "gtfs", "B1")]

    with (
        patch(
            "adapters.geo.transit_refresh._parse_file_stops",
            return_value=stops,
        ),
        patch(
            "adapters.geo.transit_refresh.upsert_transit_stops",
            return_value=LoadResult(inserted=1),
        ) as upsert,
        patch(
            "adapters.geo.transit_refresh.to_shape",
            return_value=MagicMock(is_empty=False),
        ),
        patch(
            "adapters.geo.transit_refresh.score_neighbourhood_rows",
            return_value=[MagicMock()],
        ),
        patch(
            "adapters.geo.transit_refresh.apply_transit_scores",
            return_value=1,
        ) as apply,
        patch("adapters.geo.transit_refresh.params_from_config"),
    ):
        result = refresh_transit_proximity(
            session,
            gtfs_dirs=["/tmp/gtfs"],
            persist=True,
            dry_run=False,
        )

    assert result.status == "ok"
    assert result.neighbourhoods_updated == 1
    assert result.stops_inserted == 1
    assert result.provider == "gtfs"
    upsert.assert_called_once()
    apply.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.unit
def test_refresh_from_db_skips_upsert():
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    stops = [TransitStop(-43.9, -19.9, "metro", "M", "osm", "1")]

    with (
        patch(
            "adapters.geo.transit_refresh.stops_from_db",
            return_value=stops,
        ),
        patch("adapters.geo.transit_refresh.upsert_transit_stops") as upsert,
        patch("adapters.geo.transit_refresh.params_from_config"),
    ):
        result = refresh_transit_proximity(session, from_db=True)

    assert result.status == "empty"
    assert result.mode == "from_db"
    assert result.stops_loaded == 1
    upsert.assert_not_called()


@pytest.mark.unit
def test_refresh_dry_run_does_not_write():
    session = MagicMock()
    n = MagicMock()
    n.id = "nid"
    n.geometry = "GEOM"
    session.query.return_value.filter.return_value.all.return_value = [n]
    stops = [TransitStop(-43.9, -19.9, "bus", "A", "gtfs", "B1")]

    with (
        patch(
            "adapters.geo.transit_refresh._parse_file_stops",
            return_value=stops,
        ),
        patch("adapters.geo.transit_refresh.upsert_transit_stops") as upsert,
        patch(
            "adapters.geo.transit_refresh.to_shape",
            return_value=MagicMock(is_empty=False),
        ),
        patch(
            "adapters.geo.transit_refresh.score_neighbourhood_rows",
            return_value=[MagicMock(), MagicMock()],
        ),
        patch("adapters.geo.transit_refresh.apply_transit_scores") as apply,
        patch("adapters.geo.transit_refresh.params_from_config"),
    ):
        result = refresh_transit_proximity(
            session,
            osm_geojson_paths=["/tmp/stops.geojson"],
            dry_run=True,
        )

    assert result.status == "dry_run"
    assert result.neighbourhoods_updated == 2
    upsert.assert_not_called()
    apply.assert_not_called()
    session.commit.assert_not_called()


class TestTransitRefreshTask:
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_task_skips_when_disabled(self, mock_get_config, mock_session_local):
        from adapters.queue import tasks as tasks_mod

        mock_get_config.return_value = SimpleNamespace(
            neighbourhood_quality=SimpleNamespace(
                transit=SimpleNamespace(enabled=False),
            )
        )
        result = tasks_mod.refresh_transit_proximity.run()
        assert result == {"status": "skipped", "neighbourhoods_updated": 0}
        mock_session_local.assert_not_called()

    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_task_errors_when_enabled_without_paths(
        self, mock_get_config, mock_session_local
    ):
        from adapters.queue import tasks as tasks_mod

        mock_get_config.return_value = SimpleNamespace(
            neighbourhood_quality=SimpleNamespace(
                transit=SimpleNamespace(
                    enabled=True,
                    gtfs_dirs=[],
                    osm_geojson_paths=[],
                ),
            )
        )
        result = tasks_mod.refresh_transit_proximity.run()
        assert result["status"] == "error"
        mock_session_local.assert_not_called()

    @patch("adapters.geo.transit_refresh.refresh_transit_proximity")
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_task_runs_when_enabled(
        self, mock_get_config, mock_session_local, mock_refresh
    ):
        from adapters.queue import tasks as tasks_mod

        cfg = SimpleNamespace(
            neighbourhood_quality=SimpleNamespace(
                transit=SimpleNamespace(
                    enabled=True,
                    gtfs_dirs=["/tmp/gtfs"],
                    osm_geojson_paths=[],
                ),
            )
        )
        mock_get_config.return_value = cfg
        session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session
        mock_refresh.return_value = TransitRefreshResult(
            status="ok",
            neighbourhoods_updated=3,
            stops_inserted=10,
            provider="gtfs",
            mode="files",
        )

        result = tasks_mod.refresh_transit_proximity.run()
        assert result["status"] == "ok"
        assert result["neighbourhoods_updated"] == 3
        mock_refresh.assert_called_once()
        assert mock_refresh.call_args.kwargs["gtfs_dirs"] == ["/tmp/gtfs"]
        assert mock_refresh.call_args.kwargs["persist"] is True
