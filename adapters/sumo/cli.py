"""
Command-line front end for the SUMO adapter.

Run it from the repo root:
    python -m adapters.sumo.cli scenarios/chicago_1k_car out/sumo_chi
    python -m adapters.sumo.cli scenarios/chicago_1k_car out/sumo_chi --run
    python -m adapters.sumo.cli scenarios/chicago_1k_car out/sumo_chi --run --mesoscopic
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .sumo_adapter import prepare_sumo_inputs


def _run_sumo(
    cfg_path: Path,
    output_dir: Path,
    *,
    mesoscopic: bool,
    seed: int,
    timeout_s: int,
) -> tuple[bool, float, str | None]:
    """Run the `sumo` binary on a generated `.sumocfg`.

    We always pass --ignore-route-errors. The adapter precomputes routes by
    BFS over the canonical node graph, and on big real-world networks that
    can disagree with SUMO's own edge-level lane connectivity.
    """
    if shutil.which("sumo") is None:
        return (
            False,
            0.0,
            "sumo not found on PATH. SUMO is bundled in requirements.lock as the "
            "eclipse-sumo wheel — install with: `uv pip install -r requirements.lock` "
            "(or `pip install eclipse-sumo` for an ad-hoc install). Verify with: `sumo --version`.",
        )

    cmd = ["sumo"]
    if mesoscopic:
        cmd.extend(["--mesosim", "true"])
    cmd.extend([
        "-c", str(cfg_path.resolve()),
        "--seed", str(seed),
        "--ignore-route-errors",
        "--tripinfo-output", str((output_dir / "tripinfo.xml").resolve()),
        "--statistic-output", str((output_dir / "statistics.xml").resolve()),
    ])

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - start, f"SUMO timed out after {timeout_s}s"

    runtime = time.time() - start
    # SUMO exits non-zero even on harmless warnings, so only count it failed
    # when stderr actually carries an "Error:" line.
    if result.returncode != 0:
        error_lines = [
            line for line in (result.stderr or "").splitlines()
            if line.strip().startswith("Error:")
        ]
        if error_lines:
            return False, runtime, "\n".join(error_lines)
    return True, runtime, None


def _summarize_tripinfo(tripinfo_path: Path) -> dict | None:
    """Mean/median/p95/min/max travel time from tripinfo.xml, or None if there's nothing to read."""
    if not tripinfo_path.is_file():
        return None
    try:
        tree = ET.parse(tripinfo_path)
    except ET.ParseError:
        return None
    durations = [
        float(elem.get("duration"))
        for elem in tree.getroot().findall("tripinfo")
        if elem.get("duration") is not None
    ]
    if not durations:
        return None
    durations.sort()
    n = len(durations)
    return {
        "trip_count": n,
        "mean_travel_time_s": sum(durations) / n,
        "median_travel_time_s": durations[n // 2],
        "p95_travel_time_s": durations[min(n - 1, int(0.95 * n))],
        "min_travel_time_s": durations[0],
        "max_travel_time_s": durations[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare SUMO inputs from a SimForge canonical scenario bundle."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to canonical scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where SUMO input files will be written (will be created if needed)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Also run the simulation after generating inputs (uses --ignore-route-errors)",
    )
    parser.add_argument(
        "--mesoscopic", action="store_true",
        help="Run in mesoscopic mode (--mesosim); ignored without --run",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for SUMO (default: 42)",
    )
    parser.add_argument(
        "--timeout", type=int, default=3600,
        help="Simulation timeout in seconds (default: 3600)",
    )

    args = parser.parse_args()

    scenario_root = Path(args.scenario_root)
    output_dir = Path(args.output_dir)

    if not scenario_root.is_dir():
        print(f"Error: Scenario directory not found: {scenario_root}")
        print("  Check that the path exists and contains manifest.xml.")
        raise SystemExit(1)

    if not (scenario_root / "manifest.xml").is_file():
        print(f"Error: No manifest.xml found in {scenario_root}")
        print("  This directory does not appear to be a valid SimForge scenario bundle.")
        print("  Expected files: manifest.xml, network.xml, demand.csv, config.xml")
        raise SystemExit(1)

    try:
        summary = prepare_sumo_inputs(scenario_root, output_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        raise SystemExit(1) from e
    except ValueError as e:
        print(f"Error: Invalid scenario data — {e}")
        raise SystemExit(1) from e
    except RuntimeError as e:
        print(f"Error: {e}")
        raise SystemExit(1) from e

    print(f"[SUMO ADAPTER] Prepared SUMO inputs at: {output_dir.resolve()}")
    print(f"  Scenario ID : {summary.scenario_id}")
    print(f"  Nodes       : {summary.node_count}")
    print(f"  Links       : {summary.link_count}")
    print(f"  Trips       : {summary.trip_count}")
    print(f"  Has signals : {summary.has_signals}")
    print(f"  Time horizon: {summary.start_time_s} -> {summary.end_time_s} seconds")

    if not args.run:
        return

    cfg_path = Path(output_dir) / "toy.sumocfg"
    if not cfg_path.is_file():
        print(f"Error: Expected SUMO config at {cfg_path} but it was not generated.")
        raise SystemExit(1)

    print("\n" + "-" * 60)
    mode_label = "mesoscopic" if args.mesoscopic else "microscopic"
    print(f"Running SUMO ({mode_label}) ...")
    print("-" * 60)

    success, runtime, error = _run_sumo(
        cfg_path,
        Path(output_dir),
        mesoscopic=args.mesoscopic,
        seed=args.seed,
        timeout_s=args.timeout,
    )

    if not success:
        print(f"\n✗ Simulation failed: {error}")
        sys.exit(1)

    print(f"\n✓ Simulation completed in {runtime:.2f}s")
    stats = _summarize_tripinfo(Path(output_dir) / "tripinfo.xml")
    if stats:
        print("\nTravel Time Statistics:")
        print(f"  Total trips: {stats['trip_count']}")
        print(f"  Mean:   {stats['mean_travel_time_s']:.1f} s")
        print(f"  Median: {stats['median_travel_time_s']:.1f} s")
        print(f"  P95:    {stats['p95_travel_time_s']:.1f} s")
        print(f"  Range:  {stats['min_travel_time_s']:.1f} s - {stats['max_travel_time_s']:.1f} s")


if __name__ == "__main__":
    main()
