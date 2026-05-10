"""Render the SimForge canonical network as a matplotlib basemap.

No internet, no third-party tile service. The basemap is the same road
graph the simulator was given — clean, deterministic, hash-pinned via
the bundle's manifest.

Highway types from the OSM tags are used to grade line weight + colour
so primary arterials read clearly under any overlay (heatmap, choropleth).
"""

from __future__ import annotations

from typing import Iterable

from visualization.data.bundle import Network


# Grouped by visual prominence — tuples of (highway types, line width, alpha).
# Highway types not in this list fall through to the unclassified bucket.
_HIGHWAY_STYLES: tuple[tuple[tuple[str, ...], float, float, str], ...] = (
    (("motorway", "motorway_link", "trunk", "trunk_link"), 1.0, 0.85, "#666666"),
    (("primary", "primary_link", "secondary", "secondary_link"), 0.7, 0.7, "#888888"),
    (("tertiary", "tertiary_link", "residential", "unclassified"), 0.4, 0.55, "#aaaaaa"),
    (("living_street", "service", "track"), 0.25, 0.4, "#bbbbbb"),
    (("footway", "cycleway", "pedestrian", "path", "steps"), 0.15, 0.25, "#cccccc"),
)


def _style_for(highway_type: str) -> tuple[float, float, str]:
    for types, lw, alpha, color in _HIGHWAY_STYLES:
        if highway_type in types:
            return lw, alpha, color
    # Default: same as residential
    return 0.4, 0.55, "#aaaaaa"


def render_basemap(
    network: Network,
    ax,
    *,
    include_highway_types: Iterable[str] | None = None,
    exclude_highway_types: Iterable[str] | None = None,
) -> None:
    """Render ``network`` onto a matplotlib ``Axes`` as line segments.

    Parameters
    ----------
    network : Network
        Loaded bundle network (nodes + links).
    ax : matplotlib.axes.Axes
        Target axes. Aspect is set to 'equal' so x/y scaling is geographic.
    include_highway_types, exclude_highway_types : iterable of str, optional
        Filter which OSM highway types to draw. By default all are drawn.
        Useful for "drop pedestrian noise" by passing
        ``exclude_highway_types=["footway", "path", "steps"]``.

    The basemap is rendered using LineCollection batches per style group
    so 470k links (la_50k_car) render in <2 seconds without per-link
    overhead.
    """
    from matplotlib.collections import LineCollection  # lazy import

    include = set(include_highway_types) if include_highway_types else None
    exclude = set(exclude_highway_types) if exclude_highway_types else set()

    # Group segments by style so each style group becomes one LineCollection.
    by_style: dict[tuple[float, float, str], list] = {}
    for from_id, to_id, ht in network.links:
        if include is not None and ht not in include:
            continue
        if ht in exclude:
            continue
        f = network.nodes.get(from_id)
        t = network.nodes.get(to_id)
        if not f or not t:
            continue
        style = _style_for(ht)
        by_style.setdefault(style, []).append([f, t])

    for (lw, alpha, color), segs in sorted(by_style.items()):
        lc = LineCollection(segs, linewidths=lw, alpha=alpha, colors=color, zorder=1)
        ax.add_collection(lc)

    bbox = network.bbox
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        pad_x = (max_lon - min_lon) * 0.02
        pad_y = (max_lat - min_lat) * 0.02
        ax.set_xlim(min_lon - pad_x, max_lon + pad_x)
        ax.set_ylim(min_lat - pad_y, max_lat + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
