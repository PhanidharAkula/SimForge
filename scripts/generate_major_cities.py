"""
Generate scenario bundles for major US cities with 5k trips.

Cities:
1. Chicago Downtown
2. New York (Midtown Manhattan)
3. Los Angeles Downtown

Each scenario includes:
- network.xml (from OSM)
- demand.csv (5k trips with routable OD pairs)
- config.xml
- manifest.xml
- signals.xml (placeholder)
"""

import shutil
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import project modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.network.build_network_from_osm import build_network_from_osm, BoundingBox
from pipeline.demand.generate_synthetic_demand import generate_synthetic_demand


# Major city configurations with downtown areas for manageable network sizes
CITIES = {
    "chicago_downtown": {
        "name": "Chicago Downtown",
        "center": (41.8781, -87.6298),  # The Loop
        "radius_km": 2.0,
        "description": "Chicago Downtown (The Loop area)"
    },
    "nyc_midtown": {
        "name": "NYC Midtown",
        "center": (40.7549, -73.9840),  # Midtown Manhattan
        "radius_km": 1.5,  # Compact area due to dense grid
        "description": "New York City Midtown Manhattan"
    },
    "la_downtown": {
        "name": "LA Downtown",
        "center": (34.0407, -118.2468),  # Downtown LA
        "radius_km": 2.5,
        "description": "Los Angeles Downtown"
    }
}

NUM_TRIPS = 5000
SEED = 42


def create_config_xml(scenario_path: Path, scenario_id: str, description: str) -> None:
    """Create config.xml for the scenario (following canonical schema v0)."""
    config = etree.Element("config")
    
    # Metadata - required
    metadata = etree.SubElement(config, "metadata")
    metadata.set("scenario_id", scenario_id)
    metadata.set("created_by", "simforge_generator")
    desc = etree.SubElement(metadata, "description")
    desc.text = description
    
    # Time - required
    time_elem = etree.SubElement(config, "time")
    time_elem.set("start_time_s", "0")
    time_elem.set("end_time_s", "3600")  # 1 hour simulation
    time_elem.set("time_step_s", "1")
    
    # Random - required
    random = etree.SubElement(config, "random")
    random.set("seed", str(SEED))
    random.set("engine_seed_mode", "fixed")
    
    # Units - required
    units = etree.SubElement(config, "units")
    units.set("length", "meters")
    units.set("speed", "m/s")
    units.set("time", "seconds")
    
    # Simulation - optional but helpful
    simulation = etree.SubElement(config, "simulation")
    simulation.set("warmup_time_s", "0")
    simulation.set("aggregation_interval_s", "300")
    
    tree = etree.ElementTree(config)
    tree.write(str(scenario_path / "config.xml"), pretty_print=True, 
               xml_declaration=True, encoding="UTF-8")
    logger.info(f"Created config.xml for {scenario_id}")


def create_manifest_xml(scenario_path: Path, scenario_id: str, description: str) -> None:
    """Create manifest.xml for the scenario (following canonical schema)."""
    manifest = etree.Element("manifest")
    manifest.set("version", "0.1")
    
    scenario = etree.SubElement(manifest, "scenario")
    scenario.set("id", scenario_id)
    
    # Use canonical_files format as expected by validator
    canonical_files = etree.SubElement(manifest, "canonical_files")
    for ftype, fname in [("network", "network.xml"), ("demand", "demand.csv"), 
                         ("config", "config.xml"), ("signals", "signals.xml")]:
        f = etree.SubElement(canonical_files, "file")
        f.set("type", ftype)
        f.set("path", fname)
    
    tree = etree.ElementTree(manifest)
    tree.write(str(scenario_path / "manifest.xml"), pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    logger.info(f"Created manifest.xml for {scenario_id}")


def create_signals_xml(scenario_path: Path) -> None:
    """Create placeholder signals.xml."""
    signals = etree.Element("signals")
    signals.set("version", "0.1")
    tree = etree.ElementTree(signals)
    tree.write(str(scenario_path / "signals.xml"), pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    logger.info("Created signals.xml (placeholder)")


def generate_city_scenario(city_key: str, city_config: dict, base_path: Path) -> dict:
    """Generate a complete scenario for a city."""
    scenario_id = f"{city_key}_tier5k"
    scenario_path = base_path / scenario_id
    
    # Clean and create directory
    if scenario_path.exists():
        shutil.rmtree(scenario_path)
    scenario_path.mkdir(parents=True)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Generating scenario: {scenario_id}")
    logger.info(f"City: {city_config['name']}")
    logger.info(f"{'='*60}")
    
    start_time = time.time()
    
    # Calculate bounding box from center and radius
    lat, lon = city_config["center"]
    radius_km = city_config["radius_km"]
    
    # Approximate conversion: 1 degree latitude ≈ 111 km
    lat_offset = radius_km / 111.0
    lon_offset = radius_km / (111.0 * abs(lat) / 90 + 0.5)  # Adjust for latitude
    
    bbox = BoundingBox(
        north=lat + lat_offset,
        south=lat - lat_offset,
        east=lon + lon_offset,
        west=lon - lon_offset
    )
    
    # Step 1: Build network from OSM
    logger.info("Building network from OSM...")
    network_path = scenario_path / "network.xml"
    network_stats = build_network_from_osm(bbox, network_path)  # Pass Path, not str
    logger.info(f"Network: {network_stats['node_count']} nodes, {network_stats['link_count']} links")
    
    # Step 2: Generate demand
    logger.info(f"Generating {NUM_TRIPS} trips with routable OD pairs...")
    demand_path = scenario_path / "demand.csv"
    demand_stats = generate_synthetic_demand(
        network_path=network_path,  # Path object
        output_path=demand_path,    # Path object
        num_trips=NUM_TRIPS,
        seed=SEED,
        strategy="gravity"  # More realistic distribution
    )
    logger.info(f"Demand: {demand_stats['trip_count']} trips generated")
    
    # Step 3: Create config, manifest, signals
    create_config_xml(scenario_path, scenario_id, city_config["description"])
    create_manifest_xml(scenario_path, scenario_id, city_config["description"])
    create_signals_xml(scenario_path)
    
    elapsed = time.time() - start_time
    
    return {
        "scenario_id": scenario_id,
        "path": str(scenario_path),
        "nodes": network_stats["node_count"],
        "links": network_stats["link_count"],
        "trips": demand_stats["trip_count"],
        "elapsed_seconds": round(elapsed, 1)
    }


def main():
    """Generate all major city scenarios."""
    base_path = Path(__file__).parent.parent / "scenarios"
    base_path.mkdir(exist_ok=True)
    
    results = {}
    total_start = time.time()
    
    for city_key, city_config in CITIES.items():
        try:
            result = generate_city_scenario(city_key, city_config, base_path)
            results[city_key] = result
        except Exception as e:
            logger.error(f"Failed to generate {city_key}: {e}")
            results[city_key] = {"error": str(e)}
    
    total_elapsed = time.time() - total_start
    
    # Print summary
    print(f"\n{'='*60}")
    print("SCENARIO GENERATION SUMMARY")
    print(f"{'='*60}")
    
    for city_key, result in results.items():
        print(f"\n{result.get('scenario_id', city_key)}:")
        if "error" in result:
            print(f"  ❌ ERROR: {result['error']}")
        else:
            print(f"  Path: {result['path']}")
            print(f"  Network: {result['nodes']} nodes, {result['links']} links")
            print(f"  Demand: {result['trips']} trips")
            print(f"  Time: {result['elapsed_seconds']}s")
    
    print(f"\n{'='*60}")
    print(f"Total time: {round(total_elapsed, 1)}s")
    print(f"✅ Generated {len([r for r in results.values() if 'error' not in r])} scenarios with {NUM_TRIPS} trips each")
    print("Ready for benchmarking!")
    
    return results


if __name__ == "__main__":
    main()
