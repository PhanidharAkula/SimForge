"""
Build canonical network.xml from OpenStreetMap data.

This module downloads and processes OSM data for a given bounding box,
extracting road network topology and converting it to the canonical schema.

Usage:
    python -m pipeline.network.build_network_from_osm \
        --bbox "north,south,east,west" \
        --output scenarios/city1_tier50k/network.xml

Dependencies:
    - osmnx: For downloading and processing OSM data
    - networkx: Graph operations (included with osmnx)
    - lxml: XML generation
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

from lxml import etree

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """Geographic bounding box for area of interest."""
    north: float  # Max latitude
    south: float  # Min latitude
    east: float   # Max longitude
    west: float   # Min longitude
    
    def __post_init__(self):
        if self.north <= self.south:
            raise ValueError(f"North ({self.north}) must be > South ({self.south})")
        if self.east <= self.west:
            raise ValueError(f"East ({self.east}) must be > West ({self.west})")
    
    @classmethod
    def from_string(cls, bbox_str: str) -> "BoundingBox":
        """Parse 'north,south,east,west' string."""
        parts = [float(x.strip()) for x in bbox_str.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Expected 4 values (n,s,e,w), got {len(parts)}")
        return cls(north=parts[0], south=parts[1], east=parts[2], west=parts[3])
    
    @classmethod
    def from_center(cls, lat: float, lon: float, radius_km: float) -> "BoundingBox":
        """Create bounding box from center point and radius in km."""
        # Approximate: 1 degree latitude ≈ 111 km
        # Longitude varies with latitude
        import math
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
        return cls(
            north=lat + lat_delta,
            south=lat - lat_delta,
            east=lon + lon_delta,
            west=lon - lon_delta
        )


@dataclass
class CanonicalNode:
    """A node in the canonical network schema."""
    id: str
    x: float  # Longitude or projected X
    y: float  # Latitude or projected Y
    osm_id: Optional[int] = None
    node_type: str = "intersection"  # intersection, dead_end, etc.


@dataclass
class CanonicalLink:
    """A link (edge) in the canonical network schema."""
    id: str
    from_node: str
    to_node: str
    length_m: float
    lanes: int = 1
    speed_limit_mps: float = 13.9  # ~50 km/h default
    highway_type: str = "residential"
    osm_way_id: Optional[int] = None
    name: Optional[str] = None


#  {"service", 25}, {"residential", 25}, {"primary", 35},
#         {"secondary", 35}, {"tertiary", 25}, {"motorway_link", 45},
#         {"motorway", 65}, {"trunk", 55}, {"primary_link", 45},
#         {"trunk_link", 45}, {"secondary_link", 25}, {"tertiary_link", 25},
#         {"unclassified", 10}};

# Default speed limits by OSM highway type (m/s)
DEFAULT_SPEEDS_MPS = {
    "motorway": 33.3,       # 120 km/h
    "motorway_link": 22.2,  # 80 km/h
    "trunk": 27.8,          # 100 km/h
    "trunk_link": 19.4,     # 70 km/h
    "primary": 22.2,        # 80 km/h
    "primary_link": 16.7,   # 60 km/h
    "secondary": 16.7,      # 60 km/h
    "secondary_link": 13.9, # 50 km/h
    "tertiary": 13.9,       # 50 km/h
    "tertiary_link": 11.1,  # 40 km/h
    "residential": 11.1,    # 40 km/h
    "living_street": 5.6,   # 20 km/h
    "unclassified": 11.1,   # 40 km/h
    "service": 8.3,         # 30 km/h
}

# Default lane counts by OSM highway type
DEFAULT_LANES = {
    "motorway": 3,
    "motorway_link": 1,
    "trunk": 2,
    "trunk_link": 1,
    "primary": 2,
    "primary_link": 1,
    "secondary": 2,
    "secondary_link": 1,
    "tertiary": 1,
    "tertiary_link": 1,
    "residential": 1,
    "living_street": 1,
    "unclassified": 1,
    "service": 1,
}


_OSM_CACHE_CONFIGURED = False


def _configure_osmnx_cache():
    """
    Point osmnx's built-in HTTP cache at a project-local directory.

    Overpass responses are large (tens of MB for a city) and the same bbox is
    often fetched multiple times during development, stress-testing, and CI.
    Pinning the cache folder to ``<repo>/cache/osm`` makes hits deterministic
    across machines and lets us warn the user about slow first-time downloads
    with a concrete path to inspect afterwards.
    """
    global _OSM_CACHE_CONFIGURED
    if _OSM_CACHE_CONFIGURED:
        return
    try:
        import osmnx as ox
    except ImportError:
        return

    repo_root = Path(__file__).resolve().parents[2]
    cache_dir = repo_root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cache_dir)
    # Give one clear, slow-path message rather than osmnx's multi-line logs.
    ox.settings.log_console = False
    # City-scale bboxes (e.g. NYC 20km radius ≈ 1,950 km²) blow past osmnx's
    # 50 km² default and get split into tens of thousands of Overpass sub-queries,
    # which the public endpoint will not service in any reasonable time.
    ox.settings.max_query_area_size = 2_500_000_000
    _OSM_CACHE_CONFIGURED = True


def _cache_files_for_bbox(bbox: BoundingBox) -> list[Path]:
    """Best-effort check: look for any cached osmnx responses that match bbox."""
    import hashlib
    import json as _json

    repo_root = Path(__file__).resolve().parents[2]
    cache_dir = repo_root / "cache"
    if not cache_dir.is_dir():
        return []

    # osmnx's cache keys are the SHA1 of the normalised request body, so we
    # can't recover a bbox from disk. We simply report presence/absence of any
    # cached files so the user knows whether this run will hit the network.
    _ = (hashlib, _json, bbox)
    return list(cache_dir.glob("*.json"))


def download_osm_network(bbox: BoundingBox, network_type: str = "drive") -> "networkx.MultiDiGraph":
    """
    Download road network from OSM using osmnx.

    Uses osmnx's built-in HTTP cache (pinned to ``<repo>/cache/osm`` via
    :func:`_configure_osmnx_cache`). A first-time download for a ~1km urban bbox
    takes roughly 10-30s; a cached fetch is typically <1s. We log both the
    cache location and the elapsed time so users can tell which path ran.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise ImportError(
            "osmnx is required for OSM network building. "
            "Install with: pip install osmnx"
        ) from exc

    _configure_osmnx_cache()
    cache_dir = Path(ox.settings.cache_folder)
    existing_cache = _cache_files_for_bbox(bbox)

    logger.info("Downloading OSM network for bbox: %s", bbox)
    if not existing_cache:
        logger.warning(
            "OSM cache at %s is empty — first-time fetch contacts the Overpass API "
            "and may take 10s-2min depending on bbox size and network latency. "
            "Subsequent runs with the same bbox will be served from this cache.",
            cache_dir,
        )
    else:
        logger.info(
            "OSM cache has %d prior responses at %s; this fetch will reuse cached "
            "data if the bbox matches.",
            len(existing_cache), cache_dir,
        )

    import time as _time
    t0 = _time.time()

    # osmnx 2.x expects bbox as (left, bottom, right, top) = (west, south, east, north)
    try:
        G = ox.graph_from_bbox(
            bbox=(bbox.west, bbox.south, bbox.east, bbox.north),
            network_type=network_type,
            simplify=True,
            truncate_by_edge=True
        )
    except Exception as e:
        error_type = type(e).__name__
        raise RuntimeError(
            f"Failed to download OSM network data: {error_type}: {e}\n"
            f"  Bbox: north={bbox.north}, south={bbox.south}, east={bbox.east}, west={bbox.west}\n"
            f"  Cache dir: {cache_dir}\n"
            f"  Possible causes:\n"
            f"    - No internet connection\n"
            f"    - OSM Overpass API is down or rate-limited (wait and retry)\n"
            f"    - Bounding box covers an area with no roads (ocean, desert)\n"
            f"    - Bounding box coordinates are swapped or invalid"
        ) from e

    if G.number_of_nodes() == 0:
        raise ValueError(
            f"OSM returned an empty road network (0 nodes) for the given bounding box.\n"
            f"  Bbox: north={bbox.north}, south={bbox.south}, east={bbox.east}, west={bbox.west}\n"
            f"  This usually means the area has no roads (ocean, park, desert).\n"
            f"  Try a different center point or larger radius."
        )

    elapsed = _time.time() - t0
    cache_hit = elapsed < 2.0 and bool(existing_cache)
    logger.info(
        "Downloaded network: %d nodes, %d edges  (%.1fs, %s)",
        G.number_of_nodes(),
        G.number_of_edges(),
        elapsed,
        "cache hit" if cache_hit else "fresh fetch",
    )
    return G


def extract_canonical_network(
    G: "networkx.MultiDiGraph",
    crs: str = "EPSG:4326"
) -> tuple[list[CanonicalNode], list[CanonicalLink]]:
    """
    Extract canonical nodes and links from OSM graph.
    
    Args:
        G: OSM network graph from osmnx
        crs: Coordinate reference system
    
    Returns:
        Tuple of (nodes, links)
    """
    _ = crs  # reserved for future CRS projection support
    
    nodes = []
    links = []
    
    # Build node mapping: OSM ID -> canonical ID
    osm_to_canonical = {}
    
    # Extract nodes
    for i, (osm_id, data) in enumerate(sorted(G.nodes(data=True))):
        canonical_id = f"n{i}"
        osm_to_canonical[osm_id] = canonical_id
        
        # Determine node type based on degree
        in_deg = G.in_degree(osm_id)
        out_deg = G.out_degree(osm_id)
        
        if in_deg + out_deg <= 2:
            node_type = "dead_end"
        elif in_deg + out_deg >= 6:
            node_type = "major_intersection"
        else:
            node_type = "intersection"
        
        nodes.append(CanonicalNode(
            id=canonical_id,
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            osm_id=osm_id,
            node_type=node_type
        ))
    
    # Extract links (edges)
    link_counter = 0
    seen_edges = set()
    
    for u, v, key, data in sorted(G.edges(keys=True, data=True)):
        # Create unique edge identifier
        edge_id = (u, v, key)
        if edge_id in seen_edges:
            continue
        seen_edges.add(edge_id)
        
        from_node = osm_to_canonical[u]
        to_node = osm_to_canonical[v]
        
        # Get highway type
        highway = data.get("highway", "residential")
        if isinstance(highway, list):
            highway = highway[0]
        
        # Get length
        length_m = data.get("length", 100.0)
        
        # Get speed limit
        maxspeed = data.get("maxspeed")
        if maxspeed:
            try:
                if isinstance(maxspeed, list):
                    maxspeed = maxspeed[0]
                # Parse "50" or "50 mph" or "50 km/h"
                speed_str = str(maxspeed).lower().replace("mph", "").replace("km/h", "").strip()
                speed_kmh = float(speed_str)
                if "mph" in str(maxspeed).lower():
                    speed_mps = speed_kmh * 0.44704  # mph to m/s
                else:
                    speed_mps = speed_kmh / 3.6  # km/h to m/s
            except (ValueError, TypeError):
                speed_mps = DEFAULT_SPEEDS_MPS.get(highway, 13.9)
        else:
            speed_mps = DEFAULT_SPEEDS_MPS.get(highway, 13.9)
        
        # Get lanes
        lanes = data.get("lanes")
        if lanes:
            try:
                if isinstance(lanes, list):
                    lanes = lanes[0]
                lanes = int(lanes)
            except (ValueError, TypeError):
                lanes = DEFAULT_LANES.get(highway, 1)
        else:
            lanes = DEFAULT_LANES.get(highway, 1)
        
        # Get name
        name = data.get("name")
        if isinstance(name, list):
            name = name[0]
        
        links.append(CanonicalLink(
            id=f"l{link_counter}",
            from_node=from_node,
            to_node=to_node,
            length_m=length_m,
            lanes=lanes,
            speed_limit_mps=round(speed_mps, 1),
            highway_type=highway,
            osm_way_id=data.get("osmid"),
            name=name
        ))
        link_counter += 1
    
    logger.info("Extracted %d nodes, %d links", len(nodes), len(links))
    return nodes, links


def build_network_xml(
    nodes: list[CanonicalNode],
    links: list[CanonicalLink],
    crs: str = "EPSG:4326",
    units_length: str = "meters",
    units_speed: str = "m/s"
) -> etree.Element:
    """
    Build canonical network.xml from extracted nodes and links.
    
    Args:
        nodes: List of canonical nodes
        links: List of canonical links
        crs: Coordinate reference system string
        units_length: Length unit string
        units_speed: Speed unit string
    
    Returns:
        lxml Element tree root
    """
    root = etree.Element("network")
    
    # Add metadata element (required per schema)
    metadata = etree.SubElement(root, "metadata")
    metadata.set("crs", crs)
    metadata.set("units_length", units_length)
    metadata.set("units_speed", units_speed)
    metadata.set("source", "OSM")
    
    # Add nodes
    nodes_elem = etree.SubElement(root, "nodes")
    for node in sorted(nodes, key=lambda n: n.id):
        node_elem = etree.SubElement(nodes_elem, "node")
        node_elem.set("id", node.id)
        node_elem.set("x", str(node.x))
        node_elem.set("y", str(node.y))
        node_elem.set("type", node.node_type)
        if node.osm_id:
            node_elem.set("osm_id", str(node.osm_id))
    
    # Add links
    links_elem = etree.SubElement(root, "links")
    for link in sorted(links, key=lambda l: l.id):
        link_elem = etree.SubElement(links_elem, "link")
        link_elem.set("id", link.id)
        link_elem.set("from", link.from_node)
        link_elem.set("to", link.to_node)
        link_elem.set("length", str(round(link.length_m, 2)))
        link_elem.set("lanes", str(link.lanes))
        link_elem.set("speed_limit", str(link.speed_limit_mps))
        link_elem.set("highway_type", link.highway_type)
        if link.osm_way_id:
            link_elem.set("osm_way_id", str(link.osm_way_id))
        if link.name:
            link_elem.set("name", link.name)
    
    return root


def build_network_from_osm(
    bbox: BoundingBox,
    output_path: Path,
    network_type: str = "drive",
    crs: str = "EPSG:4326"
) -> dict:
    """
    Main entry point: download OSM and build canonical network.xml.
    
    Args:
        bbox: Geographic bounding box
        output_path: Path to write network.xml
        network_type: OSM network type
        crs: Coordinate reference system
    
    Returns:
        Summary dict with node_count, link_count, etc.
    """
    # Download
    G = download_osm_network(bbox, network_type)
    
    # Extract
    nodes, links = extract_canonical_network(G, crs)
    
    # Build XML
    root = build_network_xml(nodes, links, crs)
    
    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(str(output_path), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    
    logger.info("Wrote network to %s", output_path)
    
    return {
        "node_count": len(nodes),
        "link_count": len(links),
        "output_path": str(output_path),
        "crs": crs,
        "bbox": {
            "north": bbox.north,
            "south": bbox.south,
            "east": bbox.east,
            "west": bbox.west
        }
    }


# Predefined cities for quick access
PREDEFINED_CITIES = {
    "sioux_falls": {
        "name": "Sioux Falls, SD (classic transport benchmark)",
        "center": (43.5446, -96.7311),
        "radius_km": 5.0
    },
    "anaheim": {
        "name": "Anaheim, CA (another classic benchmark)",
        "center": (33.8366, -117.9143),
        "radius_km": 4.0
    },
    "austin_downtown": {
        "name": "Austin Downtown, TX",
        "center": (30.2672, -97.7431),
        "radius_km": 3.0
    },
    "manhattan_midtown": {
        "name": "Manhattan Midtown, NY",
        "center": (40.7549, -73.9840),
        "radius_km": 2.0
    },
    "sf_downtown": {
        "name": "San Francisco Downtown, CA",
        "center": (37.7879, -122.4074),
        "radius_km": 2.5
    }
}


def get_city_bbox(city_key: str) -> BoundingBox:
    """Get bounding box for a predefined city."""
    if city_key not in PREDEFINED_CITIES:
        available = ", ".join(PREDEFINED_CITIES.keys())
        raise ValueError(f"Unknown city '{city_key}'. Available: {available}")
    
    city = PREDEFINED_CITIES[city_key]
    lat, lon = city["center"]
    return BoundingBox.from_center(lat, lon, city["radius_km"])


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Build canonical network.xml from OpenStreetMap"
    )
    parser.add_argument(
        "--bbox", type=str,
        help="Bounding box as 'north,south,east,west'"
    )
    parser.add_argument(
        "--city", type=str, choices=list(PREDEFINED_CITIES.keys()),
        help="Use predefined city bounds"
    )
    parser.add_argument(
        "--output", "-o", type=str, required=True,
        help="Output path for network.xml"
    )
    parser.add_argument(
        "--network-type", type=str, default="drive",
        choices=["drive", "walk", "bike", "all"],
        help="OSM network type (default: drive)"
    )
    parser.add_argument(
        "--crs", type=str, default="EPSG:4326",
        help="Coordinate reference system (default: EPSG:4326)"
    )
    
    args = parser.parse_args()
    
    if args.bbox:
        bbox = BoundingBox.from_string(args.bbox)
    elif args.city:
        bbox = get_city_bbox(args.city)
        logger.info("Using predefined city: %s", PREDEFINED_CITIES[args.city]['name'])
    else:
        parser.error("Either --bbox or --city is required")
        return  # unreachable but satisfies linter
    
    result = build_network_from_osm(
        bbox=bbox,
        output_path=Path(args.output),
        network_type=args.network_type,
        crs=args.crs
    )
    
    print("\nNetwork built successfully:")
    print(f"  Nodes: {result['node_count']}")
    print(f"  Links: {result['link_count']}")
    print(f"  Output: {result['output_path']}")


if __name__ == "__main__":
    main()
