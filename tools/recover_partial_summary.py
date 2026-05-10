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

Optionally pass ``--harness-log <path>`` to populate ``runtime_s``,
``engine_wall_s``, and ``cell_wall_s`` for *successful* cells from
the harness's own cell-tape output (the lines like ``[N/M] engine
mode seed=X ✓ Y.Ys wall (Z.Zs engine)``). Without this flag, recovered
success cells get ``runtime_s = 0`` and Table 5.1 (Runtime) will show
zeros for them — the travel-time / R-score numbers parsed from on-disk
artifacts are still correct.

Usage::

    # Minimal — runtime fields will be 0 for success cells:
    python -m tools.recover_partial_summary \\
        --runspec  runspecs/benchmark_small.yaml \\
        --scenario la_50k_car \\
        --base-dir runs/benchmark_small/la_50k_car

    # With harness log — populates runtime fields too:
    python -m tools.recover_partial_summary \\
        --runspec  runspecs/benchmark_small.yaml \\
        --scenario la_50k_car \\
        --base-dir runs/benchmark_small/la_50k_car \\
        --harness-log logs/simforge_benchmark_small_la_only_47248311_la_50k_car.log

Writes::

    runs/benchmark_small/la_50k_car/benchmark_results_benchmark_small.json
"""

from __future__ import annotations

import argparse
import datetime
import logging
import re
import sys
from pathlib import Path

import yaml

from execution.run_benchmark import BenchmarkResult, RunResult

logger = logging.getLogger(__name__)

# Cell-tape line emitted by execution/run_benchmark.py per cell. Three forms:
#   Success: "  [ 1/15]  sumo     meso  seed=42  ✓    92.6s wall  ( 92.1s engine)"
#   Failure: "  [11/15]  dtalite  meso  seed=42  ✗  FAIL  DTALite timeout after 3600s"
#   Failure: "  [11/15]  dtalite  meso  seed=42  ✗  FAIL  Adapter failed: ..."
# We capture engine, mode, seed, status marker, and (for success) wall + engine
# seconds. Status marker is the unicode check / cross.
_CELL_TAPE_RE = re.compile(
    r"^\s*\[\s*\d+/\d+\]\s+"           # cell index "[N/M]"
    r"(?P<engine>\w+)\s+"              # engine: sumo|matsim|dtalite
    r"(?P<mode>\w+)\s+"                # mode: meso|micro
    r"seed=(?P<seed>\d+)\s+"           # seed=42
    r"(?P<status>[✓✗])"      # ✓ or ✗
    r"\s*(?P<rest>.*)$"                # rest of line — timing or error
)
_TIMING_RE = re.compile(
    r"(?P<wall>\d+(?:\.\d+)?)s\s+wall\s*\(\s*(?P<engine_s>\d+(?:\.\d+)?)s\s+engine\)"
)


def _parse_harness_log(log_path: Path) -> dict[tuple[str, str, int], dict]:
    """Parse a harness cell-tape log and return per-cell timing info.

    Returns a dict keyed on ``(engine, mode, seed)`` mapping to::

        {"status": "success"|"failed", "wall_s": float, "engine_s": float,
         "error_msg": str|None}

    Cells not represented in the log are simply absent from the dict;
    the caller falls back to its existing default behaviour.
    """
    parsed: dict[tuple[str, str, int], dict] = {}
    if not log_path.is_file():
        logger.warning("--harness-log %s not found; runtime fields will be 0", log_path)
        return parsed

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _CELL_TAPE_RE.match(line)
            if not m:
                continue
            engine = m["engine"].lower()
            mode = m["mode"].lower()
            seed = int(m["seed"])
            status = "success" if m["status"] == "✓" else "failed"
            rest = (m["rest"] or "").strip()

            wall_s = engine_s = 0.0
            error_msg: str | None = None
            if status == "success":
                tm = _TIMING_RE.search(rest)
                if tm:
                    wall_s = float(tm["wall"])
                    engine_s = float(tm["engine_s"])
            else:
                # "FAIL  <error message>" — strip leading "FAIL"
                error_msg = re.sub(r"^FAIL\s+", "", rest).strip() or "unknown failure"

            parsed[(engine, mode, seed)] = {
                "status": status,
                "wall_s": wall_s,
                "engine_s": engine_s,
                "error_msg": error_msg,
            }

    logger.info("Parsed %d cell-tape entries from %s", len(parsed), log_path)
    return parsed


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
    harness_log_path: Path | None = None,
) -> Path:
    """Walk per-cell artifacts, build summary JSON, write to disk.

    Returns the output path written.
    """
    runspec = yaml.safe_load(runspec_path.read_text())
    runspec_name = runspec.get("name") or runspec_path.stem

    scenario_rows = [r for r in runspec["runs"] if r["scenario_id"] == scenario_id]
    if not scenario_rows:
        raise SystemExit(f"No runs for scenario {scenario_id} in {runspec_path}")

    log_runtimes = _parse_harness_log(harness_log_path) if harness_log_path else {}

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

            # Determine runtime values. Priority order:
            #   1. Harness log (most accurate — actual wall + engine times).
            #   2. Synthesized timeout (when cell failed with a timeout error).
            #   3. Zero (fallback).
            log_entry = log_runtimes.get((engine, mode, seed))
            if log_entry and log_entry["status"] == "success" and status == "success":
                engine_wall_s = log_entry["engine_s"]
                cell_wall_s = log_entry["wall_s"]
                runtime_s = engine_wall_s
            elif status == "failed" and error and "timeout" in error.lower():
                runtime_s = float(timeout_s)
                engine_wall_s = runtime_s
                cell_wall_s = runtime_s
            else:
                runtime_s = engine_wall_s = cell_wall_s = 0.0

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
                engine_wall_s=engine_wall_s,
                cell_wall_s=cell_wall_s,
            ))
            if status == "success":
                n_success += 1
            else:
                n_failed += 1
            tag = "OK" if status == "success" else "FAIL"
            src = "log" if log_entry and log_entry["status"] == "success" else "disk"
            logger.info("  [%s] %s/%s/%s/seed_%d  runtime=%.1fs (%s)  %s",
                        tag, scenario_id, engine, mode, seed, runtime_s, src, error or "")

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
    parser.add_argument("--harness-log", type=Path, default=None,
                        help="Optional path to the harness's stdout/stderr log "
                             "(e.g. logs/simforge_benchmark_small_..._<scenario>.log). "
                             "When supplied, runtime fields for successful cells "
                             "are populated from the cell-tape lines instead of being 0.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.runspec.is_file():
        print(f"runspec not found: {args.runspec}", file=sys.stderr)
        return 2
    if not args.base_dir.is_dir():
        print(f"base-dir not found: {args.base_dir}", file=sys.stderr)
        return 2

    recover_scenario(args.runspec, args.scenario, args.base_dir, args.output,
                     harness_log_path=args.harness_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
