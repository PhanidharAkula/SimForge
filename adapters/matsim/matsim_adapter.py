"""
MATSim Adapter for SimForge.

MATSim is an activity-based, mesoscopic traffic simulator that models agents
and their daily activity plans. This adapter converts canonical bundles to
MATSim input formats.

Key differences from SUMO:
- Agent-based (not vehicle-based)
- Activity plans (not simple OD trips)
- Queue-based mesoscopic traffic model
- Multi-iteration with replanning (disabled for single-run comparison)

Usage:
    from adapters.matsim import prepare_matsim_inputs
    prepare_matsim_inputs("scenarios/toy_2x2_grid", "out/matsim")
"""

import csv
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MATSimConfig:
    """Configuration options for MATSim execution."""
    # Simulation settings
    iterations: int = 0  # 0 = single iteration (no replanning)
    flow_capacity_factor: float = 1.0
    storage_capacity_factor: float = 1.0
    
    # Time settings (in seconds from midnight)
    start_time_s: int = 0
    end_time_s: int = 108000  # 30 hours to capture late arrivals
    
    # Memory settings
    java_heap_gb: int = 4
    
    # Output settings
    write_events: bool = True
    write_plans: bool = True
    
    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "flow_capacity_factor": self.flow_capacity_factor,
            "storage_capacity_factor": self.storage_capacity_factor,
            "start_time_s": self.start_time_s,
            "end_time_s": self.end_time_s,
            "java_heap_gb": self.java_heap_gb,
        }


def find_matsim_jar() -> Optional[Path]:
    """Find MATSim JAR file in common locations."""
    import os
    
    possible_paths = [
        Path("/opt/matsim/matsim.jar"),
        Path("/usr/local/share/matsim/matsim.jar"),
        Path.home() / "matsim" / "matsim.jar",
        Path.home() / ".local" / "share" / "matsim" / "matsim.jar",
    ]
    
    # Check MATSIM_HOME environment variable
    matsim_home = os.environ.get("MATSIM_HOME")
    if matsim_home:
        possible_paths.insert(0, Path(matsim_home) / "matsim.jar")
        # Also check for matsim-{version}.jar pattern
        for jar in Path(matsim_home).glob("matsim-*.jar"):
            if "sources" not in jar.name:
                possible_paths.insert(0, jar)
    
    # Check lib/ folder in project root (relative to this file)
    project_lib = Path(__file__).parent.parent.parent / "lib"
    if project_lib.exists():
        for version_dir in project_lib.glob("matsim-*"):
            if version_dir.is_dir():
                for jar in version_dir.glob("matsim-*.jar"):
                    if "sources" not in jar.name:
                        possible_paths.insert(0, jar)
    
    for p in possible_paths:
        if p.exists():
            return p
    
    # Check for any matsim*.jar in current directory
    for jar in Path(".").glob("matsim*.jar"):
        return jar
    
    return None


def check_java_available() -> Tuple[bool, str]:
    """Check if Java is available and get version."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        # Java version is typically in stderr
        version_output = result.stderr or result.stdout
        if "version" in version_output.lower():
            # Extract version number
            lines = version_output.strip().split("\n")
            return True, lines[0] if lines else "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return False, "Java not found"


def seconds_to_time_string(seconds: int) -> str:
    """Convert seconds since midnight to HH:MM:SS format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_canonical_network(network_path: Path) -> Tuple[Dict, List]:
    """Load canonical network.xml and return nodes and links."""
    tree = ET.parse(network_path)
    root = tree.getroot()
    
    nodes = {}
    nodes_elem = root.find("nodes")
    if nodes_elem is not None:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if node_id:
                nodes[node_id] = {
                    "id": node_id,
                    "x": float(node_elem.get("x", 0)),
                    "y": float(node_elem.get("y", 0)),
                }
    
    links = []
    links_elem = root.find("links")
    if links_elem is not None:
        for link_elem in links_elem.findall("link"):
            link_id = link_elem.get("id")
            if link_id:
                links.append({
                    "id": link_id,
                    "from": link_elem.get("from"),
                    "to": link_elem.get("to"),
                    "length": float(link_elem.get("length", 100)),
                    "speed": float(link_elem.get("speed_limit", 13.9)),
                    "lanes": int(link_elem.get("lanes", 1)),
                })
    
    return nodes, links


def find_link_for_origin(node_id: str, links: List[dict], link_adjacency: dict) -> Optional[str]:
    """
    Find a link for an origin activity.
    In MATSim, the agent departs from the TO-node of the activity link.
    We need a link whose TO-node is our origin AND has outgoing edges.
    """
    # Build set of nodes with outgoing edges
    nodes_with_outgoing = set(link_adjacency.keys())
    
    # First priority: link ending at origin node (TO=origin) where origin has outgoing edges
    if node_id in nodes_with_outgoing:
        for link in links:
            if link["to"] == node_id:
                return link["id"]
    
    # Second priority: link starting from origin (FROM=origin)
    # Agent will be at TO-node, but that node should have outgoing edges
    for link in links:
        if link["from"] == node_id and link["to"] in nodes_with_outgoing:
            return link["id"]
    
    # Fallback: any link connected to this node
    for link in links:
        if link["to"] == node_id or link["from"] == node_id:
            return link["id"]
    
    return links[0]["id"] if links else None


def find_link_for_destination(node_id: str, links: List[dict], link_adjacency: dict) -> Optional[str]:
    """
    Find a link for a destination activity.
    In MATSim, routing goes from origin TO-node to destination FROM-node.
    So we need a link whose FROM-node is our destination (or TO-node as fallback).
    """
    # First priority: link starting from destination (FROM=destination)
    for link in links:
        if link["from"] == node_id:
            return link["id"]
    
    # Second priority: link ending at destination (TO=destination)
    for link in links:
        if link["to"] == node_id:
            return link["id"]
    
    return links[0]["id"] if links else None


def build_matsim_vehicles_xml() -> str:
    """Build MATSim vehicles.xml with standard vehicle types."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd"
                    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                    xsi:schemaLocation="http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">
    <vehicleType id="car">
        <capacity seats="5" standingRoomInPersons="0"/>
        <length meter="7.5"/>
        <width meter="1.0"/>
        <maximumVelocity meterPerSecond="40.0"/>
        <passengerCarEquivalents pce="1.0"/>
        <networkMode networkMode="car"/>
        <flowEfficiencyFactor factor="1.0"/>
    </vehicleType>
</vehicleDefinitions>'''


def build_matsim_network_xml(nodes: Dict, links: List) -> str:
    """Build MATSim network.xml from canonical network data."""
    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">')
    lines.append('<network name="simforge_network">')
    
    # Nodes
    lines.append('  <nodes>')
    for node_id, node in sorted(nodes.items()):
        lines.append(f'    <node id="{node_id}" x="{node["x"]}" y="{node["y"]}"/>')
    lines.append('  </nodes>')
    
    # Links - use capperiod for capacity interpretation
    # Filter out self-loop links (from == to) which are invalid in MATSim
    valid_links = [link for link in links if link["from"] != link["to"]]
    
    lines.append('  <links capperiod="01:00:00">')
    for link in valid_links:
        # MATSim capacity = lanes * 1800 veh/hour (typical saturation flow)
        lanes = max(1, link["lanes"])  # Ensure at least 1 lane
        capacity = lanes * 1800
        length = max(1.0, link["length"])  # Ensure minimum length of 1m
        # Add modes="car" for routing to work
        lines.append(
            f'    <link id="{link["id"]}" '
            f'from="{link["from"]}" to="{link["to"]}" '
            f'length="{length:.2f}" '
            f'freespeed="{link["speed"]:.2f}" '
            f'capacity="{capacity}" '
            f'permlanes="{lanes}" '
            f'modes="car"/>'
        )
    lines.append('  </links>')
    
    lines.append('</network>')
    return "\n".join(lines)


def build_matsim_plans_xml(demand_path: Path, links: List) -> str:
    """Build MATSim plans.xml from canonical demand.csv."""
    lines = []
    lines.append('<?xml version="1.0" ?>')
    lines.append('<!DOCTYPE plans SYSTEM "http://www.matsim.org/files/dtd/plans_v4.dtd">')
    lines.append('<plans>')
    
    # Build adjacency from links (for finding good origin links)
    link_adjacency = {}
    for link in links:
        from_node = link["from"]
        if from_node not in link_adjacency:
            link_adjacency[from_node] = []
        link_adjacency[from_node].append(link["to"])
    
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = row.get("trip_id", "").strip()
            origin = row.get("origin_node_id", "").strip()
            dest = row.get("destination_node_id", "").strip()
            depart_s = row.get("departure_time_s", "0").strip()
            mode = row.get("mode", "car").strip()
            
            if not trip_id or not origin or not dest:
                continue
            
            try:
                depart_seconds = int(float(depart_s))
            except ValueError:
                depart_seconds = 0
            
            # Find links near origin and destination
            origin_link = find_link_for_origin(origin, links, link_adjacency)
            dest_link = find_link_for_destination(dest, links, link_adjacency)
            
            if not origin_link or not dest_link:
                continue
            
            end_time = seconds_to_time_string(depart_seconds)
            person_id = f"person_{trip_id}"
            
            # Use short activity types: h=home, w=work
            lines.append(f'<person id="{person_id}">')
            lines.append('  <plan>')
            lines.append(f'    <act type="h" link="{origin_link}" end_time="{end_time}"/>')
            lines.append(f'    <leg mode="{mode}"/>')
            lines.append(f'    <act type="w" link="{dest_link}"/>')
            lines.append('  </plan>')
            lines.append('</person>')
    
    lines.append('</plans>')
    return "\n".join(lines)


def build_matsim_config_xml(
    config: MATSimConfig,
    network_file: str = "network.xml",
    plans_file: str = "plans.xml",
    vehicles_file: str = "vehicles.xml",
    output_dir: str = "./output",
    random_seed: int = 42
) -> str:
    """Build MATSim config.xml."""
    start_time = seconds_to_time_string(config.start_time_s)
    end_time = seconds_to_time_string(config.end_time_s)
    
    return f'''<?xml version="1.0" ?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
    <module name="global">
        <param name="randomSeed" value="{random_seed}"/>
        <param name="coordinateSystem" value="EPSG:4326"/>
        <param name="numberOfThreads" value="4"/>
    </module>
    
    <module name="network">
        <param name="inputNetworkFile" value="{network_file}"/>
    </module>
    
    <module name="vehicles">
        <param name="vehiclesFile" value="{vehicles_file}"/>
    </module>
    
    <module name="plans">
        <param name="inputPlansFile" value="{plans_file}"/>
        <param name="removingUnnecessaryPlanAttributes" value="true"/>
    </module>
    
    <module name="qsim">
        <param name="startTime" value="{start_time}"/>
        <param name="endTime" value="{end_time}"/>
        <param name="flowCapacityFactor" value="{config.flow_capacity_factor}"/>
        <param name="storageCapacityFactor" value="{config.storage_capacity_factor}"/>
        <param name="numberOfThreads" value="4"/>
        <param name="mainMode" value="car"/>
        <param name="vehiclesSource" value="modeVehicleTypesFromVehiclesData"/>
        <param name="simStarttimeInterpretation" value="onlyUseStarttime"/>
    </module>
    
    <module name="controler">
        <param name="outputDirectory" value="{output_dir}"/>
        <param name="firstIteration" value="0"/>
        <param name="lastIteration" value="{config.iterations}"/>
        <param name="writeEventsInterval" value="1"/>
        <param name="writePlansInterval" value="1"/>
        <param name="mobsim" value="qsim"/>
        <param name="overwriteFiles" value="deleteDirectoryIfExists"/>
    </module>
    
    <module name="planCalcScore">
        <parameterset type="scoringParameters">
            <param name="lateArrival" value="-18"/>
            <param name="earlyDeparture" value="-0"/>
            <param name="performing" value="6"/>
            <param name="waiting" value="-0"/>
            <param name="waitingPt" value="-2"/>
            
            <parameterset type="modeParams">
                <param name="mode" value="car"/>
                <param name="constant" value="0.0"/>
                <param name="marginalUtilityOfTraveling_util_hr" value="-6.0"/>
                <param name="monetaryDistanceRate" value="-0.0002"/>
            </parameterset>
            
            <parameterset type="activityParams">
                <param name="activityType" value="h"/>
                <param name="typicalDuration" value="12:00:00"/>
            </parameterset>
            
            <parameterset type="activityParams">
                <param name="activityType" value="w"/>
                <param name="typicalDuration" value="08:00:00"/>
                <param name="openingTime" value="06:00:00"/>
                <param name="closingTime" value="20:00:00"/>
            </parameterset>
        </parameterset>
    </module>
    
    <module name="strategy">
        <param name="maxAgentPlanMemorySize" value="1"/>
        <parameterset type="strategysettings">
            <param name="strategyName" value="BestScore"/>
            <param name="weight" value="1.0"/>
        </parameterset>
    </module>
</config>
'''


def load_canonical_paths(scenario_root: Path) -> Dict[str, Path]:
    """Load file paths from manifest.xml."""
    manifest_path = scenario_root / "manifest.xml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.xml not found at {manifest_path}")
    
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    
    canonical_files = root.find("canonical_files")
    if canonical_files is None:
        raise ValueError("manifest.xml missing <canonical_files>")
    
    paths = {}
    for file_elem in canonical_files.findall("file"):
        file_type = file_elem.get("type")
        rel_path = file_elem.get("path")
        if file_type and rel_path:
            paths[file_type] = (scenario_root / rel_path).resolve()
    
    return paths


def prepare_matsim_inputs(
    scenario_path: str | Path,
    output_dir: str | Path,
    config: Optional[MATSimConfig] = None,
    random_seed: int = 42
) -> Path:
    """
    Prepare inputs for MATSim simulation.
    
    Args:
        scenario_path: Path to canonical scenario bundle
        output_dir: Output directory for generated files
        config: MATSim configuration options
        random_seed: Random seed for simulation
        
    Returns:
        Path to the generated MATSim config file
    """
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if config is None:
        config = MATSimConfig()
    
    logger.info(f"Preparing MATSim inputs for: {scenario_path}")
    
    # Load canonical files
    paths = load_canonical_paths(scenario_path)
    network_path = paths.get("network")
    demand_path = paths.get("demand")
    
    if not network_path or not network_path.exists():
        raise FileNotFoundError(f"Network file not found: {network_path}")
    if not demand_path or not demand_path.exists():
        raise FileNotFoundError(f"Demand file not found: {demand_path}")
    
    # Load and convert network
    logger.info("Converting network to MATSim format...")
    nodes, links = load_canonical_network(network_path)
    network_xml = build_matsim_network_xml(nodes, links)
    network_out = output_dir / "network.xml"
    network_out.write_text(network_xml, encoding="utf-8")
    logger.info(f"  Created: {network_out}")
    
    # Convert demand to plans
    logger.info("Converting demand to MATSim plans...")
    plans_xml = build_matsim_plans_xml(demand_path, links)
    plans_out = output_dir / "plans.xml"
    plans_out.write_text(plans_xml, encoding="utf-8")
    logger.info(f"  Created: {plans_out}")
    
    # Create vehicles definition
    logger.info("Creating MATSim vehicles definition...")
    vehicles_xml = build_matsim_vehicles_xml()
    vehicles_out = output_dir / "vehicles.xml"
    vehicles_out.write_text(vehicles_xml, encoding="utf-8")
    logger.info(f"  Created: {vehicles_out}")
    
    # Create output directory for MATSim
    matsim_output = output_dir / "output"
    matsim_output.mkdir(exist_ok=True)
    
    # Create config
    logger.info("Creating MATSim config...")
    config_xml = build_matsim_config_xml(
        config,
        network_file="network.xml",
        plans_file="plans.xml",
        vehicles_file="vehicles.xml",
        output_dir="./output",
        random_seed=random_seed
    )
    config_out = output_dir / "config.xml"
    config_out.write_text(config_xml, encoding="utf-8")
    logger.info(f"  Created: {config_out}")
    
    logger.info(f"MATSim inputs ready at: {output_dir}")
    return config_out


def run_matsim(
    config_path: str | Path,
    timeout_s: int = 86400,
    java_heap_gb: int = 4
) -> Tuple[bool, float, Optional[str]]:
    """
    Run MATSim simulation.
    
    Args:
        config_path: Path to MATSim config file
        timeout_s: Maximum runtime in seconds
        java_heap_gb: Java heap size in GB
        
    Returns:
        Tuple of (success, runtime_seconds, error_message)
    """
    import time
    
    config_path = Path(config_path).resolve()
    
    # Check Java
    java_ok, java_version = check_java_available()
    if not java_ok:
        return False, 0.0, f"Java not available: {java_version}"
    
    logger.info(f"Java version: {java_version}")
    
    # Find MATSim JAR
    matsim_jar = find_matsim_jar()
    if matsim_jar is None:
        return False, 0.0, "MATSim JAR not found. Please install MATSim or set MATSIM_HOME"
    
    logger.info(f"Using MATSim: {matsim_jar}")
    
    # Build classpath including all dependencies in libs/ folder
    matsim_dir = matsim_jar.parent
    libs_dir = matsim_dir / "libs"
    
    # Build classpath by explicitly listing all JARs (wildcards don't work reliably with spaces in paths)
    classpath_parts = [str(matsim_jar)]
    if libs_dir.exists():
        # Add all JARs from libs directory
        for jar in libs_dir.glob("*.jar"):
            classpath_parts.append(str(jar))
    classpath = ":".join(classpath_parts)
    
    # Build command - use RunMatsim instead of Controler for MATSim 15+
    cmd = [
        "java",
        f"-Xmx{java_heap_gb}g",
        "-cp", classpath,
        "org.matsim.run.RunMatsim",
        str(config_path)
    ]
    
    logger.debug(f"Running: {' '.join(cmd)}")
    
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=config_path.parent
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            return True, elapsed, None
        else:
            error = result.stderr[:500] if result.stderr else f"Exit code {result.returncode}"
            return False, elapsed, error
            
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return False, elapsed, f"Timeout after {timeout_s}s"
    except Exception as e:
        elapsed = time.time() - start_time
        return False, elapsed, str(e)


def parse_matsim_output(output_dir: Path) -> dict:
    """
    Parse MATSim output to extract travel time statistics.
    
    Args:
        output_dir: Path to MATSim output directory
        
    Returns:
        Dictionary with travel time statistics
    """
    import gzip
    
    # Look for output_trips.csv.gz
    trips_file = output_dir / "output_trips.csv.gz"
    if not trips_file.exists():
        # Try uncompressed
        trips_file = output_dir / "output_trips.csv"
    
    if not trips_file.exists():
        logger.warning(f"No trips output found in {output_dir}")
        return {}
    
    travel_times = []
    
    try:
        if trips_file.suffix == ".gz":
            f = gzip.open(trips_file, "rt", encoding="utf-8")
        else:
            f = open(trips_file, "r", encoding="utf-8")
        
        with f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                # trav_time is in HH:MM:SS format
                trav_time_str = row.get("trav_time", "")
                if trav_time_str:
                    try:
                        parts = trav_time_str.split(":")
                        if len(parts) == 3:
                            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                            travel_times.append(h * 3600 + m * 60 + s)
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning(f"Failed to parse MATSim output: {e}")
        return {}
    
    if not travel_times:
        return {}
    
    import statistics
    travel_times_sorted = sorted(travel_times)
    p95_idx = int(len(travel_times_sorted) * 0.95)
    
    return {
        "trip_count": len(travel_times),
        "mean_travel_time_s": statistics.mean(travel_times),
        "median_travel_time_s": statistics.median(travel_times),
        "p95_travel_time_s": travel_times_sorted[p95_idx] if p95_idx < len(travel_times_sorted) else travel_times_sorted[-1],
        "min_travel_time_s": min(travel_times),
        "max_travel_time_s": max(travel_times),
    }


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MATSim Adapter")
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory")
    parser.add_argument("--iterations", type=int, default=0, help="MATSim iterations (0=single run)")
    parser.add_argument("--run", action="store_true", help="Also run the simulation")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--heap", type=int, default=4, help="Java heap size in GB")
    
    args = parser.parse_args()
    
    # Check Java
    java_ok, java_version = check_java_available()
    if java_ok:
        print(f"✓ Java available: {java_version}")
    else:
        print(f"⚠ Java not found - MATSim requires Java 11+")
    
    # Check MATSim
    matsim_jar = find_matsim_jar()
    if matsim_jar:
        print(f"✓ MATSim found: {matsim_jar}")
    else:
        print("⚠ MATSim JAR not found - set MATSIM_HOME or place matsim.jar in working directory")
    
    # Create config
    config = MATSimConfig(iterations=args.iterations)
    
    # Prepare inputs
    print(f"\nPreparing MATSim inputs...")
    config_path = prepare_matsim_inputs(args.scenario, args.output, config, args.seed)
    print(f"✓ MATSim config: {config_path}")
    
    # Optionally run
    if args.run:
        if not java_ok:
            print("\n✗ Cannot run without Java")
        elif not matsim_jar:
            print("\n✗ Cannot run without MATSim JAR")
        else:
            print("\nRunning MATSim...")
            success, runtime, error = run_matsim(config_path, java_heap_gb=args.heap)
            if success:
                print(f"✓ Completed in {runtime:.2f}s")
                
                # Parse output
                output_dir = Path(args.output) / "output"
                stats = parse_matsim_output(output_dir)
                if stats:
                    print(f"\nTravel Time Statistics:")
                    print(f"  Trips: {stats['trip_count']}")
                    print(f"  Mean: {stats['mean_travel_time_s']:.1f}s")
                    print(f"  P95: {stats['p95_travel_time_s']:.1f}s")
            else:
                print(f"✗ Failed: {error}")
