"""
Generate complete scenario bundles with 5k trips for benchmarking.

This script creates 3 scenarios (replacing Berlin with SF Downtown):
1. Sioux Falls (classic transport benchmark)
2. Austin Downtown 
3. SF Downtown (replaces Berlin which caused SUMO netconvert crashes)

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import project modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.network.build_network_from_osm import build_network_from_osm, BoundingBox
from pipeline.demand.generate_synthetic_demand import generate_synthetic_demand


# City configurations with smaller bounding boxes for better network quality
CITIES = {
    "sioux_falls": {
        "name": "Sioux Falls",
        "center": (43.5446, -96.7311),
        "radius_km": 3.0,  # Smaller for cleaner network
        "description": "Classic transport benchmark city"
    },
    "austin_downtown": {
        "name": "Austin Downtown", 
        "center": (30.2672, -97.7431),
        "radius_km": 2.0,  # Smaller downtown area
        "description": "Downtown Austin, TX"
    },
    "sf_downtown": {
        "name": "SF Downtown",
        "center": (37.7879, -122.4074),
        "radius_km": 1.5,  # Compact downtown
        "description": "San Francisco Downtown (replaces Berlin)"
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
    time = etree.SubElement(config, "time")
    time.set("start_time_s", "0")
    time.set("end_time_s", "3600")  # 1 hour simulation
    time.set("time_step_s", "1")
    
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


def create_manifest_xml(scenario_path: Path, scenario_id: str) -> None:
    """Create manifest.xml for the scenario."""
    manifest = etree.Element("manifest")
    manifest.set("version", "0.1")
    
    scenario_elem = etree.SubElement(manifest, "scenario")
    scenario_elem.set("id", scenario_id)
    
    canonical_files = etree.SubElement(manifest, "canonical_files")
    
    files = [
        ("network", "network.xml"),
        ("demand", "demand.csv"),
        ("config", "config.xml"),
        ("signals", "signals.xml")
    ]
    
    for file_type, file_path in files:
        file_elem = etree.SubElement(canonical_files, "file")
        file_elem.set("type", file_type)
        file_elem.set("path", file_path)
    
    tree = etree.ElementTree(manifest)
    tree.write(str(scenario_path / "manifest.xml"), pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    logger.info(f"Created manifest.xml for {scenario_id}")


def create_signals_xml(scenario_path: Path) -> None:
    """Create placeholder signals.xml."""
    signals = etree.Element("signals")
    signals.set("version", "0.1")
    
    # Empty signals file (no traffic signals defined)
    tree = etree.ElementTree(signals)
    tree.write(str(scenario_path / "signals.xml"), pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    logger.info("Created signals.xml (placeholder)")


def generate_scenario(city_key: str, city_config: dict, output_base: Path) -> dict:
    """Generate a complete scenario for a city."""
    scenario_id = f"{city_key}_tier5k"
    scenario_path = output_base / scenario_id
    
    # Clean existing
    if scenario_path.exists():
        shutil.rmtree(scenario_path)
    scenario_path.mkdir(parents=True)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Generating scenario: {scenario_id}")
    logger.info(f"City: {city_config['name']}")
    logger.info(f"{'='*60}")
    
    # Create bounding box
    lat, lon = city_config["center"]
    import math
    lat_delta = city_config["radius_km"] / 111.0
    lon_delta = city_config["radius_km"] / (111.0 * math.cos(math.radians(lat)))
    bbox = BoundingBox(
        north=lat + lat_delta,
        south=lat - lat_delta,
        east=lon + lon_delta,
        west=lon - lon_delta
    )
    
    # 1. Build network from OSM
    logger.info("Building network from OSM...")
    network_result = build_network_from_osm(
        bbox=bbox,
        output_path=scenario_path / "network.xml",
        network_type="drive"
    )
    logger.info(f"Network: {network_result['node_count']} nodes, {network_result['link_count']} links")
    
    # 2. Generate demand with routable OD pairs
    logger.info(f"Generating {NUM_TRIPS} trips with routable OD pairs...")
    demand_result = generate_synthetic_demand(
        network_path=scenario_path / "network.xml",
        output_path=scenario_path / "demand.csv",
        num_trips=NUM_TRIPS,
        strategy="gravity",
        seed=SEED,
        horizon_start=0,
        horizon_end=3600,
        mode="car",
        min_distance_km=0.3,  # Shorter min distance for smaller networks
        max_distance_km=5.0   # Shorter max for downtown areas
    )
    logger.info(f"Demand: {demand_result['trip_count']} trips generated")
    
    # 3. Create config.xml
    create_config_xml(scenario_path, scenario_id, city_config["description"])
    
    # 4. Create manifest.xml
    create_manifest_xml(scenario_path, scenario_id)
    
    # 5. Create signals.xml placeholder
    create_signals_xml(scenario_path)
    
    return {
        "scenario_id": scenario_id,
        "path": str(scenario_path),
        "nodes": network_result["node_count"],
        "links": network_result["link_count"],
        "trips": demand_result["trip_count"]
    }


def main():
    """Generate all scenarios."""
    output_base = Path(__file__).parent.parent / "scenarios"
    
    results = []
    for city_key, city_config in CITIES.items():
        try:
            result = generate_scenario(city_key, city_config, output_base)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to generate {city_key}: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*60)
    print("SCENARIO GENERATION SUMMARY")
    print("="*60)
    for result in results:
        print(f"\n{result['scenario_id']}:")
        print(f"  Path: {result['path']}")
        print(f"  Network: {result['nodes']} nodes, {result['links']} links")
        print(f"  Demand: {result['trips']} trips")
    
    print(f"\n✅ Generated {len(results)} scenarios with {NUM_TRIPS} trips each")
    print("Ready for benchmarking!")


if __name__ == "__main__":
    main()
