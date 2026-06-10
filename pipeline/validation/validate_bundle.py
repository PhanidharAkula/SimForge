#!/usr/bin/env python3
"""
SimForge canonical bundle validator.

Usage:
    python pipeline/validation/validate_bundle.py scenarios/chicago_1k_car
"""

import argparse
import csv
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def validate_bundle(scenario_root: Path) -> bool:
    """Check the canonical bundle at scenario_root.

    Looks for manifest.xml, network.xml, demand.csv, config.xml, and
    signals.xml, and cross-checks them. Returns True if it all hangs
    together, False otherwise.
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
    except ET.ParseError as e:
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
                {"path": file_path, "required": required_flag,
                 "sha256": file_elem.get("sha256")}
            )

    # Expect exactly one of each primary canonical type
    for required_type in ("network", "demand", "config", "signals"):
        entries = canonical_files.get(required_type, [])
        if len(entries) == 0:
            errors.append(f"manifest.xml does not define a canonical '{required_type}' file")
        elif len(entries) > 1:
            errors.append(
                f"manifest.xml defines multiple canonical '{required_type}' files "
                f"(expected exactly one)"
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

    # Verify SHA-256 checksums when the manifest carries them (manifest
    # version >= 0.2). Older manifests have no sha256 attribute, so the check
    # is simply skipped for them, keeping back-compatibility with bundles
    # generated before self-verifying manifests existed.
    import hashlib
    for file_type, entries in canonical_files.items():
        for entry in entries:
            expected = entry.get("sha256")
            if not expected:
                continue
            full_path = scenario_root / entry["path"]
            if not full_path.is_file():
                continue  # missing-file error already recorded above
            actual = hashlib.sha256(full_path.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(
                    f"Checksum mismatch for canonical '{file_type}' file "
                    f"{entry['path']}: manifest sha256={expected[:12]}..., "
                    f"file sha256={actual[:12]}... (file modified since generation)"
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
    except ET.ParseError as e:
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
    except ET.ParseError as e:
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
    # 3b. Parse signals.xml content
    # -------------------------------------------------------------------------
    # Validation used to only check signals.xml *exists*. Parse its content
    # here so a malformed signals file is caught at validation time (the bundle
    # is flagged INVALID and skipped) instead of later, when an adapter's raw
    # parse would raise mid-run.
    signals_entries = canonical_files.get("signals", [])
    if signals_entries:
        signals_path = scenario_root / signals_entries[0]["path"]
        if signals_path.is_file():
            try:
                signals_root = ET.parse(signals_path).getroot()
            except ET.ParseError as e:
                errors.append(f"Failed to parse signals.xml: {e}")
            else:
                if signals_root.tag != "signals":
                    errors.append(
                        f"signals.xml root element must be <signals>, "
                        f"found <{signals_root.tag}>"
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

            data_rows = 0
            seen_trip_ids: set[str] = set()
            for row_idx, row in enumerate(reader, start=2):  # 1-based header, data starts at line 2
                data_rows += 1
                # `or ""` (not a .get default): DictReader stores None, not a
                # missing key, for columns a short/ragged row doesn't fill
                # (e.g. a stray comment or footer line). Without the guard
                # such a row crashes .strip() with an AttributeError instead
                # of being reported as the invalid data it is.
                trip_id = (row.get("trip_id") or "").strip()
                origin = (row.get("origin_node_id") or "").strip()
                dest = (row.get("destination_node_id") or "").strip()
                departure_raw = (row.get("departure_time_s") or "").strip()

                if not trip_id:
                    errors.append(f"demand.csv row {row_idx}: empty trip_id")
                elif trip_id in seen_trip_ids:
                    errors.append(f"demand.csv row {row_idx}: duplicate trip_id '{trip_id}'")
                else:
                    seen_trip_ids.add(trip_id)

                # Self-loop trips (origin == destination) are degenerate: every
                # engine drops them, so they would inflate agreement metrics
                # without simulating anything.
                if origin and dest and origin == dest:
                    errors.append(
                        f"demand.csv row {row_idx}: origin and destination are the "
                        f"same node '{origin}' (self-loop trip)"
                    )

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

            if data_rows == 0:
                errors.append(
                    "demand.csv has a valid header but zero trip rows; a bundle "
                    "with no demand is degenerate (every engine would simulate "
                    "nothing). Re-generate the scenario."
                )

    except FileNotFoundError:
        errors.append(f"demand.csv file not found at {demand_path}")
    except UnicodeDecodeError as e:
        # Binary junk or a corrupted/truncated file: report INVALID instead
        # of crashing with a raw decode traceback.
        errors.append(
            f"demand.csv is not valid UTF-8 text (binary or corrupted file): {e}"
        )
    except (OSError, csv.Error) as e:
        errors.append(f"Failed to read or parse demand.csv: {e}")

    # -------------------------------------------------------------------------
    # 5. Final report
    # -------------------------------------------------------------------------
    return report_result(scenario_root, errors)


def report_result(scenario_root: Path, errors: list[str]) -> bool:
    """Print the result and return True if valid, False if not."""
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
        help="Path to scenario directory (e.g., scenarios/chicago_1k_car)",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario_root).resolve()
    ok = validate_bundle(scenario_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()