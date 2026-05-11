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
        from visualization.render.od_density import render_od_density

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
        logger.info("[%s] rendering -> %s", map_type, out)
        return render_od_density(
            network=network,
            demand=demand,
            side=side,
            output_path=out,
            style=args.style,
            gridsize=args.gridsize,
            cmap=args.cmap,
            dpi=args.dpi,
        )

    # Phase B / C placeholders.
    logger.warning(
        "[%s] not yet implemented (Phase B or C); coverage matrix shows when this becomes generatable",
        map_type,
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
    parser.add_argument("--style", choices=["dots", "hex"], default="dots",
                        help="od_* render style. 'dots' = proportional symbols "
                             "(one circle per node, sized + colored by count — best for "
                             "sparse 1k-50k data); 'hex' = hexbin (better for 200k+).")
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
