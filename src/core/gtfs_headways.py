"""GTFS headway / frequency signals for neighbourhood transit meta (BIN-119).

Computes coarse schedule-based headways from ``frequencies.txt`` (preferred)
or median inter-arrival from ``stop_times.txt``. Surfaced under
``quality_meta.transit.headway`` — never treated as live service.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

HeadwayMethod = Literal["gtfs_frequencies", "stop_times_median", "unavailable"]

TRANSIT_HEADWAY_DISCLAIMER = (
    "Schedule-based estimate from GTFS export; not live service frequency."
)

# stop_times consecutive diffs outside this band are noise / overnight gaps
_MIN_HEADWAY_SECS = 120.0
_MAX_HEADWAY_SECS = 7200.0
MIN_STOP_TIME_DIFFS = 3


@dataclass(frozen=True)
class StopHeadway:
    headway_secs: float
    method: Literal["gtfs_frequencies", "stop_times_median"]


def parse_gtfs_clock_to_seconds(value: str) -> float | None:
    """Parse GTFS ``H:MM:SS`` (hours may be ≥24) to seconds from midnight."""
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(parts[0]), int(parts[1]), float(parts[2]))
    except ValueError:
        return None
    if minutes < 0 or minutes > 59 or seconds < 0 or seconds >= 60:
        return None
    if hours < 0:
        return None
    return hours * 3600.0 + minutes * 60.0 + seconds


def _read_gtfs_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values))


def _headways_from_frequencies(gtfs_root: Path) -> dict[str, list[float]]:
    """Map stop_id → list of headway_secs from frequencies.txt via stop_times."""
    freq_path = gtfs_root / "frequencies.txt"
    times_path = gtfs_root / "stop_times.txt"
    if not freq_path.is_file() or not times_path.is_file():
        return {}

    trip_headways: dict[str, list[float]] = {}
    for row in _read_gtfs_csv(freq_path):
        tid = row.get("trip_id")
        if not tid:
            continue
        try:
            secs = float(row.get("headway_secs") or "0")
        except ValueError:
            continue
        if secs <= 0:
            continue
        trip_headways.setdefault(tid, []).append(secs)

    if not trip_headways:
        return {}

    stop_vals: dict[str, list[float]] = {}
    for row in _read_gtfs_csv(times_path):
        sid = row.get("stop_id")
        tid = row.get("trip_id")
        if not sid or not tid or tid not in trip_headways:
            continue
        stop_vals.setdefault(sid, []).extend(trip_headways[tid])
    return stop_vals


def _headways_from_stop_times(gtfs_root: Path) -> dict[str, list[float]]:
    """Map stop_id → consecutive departure diffs within a plausible headway band."""
    times_path = gtfs_root / "stop_times.txt"
    if not times_path.is_file():
        return {}

    by_stop: dict[str, list[float]] = {}
    for row in _read_gtfs_csv(times_path):
        sid = row.get("stop_id")
        if not sid:
            continue
        secs = parse_gtfs_clock_to_seconds(
            row.get("departure_time") or row.get("arrival_time") or ""
        )
        if secs is None:
            continue
        by_stop.setdefault(sid, []).append(secs)

    out: dict[str, list[float]] = {}
    for sid, times in by_stop.items():
        times = sorted(times)
        diffs: list[float] = []
        for i in range(1, len(times)):
            delta = times[i] - times[i - 1]
            if _MIN_HEADWAY_SECS <= delta <= _MAX_HEADWAY_SECS:
                diffs.append(delta)
        if len(diffs) >= MIN_STOP_TIME_DIFFS:
            out[sid] = diffs
    return out


def parse_gtfs_stop_headways(gtfs_dir: str | Path) -> dict[str, StopHeadway]:
    """Parse per-stop headways: frequencies.txt preferred, else stop_times median."""
    directory = Path(gtfs_dir)
    if not directory.is_dir():
        return {}

    result: dict[str, StopHeadway] = {}
    for sid, vals in _headways_from_frequencies(directory).items():
        if vals:
            result[sid] = StopHeadway(
                headway_secs=_median(vals), method="gtfs_frequencies"
            )

    for sid, vals in _headways_from_stop_times(directory).items():
        if sid in result or not vals:
            continue
        result[sid] = StopHeadway(
            headway_secs=_median(vals), method="stop_times_median"
        )
    return result


def aggregate_neighbourhood_headway(
    stop_ids_in_radius: Sequence[str],
    per_stop: Mapping[str, StopHeadway],
) -> dict:
    """Build ``quality_meta.transit.headway`` for stops inside the count radius."""
    samples: list[StopHeadway] = []
    for sid in stop_ids_in_radius:
        hw = per_stop.get(sid)
        if hw is not None:
            samples.append(hw)

    if not samples:
        return {
            "method": "unavailable",
            "median_headway_min": None,
            "stop_sample": 0,
            "window": "gtfs_export",
            "disclaimer": TRANSIT_HEADWAY_DISCLAIMER,
        }

    method: HeadwayMethod = (
        "gtfs_frequencies"
        if any(s.method == "gtfs_frequencies" for s in samples)
        else "stop_times_median"
    )
    median_secs = _median([s.headway_secs for s in samples])
    return {
        "method": method,
        "median_headway_min": int(round(median_secs / 60.0)),
        "stop_sample": len(samples),
        "window": "gtfs_export",
        "disclaimer": TRANSIT_HEADWAY_DISCLAIMER,
    }


def merge_stop_headways(
    *maps: Mapping[str, StopHeadway],
) -> dict[str, StopHeadway]:
    """Merge per-dir maps; later maps win on the same stop_id."""
    out: dict[str, StopHeadway] = {}
    for m in maps:
        out.update(m)
    return out
