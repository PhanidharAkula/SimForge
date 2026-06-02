"""
Load the canonical road network from a local OSM PBF file.

A drop-in replacement for the Overpass-based ``download_osm_network`` in
``build_network_from_osm.py``. It reads a hash-pinned Geofabrik snapshot
from ``osm_data/`` (see ``osm_data/manifest.json``), slices it to the
requested bounding box, and returns a ``networkx.MultiDiGraph`` shaped just
like what osmnx would have built from Overpass, so nothing downstream has to
change.

What happens in here:
  1. ``pyosmium`` (the Python bindings for libosmium) scans the state PBF
     and writes a small, reference-complete ``.osm`` XML holding every
     highway=* way that touches the bbox plus all the nodes those ways
     reference. It's what ``osmium extract -b ...`` does at the CLI, just
     through the Python API so Pitzer only needs ``pip install osmium``.
  2. ``osmnx.graph_from_xml`` parses that XML into a ``MultiDiGraph`` with
     the same node and edge attributes (x, y, highway, length, maxspeed,
     lanes, name, osmid) the Overpass path produced.
  3. ``osmnx.truncate.truncate_graph_bbox`` trims edges that spill past the
     bbox (a way passing through drags its whole node set in via
     ``BackReferenceWriter``; truncation keeps the simulation footprint
     matched to the area we asked for).

Why a local PBF instead of live Overpass:
  - Reproducibility: Overpass serves a moving OSM target, while a
    SHA256-pinned PBF fixes the exact input every run saw.
  - Reliability: the public Overpass API rate-limits city-scale bboxes and
    quietly stalls on NYC-sized fetches (see thesis §4.3).
  - Speed: a state-PBF slice is 30-90s; the same bbox over Overpass is
    5-30+ min, if it finishes at all.
"""

from pathlib import Path
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)


def _slice_pbf_to_xml(pbf_path: Path, bbox, out_xml: Path) -> tuple[int, int, set, list]:
    """Slice ``pbf_path`` to ``out_xml`` keeping highway ways touching ``bbox``,
    and *in the same scan* collect:

      - OSM IDs of nodes tagged ``highway=traffic_signals`` inside the bbox.
      - OSM ``type=restriction`` relations whose ``via`` node is inside the
        bbox (turn restrictions: ``no_left_turn``, ``only_straight_on``, etc.).

    Uses pyosmium's ``BackReferenceWriter`` so the resulting XML is
    reference-complete: every node any written way refers to is included,
    even when the node itself sits outside the bbox (needed so osmnx can
    build the geometry).

    The PBF stream visits every entity once anyway (FileProcessor walks
    nodes, then ways, then relations in PBF order). We hang signal-node
    detection and turn-restriction detection off that same pass so there's
    no second whole-file scan, which matters on the CA PBF (1.3 GB, about
    140 s for a separate scan).

    Returns ``(ways_written, nodes_referenced_count, signal_node_ids,
    turn_restrictions)`` where ``turn_restrictions`` is a list of dicts:
    ``{"restriction": "no_left_turn", "from_way": <osm_id>, "via_node":
    <osm_id>, "to_way": <osm_id>, "osm_relation_id": <osm_id>}``.
    Only ``via=node`` restrictions get captured; ``via=way`` is rare and
    structurally different, so it's left as future work.
    """
    try:
        import osmium
    except ImportError as exc:
        raise ImportError(
            "pyosmium is required for local PBF loading.\n"
            "  Install: pip install osmium"
        ) from exc

    W, S, E, N = bbox.west, bbox.south, bbox.east, bbox.north

    fp = osmium.FileProcessor(str(pbf_path)).with_locations()
    ways_written = 0
    nodes_referenced: set[int] = set()
    signal_node_ids: set[int] = set()
    turn_restrictions: list = []
    # Cache via-node bbox membership: turn-restriction relations come AFTER
    # nodes in the PBF, so we accumulate node-in-bbox membership during the
    # node phase and check it when relations come through. This avoids
    # needing a coordinate index lookup inside the relation loop.
    node_in_bbox: set[int] = set()

    with osmium.BackReferenceWriter(str(out_xml), ref_src=str(pbf_path),
                                    overwrite=True) as writer:
        for obj in fp:
            if obj.is_node():
                # Track every node's in-bbox status for later turn-restriction
                # filtering, plus detect highway=traffic_signals for the
                # canonical network's `has_signal` attribute.
                try:
                    lon, lat = obj.location.lon, obj.location.lat
                except Exception:
                    continue
                in_box = W <= lon <= E and S <= lat <= N
                if in_box:
                    node_in_bbox.add(obj.id)
                    if obj.tags.get("highway") == "traffic_signals":
                        signal_node_ids.add(obj.id)
                continue
            if obj.is_relation():
                # Capture OSM `type=restriction` relations with `via=node`
                # (turn restrictions like no_left_turn, only_straight_on).
                # via=way restrictions exist too, but they're rare and
                # structurally different (the via is a sequence of ways), so
                # they're future work. Per OSM coverage stats they're under
                # 1% of restrictions in major US cities.
                if obj.tags.get("type") != "restriction":
                    continue
                rtype = obj.tags.get("restriction")
                if not rtype:
                    continue
                from_way = via_node = to_way = None
                via_is_node = False
                for member in obj.members:
                    role = member.role
                    mtype = member.type
                    if mtype == "w" and role == "from":
                        from_way = member.ref
                    elif mtype == "n" and role == "via":
                        via_node = member.ref
                        via_is_node = True
                    elif mtype == "w" and role == "via":
                        # via=way: skip this restriction
                        via_is_node = False
                        break
                    elif mtype == "w" and role == "to":
                        to_way = member.ref
                if (via_is_node and from_way is not None
                        and via_node is not None and to_way is not None
                        and via_node in node_in_bbox):
                    turn_restrictions.append({
                        "restriction": rtype,
                        "from_way": from_way,
                        "via_node": via_node,
                        "to_way": to_way,
                        "osm_relation_id": obj.id,
                    })
                continue
            if not obj.is_way():
                continue
            tags = obj.tags
            if "highway" not in tags:
                continue
            touches = False
            for nr in obj.nodes:
                try:
                    lon, lat = nr.lon, nr.lat
                except Exception:  # invalid / missing location
                    continue
                if W <= lon <= E and S <= lat <= N:
                    touches = True
                    break
            if touches:
                writer.add_way(obj)
                ways_written += 1
                for nr in obj.nodes:
                    nodes_referenced.add(nr.ref)

    return ways_written, len(nodes_referenced), signal_node_ids, turn_restrictions


def load_osm_from_pbf(pbf_path, bbox, network_type: str = "drive"):
    """Load and filter a local PBF into a networkx ``MultiDiGraph``.

    Args:
        pbf_path: Path to a ``.osm.pbf`` file.
        bbox: A ``BoundingBox`` (see ``build_network_from_osm.BoundingBox``).
        network_type: Road-network filter forwarded to osmnx. ``"drive"``
            filters to car-accessible roads.

    Returns:
        ``(G, signal_node_ids, turn_restrictions)`` where ``G`` is a
        ``networkx.MultiDiGraph`` with ``x``/``y`` on nodes and
        ``highway``/``length``/``maxspeed``/``lanes``/``name``/``osmid``
        on edges (schema-compatible with ``extract_canonical_network``),
        ``signal_node_ids`` is the set of OSM node IDs tagged
        ``highway=traffic_signals`` inside ``bbox``, and
        ``turn_restrictions`` is the list of OSM ``type=restriction``
        relations with ``via=node`` inside ``bbox``. All three ride the same
        PBF stream as the way slice, so there's no extra I/O.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise ImportError(
            "osmnx is required for PBF network building.\n"
            "  Install: pip install osmnx"
        ) from exc

    pbf_path = Path(pbf_path)
    if not pbf_path.exists():
        raise FileNotFoundError(
            f"OSM PBF not found at {pbf_path}.\n"
            f"  Download with: python tools/download_osm.py"
        )

    # The "Loading OSM network from local PBF: <name> (<size> MB)"
    # info is now surfaced by generate.py's "source:" header, so we
    # don't re-emit it here (avoids redundant lines in --verbose mode).
    # The bbox info is genuinely verbose-only useful and not in the
    # "source:" header, so it stays.
    logger.info(
        "  Bbox: N=%.4f S=%.4f E=%.4f W=%.4f",
        bbox.north, bbox.south, bbox.east, bbox.west,
    )

    t0 = time.time()

    # Slice the state PBF down to an in-bbox road-network XML. We stage it in
    # a temp file rather than keep it around; the canonical network.xml
    # downstream is the artifact worth preserving.
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f"{pbf_path.stem}_bbox_", suffix=".osm"
    )
    os.close(tmp_fd)
    tmp_xml = Path(tmp_path)

    try:
        ways_written, nodes_referenced, signal_node_ids, turn_restrictions = (
            _slice_pbf_to_xml(pbf_path, bbox, tmp_xml)
        )
        slice_elapsed = time.time() - t0
        logger.info(
            "  Sliced PBF: %d highway ways, %d referenced nodes, "
            "%d traffic-signals nodes, %d turn restrictions  (%.1fs)",
            ways_written, nodes_referenced, len(signal_node_ids),
            len(turn_restrictions), slice_elapsed,
        )

        if ways_written == 0:
            raise ValueError(
                f"PBF slice produced 0 highway ways for bbox {bbox}.\n"
                f"  PBF: {pbf_path}\n"
                f"  Verify the bbox lies within the PBF's coverage area —\n"
                f"  each PBF covers one US state (see osm_data/manifest.json)."
            )

        t1 = time.time()
        G = ox.graph_from_xml(str(tmp_xml), simplify=True, retain_all=False)
        logger.info(
            "  osmnx graph_from_xml: %d nodes, %d edges  (%.1fs)",
            G.number_of_nodes(), G.number_of_edges(), time.time() - t1,
        )
    finally:
        tmp_xml.unlink(missing_ok=True)

    # Clip edges that spill past the bbox. BackReferenceWriter keeps every
    # node a matching way touches, including ones well outside the bbox when
    # a long way (interstate, arterial) clips the corner. truncate_graph_bbox
    # strips those stub extensions so the simulated footprint matches what
    # Overpass's graph_from_bbox would have returned.
    G = ox.truncate.truncate_graph_bbox(
        G, bbox=(bbox.west, bbox.south, bbox.east, bbox.north),
        truncate_by_edge=True,
    )

    if G.number_of_nodes() == 0:
        raise ValueError(
            f"PBF slice + bbox truncation produced an empty graph.\n"
            f"  PBF: {pbf_path}\n  Bbox: {bbox}"
        )

    # network_type is accepted for signature parity with download_osm_network;
    # the highway-tag filter above already covers the "drive" case. Anything
    # more selective (walk/bike) would need a different tag filter.
    _ = network_type

    elapsed = time.time() - t0
    logger.info(
        "Loaded network: %d nodes, %d edges  (%.1fs, local PBF)",
        G.number_of_nodes(), G.number_of_edges(), elapsed,
    )
    return G, signal_node_ids, turn_restrictions
