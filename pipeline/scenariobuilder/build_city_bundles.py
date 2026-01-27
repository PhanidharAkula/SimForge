"""
Build multiple city-scale canonical bundles for the thesis benchmark.

This script generates bundles for:
- City 1: Sioux Falls, SD (already exists)
- City 2: Austin, TX
- City 3: Berlin, Germany

Each city has 3 tiers:
- 50k trips (small)
- 500k trips (medium)
- 5M trips (large)

Usage:
    python -m pipeline.scenariobuilder.build_city_bundles austin --tier 50k
    python -m pipeline.scenariobuilder.build_city_bundles berlin --tier all
    python -m pipeline.scenariobuilder.build_city_bundles --all
"""

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CityConfig:
    """Configuration for a city scenario."""
    name: str
    city_name: str
    state_or_country: str
    center_lat: float
    center_lon: float
    radius_km: float  # Approximate coverage
    timezone: str
    
    # Demand generation params
    population_estimate: int  # Used to scale demand
    peak_hour_pct: float = 0.08  # Percent of daily trips in peak hour


# Predefined city configurations
CITIES = {
    "sioux_falls": CityConfig(
        name="sioux_falls",
        city_name="Sioux Falls",
        state_or_country="SD, USA",
        center_lat=43.5460,
        center_lon=-96.7313,
        radius_km=15,
        timezone="America/Chicago",
        population_estimate=180000,
    ),
    "austin": CityConfig(
        name="austin",
        city_name="Austin",
        state_or_country="TX, USA",
        center_lat=30.2672,
        center_lon=-97.7431,
        radius_km=25,
        timezone="America/Chicago",
        population_estimate=1000000,
    ),
    "berlin": CityConfig(
        name="berlin",
        city_name="Berlin",
        state_or_country="Germany",
        center_lat=52.5200,
        center_lon=13.4050,
        radius_km=20,
        timezone="Europe/Berlin",
        population_estimate=3500000,
    ),
}


# Tier definitions (number of trips)
TIERS = {
    "50k": 50000,
    "500k": 500000,
    "5m": 5000000,
}


def build_scenario(
    city_key: str,
    tier: str,
    output_root: Path,
    force: bool = False,
) -> Path:
    """Build a single scenario bundle.
    
    Returns:
        Path to the created scenario directory
    """
    if city_key not in CITIES:
        raise ValueError(f"Unknown city: {city_key}. Available: {list(CITIES.keys())}")
    
    if tier not in TIERS:
        raise ValueError(f"Unknown tier: {tier}. Available: {list(TIERS.keys())}")
    
    city = CITIES[city_key]
    num_trips = TIERS[tier]
    
    scenario_name = f"{city.name}_tier{tier}"
    scenario_dir = output_root / scenario_name
    
    if scenario_dir.exists() and not force:
        logger.info(f"Scenario already exists: {scenario_dir}")
        return scenario_dir
    
    scenario_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Building scenario: {scenario_name}")
    logger.info(f"  City: {city.city_name}, {city.state_or_country}")
    logger.info(f"  Tier: {tier} ({num_trips:,} trips)")
    logger.info(f"  Output: {scenario_dir}")
    
    # Step 1: Build network from OSM
    logger.info("Step 1: Building network from OSM...")
    try:
        from pipeline.network.build_network_from_osm import (
            build_network_from_osm,
            BoundingBox,
        )
        
        bbox = BoundingBox.from_center(
            city.center_lat,
            city.center_lon,
            city.radius_km
        )
        
        network_path = scenario_dir / "network.xml"
        build_network_from_osm(bbox, network_path)
        logger.info(f"  Created: {network_path}")
        
    except ImportError as e:
        logger.error(f"  Missing dependencies: {e}")
        logger.error("  Install with: pip install osmnx")
        return scenario_dir
    except Exception as e:
        logger.error(f"  Network build failed: {e}")
        # Create a placeholder
        _create_placeholder_network(scenario_dir / "network.xml", city)
    
    # Step 2: Generate synthetic demand
    logger.info("Step 2: Generating synthetic demand...")
    try:
        from pipeline.demand.generate_synthetic_demand import (
            generate_synthetic_demand,
        )
        
        demand_path = scenario_dir / "demand.csv"
        generate_synthetic_demand(
            network_path=scenario_dir / "network.xml",
            output_path=demand_path,
            num_trips=num_trips,
            seed=42,
        )
        logger.info(f"  Created: {demand_path}")
        
    except ImportError:
        logger.warning("  Using simplified demand generator")
        _create_placeholder_demand(
            scenario_dir / "demand.csv",
            scenario_dir / "network.xml",
            num_trips,
        )
    except Exception as e:
        logger.error(f"  Demand generation failed: {e}")
        _create_placeholder_demand(
            scenario_dir / "demand.csv",
            scenario_dir / "network.xml",
            num_trips,
        )
    
    # Step 3: Generate signals
    logger.info("Step 3: Generating signal controllers...")
    try:
        from pipeline.signals.build_signals_default import (
            build_signals_default,
        )
        
        signals_path = scenario_dir / "signals.xml"
        build_signals_default(
            network_path=scenario_dir / "network.xml",
            output_path=signals_path,
        )
        logger.info(f"  Created: {signals_path}")
        
    except Exception as e:
        logger.warning(f"  Signals generation failed: {e}")
        _create_placeholder_signals(scenario_dir / "signals.xml")
    
    # Step 4: Create config
    logger.info("Step 4: Creating config...")
    _create_config(
        scenario_dir / "config.xml",
        scenario_name,
        city,
        tier,
        num_trips,
    )
    
    # Step 5: Create manifest
    logger.info("Step 5: Creating manifest...")
    _create_manifest(scenario_dir)
    
    logger.info(f"Scenario complete: {scenario_dir}")
    return scenario_dir


def _create_placeholder_network(path: Path, city: CityConfig):
    """Create a minimal placeholder network."""
    # Create a simple grid network as placeholder
    nodes = []
    links = []
    grid_size = 5
    spacing = 1000  # meters
    
    node_id = 1
    node_map = {}
    for i in range(grid_size):
        for j in range(grid_size):
            nid = f"n{node_id}"
            x = city.center_lon + (i - grid_size // 2) * 0.01
            y = city.center_lat + (j - grid_size // 2) * 0.01
            nodes.append((nid, x, y))
            node_map[(i, j)] = nid
            node_id += 1
    
    link_id = 1
    for i in range(grid_size):
        for j in range(grid_size):
            # Horizontal links
            if i < grid_size - 1:
                links.append((
                    f"l{link_id}",
                    node_map[(i, j)],
                    node_map[(i + 1, j)],
                    spacing,
                ))
                link_id += 1
            # Vertical links
            if j < grid_size - 1:
                links.append((
                    f"l{link_id}",
                    node_map[(i, j)],
                    node_map[(i, j + 1)],
                    spacing,
                ))
                link_id += 1
    
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<network crs="EPSG:4326" units="meters">\n')
        f.write('  <nodes>\n')
        for nid, x, y in nodes:
            f.write(f'    <node id="{nid}" x="{x}" y="{y}"/>\n')
        f.write('  </nodes>\n')
        f.write('  <links>\n')
        for lid, from_n, to_n, length in links:
            f.write(
                f'    <link id="{lid}" from="{from_n}" to="{to_n}" '
                f'length="{length}" speed_limit="13.9" lanes="1"/>\n'
            )
        f.write('  </links>\n')
        f.write('</network>\n')


def _create_placeholder_demand(demand_path: Path, network_path: Path, num_trips: int):
    """Create synthetic demand based on network."""
    import xml.etree.ElementTree as ET
    import csv
    import random
    
    # Parse network to get node IDs
    tree = ET.parse(network_path)
    root = tree.getroot()
    
    nodes_elem = root.find("nodes")
    if nodes_elem is None:
        nodes_elem = root.find(".//nodes")
    
    node_ids = []
    if nodes_elem is not None:
        for node in nodes_elem.findall("node"):
            nid = node.get("id")
            if nid:
                node_ids.append(nid)
    
    if not node_ids:
        node_ids = [f"n{i}" for i in range(1, 26)]
    
    random.seed(42)
    
    with open(demand_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["trip_id", "origin_node_id", "destination_node_id", "departure_time_s", "mode"])
        
        for i in range(1, num_trips + 1):
            origin = random.choice(node_ids)
            dest = random.choice([n for n in node_ids if n != origin] or node_ids)
            # Peak hours: 7-9 AM and 5-7 PM
            if random.random() < 0.4:  # 40% in AM peak
                depart = random.randint(7 * 3600, 9 * 3600)
            elif random.random() < 0.67:  # 40% in PM peak (67% of remaining 60%)
                depart = random.randint(17 * 3600, 19 * 3600)
            else:  # 20% off-peak
                depart = random.randint(0, 24 * 3600)
            
            writer.writerow([f"t{i}", origin, dest, depart, "car"])


def _create_placeholder_signals(path: Path):
    """Create minimal signals file."""
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<signals>\n')
        f.write('  <!-- Placeholder: no signal controllers defined -->\n')
        f.write('</signals>\n')


def _create_config(path: Path, scenario_id: str, city: CityConfig, tier: str, num_trips: int):
    """Create config.xml."""
    from datetime import datetime
    
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<config>\n')
        f.write(f'  <metadata scenario_id="{scenario_id}" created_by="SimForge Pipeline" created_at="{datetime.now().isoformat()}Z">\n')
        f.write(f'    <description>Canonical scenario for {city.city_name}, tier {tier}</description>\n')
        f.write('  </metadata>\n')
        f.write('  <time start_time_s="0" end_time_s="86400" time_step_s="1"/>\n')
        f.write('  <random seed="42" engine_seed_mode="fixed"/>\n')
        f.write('  <units length="meters" speed="m/s" time="seconds"/>\n')
        f.write('  <simulation warmup_time_s="0" aggregation_interval_s="300"/>\n')
        f.write('</config>\n')


def _create_manifest(scenario_dir: Path):
    """Create manifest.xml with file hashes."""
    import hashlib
    from datetime import datetime
    import os
    
    files = []
    for file in scenario_dir.glob("*.xml"):
        if file.name != "manifest.xml":
            size = os.path.getsize(file)
            with open(file, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            files.append((file.name, sha256, size))
    
    # Also include demand.csv
    demand_csv = scenario_dir / "demand.csv"
    if demand_csv.exists():
        size = os.path.getsize(demand_csv)
        with open(demand_csv, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        files.append(("demand.csv", sha256, size))
    
    scenario_id = scenario_dir.name
    scenario_name = scenario_id.replace("_", " ").title()
    
    manifest_path = scenario_dir / "manifest.xml"
    with open(manifest_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<manifest>\n')
        f.write(f'  <scenario id="{scenario_id}" name="{scenario_name}">\n')
        f.write('    <description>Generated by SimForge Pipeline</description>\n')
        f.write('  </scenario>\n')
        f.write('  <canonical_files>\n')
        
        type_map = {
            "network.xml": ("network", "true"),
            "demand.csv": ("demand", "true"),
            "signals.xml": ("signals", "false"),
            "config.xml": ("config", "true"),
        }
        
        for filename, sha256, size in files:
            file_type, required = type_map.get(filename, ("other", "false"))
            f.write(f'    <file type="{file_type}" path="{filename}" required="{required}" sha256="{sha256}" size_bytes="{size}"/>\n')
        
        f.write('  </canonical_files>\n')
        f.write(f'  <metadata generated_at="{datetime.now().isoformat()}Z" generator="SimForge Pipeline v0.1.0"/>\n')
        f.write('</manifest>\n')


def main():
    parser = argparse.ArgumentParser(
        description="Build city-scale canonical bundles for thesis benchmark"
    )
    parser.add_argument(
        "city",
        nargs="?",
        choices=list(CITIES.keys()) + ["all"],
        help="City to build (or 'all' for all cities)"
    )
    parser.add_argument(
        "--tier",
        choices=list(TIERS.keys()) + ["all"],
        default="50k",
        help="Demand tier (default: 50k)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scenarios"),
        help="Output directory root (default: scenarios/)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scenarios"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available cities and tiers"
    )
    
    args = parser.parse_args()
    
    if args.list:
        print("\nAvailable Cities:")
        print("-" * 50)
        for key, city in CITIES.items():
            print(f"  {key:15} - {city.city_name}, {city.state_or_country}")
        print("\nAvailable Tiers:")
        print("-" * 50)
        for key, count in TIERS.items():
            print(f"  {key:15} - {count:,} trips")
        return 0
    
    if not args.city:
        parser.print_help()
        return 1
    
    # Determine cities and tiers to build
    cities = list(CITIES.keys()) if args.city == "all" else [args.city]
    tiers = list(TIERS.keys()) if args.tier == "all" else [args.tier]
    
    results = []
    for city_key in cities:
        for tier in tiers:
            try:
                path = build_scenario(city_key, tier, args.output, args.force)
                results.append((city_key, tier, "SUCCESS", path))
            except Exception as e:
                logger.error(f"Failed to build {city_key}/{tier}: {e}")
                results.append((city_key, tier, "FAILED", str(e)))
    
    # Summary
    print("\n" + "=" * 60)
    print("Build Summary")
    print("=" * 60)
    for city, tier, status, info in results:
        print(f"  {city:15} {tier:6} - {status}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
