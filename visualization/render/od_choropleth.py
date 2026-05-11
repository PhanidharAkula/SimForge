"""Choropleth renderer — CityScape-style filled-polygon trip density.

For each US Census tract polygon overlapping the scenario's bbox,
counts how many trip origins (or destinations) fall inside, then
colors the polygon using CityScape's exact log-scale palette
(reproduced from ``cb_2024_*_tract_500k.dbf`` joined with our
demand.csv via point-in-polygon).

The aesthetic match:
- 100-step blue→red gradient (same as cityscape's color indexes 33-132)
- Light gray (#dddddd) for tracts with zero demand (cityscape's index 32)
- Log scale: ``color = 32 + log10(value/10) * 30`` (DrawShapes.cpp:215)
- Thin black tract borders for cartographic clarity
- Optional faded road network on top for geographic anchoring
"""

from __future__ import annotations

import logging
from pathlib import Path

from visualization.data.bundle import Demand, Network
from visualization.data.census import (
    TractPolygon, detect_state_for_bbox, load_tracts_in_bbox,
)

logger = logging.getLogger(__name__)


# CityScape's exact color logic from DrawShapes.cpp:215 — reproduced as Python.
# Their color index 32 = empty (light gray), 33-132 = 100-step gradient.
# Their endpoints (from the .fig palette we have): #0a0ae1 (blue) -> #e10a0a (red).
def _cityscape_color_index(value: int) -> int:
    """Reproduce CityScape's getColor() exactly."""
    import math
    if value < 10:
        return 32
    return int(min(132, 32 + math.log10(value / 10) * 30))


def _build_cityscape_cmap():
    """Build a matplotlib LinearSegmentedColormap matching CityScape's palette.

    Their palette declared in the .fig color table: 100 colors stepping
    from #0a0ae1 (blue) at index 33 to #e10a0a (red) at index 132. The
    intermediate colors blend through purple → magenta → red.
    """
    import matplotlib
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    # 5 anchor colors capturing CityScape's blue → blue-purple → magenta
    # → red-orange → red gradient. Manually picked to match the .fig file
    # color table at indexes 33, 58, 83, 108, 132.
    anchors = [
        "#0a0ae1",  # blue (index 33)
        "#5b1bcf",  # blue-purple (index 58)
        "#a02fb0",  # magenta (index 83)
        "#d04a4a",  # red-orange (index 108)
        "#e10a0a",  # bright red (index 132)
    ]
    return LinearSegmentedColormap.from_list("cityscape", anchors, N=100)


def aggregate_to_tracts(
    network: Network,
    demand: Demand,
    tracts: list[TractPolygon],
    side: str,
) -> dict[str, int]:
    """Spatially join trip endpoints to tract polygons.

    Returns ``{tract_geoid: trip_count}``. Tracts not in the dict have 0 trips.
    """
    from shapely.geometry import Point, Polygon
    from shapely.strtree import STRtree

    counts = demand.origin_counts if side == "origin" else demand.destination_counts
    points: list[tuple[Point, int]] = []
    for nid, count in counts.items():
        coord = network.nodes.get(nid)
        if coord is None:
            continue
        points.append((Point(coord[0], coord[1]), count))

    polygons: list[Polygon] = []
    geoids: list[str] = []
    for t in tracts:
        # Use only the outer ring; matplotlib + shapely both treat it as
        # polygon outer boundary. Holes are rare in census tracts and we
        # don't need pixel-perfect rendering for a heatmap.
        polygons.append(Polygon(t.rings[0]))
        geoids.append(t.geoid)

    tree = STRtree(polygons)
    tract_counts: dict[str, int] = {}
    for pt, n in points:
        # STRtree query returns indices of candidate polygons by bbox;
        # then test exact containment.
        for idx in tree.query(pt):
            if polygons[idx].contains(pt):
                tract_counts[geoids[idx]] = tract_counts.get(geoids[idx], 0) + n
                break  # a point is in at most one tract
    return tract_counts


def render_od_choropleth(
    network: Network,
    demand: Demand,
    *,
    side: str = "origin",
    output_path: Path,
    title: str | None = None,
    state_fips: str | None = None,
    show_basemap: bool = True,
    dpi: int = 220,
    figsize: tuple[float, float] = (14.0, 10.0),
    border_color: str = "#222222",
    border_width: float = 0.4,
    empty_color: str = "#dddddd",
) -> Path:
    """CityScape-style choropleth on real census tract polygons.

    Parameters
    ----------
    network, demand : as for ``render_od_density``
    side : "origin" | "destination"
    output_path : Path
    title : str, optional
    state_fips : str, optional
        State to load tracts from. Auto-detected from network bbox if None.
    show_basemap : bool
        Overlay the SimForge road network on top (faded). Default off —
        the choropleth speaks for itself; a basemap can compete visually.
    dpi : int
    figsize : (w, h)
    border_color, border_width : tract polygon border style
    empty_color : color for tracts with zero demand inside (CityScape's #dddddd)
    """
    if side not in ("origin", "destination"):
        raise ValueError(f"side must be 'origin' or 'destination', got {side!r}")

    bbox = network.bbox
    if bbox is None:
        raise ValueError("Empty network — cannot render choropleth")

    if state_fips is None:
        state_fips = detect_state_for_bbox(bbox)
    if state_fips is None:
        raise FileNotFoundError(
            "No cached census state covers this scenario's bbox. Run:\n"
            "  python -m tools.download_census_tracts --all-bundled"
        )

    logger.info("Loading tracts for state %s within scenario bbox...", state_fips)
    tracts = load_tracts_in_bbox(state_fips, bbox=bbox)
    logger.info("  %d tracts kept", len(tracts))

    logger.info("Spatially joining %d-trip demand to tracts...",
                demand.trip_count)
    tract_counts = aggregate_to_tracts(network, demand, tracts, side)
    logger.info("  %d tracts received >=1 trip", len(tract_counts))

    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LogNorm

    cmap = _build_cityscape_cmap()
    norm = LogNorm(vmin=1, vmax=max(tract_counts.values()) if tract_counts else 1)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Render empty tracts first (light gray), then colored tracts on top.
    empty_polys = [t.rings[0] for t in tracts if t.geoid not in tract_counts]
    colored_polys: list[list[tuple[float, float]]] = []
    colored_counts: list[int] = []
    for t in tracts:
        n = tract_counts.get(t.geoid, 0)
        if n > 0:
            colored_polys.append(t.rings[0])
            colored_counts.append(n)

    if empty_polys:
        empty_pc = PolyCollection(
            empty_polys, facecolor=empty_color,
            edgecolor=border_color, linewidth=border_width,
            zorder=1,
        )
        ax.add_collection(empty_pc)

    if colored_polys:
        # Use the colormap directly with norm to map count → color.
        colors = [cmap(norm(n)) for n in colored_counts]
        colored_pc = PolyCollection(
            colored_polys, facecolors=colors,
            edgecolor=border_color, linewidth=border_width,
            zorder=2,
        )
        ax.add_collection(colored_pc)

    if show_basemap:
        # Render TIGER/Line PRISECROADS on top of the colored tracts.
        # These are public-domain road polylines with proper curve geometry
        # preserved (unlike SimForge's intersection-only canonical network
        # which would render every road as a straight angular line).
        # Primary roads (interstates) thicker, secondary (US/state hwys) thinner.
        from matplotlib.collections import LineCollection

        from visualization.data.tiger_roads import (
            MTFCC_PRIMARY, MTFCC_SECONDARY, is_state_cached, load_roads_in_bbox,
        )
        if not is_state_cached(state_fips):
            logger.warning(
                "TIGER roads not cached for state %s — basemap skipped. Run:\n"
                "  python -m tools.download_tiger_roads --state %s",
                state_fips, state_fips,
            )
        else:
            roads = load_roads_in_bbox(state_fips, bbox=bbox)
            primary_segs = [r.points for r in roads if r.mtfcc == MTFCC_PRIMARY]
            secondary_segs = [r.points for r in roads if r.mtfcc == MTFCC_SECONDARY]
            if secondary_segs:
                ax.add_collection(LineCollection(
                    secondary_segs, linewidths=0.4, colors="#1a1a1a",
                    alpha=0.45, zorder=3, capstyle="round", joinstyle="round",
                ))
            if primary_segs:
                ax.add_collection(LineCollection(
                    primary_segs, linewidths=0.9, colors="#000000",
                    alpha=0.75, zorder=4, capstyle="round", joinstyle="round",
                ))

    # Set view bounds to the network bbox (with small padding).
    pad_x = (bbox[2] - bbox[0]) * 0.02
    pad_y = (bbox[3] - bbox[1]) * 0.02
    ax.set_xlim(bbox[0] - pad_x, bbox[2] + pad_x)
    ax.set_ylim(bbox[1] - pad_y, bbox[3] + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Colorbar driven by the same cmap+norm.
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
    cbar.set_label(f"trips per tract ({side}s)", fontsize=10)
    cbar.ax.tick_params(labelsize=9)
    cbar.outline.set_linewidth(0.5)

    if title is None:
        title = f"Trip {side} density by census tract  —  N={demand.trip_count:,}"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.5, 0.015,
        f"SimForge  ·  {len(tracts):,} census tracts  ·  "
        f"{len(tract_counts):,} non-empty  ·  state FIPS {state_fips}  ·  "
        f"CityScape-style log-scale palette  ·  source: US Census TIGER/Line CB 2024",
        ha="center", fontsize=7, color="#888",
    )

    fig.tight_layout(pad=0.8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    return output_path
