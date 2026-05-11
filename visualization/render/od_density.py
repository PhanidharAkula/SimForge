"""Origin / destination density visualization — Phase A's flagship map.

Two render styles supported:

- ``style="dots"`` (default): proportional-symbol map. One circle per
  demand-carrying node, with circle area + color both encoding trip
  count. Classical cartography for sparse data — natural for the
  1k-trip / 50k-trip range where most nodes have 0 trips.
- ``style="hex"``: hexagonal binning. Better for very dense data
  (200k+) where individual nodes blur. Pre-V Phase A used this
  exclusively.

The basemap is the canonical SimForge road network underneath, faded
so the dots/hexes dominate the visual.
"""

from __future__ import annotations

from pathlib import Path

from visualization.data.bundle import Demand, Network
from visualization.render.basemap import render_basemap


# Default basemap filter: keep only the major road backbone.
# Pass exclude_highway_types=() to render every link (busy "drawing" look).
_MAJOR_ROAD_TYPES: frozenset[str] = frozenset({
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
})


def render_od_density(
    network: Network,
    demand: Demand,
    *,
    side: str = "origin",
    output_path: Path,
    title: str | None = None,
    style: str = "dots",
    gridsize: int = 60,
    cmap: str = "dark_heat",
    dpi: int = 220,
    figsize: tuple[float, float] = (14.0, 10.0),
    include_highway_types: tuple[str, ...] | None = None,
    show_basemap: bool = True,
    color_norm: str = "log",
    color_norm_gamma: float = 0.5,
    fill_empty: bool = False,
    dot_size: float = 18.0,
) -> Path:
    """Render an origin- or destination-density hexbin onto the basemap.

    Parameters
    ----------
    network : Network
    demand : Demand
    side : "origin" or "destination"
    output_path : Path
        Where to write the PNG.
    title : str, optional
        Custom title; default ``"Trip {side} density"``.
    gridsize : int
        Hexbin grid resolution. ~50 gives clean readable blocks for a
        4 km² city; bump to 100+ for la_50k_car (much larger area).
    cmap : str
        Matplotlib colormap. ``magma`` is the default (high-contrast
        perceptually uniform). ``Spectral_r`` for SEARUMS aesthetic.
    dpi : int
    figsize : (w, h)
    include_highway_types : tuple of str, optional
        Override the default "major roads only" basemap filter. Pass an
        empty tuple ``()`` to render every link, or a custom list to
        target specific types.
    show_basemap : bool
        Set False to render only the heatmap (no road context).
    color_norm : "linear" | "power" | "log"
        Color-scale normalization. ``"power"`` (default) uses
        ``PowerNorm(gamma=color_norm_gamma)`` to expand the low end so
        small counts are visible.
    color_norm_gamma : float
        Power exponent (0.5 = sqrt; 0.3 = even more low-end expansion).

    Returns
    -------
    Path
        ``output_path`` after writing.
    """
    if side not in ("origin", "destination"):
        raise ValueError(f"side must be 'origin' or 'destination', got {side!r}")
    if style not in ("dots", "hex"):
        raise ValueError(f"style must be 'dots' or 'hex', got {style!r}")

    import matplotlib  # lazy import
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap, LogNorm, PowerNorm

    # Custom dark colormaps that have NO white/light end. Each one stays
    # clearly visible against a white background at every count level
    # while also having enough dynamic range to differentiate low vs
    # high counts via hue variation.
    _DARK_CMAPS_TRUNCATED = {
        # base colormap, low fraction, high fraction
        "magma_dark":   ("magma",   0.15, 0.85),  # dark blue -> bright pink
        "inferno_dark": ("inferno", 0.20, 0.85),  # dark red -> bright orange
        "viridis_dark": ("viridis", 0.10, 0.75),  # dark purple -> teal-green
        "plasma_dark":  ("plasma",  0.15, 0.85),  # dark purple -> bright pink
    }
    # Hand-picked multi-hue dark palette: navy -> blue -> purple -> magenta -> red.
    # All saturated dark/medium colors, visible against white, with strong
    # hue variation so even small dots clearly differentiate by count.
    _DARK_CUSTOM = {
        "dark_heat":      ["#0a1a4a", "#1a3a8a", "#5a1a8a", "#a01a5a", "#c81a1a"],
        "dark_spectral":  ["#0a3a5a", "#1a7a5a", "#7a8a1a", "#c85a1a", "#a01a3a"],
        "dark_fire":      ["#3a0a3a", "#7a0a4a", "#b01a3a", "#d04a1a", "#e08a1a"],
    }
    if cmap in _DARK_CMAPS_TRUNCATED:
        base_name, lo, hi = _DARK_CMAPS_TRUNCATED[cmap]
        base = matplotlib.colormaps[base_name]
        cmap_obj = LinearSegmentedColormap.from_list(
            cmap, base(np.linspace(lo, hi, 256))
        )
    elif cmap in _DARK_CUSTOM:
        cmap_obj = LinearSegmentedColormap.from_list(cmap, _DARK_CUSTOM[cmap])
    else:
        cmap_obj = cmap

    counts = demand.origin_counts if side == "origin" else demand.destination_counts
    points = [
        (network.nodes[nid], n)
        for nid, n in counts.items()
        if nid in network.nodes
    ]
    if not points:
        raise ValueError(
            f"No {side} coordinates found in network — demand and network may be misaligned"
        )

    xs = [p[0][0] for p in points]
    ys = [p[0][1] for p in points]
    ns = [p[1] for p in points]
    total_trips = sum(ns)

    if color_norm == "log":
        norm = LogNorm(vmin=1, vmax=max(ns))
    elif color_norm == "power":
        norm = PowerNorm(gamma=color_norm_gamma, vmin=1, vmax=max(ns))
    else:
        norm = None

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if show_basemap:
        basemap_exclude = ("footway", "path", "steps", "cycleway", "pedestrian")
        if include_highway_types is None:
            render_basemap(network, ax, exclude_highway_types=basemap_exclude)
        elif include_highway_types == ():
            render_basemap(network, ax)
        else:
            render_basemap(network, ax, include_highway_types=include_highway_types)

    if style == "dots":
        # Uniform small dots — count is encoded by color only. The dark
        # colormap means even the lowest-count nodes are visible against
        # the white background; high-count nodes pop in the brightest end
        # of the truncated palette.
        sc = ax.scatter(
            xs, ys, s=dot_size, c=ns,
            cmap=cmap_obj, alpha=0.95, zorder=3,
            edgecolors="none", linewidths=0,
            norm=norm,
        )
        cbar = fig.colorbar(sc, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
        cbar.set_label(f"trips per node ({side}s)", fontsize=10)
        cbar.outline.set_linewidth(0.5)
        cbar.ax.tick_params(labelsize=9)
        meta = (
            f"SimForge  ·  {len(network.nodes):,} nodes  ·  "
            f"{len(network.links):,} links  ·  "
            f"{len(points):,} demand-carrying nodes  ·  "
            f"cmap={cmap}  ·  norm={color_norm}  ·  dot_size={dot_size}"
        )
    else:
        # Hex binning — better for very dense data.
        hb = ax.hexbin(
            [p[0][0] for p in points for _ in range(p[1])],
            [p[0][1] for p in points for _ in range(p[1])],
            gridsize=gridsize, cmap=cmap_obj,
            mincnt=0 if fill_empty else 1,
            alpha=0.92, zorder=3,
            edgecolors="white", linewidths=0.3,
            norm=norm,
        )
        cbar = fig.colorbar(hb, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
        cbar.set_label(f"trips per hex ({side}s)", fontsize=10)
        cbar.outline.set_linewidth(0.5)
        cbar.ax.tick_params(labelsize=9)
        meta = (
            f"SimForge  ·  {len(network.nodes):,} nodes  ·  "
            f"{len(network.links):,} links  ·  "
            f"hexgrid={gridsize}  ·  cmap={cmap}  ·  norm={color_norm}"
        )

    if title is None:
        title = f"Trip {side} density  —  N={total_trips:,}"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    fig.text(0.5, 0.015, meta, ha="center", fontsize=7, color="#888")

    fig.tight_layout(pad=0.8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    return output_path
