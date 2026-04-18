#!/usr/bin/env python3
"""
Generate thesis-ready plots from benchmark results.

Creates:
1. Runtime comparison bar chart (grouped by city/engine)
2. Reproducibility heatmap (engine × city matrix)  
3. Travel time comparison bar chart
4. Engine performance summary radar/spider chart
5. Speedup analysis chart

Usage:
    python -m evaluation.generate_plots runs/benchmark_results_*.json
    python -m evaluation.generate_plots runs/benchmark_results_*.json --output doc/figures
"""

import json
import argparse
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import statistics

# Check for matplotlib availability
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not installed. Install with: pip install matplotlib")


def _require_matplotlib():
    """Raise a clear error if matplotlib is not available."""
    if not MATPLOTLIB_AVAILABLE:
        raise ImportError(
            "matplotlib is required for plot generation but is not installed.\n"
            "  Install it with: pip install matplotlib"
        )

# Optional seaborn for prettier plots
try:
    import seaborn as sns
    SEABORN_AVAILABLE = True
except ImportError:
    SEABORN_AVAILABLE = False


@dataclass
class ScenarioMetrics:
    """Aggregated metrics for a scenario-engine combination."""
    scenario: str
    city: str  # Extracted city name
    engine: str
    mode: str  # micro/meso
    runs: int
    successes: int
    avg_runtime: float
    std_runtime: float
    avg_trips: int
    avg_travel_time: float
    std_travel_time: float
    p95_travel_time: float
    reproducibility: float


def load_results(results_path: Path) -> dict:
    """Load benchmark results from JSON."""
    with open(results_path, encoding="utf-8") as f:
        return json.load(f)


def extract_city_engine(scenario_id: str) -> tuple[str, str, str]:
    """
    Parse scenario_id to extract city, engine, and mode.
    
    Examples:
        chicago_downtown_sumo_meso -> (chicago, sumo, meso)
        sioux_falls_matsim -> (sioux_falls, matsim, meso)
    """
    engines = ["sumo", "qarsumo", "matsim"]
    modes = ["meso", "micro", "mesoscopic", "microscopic"]
    
    # Find engine
    engine = "unknown"
    for eng in engines:
        if f"_{eng}" in scenario_id:
            engine = eng
            break
    
    # Find mode
    mode = "meso"  # default
    for m in modes:
        if f"_{m}" in scenario_id:
            mode = "meso" if "meso" in m else "micro"
            break
    
    # Extract city (everything before engine)
    city = scenario_id
    for eng in engines:
        city = city.replace(f"_{eng}_meso", "").replace(f"_{eng}_micro", "").replace(f"_{eng}", "")
    for m in modes:
        city = city.replace(f"_{m}", "")
    
    return city, engine, mode


def compute_reproducibility(values: list[float]) -> float:
    """Compute R = 1 - CV (coefficient of variation)."""
    if len(values) < 2:
        return 1.0
    mean_val = statistics.mean(values)
    if mean_val == 0:
        return 1.0
    std_val = statistics.stdev(values)
    cv = std_val / mean_val
    return max(0.0, 1.0 - cv)


def _identify(run: dict) -> tuple[str, str, str]:
    """Return (city/scenario, engine, mode), preferring explicit fields."""
    scenario = run.get("scenario")
    engine = run.get("engine")
    mode = run.get("mode")
    sid = run.get("scenario_id", "")
    if not (scenario and engine and mode):
        parsed_scenario, parsed_engine, parsed_mode = extract_city_engine(sid)
        scenario = scenario or parsed_scenario
        engine = engine or parsed_engine
        mode = mode or parsed_mode
    if mode not in ("micro", "meso"):
        mode = "meso" if "meso" in (mode or "") else "micro"
    return scenario, engine, mode


def analyze_results(results: dict) -> list[ScenarioMetrics]:
    """Analyze benchmark results into scenario metrics."""
    metrics_list = []

    # Group runs by (scenario, engine, mode) using explicit fields when present
    by_group: dict[tuple[str, str, str], list[dict]] = {}
    for run in results.get("results", results.get("runs", [])):
        key = _identify(run)
        by_group.setdefault(key, []).append(run)

    for (city, engine, mode), runs in by_group.items():
        scenario_id = f"{city}_{engine}_{mode}"
        
        successful = [r for r in runs if r.get("status") == "success"]
        if not successful:
            continue
        
        runtimes = [r.get("runtime_s", 0) for r in successful]
        trip_counts = [r.get("metrics", {}).get("travel_time", {}).get("trip_count", 0) for r in successful]
        travel_times = [r.get("metrics", {}).get("travel_time", {}).get("mean", 0) for r in successful]
        p95_times = [r.get("metrics", {}).get("travel_time", {}).get("p95", 0) for r in successful]
        
        valid_tt = [tt for tt in travel_times if tt > 0]
        
        metrics = ScenarioMetrics(
            scenario=scenario_id,
            city=city,
            engine=engine,
            mode=mode,
            runs=len(runs),
            successes=len(successful),
            avg_runtime=statistics.mean(runtimes) if runtimes else 0,
            std_runtime=statistics.stdev(runtimes) if len(runtimes) > 1 else 0,
            avg_trips=int(statistics.mean(trip_counts)) if trip_counts else 0,
            avg_travel_time=statistics.mean(valid_tt) if valid_tt else 0,
            std_travel_time=statistics.stdev(valid_tt) if len(valid_tt) > 1 else 0,
            p95_travel_time=statistics.mean(p95_times) if p95_times else 0,
            reproducibility=compute_reproducibility(valid_tt)
        )
        metrics_list.append(metrics)
    
    return metrics_list


def setup_style():
    """Configure matplotlib style for thesis-quality plots."""
    if SEABORN_AVAILABLE:
        sns.set_theme(style="whitegrid", palette="deep")
    
    plt.rcParams.update({
        'figure.figsize': (10, 6),
        'figure.dpi': 150,
        'font.size': 11,
        'font.family': 'sans-serif',
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'legend.fontsize': 10,
        'figure.titlesize': 16,
    })


def plot_runtime_comparison(metrics: list[ScenarioMetrics], output_dir: Path) -> Path:
    """
    Generate runtime comparison bar chart (Figure 5.1).
    Grouped by city, colored by engine.
    """
    _require_matplotlib()
    setup_style()
    
    # Organize data
    cities = sorted(set(m.city for m in metrics))
    engines = sorted(set(m.engine for m in metrics))
    
    # Color palette
    colors = {
        'sumo': '#1f77b4',      # Blue
        'qarsumo': '#ff7f0e',   # Orange  
        'matsim': '#2ca02c',    # Green
    }
    
    _, ax = plt.subplots(figsize=(12, 6))
    
    bar_width = 0.25
    group_gap = 0.3
    
    current_x = 0
    city_centers = []
    
    for city in cities:
        city_metrics = [m for m in metrics if m.city == city]
        city_engines = sorted(set(m.engine for m in city_metrics))
        
        city_start = current_x
        for _idx, engine in enumerate(city_engines):
            engine_data = [m for m in city_metrics if m.engine == engine]
            if engine_data:
                m = engine_data[0]
                ax.bar(current_x, m.avg_runtime, bar_width,
                            yerr=m.std_runtime, capsize=3,
                            color=colors.get(engine, 'gray'),
                            label=engine if city == cities[0] else None,
                            edgecolor='black', linewidth=0.5)
                current_x += bar_width
        
        city_centers.append((city_start + current_x - bar_width) / 2)
        current_x += group_gap
    
    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Runtime (seconds)', fontweight='bold')
    ax.set_title('Figure 5.1: Runtime Comparison by City and Engine', fontweight='bold', pad=20)
    
    # Format city names for display
    city_labels = [c.replace('_', ' ').title() for c in cities]
    ax.set_xticks(city_centers)
    ax.set_xticklabels(city_labels)
    
    # Legend
    handles = [mpatches.Patch(color=colors.get(e, 'gray'), label=e.upper()) for e in engines]
    ax.legend(handles=handles, title='Engine', loc='upper right')
    
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    
    output_path = output_dir / "fig_5_1_runtime_comparison.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_1_runtime_comparison.pdf", bbox_inches='tight')
    plt.close()
    
    return output_path


def plot_reproducibility_heatmap(metrics: list[ScenarioMetrics], output_dir: Path) -> Path:
    """
    Generate reproducibility heatmap (Figure 5.2).
    Engine × City matrix showing R-scores.
    """
    _require_matplotlib()
    setup_style()
    
    cities = sorted(set(m.city for m in metrics))
    engines = sorted(set(m.engine for m in metrics))
    
    # Build matrix
    matrix = []
    for engine in engines:
        row = []
        for city in cities:
            matching = [m for m in metrics if m.engine == engine and m.city == city]
            if matching:
                row.append(matching[0].reproducibility)
            else:
                row.append(0)
        matrix.append(row)
    
    _, ax = plt.subplots(figsize=(10, 6))
    
    # Create heatmap
    if SEABORN_AVAILABLE:
        im = sns.heatmap(matrix, annot=True, fmt='.4f', cmap='RdYlGn',
                        xticklabels=[c.replace('_', ' ').title() for c in cities],
                        yticklabels=[e.upper() for e in engines],
                        vmin=0.9, vmax=1.0, ax=ax,
                        cbar_kws={'label': 'Reproducibility Score (R)'})
    else:
        im = ax.imshow(matrix, cmap='RdYlGn', vmin=0.9, vmax=1.0, aspect='auto')
        
        # Add text annotations
        for i in range(len(engines)):
            for j in range(len(cities)):
                ax.text(j, i, f'{matrix[i][j]:.4f}',
                              ha='center', va='center', color='black', fontsize=10)
        
        ax.set_xticks(range(len(cities)))
        ax.set_xticklabels([c.replace('_', ' ').title() for c in cities])
        ax.set_yticks(range(len(engines)))
        ax.set_yticklabels([e.upper() for e in engines])
        
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Reproducibility Score (R)')
    
    ax.set_title('Figure 5.2: Reproducibility Analysis\n(R = 1 - CV, higher is better)', 
                 fontweight='bold', pad=20)
    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Engine', fontweight='bold')
    
    plt.tight_layout()
    
    output_path = output_dir / "fig_5_2_reproducibility_heatmap.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_2_reproducibility_heatmap.pdf", bbox_inches='tight')
    plt.close()
    
    return output_path


def plot_travel_time_comparison(metrics: list[ScenarioMetrics], output_dir: Path) -> Path:
    """
    Generate travel time comparison chart (Figure 5.3).
    Shows mean travel time with error bars.
    """
    _require_matplotlib()
    setup_style()
    
    cities = sorted(set(m.city for m in metrics))
    engines = sorted(set(m.engine for m in metrics))
    
    colors = {
        'sumo': '#1f77b4',
        'qarsumo': '#ff7f0e',
        'matsim': '#2ca02c',
    }
    
    _, ax = plt.subplots(figsize=(12, 6))
    
    bar_width = 0.25
    group_gap = 0.3
    current_x = 0
    city_centers = []
    
    for city in cities:
        city_metrics = [m for m in metrics if m.city == city]
        city_engines = sorted(set(m.engine for m in city_metrics))
        
        city_start = current_x
        for _idx, engine in enumerate(city_engines):
            engine_data = [m for m in city_metrics if m.engine == engine]
            if engine_data:
                m = engine_data[0]
                ax.bar(current_x, m.avg_travel_time, bar_width,
                      yerr=m.std_travel_time if m.std_travel_time > 0 else None, 
                      capsize=3,
                      color=colors.get(engine, 'gray'),
                      label=engine if city == cities[0] else None,
                      edgecolor='black', linewidth=0.5)
                current_x += bar_width
        
        city_centers.append((city_start + current_x - bar_width) / 2)
        current_x += group_gap
    
    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Mean Travel Time (seconds)', fontweight='bold')
    ax.set_title('Figure 5.3: Travel Time Comparison by Engine', fontweight='bold', pad=20)
    
    city_labels = [c.replace('_', ' ').title() for c in cities]
    ax.set_xticks(city_centers)
    ax.set_xticklabels(city_labels)
    
    handles = [mpatches.Patch(color=colors.get(e, 'gray'), label=e.upper()) for e in engines]
    ax.legend(handles=handles, title='Engine', loc='upper right')
    
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    
    output_path = output_dir / "fig_5_3_travel_time_comparison.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_3_travel_time_comparison.pdf", bbox_inches='tight')
    plt.close()
    
    return output_path


def plot_engine_summary(metrics: list[ScenarioMetrics], output_dir: Path) -> Path:
    """
    Generate engine performance summary (Figure 5.4).
    Aggregated statistics per engine.
    """
    _require_matplotlib()
    setup_style()
    
    engines = sorted(set(m.engine for m in metrics))
    
    # Aggregate per engine
    engine_data = {}
    for engine in engines:
        engine_metrics = [m for m in metrics if m.engine == engine]
        engine_data[engine] = {
            'avg_runtime': statistics.mean([m.avg_runtime for m in engine_metrics]),
            'avg_reproducibility': statistics.mean([m.reproducibility for m in engine_metrics]),
            'total_trips': sum([m.avg_trips for m in engine_metrics]),
            'scenarios': len(engine_metrics),
        }
    
    colors = {
        'sumo': '#1f77b4',
        'qarsumo': '#ff7f0e',
        'matsim': '#2ca02c',
    }
    
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    
    # Plot 1: Average Runtime
    ax1 = axes[0]
    runtimes = [engine_data[e]['avg_runtime'] for e in engines]
    bars1 = ax1.bar(engines, runtimes, color=[colors.get(e, 'gray') for e in engines], 
                    edgecolor='black', linewidth=0.5)
    ax1.set_ylabel('Average Runtime (seconds)', fontweight='bold')
    ax1.set_title('Runtime', fontweight='bold')
    ax1.set_xticks(range(len(engines)))
    ax1.set_xticklabels([e.upper() for e in engines])
    
    # Add value labels
    for bar, val in zip(bars1, runtimes):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                f'{val:.2f}s', ha='center', va='bottom', fontsize=9)
    
    # Plot 2: Reproducibility
    ax2 = axes[1]
    repros = [engine_data[e]['avg_reproducibility'] for e in engines]
    bars2 = ax2.bar(engines, repros, color=[colors.get(e, 'gray') for e in engines],
                    edgecolor='black', linewidth=0.5)
    ax2.set_ylabel('Average R-Score', fontweight='bold')
    ax2.set_title('Reproducibility', fontweight='bold')
    ax2.set_xticks(range(len(engines)))
    ax2.set_xticklabels([e.upper() for e in engines])
    ax2.set_ylim(0.98, 1.005)
    
    for bar, val in zip(bars2, repros):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                f'{val:.4f}', ha='center', va='bottom', fontsize=9)
    
    # Plot 3: Throughput (trips/second)
    ax3 = axes[2]
    throughputs = []
    for e in engines:
        m_list = [m for m in metrics if m.engine == e]
        total_trips = sum(m.avg_trips for m in m_list)
        total_runtime = sum(m.avg_runtime for m in m_list)
        throughputs.append(total_trips / total_runtime if total_runtime > 0 else 0)
    
    bars3 = ax3.bar(engines, throughputs, color=[colors.get(e, 'gray') for e in engines],
                    edgecolor='black', linewidth=0.5)
    ax3.set_ylabel('Throughput (trips/second)', fontweight='bold')
    ax3.set_title('Throughput', fontweight='bold')
    ax3.set_xticks(range(len(engines)))
    ax3.set_xticklabels([e.upper() for e in engines])
    
    for bar, val in zip(bars3, throughputs):
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 50,
                f'{val:.0f}', ha='center', va='bottom', fontsize=9)
    
    fig.suptitle('Figure 5.4: Engine Performance Summary', fontweight='bold', y=1.02)
    
    plt.tight_layout()
    
    output_path = output_dir / "fig_5_4_engine_summary.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_4_engine_summary.pdf", bbox_inches='tight')
    plt.close()
    
    return output_path


def plot_speedup_analysis(metrics: list[ScenarioMetrics], output_dir: Path) -> Path:
    """Generate speedup analysis (Figure 5.5). Compare SUMO/QarSUMO to MATSim baseline."""
    _require_matplotlib()
    setup_style()
    
    cities = sorted(set(m.city for m in metrics))
    
    # Calculate speedup relative to MATSim (slowest)
    speedups = {'sumo': [], 'qarsumo': []}
    city_labels = []
    
    for city in cities:
        city_metrics = {m.engine: m for m in metrics if m.city == city}
        
        if 'matsim' in city_metrics:
            baseline = city_metrics['matsim'].avg_runtime
            
            for engine in ['sumo', 'qarsumo']:
                if engine in city_metrics:
                    speedup = baseline / city_metrics[engine].avg_runtime
                    speedups[engine].append(speedup)
                else:
                    speedups[engine].append(0)
            
            city_labels.append(city.replace('_', ' ').title())
    
    if not city_labels:
        print("No MATSim baseline for speedup comparison")
        return None
    
    _, ax = plt.subplots(figsize=(10, 6))
    
    x = range(len(city_labels))
    width = 0.35
    
    bars1 = ax.bar([i - width/2 for i in x], speedups['sumo'], width, 
                   label='SUMO', color='#1f77b4', edgecolor='black', linewidth=0.5)
    bars2 = ax.bar([i + width/2 for i in x], speedups['qarsumo'], width,
                   label='QarSUMO', color='#ff7f0e', edgecolor='black', linewidth=0.5)
    
    ax.axhline(y=1, color='gray', linestyle='--', linewidth=1, alpha=0.7, label='MATSim baseline')
    
    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Speedup Factor (× faster than MATSim)', fontweight='bold')
    ax.set_title('Figure 5.5: Speedup vs MATSim Baseline', fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(city_labels)
    ax.legend()
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, height + 0.5,
                   f'{height:.1f}×', ha='center', va='bottom', fontsize=9)
    
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    
    output_path = output_dir / "fig_5_5_speedup_analysis.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_5_speedup_analysis.pdf", bbox_inches='tight')
    plt.close()
    
    return output_path


def plot_micro_vs_meso(metrics: list[ScenarioMetrics], output_dir: Path) -> Optional[Path]:
    """
    Generate micro vs meso runtime comparison (Figure 5.6).
    Side-by-side bars for each engine showing micro and meso runtimes.
    """
    _require_matplotlib()
    setup_style()

    engines = sorted(set(m.engine for m in metrics))
    cities = sorted(set(m.city for m in metrics))
    modes = sorted(set(m.mode for m in metrics))

    if len(modes) < 2:
        print("    (skipped — only one mode in results)")
        return None

    mode_colors = {'micro': '#2ca02c', 'meso': '#ff7f0e'}

    fig, axes = plt.subplots(1, len(engines), figsize=(5 * len(engines), 6), sharey=True)
    if len(engines) == 1:
        axes = [axes]

    for ax, engine in zip(axes, engines):
        bar_width = 0.3
        current_x = 0
        city_centers = []

        for city in cities:
            city_start = current_x
            for _idx, mode in enumerate(['micro', 'meso']):
                matching = [m for m in metrics if m.engine == engine and m.city == city and m.mode == mode]
                if matching:
                    m = matching[0]
                    ax.bar(current_x, m.avg_runtime, bar_width,
                           yerr=m.std_runtime, capsize=3,
                           color=mode_colors.get(mode, 'gray'),
                           edgecolor='black', linewidth=0.5)
                current_x += bar_width
            city_centers.append((city_start + current_x - bar_width) / 2)
            current_x += 0.2

        ax.set_title(engine.upper(), fontweight='bold')
        ax.set_xticks(city_centers)
        ax.set_xticklabels([c.replace('_', ' ').title() for c in cities], fontsize=9)
        ax.set_ylim(bottom=0)
        ax.grid(axis='y', alpha=0.3)

    axes[0].set_ylabel('Runtime (seconds)', fontweight='bold')

    handles = [mpatches.Patch(color=mode_colors[m], label=m.title()) for m in ['micro', 'meso']]
    fig.legend(handles=handles, title='Mode', loc='upper right', bbox_to_anchor=(0.98, 0.95))
    fig.suptitle('Figure 5.6: Micro vs Meso Runtime by Engine', fontweight='bold', y=1.02)

    plt.tight_layout()

    output_path = output_dir / "fig_5_6_micro_vs_meso.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_6_micro_vs_meso.pdf", bbox_inches='tight')
    plt.close()

    return output_path


def plot_runtime_variability(results_paths: list[Path], output_dir: Path) -> Optional[Path]:
    """
    Generate runtime variability box plot (Figure 5.7).
    Shows run-to-run spread per engine.
    """
    _require_matplotlib()
    setup_style()

    # Collect raw runtimes per engine
    engine_runtimes: dict[str, list[float]] = {}
    for rp in results_paths:
        results = load_results(rp)
        for run in results.get("results", results.get("runs", [])):
            if run.get("status") != "success":
                continue
            engine = run.get("engine", "unknown")
            rt = run.get("runtime_s", run.get("wall_time_s", 0))
            if rt > 0:
                engine_runtimes.setdefault(engine, []).append(rt)

    if not engine_runtimes:
        return None

    engines = sorted(engine_runtimes.keys())
    colors = {'sumo': '#1f77b4', 'qarsumo': '#ff7f0e', 'matsim': '#2ca02c'}

    _, ax = plt.subplots(figsize=(8, 6))

    bp = ax.boxplot(
        [engine_runtimes[e] for e in engines],
        tick_labels=[e.upper() for e in engines],
        patch_artist=True,
        showmeans=True,
        meanprops=dict(marker='D', markerfacecolor='red', markersize=6),
    )

    for patch, engine in zip(bp['boxes'], engines):
        patch.set_facecolor(colors.get(engine, 'gray'))
        patch.set_alpha(0.7)

    ax.set_ylabel('Runtime (seconds)', fontweight='bold')
    ax.set_title('Figure 5.7: Runtime Variability by Engine\n(box = IQR, diamond = mean, line = median)',
                 fontweight='bold', pad=20)
    ax.grid(axis='y', alpha=0.3)

    # Annotate counts
    for i, engine in enumerate(engines):
        n = len(engine_runtimes[engine])
        ax.text(i + 1, ax.get_ylim()[1] * 0.95, f'n={n}', ha='center', fontsize=9, color='gray')

    plt.tight_layout()

    output_path = output_dir / "fig_5_7_runtime_variability.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_7_runtime_variability.pdf", bbox_inches='tight')
    plt.close()

    return output_path


def plot_p95_travel_time(metrics: list[ScenarioMetrics], output_dir: Path) -> Optional[Path]:
    """
    Generate P95 tail-latency travel time comparison (Figure 5.8).
    Shows 95th-percentile travel times to highlight worst-case trips.
    """
    _require_matplotlib()
    setup_style()

    cities = sorted(set(m.city for m in metrics))
    engines = sorted(set(m.engine for m in metrics))

    # Filter to metrics that have p95 data
    has_p95 = [m for m in metrics if m.p95_travel_time > 0]
    if not has_p95:
        print("    (skipped — no P95 data)")
        return None

    colors = {'sumo': '#1f77b4', 'qarsumo': '#ff7f0e', 'matsim': '#2ca02c'}

    _, ax = plt.subplots(figsize=(12, 6))

    bar_width = 0.25
    group_gap = 0.3
    current_x = 0
    city_centers = []

    for city in cities:
        city_metrics = [m for m in has_p95 if m.city == city]
        city_engines = sorted(set(m.engine for m in city_metrics))

        city_start = current_x
        for engine in city_engines:
            engine_data = [m for m in city_metrics if m.engine == engine]
            if engine_data:
                m = engine_data[0]
                ax.bar(current_x, m.p95_travel_time, bar_width,
                       color=colors.get(engine, 'gray'),
                       label=engine if city == cities[0] else None,
                       edgecolor='black', linewidth=0.5)
                # Show mean as a marker for comparison
                ax.plot(current_x, m.avg_travel_time, 'k_', markersize=12, markeredgewidth=2)
            current_x += bar_width

        city_centers.append((city_start + current_x - bar_width) / 2)
        current_x += group_gap

    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Travel Time (seconds)', fontweight='bold')
    ax.set_title('Figure 5.8: P95 Tail Latency vs Mean Travel Time\n(bar = P95, dash = mean)',
                 fontweight='bold', pad=20)

    city_labels = [c.replace('_', ' ').title() for c in cities]
    ax.set_xticks(city_centers)
    ax.set_xticklabels(city_labels)

    handles = [mpatches.Patch(color=colors.get(e, 'gray'), label=e.upper()) for e in engines]
    handles.append(plt.Line2D([0], [0], marker='_', color='black', label='Mean', markersize=10, linewidth=0))
    ax.legend(handles=handles, title='Engine', loc='upper right')

    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()

    output_path = output_dir / "fig_5_8_p95_tail_latency.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.savefig(output_dir / "fig_5_8_p95_tail_latency.pdf", bbox_inches='tight')
    plt.close()

    return output_path


def generate_all_plots(results_paths: list[Path], output_dir: Path) -> dict:
    """Generate all thesis plots from benchmark results (supports multiple files)."""
    
    if not MATPLOTLIB_AVAILABLE:
        print("ERROR: matplotlib is required for plot generation")
        print("Install with: pip install matplotlib seaborn")
        return {"error": "matplotlib not installed"}
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load and combine results from all files
    all_metrics = []
    total_runs = 0
    successful_runs = 0
    
    for results_path in results_paths:
        print(f"Loading results from: {results_path}")
        results = load_results(results_path)
        
        print(f"  Benchmark: {results.get('runspec_name', results.get('timestamp', 'unknown'))}")
        print(f"  Runs: {results.get('total_runs', len(results.get('results', results.get('runs', []))))} total, "
              f"{results.get('successful_runs', results.get('summary', {}).get('completed', '?'))} successful")
        
        total_runs += results.get('total_runs', len(results.get('results', results.get('runs', []))))
        successful_runs += results.get('successful_runs', results.get('summary', {}).get('completed', 0))
        
        file_metrics = analyze_results(results)
        all_metrics.extend(file_metrics)
    
    # Deduplicate metrics (keep latest by scenario)
    seen = {}
    for m in all_metrics:
        key = (m.scenario, m.engine)
        seen[key] = m  # Later entries overwrite earlier
    
    metrics = list(seen.values())
    print(f"\nCombined: {total_runs} total runs, {len(metrics)} unique scenario-engine combinations")
    
    generated = {}
    
    # Generate each plot
    print("\nGenerating plots...")
    
    print("  → Runtime comparison (Fig 5.1)...")
    generated['runtime'] = str(plot_runtime_comparison(metrics, output_dir))
    
    print("  → Reproducibility heatmap (Fig 5.2)...")
    generated['reproducibility'] = str(plot_reproducibility_heatmap(metrics, output_dir))
    
    print("  → Travel time comparison (Fig 5.3)...")
    generated['travel_time'] = str(plot_travel_time_comparison(metrics, output_dir))
    
    print("  → Engine summary (Fig 5.4)...")
    generated['engine_summary'] = str(plot_engine_summary(metrics, output_dir))
    
    print("  → Speedup analysis (Fig 5.5)...")
    speedup_path = plot_speedup_analysis(metrics, output_dir)
    if speedup_path:
        generated['speedup'] = str(speedup_path)
    
    print("  → Micro vs Meso comparison (Fig 5.6)...")
    micro_meso_path = plot_micro_vs_meso(metrics, output_dir)
    if micro_meso_path:
        generated['micro_vs_meso'] = str(micro_meso_path)
    
    print("  → Runtime variability box plot (Fig 5.7)...")
    variability_path = plot_runtime_variability(results_paths, output_dir)
    if variability_path:
        generated['runtime_variability'] = str(variability_path)
    
    print("  → P95 tail latency (Fig 5.8)...")
    p95_path = plot_p95_travel_time(metrics, output_dir)
    if p95_path:
        generated['p95_tail_latency'] = str(p95_path)
    
    print(f"\n✓ Generated {len(generated)} plots in: {output_dir}")
    
    return generated


def main():
    parser = argparse.ArgumentParser(
        description="Generate thesis-ready plots from benchmark results"
    )
    parser.add_argument(
        "results", type=Path, nargs='+',
        help="Path to benchmark results JSON file(s) - supports multiple files"
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output directory for plots (default: plots/ next to the first results file)"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Delete existing plots in output directory before generating"
    )
    
    args = parser.parse_args()
    
    # Validate all input files exist
    for results_path in args.results:
        if not results_path.exists():
            print(f"Error: Results file not found: {results_path}")
            return 1
    
    # Default output: plots/ directory next to the first results file
    output_dir = args.output
    if output_dir is None:
        output_dir = args.results[0].resolve().parent / "plots"
    
    # Clean existing plots if requested
    if args.clean and output_dir.exists():
        old_plots = list(output_dir.glob("*.png")) + list(output_dir.glob("*.pdf"))
        if old_plots:
            for p in old_plots:
                p.unlink()
            print(f"Cleaned {len(old_plots)} existing plots from {output_dir}")
    
    generated = generate_all_plots(args.results, output_dir)
    
    if "error" in generated:
        return 1
    
    print("\nGenerated files:")
    for name, path in generated.items():
        print(f"  • {name}: {path}")
    
    return 0


if __name__ == "__main__":
    exit(main())
