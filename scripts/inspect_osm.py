"""
Quick inspection of an OSM PBF in ``osm_data/``.

Prints a human-readable summary (node/way counts, highway class histogram,
sample tags) so a reviewer can see what's inside a PBF without firing up
JOSM or QGIS. Optionally filter to a sub-bbox for city-sized peeks; without
a bbox the whole PBF is scanned (30-90s for a US state).

Usage:
    python scripts/inspect_osm.py --city nyc
    python scripts/inspect_osm.py --file osm_data/illinois-2026-04-22.osm.pbf
    python scripts/inspect_osm.py --city la --bbox 33.95,34.15,-118.40,-118.15
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = REPO_ROOT / "osm_data"
MANIFEST = OSM_DIR / "manifest.json"


CITY_TO_PBF = {
    "chicago": "illinois",
    "nyc": "new-york",
    "la": "california",
}


def resolve_pbf(args: argparse.Namespace) -> Path:
    if args.file:
        return Path(args.file)
    if args.city:
        if args.city not in CITY_TO_PBF:
            sys.exit(f"unknown --city {args.city!r}; choose from {list(CITY_TO_PBF)}")
        manifest = json.loads(MANIFEST.read_text())
        key = CITY_TO_PBF[args.city]
        return OSM_DIR / manifest["files"][key]["path"]
    sys.exit("pass --city or --file")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", choices=list(CITY_TO_PBF))
    parser.add_argument("--file", help="Path to a .osm.pbf")
    parser.add_argument("--bbox", help="Sub-bbox 'south,north,west,east' (lat,lat,lon,lon)")
    args = parser.parse_args()

    pbf = resolve_pbf(args)
    if not pbf.exists():
        sys.exit(f"PBF not found: {pbf}\n  Download with: python scripts/download_osm.py")

    try:
        import osmium
    except ImportError:
        sys.exit("pyosmium is required. Install with: pip install osmium")

    bbox = None
    if args.bbox:
        s, n, w, e = (float(x) for x in args.bbox.split(","))
        bbox = (w, s, e, n)  # W, S, E, N

    size_mb = pbf.stat().st_size / 1e6
    print(f"File: {pbf}")
    print(f"Size: {size_mb:.1f} MB")
    print(f"Filter bbox: {bbox or 'none (full PBF coverage)'}")
    print()
    print("Parsing — this may take 30-90 s for a full state PBF ...")

    fp = osmium.FileProcessor(str(pbf)).with_locations()

    n_nodes = 0
    n_ways = 0
    n_highway_ways = 0
    highway_counts: Counter[str] = Counter()
    sample_way = None

    for obj in fp:
        if obj.is_node():
            n_nodes += 1
            continue
        if not obj.is_way():
            continue
        n_ways += 1
        tags = obj.tags
        if "highway" not in tags:
            continue

        if bbox is not None:
            W, S, E, N = bbox
            in_bbox = False
            for nr in obj.nodes:
                try:
                    if W <= nr.lon <= E and S <= nr.lat <= N:
                        in_bbox = True
                        break
                except Exception:
                    continue
            if not in_bbox:
                continue

        n_highway_ways += 1
        highway_counts[tags["highway"]] += 1
        if sample_way is None:
            sample_way = {
                "osm_way_id": obj.id,
                "highway": tags["highway"],
                "name": tags.get("name"),
                "maxspeed": tags.get("maxspeed"),
                "lanes": tags.get("lanes"),
                "num_nodes": len(obj.nodes),
            }

    print()
    print(f"Nodes (total in PBF): {n_nodes:,}")
    print(f"Ways (total in PBF): {n_ways:,}")
    print(f"Highway ways{' in bbox' if bbox else ''}: {n_highway_ways:,}")
    print()

    if not n_highway_ways:
        print("No highway ways matched — check bbox coverage.")
        return 2

    print("Highway ways by class:")
    for klass, count in highway_counts.most_common(15):
        print(f"  {klass:22s} {count:>8,}")
    if len(highway_counts) > 15:
        print(f"  ... and {len(highway_counts) - 15} more classes")

    if sample_way is not None:
        print()
        print("Sample highway way (first match):")
        for k, v in sample_way.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
