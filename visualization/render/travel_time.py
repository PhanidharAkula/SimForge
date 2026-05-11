"""travel_time renderer (Phase B).

Per-tract choropleth of mean trip travel time by ORIGIN tract — for
each census tract, what's the average travel time of trips that
originate there, as observed by one engine.

Reuses the choropleth aesthetic from od_choropleth.py (CityScape-style
log palette + TIGER roads basemap), but the metric being colored is
mean travel time per origin tract, not trip count.
"""

from __future__ import annotations

import logging
from pathlib import Path

from visualization.data.bundle import Demand, Network
from visualization.data.census import (
    detect_state_for_bbox, load_tracts_in_bbox,
)
from visualization.data.results import TripAggregation

logger = logging.getLogger(__name__)


def render_travel_time_choropleth(
    network: Network,
    demand: Demand,
    aggregation: TripAggregation,
    *,
    output_path: Path,
    title: str | None = None,
    engine: str = "",
    state_fips: str | None = None,
    show_basemap: bool = True,
    dpi: int = 220,
    figsize: tuple[float, float] = (14.0, 10.0),
) -> Path:
    """Choropleth of mean per-trip travel time by census tract.

    Each tract gets the mean travel time of all trips originating at
    nodes inside the tract polygon. Empty tracts (no demand origins
    inside) render as light gray.
    """
    bbox = network.bbox
    if bbox is None:
        raise ValueError("Empty network — cannot render choropleth")
    if state_fips is None:
        state_fips = detect_state_for_bbox(bbox)
    if state_fips is None:
        raise FileNotFoundError(
            "No cached census state covers this bbox. Run:\n"
            "  python -m tools.download_census_tracts --all-bundled"
        )

    logger.info("Loading tracts for state %s within bbox...", state_fips)
    tracts = load_tracts_in_bbox(state_fips, bbox=bbox)
    logger.info("  %d tracts kept", len(tracts))

    # Spatial join: for each demand-carrying node, find its tract.
    from shapely.geometry import Point, Polygon
    from shapely.strtree import STRtree

    polys = [Polygon(t.rings[0]) for t in tracts]
    geoids = [t.geoid for t in tracts]
    tree = STRtree(polys)

    # Per-tract aggregation of trip durations.
    tract_total_duration: dict[str, float] = {}
    tract_trip_count: dict[str, int] = {}

    for nid, tt_total in aggregation.node_total_duration_s.items():
        n_trips = aggregation.node_counts.get(nid, 0)
        coord = network.nodes.get(nid)
        if coord is None or n_trips == 0:
            continue
        pt = Point(coord[0], coord[1])
        for idx in tree.query(pt):
            if polys[idx].contains(pt):
                gid = geoids[idx]
                tract_total_duration[gid] = tract_total_duration.get(gid, 0.0) + tt_total
                tract_trip_count[gid] = tract_trip_count.get(gid, 0) + n_trips
                break

    tract_mean_tt: dict[str, float] = {
        gid: tract_total_duration[gid] / tract_trip_count[gid]
        for gid in tract_total_duration
        if tract_trip_count[gid] > 0
    }
    logger.info("  %d tracts received >=1 trip, mean TT range: %.1fs - %.1fs",
                len(tract_mean_tt),
                min(tract_mean_tt.values()) if tract_mean_tt else 0,
                max(tract_mean_tt.values()) if tract_mean_tt else 0)

    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.colors import Normalize

    # Travel time uses a green->yellow->red gradient (low TT = good=green,
    # high TT = bad=red). Linear norm — TT distributions are usually less
    # skewed than count distributions.
    cmap_obj = matplotlib.colormaps["RdYlGn_r"]
    if tract_mean_tt:
        norm = Normalize(vmin=min(tract_mean_tt.values()),
                         vmax=max(tract_mean_tt.values()))
    else:
        norm = Normalize(vmin=0, vmax=1)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    empty_polys = [t.rings[0] for t in tracts if t.geoid not in tract_mean_tt]
    colored_polys = [t.rings[0] for t in tracts if t.geoid in tract_mean_tt]
    colored_vals = [tract_mean_tt[t.geoid] for t in tracts if t.geoid in tract_mean_tt]

    if empty_polys:
        ax.add_collection(PolyCollection(
            empty_polys, facecolor="#dddddd", edgecolor="#222222",
            linewidth=0.4, zorder=1,
        ))
    if colored_polys:
        colors = [cmap_obj(norm(v)) for v in colored_vals]
        ax.add_collection(PolyCollection(
            colored_polys, facecolors=colors, edgecolor="#222222",
            linewidth=0.4, zorder=2,
        ))

    if show_basemap:
        from visualization.data.tiger_roads import is_state_cached, load_roads_in_bbox
        if is_state_cached(state_fips):
            roads = load_roads_in_bbox(state_fips, bbox=bbox)
            segs = [r.points for r in roads]
            if segs:
                ax.add_collection(LineCollection(
                    segs, linewidths=0.7, colors="#1a1a1a", alpha=0.7,
                    zorder=3, capstyle="round", joinstyle="round",
                ))

    pad_x = (bbox[2] - bbox[0]) * 0.02
    pad_y = (bbox[3] - bbox[1]) * 0.02
    ax.set_xlim(bbox[0] - pad_x, bbox[2] + pad_x)
    ax.set_ylim(bbox[1] - pad_y, bbox[3] + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    sm = plt.cm.ScalarMappable(cmap=cmap_obj, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
    cbar.set_label("mean travel time (s) per origin tract", fontsize=10)
    cbar.outline.set_linewidth(0.5)
    cbar.ax.tick_params(labelsize=9)

    if title is None:
        title = f"Mean travel time by origin tract — {engine}  —  N={demand.trip_count:,}"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.5, 0.015,
        f"SimForge  ·  {len(tracts):,} tracts  ·  {len(tract_mean_tt):,} non-empty"
        f"  ·  state FIPS {state_fips}  ·  engine={engine}  ·  cmap=RdYlGn_r",
        ha="center", fontsize=7, color="#888",
    )

    fig.tight_layout(pad=0.8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    return output_path
