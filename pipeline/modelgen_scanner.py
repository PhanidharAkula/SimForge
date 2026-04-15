"""
Fast scanner for modelgen files.

Counts total persons by JWTRNS transport mode without full parsing.
Results are cached to avoid re-scanning unchanged files.

Cache is stored in: .modelgen_cache.json (project root)
Re-scan triggers: file added/removed, file size changed, mtime changed.
"""

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JWTRNS_TO_MODE = {
    1: "car",
    2: "car",
    3: "transit",
    4: "transit",
    5: "transit",
    6: "transit",
    7: "transit",
    8: "bike",
    9: "walk",
    10: "home",
    11: "car",
    12: "car",
}

# Expected city names derived from filename pattern: <city>_model.txt
# Can auto-discover any file matching *_model.txt in modelgen/


def _scan_model_file(path: Path) -> dict:
    """
    Fast line-by-line scan of a model file.

    Only looks at 'per' lines to extract JWTRNS codes.
    Returns dict with counts per canonical mode plus metadata.
    """
    mode_counts: dict[str, int] = defaultdict(int)
    total_persons = 0
    total_buildings = 0
    total_households = 0
    commuters = 0  # persons with JWTRNS > 0 and != 10 (not WFH)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("per "):
                total_persons += 1
                parts = line.split()
                if len(parts) >= 8:
                    try:
                        jwtrns = int(parts[7])
                    except ValueError:
                        continue
                    mode = JWTRNS_TO_MODE.get(jwtrns)
                    if mode and mode != "home":
                        commuters += 1
                        mode_counts[mode] = mode_counts.get(mode, 0) + 1
            elif line.startswith("bld "):
                total_buildings += 1
            elif line.startswith("hld "):
                total_households += 1

    return {
        "total_persons": total_persons,
        "total_buildings": total_buildings,
        "total_households": total_households,
        "commuters": commuters,
        "mode_counts": dict(mode_counts),
    }


def _file_fingerprint(path: Path) -> dict:
    """Get size + mtime for change detection."""
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def scan_modelgen_dir(
    modelgen_dir: Optional[Path] = None,
    cache_path: Optional[Path] = None,
    force: bool = False,
) -> dict:
    """
    Scan modelgen/ for all *_model.txt files and return census stats.

    Results are cached; only re-scans files whose size or mtime changed.

    Returns:
        {
          "cities": {
            "chicago": {
              "file": "chicago_model.txt",
              "size_mb": 293,
              "total_persons": 2420896,
              "commuters": 1234567,
              "mode_counts": {"car": 900000, "transit": 200000, ...},
            },
            ...
          },
          "scan_timestamp": "2026-04-15T..."
        }
    """
    if modelgen_dir is None:
        modelgen_dir = Path(__file__).parent.parent / "modelgen"
    if cache_path is None:
        cache_path = Path(__file__).parent.parent / ".modelgen_cache.json"

    # Find all model files
    model_files = sorted(modelgen_dir.glob("*_model.txt"))
    if not model_files:
        logger.warning("No *_model.txt files found in %s", modelgen_dir)
        return {"cities": {}}

    # Load existing cache
    cached = {}
    if cache_path.exists() and not force:
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)
        except (json.JSONDecodeError, OSError):
            cached = {}

    cached_cities = cached.get("cities", {})
    cached_fingerprints = cached.get("_fingerprints", {})

    result_cities = {}
    fingerprints = {}
    any_changed = False

    for mf in model_files:
        # Derive city key from filename: chicago_model.txt -> chicago
        city_key = mf.stem.replace("_model", "")
        fp = _file_fingerprint(mf)
        fingerprints[city_key] = fp

        # Check if cached data is still valid
        old_fp = cached_fingerprints.get(city_key, {})
        if (not force
                and city_key in cached_cities
                and old_fp.get("size") == fp["size"]
                and old_fp.get("mtime") == fp["mtime"]):
            # Cache hit
            result_cities[city_key] = cached_cities[city_key]
            logger.debug("Cache hit for %s", city_key)
        else:
            # Need to scan
            any_changed = True
            logger.info("Scanning %s (%d MB) ...", mf.name,
                        mf.stat().st_size // (1024 * 1024))
            stats = _scan_model_file(mf)
            result_cities[city_key] = {
                "file": mf.name,
                "size_mb": round(mf.stat().st_size / (1024 * 1024)),
                **stats,
            }
            logger.info("  %s: %d commuters (%s)",
                        city_key,
                        stats["commuters"],
                        ", ".join(f"{m}={c:,}" for m, c in
                                  sorted(stats["mode_counts"].items())))

    # Check if any files were removed from cache
    if set(cached_cities.keys()) != set(result_cities.keys()):
        any_changed = True

    # Write cache if anything changed
    if any_changed:
        import datetime
        cache_data = {
            "cities": result_cities,
            "_fingerprints": fingerprints,
            "scan_timestamp": datetime.datetime.now().isoformat(),
        }
        try:
            with open(cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)
            logger.info("Cache updated: %s", cache_path)
        except OSError as e:
            logger.warning("Could not write cache: %s", e)

    return {"cities": result_cities}


def get_city_stats(city_key: str, modelgen_dir: Optional[Path] = None) -> Optional[dict]:
    """Get stats for a single city. Returns None if not found."""
    data = scan_modelgen_dir(modelgen_dir=modelgen_dir)
    return data["cities"].get(city_key)


if __name__ == "__main__":
    """Quick test: scan and print results."""
    logging.basicConfig(level=logging.INFO)
    data = scan_modelgen_dir(force="--force" in __import__("sys").argv)
    for city, stats in sorted(data["cities"].items()):
        car = stats["mode_counts"].get("car", 0)
        total = stats["commuters"]
        print(f"\n{city}:")
        print(f"  File:       {stats['file']} ({stats['size_mb']} MB)")
        print(f"  Buildings:  {stats['total_buildings']:,}")
        print(f"  Households: {stats['total_households']:,}")
        print(f"  Persons:    {stats['total_persons']:,}")
        print(f"  Commuters:  {total:,}")
        print(f"  By mode:    {stats['mode_counts']}")
        print(f"  Car-only:   ~{car:,} trips")
        print(f"  All modes:  ~{total:,} trips")
