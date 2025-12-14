from __future__ import annotations

"""
Tests for evaluation.metrics.travel_time.

We do NOT need SUMO installed; we just fabricate a minimal tripinfo XML
that looks like SUMO's output and verify the computed statistics.
"""

from pathlib import Path

from evaluation.metrics.travel_time import parse_sumo_tripinfo, TripTimeStats


def _write_fake_tripinfo(path: Path) -> None:
    """
    Write a tiny fake SUMO-like tripinfo.xml file.

    Durations (seconds): 10, 20, 30, 40, 50
    """
    content = """<?xml version="1.0" encoding="UTF-8"?>
<tripinfos>
    <tripinfo id="veh_1" duration="10" depart="0" arrival="10" />
    <tripinfo id="veh_2" duration="20" depart="0" arrival="20" />
    <tripinfo id="veh_3" duration="30" depart="0" arrival="30" />
    <tripinfo id="veh_4" duration="40" depart="0" arrival="40" />
    <tripinfo id="veh_5" duration="50" depart="0" arrival="50" />
</tripinfos>
"""
    path.write_text(content, encoding="utf-8")


def test_parse_sumo_tripinfo_basic(tmp_path) -> None:
    """
    For durations 10, 20, 30, 40, 50:

      - trip_count = 5
      - mean = 30
      - 95th percentile = near the max (50 with our index rule)
    """
    tripinfo_path = tmp_path / "tripinfo.xml"
    _write_fake_tripinfo(tripinfo_path)

    stats: TripTimeStats = parse_sumo_tripinfo(tripinfo_path)

    assert stats.trip_count == 5
    # Mean should be exactly 30.0 for this sequence
    assert abs(stats.mean_travel_time_s - 30.0) < 1e-6
    # p95 with our definition (floor(0.95*(n-1))) should select the 4th value = 40.0
    assert abs(stats.p95_travel_time_s - 40.0) < 1e-6


def test_parse_sumo_tripinfo_empty(tmp_path) -> None:
    """
    If the tripinfo file has no <tripinfo> elements,
    we expect zero trip_count and zeroed stats.
    """
    tripinfo_path = tmp_path / "tripinfo_empty.xml"
    tripinfo_path.write_text('<?xml version="1.0" encoding="UTF-8"?><tripinfos></tripinfos>')

    stats = parse_sumo_tripinfo(tripinfo_path)

    assert stats.trip_count == 0
    assert stats.mean_travel_time_s == 0.0
    assert stats.p95_travel_time_s == 0.0