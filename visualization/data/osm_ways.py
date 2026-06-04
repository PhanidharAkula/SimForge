"""Extract OSM way geometries from the bundled PBF files.

The SimForge canonical ``network.xml`` only stores from/to endpoints
per link, not intermediate curve geometry. To draw smooth curves on
link_load / congestion maps, we re-extract each link's parent OSM
way from the original PBF (in ``osm_data/``), then snip the way's
vertex sequence between the SimForge link's from/to OSM node IDs.

The result is per-link curved polylines that match exactly what the
underlying real-world road looks like. Cached per scenario at
``cache/osm_ways/<scenario>/way_geometries.json`` so subsequent
renders skip the slow PBF parse.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


_OSM_PBF_BY_CITY: dict[str, str] = {
    "chicago": "illinois-2026-04-22.osm.pbf",
    "nyc":     "new-york-2026-04-22.osm.pbf",
    "la":      "california-2026-04-22.osm.pbf",
}


def detect_pbf_for_scenario(scenario_id: str) -> Path | None:
    """Map scenario name prefix to its PBF file in ``osm_data/``."""
    base = Path("osm_data")
    for city_key, fname in _OSM_PBF_BY_CITY.items():
        if scenario_id.startswith(f"{city_key}_"):
            p = base / fname
            return p if p.is_file() else None
    return None


def cache_path_for_scenario(scenario_id: str) -> Path:
    return Path("cache") / "osm_ways" / scenario_id / "way_geometries.json"


def load_way_geometries(
    scenario_id: str,
    needed_way_ids: set[int],
    pbf_path: Path | None = None,
    force_refresh: bool = False,
) -> dict[int, list[tuple[float, float]]]:
    """Return ``{way_id: [(lon, lat), ...]}`` for every needed_way_id.

    Reads the per-scenario JSON cache when it's there; otherwise it parses
    the right PBF (slow, minutes for large states) and caches the result.
    """
    cache_fp = cache_path_for_scenario(scenario_id)
    cached: dict[int, list[tuple[float, float]]] = {}
    if cache_fp.is_file() and not force_refresh:
        try:
            data = json.loads(cache_fp.read_text())
            cached = {int(k): [(p[0], p[1]) for p in v] for k, v in data.items()}
            missing = needed_way_ids - cached.keys()
            if not missing:
                logger.info("OSM ways cache hit: %d ways from %s",
                            len(needed_way_ids), cache_fp)
                return {wid: cached[wid] for wid in needed_way_ids if wid in cached}
            logger.info("OSM ways cache covers %d/%d needed; re-extracting full set",
                        len(needed_way_ids) - len(missing), len(needed_way_ids))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("OSM ways cache corrupt at %s: %s, re-extracting", cache_fp, e)

    if pbf_path is None:
        pbf_path = detect_pbf_for_scenario(scenario_id)
    if pbf_path is None or not pbf_path.is_file():
        logger.warning("No OSM PBF found for scenario %s, link curves unavailable",
                       scenario_id)
        return {}

    try:
        import osmium
    except ImportError:
        logger.warning("pyosmium not installed: install via `uv pip install osmium`")
        return {}

    logger.info("Parsing OSM ways from %s (extracting %d needed), slow first time...",
                pbf_path, len(needed_way_ids))

    way_geoms: dict[int, list[tuple[float, float]]] = {}

    class _WayCollector(osmium.SimpleHandler):
        def way(self, w):
            if w.id not in needed_way_ids:
                return
            try:
                pts = [
                    (n.location.lon, n.location.lat)
                    for n in w.nodes if n.location.valid()
                ]
                if len(pts) >= 2:
                    way_geoms[w.id] = pts
            except Exception:
                pass

    handler = _WayCollector()
    handler.apply_file(str(pbf_path), locations=True)

    cache_fp.parent.mkdir(parents=True, exist_ok=True)
    cache_fp.write_text(json.dumps(
        {str(k): v for k, v in way_geoms.items()},
        separators=(",", ":"),
    ))
    logger.info("Cached %d way geometries -> %s", len(way_geoms), cache_fp)
    return way_geoms


def link_polyline(
    link_id: str,
    from_node_id: str,
    to_node_id: str,
    way_ids: list[int],
    way_geoms: dict[int, list[tuple[float, float]]],
    node_coords: dict[str, tuple[float, float]],
    node_osm_ids: dict[str, int],
) -> list[tuple[float, float]]:
    """Build the curved polyline for one SimForge link.

    Walks each candidate parent OSM way, finds where the link's
    from/to OSM node IDs land in the way's vertex sequence, and
    returns the subpolyline between them. Falls back to a straight
    from→to line if no way mapping is found.
    """
    fallback = [node_coords[from_node_id], node_coords[to_node_id]]
    if from_node_id not in node_osm_ids or to_node_id not in node_osm_ids:
        return fallback
    from_osm = node_osm_ids[from_node_id]
    to_osm = node_osm_ids[to_node_id]

    # Try each candidate way until we find one whose node sequence
    # contains both endpoints.
    for wid in way_ids:
        pts = way_geoms.get(wid)
        if not pts or len(pts) < 2:
            continue
        # We don't have per-vertex OSM node IDs from the cache (only
        # coordinates). Instead, snip by coordinate proximity to the
        # SimForge from/to coords. SimForge node coords were extracted
        # from the same OSM nodes, so they match the way's vertices to
        # ~floating-point precision.
        from_xy = node_coords[from_node_id]
        to_xy = node_coords[to_node_id]
        from_idx = _nearest_index(pts, from_xy)
        to_idx = _nearest_index(pts, to_xy)
        if from_idx is None or to_idx is None:
            continue
        if from_idx == to_idx:
            continue
        if from_idx < to_idx:
            return pts[from_idx:to_idx + 1]
        return list(reversed(pts[to_idx:from_idx + 1]))

    return fallback


def _nearest_index(
    pts: list[tuple[float, float]],
    target: tuple[float, float],
    epsilon: float = 1e-5,
) -> int | None:
    """Find the index of the vertex closest to ``target`` within ``epsilon`` degrees."""
    best_idx = None
    best_d2 = epsilon * epsilon
    tx, ty = target
    for i, (x, y) in enumerate(pts):
        dx = x - tx
        dy = y - ty
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best_idx = i
    return best_idx
