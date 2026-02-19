"""
Generate census-calibrated demand from modelgen data + canonical network.

This module replaces the synthetic gravity model with demand grounded in
U.S. Census PUMS microdata.  It reads a parsed ModelData object (buildings,
households, persons) and the canonical network.xml to produce demand.csv
with:
  - Origins  weighted by residential building population
  - Destinations  selected via gravity model over the canonical network
  - Departure times  drawn from a realistic morning-peak profile
                     calibrated by PUMS JWMNP (commute-time) data
  - Mode  set from PUMS JWTRNS (only car trips for v0)

Usage (library):
    from pipeline.demand.parse_model_file import parse_model_file
    from pipeline.demand.generate_census_demand import generate_census_demand

    data = parse_model_file(model_path, bbox=(...))
    result = generate_census_demand(
        model_data=data,
        network_path=Path("scenarios/la_5k/network.xml"),
        output_path=Path("scenarios/la_5k/demand.csv"),
        num_trips=5000,
        seed=42,
    )
"""

import csv
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

from lxml import etree

from pipeline.demand.parse_model_file import ModelData, Building

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Network loading (lightweight — only nodes + adjacency)
# ---------------------------------------------------------------------------

@dataclass
class NetworkInfo:
    """Minimal network representation for demand generation."""
    node_ids: list[str]
    node_coords: dict[str, tuple[float, float]]  # id → (lon, lat)
    node_degrees: dict[str, int]
    adjacency: dict[str, list[str]]


def _load_network_nodes(network_path: Path) -> NetworkInfo:
    """Load node coordinates and adjacency from canonical network.xml."""
    tree = etree.parse(str(network_path))
    root = tree.getroot()

    node_ids = []
    node_coords = {}
    node_degrees: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)

    for node in root.findall(".//node"):
        nid = node.get("id")
        x = float(node.get("x", 0))
        y = float(node.get("y", 0))
        node_ids.append(nid)
        node_coords[nid] = (x, y)  # x=lon, y=lat

    for link in root.findall(".//link"):
        from_node = link.get("from")
        to_node = link.get("to")
        if from_node and to_node and from_node != to_node:
            adjacency[from_node].append(to_node)
            node_degrees[from_node] += 1
            node_degrees[to_node] += 1

    return NetworkInfo(
        node_ids=sorted(node_ids),
        node_coords=node_coords,
        node_degrees=dict(node_degrees),
        adjacency=dict(adjacency),
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
    Map each building to the nearest canonical network node.

    Uses the building's way_lat/way_lon (the snap point on the nearest
    road in the model file) for better accuracy than raw building centroid.

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

def _generate_departure_time(
    rng: random.Random,
    commute_min: int,
    horizon_start: int,
    horizon_end: int,
) -> int:
    """
    Generate a departure time based on commute duration.

    Uses a morning-peak profile centered at ~8:00 AM (28800 s from midnight)
    but mapped into the scenario's [horizon_start, horizon_end] window.
    Persons with longer commutes depart earlier in the peak.

    Since our scenarios use a 0–3600 s window (1 hour), we compress the
    peak into that range with a normal distribution centered at the midpoint.
    """
    mid = (horizon_start + horizon_end) / 2.0
    spread = (horizon_end - horizon_start) / 6.0  # ±3σ covers the window

    # Longer commutes → earlier departure (slight shift left)
    offset = -min(commute_min, 60) * (spread / 120.0)

    t = rng.gauss(mid + offset, spread)
    # Clamp to horizon
    t = max(horizon_start, min(horizon_end - 1, t))
    return int(t)


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
    max_snap_distance_km: float = 0.5,
    allow_oversample: bool = False,
) -> dict:
    """
    Generate census-calibrated demand.csv from model data and network.

    Pipeline:
      1. Load canonical network nodes.
      2. Map residential buildings to nearest network nodes.
      3. Build origin weights proportional to building population.
      4. For each trip:
         a. Sample an origin node (population-weighted).
         b. Sample a census person from that building (for commute profile).
         c. Sample a destination node (degree-weighted gravity, distance-decayed).
         d. Generate departure time from JWMNP-calibrated peak profile.
      5. Write demand.csv.

    Args:
        model_data: Parsed ModelData from parse_model_file().
        network_path: Path to canonical network.xml.
        output_path: Path to write demand.csv.
        num_trips: Number of trips to generate.
        seed: Random seed for reproducibility.
        horizon_start: Simulation start time (seconds).
        horizon_end: Simulation end time (seconds).
        mode: Travel mode (default "car").
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

    # 3. Build origin weights — residential buildings only
    #    Weight = building population (from model file)
    origin_node_pop: dict[str, int] = defaultdict(int)
    origin_node_buildings: dict[str, list[Building]] = defaultdict(list)

    for bld in model_data.buildings:
        if bld.bld_id not in bld_to_node:
            continue
        if bld.population <= 0:
            continue
        node_id = bld_to_node[bld.bld_id]
        origin_node_pop[node_id] += bld.population
        origin_node_buildings[node_id].append(bld)

    if not origin_node_pop:
        n_bld = len(model_data.buildings)
        n_per = len(model_data.persons)
        raise ValueError(
            f"No residential buildings mapped to network nodes.\n"
            f"  Model file contained {n_bld:,} buildings and {n_per:,} persons "
            f"within the bounding box.\n"
            f"  If both are 0, the model file likely covers a different city "
            f"than this scenario's bounding box.\n"
            f"  Check that the model file matches the target city."
        )

    origin_nodes = list(origin_node_pop.keys())
    origin_weights = [origin_node_pop[n] for n in origin_nodes]

    logger.info("Origin nodes: %d (total pop weight: %d)",
                len(origin_nodes), sum(origin_weights))

    # 4. Build destination weights — degree-based (all nodes eligible)
    #    Nodes with higher connectivity attract more trips
    dest_nodes = [n for n in network.node_ids
                  if network.node_degrees.get(n, 0) > 0]
    dest_weights = [network.node_degrees.get(n, 1) + 1 for n in dest_nodes]

    # Pre-compute coordinate lookup for distance calculations
    dest_coords = {n: network.node_coords[n] for n in dest_nodes}

    # 5. Build a person pool — census persons for commute-time sampling
    #    Grouped by building for origin-correlated sampling
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
        all_commuters = [_FakePerson()]  # type: ignore

    avg_commute = sum(p.commute_min for p in all_commuters) / len(all_commuters)
    logger.info("Census commuters: %d (avg %.0f min)", len(all_commuters), avg_commute)

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

    # 6. Generate trips
    trips: list[dict] = []
    attempts = 0
    max_attempts = num_trips * 20

    while len(trips) < num_trips and attempts < max_attempts:
        attempts += 1

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
        #    Use commute_min to set a target distance range
        target_km = person.commute_min * 0.5  # rough: 30 km/h avg → 0.5 km/min
        target_km = max(0.5, min(target_km, 15.0))

        # Score each candidate destination
        candidate_scores = []
        for i, dn in enumerate(dest_nodes):
            if dn == origin:
                continue
            dist = _haversine_km(origin_coord, dest_coords[dn])
            if dist < 0.1:  # skip very close nodes
                continue
            # Gaussian fit around target distance
            dist_score = math.exp(-0.5 * ((dist - target_km) / (target_km * 0.7 + 0.5)) ** 2)
            score = dest_weights[i] * dist_score
            candidate_scores.append((dn, score))

        if not candidate_scores:
            continue

        dest_names, dest_scores = zip(*candidate_scores)
        destination = rng.choices(dest_names, weights=dest_scores, k=1)[0]

        if destination == origin:
            continue

        # d. Generate departure time
        departure = _generate_departure_time(
            rng, person.commute_min, horizon_start, horizon_end
        )

        trips.append({
            "trip_id": f"t{len(trips)}",
            "origin_node_id": origin,
            "destination_node_id": destination,
            "departure_time_s": departure,
            "mode": mode,
        })

    # Sort by departure time and renumber
    trips.sort(key=lambda t: t["departure_time_s"])
    for i, trip in enumerate(trips):
        trip["trip_id"] = f"t{i}"

    # 7. Write demand.csv
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["trip_id", "origin_node_id", "destination_node_id",
                  "departure_time_s", "mode"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trips)

    logger.info("Wrote %d census-calibrated trips to %s", len(trips), output_path)

    # Compute statistics
    unique_origins = len(set(t["origin_node_id"] for t in trips))
    unique_dests = len(set(t["destination_node_id"] for t in trips))
    deps = [t["departure_time_s"] for t in trips]

    return {
        "trip_count": len(trips),
        "unique_origins": unique_origins,
        "unique_destinations": unique_dests,
        "strategy": "census",
        "seed": seed,
        "output_path": str(output_path),
        "census_commuters": len(all_commuters),
        "avg_commute_min": round(avg_commute, 1),
        "mapped_buildings": len(bld_to_node),
        "origin_nodes": len(origin_nodes),
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

    print(f"\nCensus-calibrated demand generated:")
    print(f"  Trips:            {result['trip_count']}")
    print(f"  Unique origins:   {result['unique_origins']}")
    print(f"  Unique dests:     {result['unique_destinations']}")
    print(f"  Census commuters: {result['census_commuters']}")
    print(f"  Avg commute:      {result['avg_commute_min']} min")
    print(f"  Mapped buildings: {result['mapped_buildings']}")
    print(f"  Output:           {result['output_path']}")


if __name__ == "__main__":
    main()
