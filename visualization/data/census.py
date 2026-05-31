"""Load US Census Bureau tract shapefiles for choropleth rendering.

Files are cached under ``cache/census/<state_fips>/`` by
``tools/download_census_tracts.py``. This module loads them, filters
to the scenarios' geographic bbox, and exposes per-tract polygons
ready for point-in-polygon aggregation.

The loader uses ``pyshp`` (pure-Python shapefile reader) and
``shapely`` (the latter is already a SimForge dep). No geopandas
required, keeps the dep footprint light.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TractPolygon:
    """One census tract polygon with its identifying metadata."""

    geoid: str           # e.g. "17031839100" (Cook County, tract 8391.00)
    state_fp: str        # e.g. "17"
    county_fp: str       # e.g. "031"
    tract_ce: str        # e.g. "839100"
    name: str            # e.g. "Census Tract 8391"
    county_name: str     # e.g. "Cook County"
    rings: list[list[tuple[float, float]]] = field(default_factory=list)
    """Polygon rings as ordered (lon, lat) sequences. The first ring is
    the outer boundary; subsequent rings (rare) are interior holes."""
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)


def census_cache_dir(state_fips: str) -> Path:
    return Path("cache") / "census" / state_fips.zfill(2)


def is_state_cached(state_fips: str) -> bool:
    d = census_cache_dir(state_fips)
    return all(
        (d / f"cb_2024_{state_fips.zfill(2)}_tract_500k{ext}").is_file()
        for ext in (".shp", ".shx", ".dbf")
    )


def detect_state_for_bbox(
    bbox: tuple[float, float, float, float],
) -> str | None:
    """Pick a state FIPS by checking which cached state's shapefile bbox covers ``bbox``.

    Returns the first match. None if no cached state covers it.
    """
    base = Path("cache") / "census"
    if not base.is_dir():
        return None
    for state_dir in sorted(base.iterdir()):
        if not state_dir.is_dir():
            continue
        state_fips = state_dir.name
        if not is_state_cached(state_fips):
            continue
        # Use the shapefile's overall bbox as a quick filter
        try:
            import shapefile  # lazy
            sf = shapefile.Reader(
                str(state_dir / f"cb_2024_{state_fips}_tract_500k.shp")
            )
            sb = sf.bbox  # (xmin, ymin, xmax, ymax)
            sf.close()
            if (sb[0] <= bbox[0] and sb[1] <= bbox[1]
                    and sb[2] >= bbox[2] and sb[3] >= bbox[3]):
                return state_fips
        except Exception as e:
            logger.warning("Could not check %s: %s", state_dir, e)
            continue
    return None


def load_tracts_in_bbox(
    state_fips: str,
    bbox: tuple[float, float, float, float] | None = None,
    pad_frac: float = 0.05,
) -> list[TractPolygon]:
    """Load all tract polygons from a state, optionally filtered to a bbox.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)``. Tracts whose
    bounding boxes do not intersect the (padded) bbox are skipped to
    keep memory + render time low.
    """
    import shapefile  # lazy

    state_fips = state_fips.zfill(2)
    cache = census_cache_dir(state_fips)
    shp_path = cache / f"cb_2024_{state_fips}_tract_500k.shp"
    if not shp_path.is_file():
        raise FileNotFoundError(
            f"State {state_fips} census tracts not cached at {shp_path}. "
            f"Run: python -m tools.download_census_tracts --state {state_fips}"
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

    tracts: list[TractPolygon] = []
    total_shapes = 0
    for shape_rec in sf.shapeRecords():
        total_shapes += 1
        shape = shape_rec.shape
        rec = shape_rec.record
        if not shape.points:
            continue
        sb = shape.bbox
        if bbox is not None and not bbox_intersects(sb, bbox):
            continue

        # Split shape.points into rings using shape.parts as ring start indices.
        rings: list[list[tuple[float, float]]] = []
        parts = list(shape.parts) + [len(shape.points)]
        for i in range(len(parts) - 1):
            ring = [(p[0], p[1]) for p in shape.points[parts[i]:parts[i + 1]]]
            if len(ring) >= 3:
                rings.append(ring)

        if not rings:
            continue

        tracts.append(TractPolygon(
            geoid=rec[field_idx["GEOID"]],
            state_fp=rec[field_idx["STATEFP"]],
            county_fp=rec[field_idx["COUNTYFP"]],
            tract_ce=rec[field_idx["TRACTCE"]],
            name=rec[field_idx.get("NAMELSAD", field_idx["NAME"])],
            county_name=rec[field_idx.get("NAMELSADCO", field_idx["STATEFP"])],
            rings=rings,
            bbox=tuple(sb),
        ))

    sf.close()
    logger.info(
        "Loaded %d tracts from state %s (bbox-filtered from %d shapes)",
        len(tracts), state_fips, total_shapes,
    )
    return tracts
