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
        for eng in ("sumo", "qarsumo", "matsim"):
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

    # Group runs by (scenario, engine, mode) — meso and micro are different
    # simulators behaviorally, so collapsing them inflates std and crushes the
    # R-score. Keeping mode in the key preserves an apples-to-apples comparison.
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
            reproducibility_score=compute_reproducibility(valid_travel_times)
        )
        stats_list.append(stats)
    
    return stats_list


def print_runtime_table(stats_list: list[ScenarioStats]) -> str:
    """Generate runtime comparison table (Table 5.1 in thesis)."""
    lines = []
    lines.append("\n" + "=" * 90)
    lines.append("TABLE 5.1: Runtime Performance Comparison (seconds)")
    lines.append("=" * 90)
    lines.append(f"{'Scenario':<25} {'Engine':<10} {'Mode':<7} {'Mean':<10} {'Std':<10} {'Min':<10} {'Max':<10}")
    lines.append("-" * 90)

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))

    for s in sorted_stats:
        if s.successes > 0:
            lines.append(f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} {s.avg_runtime:>8.2f}s {s.std_runtime:>8.3f}s {s.min_runtime:>8.2f}s {s.max_runtime:>8.2f}s")
        else:
            lines.append(f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} {'FAILED':<10} {'-':<10} {'-':<10} {'-':<10}")

    lines.append("=" * 90)
    return "\n".join(lines)


def print_reproducibility_table(stats_list: list[ScenarioStats]) -> str:
    """Generate reproducibility table (Table 5.2 in thesis)."""
    lines = []
    lines.append("\n" + "=" * 95)
    lines.append("TABLE 5.2: Reproducibility Analysis (Travel Time)")
    lines.append("=" * 95)
    lines.append(f"{'Scenario':<25} {'Engine':<10} {'Mode':<7} {'Avg TT (s)':<12} {'Std TT (s)':<12} {'R-Score':<10} {'Rating':<15}")
    lines.append("-" * 95)

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

            lines.append(f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} {s.avg_travel_time:>10.1f} {s.std_travel_time:>10.1f} {s.reproducibility_score:>8.4f} {rating:<15}")
        else:
            lines.append(f"{s.scenario:<25} {s.engine:<10} {s.mode:<7} {'FAILED':<12} {'-':<12} {'-':<10} {'-':<15}")

    lines.append("=" * 95)
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
    """Generate LaTeX table for thesis."""
    lines = []
    lines.append("\n% LaTeX table for thesis Chapter 5")
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Mesoscopic Simulation Runtime Comparison}")
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

            lines.append(f"{scenario_name} & {s.engine}/{s.mode} & {s.avg_runtime:.2f} & {int(s.avg_trips)} & {s.reproducibility_score:.4f} \\\\")
    
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table}")
    
    return "\n".join(lines)


def generate_markdown_table(stats_list: list[ScenarioStats]) -> str:
    """Generate Markdown table for documentation."""
    lines = []
    lines.append("\n## Benchmark Results\n")
    lines.append("| Scenario | Engine | Mode | Runtime (s) | Trips | Avg TT (s) | R-Score |")
    lines.append("|----------|--------|------|-------------|-------|------------|---------|")

    sorted_stats = sorted(stats_list, key=lambda x: (x.scenario, x.engine, x.mode))

    for s in sorted_stats:
        if s.successes > 0:
            lines.append(f"| {s.scenario} | {s.engine} | {s.mode} | {s.avg_runtime:.2f} | {int(s.avg_trips)} | {s.avg_travel_time:.1f} | {s.reproducibility_score:.4f} |")
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
