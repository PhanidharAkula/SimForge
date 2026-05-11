"""animated_flow renderer (Phase C).

Two modes:

- ``throughput`` (snapshot per time bin): network links colored by
  vehicle throughput in fixed-width windows. Standard cartographic
  convention; same data as link_load.png but per-bin instead of
  horizon-total.
- ``particles`` (default): each vehicle is a moving dot streaming
  along its actual route at its actual simulated speed. Smoother,
  more cinematic; shows real traffic flow as a swarm of particles.

Output: MP4 via matplotlib.animation + ffmpeg writer. Falls back to
GIF via Pillow writer if ffmpeg unavailable.

Currently MATSim-only: needs event-level data with timestamps, which
neither SUMO (without --fcd-output config change) nor DTALite (steady-
state UE) provides natively.
"""

from __future__ import annotations

import bisect
import logging
from datetime import timedelta
from pathlib import Path

from visualization.data.bundle import Network

logger = logging.getLogger(__name__)


def _build_link_polylines(
    network: Network,
    use_osm_curves: bool,
    scenario_id: str | None,
) -> dict[str, list[tuple[float, float]]]:
    """Return {link_id: polyline} for every link, curved if OSM cache available."""
    way_geoms: dict[int, list[tuple[float, float]]] = {}
    if use_osm_curves and scenario_id and network.link_osm_way_ids:
        from visualization.data.osm_ways import load_way_geometries
        needed = set()
        for ids in network.link_osm_way_ids.values():
            needed.update(ids)
        if needed:
            way_geoms = load_way_geometries(scenario_id, needed)

    out: dict[str, list[tuple[float, float]]] = {}
    if way_geoms:
        from visualization.data.osm_ways import link_polyline
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id); t = network.nodes.get(to_id)
            if not f or not t:
                continue
            way_ids = network.link_osm_way_ids.get(lid, [])
            out[lid] = link_polyline(
                lid, from_id, to_id, way_ids,
                way_geoms, network.nodes, network.node_osm_ids,
            )
    else:
        for lid, from_id, to_id, _ht in network.links:
            f = network.nodes.get(from_id); t = network.nodes.get(to_id)
            if not f or not t:
                continue
            out[lid] = [f, t]
    return out


def _polyline_arc_lengths(poly: list[tuple[float, float]]) -> tuple[list[float], float]:
    """Return cumulative arc lengths + total."""
    cum = [0.0]
    for i in range(1, len(poly)):
        x0, y0 = poly[i - 1]
        x1, y1 = poly[i]
        dx, dy = x1 - x0, y1 - y0
        cum.append(cum[-1] + (dx * dx + dy * dy) ** 0.5)
    return cum, cum[-1]


def _position_along(
    poly: list[tuple[float, float]],
    cum: list[float],
    total: float,
    progress: float,
) -> tuple[float, float]:
    """Interpolate (lon, lat) at normalized progress (0..1) along a polyline."""
    if total == 0 or len(poly) < 2:
        return poly[0] if poly else (0.0, 0.0)
    target = max(0.0, min(1.0, progress)) * total
    idx = bisect.bisect_left(cum, target)
    if idx == 0:
        return poly[0]
    if idx >= len(poly):
        return poly[-1]
    seg_start = cum[idx - 1]
    seg_end = cum[idx]
    if seg_end == seg_start:
        return poly[idx]
    f = (target - seg_start) / (seg_end - seg_start)
    x0, y0 = poly[idx - 1]
    x1, y1 = poly[idx]
    return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))


def render_flowing_particles(
    network: Network,
    traversals: dict[str, list[tuple[str, float, float]]],
    *,
    output_path: Path,
    title: str | None = None,
    engine: str = "matsim",
    fps: int = 30,
    sim_seconds_per_frame: float = 5.0,
    figsize: tuple[float, float] | None = None,
    dpi: int = 120,
    dot_size: float = 9.0,
    dot_alpha: float = 0.85,
    dot_color: str = "#e60026",
    use_osm_curves: bool = True,
    scenario_id: str | None = None,
) -> Path:
    """Render an MP4 of vehicles flowing along their routes as moving dots.

    Each frame at simulation time T:
      - Identify vehicles currently on a link (enter <= T <= leave)
      - Interpolate their position along that link's polyline by
        progress = (T - enter) / (leave - enter)
      - Plot positions as a single scatter

    sim_seconds_per_frame controls the time-warp factor: 5s/frame at
    30 fps = 150x speedup vs real time (1 hour sim → 24 sec video).
    """
    import matplotlib  # lazy
    matplotlib.use("Agg")
    import matplotlib.animation as animation
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import LineCollection

    if not traversals:
        raise ValueError("Empty traversals — no vehicles to animate")

    link_polys = _build_link_polylines(network, use_osm_curves, scenario_id)
    arc_cache: dict[str, tuple[list[float], float]] = {}
    for lid, poly in link_polys.items():
        if len(poly) >= 2:
            arc_cache[lid] = _polyline_arc_lengths(poly)

    # Flatten traversals for fast per-frame lookup, sorted by enter_t.
    flat = sorted(
        ((r[1], r[2], v, r[0])
         for v, recs in traversals.items() for r in recs),
        key=lambda x: x[0],
    )
    enter_times = [item[0] for item in flat]
    all_leave = [item[1] for item in flat]
    if not flat:
        raise ValueError("No traversal records to animate")

    t_start = min(enter_times)
    t_end = max(all_leave)
    total_sim_seconds = t_end - t_start
    n_frames = int(total_sim_seconds / sim_seconds_per_frame) + 1

    logger.info(
        "Particle animation: %d vehicles, sim horizon %.0fs (%.1fh), "
        "%d frames @ %d fps (%.1fs video, %.0fx speedup)",
        len(traversals), total_sim_seconds, total_sim_seconds / 3600,
        n_frames, fps, n_frames / fps, sim_seconds_per_frame * fps,
    )

    bbox = network.bbox
    if figsize is None:
        from visualization.data.bundle import figsize_for_bbox
        figsize = figsize_for_bbox(bbox) if bbox else (12.0, 10.0)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    if bbox is not None:
        pad_x = (bbox[2] - bbox[0]) * 0.02
        pad_y = (bbox[3] - bbox[1]) * 0.02
        ax.set_xlim(bbox[0] - pad_x, bbox[2] + pad_x)
        ax.set_ylim(bbox[1] - pad_y, bbox[3] + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    all_polys = list(link_polys.values())
    ax.add_collection(LineCollection(
        all_polys, linewidths=0.35, colors="#888888", alpha=0.55, zorder=1,
    ))

    sc = ax.scatter(
        [], [], s=dot_size, c=dot_color, alpha=dot_alpha,
        zorder=3, edgecolors="none",
    )

    title_text = ax.set_title("", fontsize=14, fontweight="bold", pad=12)
    fig.text(
        0.5, 0.015,
        f"SimForge animated_flow (particles)  ·  engine={engine}  ·  "
        f"{sim_seconds_per_frame:.0f}s/frame @ {fps}fps  ·  "
        f"{len(traversals):,} vehicles  ·  {n_frames} frames",
        ha="center", fontsize=7, color="#888",
    )

    def _frame(frame_idx: int) -> tuple:
        T = t_start + frame_idx * sim_seconds_per_frame
        # All traversals where enter_t <= T (binary search), filter for leave >= T.
        hi = bisect.bisect_right(enter_times, T)
        positions: list[tuple[float, float]] = []
        for i in range(hi):
            enter_t, leave_t, _veh, link_id = flat[i]
            if leave_t < T:
                continue
            arc = arc_cache.get(link_id)
            if arc is None:
                continue
            cum, total = arc
            poly = link_polys[link_id]
            progress = (T - enter_t) / max(leave_t - enter_t, 1e-9)
            positions.append(_position_along(poly, cum, total, progress))

        if positions:
            sc.set_offsets(np.array(positions))
        else:
            sc.set_offsets(np.empty((0, 2)))

        td = timedelta(seconds=int(T))
        hh = td.seconds // 3600
        mm = (td.seconds % 3600) // 60
        ss = td.seconds % 60
        title_text.set_text(
            f"{title or 'Vehicle flow'}  ·  "
            f"{hh:02d}:{mm:02d}:{ss:02d}  ·  {len(positions):,} active vehicles"
        )
        return (sc, title_text)

    anim = animation.FuncAnimation(
        fig, _frame, frames=n_frames, interval=1000 / fps, blit=False,
    )

    output_path = _save_animation(anim, output_path, fps, dpi)
    plt.close(fig)
    logger.info("Wrote particle animation -> %s", output_path)
    return output_path


def _save_animation(anim, output_path: Path, fps: int, dpi: int) -> Path:
    """Save a matplotlib FuncAnimation in the right format based on suffix.

    Supported: .mp4 (ffmpeg+libx264), .gif (Pillow), .apng (ffmpeg),
    .webp (ffmpeg+libwebp_anim — smallest file).
    """
    import matplotlib.animation as animation
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()

    if suffix == ".mp4":
        try:
            writer = animation.FFMpegWriter(fps=fps, bitrate=3200, codec="libx264")
            anim.save(str(output_path), writer=writer, dpi=dpi)
        except Exception as e:
            logger.warning("ffmpeg write failed (%s); falling back to GIF", e)
            output_path = output_path.with_suffix(".gif")
            anim.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    elif suffix == ".gif":
        # Pillow writer is the most reliable for GIF. ffmpeg can do GIF
        # too with -vcodec gif but Pillow handles palette + transparency.
        anim.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    elif suffix == ".apng":
        # ffmpeg APNG: full color, small (vs GIF), wide modern browser support.
        try:
            writer = animation.FFMpegWriter(
                fps=fps, codec="apng",
                extra_args=["-plays", "0", "-pix_fmt", "rgba"],
            )
            anim.save(str(output_path), writer=writer, dpi=dpi)
        except Exception as e:
            logger.warning("APNG write failed (%s); falling back to GIF", e)
            output_path = output_path.with_suffix(".gif")
            anim.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    else:
        raise ValueError(
            f"Unsupported output format: {suffix} (use .mp4, .gif, or .apng). "
            f"WebP is not supported because Homebrew's ffmpeg lacks libwebp."
        )
    return output_path


def render_animated_flow(
    network: Network,
    time_bin_loads: dict[int, dict[str, int]],
    *,
    output_path: Path,
    title: str | None = None,
    engine: str = "matsim",
    time_bin_seconds: int = 300,
    fps: int = 2,
    figsize: tuple[float, float] | None = None,
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

    # Figure setup — figsize matches data aspect to avoid white margins.
    bbox = network.bbox
    if figsize is None:
        from visualization.data.bundle import figsize_for_bbox
        figsize = figsize_for_bbox(bbox) if bbox else (12.0, 10.0)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if bbox is not None:
        pad_x = (bbox[2] - bbox[0]) * 0.02
        pad_y = (bbox[3] - bbox[1]) * 0.02
        ax.set_xlim(bbox[0] - pad_x, bbox[2] + pad_x)
        ax.set_ylim(bbox[1] - pad_y, bbox[3] + pad_y)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    # Inactive-link basemap underneath (always visible). Medium-light
    # gray so the road network is readable but doesn't dominate the
    # colored active overlay on top.
    ax.add_collection(LineCollection(
        link_polys, linewidths=0.35, colors="#888888", alpha=0.55, zorder=1,
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

    output_path = _save_animation(anim, output_path, fps, dpi)
    plt.close(fig)
    logger.info("Wrote animation -> %s", output_path)
    return output_path
