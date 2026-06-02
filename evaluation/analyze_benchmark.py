#!/usr/bin/env python3
"""
Analyze benchmark results and generate thesis-ready tables/plots.

Usage:
    python -m evaluation.analyze_benchmark runs/benchmark_results_*.json
"""

import json
import argparse
from pathlib import Path
from dataclasses import dataclass
import statistics

from evaluation.metrics.confidence import confidence_interval_95
from evaluation.demand_composition import (
    find_canonical_demand,
    read_demand_composition,
)


@dataclass
class ScenarioStats:
    """Statistics for a scenario-engine-mode combination."""
    scenario: str
    engine: str
    mode: str
    runs: int
    successes: int
    avg_runtime: float
    std_runtime: float
    min_runtime: float
    max_runtime: float
    avg_trips: float
    avg_travel_time: float
    std_travel_time: float
    reproducibility_score: float
    # 95 % CI half-widths on the mean. Plan §3.5 commits to reporting
    # these on every KPI.
    ci95_runtime: float = 0.0
    ci95_travel_time: float = 0.0


def load_results(results_path: Path) -> dict:
    """Load benchmark results from JSON."""
    if not results_path.is_file():
        raise FileNotFoundError(
            f"Benchmark results file not found: {results_path}\n"
            f"  Run a benchmark first: python run.py benchmark --runspec <file>"
        )
    with open(results_path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse benchmark results at {results_path}: {e}\n"
                f"  The file may be corrupted or truncated. Re-run the benchmark."
            ) from e


def compute_reproducibility(travel_times: list[float]) -> float:
    """
    Compute reproducibility score (1 - CV).
    CV = coefficient of variation = std/mean
    Score of 1.0 = perfectly deterministic
    """
    if len(travel_times) < 2:
        return 1.0
    mean_tt = statistics.mean(travel_times)
    if mean_tt == 0:
        return 1.0
    std_tt = statistics.stdev(travel_times)
    cv = std_tt / mean_tt
    return max(0.0, 1.0 - cv)


def _resolve_identity(run: dict) -> tuple[str, str, str]:
    """
    Return (scenario, engine, mode) for a run dict, preferring explicit fields
    and falling back to scenario_id string parsing for backward compat.
    """
    engine = run.get("engine")
    scenario = run.get("scenario")
    mode = run.get("mode")
    scenario_id = run.get("scenario_id", "")

    if not engine or not scenario or not mode:
        parsed_engine = "unknown"
        parsed_scenario = scenario_id or "unknown"
        parsed_mode = "unknown"
        for eng in ("sumo", "matsim", "dtalite"):
            if scenario_id.endswith(f"_{eng}") or f"_{eng}_" in scenario_id:
                parsed_engine = eng
                if f"_{eng}_meso" in scenario_id:
                    parsed_mode = "meso"
                elif f"_{eng}_micro" in scenario_id:
                    parsed_mode = "micro"
                parsed_scenario = (
                    scenario_id
                    .replace(f"_{eng}_meso", "")
                    .replace(f"_{eng}_micro", "")
                    .replace(f"_{eng}", "")
                )
                break
        engine = engine or parsed_engine
        scenario = scenario or parsed_scenario
        mode = mode or parsed_mode
    return scenario, engine, mode


def analyze_results(results: dict) -> list[ScenarioStats]:
    """Analyze benchmark results and compute statistics."""
    stats_list = []

    # Group runs by (scenario, engine, mode). Meso and micro behave like
    # different simulators, so collapsing them inflates the std and crushes
    # the R-score. Keeping mode in the key keeps the comparison honest.
    by_group: dict[tuple[str, str, str], list[dict]] = {}
    for run in results.get("results", results.get("runs", [])):
        scenario, engine, mode = _resolve_identity(run)
        by_group.setdefault((scenario, engine, mode), []).append(run)

    for (scenario, engine, mode), runs in by_group.items():

        # Use "status" field instead of "success"
        successful_runs = [r for r in runs if r.get("status") == "success"]

        if not successful_runs:
            # Record failed scenario
            stats_list.append(ScenarioStats(
                scenario=scenario,
                engine=engine,
                mode=mode,
                runs=len(runs),
                successes=0,
                avg_runtime=0,
                std_runtime=0,
                min_runtime=0,
                max_runtime=0,
                avg_trips=0,
                avg_travel_time=0,
                std_travel_time=0,
                reproducibility_score=0
            ))
            continue

        # Compute statistics from successful runs - use "runtime_s" not "runtime_seconds"
        runtimes = [r.get("runtime_s", 0) for r in successful_runs]
        # Metrics structure: metrics.travel_time.trip_count, metrics.travel_time.mean
        trip_counts = [r.get("metrics", {}).get("travel_time", {}).get("trip_count", 0) for r in successful_runs]
        travel_times = [r.get("metrics", {}).get("travel_time", {}).get("mean", 0) for r in successful_runs]

        # Filter out zero travel times (might indicate metric computation failure)
        valid_travel_times = [tt for tt in travel_times if tt > 0]

        # 95 % CI half-widths from the same per-cell sample. These shrink as
        # √N grows and as σ shrinks, so they're directly comparable across
        # cells in a way std isn't. With N=1 the CI degenerates to ± 0.0.
        ci_runtime = confidence_interval_95(runtimes).half_width if runtimes else 0.0
        ci_tt = (
            confidence_interval_95(valid_travel_times).half_width
            if valid_travel_times else 0.0
        )

        stats = ScenarioStats(
            scenario=scenario,
            engine=engine,
            mode=mode,
            runs=len(runs),
            successes=len(successful_runs),
            avg_runtime=statistics.mean(runtimes) if runtimes else 0,
            std_runtime=statistics.stdev(runtimes) if len(runtimes) > 1 else 0,
            min_runtime=min(runtimes) if runtimes else 0,
            max_runtime=max(runtimes) if runtimes else 0,
            avg_trips=statistics.mean(trip_counts) if trip_counts else 0,
            avg_travel_time=statistics.mean(valid_travel_times) if valid_travel_times else 0,
            std_travel_time=statistics.stdev(valid_travel_times) if len(valid_travel_times) > 1 else 0,
            reproducibility_score=compute_reproducibility(valid_travel_times),
            ci95_runtime=ci_runtime,
            ci95_travel_time=ci_tt,
        )
        stats_list.append(stats)
    
    return stats_list


def print_runtime_table(stats_list: list[ScenarioStats]) -> str:
    """Generate runtime comparison table (Table 5.1 in thesis)."""
    lines = []
    lines.append("\n" + "=" * 102)
    lines.append("TABLE 5.1: Runtime Performance Comparison (seconds; ± is the 95 % CI half-width on the mean)")
    lines.append("=" * 102)
    lines.append(f"{'Scenario':<25} {'Engine':<10} {'Mode':<7} {'Mean':<10} {'95% CI':<10} {'Std':<10} {'Min':<10} {'Max':<10}")
    lines.append("-" * 102)

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))

    for s in sorted_stats:
        if s.successes > 0:
            lines.append(
                f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} "
                f"{s.avg_runtime:>8.2f}s {s.ci95_runtime:>8.3f}s "
                f"{s.std_runtime:>8.3f}s {s.min_runtime:>8.2f}s {s.max_runtime:>8.2f}s"
            )
        else:
            lines.append(
                f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} "
                f"{'FAILED':<10} {'-':<10} {'-':<10} {'-':<10} {'-':<10}"
            )

    lines.append("=" * 102)
    return "\n".join(lines)


def print_reproducibility_table(stats_list: list[ScenarioStats]) -> str:
    """Generate reproducibility table (Table 5.2 in thesis)."""
    lines = []
    lines.append("\n" + "=" * 107)
    lines.append("TABLE 5.2: Reproducibility Analysis (Travel Time; ± is the 95 % CI half-width on the mean)")
    lines.append("=" * 107)
    lines.append(f"{'Scenario':<25} {'Engine':<10} {'Mode':<7} {'Avg TT (s)':<12} {'95% CI':<10} {'Std TT (s)':<12} {'R-Score':<10} {'Rating':<15}")
    lines.append("-" * 107)

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))

    for s in sorted_stats:
        if s.successes > 0 and s.avg_travel_time > 0:
            if s.reproducibility_score >= 0.99:
                rating = "Excellent"
            elif s.reproducibility_score >= 0.95:
                rating = "Good"
            elif s.reproducibility_score >= 0.90:
                rating = "Acceptable"
            else:
                rating = "Poor"

            lines.append(
                f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} "
                f"{s.avg_travel_time:>10.1f} {s.ci95_travel_time:>8.2f} "
                f"{s.std_travel_time:>10.1f} {s.reproducibility_score:>8.4f} {rating:<15}"
            )
        else:
            lines.append(
                f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} "
                f"{'FAILED':<12} {'-':<10} {'-':<12} {'-':<10} {'-':<15}"
            )

    lines.append("=" * 107)
    return "\n".join(lines)


def print_coverage_report(stats_list: list[ScenarioStats]) -> str:
    """Surface cells with thin samples or asymmetric coverage across scenarios.

    Silent undercoverage is a real risk: R-score from n=2 is just |a-b|/mean,
    and a missing (scenario, engine, mode) cell can skew cross-engine plots
    without any visual cue. This prints both so the user notices before
    drawing conclusions.
    """
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("COVERAGE DIAGNOSTIC")
    lines.append("=" * 80)

    # Low-sample cells: any successful cell with fewer than 3 good runs.
    thin = [s for s in stats_list if 0 < s.successes < 3]
    if thin:
        lines.append("\n  Low-sample cells (n < 3 — R-score is statistically weak):")
        for s in sorted(thin, key=lambda x: (x.scenario, x.engine, x.mode)):
            lines.append(
                f"    • {s.scenario:<20} {s.engine:<8} {s.mode:<7}  "
                f"n={s.successes}/{s.runs}  R={s.reproducibility_score:.4f}"
            )
    else:
        lines.append("\n  Low-sample cells: none (all successful cells have n ≥ 3)")

    # Asymmetric coverage: (engine, mode) tuples present in some scenarios but
    # not others. Reference set = union across scenarios.
    by_scenario: dict[str, set[tuple[str, str]]] = {}
    for s in stats_list:
        by_scenario.setdefault(s.scenario, set()).add((s.engine, s.mode))
    reference = set().union(*by_scenario.values()) if by_scenario else set()

    asymmetric = []
    for scenario, present in sorted(by_scenario.items()):
        missing = reference - present
        if missing:
            for engine, mode in sorted(missing):
                asymmetric.append((scenario, engine, mode))
    if asymmetric:
        lines.append(
            "\n  Asymmetric coverage — present for some scenarios, missing for others:"
        )
        for scenario, engine, mode in asymmetric:
            lines.append(
                f"    • {scenario:<20} missing: {engine}/{mode}"
            )
    else:
        lines.append("\n  Asymmetric coverage: none (every scenario covers the same cells)")

    # Failed cells: ran but all runs failed.
    failed = [s for s in stats_list if s.runs > 0 and s.successes == 0]
    if failed:
        lines.append("\n  Fully-failed cells (ran but 0 successes):")
        for s in sorted(failed, key=lambda x: (x.scenario, x.engine, x.mode)):
            lines.append(
                f"    • {s.scenario:<20} {s.engine:<8} {s.mode:<7}  "
                f"0/{s.runs} runs succeeded"
            )

    lines.append("=" * 80)
    return "\n".join(lines)


def print_demand_composition_table(stats_list: list[ScenarioStats]) -> str:
    """One row per unique scenario showing the V5+ purpose breakdown of
    its canonical demand.csv. Pre-V5 bundles (no `purpose` column) are
    skipped silently; if all bundles are pre-V5 the whole section is
    omitted from the output.
    """
    seen: dict[str, dict | None] = {}
    for s in stats_list:
        if s.scenario in seen:
            continue
        seen[s.scenario] = read_demand_composition(find_canonical_demand(s.scenario))

    tagged = [(name, comp) for name, comp in seen.items() if comp is not None]
    if not tagged:
        return ""  # no V5+ bundles, so leave the section out

    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("DEMAND COMPOSITION (V5+ trip-purpose breakdown from canonical demand.csv)")
    lines.append("=" * 80)
    lines.append(
        f"\n{'Scenario':<30} {'Total':>8}  {'AM peak':>14} {'PM peak':>14} {'School-rel.':>14}"
    )
    lines.append("-" * 84)
    for name, comp in sorted(tagged):
        total = comp["total"]
        am = comp["am_peak"]
        pm = comp["pm_peak"]
        chains = comp["chain_legs"]
        am_pct = 100.0 * am / max(total, 1)
        pm_pct = 100.0 * pm / max(total, 1)
        ch_pct = 100.0 * chains / max(total, 1)
        lines.append(
            f"{name:<30} {total:>8,}  "
            f"{am:>6,} ({am_pct:5.1f}%) "
            f"{pm:>6,} ({pm_pct:5.1f}%) "
            f"{chains:>6,} ({ch_pct:5.1f}%)"
        )
    skipped = [n for n, c in seen.items() if c is None]
    if skipped:
        lines.append(
            f"\n  (no purpose column found for: {', '.join(sorted(skipped))})"
        )
    lines.append("=" * 80)
    return "\n".join(lines)


def print_summary_table(stats_list: list[ScenarioStats]) -> str:
    """Generate summary table for thesis."""
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("SUMMARY: Benchmark Results")
    lines.append("=" * 80)
    
    # Count by engine
    engine_stats = {}
    for s in stats_list:
        if s.engine not in engine_stats:
            engine_stats[s.engine] = {"total": 0, "success": 0, "runtimes": [], "r_scores": []}
        engine_stats[s.engine]["total"] += s.runs
        engine_stats[s.engine]["success"] += s.successes
        if s.successes > 0:
            engine_stats[s.engine]["runtimes"].append(s.avg_runtime)
            if s.reproducibility_score > 0:
                engine_stats[s.engine]["r_scores"].append(s.reproducibility_score)
    
    lines.append(f"\n{'Engine':<15} {'Success Rate':<15} {'Avg Runtime':<15} {'Avg R-Score':<15}")
    lines.append("-" * 60)
    
    for engine, data in sorted(engine_stats.items()):
        rate = f"{data['success']}/{data['total']}"
        avg_rt = f"{statistics.mean(data['runtimes']):.2f}s" if data['runtimes'] else "N/A"
        avg_r = f"{statistics.mean(data['r_scores']):.4f}" if data['r_scores'] else "N/A"
        lines.append(f"{engine:<15} {rate:<15} {avg_rt:<15} {avg_r:<15}")
    
    lines.append("=" * 80)
    return "\n".join(lines)


def generate_latex_table(stats_list: list[ScenarioStats]) -> str:
    """Generate LaTeX table for thesis. Runtime and travel time include 95 % CIs."""
    lines = []
    lines.append("\n% LaTeX table for thesis Chapter 5")
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Simulation Runtime Comparison (mean $\\pm$ 95\\,\\% CI half-width)}")
    lines.append("\\label{tab:runtime-comparison}")
    lines.append("\\begin{tabular}{llrrr}")
    lines.append("\\toprule")
    lines.append("Scenario & Engine & Runtime (s) & Trips & R-Score \\\\")
    lines.append("\\midrule")

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))
    current_scenario = None

    for s in sorted_stats:
        if s.successes > 0:
            scenario_name = s.scenario.replace("_", "\\_")
            if current_scenario != s.scenario:
                if current_scenario is not None:
                    lines.append("\\midrule")
                current_scenario = s.scenario

            lines.append(
                f"{scenario_name} & {s.engine}/{s.mode} & "
                f"{s.avg_runtime:.2f} $\\pm$ {s.ci95_runtime:.3f} & "
                f"{int(s.avg_trips)} & {s.reproducibility_score:.4f} \\\\"
            )

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table}")

    return "\n".join(lines)


def generate_markdown_table(stats_list: list[ScenarioStats]) -> str:
    """Generate Markdown table for documentation. ± is the 95 % CI half-width."""
    lines = []
    lines.append("\n## Benchmark Results\n")
    lines.append("> ± values are 95 % confidence-interval half-widths on the mean (Student's t).\n")
    lines.append("| Scenario | Engine | Mode | Runtime (s) | Trips | Avg TT (s) | R-Score |")
    lines.append("|----------|--------|------|-------------|-------|------------|---------|")

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))

    for s in sorted_stats:
        if s.successes > 0:
            lines.append(
                f"| {s.scenario} | {s.engine} | {s.mode} | "
                f"{s.avg_runtime:.2f} ± {s.ci95_runtime:.3f} | {int(s.avg_trips)} | "
                f"{s.avg_travel_time:.1f} ± {s.ci95_travel_time:.2f} | {s.reproducibility_score:.4f} |"
            )
        else:
            lines.append(f"| {s.scenario} | {s.engine} | {s.mode} | FAILED | - | - | - |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument("results", type=Path, help="Path to benchmark results JSON")
    parser.add_argument("--latex", action="store_true", help="Generate LaTeX table")
    parser.add_argument("--markdown", action="store_true", help="Generate Markdown table")
    parser.add_argument("--output", "-o", type=Path, help="Output file for tables")
    args = parser.parse_args()
    
    if not args.results.exists():
        print(f"Error: Results file not found: {args.results}")
        return 1
    
    print(f"Loading results from: {args.results}")
    results = load_results(args.results)
    
    print(f"Benchmark: {results.get('runspec_name', results.get('timestamp', 'unknown'))}")
    print(f"Total runs: {len(results.get('results', results.get('runs', [])))}")
    
    stats_list = analyze_results(results)
    
    # Print all tables
    output_parts = []
    
    output_parts.append(print_summary_table(stats_list))
    output_parts.append(print_coverage_report(stats_list))
    output_parts.append(print_demand_composition_table(stats_list))
    output_parts.append(print_runtime_table(stats_list))
    output_parts.append(print_reproducibility_table(stats_list))
    
    if args.latex:
        output_parts.append(generate_latex_table(stats_list))
    
    if args.markdown:
        output_parts.append(generate_markdown_table(stats_list))
    
    full_output = "\n".join(output_parts)
    print(full_output)
    
    if args.output:
        args.output.write_text(full_output)
        print(f"\nSaved to: {args.output}")
    
    return 0


if __name__ == "__main__":
    exit(main())
