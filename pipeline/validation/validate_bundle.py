#!/usr/bin/env python3
"""
SimForge v0 bundle validator.

Usage:
    python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid
"""

import argparse
import csv
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def validate_bundle(scenario_root: Path) -> bool:
    """
    Validate a canonical scenario bundle located at scenario_root.

    Expected files (for v0):
      - manifest.xml
      - network.xml
      - demand.csv
      - config.xml
      - (optional) signals.xml

    Returns True if the bundle is valid, False otherwise.
    """
    errors: list[str] = []

    if not scenario_root.is_dir():
        errors.append(f"Scenario root is not a directory: {scenario_root}")
        return report_result(scenario_root, errors)

    # -------------------------------------------------------------------------
    # 1. Check manifest.xml
    # -------------------------------------------------------------------------
    manifest_path = scenario_root / "manifest.xml"
    if not manifest_path.is_file():
        errors.append(f"Missing manifest.xml at {manifest_path}")
        return report_result(scenario_root, errors)

    try:
        manifest_tree = ET.parse(manifest_path)
        manifest_root = manifest_tree.getroot()
    except Exception as e:
        errors.append(f"Failed to parse manifest.xml: {e}")
        return report_result(scenario_root, errors)

    if manifest_root.tag != "manifest":
        errors.append(f"manifest.xml root element must be <manifest>, found <{manifest_root.tag}>")

    scenario_elem = manifest_root.find("scenario")
    canonical_files_elem = manifest_root.find("canonical_files")

    if scenario_elem is None:
        errors.append("manifest.xml is missing <scenario> element")
    if canonical_files_elem is None:
        errors.append("manifest.xml is missing <canonical_files> element")

    scenario_id_manifest = None
    if scenario_elem is not None:
        scenario_id_manifest = scenario_elem.get("id")
        if not scenario_id_manifest:
            errors.append("<scenario> element must have non-empty 'id' attribute")

    # Collect canonical file declarations
    canonical_files: dict[str, list[dict]] = {}
    if canonical_files_elem is not None:
        for file_elem in canonical_files_elem.findall("file"):
            file_type = file_elem.get("type")
            file_path = file_elem.get("path")
            required_str = (file_elem.get("required") or "true").lower()
            required_flag = required_str != "false"

            if not file_type:
                errors.append("A <file> entry in <canonical_files> is missing 'type' attribute")
                continue
            if not file_path:
                errors.append(f"<file> entry with type='{file_type}' is missing 'path' attribute")
                continue

            canonical_files.setdefault(file_type, []).append(
                {"path": file_path, "required": required_flag}
            )

    # For v0: expect exactly one of each primary canonical type
    for required_type in ("network", "demand", "config"):
        entries = canonical_files.get(required_type, [])
        if len(entries) == 0:
            errors.append(f"manifest.xml does not define a canonical '{required_type}' file")
        elif len(entries) > 1:
            errors.append(
                f"manifest.xml defines multiple canonical '{required_type}' files "
                f"(expected exactly one for v0)"
            )

    # Check that required files exist on disk
    for file_type, entries in canonical_files.items():
        for entry in entries:
            if not entry["required"]:
                continue
            rel_path = entry["path"]
            full_path = scenario_root / rel_path
            if not full_path.is_file():
                errors.append(
                    f"Required canonical file of type '{file_type}' not found: {full_path}"
                )

    # If manifest structure is already broken badly, stop here
    if errors:
        return report_result(scenario_root, errors)

    # -------------------------------------------------------------------------
    # 2. Load config.xml and cross-check scenario id + units
    # -------------------------------------------------------------------------
    config_entry = canonical_files["config"][0]
    config_path = scenario_root / config_entry["path"]

    try:
        config_tree = ET.parse(config_path)
        config_root = config_tree.getroot()
    except Exception as e:
        errors.append(f"Failed to parse config.xml: {e}")
        return report_result(scenario_root, errors)

    if config_root.tag != "config":
        errors.append(f"config.xml root element must be <config>, found <{config_root.tag}>")

    cfg_metadata = config_root.find("metadata")
    cfg_units = config_root.find("units")

    scenario_id_config = None
    if cfg_metadata is None:
        errors.append("config.xml is missing <metadata> element")
    else:
        scenario_id_config = cfg_metadata.get("scenario_id")
        if not scenario_id_config:
            errors.append("<metadata> in config.xml must have non-empty 'scenario_id' attribute")

    # Compare scenario ids
    if scenario_id_manifest and scenario_id_config:
        if scenario_id_manifest != scenario_id_config:
            errors.append(
                f"Scenario ID mismatch: manifest.id='{scenario_id_manifest}' "
                f"vs config.metadata.scenario_id='{scenario_id_config}'"
            )

    # Extract units from config
    cfg_units_length = cfg_units_speed = cfg_units_time = None
    if cfg_units is None:
        errors.append("config.xml is missing <units> element")
    else:
        cfg_units_length = cfg_units.get("length")
        cfg_units_speed = cfg_units.get("speed")
        cfg_units_time = cfg_units.get("time")
        if not cfg_units_length or not cfg_units_speed or not cfg_units_time:
            errors.append(
                "config.xml <units> must define 'length', 'speed', and 'time' attributes"
            )

    # -------------------------------------------------------------------------
    # 3. Load network.xml and extract node ids + units
    # -------------------------------------------------------------------------
    network_entry = canonical_files["network"][0]
    network_path = scenario_root / network_entry["path"]

    node_ids: set[str] = set()
    net_units_length = net_units_speed = None

    try:
        network_tree = ET.parse(network_path)
        network_root = network_tree.getroot()
    except Exception as e:
        errors.append(f"Failed to parse network.xml: {e}")
        return report_result(scenario_root, errors)

    if network_root.tag != "network":
        errors.append(f"network.xml root element must be <network>, found <{network_root.tag}>")

    meta_elem = network_root.find("metadata")
    nodes_elem = network_root.find("nodes")

    if meta_elem is None:
        errors.append("network.xml is missing <metadata> element")
    else:
        net_units_length = meta_elem.get("units_length")
        net_units_speed = meta_elem.get("units_speed")
        if not net_units_length or not net_units_speed:
            errors.append(
                "network.xml <metadata> must define 'units_length' and 'units_speed' attributes"
            )

    if nodes_elem is None:
        errors.append("network.xml is missing <nodes> element")
    else:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if not node_id:
                errors.append("<node> element in network.xml is missing 'id' attribute")
                continue
            if node_id in node_ids:
                errors.append(f"Duplicate node id in network.xml: '{node_id}'")
            node_ids.add(node_id)

    # Cross-check unit consistency between network and config
    if net_units_length and cfg_units_length and net_units_length != cfg_units_length:
        errors.append(
            f"Length units mismatch: network.metadata.units_length='{net_units_length}' "
            f"vs config.units.length='{cfg_units_length}'"
        )
    if net_units_speed and cfg_units_speed and net_units_speed != cfg_units_speed:
        errors.append(
            f"Speed units mismatch: network.metadata.units_speed='{net_units_speed}' "
            f"vs config.units.speed='{cfg_units_speed}'"
        )

    # -------------------------------------------------------------------------
    # 4. Load demand.csv and check node references
    # -------------------------------------------------------------------------
    demand_entry = canonical_files["demand"][0]
    demand_path = scenario_root / demand_entry["path"]

    required_columns = {
        "trip_id",
        "origin_node_id",
        "destination_node_id",
        "departure_time_s",
        "mode",
    }

    if not node_ids:
        errors.append(
            "No node ids were extracted from network.xml; cannot validate demand node references"
        )
        return report_result(scenario_root, errors)

    try:
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                errors.append("demand.csv appears to be empty or has no header row")
                return report_result(scenario_root, errors)

            header_cols = set(reader.fieldnames)
            missing = required_columns - header_cols
            if missing:
                errors.append(
                    f"demand.csv is missing required columns: {', '.join(sorted(missing))}"
                )
                return report_result(scenario_root, errors)

            for row_idx, row in enumerate(reader, start=2):  # 1-based header, data starts at line 2
                trip_id = row.get("trip_id", "").strip()
                origin = row.get("origin_node_id", "").strip()
                dest = row.get("destination_node_id", "").strip()
                departure_raw = row.get("departure_time_s", "").strip()

                if not trip_id:
                    errors.append(f"demand.csv row {row_idx}: empty trip_id")

                if origin not in node_ids:
                    errors.append(
                        f"demand.csv row {row_idx}: origin_node_id '{origin}' not found in network nodes"
                    )
                if dest not in node_ids:
                    errors.append(
                        f"demand.csv row {row_idx}: destination_node_id '{dest}' not found in network nodes"
                    )

                # Basic non-negative integer check for departure_time_s
                try:
                    departure_val = int(departure_raw)
                    if departure_val < 0:
                        errors.append(
                            f"demand.csv row {row_idx}: departure_time_s={departure_val} is negative"
                        )
                except ValueError:
                    errors.append(
                        f"demand.csv row {row_idx}: departure_time_s='{departure_raw}' is not a valid integer"
                    )

    except FileNotFoundError:
        errors.append(f"demand.csv file not found at {demand_path}")
    except Exception as e:
        errors.append(f"Failed to read or parse demand.csv: {e}")

    # -------------------------------------------------------------------------
    # 5. Final report
    # -------------------------------------------------------------------------
    return report_result(scenario_root, errors)


def report_result(scenario_root: Path, errors: list[str]) -> bool:
    """
    Print validation result and return True (valid) or False (invalid).
    """
    if errors:
        print(f"  ✗ INVALID  {scenario_root.name}")
        for err in errors:
            print(f"    └─ {err}")
        return False
    else:
        print(f"  ✓ VALID    {scenario_root.name}")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a SimForge canonical scenario bundle."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario_root).resolve()
    ok = validate_bundle(scenario_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()