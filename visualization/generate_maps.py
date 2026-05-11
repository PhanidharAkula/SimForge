"""CLI entry point for the SimForge visualization component.

Usage::

    # Coverage report only — what's generatable from current data?
    python -m visualization.generate_maps --scenario chicago_1k_car --dry-run

    # Render origin density (Phase A flagship map) — defaults to
    # visualization/output/chicago_1k_car/od_origins.png:
    python -m visualization.generate_maps --scenario chicago_1k_car --maps od_origins

    # Render both origin + destination, custom output dir, with grid override:
    python -m visualization.generate_maps --scenario chicago_1k_car \\
        --maps od_origins,od_destinations \\
        --output doc/figures/maps/chicago_1k_car \\
        --gridsize 80

The component reports a coverage matrix before doing any work. Maps that
require data not on disk are skipped (logged, not error). Phase A ships
``od_origins`` and ``od_destinations``; ``link_load`` / ``travel_time`` /
``route_diversity`` / ``congestion`` / ``animated_flow`` are listed in
the coverage matrix but their renderers are Phase B + C.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from visualization.coverage import (
    ALL_MAP_TYPES,
    ScenarioCoverage,
    discover_bundle,
    discover_run_cells,
    format_coverage_matrix,
)

logger = logging.getLogger("visualization")


PHASE_A_MAPS: frozenset[str] = frozenset({"od_origins", "od_destinations"})
PHASE_B_MAPS: frozenset[str] = frozenset({"link_load", "travel_time", "congestion"})
PHASE_C_MAPS: frozenset[str] = frozenset({"route_diversity", "animated_flow"})


def _pick_engine_cell(coverage, engine_pref: str | None) -> "CellArtifacts | None":
    """Pick one engine/seed cell to render from. Defaults to first available."""
    if not coverage.cells:
        return None
    candidates = [c for c in coverage.cells if c.has_any_output]
    if not candidates:
        return None
    if engine_pref:
        engine_matches = [c for c in candidates if c.engine == engine_pref]
        if engine_matches:
            candidates = engine_matches
    candidates.sort(key=lambda c: (c.engine, c.mode, c.seed))
    return candidates[0]


def _resolve_default_output(scenario: str) -> Path:
    """Default output dir: ``visualization/output/<scenario>/``.

    Single predictable location co-located with the visualization tool.
    Easy to find, easy to clean, gitignored. Override with ``--output``
    to publish maps elsewhere (e.g. ``doc/figures/maps/`` for thesis use).
    """
    return Path(__file__).parent / "output" / scenario


def _autodetect_run_dir(scenario: str) -> Path | None:
    """Look for a per-scenario run dir under the conventional locations."""
    candidates = [
        Path("runs") / "benchmark_small" / scenario,
        Path("runs") / "benchmark_large" / scenario,
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None


def _render_map(
    map_type: str,
    coverage: ScenarioCoverage,
    output_dir: Path,
    args: argparse.Namespace,
) -> Path | None:
    """Dispatch to the appropriate renderer. Returns None if not implemented yet."""
    if map_type in PHASE_A_MAPS:
        from visualization.data.bundle import load_demand, load_network

        net_path = coverage.bundle_files.get("network")
        dem_path = coverage.bundle_files.get("demand")
        if not net_path or not dem_path:
            logger.warning("[%s] skipped: bundle missing network or demand", map_type)
            return None

        logger.info("[%s] loading network: %s", map_type, net_path)
        network = load_network(net_path)
        logger.info("[%s] loading demand: %s", map_type, dem_path)
        demand = load_demand(dem_path)

        side = "origin" if map_type == "od_origins" else "destination"
        out = output_dir / f"{map_type}.png"
        logger.info("[%s] rendering (%s) -> %s", map_type, args.style, out)

        if args.style == "choropleth":
            from visualization.render.od_choropleth import render_od_choropleth
            return render_od_choropleth(
                network=network, demand=demand, side=side,
                output_path=out, dpi=args.dpi,
            )

        from visualization.render.od_density import render_od_density
        return render_od_density(
            network=network, demand=demand, side=side,
            output_path=out, style=args.style,
            gridsize=args.gridsize, cmap=args.cmap, dpi=args.dpi,
        )

    if map_type in PHASE_B_MAPS:
        return _render_phase_b(map_type, coverage, output_dir, args)

    if map_type in PHASE_C_MAPS:
        return _render_phase_c(map_type, coverage, output_dir, args)

    logger.warning(
        "[%s] not yet implemented; coverage matrix shows when this becomes generatable",
        map_type,
    )
    return None


def _render_phase_c(
    map_type: str,
    coverage,
    output_dir: Path,
    args: argparse.Namespace,
) -> Path | None:
    """Phase C renderers: route_diversity (and future animated_flow)."""
    from visualization.data.bundle import load_network

    net_path = coverage.bundle_files.get("network")
    if not net_path:
        logger.warning("[%s] skipped: bundle missing network", map_type)
        return None

    if map_type == "animated_flow":
        # MATSim-only: needs event-level data (events.xml.gz).
        matsim_cells = [c for c in coverage.cells
                        if c.engine == "matsim" and c.has_event_output]
        if not matsim_cells:
            logger.warning(
                "[%s] skipped: no MATSim cell with output_events.xml.gz on disk",
                map_type,
            )
            return None
        cell = sorted(matsim_cells, key=lambda c: c.seed)[0]
        from visualization.data.bundle import load_network
        network = load_network(net_path)
        events_path = cell.cell_dir / "output" / "output_events.xml.gz"

        anim_mode = getattr(args, "anim_mode", "particles")
        anim_ext = getattr(args, "anim_format", "mp4")
        if anim_mode == "particles":
            from visualization.data.events import parse_matsim_vehicle_traversals
            from visualization.render.animated_flow import render_flowing_particles

            traversals = parse_matsim_vehicle_traversals(
                events_path, scenario_id=args.scenario, seed=cell.seed,
            )
            out = output_dir / f"{map_type}_matsim_meso.{anim_ext}"
            return render_flowing_particles(
                network=network, traversals=traversals,
                output_path=out, engine="matsim",
                fps=getattr(args, "anim_fps", 30),
                sim_seconds_per_frame=getattr(args, "anim_sim_per_frame", 5.0),
                dpi=args.dpi // 2,
                scenario_id=args.scenario,
            )
        else:  # throughput
            from visualization.data.events import parse_matsim_throughput
            from visualization.render.animated_flow import render_animated_flow

            loads = parse_matsim_throughput(
                events_path, time_bin_seconds=300,
                scenario_id=args.scenario, seed=cell.seed,
            )
            out = output_dir / f"{map_type}_matsim_meso.{anim_ext}"
            return render_animated_flow(
                network=network, time_bin_loads=loads,
                output_path=out, engine="matsim", time_bin_seconds=300,
                fps=2, dpi=args.dpi // 2, scenario_id=args.scenario,
            )

    if map_type == "route_diversity":
        # Aggregate links per engine using whichever loader fits.
        from visualization.data.results import (
            load_dtalite_links, load_matsim_links, load_sumo_links,
        )

        # Pick first available cell per engine that has the right artifacts.
        engine_links = {}
        per_engine_first_cell: dict[str, "CellArtifacts"] = {}
        for cell in coverage.cells:
            if cell.engine in per_engine_first_cell:
                continue
            per_engine_first_cell[cell.engine] = cell

        for engine, cell in per_engine_first_cell.items():
            try:
                if engine == "sumo" and cell.has_tripinfo:
                    engine_links[engine] = load_sumo_links(cell.cell_dir)
                elif engine == "matsim" and cell.has_matsim_trips:
                    engine_links[engine] = load_matsim_links(cell.cell_dir)
                elif engine == "dtalite" and cell.has_dtalite_link_perf:
                    engine_links[engine] = load_dtalite_links(cell.cell_dir)
            except Exception as e:
                logger.warning("[%s] %s loader failed: %s", map_type, engine, e)

        engine_links = {k: v for k, v in engine_links.items() if v}
        if len(engine_links) < 2:
            logger.warning(
                "[%s] skipped: need >= 2 engines with link data, found %d (%s)",
                map_type, len(engine_links), list(engine_links.keys()),
            )
            return None

        from visualization.render.route_diversity import render_route_diversity
        network = load_network(net_path)
        out = output_dir / f"{map_type}.png"
        return render_route_diversity(
            network=network, engine_links=engine_links,
            output_path=out, dpi=args.dpi, scenario_id=args.scenario,
        )

    return None


def _render_phase_b(
    map_type: str,
    coverage,
    output_dir: Path,
    args: argparse.Namespace,
) -> Path | None:
    """Phase B renderers: link_load, travel_time, congestion."""
    from visualization.data.bundle import load_demand, load_network

    net_path = coverage.bundle_files.get("network")
    dem_path = coverage.bundle_files.get("demand")
    if not net_path or not dem_path:
        logger.warning("[%s] skipped: bundle missing network or demand", map_type)
        return None

    cell = _pick_engine_cell(coverage, getattr(args, "engine", None))
    if cell is None:
        logger.warning("[%s] skipped: no engine cells with output", map_type)
        return None
    logger.info("[%s] using cell: %s/%s/seed_%d", map_type, cell.engine, cell.mode, cell.seed)

    network = load_network(net_path)
    demand = load_demand(dem_path)

    if map_type in ("link_load", "congestion"):
        # All three engines support link_load; only DTALite supports
        # congestion (needs per-link mean speed which only DTALite
        # writes natively without re-running with extra adapter flags).
        from visualization.data.results import (
            load_dtalite_links, load_matsim_links, load_sumo_links,
        )
        from visualization.render.link_load import render_link_metric

        if map_type == "congestion" and cell.engine != "dtalite":
            logger.warning(
                "[%s] skipped: only DTALite supports congestion at this time "
                "(needs link mean-speed; SUMO/MATSim would require extra "
                "adapter outputs). Use --engine dtalite.",
                map_type,
            )
            return None

        # Pick loader by engine.
        if cell.engine == "dtalite":
            if not cell.has_dtalite_link_perf:
                logger.warning(
                    "[%s] skipped: %s/%s/seed_%d has no link_performance.csv",
                    map_type, cell.engine, cell.mode, cell.seed,
                )
                return None
            links = load_dtalite_links(cell.cell_dir)
        elif cell.engine == "sumo":
            if not cell.has_tripinfo:
                logger.warning(
                    "[%s] skipped: %s/%s/seed_%d has no tripinfo.xml",
                    map_type, cell.engine, cell.mode, cell.seed,
                )
                return None
            links = load_sumo_links(cell.cell_dir)
        elif cell.engine == "matsim":
            if not cell.has_matsim_trips:
                logger.warning(
                    "[%s] skipped: %s/%s/seed_%d has no output/output_trips.csv.gz",
                    map_type, cell.engine, cell.mode, cell.seed,
                )
                return None
            links = load_matsim_links(cell.cell_dir)
        else:
            logger.warning("[%s] skipped: unknown engine %s", map_type, cell.engine)
            return None

        if not links:
            logger.warning("[%s] skipped: link loader returned empty", map_type)
            return None
        out = output_dir / f"{map_type}_{cell.engine}_{cell.mode}.png"
        metric = "volume" if map_type == "link_load" else "speed_ratio"
        return render_link_metric(
            network=network, links=links,
            metric=metric, output_path=out, engine=cell.engine,
            dpi=args.dpi, scenario_id=args.scenario,
        )

    if map_type == "travel_time":
        from visualization.data.results import (
            aggregate_trips_by_origin, load_dtalite_trips, load_matsim_trips,
            load_sumo_trips,
        )
        from visualization.render.travel_time import render_travel_time_choropleth

        loaders = {
            "sumo":    (load_sumo_trips,    cell.has_tripinfo),
            "matsim":  (load_matsim_trips,  cell.has_matsim_trips),
            "dtalite": (load_dtalite_trips, cell.has_dtalite_link_perf),
        }
        loader_fn, has_data = loaders.get(cell.engine, (None, False))
        if loader_fn is None or not has_data:
            logger.warning(
                "[%s] skipped: no trip-level output for %s/%s/seed_%d",
                map_type, cell.engine, cell.mode, cell.seed,
            )
            return None

        trips = loader_fn(cell.cell_dir)
        if not trips:
            logger.warning("[%s] skipped: trip parser returned 0 trips", map_type)
            return None

        # Build the trip_id -> origin_node_id map from demand.csv. Re-parse
        # demand to get the full row info (load_demand only stores per-trip
        # origin+dest in lists, not by trip_id).
        import csv as _csv
        demand_origin: dict[str, str] = {}
        with dem_path.open(newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                tid = (row.get("trip_id") or "").strip()
                origin = (row.get("origin_node_id") or "").strip()
                if tid and origin:
                    demand_origin[tid] = origin

        agg = aggregate_trips_by_origin(trips, demand_origin)
        out = output_dir / f"{map_type}_{cell.engine}_{cell.mode}.png"
        return render_travel_time_choropleth(
            network=network, demand=demand, aggregation=agg,
            output_path=out, engine=cell.engine, dpi=args.dpi,
        )

    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True,
                        help="scenario_id (e.g. chicago_1k_car)")
    parser.add_argument("--bundle-dir", type=Path, default=None,
                        help="Path to the bundle dir (default: scenarios/<scenario>)")
    parser.add_argument("--run-dir", type=Path, default=None,
                        help="Path to a per-scenario run dir "
                             "(default: auto-detect under runs/benchmark_*/)")
    parser.add_argument("--maps", default="all",
                        help="Comma-separated map types, or 'all'. "
                             f"Known: {','.join(ALL_MAP_TYPES)}")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output dir for PNGs "
                             "(default: visualization/output/<scenario>/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print coverage matrix and exit; render nothing")
    parser.add_argument("--style", choices=["dots", "hex", "choropleth"], default="dots",
                        help="od_* render style. 'dots' (default) = uniform small "
                             "circles, color-only encoding; 'hex' = hexbin (denser "
                             "data); 'choropleth' = CityScape-style filled census "
                             "tracts (requires `python -m tools.download_census_tracts "
                             "--all-bundled` first).")
    parser.add_argument("--gridsize", type=int, default=60,
                        help="hexbin gridsize for --style hex (default 60). Ignored for dots.")
    parser.add_argument("--cmap", default="dark_heat",
                        help="colormap. Custom dark presets (no white end that blends "
                             "into white bg): 'dark_heat' (default — navy→blue→purple→"
                             "magenta→red multi-hue), 'dark_spectral', 'dark_fire'. "
                             "Truncated standard: 'magma_dark', 'inferno_dark', "
                             "'viridis_dark', 'plasma_dark'. Or any matplotlib name: "
                             "'Reds', 'plasma', 'viridis', 'Spectral_r'.")
    parser.add_argument("--dpi", type=int, default=220,
                        help="render DPI (default 220)")
    parser.add_argument("--engine", default=None,
                        choices=["sumo", "matsim", "dtalite", None],
                        help="Engine to render Phase B maps from (link_load, "
                             "travel_time, congestion). Defaults to first "
                             "available engine in the run dir.")
    parser.add_argument("--anim-mode", choices=["particles", "throughput"],
                        default="particles",
                        help="animated_flow rendering: 'particles' (default) = "
                             "moving dots per vehicle (fluid, cinematic); "
                             "'throughput' = per-bin link-load snapshots stitched "
                             "together (cartographic convention).")
    parser.add_argument("--anim-fps", type=int, default=30,
                        help="animated_flow real-time playback fps (default 30 "
                             "for particles, ignored for throughput which uses 2)")
    parser.add_argument("--anim-sim-per-frame", type=float, default=5.0,
                        help="animated_flow particles mode: how many simulated "
                             "seconds each frame represents (default 5.0). "
                             "Lower = slower-motion video, longer file.")
    parser.add_argument("--anim-format", choices=["mp4", "gif", "apng"],
                        default="mp4",
                        help="animated_flow output container: 'mp4' (default — "
                             "smallest, needs ffmpeg + a video player), "
                             "'gif' (universal, embeds in markdown/HTML "
                             "directly, but largest file), 'apng' (full-color, "
                             "~5x smaller than GIF, modern browser support). "
                             "WebP is NOT supported because the standard "
                             "Homebrew ffmpeg lacks libwebp; would need a "
                             "custom ffmpeg build.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="enable debug-level logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    bundle_dir = args.bundle_dir or (Path("scenarios") / args.scenario)
    run_dir = args.run_dir or _autodetect_run_dir(args.scenario)
    output_dir = args.output or _resolve_default_output(args.scenario)

    coverage = discover_bundle(bundle_dir, scenario_id=args.scenario)
    if run_dir is not None:
        coverage = discover_run_cells(run_dir, coverage)

    print(format_coverage_matrix(coverage))
    print()

    if args.dry_run:
        print("(dry run -- no maps rendered)")
        return 0

    if args.maps == "all":
        requested = list(ALL_MAP_TYPES)
    else:
        requested = [m.strip() for m in args.maps.split(",") if m.strip()]
        unknown = [m for m in requested if m not in ALL_MAP_TYPES]
        if unknown:
            print(f"ERROR: unknown map types: {unknown}", file=sys.stderr)
            print(f"Known types: {','.join(ALL_MAP_TYPES)}", file=sys.stderr)
            return 2

    print(f"Output dir: {output_dir}")
    print(f"Rendering: {requested}")
    print()

    rendered: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for map_type in requested:
        ok, reason = coverage.map_generatable(map_type)
        if not ok:
            print(f"  [SKIP]  {map_type:<20s}  ({reason})")
            skipped.append((map_type, reason))
            continue
        try:
            out = _render_map(map_type, coverage, output_dir, args)
        except Exception as e:
            print(f"  [FAIL]  {map_type:<20s}  {type(e).__name__}: {e}")
            skipped.append((map_type, f"renderer error: {e}"))
            continue
        if out is None:
            print(f"  [SKIP]  {map_type:<20s}  (renderer returned None)")
            skipped.append((map_type, "renderer not yet implemented"))
            continue
        print(f"  [OK]    {map_type:<20s}  {out}")
        rendered.append(out)

    print()
    print(f"Done: {len(rendered)} rendered, {len(skipped)} skipped.")
    if rendered:
        print("Rendered files:")
        for p in rendered:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
