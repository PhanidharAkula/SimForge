"""Load per-cell simulation outputs from SUMO / MATSim / DTALite cell dirs.

Each loader returns a small canonical structure the renderers consume.
Engine-specific quirks (path4gmns column-rename gotchas, MATSim CSV
delimiters, SUMO tripinfo XML structure) are absorbed here so the
visualization layer stays clean.
"""

from __future__ import annotations

import csv
import gzip
import logging
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)


# --- per-trip records ------------------------------------------------------

@dataclass
class TripRecord:
    """A completed trip's identity + headline metrics."""

    trip_id: str
    depart_s: float
    duration_s: float
    distance_m: float = 0.0
    origin_node_id: str | None = None
    destination_node_id: str | None = None


# --- per-link records ------------------------------------------------------

@dataclass
class LinkPerformance:
    """One simulated link's aggregate performance for a cell."""

    link_id: str        # engine-side ID (DTALite int, SUMO/MATSim "lXXX")
    volume: float = 0.0          # vehicles per simulation horizon
    mean_speed_kmh: float = 0.0  # avg simulated speed
    free_flow_kmh: float = 0.0   # network capacity reference
    travel_time_s: float = 0.0   # avg per-vehicle on this link

    @property
    def speed_ratio(self) -> float:
        """0..1, lower = more congested. 1 = freeflow."""
        if self.free_flow_kmh <= 0:
            return 1.0
        return min(1.0, self.mean_speed_kmh / self.free_flow_kmh)


# ---------------------------------------------------------------------------
# DTALite (richest per-cell data — link_performance.csv has volume + speed)
# ---------------------------------------------------------------------------

def load_dtalite_links(cell_dir: Path) -> list[LinkPerformance]:
    """Parse DTALite ``link_performance.csv`` -> LinkPerformance list.

    DTALite writes a row per (link, time_period). For SimForge UE runs
    there is one period (AM peak), so one row per link.
    """
    fp = cell_dir / "link_performance.csv"
    if not fp.is_file():
        return []
    out: list[LinkPerformance] = []
    with fp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                link_id = (row.get("link_id") or row.get("from_node_id_to_node_id")
                           or "").strip()
                if not link_id:
                    continue
                vol = float(row.get("volume") or 0.0)
                # DTALite columns vary by version; cover both names.
                speed = float(
                    row.get("speed_kmph") or row.get("speed") or
                    row.get("speed_kmh") or 0.0
                )
                fft = float(row.get("FFTT") or row.get("travel_time") or 0.0)
                cap_speed = float(
                    row.get("free_speed_kmph") or row.get("free_speed") or
                    row.get("speed_limit") or 0.0
                )
                out.append(LinkPerformance(
                    link_id=link_id, volume=vol,
                    mean_speed_kmh=speed,
                    free_flow_kmh=cap_speed if cap_speed > 0 else speed,
                    travel_time_s=fft * 60.0 if fft else 0.0,  # FFTT in minutes
                ))
            except (ValueError, KeyError) as e:
                logger.debug("Skipping DTALite link row %s: %s", row, e)
    logger.info("DTALite cell %s: loaded %d link rows", cell_dir.name, len(out))
    return out


def load_dtalite_trips(cell_dir: Path) -> list[TripRecord]:
    """Parse DTALite ``agent.csv`` -> TripRecord list.

    Each row in agent.csv is one assigned route. For path-based UE,
    multiple routes can exist for the same OD pair; each becomes a
    separate "trip" in this list.

    DTALite's ``agent_id`` is a renumbered 1-indexed integer — it does
    NOT correspond to SimForge's ``trip_id`` (e.g., "t42"). However,
    DTALite preserves the SimForge node IDs as ``o_zone_id`` /
    ``d_zone_id`` (with the "n" prefix stripped to satisfy DTALite's
    int-only zone ID requirement). We restore the prefix here so the
    aggregator can join against SimForge's network nodes uniformly.
    """
    fp = cell_dir / "agent.csv"
    if not fp.is_file():
        return []
    out: list[TripRecord] = []
    # DTALite reports times in minutes (per its docs); we convert to seconds.
    with fp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                tid = (row.get("agent_id") or row.get("trip_id") or "").strip()
                if not tid:
                    continue
                # DTALite columns: travel_time / distance are in minutes / km.
                depart_min = float(row.get("departure_time") or 0.0)
                tt_min = float(row.get("travel_time") or 0.0)
                dist_km = float(row.get("distance") or 0.0)
                # o_zone_id / d_zone_id store the SimForge node int index.
                # SimForge node IDs are "n<int>", so re-add the prefix.
                o_int = (row.get("o_zone_id") or "").strip()
                d_int = (row.get("d_zone_id") or "").strip()
                origin = f"n{o_int}" if o_int else None
                dest = f"n{d_int}" if d_int else None
                out.append(TripRecord(
                    trip_id=tid,
                    depart_s=depart_min * 60.0,
                    duration_s=tt_min * 60.0,
                    distance_m=dist_km * 1000.0,
                    origin_node_id=origin,
                    destination_node_id=dest,
                ))
            except (ValueError, KeyError) as e:
                logger.debug("Skipping DTALite agent row %s: %s", row, e)
    logger.info("DTALite cell %s: loaded %d agent rows", cell_dir.name, len(out))
    return out


# ---------------------------------------------------------------------------
# SUMO (per-trip from tripinfo.xml; per-link needs edgedata.xml which the
# adapter doesn't currently emit by default)
# ---------------------------------------------------------------------------

def load_sumo_trips(cell_dir: Path) -> list[TripRecord]:
    """Parse SUMO ``tripinfo.xml`` -> TripRecord list.

    Trip ID convention in SimForge SUMO adapter: ``veh_<trip_id>``.
    Strips the ``veh_`` prefix so origin/destination joins via demand.csv
    work uniformly across engines.
    """
    fp = cell_dir / "tripinfo.xml"
    if not fp.is_file():
        return []
    out: list[TripRecord] = []
    try:
        ctx = etree.iterparse(str(fp), events=("end",), tag="tripinfo")
        for _, elem in ctx:
            tid = (elem.get("id") or "").removeprefix("veh_")
            try:
                depart = float(elem.get("depart") or 0.0)
                duration = float(elem.get("duration") or 0.0)
                dist = float(elem.get("routeLength") or 0.0)
                out.append(TripRecord(
                    trip_id=tid, depart_s=depart, duration_s=duration,
                    distance_m=dist,
                ))
            except (TypeError, ValueError):
                pass
            elem.clear()
    except Exception as e:
        logger.warning("SUMO tripinfo parse failed for %s: %s", cell_dir, e)
        return []
    logger.info("SUMO cell %s: loaded %d trips", cell_dir.name, len(out))
    return out


# ---------------------------------------------------------------------------
# MATSim (per-trip from output_trips.csv.gz; per-link needs events parsing)
# ---------------------------------------------------------------------------

def load_matsim_trips(cell_dir: Path) -> list[TripRecord]:
    """Parse MATSim ``output_trips.csv.gz`` -> TripRecord list.

    Trip ID convention in SimForge MATSim adapter: ``person_<trip_id>``.
    Strips the prefix so origin/destination joins are uniform across engines.
    """
    fp = cell_dir / "output" / "output_trips.csv.gz"
    if not fp.is_file():
        return []
    out: list[TripRecord] = []
    try:
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                # The "person" column is the SimForge person ID (e.g.
                # "person_t0"), which strips to SimForge trip_id "t0".
                # The "trip_id" column is MATSim's internal leg ID (e.g.
                # "person_t0_1") and does NOT correspond to a SimForge
                # trip_id — don't use it.
                tid = (row.get("person") or "").removeprefix("person_")
                tt_str = row.get("trav_time") or "00:00:00"
                duration = _hms_to_seconds(tt_str)
                dep_str = row.get("dep_time") or "00:00:00"
                depart = _hms_to_seconds(dep_str)
                try:
                    dist = float(row.get("traveled_distance") or 0.0)
                except ValueError:
                    dist = 0.0
                out.append(TripRecord(
                    trip_id=tid, depart_s=depart, duration_s=duration,
                    distance_m=dist,
                ))
    except Exception as e:
        logger.warning("MATSim trips parse failed for %s: %s", cell_dir, e)
        return []
    logger.info("MATSim cell %s: loaded %d trips", cell_dir.name, len(out))
    return out


def _hms_to_seconds(s: str) -> float:
    parts = s.split(":")
    if len(parts) != 3:
        return 0.0
    try:
        h, m, sec = int(parts[0]), int(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + sec
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Cross-engine: aggregate trip records by origin (or destination) node, then
# join with demand.csv to get the engine-side trip <-> bundle-side node link.
# ---------------------------------------------------------------------------

@dataclass
class TripAggregation:
    """Per-node aggregate of trip metrics for one engine."""

    node_counts: dict[str, int] = field(default_factory=dict)
    node_total_duration_s: dict[str, float] = field(default_factory=dict)
    node_total_distance_m: dict[str, float] = field(default_factory=dict)

    def mean_duration_s(self, node_id: str) -> float:
        n = self.node_counts.get(node_id, 0)
        if n == 0:
            return 0.0
        return self.node_total_duration_s.get(node_id, 0.0) / n


def aggregate_trips_by_origin(
    trips: list[TripRecord],
    demand_origin_by_trip: dict[str, str],
) -> TripAggregation:
    """Group trip metrics by their bundle-side origin node ID.

    Priority for origin resolution:
    1. ``trip.origin_node_id`` if the engine populated it (DTALite uses
       o_zone_id from its agent.csv, restored to "n<int>" form).
    2. Otherwise look up in ``demand_origin_by_trip`` by trip_id (for
       SUMO/MATSim where the engine preserves SimForge's "tNN" trip_id
       but doesn't echo origin/dest in its trip output).
    """
    agg = TripAggregation()
    for trip in trips:
        origin = trip.origin_node_id or demand_origin_by_trip.get(trip.trip_id)
        if origin is None:
            continue
        agg.node_counts[origin] = agg.node_counts.get(origin, 0) + 1
        agg.node_total_duration_s[origin] = (
            agg.node_total_duration_s.get(origin, 0.0) + trip.duration_s
        )
        agg.node_total_distance_m[origin] = (
            agg.node_total_distance_m.get(origin, 0.0) + trip.distance_m
        )
    return agg
