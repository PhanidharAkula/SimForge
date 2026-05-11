"""animated_flow renderer (Phase C).

Time-resolved animation of per-link traffic flow over the simulation
horizon. One frame per time bin (default 5-min windows); each frame
shows network links colored by vehicle throughput in that window.

Output: MP4 via matplotlib.animation + ffmpeg writer. Falls back to
GIF via Pillow writer if ffmpeg unavailable.

Currently MATSim-only: needs event-level data with timestamps, which
neither SUMO (without --fcd-output config change) nor DTALite (steady-
state UE) provides natively.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from visualization.data.bundle import Network

logger = logging.getLogger(__name__)


def render_animated_flow(
    network: Network,
    time_bin_loads: dict[int, dict[str, int]],
    *,
    output_path: Path,
    title: str | None = None,
    engine: str = "matsim",
    time_bin_seconds: int = 300,
    fps: int = 2,
    figsize: tuple[float, float] = (14.0, 10.0),
    dpi: int = 150,  # lower than statics so MP4 file stays compact
    cmap: str = "Reds",
    use_osm_curves: bool = True,
    scenario_id: str | None = None,
    line_width_min: float = 0.3,
    line_width_max: float = 2.5,
) -> Path:
    """Render an MP4 animation of link throughput over time.

    Parameters
    ----------
    network : Network
    time_bin_loads : dict[int, dict[str, int]]
        Per-bin per-link throughput from
        ``visualization.data.events.parse_matsim_throughput``.
        Keys are bin-start seconds-from-midnight.
    output_path : Path
        ``.mp4`` recommended (smaller file). ``.gif`` also supported.
    title : str, optional
    engine : str
    time_bin_seconds : int
        Width of each time bin (matches the parser's setting). Used
        for the per-frame timestamp label.
    fps : int
        Frames per second. 2-4 is good for a smooth-but-comprehensible
        time-lapse.
    figsize, dpi : matplotlib figure size + DPI per frame
    cmap : matplotlib colormap (Reds default for throughput).
    use_osm_curves, scenario_id : same as link_load — pulls OSM way
        polylines from the cache for proper curved rendering.
    """
    if not time_bin_loads:
        raise ValueError("No time-bin loads — empty events?")

    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.animation as animation
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LogNorm

    # Build per-link polylines (curved if OSM data is cached).
    way_geoms: dict[int, list[tuple[float, float]]] = {}
    if use_osm_curves and scenario_id and network.link_osm_way_ids:
        from visualization.data.osm_ways import load_way_geometries
        needed = set()
        for ids in network.link_osm_way_ids.values():
            needed.update(ids)
        if needed:
            way_geoms = load_way_geometries(scenario_id, needed)

    # Build a parallel arrays: link_id, polyline. Index aligned for
    # fast color lookup per frame.
    link_polys: list[list[tuple[float, float]]] = []
    link_ids: list[str] = []
    if way_geoms:
        from visualization.data.osm_ways import link_polyline
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id); t = network.nodes.get(to_id)
            if not f or not t:
                continue
            way_ids = network.link_osm_way_ids.get(lid, [])
            poly = link_polyline(
                lid, from_id, to_id, way_ids,
                way_geoms, network.nodes, network.node_osm_ids,
            )
            link_polys.append(poly)
            link_ids.append(lid)
    else:
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id); t = network.nodes.get(to_id)
            if not f or not t:
                continue
            link_polys.append([f, t])
            link_ids.append(lid)

    link_idx_by_id = {lid: i for i, lid in enumerate(link_ids)}

    # Compute global vmax for stable color norm across frames.
    global_max = max((c for v in time_bin_loads.values() for c in v.values()),
                     default=1)
    norm = LogNorm(vmin=1, vmax=max(global_max, 1))
    cmap_obj = matplotlib.colormaps[cmap]

    sorted_bins = sorted(time_bin_loads.keys())
    n_frames = len(sorted_bins)
    logger.info("Animating %d frames @ %d fps (~%ds video)",
                n_frames, fps, n_frames // max(fps, 1))

    # Figure setup
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

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

    # Faded inactive basemap underneath (always visible).
    ax.add_collection(LineCollection(
        link_polys, linewidths=0.15, colors="#dddddd", alpha=0.6, zorder=1,
    ))

    # Mutable LineCollection for "currently active" links.
    active_lc = LineCollection(
        [], linewidths=[], colors=[], alpha=0.92, zorder=3,
        capstyle="round",
    )
    ax.add_collection(active_lc)

    title_text = ax.set_title("", fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.5, 0.015,
        f"SimForge animated_flow  ·  engine={engine}  ·  "
        f"bin={time_bin_seconds}s  ·  fps={fps}  ·  "
        f"{len(network.links):,} links  ·  {n_frames} frames",
        ha="center", fontsize=7, color="#888",
    )

    # Optional: colorbar for the whole animation (constant scale).
    sm = plt.cm.ScalarMappable(cmap=cmap_obj, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.015, fraction=0.04)
    cbar.set_label(f"vehicles entering link / {time_bin_seconds}s window",
                   fontsize=10)
    cbar.outline.set_linewidth(0.5)
    cbar.ax.tick_params(labelsize=9)

    def _frame(frame_idx: int) -> tuple:
        bin_t = sorted_bins[frame_idx]
        loads = time_bin_loads[bin_t]
        active_polys: list = []
        active_widths: list[float] = []
        active_colors: list = []
        for lid, count in loads.items():
            if count <= 0:
                continue
            idx = link_idx_by_id.get(lid)
            if idx is None:
                continue
            active_polys.append(link_polys[idx])
            # Width scales with count; clamp.
            if global_max == 1:
                w = (line_width_min + line_width_max) / 2
            else:
                w = (line_width_min + (line_width_max - line_width_min)
                     * (count / global_max) ** 0.5)
            active_widths.append(w)
            active_colors.append(cmap_obj(norm(count)))

        active_lc.set_segments(active_polys)
        active_lc.set_linewidths(active_widths)
        active_lc.set_colors(active_colors)
        # Compose timestamp label (bin start, HH:MM)
        td = timedelta(seconds=bin_t)
        hh = td.seconds // 3600
        mm = (td.seconds % 3600) // 60
        title_text.set_text(
            f"{title or 'Link throughput'}  ·  "
            f"{hh:02d}:{mm:02d}  ·  {len(active_polys):,} active links"
        )
        return (active_lc, title_text)

    anim = animation.FuncAnimation(
        fig, _frame, frames=n_frames, interval=1000 / fps, blit=False,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == ".mp4":
        try:
            writer = animation.FFMpegWriter(fps=fps, bitrate=2400, codec="libx264")
            anim.save(str(output_path), writer=writer, dpi=dpi)
        except Exception as e:
            logger.warning("ffmpeg write failed (%s); falling back to GIF", e)
            output_path = output_path.with_suffix(".gif")
            anim.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    elif suffix == ".gif":
        anim.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    else:
        raise ValueError(f"Unsupported output format: {suffix} (use .mp4 or .gif)")

    plt.close(fig)
    logger.info("Wrote animation -> %s", output_path)
    return output_path
