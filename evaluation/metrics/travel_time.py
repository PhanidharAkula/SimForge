from __future__ import annotations

"""
Evaluation metrics for trip-level outputs (e.g., SUMO tripinfo.xml).

We focus on:

- mean travel time
- 95th percentile travel time
- trip count

The primary entrypoint is:

    parse_sumo_tripinfo(tripinfo_path: Path) -> TripTimeStats
"""

from dataclasses import dataclass
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from typing import List


@dataclass
class TripTimeStats:
    """
    Aggregate statistics over completed trips.
    """
    trip_count: int
    mean_travel_time_s: float
    p95_travel_time_s: float


def _compute_p95(values: List[float]) -> float:
    """
    Return an approximate 95th percentile using sorted values.

    For n values, index = floor(0.95 * (n - 1)).
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(0.95 * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def parse_sumo_tripinfo(tripinfo_path: Path) -> TripTimeStats:
    """
    Parse a SUMO tripinfo XML file and compute basic travel-time statistics.

    We expect XML with one or more `<tripinfo ... />` elements, where each element
    has:

        duration="..."   (seconds)

    This matches the standard SUMO tripinfo output format.

    Parameters
    ----------
    tripinfo_path : Path
        Path to the tripinfo XML file.

    Returns
    -------
    TripTimeStats
        Aggregate statistics over all tripinfo records.
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