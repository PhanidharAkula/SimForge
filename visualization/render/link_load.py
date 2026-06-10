"""link_load + congestion renderers (Phase B).

Shows per-engine simulated traffic on each road link in the SimForge
canonical network. Two modes:

- ``link_load``: color = total volume (vehicles per simulation horizon).
  Red = busiest links, blue = quiet.
- ``congestion``: color = ratio of simulated mean speed to free-flow
  speed. Red = congested (slow), green = free-flow.

Both reuse the same renderer with a different metric + colormap.

All three engines support ``link_load`` (volume): SUMO and MATSim link
volumes are reconstructed from their completed-trip route link
sequences, while DTALite reads ready-made volumes from
``link_performance.csv``. ``congestion`` (speed ratio) is DTALite-only,
since it is the one engine whose per-link output includes mean speed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from visualization.data.bundle import Network
from visualization.data.results import LinkPerformance

logger = logging.getLogger(__name__)


def render_link_metric(
    network: Network,
    links: list[LinkPerformance],
    *,
    metric: str = "volume",
    output_path: Path,
    title: str | None = None,
    engine: str = "",
    cmap: str | None = None,
    dpi: int = 220,
    figsize: tuple[float, float] | None = None,
    color_norm: str = "log",
    show_inactive: bool = True,
    line_width_min: float = 0.3,
    line_width_max: float = 2.5,
    use_osm_curves: bool = True,
    scenario_id: str | None = None,
) -> Path | None:
    """Render road links colored by a per-link metric.

    Parameters
    ----------
    network : Network
        Bundle network providing geometry (from/to node coords).
    links : list[LinkPerformance]
        Per-link metrics from one engine.
    metric : "volume" | "speed_ratio"
        Which field to color by. ``volume`` for link_load,
        ``speed_ratio`` for congestion (1.0 = freeflow, 0.0 = standstill).
    output_path : Path
    title : str, optional
    engine : str
        Engine label for the title + caption.
    cmap : str, optional
        Matplotlib colormap. Defaults: ``Reds`` for volume,
        ``RdYlGn`` (reversed for speed_ratio so green=fast, red=slow).
    color_norm : "linear" | "log"
        Volume distributions are heavily skewed → log default.
    show_inactive : bool
        Draw uncolored network as faded gray underneath, so the active
        links are silhouetted against the full road network.
    line_width_min, line_width_max : float
        Linear interpolation of line width from min metric to max.
    """
    if not links:
        raise ValueError(f"No link data: engine '{engine}' has no link_performance.csv")

    # Pick metric value per link.
    def metric_val(lp: LinkPerformance) -> float:
        if metric == "volume":
            return lp.volume
        if metric == "speed_ratio":
            return lp.speed_ratio
        raise ValueError(f"Unknown metric: {metric}")

    # Build link_id -> (volume) lookup. Engine ID prefix conventions:
    #   DTALite: int IDs (e.g. "1234"), which map to the bundle's "l1234".
    #   SUMO:    "lXXX" already.
    #   MATSim:  "lXXX" already.
    link_metric: dict[str, float] = {}
    for lp in links:
        # DTALite link IDs are bare integers; map to SimForge "lN" form.
        key_int = f"l{lp.link_id}" if lp.link_id.isdigit() else lp.link_id
        link_metric[key_int] = metric_val(lp)

    # Default colormaps
    if cmap is None:
        cmap = "Reds" if metric != "speed_ratio" else "RdYlGn"

    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LogNorm, Normalize

    cmap_obj = matplotlib.colormaps[cmap]

    # Build per-link polylines (curved if OSM way data is available).
    way_geoms: dict[int, list[tuple[float, float]]] = {}
    if use_osm_curves and scenario_id and network.link_osm_way_ids:
        from visualization.data.osm_ways import load_way_geometries
        needed = set()
        for ids in network.link_osm_way_ids.values():
            needed.update(ids)
        if needed:
            way_geoms = load_way_geometries(scenario_id, needed)

    inactive_segs: list = []
    active_segs: list = []
    active_vals: list[float] = []

    if way_geoms:
        from visualization.data.osm_ways import link_polyline
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id)
            t = network.nodes.get(to_id)
            if not f or not t:
                continue
            way_ids = network.link_osm_way_ids.get(lid, [])
            poly = link_polyline(
                lid, from_id, to_id, way_ids,
                way_geoms, network.nodes, network.node_osm_ids,
            )
            val = link_metric.get(lid)
            if val is None or val == 0:
                inactive_segs.append(poly)
            else:
                active_segs.append(poly)
                active_vals.append(val)
    else:
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id)
            t = network.nodes.get(to_id)
            if not f or not t:
                continue
            seg = [f, t]
            val = link_metric.get(lid)
            if val is None or val == 0:
                inactive_segs.append(seg)
            else:
                active_segs.append(seg)
                active_vals.append(val)

    if not active_vals:
        logger.warning(
            "No active link segments after match (link IDs: bundle prefix=l, "
            "engine prefix=%s). Falling back to inactive-only render.",
            "int" if links and links[0].link_id.isdigit() else "str",
        )

    if figsize is None:
        from visualization.data.bundle import figsize_for_bbox
        figsize = figsize_for_bbox(network.bbox) if network.bbox else (12.0, 10.0)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.subplots_adjust(left=0.02, right=0.92, top=0.93, bottom=0.05)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if show_inactive and inactive_segs:
        ax.add_collection(LineCollection(
            inactive_segs, linewidths=0.2, colors="#cccccc", alpha=0.6, zorder=1,
        ))

    if active_segs:
        if color_norm == "log":
            norm = LogNorm(vmin=max(min(active_vals), 0.01), vmax=max(active_vals))
        else:
            norm = Normalize(vmin=min(active_vals), vmax=max(active_vals))

        # Linewidth scales with metric value.
        vmin, vmax = min(active_vals), max(active_vals)
        widths = []
        for v in active_vals:
            if vmax == vmin:
                widths.append((line_width_min + line_width_max) / 2)
            else:
                widths.append(
                    line_width_min + (line_width_max - line_width_min)
                    * ((v - vmin) / (vmax - vmin)) ** 0.5
                )

        colors = [cmap_obj(norm(v)) for v in active_vals]
        ax.add_collection(LineCollection(
            active_segs, linewidths=widths, colors=colors,
            alpha=0.9, zorder=3, capstyle="round",
        ))

        sm = plt.cm.ScalarMappable(cmap=cmap_obj, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
        labels = {
            "volume": "vehicles per link",
            "speed_ratio": "speed / free-flow",
        }
        cbar.set_label(labels.get(metric, metric), fontsize=10)
        cbar.outline.set_linewidth(0.5)
        cbar.ax.tick_params(labelsize=9)

    bbox = network.bbox
    if bbox is not None:
        pad_x = (bbox[2] - bbox[0]) * 0.02
        pad_y = (bbox[3] - bbox[1]) * 0.02
        ax.set_xlim(bbox[0] - pad_x, bbox[2] + pad_x)
        ax.set_ylim(bbox[1] - pad_y, bbox[3] + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    if title is None:
        kind = {"volume": "load",
                "speed_ratio": "congestion"}.get(metric, metric)
        title = f"Link {kind}: {engine}  ·  {len(active_segs):,} active links"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.5, 0.015,
        f"SimForge  ·  {len(network.nodes):,} nodes  ·  "
        f"{len(network.links):,} links  ·  metric={metric}  ·  "
        f"engine={engine}  ·  norm={color_norm}",
        ha="center", fontsize=7, color="#888",
    )

    fig.tight_layout(pad=0.8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    return output_path


