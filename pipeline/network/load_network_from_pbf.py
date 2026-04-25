"""
Load canonical road network from a local OSM PBF file.

Drop-in replacement for the Overpass-based ``download_osm_network`` in
``build_network_from_osm.py``. Reads a hash-pinned Geofabrik snapshot from
``osm_data/`` (see ``osm_data/manifest.json``), slices it to the requested
bounding box, and returns a ``networkx.MultiDiGraph`` shape-compatible with
what osmnx would have produced via Overpass — so the downstream canonical
extraction is unchanged.

Pipeline inside this module:
  1. ``pyosmium`` (Python bindings for libosmium) scans the state PBF and
     writes a small reference-complete ``.osm`` XML file containing every
     highway=* way that touches the bbox, plus all nodes those ways refer
     to. This is what ``osmium extract -b ...`` does as a CLI, expressed
     through the Python API so Pitzer only needs ``pip install osmium``.
  2. ``osmnx.graph_from_xml`` parses that XML into a ``MultiDiGraph`` with
     the same node/edge attributes (x, y, highway, length, maxspeed, lanes,
     name, osmid) the Overpass path produced.
  3. ``osmnx.truncate.truncate_graph_bbox`` clips edges that bleed past the
     requested bbox (ways that pass through drag their full node set in
     via ``BackReferenceWriter``; truncation keeps the simulation footprint
     matched to the requested area).

Why local PBF over live Overpass:
  - Reproducibility: live Overpass returns a moving OSM target; a PBF
    pinned by SHA256 fixes the exact input every run saw.
  - Reliability: the public Overpass API rate-limits city-scale bboxes
    and silently stalls on NYC-sized fetches (see thesis §4.3).
  - Speed: state-PBF slice is 30-90s; the same bbox over Overpass is
    5-30+min when it completes at all.
"""

from pathlib import Path
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)


def _slice_pbf_to_xml(pbf_path: Path, bbox, out_xml: Path) -> tuple[int, int]:
    """Slice ``pbf_path`` to ``out_xml`` keeping highway ways touching ``bbox``.

    Uses pyosmium's ``BackReferenceWriter`` so the resulting XML is
    reference-complete: every node any written way refers to is included,
    even when the node itself sits outside the bbox (needed so osmnx can
    build the geometry).
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

    with osmium.BackReferenceWriter(str(out_xml), ref_src=str(pbf_path),
                                    overwrite=True) as writer:
        for obj in fp:
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

    return ways_written, len(nodes_referenced)


def load_osm_from_pbf(pbf_path, bbox, network_type: str = "drive"):
    """Load and filter a local PBF into a networkx ``MultiDiGraph``.

    Args:
        pbf_path: Path to a ``.osm.pbf`` file.
        bbox: A ``BoundingBox`` (see ``build_network_from_osm.BoundingBox``).
        network_type: Road-network filter forwarded to osmnx. ``"drive"``
            filters to car-accessible roads.

    Returns:
        ``networkx.MultiDiGraph`` with ``x``/``y`` on nodes and
        ``highway``/``length``/``maxspeed``/``lanes``/``name``/``osmid``
        on edges — schema-compatible with ``extract_canonical_network``.
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

    size_mb = pbf_path.stat().st_size / 1e6
    logger.info(
        "Loading OSM network from local PBF: %s (%.0f MB)",
        pbf_path.name, size_mb,
    )
    logger.info(
        "  Bbox: N=%.4f S=%.4f E=%.4f W=%.4f",
        bbox.north, bbox.south, bbox.east, bbox.west,
    )

    t0 = time.time()

    # Slice the state PBF down to an in-bbox road network XML. We stage it
    # under a temp file rather than keeping it on disk — the canonical
    # network.xml downstream is the artifact we care about preserving.
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f"{pbf_path.stem}_bbox_", suffix=".osm"
    )
    os.close(tmp_fd)
    tmp_xml = Path(tmp_path)

    try:
        ways_written, nodes_referenced = _slice_pbf_to_xml(pbf_path, bbox, tmp_xml)
        slice_elapsed = time.time() - t0
        logger.info(
            "  Sliced PBF: %d highway ways, %d referenced nodes  (%.1fs)",
            ways_written, nodes_referenced, slice_elapsed,
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

    # Clip edges that bleed past the bbox. BackReferenceWriter keeps every
    # node a matching way refers to — including ones far outside the bbox
    # when long ways (interstates, arterials) pass through the corner.
    # truncate_graph_bbox removes those stub extensions so the simulated
    # footprint matches what Overpass's graph_from_bbox would have returned.
    #
    # osmnx 2.x takes bbox=(W,S,E,N); 1.x takes north/south/east/west kwargs
    # (passing a 2.x-style tuple to 1.x would be silently accepted as
    # (N,S,E,W), build an inverted polygon, and clip the graph to zero
    # nodes). Branch on the major version — Pitzer runs 1.9.x, the dev
    # box runs 2.x, and either is a valid pipeline for the thesis.
    osmnx_major = int(ox.__version__.split(".", 1)[0])
    if osmnx_major >= 2:
        G = ox.truncate.truncate_graph_bbox(
            G, bbox=(bbox.west, bbox.south, bbox.east, bbox.north),
            truncate_by_edge=True,
        )
    else:
        G = ox.truncate.truncate_graph_bbox(
            G, north=bbox.north, south=bbox.south,
            east=bbox.east, west=bbox.west,
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
    return G
