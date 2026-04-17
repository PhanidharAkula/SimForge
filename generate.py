#!/usr/bin/env python3
"""
SimForge Unified Scenario Generator

Generate fully customizable canonical scenario bundles using census
(ModelGen) data as the default demand source.

Users can specify any combination of: city, trip count, time window,
travel modes, network radius, and random seed.

Usage:
  # Basic: 5K car trips in Chicago, 1-hour window (census default)
  python generate.py --city chicago --trips 5000

  # Custom: 200K mixed-mode trips, morning rush
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400

  # Full control
  python generate.py --city nyc --trips 170000 --modes car \\
         --start-time 0 --end-time 86400 --radius 5.0 --seed 123

  # Use a preset configuration
  python generate.py --preset morning_rush

  # Use synthetic demand (fallback if no model file)
  python generate.py --city chicago --trips 5000 --synthetic

  # List presets and cities
  python generate.py --list
"""

import argparse
import json
import math
import shutil
import sys
import time
import logging
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.network.build_network_from_osm import build_network_from_osm, BoundingBox
from pipeline.demand.generate_synthetic_demand import generate_synthetic_demand
from pipeline.demand.generate_census_demand import generate_census_demand
from pipeline.demand.parse_model_file import parse_model_file
from pipeline.signals.build_signals_default import build_signals_default
from pipeline.modelgen_scanner import scan_modelgen_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# CITY REGISTRY
# =============================================================================

CITIES = {
    "chicago": {
        "name": "Chicago, IL",
        "lat": 41.8781,
        "lon": -87.6298,
        "default_radius_km": 4.0,
        "model_file": "modelgen/chicago_model.txt",
        "description": "Chicago urban core — The Loop and surrounding neighbourhoods",
    },
    "nyc": {
        "name": "New York City, NY",
        "lat": 40.7580,
        "lon": -73.9855,
        "default_radius_km": 3.0,
        "model_file": "modelgen/nyc_model.txt",
        "description": "Manhattan Midtown and surrounding boroughs",
    },
    "la": {
        "name": "Los Angeles, CA",
        "lat": 34.0522,
        "lon": -118.2437,
        "default_radius_km": 5.0,
        "model_file": "modelgen/la_model.txt",
        "description": "Downtown LA and surrounding urban area",
    },
}

# All supported travel modes
VALID_MODES = {"car", "transit", "bike", "walk"}


# =============================================================================
# PRESET CONFIGURATIONS
# =============================================================================

PRESETS = {
    "quick_test": {
        "description": "Quick test — 1K car trips, Chicago, 1-hour window",
        "city": "chicago",
        "trips": 1_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 28800,     # 8:00 AM
        "radius_km": 2.0,
        "seed": 42,
    },
    "small_commute": {
        "description": "Small commute — 10K car trips, NYC, 7–9 AM",
        "city": "nyc",
        "trips": 10_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 32400,     # 9:00 AM
        "radius_km": 4.0,
        "seed": 42,
    },
    "medium_multimodal": {
        "description": "Medium multi-modal — 50K trips (car+transit+bike), LA, 6–10 AM",
        "city": "la",
        "trips": 50_000,
        "modes": ["car", "transit", "bike"],
        "start_time": 21600,   # 6:00 AM
        "end_time": 36000,     # 10:00 AM
        "radius_km": 10.0,
        "seed": 42,
    },
    "large_full_day": {
        "description": "Large full-day — 200K car+transit trips, Chicago, 24-hour",
        "city": "chicago",
        "trips": 200_000,
        "modes": ["car", "transit"],
        "start_time": 0,
        "end_time": 86400,     # 24 hours
        "radius_km": 15.0,
        "seed": 42,
    },
    "stress_test": {
        "description": "Stress test — 500K car trips, NYC, 6–10 AM",
        "city": "nyc",
        "trips": 500_000,
        "modes": ["car"],
        "start_time": 21600,   # 6:00 AM
        "end_time": 36000,     # 10:00 AM
        "radius_km": 20.0,
        "seed": 42,
    },
}


# =============================================================================
# HELPERS
# =============================================================================

def _bbox_from_center(lat: float, lon: float, radius_km: float) -> BoundingBox:
    """Create a bounding box from a center point and radius."""
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return BoundingBox(
        north=lat + lat_delta,
        south=lat - lat_delta,
        east=lon + lon_delta,
        west=lon - lon_delta,
    )


def _seconds_to_hhmm(seconds: int) -> str:
    """Convert seconds since midnight to HH:MM format."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h:02d}:{m:02d}"


def _make_scenario_id(city: str, trips: int, modes: list[str]) -> str:
    """Generate a descriptive scenario ID."""
    # Compact trip count
    if trips >= 1_000_000:
        count_str = f"{trips // 1_000_000}m"
    elif trips >= 1_000:
        count_str = f"{trips // 1_000}k"
    else:
        count_str = str(trips)

    mode_str = "_".join(sorted(modes)) if len(modes) > 1 else modes[0]
    return f"{city}_{count_str}_{mode_str}"


def _write_config_xml(
    path: Path,
    scenario_id: str,
    description: str,
    horizon_start: int,
    horizon_end: int,
    seed: int,
) -> None:
    """Write canonical config.xml."""
    root = etree.Element("config")

    meta = etree.SubElement(root, "metadata")
    meta.set("scenario_id", scenario_id)
    meta.set("created_by", "simforge_generator")
    etree.SubElement(meta, "description").text = description

    t = etree.SubElement(root, "time")
    t.set("start_time_s", str(horizon_start))
    t.set("end_time_s", str(horizon_end))
    t.set("time_step_s", "1")

    r = etree.SubElement(root, "random")
    r.set("seed", str(seed))
    r.set("engine_seed_mode", "fixed")

    u = etree.SubElement(root, "units")
    u.set("length", "meters")
    u.set("speed", "m/s")
    u.set("time", "seconds")

    s = etree.SubElement(root, "simulation")
    s.set("warmup_time_s", "0")
    s.set("aggregation_interval_s", "300")

    etree.ElementTree(root).write(
        str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8",
    )


def _write_manifest_xml(path: Path, scenario_id: str) -> None:
    """Write canonical manifest.xml."""
    root = etree.Element("manifest", version="0.1")
    etree.SubElement(root, "scenario", id=scenario_id)

    cf = etree.SubElement(root, "canonical_files")
    for ftype, fname in [
        ("network", "network.xml"),
        ("demand", "demand.csv"),
        ("config", "config.xml"),
        ("signals", "signals.xml"),
    ]:
        etree.SubElement(cf, "file", type=ftype, path=fname)

    etree.ElementTree(root).write(
        str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8",
    )


# =============================================================================
# DISPLAY
# =============================================================================

def show_list():
    """Show available cities and presets with live census data."""
    # Get live census stats
    scan_data = scan_modelgen_dir()
    city_stats = scan_data.get("cities", {})

    print("\n" + "=" * 65)
    print("  SimForge — Available Cities & Presets")
    print("=" * 65)

    print("\n  SUPPORTED CITIES:")
    print("  " + "-" * 61)
    for key, city in CITIES.items():
        model_path = Path(__file__).parent / city["model_file"]
        has_model = model_path.exists()
        status = "census: YES" if has_model else "census: NO"
        print(f"    {key:<12} {city['name']:<25} {status}  "
              f"r={city['default_radius_km']}km")
        print(f"    {'':12} {city['description']}")
        if key in city_stats:
            stats = city_stats[key]
            car = stats['mode_counts'].get('car', 0)
            total = stats['commuters']
            print(f"    {'':12} Census: {car:,} car, {total:,} total commuters")
        print()

    print("  PRESETS (use --preset <name>):")
    print("  " + "-" * 61)
    for name, preset in PRESETS.items():
        modes_str = ",".join(preset["modes"])
        time_str = (f"{_seconds_to_hhmm(preset['start_time'])}"
                    f"–{_seconds_to_hhmm(preset['end_time'])}")
        print(f"    {name:<20} {preset['description']}")
        print(f"    {'':20} city={preset['city']}  trips={preset['trips']:,}  "
              f"modes={modes_str}  time={time_str}")
        print()

    print("  VALID MODES:", ", ".join(sorted(VALID_MODES)))
    print()
    print("  Tip: Run 'python help.py cities' for detailed census limits.")
    print("=" * 65 + "\n")


# =============================================================================
# MAIN GENERATION PIPELINE
# =============================================================================

def generate_scenario(
    city: str,
    trips: int,
    modes: list[str],
    start_time: int,
    end_time: int,
    radius_km: float,
    seed: int,
    output_dir: str | None = None,
    scenario_id: str | None = None,
    synthetic: bool = False,
    allow_oversample: bool = False,
) -> dict:
    """
    Generate a complete canonical scenario bundle.

    Args:
        city: City key (chicago, nyc, la).
        trips: Number of OD trips to generate.
        modes: List of travel modes (car, transit, bike, walk).
        start_time: Simulation start time in seconds from midnight.
        end_time: Simulation end time in seconds from midnight.
        radius_km: Network extraction radius in km.
        seed: Random seed for reproducibility.
        output_dir: Custom output directory. Default: scenarios/<scenario_id>/
        scenario_id: Custom scenario ID. Default: auto-generated.
        synthetic: Force synthetic demand instead of census.
        allow_oversample: Allow more trips than raw census commuters.

    Returns:
        Summary dict with generation results.
    """
    if city not in CITIES:
        raise ValueError(f"Unknown city: {city}. Available: {', '.join(CITIES)}")

    for m in modes:
        if m not in VALID_MODES:
            raise ValueError(f"Invalid mode: {m}. Valid: {', '.join(VALID_MODES)}")

    city_info = CITIES[city]

    # Resolve scenario ID and output path
    if scenario_id is None:
        scenario_id = _make_scenario_id(city, trips, modes)

    project_root = Path(__file__).parent
    if output_dir is not None:
        out = Path(output_dir)
    else:
        out = project_root / "scenarios" / scenario_id

    bbox = _bbox_from_center(city_info["lat"], city_info["lon"], radius_km)

    # Resolve model file
    model_path = project_root / city_info["model_file"]
    use_census = model_path.exists() and not synthetic

    if not use_census and not synthetic:
        logger.warning("Census model file not found: %s — falling back to synthetic",
                       model_path)

    # Time description
    time_desc = f"{_seconds_to_hhmm(start_time)}–{_seconds_to_hhmm(end_time)}"
    modes_desc = "+".join(modes)
    description = (f"{city_info['name']} — {trips:,} {modes_desc} trips, "
                   f"{time_desc}, r={radius_km}km")

    logger.info("=" * 65)
    logger.info("SimForge Scenario Generator")
    logger.info("=" * 65)
    logger.info("  Scenario:   %s", scenario_id)
    logger.info("  City:       %s", city_info["name"])
    logger.info("  Trips:      %s", f"{trips:,}")
    logger.info("  Modes:      %s", ", ".join(modes))
    logger.info("  Time:       %s (%d–%d s)", time_desc, start_time, end_time)
    logger.info("  Radius:     %.1f km", radius_km)
    logger.info("  Seed:       %d", seed)
    logger.info("  Demand:     %s", "census (ModelGen)" if use_census else "synthetic (gravity)")
    logger.info("  Output:     %s", out)
    logger.info("=" * 65)

    t0 = time.time()

    # ---- 1. Network from OSM ----
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    logger.info("Step 1/4: Downloading OSM network (%.1f km radius) ...", radius_km)
    t_step = time.time()
    net = build_network_from_osm(bbox, out / "network.xml", network_type="drive")
    logger.info("  Network: %d nodes, %d links  (%.1fs)",
                net["node_count"], net["link_count"], time.time() - t_step)

    # ---- 2. Signals ----
    logger.info("Step 2/4: Inferring traffic signals ...")
    t_step = time.time()
    sig = build_signals_default(
        network_path=out / "network.xml",
        output_path=out / "signals.xml",
        min_degree=4,
    )
    logger.info("  Signals: %d controllers  (%.1fs)",
                sig["signal_count"], time.time() - t_step)

    # ---- 3. Config / Manifest ----
    logger.info("Step 3/4: Writing config and manifest ...")
    t_step = time.time()
    _write_config_xml(out / "config.xml", scenario_id, description,
                      start_time, end_time, seed)
    _write_manifest_xml(out / "manifest.xml", scenario_id)
    logger.info("  Done  (%.1fs)", time.time() - t_step)

    # ---- 4. Demand ----
    logger.info("Step 4/4: Generating demand (%s) ...",
                "census" if use_census else "synthetic")
    t_step = time.time()
    if use_census:
        multi_mode = len(modes) > 1
        model_data = parse_model_file(
            model_path,
            bbox=(bbox.south, bbox.north, bbox.west, bbox.east),
            car_only=False if multi_mode else ("car" in modes and len(modes) == 1),
            modes=modes if multi_mode else None,
        )
        dem = generate_census_demand(
            model_data=model_data,
            network_path=out / "network.xml",
            output_path=out / "demand.csv",
            num_trips=trips,
            seed=seed,
            horizon_start=start_time,
            horizon_end=end_time,
            mode=modes[0] if len(modes) == 1 else "car",
            modes=modes if multi_mode else None,
            allow_oversample=allow_oversample,
        )
    else:
        dem = generate_synthetic_demand(
            network_path=out / "network.xml",
            output_path=out / "demand.csv",
            num_trips=trips,
            strategy="gravity",
            seed=seed,
            horizon_start=start_time,
            horizon_end=end_time,
            mode=modes[0] if len(modes) == 1 else "car",
        )

    logger.info("  Demand: %d trips  (%.1fs)", dem["trip_count"], time.time() - t_step)

    elapsed = round(time.time() - t0, 1)
    strategy = dem.get("strategy", "synthetic")

    logger.info("")
    logger.info("=" * 65)
    logger.info("  COMPLETE in %.1f s", elapsed)
    logger.info("  Scenario:     %s", scenario_id)
    logger.info("  Output:       %s/", out)
    logger.info("  Network:      %d nodes, %d links", net["node_count"], net["link_count"])
    logger.info("  Signals:      %d controllers", sig["signal_count"])
    logger.info("  Demand (%s): %d trips", strategy, dem["trip_count"])
    logger.info("=" * 65)

    # Save generation metadata
    metadata = {
        "scenario_id": scenario_id,
        "city": city,
        "city_name": city_info["name"],
        "trips_requested": trips,
        "trips_generated": dem["trip_count"],
        "modes": modes,
        "start_time_s": start_time,
        "end_time_s": end_time,
        "radius_km": radius_km,
        "seed": seed,
        "demand_strategy": strategy,
        "node_count": net["node_count"],
        "link_count": net["link_count"],
        "signal_count": sig["signal_count"],
        "generation_time_s": elapsed,
    }
    with open(out / "generation_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description=(
            "SimForge Unified Scenario Generator\n"
            "Generate customizable canonical scenario bundles using census data.\n\n"
            "Census (ModelGen) data is used by default. Use --synthetic to\n"
            "force the gravity-model fallback."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick 5K car scenario in Chicago
  python generate.py --city chicago --trips 5000

  # 200K mixed-mode trips in LA, morning rush (6-9 AM)
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400

  # Full-day 170K car trips in NYC
  python generate.py --city nyc --trips 170000 --start-time 0 --end-time 86400

  # Use a preset configuration
  python generate.py --preset morning_rush

  # Force synthetic demand
  python generate.py --city chicago --trips 5000 --synthetic

  # List all cities, presets, and modes
  python generate.py --list

Supported cities:  chicago, nyc, la
Supported modes:   car, transit, bike, walk
Census limit:      ~500K car trips per city without --allow-oversample
        """,
    )

    # Display commands
    parser.add_argument("--list", action="store_true",
                        help="List available cities, presets, and modes")

    # Preset
    parser.add_argument("--preset", "-p", type=str, default=None,
                        choices=list(PRESETS.keys()),
                        help="Use a built-in preset configuration")

    # City & location
    parser.add_argument("--city", "-c", type=str, default=None,
                        choices=list(CITIES.keys()),
                        help="City to generate (chicago, nyc, la)")
    parser.add_argument("--radius", "-r", type=float, default=None,
                        help="Network radius in km (default: city-specific)")

    # Demand parameters
    parser.add_argument("--trips", "-t", type=int, default=None,
                        help="Number of OD trips to generate (default: 5000)")
    parser.add_argument("--modes", type=str, default=None,
                        help="Comma-separated travel modes: car,transit,bike,walk "
                             "(default: car)")
    parser.add_argument("--start-time", type=int, default=None,
                        help="Simulation start time in seconds from midnight "
                             "(default: 0)")
    parser.add_argument("--end-time", type=int, default=None,
                        help="Simulation end time in seconds from midnight "
                             "(default: 3600)")

    # Control
    parser.add_argument("--seed", "-s", type=int, default=None,
                        help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Custom output directory")
    parser.add_argument("--id", type=str, default=None,
                        help="Custom scenario ID (default: auto-generated)")

    # Demand source
    parser.add_argument("--synthetic", action="store_true",
                        help="Force synthetic gravity-model demand instead of census")
    parser.add_argument("--allow-oversample", action="store_true",
                        help="Allow more trips than raw census commuters "
                             "(resamples origins)")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Handle --list
    if args.list:
        show_list()
        return

    # Handle --preset (load defaults, then allow overrides)
    if args.preset:
        preset = PRESETS[args.preset]
        city = args.city or preset["city"]
        trips = args.trips if args.trips is not None else preset["trips"]
        modes = (args.modes.split(",") if args.modes
                 else preset["modes"])
        start_time = (args.start_time if args.start_time is not None
                      else preset["start_time"])
        end_time = (args.end_time if args.end_time is not None
                    else preset["end_time"])
        radius_km = (args.radius if args.radius is not None
                     else preset["radius_km"])
        seed = args.seed if args.seed is not None else preset["seed"]
    else:
        # Require --city if no preset
        if args.city is None:
            print("Error: --city is required (or use --preset).")
            print("  Available cities: chicago, nyc, la")
            print("  Use --list to see all options.")
            sys.exit(1)

        city = args.city
        trips = args.trips if args.trips is not None else 5_000
        modes = args.modes.split(",") if args.modes else ["car"]
        start_time = args.start_time if args.start_time is not None else 0
        end_time = args.end_time if args.end_time is not None else 3600
        radius_km = (args.radius if args.radius is not None
                     else CITIES[city]["default_radius_km"])
        seed = args.seed if args.seed is not None else 42

    # Validate
    for m in modes:
        if m not in VALID_MODES:
            print(f"Error: Invalid mode '{m}'. Valid modes: {', '.join(sorted(VALID_MODES))}")
            sys.exit(1)

    if start_time >= end_time:
        print(f"Error: --start-time ({start_time}) must be < --end-time ({end_time})")
        sys.exit(1)

    if trips < 1:
        print("Error: --trips must be >= 1")
        sys.exit(1)

    # Run generation
    generate_scenario(
        city=city,
        trips=trips,
        modes=modes,
        start_time=start_time,
        end_time=end_time,
        radius_km=radius_km,
        seed=seed,
        output_dir=args.output,
        scenario_id=args.id,
        synthetic=args.synthetic,
        allow_oversample=args.allow_oversample,
    )


if __name__ == "__main__":
    main()
