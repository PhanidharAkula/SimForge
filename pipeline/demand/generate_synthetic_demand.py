"""
Generate synthetic demand (trips) from a canonical network.

Supports multiple demand generation strategies:
1. Uniform random: Random OD pairs with uniform departure times
2. Gravity model: Trip probability proportional to node centrality
3. Peak-hour: Concentrated departures during morning/evening peaks

Usage:
    python -m pipeline.demand.generate_synthetic_demand \
        --network scenarios/city1/network.xml \
        --output scenarios/city1/demand.csv \
        --trips 50000 \
        --strategy gravity \
        --seed 42
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NetworkStats:
    """Statistics about the network for demand generation."""
    node_ids: list[str]
    node_coords: dict[str, tuple[float, float]]  # id -> (x, y)
    node_degrees: dict[str, int]  # id -> degree (in + out)
    adjacency: dict[str, list[str]]  # id -> list of neighbor ids
    reverse_adjacency: dict[str, list[str]]  # id -> list of nodes that can reach this node
    total_nodes: int
    total_links: int
    reachable_from: dict[str, set[str]]  # id -> set of nodes reachable from this node
    strongly_connected_nodes: set[str]  # nodes in the main strongly connected component


def compute_strongly_connected_component(adjacency: dict[str, list[str]], 
                                         reverse_adjacency: dict[str, list[str]],
                                         node_ids: list[str]) -> set[str]:
    """
    Find the largest strongly connected component of the network.
    Returns the set of nodes in that component.
    """
    from collections import deque
    
    if not node_ids:
        return set()
    
    def bfs_reachable(start: str, adj: dict) -> set[str]:
        visited = set()
        queue = deque([start])
        visited.add(start)
        while queue:
            node = queue.popleft()
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited
    
    # Find a good starting node (highest degree)
    degrees = {n: len(adjacency.get(n, [])) + len(reverse_adjacency.get(n, [])) 
               for n in node_ids}
    start_node = max(degrees, key=degrees.get) if degrees else node_ids[0]
    
    # Forward and backward reachability
    forward = bfs_reachable(start_node, adjacency)
    backward = bfs_reachable(start_node, reverse_adjacency)
    
    # Strongly connected = intersection
    scc = forward & backward
    return scc


def compute_reachability(adjacency: dict[str, list[str]], node_ids: list[str]) -> dict[str, set[str]]:
    """
    Compute which nodes are reachable from each node using BFS.
    This ensures we only generate routable OD pairs.
    """
    from collections import deque
    
    reachable = {}
    for start in node_ids:
        visited = set()
        queue = deque([start])
        visited.add(start)
        while queue:
            node = queue.popleft()
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        reachable[start] = visited - {start}  # Exclude self
    return reachable


def load_network_for_demand(network_path: Path) -> NetworkStats:
    """
    Load network.xml and extract statistics needed for demand generation.
    
    Args:
        network_path: Path to canonical network.xml
    
    Returns:
        NetworkStats with node IDs, coordinates, degrees, and adjacency
    """
    tree = etree.parse(str(network_path))
    root = tree.getroot()
    
    node_ids = []
    node_coords = {}
    adjacency = defaultdict(list)
    node_degrees = defaultdict(int)
    
    # Parse nodes
    for node in root.findall(".//node"):
        nid = node.get("id")
        x = float(node.get("x", 0))
        y = float(node.get("y", 0))
        node_ids.append(nid)
        node_coords[nid] = (x, y)
    
    # Parse links to build adjacency and degrees
    # Skip self-loops (from == to) as they cause issues in routing
    link_count = 0
    reverse_adjacency = defaultdict(list)
    for link in root.findall(".//link"):
        from_node = link.get("from")
        to_node = link.get("to")
        if from_node and to_node and from_node != to_node:  # Skip self-loops
            adjacency[from_node].append(to_node)
            reverse_adjacency[to_node].append(from_node)
            node_degrees[from_node] += 1
            node_degrees[to_node] += 1
            link_count += 1
    
    # Ensure all nodes have degree entry
    for nid in node_ids:
        if nid not in node_degrees:
            node_degrees[nid] = 0
    
    # Compute strongly connected component
    logger.info("Computing strongly connected component...")
    scc = compute_strongly_connected_component(
        dict(adjacency), dict(reverse_adjacency), node_ids
    )
    logger.info(f"Strongly connected component: {len(scc)} of {len(node_ids)} nodes")
    
    # Compute reachability only within the SCC for routable OD pairs
    logger.info("Computing node reachability for routable OD pairs...")
    scc_list = list(scc)
    # Filter adjacency to only include SCC nodes
    scc_adjacency = {n: [dest for dest in adjacency.get(n, []) if dest in scc] 
                     for n in scc}
    reachable_from = compute_reachability(scc_adjacency, scc_list)
    logger.info(f"Reachability computed for {len(scc_list)} strongly connected nodes")
    
    return NetworkStats(
        node_ids=sorted(node_ids),
        node_coords=node_coords,
        node_degrees=dict(node_degrees),
        adjacency=dict(adjacency),
        reverse_adjacency=dict(reverse_adjacency),
        total_nodes=len(node_ids),
        total_links=link_count,
        reachable_from=reachable_from,
        strongly_connected_nodes=scc
    )


def euclidean_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calculate Euclidean distance between two coordinates."""
    return math.sqrt((coord1[0] - coord2[0])**2 + (coord1[1] - coord2[1])**2)


def haversine_distance_km(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """
    Calculate Haversine distance in km between two (lon, lat) coordinates.
    Assumes coord is (x=lon, y=lat).
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    R = 6371  # Earth radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


class DemandGenerator:
    """Base class for demand generation strategies."""
    
    def __init__(self, network: NetworkStats, seed: int = 42):
        self.network = network
        self.rng = random.Random(seed)
    
    def generate_od_pair(self) -> tuple[str, str]:
        """Generate a single origin-destination pair. Override in subclasses."""
        raise NotImplementedError
    
    def generate_departure_time(self, horizon_start: int, horizon_end: int) -> float:
        """Generate a departure time in seconds. Override in subclasses."""
        return self.rng.uniform(horizon_start, horizon_end)
    
    def generate_trips(
        self,
        num_trips: int,
        horizon_start: int = 0,
        horizon_end: int = 3600,
        mode: str = "car"
    ) -> list[dict]:
        """
        Generate multiple trips.
        
        Args:
            num_trips: Number of trips to generate
            horizon_start: Start time in seconds
            horizon_end: End time in seconds
            mode: Travel mode (car, walk, bike, etc.)
        
        Returns:
            List of trip dictionaries
        """
        trips = []
        attempts = 0
        max_attempts = num_trips * 10  # Avoid infinite loops
        
        while len(trips) < num_trips and attempts < max_attempts:
            attempts += 1
            
            origin, destination = self.generate_od_pair()
            
            # Skip if same node
            if origin == destination:
                continue
            
            departure = self.generate_departure_time(horizon_start, horizon_end)
            
            trips.append({
                "trip_id": f"t{len(trips)}",
                "origin_node_id": origin,
                "destination_node_id": destination,
                "departure_time_s": int(departure),  # Schema requires integer
                "mode": mode
            })
        
        # Sort by departure time
        trips.sort(key=lambda t: t["departure_time_s"])
        
        # Renumber trip IDs after sorting
        for i, trip in enumerate(trips):
            trip["trip_id"] = f"t{i}"
        
        logger.info(f"Generated {len(trips)} trips in {attempts} attempts")
        return trips


class UniformRandomGenerator(DemandGenerator):
    """Generate trips with uniform random OD pairs and departure times."""
    
    def generate_od_pair(self) -> tuple[str, str]:
        """Pick random origin and destination from strongly connected component."""
        # Use only nodes in the strongly connected component
        scc_nodes = list(self.network.strongly_connected_nodes)
        if not scc_nodes:
            # Fallback if SCC not computed
            origin = self.rng.choice(self.network.node_ids)
            destination = self.rng.choice(self.network.node_ids)
            return origin, destination
        
        origin = self.rng.choice(scc_nodes)
        # Pick destination from reachable nodes (within SCC)
        reachable = list(self.network.reachable_from.get(origin, set()))
        if reachable:
            destination = self.rng.choice(reachable)
        else:
            # Fallback to any SCC node
            destination = self.rng.choice(scc_nodes)
        return origin, destination


class GravityModelGenerator(DemandGenerator):
    """
    Generate trips using a gravity model.
    
    Trip probability is proportional to:
    - Origin node degree (higher connectivity = more trips originate)
    - Destination node degree (higher connectivity = more trips terminate)
    - Inverse distance (closer nodes more likely for short trips)
    """
    
    def __init__(
        self,
        network: NetworkStats,
        seed: int = 42,
        distance_decay: float = 1.0,
        min_distance_km: float = 0.5,
        max_distance_km: float = 10.0
    ):
        super().__init__(network, seed)
        self.distance_decay = distance_decay
        self.min_distance_km = min_distance_km
        self.max_distance_km = max_distance_km
        
        # Use only nodes in strongly connected component
        scc_nodes = list(network.strongly_connected_nodes)
        
        # Precompute node weights based on degree (only for SCC nodes)
        total_degree = sum(network.node_degrees.get(n, 0) for n in scc_nodes) or 1
        self.node_weights = {
            nid: (network.node_degrees.get(nid, 1) + 1) / total_degree
            for nid in scc_nodes
        }
        
        # Build weighted choice list (only SCC nodes)
        self.weighted_nodes = list(self.node_weights.keys())
        self.weights = [self.node_weights[n] for n in self.weighted_nodes]
    
    def generate_od_pair(self) -> tuple[str, str]:
        """Generate OD pair using gravity model, ensuring routability."""
        if not self.weighted_nodes:
            # Fallback if no SCC
            origin = self.rng.choice(self.network.node_ids)
            destination = self.rng.choice(self.network.node_ids)
            return origin, destination
        
        # Select origin weighted by degree (from SCC)
        origin = self.rng.choices(self.weighted_nodes, weights=self.weights, k=1)[0]
        
        # Get reachable destinations from this origin (all in SCC)
        reachable = self.network.reachable_from.get(origin, set())
        if not reachable:
            # Fallback to random SCC node
            return origin, self.rng.choice(self.weighted_nodes)
        
        # Select destination weighted by degree and distance, but only from reachable nodes
        origin_coord = self.network.node_coords[origin]
        
        # Compute destination weights only for reachable nodes
        reachable_list = list(reachable)
        dest_weights = []
        for dest in reachable_list:
            dest_coord = self.network.node_coords[dest]
            dist_km = haversine_distance_km(origin_coord, dest_coord)
            
            # Apply distance constraints
            if dist_km < self.min_distance_km or dist_km > self.max_distance_km:
                dest_weights.append(0.01)  # Small weight instead of 0 to allow some selection
                continue
            
            # Gravity weight: degree / distance^decay
            degree_weight = self.node_weights.get(dest, 0.01)
            distance_weight = 1 / (dist_km ** self.distance_decay + 0.1)
            dest_weights.append(degree_weight * distance_weight)
        
        # Normalize and select
        total_weight = sum(dest_weights)
        if total_weight == 0:
            # Fallback to random reachable
            destination = self.rng.choice(reachable_list)
        else:
            destination = self.rng.choices(reachable_list, weights=dest_weights, k=1)[0]
        
        return origin, destination


class PeakHourGenerator(DemandGenerator):
    """
    Generate trips with peak-hour departure patterns.
    
    Default: Morning peak 7-9am, evening peak 5-7pm.
    """
    
    def __init__(
        self,
        network: NetworkStats,
        seed: int = 42,
        morning_peak: tuple[int, int] = (7 * 3600, 9 * 3600),
        evening_peak: tuple[int, int] = (17 * 3600, 19 * 3600),
        peak_fraction: float = 0.7  # Fraction of trips during peaks
    ):
        super().__init__(network, seed)
        self.morning_peak = morning_peak
        self.evening_peak = evening_peak
        self.peak_fraction = peak_fraction
    
    def generate_od_pair(self) -> tuple[str, str]:
        """Pick random routable OD pair from strongly connected component."""
        # Use only nodes in the strongly connected component
        scc_nodes = list(self.network.strongly_connected_nodes)
        if not scc_nodes:
            origin = self.rng.choice(self.network.node_ids)
            destination = self.rng.choice(self.network.node_ids)
            return origin, destination
        
        origin = self.rng.choice(scc_nodes)
        reachable = list(self.network.reachable_from.get(origin, set()))
        if reachable:
            destination = self.rng.choice(reachable)
        else:
            destination = self.rng.choice(scc_nodes)
        return origin, destination
    
    def generate_departure_time(self, horizon_start: int, horizon_end: int) -> float:
        """Generate departure time with peak-hour concentration."""
        if self.rng.random() < self.peak_fraction:
            # Peak hour
            if self.rng.random() < 0.5:
                # Morning peak
                start, end = self.morning_peak
            else:
                # Evening peak
                start, end = self.evening_peak
            
            # Ensure within horizon
            start = max(start, horizon_start)
            end = min(end, horizon_end)
            
            if start < end:
                return self.rng.uniform(start, end)
        
        # Off-peak: uniform across horizon
        return self.rng.uniform(horizon_start, horizon_end)


def write_demand_csv(trips: list[dict], output_path: Path) -> None:
    """Write trips to canonical demand.csv format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    fieldnames = ["trip_id", "origin_node_id", "destination_node_id", "departure_time_s", "mode"]
    
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trips)
    
    logger.info(f"Wrote {len(trips)} trips to {output_path}")


def generate_synthetic_demand(
    network_path: Path,
    output_path: Path,
    num_trips: int,
    strategy: str = "gravity",
    seed: int = 42,
    horizon_start: int = 0,
    horizon_end: int = 3600,
    mode: str = "car",
    **kwargs
) -> dict:
    """
    Main entry point for demand generation.
    
    Args:
        network_path: Path to canonical network.xml
        output_path: Path to write demand.csv
        num_trips: Number of trips to generate
        strategy: Generation strategy ('uniform', 'gravity', 'peak_hour')
        seed: Random seed for reproducibility
        horizon_start: Simulation start time (seconds)
        horizon_end: Simulation end time (seconds)
        mode: Travel mode
        **kwargs: Additional strategy-specific parameters
    
    Returns:
        Summary dict with trip statistics
    """
    # Load network
    network = load_network_for_demand(network_path)
    logger.info(f"Loaded network: {network.total_nodes} nodes, {network.total_links} links")
    
    # Select generator
    if strategy == "uniform":
        generator = UniformRandomGenerator(network, seed)
    elif strategy == "gravity":
        generator = GravityModelGenerator(
            network, seed,
            distance_decay=kwargs.get("distance_decay", 1.0),
            min_distance_km=kwargs.get("min_distance_km", 0.5),
            max_distance_km=kwargs.get("max_distance_km", 10.0)
        )
    elif strategy == "peak_hour":
        generator = PeakHourGenerator(network, seed)
    else:
        raise ValueError(f"Unknown strategy: {strategy}. Use 'uniform', 'gravity', or 'peak_hour'")
    
    # Generate trips
    trips = generator.generate_trips(num_trips, horizon_start, horizon_end, mode)
    
    # Write output
    write_demand_csv(trips, output_path)
    
    # Compute statistics
    unique_origins = len(set(t["origin_node_id"] for t in trips))
    unique_destinations = len(set(t["destination_node_id"] for t in trips))
    
    return {
        "trip_count": len(trips),
        "unique_origins": unique_origins,
        "unique_destinations": unique_destinations,
        "strategy": strategy,
        "seed": seed,
        "output_path": str(output_path)
    }


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate synthetic demand from canonical network"
    )
    parser.add_argument(
        "--network", "-n", type=str, required=True,
        help="Path to canonical network.xml"
    )
    parser.add_argument(
        "--output", "-o", type=str, required=True,
        help="Output path for demand.csv"
    )
    parser.add_argument(
        "--trips", "-t", type=int, default=50000,
        help="Number of trips to generate (default: 50000)"
    )
    parser.add_argument(
        "--strategy", "-s", type=str, default="gravity",
        choices=["uniform", "gravity", "peak_hour"],
        help="Demand generation strategy (default: gravity)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--horizon-start", type=int, default=0,
        help="Simulation start time in seconds (default: 0)"
    )
    parser.add_argument(
        "--horizon-end", type=int, default=3600,
        help="Simulation end time in seconds (default: 3600 = 1 hour)"
    )
    parser.add_argument(
        "--mode", type=str, default="car",
        help="Travel mode (default: car)"
    )
    
    args = parser.parse_args()
    
    result = generate_synthetic_demand(
        network_path=Path(args.network),
        output_path=Path(args.output),
        num_trips=args.trips,
        strategy=args.strategy,
        seed=args.seed,
        horizon_start=args.horizon_start,
        horizon_end=args.horizon_end,
        mode=args.mode
    )
    
    print(f"\nDemand generated successfully:")
    print(f"  Trips: {result['trip_count']}")
    print(f"  Unique origins: {result['unique_origins']}")
    print(f"  Unique destinations: {result['unique_destinations']}")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Output: {result['output_path']}")


if __name__ == "__main__":
    main()
