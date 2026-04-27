"""
CLI for the LPSim adapter.

Usage::

    python -m adapters.lpsim.cli scenarios/chicago_1k_car out/lpsim
    python -m adapters.lpsim.cli scenarios/chicago_1k_car out/lpsim --run
    python -m adapters.lpsim.cli scenarios/chicago_1k_car out/lpsim --run --use-cpu
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from adapters.lpsim.lpsim_adapter import (
    LPSimConfig,
    prepare_lpsim_inputs,
    run_lpsim,
    parse_lpsim_output,
    find_lpsim_binary,
    find_lpsim_singularity_image,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LPSim Adapter — convert canonical bundles to LPSim inputs."
    )
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory for generated files")
    parser.add_argument(
        "--run", action="store_true",
        help="Also invoke the LivingCity binary after writing inputs.",
    )
    parser.add_argument(
        "--use-cpu", action="store_true",
        help="USE_CPU=true — runs the CPU code path (slow, useful for debugging).",
    )
    parser.add_argument(
        "--passes", type=int, default=1,
        help="NUM_PASSES (default 1; matches SUMO/MATSim single-iteration semantics).",
    )
    parser.add_argument(
        "--timeout", type=int, default=3600,
        help="Per-run timeout in seconds (default 3600).",
    )
    parser.add_argument(
        "--no-singularity", action="store_true",
        help="Force the native binary path even if a Singularity image is available.",
    )

    args = parser.parse_args()

    cfg = LPSimConfig(use_cpu=args.use_cpu, num_passes=args.passes)

    summary = prepare_lpsim_inputs(Path(args.scenario), Path(args.output), cfg)
    print(
        f"  Wrote LPSim inputs for {summary.scenario_id}: "
        f"{summary.node_count} nodes, {summary.link_count} links, "
        f"{summary.trip_count} trips → {args.output}/"
    )

    if not args.run:
        return 0

    sif = find_lpsim_singularity_image()
    binary = find_lpsim_binary()
    if sif:
        print(f"  Will run via Singularity image: {sif}")
    elif binary:
        print(f"  Will run native binary: {binary}")
    else:
        print(
            "ERROR: no LPSim binary or Singularity image found.\n"
            "  Build once on a Pitzer GPU node: sbatch cluster/jobs/build_lpsim.sbatch"
        )
        return 1

    success, runtime, error = run_lpsim(
        Path(args.output),
        timeout_s=args.timeout,
        use_singularity=not args.no_singularity,
    )
    if not success:
        print(f"FAILED in {runtime:.1f}s: {error}")
        return 1

    stats = parse_lpsim_output(Path(args.output))
    if stats is None:
        print(f"  LPSim ran in {runtime:.1f}s but produced no *_people.csv output")
        return 1
    print(
        f"  LPSim OK in {runtime:.1f}s — "
        f"{stats.completed_count}/{stats.trip_count} trips completed, "
        f"mean TT {stats.mean_travel_time_s:.1f}s, "
        f"P95 TT {stats.p95_travel_time_s:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
