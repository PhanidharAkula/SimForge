"""Load US Census Bureau TIGER/Line PRISECROADS shapefiles.

Returns road polylines (with proper curve geometry) ready for
matplotlib rendering as the choropleth basemap. Caches under
``cache/tiger_roads/<state_fips>/`` (populated by
``tools/download_tiger_roads.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# MTFCC codes from TIGER/Line spec.
MTFCC_PRIMARY = "S1100"     # Interstate / primary
MTFCC_SECONDARY = "S1200"   # US / state highway


@dataclass
class RoadLine:
    """One road polyline (one part of one road feature)."""

    mtfcc: str
    fullname: str
    points: list[tuple[float, float]]   # (lon, lat) sequence with curves preserved


def tiger_roads_cache_dir(state_fips: str) -> Path:
    return Path("cache") / "tiger_roads" / state_fips.zfill(2)


def is_state_cached(state_fips: str) -> bool:
    d = tiger_roads_cache_dir(state_fips)
    return all(
        (d / f"tl_2024_{state_fips.zfill(2)}_prisecroads{ext}").is_file()
        for ext in (".shp", ".shx", ".dbf")
    )


def load_roads_in_bbox(
    state_fips: str,
    bbox: tuple[float, float, float, float] | None = None,
    pad_frac: float = 0.05,
) -> list[RoadLine]:
    """Load all primary+secondary roads from a state, optionally bbox-filtered.

    The shapefile bbox-test on each polyline is cheap and skips most
    features for small scenarios. For statewide scenarios (nyc_500k_car
    covers most of NYC area), the loader still returns thousands of lines.
    """
    import shapefile  # lazy

    state_fips = state_fips.zfill(2)
    cache = tiger_roads_cache_dir(state_fips)
    shp_path = cache / f"tl_2024_{state_fips}_prisecroads.shp"
    if not shp_path.is_file():
        raise FileNotFoundError(
            f"TIGER roads for state {state_fips} not cached. Run:\n"
            f"  python -m tools.download_tiger_roads --state {state_fips}"
        )

    if bbox is not None:
        pad_x = (bbox[2] - bbox[0]) * pad_frac
        pad_y = (bbox[3] - bbox[1]) * pad_frac
        bbox = (bbox[0] - pad_x, bbox[1] - pad_y,
                bbox[2] + pad_x, bbox[3] + pad_y)

    def bbox_intersects(a, b) -> bool:
        return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

    sf = shapefile.Reader(str(shp_path))
    fields = [f[0] for f in sf.fields[1:]]
    field_idx = {name: i for i, name in enumerate(fields)}

    roads: list[RoadLine] = []
    for shape_rec in sf.shapeRecords():
        shape = shape_rec.shape
        rec = shape_rec.record
        if not shape.points:
            continue
        if bbox is not None and not bbox_intersects(shape.bbox, bbox):
            continue

        parts = list(shape.parts) + [len(shape.points)]
        mtfcc = rec[field_idx["MTFCC"]]
        fullname = rec[field_idx.get("FULLNAME", 0)] or ""
        for i in range(len(parts) - 1):
            pts = [(p[0], p[1]) for p in shape.points[parts[i]:parts[i + 1]]]
            if len(pts) >= 2:
                roads.append(RoadLine(mtfcc=mtfcc, fullname=fullname, points=pts))

    sf.close()
    logger.info("Loaded %d road polylines from state %s", len(roads), state_fips)
    return roads
