from __future__ import annotations

"""
Trip-level metrics from engine output (e.g. SUMO tripinfo.xml).

Three numbers: mean travel time, 95th-percentile travel time, and trip
count. The entry point is:

    parse_sumo_tripinfo(tripinfo_path: Path) -> TripTimeStats
"""

from dataclasses import dataclass
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from typing import List


@dataclass
class TripTimeStats:
    """Aggregate statistics over the completed trips."""
    trip_count: int
    mean_travel_time_s: float
    p95_travel_time_s: float


def _compute_p95(values: List[float]) -> float:
    """Approximate 95th percentile from sorted values.

    For n values, the index is floor(0.95 * (n - 1)).
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(0.95 * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def parse_sumo_tripinfo(tripinfo_path: Path) -> TripTimeStats:
    """Parse a SUMO tripinfo XML and compute the travel-time stats.

    Expects the standard SUMO format: one or more `<tripinfo ... />`
    elements, each with a `duration="..."` (seconds). Returns a
    TripTimeStats aggregated over every record.
    """
    tripinfo_path = tripinfo_path.resolve()
    if not tripinfo_path.is_file():
        raise FileNotFoundError(f"tripinfo file not found: {tripinfo_path}")

    try:
        tree = ET.parse(tripinfo_path)
    except Exception as e:
        raise ValueError(f"Failed to parse tripinfo XML at {tripinfo_path}: {e}") from e

    root = tree.getroot()

    durations: List[float] = []

    # SUMO tripinfo usually uses <tripinfo> as direct children of root
    for elem in root.iter("tripinfo"):
        dur_raw = elem.get("duration")
        if dur_raw is None:
            continue
        try:
            dur = float(dur_raw)
        except ValueError:
            continue
        durations.append(dur)

    if not durations:
        # No completed trips, return zeros
        return TripTimeStats(
            trip_count=0,
            mean_travel_time_s=0.0,
            p95_travel_time_s=0.0,
        )

    mean_tt = statistics.mean(durations)
    p95_tt = _compute_p95(durations)

    return TripTimeStats(
        trip_count=len(durations),
        mean_travel_time_s=mean_tt,
        p95_travel_time_s=p95_tt,
    )