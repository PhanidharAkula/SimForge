"""
Pre-warm the on-disk OSM cache for every scenario in ``scenarios/``.

Why this exists
---------------
``download_osm_network`` already pins osmnx's HTTP cache to ``<repo>/cache/``,
so the *second* fetch for a given bbox is fast. The first fetch is bounded by
the Overpass API and takes anywhere from 10 s to 2 min. On a fresh clone or
after wiping ``cache/``, that latency hits the user during the very first
benchmark run — exactly when they don't want surprises.

This CLI walks each scenario's ``generation_metadata.json`` (or, as a fallback,
the bounding rectangle of its ``network.xml`` nodes), reconstructs the bbox
``download_osm_network`` would have requested, and forces a fetch. Subsequent
benchmark runs hit the cache and start instantly.

Usage
-----
    python -m pipeline.network.warmup                  # all scenarios
    python -m pipeline.network.warmup --scenarios chicago_1k_car,nyc_1k_car
    python -m pipeline.network.warmup --dry-run        # report only, no fetch
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from pipeline.network.build_network_from_osm import BoundingBox

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "scenarios"
CACHE_DIR = REPO_ROOT / "cache"


@dataclass
class WarmupTarget:
    """One bbox we plan to (or did) fetch."""

    scenario_id: str
    source: str  # "generation_metadata" | "network_bbox"
    bbox: "BoundingBox"


def _load_cities_registry() -> dict:
    """Pull the canonical city registry from the top-level generator.

    Kept as a function (not a module-level import) so this CLI can be invoked
    in a fresh-clone state where generate.py's other imports may not yet have
    side-effects we care about.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from generate import CITIES  # type: ignore  # noqa: WPS433
    return CITIES


def _bbox_from_metadata(scenario_dir: Path):
    """Reconstruct the original bbox from generation_metadata.json, if present."""
    from pipeline.network.build_network_from_osm import BoundingBox  # local import

    meta_path = scenario_dir / "generation_metadata.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    city = meta.get("city")
    radius = meta.get("radius_km")
    if not city or radius is None:
        return None

    cities = _load_cities_registry()
    if city not in cities:
        return None
    lat = cities[city]["lat"]
    lon = cities[city]["lon"]
    return BoundingBox.from_center(lat, lon, float(radius))


def _bbox_from_network(scenario_dir: Path):
    """Last-resort: derive a bounding rectangle from the network's node coords.

    NOTE: this won't necessarily match the original Overpass cache key (osmnx
    truncates at the network's edge), but it's still a useful warmup since the
    fetched bbox will be a superset of the canonical network's footprint.
    """
    from pipeline.network.build_network_from_osm import BoundingBox  # local import

    net_path = scenario_dir / "network.xml"
    if not net_path.is_file():
        return None
    try:
        root = ET.parse(net_path).getroot()
    except ET.ParseError:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for node in root.findall(".//node"):
        try:
            xs.append(float(node.get("x", "")))
            ys.append(float(node.get("y", "")))
        except ValueError:
            continue
    if not xs or not ys:
        return None
    # x = lon, y = lat in our canonical schema.
    return BoundingBox(
        north=max(ys),
        south=min(ys),
        east=max(xs),
        west=min(xs),
    )


def _discover_targets(
    scenarios: Optional[Iterable[str]] = None,
) -> List[WarmupTarget]:
    if not SCENARIOS_DIR.is_dir():
        logger.warning("scenarios/ directory not found at %s", SCENARIOS_DIR)
        return []

    if scenarios:
        candidates = [SCENARIOS_DIR / s for s in scenarios]
    else:
        candidates = sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir())

    targets: List[WarmupTarget] = []
    for scenario_dir in candidates:
        if not scenario_dir.is_dir():
            logger.warning("Skipping %s — not a directory", scenario_dir)
            continue

        bbox = _bbox_from_metadata(scenario_dir)
        source = "generation_metadata"
        if bbox is None:
            bbox = _bbox_from_network(scenario_dir)
            source = "network_bbox"
        if bbox is None:
            logger.warning(
                "Skipping %s — no generation_metadata.json or readable network.xml",
                scenario_dir.name,
            )
            continue

        targets.append(WarmupTarget(
            scenario_id=scenario_dir.name,
            source=source,
            bbox=bbox,
        ))
    return targets


def warmup(
    scenarios: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> dict:
    """Fetch every discovered bbox; return a per-scenario summary."""
    targets = _discover_targets(scenarios)

    cache_files_before = (
        list(CACHE_DIR.glob("*.json")) if CACHE_DIR.is_dir() else []
    )
    logger.info(
        "OSM cache: %d existing responses at %s",
        len(cache_files_before), CACHE_DIR,
    )
    logger.info(
        "Found %d scenario(s) to warm up%s",
        len(targets),
        " (dry run — no fetches)" if dry_run else "",
    )

    results: list[dict] = []
    for t in targets:
        bbox = t.bbox
        bbox_repr = (
            f"n={bbox.north:.5f}, s={bbox.south:.5f}, "
            f"e={bbox.east:.5f}, w={bbox.west:.5f}"
        )
        logger.info(
            "[%s] bbox via %s: %s", t.scenario_id, t.source, bbox_repr,
        )
        if dry_run:
            results.append({
                "scenario_id": t.scenario_id,
                "source": t.source,
                "fetched": False,
                "elapsed_s": 0.0,
            })
            continue

        from pipeline.network.build_network_from_osm import download_osm_network

        start = time.time()
        try:
            G = download_osm_network(bbox)
            elapsed = time.time() - start
            results.append({
                "scenario_id": t.scenario_id,
                "source": t.source,
                "fetched": True,
                "elapsed_s": round(elapsed, 2),
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
                "cache_hit": elapsed < 2.0,
            })
        except Exception as exc:  # noqa: BLE001 — surface, don't abort batch
            elapsed = time.time() - start
            logger.error(
                "[%s] warmup failed after %.1fs: %s",
                t.scenario_id, elapsed, exc,
            )
            results.append({
                "scenario_id": t.scenario_id,
                "source": t.source,
                "fetched": False,
                "elapsed_s": round(elapsed, 2),
                "error": str(exc),
            })

    cache_files_after = (
        list(CACHE_DIR.glob("*.json")) if CACHE_DIR.is_dir() else []
    )
    new_files = len(cache_files_after) - len(cache_files_before)

    summary = {
        "targets": len(targets),
        "fetched": sum(1 for r in results if r.get("fetched")),
        "cache_hits": sum(1 for r in results if r.get("cache_hit")),
        "new_cache_entries": new_files,
        "results": results,
    }
    logger.info(
        "Warmup complete: %d fetched, %d cache hits, %d new cache entries",
        summary["fetched"], summary["cache_hits"], summary["new_cache_entries"],
    )
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Pre-warm the OSM cache for every scenario in scenarios/",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=None,
        help="Comma-separated scenario IDs (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover bboxes and report, but do not fetch",
    )
    args = parser.parse_args()

    scenarios = (
        [s.strip() for s in args.scenarios.split(",") if s.strip()]
        if args.scenarios else None
    )
    summary = warmup(scenarios=scenarios, dry_run=args.dry_run)

    print()
    print("=" * 70)
    print("  OSM cache warmup summary")
    print("=" * 70)
    print(f"  Targets:           {summary['targets']}")
    print(f"  Fetched:           {summary['fetched']}")
    print(f"  Cache hits:        {summary['cache_hits']}")
    print(f"  New cache entries: {summary['new_cache_entries']}")
    print("=" * 70)
    for r in summary["results"]:
        flag = "✓" if r.get("fetched") else ("·" if not r.get("error") else "✗")
        extra = ""
        if r.get("fetched"):
            extra = (
                f" — {r.get('nodes', '?')} nodes, "
                f"{r.get('edges', '?')} edges, "
                f"{'cache hit' if r.get('cache_hit') else 'fresh fetch'}"
            )
        elif r.get("error"):
            extra = f" — {r['error']}"
        print(
            f"  {flag} {r['scenario_id']:<32} "
            f"{r.get('elapsed_s', 0.0):>6.2f}s  "
            f"({r['source']}){extra}"
        )


if __name__ == "__main__":
    main()
