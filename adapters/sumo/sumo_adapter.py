"""
SUMO adapter for SimForge.

For v0, this module:

- Loads a canonical scenario bundle (manifest, network, demand, config, optional signals).
- Builds a simple summary of the scenario (node count, link count, trip count, time horizon, etc.).
- Writes placeholder SUMO input files into an output directory:
    - net.net.xml
    - routes.rou.xml
    - toy.sumocfg

Later, this will be extended to perform an actual conversion of the canonical bundle
into proper SUMO artifacts.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass
class ScenarioSummary:
    scenario_id: str
    node_count: int
    link_count: int
    trip_count: int
    has_signals: bool
    start_time_s: int
    end_time_s: int


def load_canonical_paths(scenario_root: Path) -> dict[str, Path]:
    """
    Resolve canonical file paths from manifest.xml.

    Expected:
      - manifest.xml exists at scenario_root
      - <canonical_files> section lists network, demand, config
      - signals is optional
    """
    manifest_path = scenario_root / "manifest.xml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.xml not found at {manifest_path}")

    tree = ET.parse(manifest_path)
    root = tree.getroot()
    if root.tag != "manifest":
        raise ValueError(f"manifest.xml root tag must be <manifest>, found <{root.tag}>")

    canonical_files_elem = root.find("canonical_files")
    if canonical_files_elem is None:
        raise ValueError("manifest.xml missing <canonical_files> element")

    resolved: dict[str, Path] = {}
    for file_elem in canonical_files_elem.findall("file"):
        file_type = file_elem.get("type")
        rel_path = file_elem.get("path")
        if not file_type or not rel_path:
            continue
        resolved[file_type] = scenario_root / rel_path

    # Basic expectations for v0
    for required_type in ("network", "demand", "config"):
        if required_type not in resolved:
            raise ValueError(f"manifest.xml does not define canonical '{required_type}' file")

    # signals is optional
    return resolved


def summarize_scenario(scenario_root: Path) -> ScenarioSummary:
    """
    Load the canonical bundle and return a high-level summary.

    This reuses the same canonical files the validator checked,
    but does not perform deep validation here (that's the validator's job).
    """
    paths = load_canonical_paths(scenario_root)

    # --- Config: scenario_id + time horizon ---
    config_path = paths["config"]
    config_tree = ET.parse(config_path)
    config_root = config_tree.getroot()
    if config_root.tag != "config":
        raise ValueError(f"config.xml root must be <config>, found <{config_root.tag}>")

    metadata_elem = config_root.find("metadata")
    time_elem = config_root.find("time")

    if metadata_elem is None:
        raise ValueError("config.xml missing <metadata> element")
    if time_elem is None:
        raise ValueError("config.xml missing <time> element")

    scenario_id = metadata_elem.get("scenario_id") or ""
    if not scenario_id:
        raise ValueError("config.xml <metadata> must have non-empty 'scenario_id'")

    start_time_s_raw = time_elem.get("start_time_s")
    end_time_s_raw = time_elem.get("end_time_s")
    if start_time_s_raw is None or end_time_s_raw is None:
        raise ValueError("config.xml <time> must define 'start_time_s' and 'end_time_s'")

    start_time_s = int(start_time_s_raw)
    end_time_s = int(end_time_s_raw)

    # --- Network: node + link counts ---
    network_path = paths["network"]
    network_tree = ET.parse(network_path)
    network_root = network_tree.getroot()
    if network_root.tag != "network":
        raise ValueError(f"network.xml root must be <network>, found <{network_root.tag}>")

    nodes_elem = network_root.find("nodes")
    links_elem = network_root.find("links")

    node_count = 0
    link_count = 0

    if nodes_elem is not None:
        node_count = len(nodes_elem.findall("node"))
    if links_elem is not None:
        link_count = len(links_elem.findall("link"))

    # --- Demand: trip count ---
    demand_path = paths["demand"]
    trip_count = 0
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for _row in reader:
            trip_count += 1

    # --- Signals: presence flag ---
    has_signals = False
    signals_path = paths.get("signals")
    if signals_path is not None and signals_path.is_file():
        signals_tree = ET.parse(signals_path)
        signals_root = signals_tree.getroot()
        if signals_root.tag == "signals":
            junctions = signals_root.findall("junction")
            has_signals = len(junctions) > 0

    return ScenarioSummary(
        scenario_id=scenario_id,
        node_count=node_count,
        link_count=link_count,
        trip_count=trip_count,
        has_signals=has_signals,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
    )


def prepare_sumo_inputs(scenario_root: Path, output_dir: Path) -> ScenarioSummary:
    """
    Prepare SUMO input files for the given canonical scenario.

    v0 behavior:
      - Ensure output_dir exists.
      - Compute a ScenarioSummary.
      - Write placeholder SUMO files:
          - net.net.xml
          - routes.rou.xml
          - toy.sumocfg

    Later, this will be replaced with real conversion logic.
    """
    scenario_root = scenario_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize_scenario(scenario_root)

    net_path = output_dir / "net.net.xml"
    routes_path = output_dir / "routes.rou.xml"
    cfg_path = output_dir / "toy.sumocfg"

    # Placeholder SUMO network
    net_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Placeholder SUMO network generated from canonical network.xml -->
<!-- Scenario: {summary.scenario_id} -->
<net>
  <!-- TODO: implement canonical network -> SUMO net conversion -->
</net>
"""
    net_path.write_text(net_content, encoding="utf-8")

    # Placeholder SUMO routes
    routes_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Placeholder SUMO routes generated from canonical demand.csv -->
<!-- Scenario: {summary.scenario_id}, trips: {summary.trip_count} -->
<routes>
  <!-- TODO: implement canonical demand -> SUMO routes conversion -->
</routes>
"""
    routes_path.write_text(routes_content, encoding="utf-8")

    # Minimal SUMO config referencing the above files
    cfg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Placeholder SUMO config for scenario '{summary.scenario_id}' -->
<configuration>
  <input>
    <net-file value="net.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
  <time>
    <begin value="{summary.start_time_s}" />
    <end value="{summary.end_time_s}" />
  </time>
</configuration>
"""
    cfg_path.write_text(cfg_content, encoding="utf-8")

    return summary