"""Download US Census Bureau Cartographic Boundary tract shapefiles.

These are pre-simplified for cartographic use (much smaller than the
full TIGER/Line survey-grade shapefiles), perfect for choropleth maps.
Public-domain, free to download.

Files land under ``cache/census/<state_fips>/`` and are auto-detected
by the visualization component when rendering choropleth maps.

Usage::

    # Download for a specific state by FIPS code:
    python -m tools.download_census_tracts --state 17  # Illinois (Chicago)
    python -m tools.download_census_tracts --state 36  # New York
    python -m tools.download_census_tracts --state 06  # California (LA)

    # Download all states needed for the bundled benchmark scenarios:
    python -m tools.download_census_tracts --all-bundled
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

CB_BASE_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp"

# State FIPS codes for the cities the bundled benchmark scenarios cover.
BUNDLED_STATES: dict[str, str] = {
    "17": "Illinois (chicago_1k_car, chicago_200k_car)",
    "36": "New York (nyc_10k_car, nyc_500k_car)",
    "06": "California (la_50k_car)",
}


def _cache_dir(state_fips: str) -> Path:
    """Standard cache location for a state's tract shapefiles."""
    return Path("cache") / "census" / state_fips


def is_cached(state_fips: str) -> bool:
    """Check if the unzipped .shp / .shx / .dbf already exist locally."""
    d = _cache_dir(state_fips)
    return all((d / f"cb_2024_{state_fips}_tract_500k{ext}").is_file()
               for ext in (".shp", ".shx", ".dbf"))


def download_state_tracts(state_fips: str, force: bool = False) -> Path:
    """Download + unzip the Cartographic Boundary tract file for a state.

    Returns the cache directory containing .shp / .shx / .dbf / .prj.
    """
    cache = _cache_dir(state_fips)
    if not force and is_cached(state_fips):
        logger.info("[%s] already cached at %s", state_fips, cache)
        return cache

    cache.mkdir(parents=True, exist_ok=True)
    fname = f"cb_2024_{state_fips}_tract_500k.zip"
    url = f"{CB_BASE_URL}/{fname}"
    zip_path = cache / fname

    logger.info("[%s] downloading %s", state_fips, url)
    with urllib.request.urlopen(url) as resp, open(zip_path, "wb") as out:
        shutil.copyfileobj(resp, out)
    logger.info("[%s] downloaded %.1f MB", state_fips, zip_path.stat().st_size / 1e6)

    logger.info("[%s] unzipping into %s", state_fips, cache)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cache)

    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (cache / f"{fname}.sha256").write_text(sha + "\n", encoding="utf-8")
    logger.info("[%s] sha256 %s", state_fips, sha[:16] + "...")

    if not is_cached(state_fips):
        raise RuntimeError(
            f"Download succeeded but expected files not found in {cache}"
        )
    return cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", action="append", default=[],
                        help="State FIPS code to download (e.g. 17 for IL). "
                             "May be repeated.")
    parser.add_argument("--all-bundled", action="store_true",
                        help="Download all states needed for bundled scenarios "
                             f"({', '.join(BUNDLED_STATES.keys())})")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if cache exists.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    states = list(args.state)
    if args.all_bundled:
        states.extend(BUNDLED_STATES.keys())
    if not states:
        print("Error: pass --state <fips> or --all-bundled", file=sys.stderr)
        print(f"Bundled states: {BUNDLED_STATES}", file=sys.stderr)
        return 2

    seen = set()
    for state in states:
        state = state.zfill(2)
        if state in seen:
            continue
        seen.add(state)
        try:
            cache = download_state_tracts(state, force=args.force)
            print(f"[OK]   {state}  {BUNDLED_STATES.get(state, '(custom)')}: {cache}")
        except Exception as e:
            print(f"[FAIL] {state}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
