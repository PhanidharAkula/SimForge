#!/usr/bin/env python3
"""
Scenario Generation Pipeline for Large-Scale City Networks

Generates canonical scenario bundles for cities at various demand scales.
Supports NYC, LA, Chicago, and custom OSM extracts.

Usage:
    python -m pipeline.scenariobuilder.generate_city_scenario \
        --city nyc --tier 50k --output scenarios/nyc_tier50k

    python -m pipeline.scenariobuilder.generate_city_scenario \
        --city chicago --tier 500k --output scenarios/chicago_tier500k \
        --parallel 4

Time Estimates (M1 Mac / 8-core):
    City       | 50k     | 500k    | 5M
    -----------|---------|---------|--------
    NYC        | ~2-3 hr | ~4-6 hr | ~12-24 hr
    LA         | ~2-3 hr | ~4-6 hr | ~10-20 hr
    Chicago    | ~1.5-2h | ~3-5 hr | ~8-16 hr
"""

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# City Definitions
# =============================================================================

@dataclass
class CityDefinition:
    """Definition of a city for scenario generation."""
    name: str
    osm_bbox: tuple[float, float, float, float]  # (south, west, north, east)
    osm_url: Optional[str] = None  # Optional pre-downloaded OSM file URL
    estimated_links: int = 100000
    estimated_nodes: int = 50000
    time_zone: str = "America/Chicago"
    
    # Time estimates in minutes for each stage at 50k demand
    est_download_min: int = 10
    est_network_min: int = 45
    est_signals_min: int = 20
    est_demand_base_min: int = 30  # Base time for 50k
    est_routing_base_min: int = 20  # Base time for 50k
    est_validation_min: int = 10


CITY_DEFINITIONS = {
    "nyc": CityDefinition(
        name="New York City",
        osm_bbox=(40.4774, -74.2591, 40.9176, -73.7004),  # Greater NYC
        estimated_links=500000,
        estimated_nodes=250000,
        time_zone="America/New_York",
        est_download_min=15,
        est_network_min=60,
        est_signals_min=30,
        est_demand_base_min=45,
        est_routing_base_min=30,
        est_validation_min=15,
    ),
    "la": CityDefinition(
        name="Los Angeles",
        osm_bbox=(33.7037, -118.6682, 34.3373, -117.6462),  # LA Metro
        estimated_links=400000,
        estimated_nodes=200000,
        time_zone="America/Los_Angeles",
        est_download_min=12,
        est_network_min=50,
        est_signals_min=25,
        est_demand_base_min=40,
        est_routing_base_min=25,
        est_validation_min=12,
    ),
    "chicago": CityDefinition(
        name="Chicago",
        osm_bbox=(41.6445, -87.9401, 42.0230, -87.5241),  # Chicago Metro
        estimated_links=300000,
        estimated_nodes=150000,
        time_zone="America/Chicago",
        est_download_min=10,
        est_network_min=40,
        est_signals_min=20,
        est_demand_base_min=30,
        est_routing_base_min=20,
        est_validation_min=10,
    ),
    "austin": CityDefinition(
        name="Austin",
        osm_bbox=(30.1007, -97.9384, 30.5167, -97.5614),
        estimated_links=150000,
        estimated_nodes=75000,
        time_zone="America/Chicago",
        est_download_min=8,
        est_network_min=30,
        est_signals_min=15,
        est_demand_base_min=25,
        est_routing_base_min=15,
        est_validation_min=8,
    ),
    "berlin": CityDefinition(
        name="Berlin",
        osm_bbox=(52.3382, 13.0883, 52.6755, 13.7611),
        estimated_links=200000,
        estimated_nodes=100000,
        time_zone="Europe/Berlin",
        est_download_min=10,
        est_network_min=35,
        est_signals_min=18,
        est_demand_base_min=28,
        est_routing_base_min=18,
        est_validation_min=10,
    ),
}


DEMAND_TIERS = {
    "50k": 50000,
    "500k": 500000,
    "5m": 5000000,
}


# =============================================================================
# Time Estimation
# =============================================================================

def estimate_generation_time(city: CityDefinition, demand_count: int) -> dict:
    """
    Estimate time for each pipeline stage.
    
    Demand scales roughly O(n) for generation and O(n log n) for routing.
    """
    base_demand = 50000
    demand_factor = demand_count / base_demand
    
    # Demand generation scales linearly
    demand_time = city.est_demand_base_min * demand_factor
    
    # Routing scales O(n log n) approximately
    import math
    routing_factor = demand_factor * (1 + 0.2 * math.log10(max(demand_factor, 1)))
    routing_time = city.est_routing_base_min * routing_factor
    
    estimates = {
        "download": city.est_download_min,
        "network": city.est_network_min,
        "signals": city.est_signals_min,
        "demand": int(demand_time),
        "routing": int(routing_time),
        "validation": city.est_validation_min,
    }
    
    estimates["total"] = sum(estimates.values())
    return estimates


def format_time_estimate(minutes: int) -> str:
    """Format minutes as human-readable string."""
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours} hr"
    return f"{hours} hr {mins} min"


# =============================================================================
# Pipeline Stages
# =============================================================================

@dataclass
class StageResult:
    """Result of a pipeline stage."""
    stage: str
    success: bool
    duration_s: float
    output_path: Optional[Path] = None
    error: Optional[str] = None
    metrics: dict = field(default_factory=dict)


class ScenarioGenerator:
    """
    Multi-stage pipeline for generating canonical scenario bundles.
    """
    
    def __init__(
        self,
        city: CityDefinition,
        demand_count: int,
        output_dir: Path,
        parallel: int = 1,
        sumo_home: Optional[str] = None,
    ):
        self.city = city
        self.demand_count = demand_count
        self.output_dir = Path(output_dir)
        self.parallel = parallel
        self.sumo_home = sumo_home or os.environ.get("SUMO_HOME", "/opt/homebrew/share/sumo")
        
        # Working directories
        self.work_dir = self.output_dir / ".work"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        self.results: list[StageResult] = []
    
    def run_all(self) -> bool:
        """Run all pipeline stages."""
        stages = [
            ("download", self.stage_download_osm),
            ("network", self.stage_extract_network),
            ("signals", self.stage_infer_signals),
            ("demand", self.stage_generate_demand),
            ("routing", self.stage_route_assignment),
            ("canonical", self.stage_create_canonical),
            ("validation", self.stage_validate),
        ]
        
        logger.info(f"=" * 60)
        logger.info(f"Generating scenario: {self.city.name} @ {self.demand_count:,} trips")
        logger.info(f"Output: {self.output_dir}")
        logger.info(f"=" * 60)
        
        # Print time estimates
        estimates = estimate_generation_time(self.city, self.demand_count)
        logger.info(f"Estimated time: {format_time_estimate(estimates['total'])}")
        logger.info(f"  Download:   {format_time_estimate(estimates['download'])}")
        logger.info(f"  Network:    {format_time_estimate(estimates['network'])}")
        logger.info(f"  Signals:    {format_time_estimate(estimates['signals'])}")
        logger.info(f"  Demand:     {format_time_estimate(estimates['demand'])}")
        logger.info(f"  Routing:    {format_time_estimate(estimates['routing'])}")
        logger.info(f"  Validation: {format_time_estimate(estimates['validation'])}")
        logger.info(f"=" * 60)
        
        start_time = time.time()
        
        for stage_name, stage_func in stages:
            logger.info(f"\n>>> Stage: {stage_name.upper()}")
            stage_start = time.time()
            
            try:
                result = stage_func()
                result.duration_s = time.time() - stage_start
                self.results.append(result)
                
                if result.success:
                    logger.info(f"✓ {stage_name} completed in {result.duration_s:.1f}s")
                else:
                    logger.error(f"✗ {stage_name} failed: {result.error}")
                    return False
                    
            except Exception as e:
                logger.exception(f"✗ {stage_name} raised exception")
                self.results.append(StageResult(
                    stage=stage_name,
                    success=False,
                    duration_s=time.time() - stage_start,
                    error=str(e)
                ))
                return False
        
        total_time = time.time() - start_time
        logger.info(f"\n{'=' * 60}")
        logger.info(f"✓ Scenario generation complete!")
        logger.info(f"  Total time: {total_time:.1f}s ({format_time_estimate(int(total_time / 60))})")
        logger.info(f"  Output: {self.output_dir}")
        logger.info(f"{'=' * 60}")
        
        return True
    
    # -------------------------------------------------------------------------
    # Stage 1: Download OSM
    # -------------------------------------------------------------------------
    
    def stage_download_osm(self) -> StageResult:
        """Download OSM data for the city bounding box."""
        osm_file = self.work_dir / "city.osm"
        
        if osm_file.exists():
            logger.info(f"  Using cached OSM file: {osm_file}")
            return StageResult(
                stage="download",
                success=True,
                duration_s=0,
                output_path=osm_file,
                metrics={"cached": True}
            )
        
        south, west, north, east = self.city.osm_bbox
        
        # Use Overpass API
        overpass_url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:xml][timeout:1800];
        (
          way["highway"]({south},{west},{north},{east});
          node(w);
        );
        out body;
        """
        
        logger.info(f"  Downloading OSM data for bbox: {self.city.osm_bbox}")
        logger.info(f"  This may take 10-20 minutes for large cities...")
        
        try:
            import urllib.request
            import urllib.parse
            
            data = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(overpass_url, data=data)
            req.add_header("User-Agent", "SimForge/1.0")
            
            with urllib.request.urlopen(req, timeout=1800) as response:
                with open(osm_file, 'wb') as f:
                    f.write(response.read())
            
            size_mb = osm_file.stat().st_size / (1024 * 1024)
            logger.info(f"  Downloaded {size_mb:.1f} MB")
            
            return StageResult(
                stage="download",
                success=True,
                duration_s=0,
                output_path=osm_file,
                metrics={"size_mb": size_mb}
            )
            
        except Exception as e:
            return StageResult(
                stage="download",
                success=False,
                duration_s=0,
                error=str(e)
            )
    
    # -------------------------------------------------------------------------
    # Stage 2: Extract Network
    # -------------------------------------------------------------------------
    
    def stage_extract_network(self) -> StageResult:
        """Convert OSM to SUMO network and then to canonical format."""
        osm_file = self.work_dir / "city.osm"
        sumo_net = self.work_dir / "city.net.xml"
        canonical_net = self.work_dir / "network.xml"
        
        if not osm_file.exists():
            return StageResult(
                stage="network",
                success=False,
                duration_s=0,
                error="OSM file not found"
            )
        
        # Step 1: netconvert OSM -> SUMO
        logger.info("  Converting OSM to SUMO network...")
        netconvert = Path(self.sumo_home) / "bin" / "netconvert"
        if not netconvert.exists():
            netconvert = Path("/opt/homebrew/bin/netconvert")
        
        cmd = [
            str(netconvert),
            "--osm-files", str(osm_file),
            "--output-file", str(sumo_net),
            "--geometry.remove",
            "--ramps.guess",
            "--junctions.join",
            "--tls.guess-signals",
            "--tls.default-type", "actuated",
            "--remove-edges.isolated",
            "--no-turnarounds",
            "--junctions.corner-detail", "0",
            "--output.street-names",
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return StageResult(
                stage="network",
                success=False,
                duration_s=0,
                error=f"netconvert failed: {result.stderr[:500]}"
            )
        
        # Step 2: Convert SUMO network to canonical format
        logger.info("  Converting to canonical network format...")
        node_count, link_count = self._sumo_net_to_canonical(sumo_net, canonical_net)
        
        return StageResult(
            stage="network",
            success=True,
            duration_s=0,
            output_path=canonical_net,
            metrics={"nodes": node_count, "links": link_count}
        )
    
    def _sumo_net_to_canonical(self, sumo_net: Path, output: Path) -> tuple[int, int]:
        """Convert SUMO net.xml to canonical network.xml."""
        tree = ET.parse(sumo_net)
        root = tree.getroot()
        
        # Create canonical network
        network = ET.Element("network")
        network.set("version", "0.1")
        
        nodes_elem = ET.SubElement(network, "nodes")
        links_elem = ET.SubElement(network, "links")
        
        # Extract junctions -> nodes
        node_count = 0
        for junction in root.findall(".//junction"):
            if junction.get("type") == "internal":
                continue
            
            node = ET.SubElement(nodes_elem, "node")
            node.set("id", junction.get("id"))
            node.set("x", junction.get("x"))
            node.set("y", junction.get("y"))
            node.set("type", junction.get("type", "priority"))
            node_count += 1
        
        # Extract edges -> links
        link_count = 0
        for edge in root.findall(".//edge"):
            if edge.get("function") == "internal":
                continue
            
            edge_id = edge.get("id")
            from_node = edge.get("from")
            to_node = edge.get("to")
            
            # Get lane info
            lanes = edge.findall("lane")
            if not lanes:
                continue
            
            # Use first lane for attributes
            lane = lanes[0]
            
            link = ET.SubElement(links_elem, "link")
            link.set("id", edge_id)
            link.set("from", from_node)
            link.set("to", to_node)
            link.set("length", lane.get("length", "100"))
            link.set("speed", lane.get("speed", "13.89"))
            link.set("lanes", str(len(lanes)))
            link.set("capacity", str(int(len(lanes) * 1800)))  # 1800 veh/hr/lane
            link_count += 1
        
        # Write output
        tree = ET.ElementTree(network)
        ET.indent(tree, space="  ")
        tree.write(output, encoding="utf-8", xml_declaration=True)
        
        return node_count, link_count
    
    # -------------------------------------------------------------------------
    # Stage 3: Infer Signals
    # -------------------------------------------------------------------------
    
    def stage_infer_signals(self) -> StageResult:
        """Extract traffic signal timing from SUMO network."""
        sumo_net = self.work_dir / "city.net.xml"
        signals_file = self.work_dir / "signals.xml"
        
        if not sumo_net.exists():
            return StageResult(
                stage="signals",
                success=False,
                duration_s=0,
                error="SUMO network not found"
            )
        
        logger.info("  Extracting signal timing from network...")
        
        tree = ET.parse(sumo_net)
        root = tree.getroot()
        
        signals = ET.Element("signals")
        signals.set("version", "0.1")
        
        signal_count = 0
        for tl in root.findall(".//tlLogic"):
            controller = ET.SubElement(signals, "controller")
            controller.set("id", tl.get("id"))
            controller.set("type", tl.get("type", "static"))
            controller.set("offset", tl.get("offset", "0"))
            
            for phase in tl.findall("phase"):
                phase_elem = ET.SubElement(controller, "phase")
                phase_elem.set("duration", phase.get("duration"))
                phase_elem.set("state", phase.get("state"))
            
            signal_count += 1
        
        tree = ET.ElementTree(signals)
        ET.indent(tree, space="  ")
        tree.write(signals_file, encoding="utf-8", xml_declaration=True)
        
        return StageResult(
            stage="signals",
            success=True,
            duration_s=0,
            output_path=signals_file,
            metrics={"signal_count": signal_count}
        )
    
    # -------------------------------------------------------------------------
    # Stage 4: Generate Demand
    # -------------------------------------------------------------------------
    
    def stage_generate_demand(self) -> StageResult:
        """Generate synthetic OD demand."""
        network_file = self.work_dir / "network.xml"
        demand_file = self.work_dir / "demand.csv"
        
        if not network_file.exists():
            return StageResult(
                stage="demand",
                success=False,
                duration_s=0,
                error="Network file not found"
            )
        
        logger.info(f"  Generating {self.demand_count:,} OD trips...")
        
        # Parse network nodes
        tree = ET.parse(network_file)
        nodes = [n.get("id") for n in tree.findall(".//node")]
        
        if len(nodes) < 2:
            return StageResult(
                stage="demand",
                success=False,
                duration_s=0,
                error="Network has insufficient nodes"
            )
        
        import random
        random.seed(42)  # Reproducible
        
        # Generate trips with realistic departure time distribution
        # Peak hours: 7-9 AM (25%), 4-7 PM (30%), off-peak (45%)
        def sample_departure_time() -> float:
            r = random.random()
            if r < 0.25:  # Morning peak
                return random.uniform(7 * 3600, 9 * 3600)
            elif r < 0.55:  # Evening peak
                return random.uniform(16 * 3600, 19 * 3600)
            else:  # Off-peak
                return random.uniform(0, 24 * 3600)
        
        logger.info(f"  Writing demand to {demand_file}...")
        
        batch_size = 100000
        trips_written = 0
        
        with open(demand_file, 'w') as f:
            f.write("trip_id,origin,destination,departure_time,mode\n")
            
            while trips_written < self.demand_count:
                batch = min(batch_size, self.demand_count - trips_written)
                
                for i in range(batch):
                    trip_id = f"trip_{trips_written + i}"
                    origin = random.choice(nodes)
                    destination = random.choice(nodes)
                    while destination == origin:
                        destination = random.choice(nodes)
                    
                    departure = sample_departure_time()
                    
                    f.write(f"{trip_id},{origin},{destination},{departure:.1f},car\n")
                
                trips_written += batch
                if trips_written % 500000 == 0:
                    logger.info(f"    Written {trips_written:,} / {self.demand_count:,} trips")
        
        return StageResult(
            stage="demand",
            success=True,
            duration_s=0,
            output_path=demand_file,
            metrics={"trip_count": self.demand_count}
        )
    
    # -------------------------------------------------------------------------
    # Stage 5: Route Assignment
    # -------------------------------------------------------------------------
    
    def stage_route_assignment(self) -> StageResult:
        """
        Perform route assignment using SUMO's duaIterate.
        
        For large demand, this can be very slow. Consider:
        - Using --threads for parallel routing
        - Reducing iterations (--max-iterations)
        - Using mesoscopic assignment
        """
        sumo_net = self.work_dir / "city.net.xml"
        demand_file = self.work_dir / "demand.csv"
        routes_file = self.work_dir / "routes.rou.xml"
        
        logger.info("  Generating routes (this may take a while)...")
        logger.info(f"  Demand: {self.demand_count:,} trips")
        
        # First convert demand.csv to SUMO trips format
        trips_file = self.work_dir / "trips.trips.xml"
        self._csv_to_sumo_trips(demand_file, trips_file)
        
        # Use duarouter for route assignment
        duarouter = Path(self.sumo_home) / "bin" / "duarouter"
        if not duarouter.exists():
            duarouter = Path("/opt/homebrew/bin/duarouter")
        
        cmd = [
            str(duarouter),
            "--net-file", str(sumo_net),
            "--trip-files", str(trips_file),
            "--output-file", str(routes_file),
            "--ignore-errors",
            "--routing-threads", str(self.parallel),
            "--routing-algorithm", "astar",
        ]
        
        logger.info(f"  Running duarouter with {self.parallel} threads...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        
        if result.returncode != 0:
            # duarouter often returns warnings, check if output exists
            if routes_file.exists():
                logger.warning(f"  duarouter completed with warnings")
            else:
                return StageResult(
                    stage="routing",
                    success=False,
                    duration_s=0,
                    error=f"duarouter failed: {result.stderr[:500]}"
                )
        
        # Count routes generated
        route_count = 0
        if routes_file.exists():
            with open(routes_file) as f:
                for line in f:
                    if "<vehicle" in line or "<trip" in line:
                        route_count += 1
        
        return StageResult(
            stage="routing",
            success=True,
            duration_s=0,
            output_path=routes_file,
            metrics={"routes": route_count}
        )
    
    def _csv_to_sumo_trips(self, csv_file: Path, output: Path):
        """Convert demand.csv to SUMO trips XML."""
        trips = ET.Element("routes")
        
        with open(csv_file) as f:
            next(f)  # Skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                
                trip_id, origin, dest, depart = parts[:4]
                
                trip = ET.SubElement(trips, "trip")
                trip.set("id", trip_id)
                trip.set("depart", str(float(depart)))
                trip.set("from", origin)
                trip.set("to", dest)
        
        tree = ET.ElementTree(trips)
        tree.write(output, encoding="utf-8", xml_declaration=True)
    
    # -------------------------------------------------------------------------
    # Stage 6: Create Canonical Bundle
    # -------------------------------------------------------------------------
    
    def stage_create_canonical(self) -> StageResult:
        """Assemble final canonical bundle."""
        logger.info("  Assembling canonical bundle...")
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy files to output
        import shutil
        
        files_to_copy = [
            ("network.xml", "network.xml"),
            ("signals.xml", "signals.xml"),
            ("demand.csv", "demand.csv"),
        ]
        
        for src_name, dst_name in files_to_copy:
            src = self.work_dir / src_name
            dst = self.output_dir / dst_name
            if src.exists():
                shutil.copy(src, dst)
        
        # Create config.xml
        self._create_config()
        
        # Create manifest.xml
        self._create_manifest()
        
        return StageResult(
            stage="canonical",
            success=True,
            duration_s=0,
            output_path=self.output_dir,
            metrics={}
        )
    
    def _create_config(self):
        """Create config.xml for the scenario."""
        tier_name = f"{self.demand_count // 1000}k" if self.demand_count < 1000000 else f"{self.demand_count // 1000000}m"
        scenario_id = f"{self.city.name.lower().replace(' ', '_')}_tier{tier_name}"
        
        config = ET.Element("config")
        config.set("version", "0.1")
        
        scenario = ET.SubElement(config, "scenario")
        scenario.set("id", scenario_id)
        scenario.set("name", f"{self.city.name} {tier_name.upper()} Demand")
        
        sim = ET.SubElement(config, "simulation")
        sim.set("start_time", "0")
        sim.set("end_time", "86400")  # 24 hours
        sim.set("time_step", "1.0")
        
        meta = ET.SubElement(config, "metadata")
        meta.set("created", datetime.now().isoformat())
        meta.set("generator", "SimForge/generate_city_scenario")
        meta.set("city", self.city.name)
        meta.set("demand_count", str(self.demand_count))
        
        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")
        tree.write(self.output_dir / "config.xml", encoding="utf-8", xml_declaration=True)
    
    def _create_manifest(self):
        """Create manifest.xml with file hashes."""
        manifest = ET.Element("manifest")
        manifest.set("version", "0.1")
        
        files_elem = ET.SubElement(manifest, "files")
        
        for filename in ["network.xml", "demand.csv", "signals.xml", "config.xml"]:
            filepath = self.output_dir / filename
            if not filepath.exists():
                continue
            
            # Compute SHA-256
            sha256 = hashlib.sha256()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            
            file_elem = ET.SubElement(files_elem, "file")
            file_elem.set("name", filename)
            file_elem.set("sha256", sha256.hexdigest())
            file_elem.set("size", str(filepath.stat().st_size))
        
        tree = ET.ElementTree(manifest)
        ET.indent(tree, space="  ")
        tree.write(self.output_dir / "manifest.xml", encoding="utf-8", xml_declaration=True)
    
    # -------------------------------------------------------------------------
    # Stage 7: Validation
    # -------------------------------------------------------------------------
    
    def stage_validate(self) -> StageResult:
        """Validate the generated scenario bundle."""
        logger.info("  Validating canonical bundle...")
        
        # Check required files exist
        required = ["network.xml", "demand.csv", "signals.xml", "config.xml", "manifest.xml"]
        missing = [f for f in required if not (self.output_dir / f).exists()]
        
        if missing:
            return StageResult(
                stage="validation",
                success=False,
                duration_s=0,
                error=f"Missing files: {missing}"
            )
        
        # Verify manifest hashes
        manifest_tree = ET.parse(self.output_dir / "manifest.xml")
        for file_elem in manifest_tree.findall(".//file"):
            filename = file_elem.get("name")
            expected_hash = file_elem.get("sha256")
            
            filepath = self.output_dir / filename
            if not filepath.exists():
                continue
            
            sha256 = hashlib.sha256()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            
            actual_hash = sha256.hexdigest()
            if actual_hash != expected_hash:
                return StageResult(
                    stage="validation",
                    success=False,
                    duration_s=0,
                    error=f"Hash mismatch for {filename}"
                )
        
        logger.info("  ✓ All files present")
        logger.info("  ✓ All hashes verified")
        
        return StageResult(
            stage="validation",
            success=True,
            duration_s=0,
            output_path=self.output_dir,
            metrics={"files_validated": len(required)}
        )


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate canonical scenario bundles for cities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate NYC at 50k demand
    python -m pipeline.scenariobuilder.generate_city_scenario \\
        --city nyc --tier 50k --output scenarios/nyc_tier50k
    
    # Generate all tiers for Chicago
    python -m pipeline.scenariobuilder.generate_city_scenario \\
        --city chicago --tier all --output scenarios/chicago
    
    # Estimate time only
    python -m pipeline.scenariobuilder.generate_city_scenario \\
        --city la --tier 5m --estimate-only

Time Estimates (approximate):
    City       | 50k     | 500k    | 5M
    -----------|---------|---------|--------
    NYC        | ~2-3 hr | ~4-6 hr | ~12-24 hr
    LA         | ~2-3 hr | ~4-6 hr | ~10-20 hr
    Chicago    | ~1.5-2h | ~3-5 hr | ~8-16 hr
        """
    )
    
    parser.add_argument("--city", required=True, choices=list(CITY_DEFINITIONS.keys()),
                        help="City to generate")
    parser.add_argument("--tier", required=True, choices=list(DEMAND_TIERS.keys()) + ["all"],
                        help="Demand tier (50k, 500k, 5m, or all)")
    parser.add_argument("--output", required=True, type=Path,
                        help="Output directory")
    parser.add_argument("--parallel", type=int, default=4,
                        help="Number of parallel threads for routing")
    parser.add_argument("--estimate-only", action="store_true",
                        help="Only print time estimates, don't generate")
    parser.add_argument("--sumo-home", type=str,
                        help="Path to SUMO installation")
    
    args = parser.parse_args()
    
    city = CITY_DEFINITIONS[args.city]
    
    # Determine tiers to generate
    if args.tier == "all":
        tiers = list(DEMAND_TIERS.items())
    else:
        tiers = [(args.tier, DEMAND_TIERS[args.tier])]
    
    # Print estimates
    print(f"\n{'=' * 60}")
    print(f"City: {city.name}")
    print(f"Estimated network: ~{city.estimated_links:,} links, ~{city.estimated_nodes:,} nodes")
    print(f"{'=' * 60}")
    
    total_time = 0
    for tier_name, demand_count in tiers:
        estimates = estimate_generation_time(city, demand_count)
        print(f"\nTier {tier_name.upper()} ({demand_count:,} trips):")
        print(f"  Download:   {format_time_estimate(estimates['download'])}")
        print(f"  Network:    {format_time_estimate(estimates['network'])}")
        print(f"  Signals:    {format_time_estimate(estimates['signals'])}")
        print(f"  Demand:     {format_time_estimate(estimates['demand'])}")
        print(f"  Routing:    {format_time_estimate(estimates['routing'])}")
        print(f"  Validation: {format_time_estimate(estimates['validation'])}")
        print(f"  TOTAL:      {format_time_estimate(estimates['total'])}")
        total_time += estimates['total']
    
    if len(tiers) > 1:
        print(f"\n{'=' * 60}")
        print(f"Total for all tiers: {format_time_estimate(total_time)}")
    
    if args.estimate_only:
        print(f"\n(--estimate-only flag set, not generating)")
        return
    
    print(f"\n{'=' * 60}")
    print(f"Starting generation...")
    print(f"{'=' * 60}\n")
    
    # Generate each tier
    for tier_name, demand_count in tiers:
        if args.tier == "all":
            output_dir = args.output / f"tier{tier_name}"
        else:
            output_dir = args.output
        
        generator = ScenarioGenerator(
            city=city,
            demand_count=demand_count,
            output_dir=output_dir,
            parallel=args.parallel,
            sumo_home=args.sumo_home,
        )
        
        success = generator.run_all()
        
        if not success:
            logger.error(f"Failed to generate {tier_name} tier")
            sys.exit(1)
    
    print(f"\n✓ All scenarios generated successfully!")


if __name__ == "__main__":
    main()
