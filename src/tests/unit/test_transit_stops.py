"""Unit tests for transit_stops upsert / load (BIN-118)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from shapely.geometry import Point

from core.transit_proximity import TransitStop
from core.transit_stops import (
    LoadResult,
    external_id_for,
    stops_from_db,
    upsert_transit_stops,
)


def _stop(
    *,
    lon: float = -43.9375,
    lat: float = -19.9175,
    mode: str = "bus",
    name: str = "Stop A",
    source: str = "gtfs",
    stop_id: str | None = "BUS1",
) -> TransitStop:
    return TransitStop(
        lon=lon, lat=lat, mode=mode, name=name, source=source, stop_id=stop_id
    )


@pytest.mark.unit
def test_external_id_prefers_stop_id():
    assert external_id_for(_stop(stop_id="BUS1")) == "BUS1"
    assert external_id_for(_stop(stop_id="  BUS2  ")) == "BUS2"


@pytest.mark.unit
def test_external_id_synthesizes_from_coords_when_missing():
    stop = _stop(lon=-43.93751, lat=-19.91749, stop_id=None)
    assert external_id_for(stop) == "-43.93751:-19.91749"
    assert external_id_for(_stop(stop_id="")) == "-43.93750:-19.91750"
    assert external_id_for(_stop(stop_id="   ")) == "-43.93750:-19.91750"


@pytest.mark.unit
def test_upsert_inserts_when_missing():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    with patch("core.transit_stops.from_shape", return_value="WKB"):
        result = upsert_transit_stops(session, [_stop()])

    assert result == LoadResult(inserted=1, updated=0, skipped=0)
    session.add.assert_called_once()
    session.flush.assert_called_once()
    added = session.add.call_args.args[0]
    assert added.source == "gtfs"
    assert added.external_id == "BUS1"
    assert added.name == "Stop A"
    assert added.mode == "bus"
    assert added.location == "WKB"


@pytest.mark.unit
def test_upsert_skips_unchanged():
    existing = MagicMock()
    existing.name = "Stop A"
    existing.mode = "bus"
    existing.location = "EXISTING"
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    with (
        patch("core.transit_stops.from_shape", return_value="WKB"),
        patch("core.transit_stops.to_shape", return_value=Point(-43.9375, -19.9175)),
    ):
        result = upsert_transit_stops(session, [_stop()])

    assert result == LoadResult(inserted=0, updated=0, skipped=1)
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.unit
def test_upsert_updates_when_mode_or_location_changes():
    existing = MagicMock()
    existing.name = "Stop A"
    existing.mode = "bus"
    existing.location = "EXISTING"
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    with (
        patch("core.transit_stops.from_shape", return_value="NEW_WKB"),
        patch("core.transit_stops.to_shape", return_value=Point(-43.9375, -19.9175)),
    ):
        result = upsert_transit_stops(
            session, [_stop(mode="metro", name="Metro A")]
        )

    assert result == LoadResult(inserted=0, updated=1, skipped=0)
    assert existing.mode == "metro"
    assert existing.name == "Metro A"
    assert existing.location == "NEW_WKB"
    session.flush.assert_called_once()


@pytest.mark.unit
def test_upsert_updates_when_point_moves():
    existing = MagicMock()
    existing.name = "Stop A"
    existing.mode = "bus"
    existing.location = "EXISTING"
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    with (
        patch("core.transit_stops.from_shape", return_value="NEW_WKB"),
        patch("core.transit_stops.to_shape", return_value=Point(-43.9400, -19.9200)),
    ):
        result = upsert_transit_stops(session, [_stop()])

    assert result.updated == 1
    assert existing.location == "NEW_WKB"


@pytest.mark.unit
def test_stops_from_db_maps_rows():
    row = MagicMock()
    row.mode = "metro"
    row.name = "Central"
    row.source = "gtfs"
    row.external_id = "M1"
    row.location = "LOC"
    session = MagicMock()
    session.query.return_value.order_by.return_value = [row]

    with patch("core.transit_stops.to_shape", return_value=Point(-43.9, -19.9)):
        stops = stops_from_db(session)

    assert len(stops) == 1
    assert stops[0] == TransitStop(
        lon=-43.9,
        lat=-19.9,
        mode="metro",
        name="Central",
        source="gtfs",
        stop_id="M1",
    )


@pytest.mark.unit
def test_stops_from_db_skips_empty_geometry():
    row = MagicMock()
    row.location = "LOC"
    session = MagicMock()
    session.query.return_value.order_by.return_value = [row]

    with patch("core.transit_stops.to_shape", return_value=Point()):
        assert stops_from_db(session) == []
