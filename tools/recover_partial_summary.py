"""Recover a benchmark scenario summary JSON from on-disk per-cell artifacts.

Use case: a sbatch worker for one scenario completed some engine cells
(SUMO ✓ + MATSim ✓ on disk) but was killed before the harness could
write the aggregate summary JSON (OOM, walltime, signal). Or some
cells genuinely failed (DTALite timeout) and we need a JSON that
records that fact.

This tool walks the per-cell directory tree, parses what's there,
synthesizes failure entries for what isn't, and writes the canonical
``benchmark_results_<runspec>.json`` the harness would have produced.
The resulting JSON is byte-compatible with the schema the analyzer +
audit_fairness scripts read.

Synthesized cells use ``timeout_s`` from the runspec entry, so the
JSON honestly records the timeout we *attempted* — even though the
cell never ran to completion. Pair with a CHANGELOG entry explaining
why recovery was needed (which run was interrupted, what timeout was
in force, etc.).

Usage::

    python -m tools.recover_partial_summary \\
        --runspec  runspecs/benchmark_small.yaml \\
        --scenario la_50k_car \\
        --base-dir runs/benchmark_small/la_50k_car

Writes::

    runs/benchmark_small/la_50k_car/benchmark_results_benchmark_small.json
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

import yaml

from execution.run_benchmark import BenchmarkResult, RunResult

logger = logging.getLogger(__name__)


def _short_mode(mode: str) -> str:
    """Runspec uses 'mesoscopic'/'microscopic'; cell dirs use 'meso'/'micro'."""
    return {"mesoscopic": "meso", "microscopic": "micro"}.get(mode, mode)


def _parse_sumo_cell(cell_dir: Path) -> tuple[str, dict, Path | None, str | None]:
    """Return (status, metrics, tripinfo_path, error_message)."""
    tripinfo = cell_dir / "tripinfo.xml"
    if not tripinfo.is_file() or tripinfo.stat().st_size == 0:
        return "failed", {}, None, "Cell artifact missing: tripinfo.xml"
    try:
        from evaluation.metrics.travel_time import parse_sumo_tripinfo
        stats = parse_sumo_tripinfo(tripinfo)
        return "success", {"travel_time": {
            "mean": stats.mean_travel_time_s,
            "p95": stats.p95_travel_time_s,
            "trip_count": stats.trip_count,
        }}, tripinfo, None
    except Exception as e:
        return "failed", {}, tripinfo, f"tripinfo parse failed: {e}"


def _parse_matsim_cell(cell_dir: Path) -> tuple[str, dict, str | None]:
    """Return (status, metrics, error_message)."""
    output_subdir = cell_dir / "output"
    trips_gz = output_subdir / "output_trips.csv.gz"
    if not trips_gz.is_file() or trips_gz.stat().st_size == 0:
        return "failed", {}, "Cell artifact missing: output/output_trips.csv.gz"
    try:
        from adapters.matsim import parse_matsim_output
        stats = parse_matsim_output(output_subdir)
        if not stats:
            return "failed", {}, "MATSim parser returned no stats"
        return "success", {"travel_time": {
            "mean": stats.get("mean_travel_time_s", 0),
            "p95": stats.get("p95_travel_time_s", 0),
            "trip_count": stats.get("trip_count", 0),
        }}, None
    except Exception as e:
        return "failed", {}, f"MATSim parse failed: {e}"


def _parse_dtalite_cell(cell_dir: Path) -> tuple[str, dict, str | None]:
    """Return (status, metrics, error_message)."""
    link_perf = cell_dir / "link_performance.csv"
    if not link_perf.is_file() or link_perf.stat().st_size == 0:
        return "failed", {}, None  # caller fills in synthesized timeout msg
    try:
        from adapters.dtalite import parse_dtalite_output
        stats = parse_dtalite_output(cell_dir)
        if stats is None or stats.completed_count == 0:
            return "failed", {}, None
        return "success", {"travel_time": {
            "mean": stats.mean_travel_time_s,
            "p95": stats.p95_travel_time_s,
            "trip_count": stats.completed_count,
        }}, None
    except Exception as e:
        return "failed", {}, f"DTALite parse failed: {e}"


def recover_scenario(
    runspec_path: Path,
    scenario_id: str,
    base_dir: Path,
    output_path: Path | None = None,
) -> Path:
    """Walk per-cell artifacts, build summary JSON, write to disk.

    Returns the output path written.
    """
    runspec = yaml.safe_load(runspec_path.read_text())
    runspec_name = runspec.get("name") or runspec_path.stem

    scenario_rows = [r for r in runspec["runs"] if r["scenario_id"] == scenario_id]
    if not scenario_rows:
        raise SystemExit(f"No runs for scenario {scenario_id} in {runspec_path}")

    results: list[RunResult] = []
    n_success = n_failed = 0

    for row in scenario_rows:
        engine = row["engine"]
        mode = _short_mode(row["mode"])
        repeats = row["repeats"]
        seed_base = row["seed"]
        seed_inc = row.get("seed_increment", True)
        timeout_s = row.get("timeout_s", 0)

        for i in range(repeats):
            seed = seed_base + i if seed_inc else seed_base
            cell_dir = base_dir / engine / mode / f"seed_{seed}"

            tripinfo_path: Path | None = None
            if engine == "sumo":
                status, metrics, tripinfo_path, error = _parse_sumo_cell(cell_dir)
            elif engine == "matsim":
                status, metrics, error = _parse_matsim_cell(cell_dir)
            elif engine == "dtalite":
                status, metrics, error = _parse_dtalite_cell(cell_dir)
                # If DTALite missing/incomplete, synthesize a timeout message
                # using the runspec's configured timeout_s — recording what
                # we *attempted*, not zero.
                if status == "failed" and error is None:
                    error = f"{engine.upper()} timeout after {timeout_s}s (synthesized — cell did not complete; see CHANGELOG for context)"
            else:
                status, metrics, error = "failed", {}, f"Unknown engine: {engine}"

            runtime_s = float(timeout_s) if status == "failed" and error and "timeout" in error.lower() else 0.0

            results.append(RunResult(
                scenario=scenario_id,
                engine=engine,
                mode=mode,
                seed=seed,
                repeat_index=i,
                status=status,
                runtime_s=runtime_s,
                output_dir=cell_dir,
                tripinfo_path=tripinfo_path,
                error_message=error,
                metrics=metrics,
                engine_wall_s=runtime_s,
                cell_wall_s=runtime_s,
            ))
            if status == "success":
                n_success += 1
            else:
                n_failed += 1
            tag = "OK" if status == "success" else "FAIL"
            logger.info("  [%s] %s/%s/%s/seed_%d  %s", tag, scenario_id, engine, mode, seed, error or "")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    br = BenchmarkResult(
        runspec_name=runspec_name,
        started_at=now,
        completed_at=now,
        total_runs=len(results),
        successful_runs=n_success,
        failed_runs=n_failed,
        results=results,
    )

    if output_path is None:
        output_path = base_dir / f"benchmark_results_{runspec_name}.json"

    br.save(output_path)
    logger.info("Wrote %s  (%d success, %d failed, %d total)",
                output_path, n_success, n_failed, len(results))
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runspec", type=Path, required=True,
                        help="Path to the runspec YAML used by the original sbatch")
    parser.add_argument("--scenario", required=True,
                        help="scenario_id to recover (e.g. la_50k_car)")
    parser.add_argument("--base-dir", type=Path, required=True,
                        help="Per-scenario output dir, e.g. runs/benchmark_small/la_50k_car")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output JSON path (default: <base-dir>/benchmark_results_<runspec>.json)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.runspec.is_file():
        print(f"runspec not found: {args.runspec}", file=sys.stderr)
        return 2
    if not args.base_dir.is_dir():
        print(f"base-dir not found: {args.base_dir}", file=sys.stderr)
        return 2

    recover_scenario(args.runspec, args.scenario, args.base_dir, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
