#!/usr/bin/env python3
"""
Generate a canonical scenario bundle for Chicago (5K trips).

City:   Chicago, IL — full urban core
Trips:  5,000 OD pairs
Scope:  ~4.0 km radius covering The Loop, Near North/South Side, West Loop

Demand modes:
  Default           Synthetic gravity model (no external data required)
  --model <path>    Census-calibrated using ModelGen file (PUMS + LandScan)

Usage:
  python scripts/generate_chicago_5k.py                              # synthetic demand
  python scripts/generate_chicago_5k.py --model chicago_model.txt  # census demand

Output: scenarios/chicago_5k/
"""

import argparse
import math
import shutil
import time
import logging
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.network.build_network_from_osm import build_network_from_osm, BoundingBox
from pipeline.demand.generate_synthetic_demand import generate_synthetic_demand
from pipeline.demand.generate_census_demand import generate_census_demand
from pipeline.demand.parse_model_file import parse_model_file
from pipeline.signals.build_signals_default import build_signals_default

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City parameters
# ---------------------------------------------------------------------------
CITY_KEY        = "chicago"
SCENARIO_ID     = "chicago_5k"
DESCRIPTION     = "Chicago urban core — 5K trip tier"

CENTER_LAT      = 41.8781
CENTER_LON      = -87.6298
RADIUS_KM       = 4.0          # covers Loop + surrounding neighbourhoods

NUM_TRIPS       = 5_000
SEED            = 42
HORIZON_START   = 0
HORIZON_END     = 3600          # 1-hour simulation window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bbox_from_center(lat: float, lon: float, radius_km: float) -> BoundingBox:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return BoundingBox(
        north=lat + lat_delta,
        south=lat - lat_delta,
        east=lon + lon_delta,
        west=lon - lon_delta,
    )


def _write_config_xml(path: Path) -> None:
    root = etree.Element("config")

    meta = etree.SubElement(root, "metadata")
    meta.set("scenario_id", SCENARIO_ID)
    meta.set("created_by", "simforge_generator")
    etree.SubElement(meta, "description").text = DESCRIPTION

    t = etree.SubElement(root, "time")
    t.set("start_time_s", str(HORIZON_START))
    t.set("end_time_s", str(HORIZON_END))
    t.set("time_step_s", "1")

    r = etree.SubElement(root, "random")
    r.set("seed", str(SEED))
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


def _write_manifest_xml(path: Path) -> None:
    root = etree.Element("manifest", version="0.1")
    etree.SubElement(root, "scenario", id=SCENARIO_ID)

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


# ---------------------------------------------------------------------------
# Demand generation (synthetic vs census)
# ---------------------------------------------------------------------------
def _generate_demand_synthetic(bbox: BoundingBox, out: Path) -> dict:
    """Generate demand using the synthetic gravity model."""
    logger.info("Generating %d synthetic gravity-model trips ...", NUM_TRIPS)
    return generate_synthetic_demand(
        network_path=out / "network.xml",
        output_path=out / "demand.csv",
        num_trips=NUM_TRIPS,
        strategy="gravity",
        seed=SEED,
        horizon_start=HORIZON_START,
        horizon_end=HORIZON_END,
        mode="car",
    )


def _generate_demand_census(bbox: BoundingBox, out: Path,
                            model_path: Path,
                            allow_oversample: bool = False) -> dict:
    """Generate demand from a ModelGen census file."""
    logger.info("Parsing ModelGen file: %s", model_path)
    logger.info("  bbox (%.4f, %.4f, %.4f, %.4f)",
                bbox.south, bbox.north, bbox.west, bbox.east)
    model_data = parse_model_file(
        model_path,
        bbox=(bbox.south, bbox.north, bbox.west, bbox.east),
    )
    logger.info("Generating %d census-calibrated trips ...", NUM_TRIPS)
    return generate_census_demand(
        model_data=model_data,
        network_path=out / "network.xml",
        output_path=out / "demand.csv",
        num_trips=NUM_TRIPS,
        seed=SEED,
        horizon_start=HORIZON_START,
        horizon_end=HORIZON_END,
        mode="car",
        allow_oversample=allow_oversample,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Generate {SCENARIO_ID} scenario bundle.",
    )
    parser.add_argument(
        "--model", "-m", type=Path, default=None,
        help="Path to ModelGen file (e.g. chicago_model.txt). "
             "Enables census-calibrated demand. "
             "When omitted, synthetic gravity-model demand is generated.",
    )
    parser.add_argument(
        "--allow-oversample", action="store_true",
        help="Allow more trips than raw census commuters in the model file. "
             "Origins will be resampled (repeated). Without this flag, the "
             "script errors if the model file has fewer commuters than NUM_TRIPS.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    base = Path(__file__).parent.parent / "scenarios"
    out = base / SCENARIO_ID
    bbox = _bbox_from_center(CENTER_LAT, CENTER_LON, RADIUS_KM)

    # Validate --model path up front
    if args.model is not None and not args.model.exists():
        logger.error("Model file not found: %s", args.model)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Generating  %s  (%s)", SCENARIO_ID, DESCRIPTION)
    if args.model:
        logger.info("Demand mode: census (ModelGen: %s)", args.model.name)
    else:
        logger.info("Demand mode: synthetic (gravity model)")
    logger.info("=" * 60)

    t0 = time.time()

    # 1 -- Network from OSM
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    logger.info("Downloading OSM network (%.1f km radius) ...", RADIUS_KM)
    net = build_network_from_osm(bbox, out / "network.xml",
                                 network_type="drive")
    logger.info("Network: %d nodes, %d links",
                net["node_count"], net["link_count"])

    # 3 -- Signals (inferred from network topology)
    logger.info("Inferring traffic signals from network topology ...")
    sig = build_signals_default(
        network_path=out / "network.xml",
        output_path=out / "signals.xml",
        min_degree=4,
    )
    logger.info("Signals: %d controllers", sig["signal_count"])

    # 4 -- Config / Manifest
    _write_config_xml(out / "config.xml")
    _write_manifest_xml(out / "manifest.xml")

    # 2 -- Demand
    if args.model:
        dem = _generate_demand_census(bbox, out, args.model,
                                            args.allow_oversample)
    else:
        dem = _generate_demand_synthetic(bbox, out)

    strategy = dem.get("strategy", "synthetic")
    logger.info("Demand (%s): %d trips", strategy, dem["trip_count"])

    elapsed = round(time.time() - t0, 1)

    print()
    print("=" * 60)
    print(f"  {SCENARIO_ID}")
    print(f"  Network : {net['node_count']} nodes, {net['link_count']} links")
    print(f"  Demand  : {dem['trip_count']} trips ({strategy})")
    print(f"  Signals : {sig['signal_count']} controllers")
    if strategy == "census":
        print(f"  Census  : {dem.get('census_commuters', '?')} commuters, "
              f"avg {dem.get('avg_commute_min', '?')} min")
    print(f"  Time    : {elapsed} s")
    print(f"  Output  : {out}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
