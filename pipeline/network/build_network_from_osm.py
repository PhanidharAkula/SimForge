"""
Build canonical network.xml from OpenStreetMap data.

Given a bounding box, this downloads (or slices) the OSM data, pulls out the
road-network topology, and converts it to the canonical schema.

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
        # Rough: 1 degree of latitude is about 111 km. Longitude shrinks with
        # latitude, hence the cos() below.
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
    has_signal: bool = False  # True if OSM tags this node as highway=traffic_signals


@dataclass
class CanonicalTurnRestriction:
    """A turn restriction at a junction (e.g. no-left, only-straight).

    Sourced from OSM `type=restriction` relations with `via=node`.
    Resolved to canonical link IDs at extraction time so consumers
    don't need to round-trip back to OSM.
    """
    restriction: str            # OSM restriction value: no_left_turn, no_right_turn,
                                # no_u_turn, no_straight_on, only_left_turn,
                                # only_right_turn, only_straight_on
    from_link: str              # canonical link ID of the entering link
    via_node: str               # canonical node ID at the junction
    to_link: str                # canonical link ID of the leaving link
    osm_relation_id: Optional[int] = None  # provenance


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


# Default speed limits by OSM highway type (m/s).
#
# Used only when an OSM way has no explicit `maxspeed` tag. Most major US
# roads carry maxspeed in OSM and override these defaults; this table is
# for the long tail of unmarked residential / service roads. Values are
# typical urban speed limits in km/h converted to m/s. (Cityscape's
# `model_gen/ModelGenerator.cpp::SpeedLimits` is a separate US-mph table it
# uses for its own travel-time estimation; we don't touch it, we read OSM
# `maxspeed` directly through osmnx.)
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
    Pinning the cache folder to ``<repo>/cache`` makes hits deterministic
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
    # osmnx's projected-area calculation overestimates city-scale bboxes by
    # several orders of magnitude (NYC 20km bbox shows up as ~10^14 m² rather
    # than the true ~2×10^9). The default 2.5×10^9 ceiling then triggers tens
    # of thousands of Overpass sub-queries that the public endpoint cannot
    # service. Setting the ceiling above the inflated value (10^15) sends one
    # query that Overpass refuses as too large; 10^13 splits the same NYC bbox
    # into ~10 manageable chunks (each Manhattan-sized in real area).
    ox.settings.max_query_area_size = 10**13
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

    Uses osmnx's built-in HTTP cache (pinned to ``<repo>/cache`` via
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
    crs: str = "EPSG:4326",
    osm_signal_ids: Optional[set] = None,
    osm_turn_restrictions: Optional[list] = None,
) -> tuple[list[CanonicalNode], list[CanonicalLink], list[CanonicalTurnRestriction]]:
    """Pull canonical nodes, links, and turn restrictions out of an OSM graph.

    Args:
        G: OSM network graph from osmnx
        crs: Coordinate reference system
        osm_signal_ids: Optional set of OSM node IDs that carry the
            ``highway=traffic_signals`` tag, sourced from the unified PBF
            scan inside ``load_network_from_pbf.load_osm_from_pbf`` (or
            empty for the Overpass fallback path, where node tags are
            preserved on the graph and read directly below). Used to set
            ``has_signal=True`` on the matching canonical node. When
            empty AND the graph nodes have no ``highway`` attribute,
            all nodes default to ``has_signal=False`` and the signal
            generator falls back to its degree heuristic with a warning.
        osm_turn_restrictions: Optional list of dicts (each with keys
            ``restriction``, ``from_way``, ``via_node``, ``to_way``,
            ``osm_relation_id``) sourced from
            ``load_network_from_pbf._slice_pbf_to_xml``. Each entry is
            resolved here against canonical link/node IDs and emitted
            as a ``CanonicalTurnRestriction``. Restrictions whose
            ``via_node``, ``from_way``, or ``to_way`` didn't survive the
            bbox or SCC truncation are dropped quietly, since those movements
            don't exist in the canonical network anyway.

    Returns:
        Tuple of (nodes, links, turn_restrictions)
    """
    _ = crs  # reserved for future CRS projection support
    osm_signal_ids = osm_signal_ids or set()
    osm_turn_restrictions = osm_turn_restrictions or []
    
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

        # Real-world signal placement comes from OSM's `highway=traffic_signals`
        # node tag (community-curated; ~5-15% of nodes in major US cities).
        # Two routes get the tag in here, depending on which OSM source path
        # produced the graph:
        #   - PBF (default): pyosmium's BackReferenceWriter emits referenced
        #     nodes as bare `<node id lat lon />` *without* their tags, so the
        #     way-slice scan in `load_network_from_pbf._slice_pbf_to_xml`
        #     piggybacks signal-node detection on the same PBF stream and
        #     returns the OSM-ID set, which arrives here as `osm_signal_ids`.
        #   - Overpass fallback: `osmnx.graph_from_bbox` preserves node tags
        #     directly on the graph (per `osmnx.settings.useful_tags_node`),
        #     so we read `data.get("highway")` and accept the match.
        # OR'ing both sources keeps the code robust if either path improves
        # in the future.
        node_highway = data.get("highway")
        if isinstance(node_highway, list):
            node_highway = node_highway[0] if node_highway else None
        has_signal = (
            osm_id in osm_signal_ids
            or node_highway == "traffic_signals"
        )

        nodes.append(CanonicalNode(
            id=canonical_id,
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            osm_id=osm_id,
            node_type=node_type,
            has_signal=has_signal,
        ))
    
    # Extract links (edges)
    link_counter = 0
    seen_edges = set()
    skipped_zero_length = 0
    skipped_self_loops = 0

    for u, v, key, data in sorted(G.edges(keys=True, data=True)):
        # Create unique edge identifier
        edge_id = (u, v, key)
        if edge_id in seen_edges:
            continue
        seen_edges.add(edge_id)

        # Drop self-loops (from == to). SUMO's netconvert 1.26+ refuses to
        # produce a net file when it encounters them; pipeline.network.scc
        # also ignores them. They have no traffic-engineering meaning, and
        # osmnx 2.x emits more of them from circular OSM ways than 1.x did.
        if u == v:
            skipped_self_loops += 1
            continue

        from_node = osm_to_canonical[u]
        to_node = osm_to_canonical[v]

        # Get highway type
        highway = data.get("highway", "residential")
        if isinstance(highway, list):
            highway = highway[0]

        # Get length, and drop degenerate edges (length <= 0). These show up
        # when an OSM way joins two nodes at the exact same coordinates
        # (parking connectors, barrier-crossing artifacts, and the like). SUMO
        # would warn and MATSim would teleport, so it's cleaner to filter here.
        # Logged at INFO so the noise stays out of default-mode output and only
        # surfaces under --verbose; the per-step summary line below still
        # reports the aggregate `dropped N zero-length` count regardless.
        length_m = data.get("length", 100.0)
        if length_m <= 0:
            logger.info(
                "Dropping degenerate edge u=%s v=%s key=%s length=%s "
                "(osmid=%s, highway=%s) — endpoints share the same coordinates",
                u, v, key, length_m, data.get("osmid"), highway,
            )
            skipped_zero_length += 1
            continue
        
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
    
    drop_notes = []
    if skipped_zero_length:
        drop_notes.append(f"{skipped_zero_length} zero-length")
    if skipped_self_loops:
        drop_notes.append(f"{skipped_self_loops} self-loops")
    if drop_notes:
        logger.info(
            "Extracted %d nodes, %d links (dropped %s)",
            len(nodes), len(links), ", ".join(drop_notes),
        )
    else:
        logger.info("Extracted %d nodes, %d links", len(nodes), len(links))

    # ---------- Resolve OSM turn restrictions to canonical IDs ----------
    # Each OSM `type=restriction` relation has (from_way, via_node, to_way)
    # at the OSM level. We need to resolve those to the specific canonical
    # links that approach + leave the via_node, since one OSM way may
    # decompose into many canonical links across the network.
    #
    # Strategy:
    #   - Index canonical links by (osm_way_id, to_node) for the "from" lookup
    #     (the link approaching the junction).
    #   - Index canonical links by (osm_way_id, from_node) for the "to" lookup
    #     (the link leaving the junction).
    #   - Drop restrictions whose via_node didn't survive into canonical IDs,
    #     or whose ways were filtered out (e.g. by SCC clipping).
    osm_to_canonical_node = {n.osm_id: n.id for n in nodes if n.osm_id is not None}
    from_link_index: dict[tuple[int, str], CanonicalLink] = {}
    to_link_index: dict[tuple[int, str], CanonicalLink] = {}
    for link in links:
        if link.osm_way_id is None:
            continue
        # When an OSM way is split mid-segment, the same osm_way_id appears
        # on multiple canonical links. Indexing by (way_id, endpoint) picks
        # the unique link incident on each junction.
        try:
            way_id = int(str(link.osm_way_id).split(",")[0])
        except (TypeError, ValueError):
            continue
        from_link_index.setdefault((way_id, link.to_node), link)
        to_link_index.setdefault((way_id, link.from_node), link)

    turn_restrictions: list[CanonicalTurnRestriction] = []
    skipped_via_filtered = 0
    skipped_link_unresolved = 0
    for r in osm_turn_restrictions:
        canonical_via = osm_to_canonical_node.get(r["via_node"])
        if canonical_via is None:
            skipped_via_filtered += 1
            continue
        from_link = from_link_index.get((r["from_way"], canonical_via))
        to_link = to_link_index.get((r["to_way"], canonical_via))
        if from_link is None or to_link is None:
            skipped_link_unresolved += 1
            continue
        turn_restrictions.append(CanonicalTurnRestriction(
            restriction=r["restriction"],
            from_link=from_link.id,
            via_node=canonical_via,
            to_link=to_link.id,
            osm_relation_id=r.get("osm_relation_id"),
        ))

    if osm_turn_restrictions:
        kept = len(turn_restrictions)
        total = len(osm_turn_restrictions)
        logger.info(
            "Turn restrictions: %d kept, %d dropped "
            "(%d via-node filtered out, %d unresolved link)  of %d total",
            kept, total - kept, skipped_via_filtered, skipped_link_unresolved, total,
        )

    return nodes, links, turn_restrictions


def build_network_xml(
    nodes: list[CanonicalNode],
    links: list[CanonicalLink],
    crs: str = "EPSG:4326",
    units_length: str = "meters",
    units_speed: str = "m/s",
    turn_restrictions: Optional[list[CanonicalTurnRestriction]] = None,
) -> etree.Element:
    """
    Build the canonical network.xml from the extracted nodes, links, and
    (optional) turn restrictions.

    Args:
        nodes: the canonical nodes
        links: the canonical links
        crs: coordinate reference system string
        units_length: length unit string
        units_speed: speed unit string
        turn_restrictions: optional CanonicalTurnRestriction list. When it's
            non-empty, a ``<turn_restrictions>`` block follows ``<links>``
            with one ``<turn_restriction>`` per entry.

    Returns:
        The lxml element-tree root.
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
        if node.has_signal:
            node_elem.set("has_signal", "true")
    
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

    # Optional turn-restrictions block (V5+). Emitted only when
    # extraction returned at least one resolved restriction so that
    # absent-restrictions networks (synthetic, Overpass-without-relations)
    # still produce a clean schema.
    if turn_restrictions:
        tr_elem = etree.SubElement(root, "turn_restrictions")
        for r in sorted(turn_restrictions,
                        key=lambda x: (x.via_node, x.from_link, x.to_link)):
            r_elem = etree.SubElement(tr_elem, "turn_restriction")
            r_elem.set("type", r.restriction)
            r_elem.set("from_link", r.from_link)
            r_elem.set("via_node", r.via_node)
            r_elem.set("to_link", r.to_link)
            if r.osm_relation_id is not None:
                r_elem.set("osm_relation_id", str(r.osm_relation_id))

    return root


def build_network_from_osm(
    bbox: BoundingBox,
    output_path: Path,
    network_type: str = "drive",
    crs: str = "EPSG:4326",
    *,
    pbf_path: Optional[Path] = None,
) -> dict:
    """
    The entry point: build canonical network.xml from OSM data.

    With ``pbf_path``, the network comes from a local Geofabrik snapshot
    (reproducible, offline). Without it, the function falls back to a live
    Overpass download, which we keep around only for bboxes no local PBF
    covers.

    Args:
        bbox: geographic bounding box
        output_path: where to write network.xml
        network_type: OSM network type
        crs: coordinate reference system
        pbf_path: optional local ``.osm.pbf``, the preferred source.

    Returns:
        A summary dict with node_count, link_count, osm_source, and so on.
    """
    if pbf_path is not None:
        # PBF path is the default for all bundled cities (chicago/nyc/la have
        # PBFs in osm_data/, see osm_data/manifest.json). Hash-pinned, offline,
        # reproducible.
        from pipeline.network.load_network_from_pbf import load_osm_from_pbf
        # `load_osm_from_pbf` returns (graph, signal_node_ids,
        # turn_restrictions). All three come off the same PBF stream that
        # produces the way slice, so there's no second whole-file scan and
        # the extraction is basically free even on the 1.3 GB CA PBF.
        G, osm_signal_ids, osm_turn_restrictions = load_osm_from_pbf(
            pbf_path, bbox, network_type,
        )
        osm_source = {"type": "pbf", "path": str(pbf_path), "name": Path(pbf_path).name}
    else:
        # Overpass fallback, which only fires when no local PBF covers the
        # bbox (rare; kept for one-off experiments). osmnx.graph_from_bbox
        # keeps node tags per `osmnx.settings.useful_tags_node`, so signal
        # placement still comes through as a graph attribute in
        # extract_canonical_network(). Turn-restriction relations, though,
        # aren't exposed by graph_from_bbox in any structured form (they'd
        # need a separate Overpass query), so we pass an empty list. Networks
        # built this way skip turn restrictions; only the PBF path produces
        # them, which is fine, since PBF is the default for thesis bundles.
        G = download_osm_network(bbox, network_type)
        osm_signal_ids = set()
        osm_turn_restrictions = []
        osm_source = {"type": "overpass", "endpoint": "https://overpass-api.de/api/"}

    # Extract
    nodes, links, turn_restrictions = extract_canonical_network(
        G, crs,
        osm_signal_ids=osm_signal_ids,
        osm_turn_restrictions=osm_turn_restrictions,
    )

    # Build XML
    root = build_network_xml(nodes, links, crs, turn_restrictions=turn_restrictions)

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(str(output_path), pretty_print=True, xml_declaration=True, encoding="UTF-8")

    logger.info("Wrote network to %s", output_path)

    osm_signal_node_count = sum(1 for n in nodes if n.has_signal)
    return {
        "node_count": len(nodes),
        "link_count": len(links),
        "osm_signal_node_count": osm_signal_node_count,
        "turn_restriction_count": len(turn_restrictions),
        "output_path": str(output_path),
        "crs": crs,
        "bbox": {
            "north": bbox.north,
            "south": bbox.south,
            "east": bbox.east,
            "west": bbox.west
        },
        "osm_source": osm_source,
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
