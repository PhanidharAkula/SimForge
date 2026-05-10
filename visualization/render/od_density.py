"""Origin / destination density choropleth — Phase A's flagship map.

Direct equivalent of the SEARUMS-style Chicago heatmap: shows where
trips originate (or terminate) on the actual road network. Aggregation
uses hexbin so it's deterministic and doesn't depend on scipy.

A single render call produces one PNG. The CLI calls this twice if
both ``od_origins`` and ``od_destinations`` are requested.
"""

from __future__ import annotations

from pathlib import Path

from visualization.data.bundle import Demand, Network
from visualization.render.basemap import render_basemap


def render_od_density(
    network: Network,
    demand: Demand,
    *,
    side: str = "origin",
    output_path: Path,
    title: str | None = None,
    gridsize: int = 60,
    cmap: str = "YlOrRd",
    dpi: int = 150,
    figsize: tuple[float, float] = (12.0, 9.0),
    exclude_highway_types: tuple[str, ...] | None = (
        "footway", "path", "steps", "cycleway",
    ),
    show_basemap: bool = True,
) -> Path:
    """Render an origin- or destination-density hexbin onto the basemap.

    Parameters
    ----------
    network : Network
        Bundle network (basemap source).
    demand : Demand
        Bundle demand (origin / destination IDs).
    side : "origin" or "destination"
        Which endpoint to plot.
    output_path : Path
        Where to write the PNG.
    title : str, optional
        Custom title; default ``"Trip {side}s — N={count}"``.
    gridsize : int
        Hexbin grid resolution. 60 gives ~3500 hexagons over a 4 km city.
    cmap : str
        Matplotlib colormap. ``YlOrRd`` matches SEARUMS aesthetic; try
        ``viridis`` for perceptually uniform.
    dpi : int
        Render DPI.
    figsize : (w, h)
        Figure size in inches.
    exclude_highway_types : tuple[str, ...]
        Highway types to exclude from the basemap. Default drops
        pedestrian noise so the choropleth reads more clearly.
    show_basemap : bool
        Set False to render only the heatmap (no road context).

    Returns
    -------
    Path
        ``output_path`` after writing.
    """
    if side not in ("origin", "destination"):
        raise ValueError(f"side must be 'origin' or 'destination', got {side!r}")

    import matplotlib  # lazy import
    matplotlib.use("Agg")  # non-interactive
    import matplotlib.pyplot as plt

    node_ids = demand.origins if side == "origin" else demand.destinations
    coords = [network.nodes.get(nid) for nid in node_ids]
    coords = [c for c in coords if c is not None]
    if not coords:
        raise ValueError(
            f"No {side} coordinates found in network — demand and network may be misaligned"
        )
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if show_basemap:
        render_basemap(network, ax, exclude_highway_types=exclude_highway_types)

    # Hexbin overlay. mincnt=1 so empty hexes stay transparent and the
    # basemap shows through.
    hb = ax.hexbin(
        xs, ys, gridsize=gridsize, cmap=cmap, mincnt=1, alpha=0.75, zorder=2,
        edgecolors="face", linewidths=0,
    )
    cbar = fig.colorbar(hb, ax=ax, shrink=0.6, pad=0.02)
    cbar.set_label(f"trips per hex ({side}s)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    if title is None:
        title = f"Trip {side}s — N={len(coords)} (gridsize={gridsize})"
    ax.set_title(title, fontsize=11)

    fig.text(
        0.5, 0.02,
        f"SimForge visualization — {len(network.nodes)} nodes, "
        f"{len(network.links)} links — basemap = canonical SimForge network",
        ha="center", fontsize=7, color="gray",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path
