"""
Census-calibrated demand from modelgen data plus the canonical network.

The demand this module produces is grounded in U.S. Census PUMS microdata.
It takes a parsed ModelData (buildings, households, persons, and activity
schedules where present) and the canonical network.xml, and writes
demand.csv:

  - Origins        weighted by residential building population.
  - Destinations   schedule-first hybrid:
                     1. If the chosen person has a cityscape activity
                        schedule, use the workplace bld_id from it (a real
                        PUMS-derived OD pair).
                     2. Otherwise fall back to the gravity sampler
                        (degree-weighted, distance-decayed around the
                        person's PUMS commute time).
  - Departure times morning peak, calibrated by PUMS JWMNP commute time.
                     Cityscape's schedule field hardcodes 8 AM and 5 PM,
                     which we deliberately don't use; they'd pile everyone
                     onto 08:00 at once.
  - Mode           from PUMS JWTRNS (car-only by default; multi-mode when
                     you pass modes=[...]).

The CSV carries an extra `dest_source` column ({"schedule", "gravity"}) so
each trip's provenance survives. Adapters read the canonical 5 columns by
name and ignore the extra one. The summary dict from
``generate_census_demand`` has a ``provenance`` block (counts and fallback
reasons) that ``generate.py`` writes into generation_metadata.json.

Usage (library):
    from pipeline.demand.parse_model_file import parse_model_file
    from pipeline.demand.generate_census_demand import generate_census_demand

    data = parse_model_file(model_path, bbox=(...))
    result = generate_census_demand(
        model_data=data,
        network_path=Path("scenarios/chicago_1k_car/network.xml"),
        output_path=Path("scenarios/chicago_1k_car/demand.csv"),
        num_trips=1000,
        seed=42,
    )
"""

import csv
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

import numpy as np
from lxml import etree

from pipeline.demand.parse_model_file import ModelData, Building, JWTRNS_TO_MODE
from pipeline.network.scc import compute_largest_scc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Network loading (lightweight: just nodes + adjacency)
# ---------------------------------------------------------------------------

@dataclass
class NetworkInfo:
    """Minimal network representation for demand generation."""
    node_ids: list[str]
    node_coords: dict[str, tuple[float, float]]  # id → (lon, lat)
    node_degrees: dict[str, int]
    adjacency: dict[str, list[str]]
    scc_nodes: set[str]  # nodes in the largest strongly-connected component


def _load_network_nodes(network_path: Path) -> NetworkInfo:
    """Load node coordinates, adjacency, and the largest SCC from network.xml."""
    if not network_path.is_file():
        raise FileNotFoundError(
            f"Network file not found: {network_path}\n"
            f"  Census demand generation requires a valid network.xml.\n"
            f"  Run network generation first."
        )
    try:
        tree = etree.parse(str(network_path))
    except etree.XMLSyntaxError as e:
        raise ValueError(
            f"Failed to parse network.xml at {network_path}: {e}\n"
            f"  The file may be corrupted or truncated. Re-generate it."
        ) from e
    root = tree.getroot()

    node_ids = []
    node_coords = {}
    node_degrees: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)
    edges: list[tuple[str, str]] = []

    for node in root.findall(".//node"):
        nid = node.get("id")
        # Skip nodes missing an id (mirrors pipeline/network/scc.py): a
        # malformed network with an id-less <node> would otherwise crash the
        # adjacency/degree bookkeeping with a TypeError on the None key.
        if not nid:
            continue
        x = float(node.get("x", 0))
        y = float(node.get("y", 0))
        node_ids.append(nid)
        node_coords[nid] = (x, y)  # x=lon, y=lat

    if not node_ids:
        raise ValueError(
            f"No valid nodes found in network.xml at {network_path}: "
            f"every <node> was missing an 'id' attribute. Re-generate the network."
        )

    for link in root.findall(".//link"):
        from_node = link.get("from")
        to_node = link.get("to")
        if from_node and to_node and from_node != to_node:
            adjacency[from_node].append(to_node)
            node_degrees[from_node] += 1
            node_degrees[to_node] += 1
            edges.append((from_node, to_node))

    scc = compute_largest_scc(set(node_ids), edges)
    logger.info(
        "Network largest SCC: %d/%d nodes (%.1f%%) — demand will be sampled within it",
        len(scc), len(node_ids),
        (100.0 * len(scc) / len(node_ids)) if node_ids else 0.0,
    )

    return NetworkInfo(
        node_ids=sorted(node_ids),
        node_coords=node_coords,
        node_degrees=dict(node_degrees),
        adjacency=dict(adjacency),
        scc_nodes=scc,
    )


# ---------------------------------------------------------------------------
# Building → Network node mapping
# ---------------------------------------------------------------------------

def _haversine_km(coord1: tuple[float, float],
                  coord2: tuple[float, float]) -> float:
    """Haversine distance in km between two (lon, lat) pairs."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def map_buildings_to_nodes(
    buildings: list[Building],
    network: NetworkInfo,
    max_distance_km: float = 1.0,
) -> dict[int, str]:
    """
    Snap each building to its nearest canonical network node.

    We use the building's way_lat/way_lon (the model file's snap point on
    the nearest road), which is more accurate than the raw centroid.

    Args:
        buildings: List of Building objects.
        network: NetworkInfo with node coordinates.
        max_distance_km: Maximum allowed distance; buildings farther
                         from any node are dropped.

    Returns:
        Dict of bld_id → node_id.
    """
    # Build a simple spatial index: bucket nodes into grid cells
    # This avoids O(B×N) brute-force matching
    cell_size = 0.005  # ~500 m at mid-latitudes
    grid: dict[tuple[int, int], list[str]] = defaultdict(list)

    for nid, (lon, lat) in network.node_coords.items():
        key = (int(lat / cell_size), int(lon / cell_size))
        grid[key].append(nid)

    mapping: dict[int, str] = {}
    unmapped = 0

    for bld in buildings:
        # Use way snap point for matching (more accurate than building centroid)
        bld_lon = bld.way_lon
        bld_lat = bld.way_lat
        bld_key = (int(bld_lat / cell_size), int(bld_lon / cell_size))

        best_node = None
        best_dist = float("inf")

        # Search in 3×3 neighborhood of grid cells
        for di in range(-1, 2):
            for dj in range(-1, 2):
                neighbor_key = (bld_key[0] + di, bld_key[1] + dj)
                for nid in grid.get(neighbor_key, []):
                    nlon, nlat = network.node_coords[nid]
                    dist = _haversine_km((bld_lon, bld_lat), (nlon, nlat))
                    if dist < best_dist:
                        best_dist = dist
                        best_node = nid

        if best_node is not None and best_dist <= max_distance_km:
            mapping[bld.bld_id] = best_node
        else:
            unmapped += 1

    logger.info("Mapped %d buildings to network nodes (%d unmapped)",
                len(mapping), unmapped)
    return mapping


# ---------------------------------------------------------------------------
# Departure time generation (morning peak profile)
# ---------------------------------------------------------------------------

# Cityscape's Schedule-generator hardcodes the AM-peak workplace arrival at
# 28800 s (08:00) and the PM-peak return at 61200 s (17:00); see
# `model_gen/ScheduleGenerator.h` and the corresponding ScheduleEntry.h
# field semantics. Persons whose mode cityscape doesn't cover (non-code-1)
# have an empty schedule, so we fall back to these constants for trip
# timing rather than sampling a Gaussian peak. That keeps every demand
# row's temporal placement grounded in PUMS rather than a synthetic
# distribution.
_CITYSCAPE_AM_ARRIVAL_S = 28800   # 08:00 AM workplace arrival
_CITYSCAPE_PM_ARRIVAL_S = 61200   # 17:00 PM home return


# Trip-purpose categorisation for the AM/PM peak budget split. Each peak
# bucket includes the bare HBW trip plus its school-chain pair, since
# chained legs consume budget slots from the same peak as their HBW partner.
# AM chain = HBSchool_AM (home→school) + HBW_AM_chained (school→work).
# PM chain = HBW_PM_chained (work→school) + HBSchool_PM (school→home).
AM_PURPOSES: frozenset[str] = frozenset({"HBW_AM", "HBSchool_AM", "HBW_AM_chained"})
PM_PURPOSES: frozenset[str] = frozenset({"HBW_PM", "HBSchool_PM", "HBW_PM_chained"})


def _generate_departure_time(
    commute_min: int,
    horizon_start: int,
    horizon_end: int,
    arrival_time_s: int = _CITYSCAPE_AM_ARRIVAL_S,
) -> int:
    """A per-person departure time, straight from real PUMS data.

    ``departure = arrival_time_s - commute_min * 60``

    ``arrival_time_s`` is cityscape's workplace-arrival time (28800 s,
    08:00, for schedule-driven persons) and ``commute_min`` is the person's
    PUMS `JWMNP` (travel time to work, in minutes). This took over from the
    pre-V5 Gaussian peak that parked every trip at the horizon midpoint no
    matter how long the actual commute was.

    When the horizon doesn't cover cityscape's arrival time (rare; most
    thesis bundles use 7-8 AM or 6-10 AM windows that include 28800), the
    result clamps to ``[horizon_start, horizon_end - 1]``. A long commute
    can put the departure before ``horizon_start``, and those clamp to
    ``horizon_start`` rather than getting dropped, which keeps the requested
    trip count steady.
    """
    departure = arrival_time_s - commute_min * 60
    return int(max(horizon_start, min(horizon_end - 1, departure)))


# ---------------------------------------------------------------------------
# HBSchool support (V5+)
# ---------------------------------------------------------------------------

# OSM `building=*` tag values that denote a school. Cityscape preserves
# these on `bld.kind` (with optional trailing colon for subkind). We match
# on the leading prefix so e.g. `school:fast_food` (rare misclassification)
# still counts; mostly the values come through bare like `school:` or
# `kindergarten:`.
_SCHOOL_KIND_PREFIXES = (
    "school", "kindergarten", "preschool",
    "college", "university",
)

# How far from home we'll look for the nearest school (km). Real US
# catchment areas run 1-3 km in dense urban cores and 5-8 km out in the
# suburbs. 5 km is a reasonable ceiling; past that a chained drop-off is
# unlikely (the parent would just put the kid on the bus).
_SCHOOL_MAX_KM = 5.0


def _is_school_kind(kind: str) -> bool:
    """True if a Building.kind value denotes a school (any school level)."""
    if not kind:
        return False
    k = kind.lower().strip().rstrip(":").split(":")[0]
    return k in _SCHOOL_KIND_PREFIXES


def _build_school_destination_array(
    model_data: ModelData,
    bld_to_node: dict,
    network: "NetworkInfo",
):
    """Pre-compute (school_node, lat, lon) arrays for a vectorized
    nearest-school lookup. Returns (nodes_list, lats_array, lons_array),
    ready for a haversine distance against parent home coordinates.

    A school whose nearest network node falls outside the SCC gets dropped,
    since no home could route to it anyway.
    """
    nodes: list = []
    lats: list = []
    lons: list = []
    for bld in model_data.buildings:
        if not _is_school_kind(bld.kind):
            continue
        snode = bld_to_node.get(bld.bld_id)
        if snode is None or snode not in network.scc_nodes:
            continue
        nodes.append(snode)
        lats.append(bld.lat)
        lons.append(bld.lon)
    return nodes, np.array(lats), np.array(lons)


def _has_school_age_dependent(person, model_data: ModelData) -> bool:
    """Does this person's household have a school-age (AGEP < 18) dependent?

    True when the household holds at least one *other* person whose age is
    in [0, 18). The `>= 0` check drops PUMS's `-1` (not-applicable) sentinel.

    The catch: kids in PUMS have `JWTRNS=-1` (not a worker), so the
    mode/car-only step filters them out of `model_data.persons`, and a
    `model_data.per_by_id` lookup would never see them. So we read
    `model_data.age_by_per_id` instead, which the parser fills from the
    unfiltered all-persons pass and therefore covers every household member
    no matter their own JWTRNS.
    """
    home_bld = model_data.home_bld_by_per_id.get(person.per_id)
    if home_bld is None:
        return False
    households = model_data.hld_by_bld.get(home_bld, [])
    for hld in households:
        if person.per_id not in hld.person_ids:
            continue
        for other_id in hld.person_ids:
            if other_id == person.per_id:
                continue
            age = model_data.age_by_per_id.get(other_id)
            if age is not None and 0 <= age < 18:
                return True
    return False


def _nearest_school_node(
    home_lat: float, home_lon: float,
    school_nodes: list, school_lats: np.ndarray, school_lons: np.ndarray,
    R_KM: float = 6371.0,
    max_km: float = _SCHOOL_MAX_KM,
) -> Optional[str]:
    """Vectorized nearest-school lookup using haversine distance.

    Returns the school node ID with smallest distance to (home_lat,
    home_lon), or None if every school is beyond ``max_km``.
    """
    if not school_nodes:
        return None
    home_lat_rad = math.radians(home_lat)
    cos_home = math.cos(home_lat_rad)
    school_lats_rad = np.radians(school_lats)
    dlat = school_lats_rad - home_lat_rad
    dlon = np.radians(school_lons - home_lon)
    a = (np.sin(dlat * 0.5) ** 2
         + cos_home * np.cos(school_lats_rad) * np.sin(dlon * 0.5) ** 2)
    distances_km = R_KM * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    nearest_idx = int(np.argmin(distances_km))
    if distances_km[nearest_idx] > max_km:
        return None
    return school_nodes[nearest_idx]


# ---------------------------------------------------------------------------
# Main demand generator
# ---------------------------------------------------------------------------

def generate_census_demand(
    model_data: ModelData,
    network_path: Path,
    output_path: Path,
    num_trips: int = 5000,
    seed: int = 42,
    horizon_start: int = 0,
    horizon_end: int = 3600,
    mode: str = "car",
    modes: Optional[list[str]] = None,
    max_snap_distance_km: float = 0.5,
    allow_oversample: bool = False,
) -> dict:
    """
    Write a census-calibrated demand.csv from model data and the network.

    The pipeline:
      1. Load the canonical network nodes.
      2. Snap residential buildings to their nearest network nodes.
      3. Weight origins by building population.
      4. For each trip:
         a. Sample an origin node (population-weighted).
         b. Sample a census person from that building (for the commute profile).
         c. Sample a destination (degree-weighted gravity, distance-decayed).
         d. Set the departure time from the JWMNP-calibrated peak profile.
      5. Write demand.csv.

    Args:
        model_data: Parsed ModelData from parse_model_file().
        network_path: Path to canonical network.xml.
        output_path: Path to write demand.csv.
        num_trips: Number of trips to generate.
        seed: Random seed for reproducibility.
        horizon_start: Simulation start time (seconds).
        horizon_end: Simulation end time (seconds).
        mode: Single travel mode for all trips (default "car").
              Ignored if `modes` is provided.
        modes: List of allowed modes (e.g. ["car", "transit"]).
               When provided, each trip gets the census person's actual
               mode from JWTRNS.  Only persons with modes in this list
               are sampled.
        max_snap_distance_km: Max distance for building-to-node snap.
        allow_oversample: If True, allow num_trips > available commuters
            (origins will be resampled). If False, raise an error when the
            model file does not contain enough raw commuter records.

    Returns:
        Summary dict compatible with existing pipeline.
    """
    rng = random.Random(seed)

    # 1. Load network
    network = _load_network_nodes(network_path)
    logger.info("Loaded network: %d nodes", len(network.node_ids))

    # 2. Map buildings to nodes
    bld_to_node = map_buildings_to_nodes(
        model_data.buildings, network, max_distance_km=max_snap_distance_km
    )

    # 3. Build origin weights: residential buildings only, restricted to SCC.
    #    Weight = building population (from model file). Buildings whose nearest
    #    node lies outside the largest strongly-connected component are dropped
    #    here so every emitted trip is routable in both directions (matching the
    #    feasibility filter every adapter applies before simulation).
    origin_node_pop: dict[str, int] = defaultdict(int)
    origin_node_buildings: dict[str, list[Building]] = defaultdict(list)
    origins_outside_scc = 0

    for bld in model_data.buildings:
        if bld.bld_id not in bld_to_node:
            continue
        if bld.population <= 0:
            continue
        node_id = bld_to_node[bld.bld_id]
        if node_id not in network.scc_nodes:
            origins_outside_scc += 1
            continue
        origin_node_pop[node_id] += bld.population
        origin_node_buildings[node_id].append(bld)

    if not origin_node_pop:
        n_bld = len(model_data.buildings)
        n_per = len(model_data.persons)
        raise ValueError(
            f"No residential buildings mapped to network nodes inside the largest SCC.\n"
            f"  Model file contained {n_bld:,} buildings and {n_per:,} persons "
            f"within the bounding box; {origins_outside_scc} buildings mapped to "
            f"nodes outside the routable component.\n"
            f"  If totals are 0, the model file likely covers a different city "
            f"than this scenario's bounding box."
        )

    origin_nodes = list(origin_node_pop.keys())
    origin_weights = [origin_node_pop[n] for n in origin_nodes]

    if origins_outside_scc:
        logger.info(
            "Dropped %d residential buildings whose nearest node was outside the SCC",
            origins_outside_scc,
        )
    logger.info("Origin nodes: %d (total pop weight: %d)",
                len(origin_nodes), sum(origin_weights))

    # 4. Build destination weights: degree-based, restricted to SCC.
    dest_nodes = [n for n in network.node_ids
                  if n in network.scc_nodes
                  and network.node_degrees.get(n, 0) > 0]
    dest_weights = [network.node_degrees.get(n, 1) + 1 for n in dest_nodes]

    # Pre-compute coordinate lookup for distance calculations
    dest_coords = {n: network.node_coords[n] for n in dest_nodes}

    # Vectorised arrays for the per-trip dest-scoring hot loop.
    # node_coords stores (lon, lat); the vectorised haversine below assumes
    # lon = column 0, lat = column 1.
    _dest_lons = np.array([dest_coords[n][0] for n in dest_nodes], dtype=np.float64)
    _dest_lats = np.array([dest_coords[n][1] for n in dest_nodes], dtype=np.float64)
    _dest_lats_rad = np.radians(_dest_lats)
    _dest_cos_lat = np.cos(_dest_lats_rad)
    _dest_weights_arr = np.asarray(dest_weights, dtype=np.float64)
    _node_idx = {n: i for i, n in enumerate(dest_nodes)}
    _R_KM = 6371.0

    # 5. Build a person pool: census persons for commute-time sampling,
    #    grouped by building so the gravity path can sample origin-correlated.
    bld_persons: dict[int, list] = defaultdict(list)
    for hld in model_data.households:
        for pid in hld.person_ids:
            per = model_data.per_by_id.get(pid)
            if per is not None and per.commute_min > 0:
                bld_persons[hld.bld_id].append(per)

    # Flat pool as fallback
    all_commuters = [p for p in model_data.persons if p.commute_min > 0]
    if not all_commuters:
        logger.warning("No commuters found in model data — using flat 30-min default")
        class _FakePerson:
            commute_min = 30
            transport_mode = 1
            schedule: list = []  # type: ignore[var-annotated]
        all_commuters = [_FakePerson()]  # type: ignore

    avg_commute = sum(p.commute_min for p in all_commuters) / len(all_commuters)
    logger.info("Census commuters: %d (avg %.0f min)", len(all_commuters), avg_commute)

    # 5b. Schedule-driven pool: persons whose cityscape schedule resolves to a
    # valid (home_node, dest_node) pair inside the bbox + SCC. Persons whose
    # schedule references a building we don't have (orphan), maps to a node
    # outside the SCC, or collapses to a self-trip are dropped here and will
    # be served by the gravity fallback in Phase 2 below.
    valid_scheduled: list[tuple[object, str, str]] = []
    fallback_reasons: Counter[str] = Counter()
    for per in model_data.persons:
        if per.commute_min <= 0 or not per.schedule:
            continue
        home_bld_id = model_data.home_bld_by_per_id.get(per.per_id)
        if home_bld_id is None:
            fallback_reasons["no_home_household"] += 1
            continue
        home_node = bld_to_node.get(home_bld_id)
        if home_node is None:
            fallback_reasons["home_unmapped_to_node"] += 1
            continue
        if home_node not in network.scc_nodes:
            fallback_reasons["home_outside_scc"] += 1
            continue
        # In cityscape's output the first activity is the workplace (8 AM
        # arrival), the second the trip home (5 PM). We take the workplace
        # destination and its arrival time, then compute departure as
        # `arrival - commute_min*60` (V5, real PUMS JWMNP) instead of the
        # pre-V5 Gaussian around the horizon midpoint.
        dest_bld_id = per.schedule[0].bld_id
        dest_node = bld_to_node.get(dest_bld_id)
        if dest_node is None:
            fallback_reasons["schedule_dest_orphan_or_outside_bbox"] += 1
            continue
        if dest_node not in network.scc_nodes:
            fallback_reasons["schedule_dest_outside_scc"] += 1
            continue
        if home_node == dest_node:
            fallback_reasons["schedule_dest_equals_home"] += 1
            continue
        valid_scheduled.append((per, home_node, dest_node))

    logger.info(
        "Schedule-driven pool: %d persons with usable workplace destinations "
        "(of %d with any schedule)",
        len(valid_scheduled),
        sum(1 for p in model_data.persons if p.schedule),
    )
    if fallback_reasons:
        logger.info("  Schedule rejections by reason: %s", dict(fallback_reasons))

    # Guard: refuse to oversample unless explicitly allowed
    if num_trips > len(all_commuters) and not allow_oversample:
        raise ValueError(
            f"Requested {num_trips:,} trips but only {len(all_commuters):,} "
            f"raw census commuters are available in the model file for this "
            f"bounding box.  This would require reusing the same origin "
            f"records.\n\n"
            f"Options:\n"
            f"  1. Pass --allow-oversample to permit resampling origins\n"
            f"  2. Omit --model to use the synthetic gravity model instead\n"
            f"  3. Use a wider bounding box / radius to capture more records\n"
            f"  4. (Future) Enable WGTP household-weight expansion\n"
        )
    if num_trips > len(all_commuters) and allow_oversample:
        ratio = num_trips / len(all_commuters)
        logger.warning(
            "Oversampling enabled: %d trips from %d raw commuters "
            "(%.1f× oversample ratio — origins will repeat)",
            num_trips, len(all_commuters), ratio,
        )

    def _trip_mode_for(person) -> str:
        """Resolve a trip's mode column from the requested mode set + person."""
        if modes is not None:
            return JWTRNS_TO_MODE.get(person.transport_mode, "car")
        return mode

    # 6. Generate trips: Phase 1 (schedule-driven), then Phase 2 (gravity).
    # The rows here have no `trip_id` yet; ids are assigned after the final
    # sort by departure_time so they stay stable and dense (t0..tN-1).
    trips: list[dict] = []

    # Which peaks are in the horizon. V5+ adds PM HBW (work to home at 17:00)
    # trips from cityscape's `schedule[1]` tuple, which had been live data in
    # modelgen all along but was getting thrown away. The budget split: if
    # both AM and PM peaks land inside the user's horizon, split the trips
    # 50/50 across the two purposes; otherwise put everything on whichever
    # peak is in window. AM-only horizons (chicago_1k_car 7-8 AM, nyc_10k_car
    # 7-9 AM, la_50k_car 6-10 AM, nyc_500k_car 6-10 AM) come out identical to
    # the pre-V5 demand.csv, so back-compat holds.
    am_in_horizon = horizon_start <= _CITYSCAPE_AM_ARRIVAL_S <= horizon_end
    pm_in_horizon = horizon_start <= _CITYSCAPE_PM_ARRIVAL_S <= horizon_end

    if am_in_horizon and pm_in_horizon:
        n_am_target = num_trips // 2
        n_pm_target = num_trips - n_am_target
        peak_split_note = f"AM={n_am_target} + PM={n_pm_target}"
    elif pm_in_horizon and not am_in_horizon:
        n_am_target = 0
        n_pm_target = num_trips
        peak_split_note = f"PM-only horizon, all {n_pm_target} trips are HBW return"
    else:
        # AM-only or neither (clamp falls back to AM template).
        n_am_target = num_trips
        n_pm_target = 0
        peak_split_note = f"AM-only horizon, all {n_am_target} trips are HBW outbound"
    logger.info(
        "Trip purpose allocation across peaks (modelgen schedule[0]+schedule[1]): %s",
        peak_split_note,
    )

    # V5+: pre-compute school-building positions for HBSchool chain
    # generation. Parents with school-age dependents (AGEP<18 in same
    # household) get a home → school → work morning chain instead of
    # the bare home → work trip. Schools come from OSM building tags
    # (kind=school|kindergarten|preschool|college|university) that
    # cityscape preserves on `Building.kind`.
    school_nodes, school_lats, school_lons = _build_school_destination_array(
        model_data, bld_to_node, network,
    )
    if school_nodes:
        logger.info(
            "HBSchool: %d school buildings inside SCC available for chain destinations",
            len(school_nodes),
        )

    def _maybe_school_chain_for(person, home_node, work_node):
        """Return the school_node when this person has a school-age
        dependent, a school sits within `_SCHOOL_MAX_KM` of home, and the
        chain won't collapse into a self-trip; otherwise None.

        The self-trip guard: if the building-to-node snap lands home,
        school, or work on the same network node, the chain would emit a
        ``home -> school`` or ``school -> work`` row with origin == dest,
        which the validator's
        TestDemandIntegrity.test_origin_differs_from_destination rightly
        rejects. It happens most in dense grids where several OSM buildings
        collapse onto one graph node after SCC pruning. We skip the chain in
        that case and the caller falls back to a plain HBW row, keeping the
        realism without breaking referential integrity.
        """
        if not school_nodes:
            return None
        if not _has_school_age_dependent(person, model_data):
            return None
        home_lon, home_lat = network.node_coords[home_node]
        school_node = _nearest_school_node(
            home_lat, home_lon,
            school_nodes, school_lats, school_lons,
        )
        if school_node is None:
            return None
        # Reject chains that would self-trip on either leg.
        if school_node == home_node or school_node == work_node:
            return None
        return school_node

    # Phase 1a: Schedule-driven AM trips (home → work, 8 AM arrival).
    # V5+: parents with a school-age dependent emit a chained
    # home → school → work pair (HBSchool_AM + HBW_AM_chained) instead
    # of a bare home → work trip. Each chain consumes 2 budget slots.
    n_school_chains = 0
    if n_am_target > 0 and len(valid_scheduled) > 0:
        sched_indices = list(range(len(valid_scheduled)))
        rng.shuffle(sched_indices)
        am_emitted = 0
        for i in sched_indices:
            if am_emitted >= n_am_target:
                break
            person, home_node, dest_node = valid_scheduled[i]
            arrival_s = person.schedule[0].time_s
            departure_s = _generate_departure_time(
                person.commute_min, horizon_start, horizon_end,
                arrival_time_s=arrival_s,
            )
            mode_str = _trip_mode_for(person)

            school_node = _maybe_school_chain_for(person, home_node, dest_node)
            # If chain fits the budget AND a reachable school exists
            # AND neither leg would self-trip, emit two rows:
            # home → school + school → work.
            if school_node is not None and am_emitted + 2 <= n_am_target:
                # The school drop is a little before workplace arrival (the
                # parent stops on the way). To keep it simple we give both
                # rows the same departure time; engines order by
                # departure_time_s and both vehicles enter at the same
                # instant. A fancier model could split the journey time
                # across the two legs.
                trips.append({
                    "origin_node_id": home_node,
                    "destination_node_id": school_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBSchool_AM",
                })
                trips.append({
                    "origin_node_id": school_node,
                    "destination_node_id": dest_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBW_AM_chained",
                })
                am_emitted += 2
                n_school_chains += 1
            else:
                trips.append({
                    "origin_node_id": home_node,
                    "destination_node_id": dest_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBW_AM",
                })
                am_emitted += 1
    if n_school_chains:
        logger.info(
            "HBSchool: %d AM chains emitted (each = home→school + school→work)",
            n_school_chains,
        )

    # Phase 1b: schedule-driven PM trips (work to home, 17:00 arrival). V5+
    # reads cityscape's `schedule[1]` tuple. Cityscape always emits the PM
    # tuple next to the AM one, same dow_start=1, dow_end=5 weekday range;
    # the destination bld_id in `schedule[1]` is the home building (mirror of
    # the AM origin). We flip the OD direction and recompute the departure
    # from `schedule[1].time_s`.
    #
    # V5+: a parent with a school-age dependent emits a chained
    # work -> school -> home pair (HBW_PM_chained + HBSchool_PM) instead of a
    # plain work -> home trip, the symmetric mirror of the AM chain (pick the
    # kid up on the way home). Each chain uses 2 budget slots.
    n_school_chains_pm = 0
    if n_pm_target > 0 and len(valid_scheduled) > 0:
        # Shuffle independently so the PM person mix isn't just a fixed tail
        # of the AM mix; that keeps the cohort representative at any sample size.
        pm_sched_indices = list(range(len(valid_scheduled)))
        rng.shuffle(pm_sched_indices)
        pm_emitted = 0
        for i in pm_sched_indices:
            if pm_emitted >= n_pm_target:
                break
            person, home_node, work_node = valid_scheduled[i]
            arrival_s = person.schedule[1].time_s   # 17:00 home arrival
            departure_s = _generate_departure_time(
                person.commute_min, horizon_start, horizon_end,
                arrival_time_s=arrival_s,
            )
            mode_str = _trip_mode_for(person)

            school_node = _maybe_school_chain_for(person, home_node, work_node)
            # If the chain fits the budget, a reachable school exists, and
            # neither leg self-trips, emit two rows: work -> school and
            # school -> home.
            if school_node is not None and pm_emitted + 2 <= n_pm_target:
                # Both legs share one departure_time_s, same simplification
                # as the AM chain. Engines order by departure_time_s and both
                # vehicles enter at the same instant.
                trips.append({
                    "origin_node_id": work_node,
                    "destination_node_id": school_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBW_PM_chained",
                })
                trips.append({
                    "origin_node_id": school_node,
                    "destination_node_id": home_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBSchool_PM",
                })
                pm_emitted += 2
                n_school_chains_pm += 1
            else:
                trips.append({
                    # PM direction: work → home (origin/destination flipped vs AM).
                    "origin_node_id": work_node,
                    "destination_node_id": home_node,
                    "departure_time_s": departure_s,
                    "mode": mode_str,
                    "dest_source": "schedule",
                    "purpose": "HBW_PM",
                })
                pm_emitted += 1
    if n_school_chains_pm:
        logger.info(
            "HBSchool: %d PM chains emitted (each = work→school + school→home)",
            n_school_chains_pm,
        )

    # Phase 2: Gravity fallback for the remaining trips. This is the original
    # loop with V5+ peak-aware adaptation: gravity fills both AM and PM
    # budgets to whatever the schedule path didn't cover. Deterministic
    # weighting picks AM vs PM proportional to remaining budget.
    #
    # AM_PURPOSES / PM_PURPOSES are module-level frozensets; the constants
    # block near the top of the file explains why.
    am_emitted_so_far = sum(1 for t in trips if t["purpose"] in AM_PURPOSES)
    pm_emitted_so_far = sum(1 for t in trips if t["purpose"] in PM_PURPOSES)
    am_remaining = max(0, n_am_target - am_emitted_so_far)
    pm_remaining = max(0, n_pm_target - pm_emitted_so_far)
    n_gravity_needed = am_remaining + pm_remaining
    gravity_attempts = 0
    gravity_max_attempts = n_gravity_needed * 20 if n_gravity_needed > 0 else 0

    while (am_remaining + pm_remaining > 0
           and gravity_attempts < gravity_max_attempts):
        gravity_attempts += 1
        # Pick the peak to fill in proportion to the remaining budget, so
        # the gravity AM/PM mix tracks the overall allocation.
        if pm_remaining == 0:
            current_peak = "AM"
        elif am_remaining == 0:
            current_peak = "PM"
        elif rng.random() < am_remaining / (am_remaining + pm_remaining):
            current_peak = "AM"
        else:
            current_peak = "PM"

        # a. Sample origin (population-weighted)
        origin = rng.choices(origin_nodes, weights=origin_weights, k=1)[0]
        origin_coord = network.node_coords[origin]

        # b. Sample a census person from a building at this origin node
        buildings_at_origin = origin_node_buildings.get(origin, [])
        person = None
        if buildings_at_origin:
            bld = rng.choice(buildings_at_origin)
            bld_pool = bld_persons.get(bld.bld_id, [])
            if bld_pool:
                person = rng.choice(bld_pool)
        if person is None:
            person = rng.choice(all_commuters)

        # c. Sample destination (gravity: degree-weighted, distance-decayed)
        target_km = person.commute_min * 0.5  # rough: 30 km/h avg → 0.5 km/min
        target_km = max(0.5, min(target_km, 15.0))

        origin_lon, origin_lat = origin_coord
        origin_lat_rad = math.radians(origin_lat)
        cos_orig = math.cos(origin_lat_rad)
        dlat = _dest_lats_rad - origin_lat_rad
        dlon = np.radians(_dest_lons - origin_lon)
        a = (np.sin(dlat * 0.5) ** 2
             + cos_orig * _dest_cos_lat * np.sin(dlon * 0.5) ** 2)
        distances = _R_KM * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))

        sigma = target_km * 0.7 + 0.5
        scores = _dest_weights_arr * np.exp(
            -0.5 * ((distances - target_km) / sigma) ** 2
        )
        scores = np.where(distances < 0.1, 0.0, scores)
        origin_idx = _node_idx.get(origin)
        if origin_idx is not None:
            scores[origin_idx] = 0.0

        # An empty score array (no eligible destinations in the SCC) would make
        # csum[-1] raise IndexError. Bail out of the gravity loop cleanly: no
        # destination can be sampled, so further attempts are futile.
        if scores.size == 0:
            break

        csum = np.cumsum(scores)
        total = csum[-1]
        if total <= 0.0:
            continue
        r = rng.random() * total
        idx = int(np.searchsorted(csum, r, side="right"))
        if idx >= len(dest_nodes):
            idx = len(dest_nodes) - 1
        destination = dest_nodes[idx]

        if destination == origin:
            continue

        # Pick the AM or PM template (V5+ is peak-aware). A person with a
        # cityscape schedule brings their own arrival time; one without a
        # schedule uses the cityscape constant for whichever peak this
        # iteration is filling.
        if current_peak == "AM":
            arrival_s = (
                person.schedule[0].time_s
                if person.schedule
                else _CITYSCAPE_AM_ARRIVAL_S
            )
            purpose = "HBW_AM"
            trip_origin, trip_dest = origin, destination
            am_remaining -= 1
        else:
            # PM template: reverse the OD direction so the trip is
            # work → home, mirroring the schedule[1] semantics.
            arrival_s = (
                person.schedule[1].time_s
                if len(person.schedule) >= 2
                else _CITYSCAPE_PM_ARRIVAL_S
            )
            purpose = "HBW_PM"
            trip_origin, trip_dest = destination, origin
            pm_remaining -= 1

        trips.append({
            "origin_node_id": trip_origin,
            "destination_node_id": trip_dest,
            "departure_time_s": _generate_departure_time(
                person.commute_min, horizon_start, horizon_end,
                arrival_time_s=arrival_s,
            ),
            "mode": _trip_mode_for(person),
            "dest_source": "gravity",
            "purpose": purpose,
        })

    # Degenerate networks (no routable destinations in the SCC, or a tiny
    # scheduled+gravity pool) can leave the loops short of the request after
    # exhausting attempts. Surface the shortfall loudly here; the caller
    # (generate.py) compares the returned trip_count against the request and
    # decides what to do. We do not raise: returning what we generated keeps
    # the contract intact.
    if len(trips) < num_trips:
        logger.warning(
            "Under-generated census demand: produced %d of %d requested trips. "
            "The network may be degenerate (no routable destinations in the SCC) "
            "or the census pool too small for this bounding box.",
            len(trips), num_trips,
        )

    # Final ordering + dense trip ids. Sort key includes a secondary tiebreak
    # so ties on departure_time_s are deterministic across runs.
    trips.sort(key=lambda t: (t["departure_time_s"], t["origin_node_id"],
                              t["destination_node_id"]))
    for i, trip in enumerate(trips):
        trip["trip_id"] = f"t{i}"

    # 7. Write demand.csv with the dest_source + purpose provenance columns.
    # Adapters consume the canonical 5-column subset (trip_id,
    # origin_node_id, destination_node_id, departure_time_s, mode) by name
    # and ignore the extras.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["trip_id", "origin_node_id", "destination_node_id",
                  "departure_time_s", "mode", "dest_source", "purpose"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trips)

    schedule_driven = sum(1 for t in trips if t["dest_source"] == "schedule")
    gravity_fallback = len(trips) - schedule_driven
    pct_sched = (schedule_driven / len(trips) * 100) if trips else 0.0
    n_am_total = sum(1 for t in trips if t["purpose"] in AM_PURPOSES)
    n_pm_total = sum(1 for t in trips if t["purpose"] in PM_PURPOSES)
    n_chain_legs = sum(
        1 for t in trips
        if t["purpose"] in {"HBSchool_AM", "HBW_AM_chained",
                            "HBSchool_PM", "HBW_PM_chained"}
    )
    logger.info(
        "Wrote %d census-calibrated trips to %s "
        "(schedule-driven=%d / %.1f%%, gravity-fallback=%d; "
        "AM peak=%d, PM peak=%d; school-chain legs=%d)",
        len(trips), output_path, schedule_driven, pct_sched, gravity_fallback,
        n_am_total, n_pm_total, n_chain_legs,
    )

    # Compute statistics
    unique_origins = len(set(t["origin_node_id"] for t in trips))
    unique_dests = len(set(t["destination_node_id"] for t in trips))

    return {
        "trip_count": len(trips),
        "unique_origins": unique_origins,
        "unique_destinations": unique_dests,
        "strategy": "census_schedule_first",
        "seed": seed,
        "output_path": str(output_path),
        "census_commuters": len(all_commuters),
        "avg_commute_min": round(avg_commute, 1),
        "mapped_buildings": len(bld_to_node),
        "origin_nodes": len(origin_nodes),
        "provenance": {
            "schedule_driven_count": schedule_driven,
            "gravity_fallback_count": gravity_fallback,
            "schedule_driven_pct": round(pct_sched, 2),
            "scheduled_pool_size": len(valid_scheduled),
            "fallback_reasons": dict(fallback_reasons),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate census-calibrated demand from model file + network."
    )
    parser.add_argument("--model", "-m", type=str, required=True,
                        help="Path to model file (e.g. la_model.txt)")
    parser.add_argument("--network", "-n", type=str, required=True,
                        help="Path to canonical network.xml")
    parser.add_argument("--output", "-o", type=str, required=True,
                        help="Output path for demand.csv")
    parser.add_argument("--trips", "-t", type=int, default=5000,
                        help="Number of trips (default: 5000)")
    parser.add_argument("--bbox", type=str, default=None,
                        help="Bounding box as 'south,north,west,east'")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    from pipeline.demand.parse_model_file import parse_model_file

    bbox = None
    if args.bbox:
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        bbox = (parts[0], parts[1], parts[2], parts[3])

    data = parse_model_file(Path(args.model), bbox=bbox)

    result = generate_census_demand(
        model_data=data,
        network_path=Path(args.network),
        output_path=Path(args.output),
        num_trips=args.trips,
        seed=args.seed,
    )

    print("\nCensus-calibrated demand generated:")
    print(f"  Trips:            {result['trip_count']}")
    print(f"  Unique origins:   {result['unique_origins']}")
    print(f"  Unique dests:     {result['unique_destinations']}")
    print(f"  Census commuters: {result['census_commuters']}")
    print(f"  Avg commute:      {result['avg_commute_min']} min")
    print(f"  Mapped buildings: {result['mapped_buildings']}")
    print(f"  Output:           {result['output_path']}")


if __name__ == "__main__":
    main()
