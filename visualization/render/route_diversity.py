"""route_diversity renderer (Phase C).

Cross-engine map showing where multiple engines agree on route choice
vs where DTALite's UE assignment diverges from the BFS routes that
SUMO + MATSim share.

For each link in the SimForge canonical network:
- count how many of the 3 engines used it (engine_count)
- color by agreement: links used by all 3 = "consensus", by 2 = "partial",
  by 1 = "single-engine choice" (typically DTALite-only)

This visualizes the SUMO ≈ MATSim ≠ DTALite story documented in
README.md "Why SUMO and MATSim link_load look identical": the
"consensus" links are the SimForge-BFS routes both queue mobsims use;
the "DTALite-only" links are the alternative paths UE picks for flow
balancing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from visualization.data.bundle import Network
from visualization.data.results import LinkPerformance

logger = logging.getLogger(__name__)


# Color scheme: agreement level -> (color, linewidth, alpha, zorder, label).
# Render in zorder so single-engine (interesting!) ends up on top.
_AGREEMENT_STYLE: dict[int, tuple[str, float, float, int, str]] = {
    3: ("#888888", 0.6, 0.5,  3, "all 3 engines (SUMO + MATSim + DTALite)"),
    2: ("#1f77b4", 0.9, 0.7,  4, "2 of 3 engines"),
    1: ("#d62728", 1.4, 0.95, 5, "1 engine only (typically DTALite UE alternate)"),
}


def render_route_diversity(
    network: Network,
    engine_links: dict[str, list[LinkPerformance]],
    *,
    output_path: Path,
    title: str | None = None,
    dpi: int = 220,
    figsize: tuple[float, float] | None = None,
    use_osm_curves: bool = True,
    scenario_id: str | None = None,
) -> Path:
    """Render the cross-engine route-agreement map.

    Parameters
    ----------
    network : Network
        Bundle network (geometry source).
    engine_links : dict[engine_name -> list[LinkPerformance]]
        Per-engine link aggregations. Pass at least 2 engines; more
        gives finer-grained agreement bands.
    output_path : Path
    title : str, optional
    dpi : int
    figsize : (w, h)
    use_osm_curves : bool
    scenario_id : str, optional
        Required for OSM curve cache lookup.
    """
    if len(engine_links) < 2:
        raise ValueError(
            f"route_diversity needs >= 2 engines, got {list(engine_links.keys())}"
        )

    # Build per-link engine usage set: {link_id: {engines that used it}}
    link_engines: dict[str, set[str]] = {}
    for engine, links in engine_links.items():
        for lp in links:
            if lp.volume <= 0:
                continue
            key = f"l{lp.link_id}" if lp.link_id.isdigit() else lp.link_id
            link_engines.setdefault(key, set()).add(engine)

    # Resolve curved geometries if available.
    way_geoms: dict[int, list[tuple[float, float]]] = {}
    if use_osm_curves and scenario_id and network.link_osm_way_ids:
        from visualization.data.osm_ways import load_way_geometries
        needed = set()
        for ids in network.link_osm_way_ids.values():
            needed.update(ids)
        if needed:
            way_geoms = load_way_geometries(scenario_id, needed)

    # Bucket each link's polyline by agreement count.
    inactive_polys: list = []
    by_agreement: dict[int, list] = {1: [], 2: [], 3: []}

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
            engines = link_engines.get(lid, set())
            n = len(engines)
            if n == 0:
                inactive_polys.append(poly)
            else:
                # Cap at 3 (we have at most 3 engines)
                by_agreement[min(n, 3)].append(poly)
    else:
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id)
            t = network.nodes.get(to_id)
            if not f or not t:
                continue
            seg = [f, t]
            engines = link_engines.get(lid, set())
            n = len(engines)
            if n == 0:
                inactive_polys.append(seg)
            else:
                by_agreement[min(n, 3)].append(seg)

    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    if figsize is None:
        from visualization.data.bundle import figsize_for_bbox
        figsize = figsize_for_bbox(network.bbox) if network.bbox else (12.0, 10.0)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.subplots_adjust(left=0.02, right=0.92, top=0.93, bottom=0.05)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if inactive_polys:
        ax.add_collection(LineCollection(
            inactive_polys, linewidths=0.15, colors="#dddddd", alpha=0.6, zorder=1,
        ))

    legend_handles: list = []
    for agreement_count in sorted(by_agreement.keys()):
        segs = by_agreement[agreement_count]
        if not segs:
            continue
        color, lw, alpha, zorder, label = _AGREEMENT_STYLE[agreement_count]
        ax.add_collection(LineCollection(
            segs, linewidths=lw, colors=color, alpha=alpha, zorder=zorder,
            capstyle="round", joinstyle="round",
        ))
        legend_handles.append(Line2D(
            [0], [0], color=color, lw=lw * 2, alpha=alpha,
            label=f"{label}  ({len(segs):,} links)",
        ))

    ax.legend(
        handles=legend_handles, loc="lower right", fontsize=9, framealpha=0.95,
        edgecolor="#cccccc",
    )

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
        engines_used = sorted(engine_links.keys())
        title = f"Route diversity across {len(engines_used)} engines: {' + '.join(engines_used)}"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)

    fig.tight_layout(pad=0.8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    return output_path
