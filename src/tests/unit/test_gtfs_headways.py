"""Unit tests for GTFS headway / frequency ingest (BIN-119)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.gtfs_headways import (
    TRANSIT_HEADWAY_DISCLAIMER,
    StopHeadway,
    aggregate_neighbourhood_headway,
    parse_gtfs_clock_to_seconds,
    parse_gtfs_stop_headways,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transit"
GTFS_DIR = FIXTURES / "gtfs_tiny"


@pytest.mark.unit
def test_parse_gtfs_clock_to_seconds():
    assert parse_gtfs_clock_to_seconds("08:00:00") == 8 * 3600
    assert parse_gtfs_clock_to_seconds("25:30:00") == 25 * 3600 + 30 * 60
    assert parse_gtfs_clock_to_seconds("") is None
    assert parse_gtfs_clock_to_seconds("bad") is None


@pytest.mark.unit
def test_parse_gtfs_stop_headways_from_frequencies():
    by_stop = parse_gtfs_stop_headways(GTFS_DIR)
    assert "BUS1" in by_stop
    assert by_stop["BUS1"].method == "gtfs_frequencies"
    assert by_stop["BUS1"].headway_secs == pytest.approx(600.0)


@pytest.mark.unit
def test_parse_gtfs_stop_headways_missing_dir_returns_empty(tmp_path: Path):
    assert parse_gtfs_stop_headways(tmp_path) == {}


@pytest.mark.unit
def test_parse_gtfs_stop_headways_stop_times_median_fallback(tmp_path: Path):
    (tmp_path / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T2,08:10:00,08:10:00,S1,1\n"
        "T3,08:20:00,08:20:00,S1,1\n"
        "T4,08:30:00,08:30:00,S1,1\n",
        encoding="utf-8",
    )
    by_stop = parse_gtfs_stop_headways(tmp_path)
    assert "S1" in by_stop
    assert by_stop["S1"].method == "stop_times_median"
    assert by_stop["S1"].headway_secs == pytest.approx(600.0)


@pytest.mark.unit
def test_parse_gtfs_stop_headways_frequencies_preferred_over_stop_times(tmp_path: Path):
    (tmp_path / "frequencies.txt").write_text(
        "trip_id,start_time,end_time,headway_secs\n"
        "T1,06:00:00,22:00:00,300\n",
        encoding="utf-8",
    )
    (tmp_path / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T2,08:10:00,08:10:00,S1,1\n"
        "T3,08:20:00,08:20:00,S1,1\n"
        "T4,08:30:00,08:30:00,S1,1\n",
        encoding="utf-8",
    )
    by_stop = parse_gtfs_stop_headways(tmp_path)
    assert by_stop["S1"].method == "gtfs_frequencies"
    assert by_stop["S1"].headway_secs == pytest.approx(300.0)


@pytest.mark.unit
def test_aggregate_unavailable_when_no_signals():
    payload = aggregate_neighbourhood_headway(["A", "B"], {})
    assert payload["method"] == "unavailable"
    assert payload["median_headway_min"] is None
    assert payload["stop_sample"] == 0
    assert payload["window"] == "gtfs_export"
    assert payload["disclaimer"] == TRANSIT_HEADWAY_DISCLAIMER


@pytest.mark.unit
def test_aggregate_prefers_frequencies_method():
    per_stop = {
        "A": StopHeadway(headway_secs=600.0, method="gtfs_frequencies"),
        "B": StopHeadway(headway_secs=900.0, method="stop_times_median"),
        "C": StopHeadway(headway_secs=300.0, method="gtfs_frequencies"),
    }
    payload = aggregate_neighbourhood_headway(["A", "B", "C"], per_stop)
    assert payload["method"] == "gtfs_frequencies"
    assert payload["stop_sample"] == 3
    # median of 300, 600, 900 = 600s → 10 min
    assert payload["median_headway_min"] == 10
    assert payload["disclaimer"] == TRANSIT_HEADWAY_DISCLAIMER


@pytest.mark.unit
def test_aggregate_stop_times_only():
    per_stop = {
        "A": StopHeadway(headway_secs=480.0, method="stop_times_median"),
        "B": StopHeadway(headway_secs=720.0, method="stop_times_median"),
    }
    payload = aggregate_neighbourhood_headway(["A", "B", "Z"], per_stop)
    assert payload["method"] == "stop_times_median"
    assert payload["stop_sample"] == 2
    assert payload["median_headway_min"] == 10  # median(480,720)=600s
