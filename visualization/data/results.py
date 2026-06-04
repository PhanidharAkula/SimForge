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
# DTALite (the richest per-cell data: link_performance.csv has volume + speed)
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

    DTALite's ``agent_id`` is a renumbered 1-indexed integer; it does NOT
    match SimForge's ``trip_id`` (e.g. "t42"). It does keep the SimForge node
    IDs, though, as ``o_zone_id`` / ``d_zone_id`` (with the "n" prefix
    stripped to satisfy DTALite's int-only zone IDs). We put the prefix back
    here so the aggregator can join against SimForge's network nodes the same
    way it does for the other engines.
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
# SUMO (per-trip from tripinfo.xml; per-link from routes.rou.xml filtered
# by completed trips)
# ---------------------------------------------------------------------------


def load_sumo_links(cell_dir: Path) -> list[LinkPerformance]:
    """Per-link traffic volume for SUMO, derived from the routes file
    filtered by completed trips in tripinfo.xml.

    SimForge writes routes.rou.xml with each vehicle's BFS-pre-routed link
    sequence. SUMO simulates those and writes tripinfo.xml, one entry per
    completed trip. We count per link, keeping only routes whose vehicle id
    shows up in tripinfo (the trips that actually finished; SUMO refuses some
    insertions on congested edges).

    This is an approximate link load: it counts each route's link sequence
    once per completed trip. It does NOT capture SUMO's real second-by-second
    link usage, which would need --edgedata-output turned on and a re-run.
    Close enough for a picture.
    """
    routes_fp = cell_dir / "routes.rou.xml"
    tripinfo_fp = cell_dir / "tripinfo.xml"
    if not routes_fp.is_file() or not tripinfo_fp.is_file():
        return []

    completed_vehs: set[str] = set()
    try:
        ctx = etree.iterparse(str(tripinfo_fp), events=("end",), tag="tripinfo")
        for _, elem in ctx:
            vid = elem.get("id")
            if vid:
                completed_vehs.add(vid)
            elem.clear()
    except Exception as e:
        logger.warning("SUMO tripinfo parse failed for %s: %s", cell_dir, e)
        return []

    counts: dict[str, int] = {}
    try:
        ctx = etree.iterparse(str(routes_fp), events=("end",), tag="vehicle")
        for _, vehicle in ctx:
            if vehicle.get("id") not in completed_vehs:
                vehicle.clear()
                continue
            for route in vehicle:
                edges = (route.get("edges") or "").split()
                for lid in edges:
                    counts[lid] = counts.get(lid, 0) + 1
            vehicle.clear()
    except Exception as e:
        logger.warning("SUMO routes parse failed for %s: %s", cell_dir, e)
        return []

    out = [LinkPerformance(link_id=lid, volume=float(c)) for lid, c in counts.items()]
    logger.info("SUMO cell %s: aggregated %d links from %d completed trips",
                cell_dir.name, len(out), len(completed_vehs))
    return out


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
# MATSim (per-trip from output_trips.csv.gz; per-link from output_plans.xml.gz
# filtered by completed trips)
# ---------------------------------------------------------------------------


def load_matsim_links(cell_dir: Path) -> list[LinkPerformance]:
    """Per-link traffic volume for MATSim, derived from output_plans.xml.gz
    filtered by completed trips in output_trips.csv.gz.

    SimForge MATSim adapter pre-routes via Phase 12.1's
    ``<route type="links">`` mechanism, so each agent's plan contains
    the full link sequence. With ``lastIteration=0`` the qsim plays out
    these plans without replanning, so the route in the plan IS the
    route the engine simulated.

    Counts each link once per completed trip. Like the SUMO version, this is
    an approximate link load; getting it exactly right would mean parsing
    output_events.xml.gz (every link-enter event), which is correct but
    slower on large scenarios.
    """
    plans_fp = cell_dir / "output" / "output_plans.xml.gz"
    trips_fp = cell_dir / "output" / "output_trips.csv.gz"
    if not plans_fp.is_file() or not trips_fp.is_file():
        return []

    completed_persons: set[str] = set()
    try:
        with gzip.open(trips_fp, "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                pid = (row.get("person") or "").strip()
                if pid:
                    completed_persons.add(pid)
    except Exception as e:
        logger.warning("MATSim trips parse failed for %s: %s", cell_dir, e)
        return []

    counts: dict[str, int] = {}
    try:
        with gzip.open(plans_fp, "rb") as gz:
            ctx = etree.iterparse(gz, events=("end",), tag="person")
            for _, person in ctx:
                pid = person.get("id")
                if pid not in completed_persons:
                    person.clear()
                    continue
                for route in person.iter("route"):
                    if (route.get("type") or "") != "links":
                        continue
                    text = (route.text or "").strip()
                    if not text:
                        continue
                    for lid in text.split():
                        counts[lid] = counts.get(lid, 0) + 1
                person.clear()
    except Exception as e:
        logger.warning("MATSim plans parse failed for %s: %s", cell_dir, e)
        return []

    out = [LinkPerformance(link_id=lid, volume=float(c)) for lid, c in counts.items()]
    logger.info("MATSim cell %s: aggregated %d links from %d completed persons",
                cell_dir.name, len(out), len(completed_persons))
    return out


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
                # "person_t0_1"), not a SimForge trip_id, so don't use it.
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
