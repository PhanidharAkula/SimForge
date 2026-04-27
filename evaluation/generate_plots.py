#!/usr/bin/env python3
"""
Generate thesis-ready plots from benchmark results.

All per-(city, engine) plots facet by *mode* so meso and micro never collapse
into a single bar. Missing cells in the reproducibility heatmap render as
hatched grey ("not run") instead of red ("R=0"), to keep absent data from
looking like a failure.

Figures
-------
5.1  Runtime comparison           — facets by mode, bars by (city, engine)
5.2  Reproducibility heatmap      — rows are (engine, mode); NaN = grey
5.3  Travel time comparison       — facets by mode
5.4  Engine performance summary   — per-mode runtime, R-score, throughput
5.5  Speedup vs MATSim            — within-mode (avoids meso/micro mixing)
5.6  Micro vs Meso runtime        — explicit mode comparison per engine
5.7  Runtime variability          — boxplot per (engine, mode)
5.8  P95 tail latency vs mean     — facets by mode
5.9  Trip-count parity            — completed trips per (engine, mode);
                                    validates the SCC/feasibility filter
                                    by showing every engine ran the same N

Usage
-----
    python -m evaluation.generate_plots runs/benchmark_results_*.json
    python -m evaluation.generate_plots runs/benchmark_results_*.json --output doc/figures
"""

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from evaluation.metrics.confidence import confidence_interval_95

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not installed. Install with: pip install matplotlib")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import seaborn as sns
    SEABORN_AVAILABLE = True
except ImportError:
    SEABORN_AVAILABLE = False


ENGINE_COLORS = {
    'sumo': '#1f77b4',     # blue
    'matsim': '#2ca02c',   # green
    'lpsim': '#d62728',    # red — GPU comparator
}
MODE_COLORS = {'meso': '#ff7f0e', 'micro': '#2ca02c'}
KNOWN_ENGINES = ('sumo', 'matsim', 'lpsim')


def _require_matplotlib():
    if not MATPLOTLIB_AVAILABLE:
        raise ImportError(
            "matplotlib is required for plot generation but is not installed.\n"
            "  Install it with: pip install matplotlib"
        )


@dataclass
class ScenarioMetrics:
    """Aggregated metrics for one (city, engine, mode) cell."""
    scenario: str
    city: str
    engine: str
    mode: str
    runs: int
    successes: int
    avg_runtime: float
    std_runtime: float
    avg_trips: int
    avg_travel_time: float
    std_travel_time: float
    p95_travel_time: float
    reproducibility: float
    # 95 % confidence-interval half-widths on the mean (plan §3.5).
    # These drive the error bars on every figure that previously used ±1σ.
    ci95_runtime: float = 0.0
    ci95_travel_time: float = 0.0


def load_results(results_path: Path) -> dict:
    """Load benchmark results from JSON."""
    with open(results_path, encoding="utf-8") as f:
        return json.load(f)


def extract_city_engine(scenario_id: str) -> tuple[str, str, str]:
    """Parse scenario_id → (city, engine, mode). Used only as a fallback."""
    engine = "unknown"
    for eng in KNOWN_ENGINES:
        if f"_{eng}" in scenario_id:
            engine = eng
            break

    mode = "meso"
    if "_micro" in scenario_id:
        mode = "micro"
    elif "_meso" in scenario_id:
        mode = "meso"

    city = scenario_id
    for eng in KNOWN_ENGINES:
        city = (city
                .replace(f"_{eng}_meso", "")
                .replace(f"_{eng}_micro", "")
                .replace(f"_{eng}", ""))
    for m in ("_meso", "_micro", "_mesoscopic", "_microscopic"):
        city = city.replace(m, "")

    return city, engine, mode


def compute_reproducibility(values: list[float]) -> float:
    """R = 1 - CV. Returns 1.0 if fewer than two samples."""
    if len(values) < 2:
        return 1.0
    mean_val = statistics.mean(values)
    if mean_val == 0:
        return 1.0
    std_val = statistics.stdev(values)
    return max(0.0, 1.0 - (std_val / mean_val))


def _identify(run: dict) -> tuple[str, str, str]:
    """Return (city, engine, mode), preferring explicit fields over parsing."""
    scenario = run.get("scenario")
    engine = run.get("engine")
    mode = run.get("mode")
    if not (scenario and engine and mode):
        sid = run.get("scenario_id", "")
        parsed_scenario, parsed_engine, parsed_mode = extract_city_engine(sid)
        scenario = scenario or parsed_scenario
        engine = engine or parsed_engine
        mode = mode or parsed_mode
    if mode not in ("micro", "meso"):
        mode = "micro" if "micro" in (mode or "") else "meso"
    return scenario, engine, mode


def analyze_results(results: dict) -> list[ScenarioMetrics]:
    """Group runs by (city, engine, mode) and aggregate."""
    by_group: dict[tuple[str, str, str], list[dict]] = {}
    for run in results.get("results", results.get("runs", [])):
        by_group.setdefault(_identify(run), []).append(run)

    out: list[ScenarioMetrics] = []
    for (city, engine, mode), runs in by_group.items():
        successful = [r for r in runs if r.get("status") == "success"]
        if not successful:
            continue

        runtimes = [r.get("runtime_s", 0) for r in successful]
        trip_counts = [
            r.get("metrics", {}).get("travel_time", {}).get("trip_count", 0)
            for r in successful
        ]
        travel_times = [
            r.get("metrics", {}).get("travel_time", {}).get("mean", 0)
            for r in successful
        ]
        p95_times = [
            r.get("metrics", {}).get("travel_time", {}).get("p95", 0)
            for r in successful
        ]
        valid_tt = [tt for tt in travel_times if tt > 0]

        ci_runtime = (
            confidence_interval_95(runtimes).half_width if runtimes else 0.0
        )
        ci_tt = (
            confidence_interval_95(valid_tt).half_width if valid_tt else 0.0
        )

        out.append(ScenarioMetrics(
            scenario=f"{city}_{engine}_{mode}",
            city=city,
            engine=engine,
            mode=mode,
            runs=len(runs),
            successes=len(successful),
            avg_runtime=statistics.mean(runtimes) if runtimes else 0,
            std_runtime=statistics.stdev(runtimes) if len(runtimes) > 1 else 0,
            avg_trips=int(statistics.mean(trip_counts)) if trip_counts else 0,
            avg_travel_time=statistics.mean(valid_tt) if valid_tt else 0,
            std_travel_time=(statistics.stdev(valid_tt)
                             if len(valid_tt) > 1 else 0),
            p95_travel_time=statistics.mean(p95_times) if p95_times else 0,
            reproducibility=compute_reproducibility(valid_tt),
            ci95_runtime=ci_runtime,
            ci95_travel_time=ci_tt,
        ))
    return out


def setup_style():
    """Configure matplotlib for thesis-quality plots."""
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


def _city_label(city: str) -> str:
    return city.replace('_', ' ').title()


def _save(name: str, output_dir: Path) -> Path:
    """Save the current figure as both PNG and PDF, return PNG path."""
    png = output_dir / f"{name}.png"
    pdf = output_dir / f"{name}.pdf"
    plt.savefig(png, dpi=300, bbox_inches='tight')
    plt.savefig(pdf, bbox_inches='tight')
    plt.close()
    return png


# ---------------------------------------------------------------------------
# Figure 5.1 — Runtime comparison (faceted by mode)
# ---------------------------------------------------------------------------

def plot_runtime_comparison(metrics: list[ScenarioMetrics],
                            output_dir: Path) -> Path:
    _require_matplotlib()
    setup_style()

    cities = sorted({m.city for m in metrics})
    modes = sorted({m.mode for m in metrics})

    fig, axes = plt.subplots(1, len(modes),
                             figsize=(6 * len(modes), 6),
                             sharey=False)
    if len(modes) == 1:
        axes = [axes]

    for ax, mode in zip(axes, modes):
        engines = sorted({m.engine for m in metrics if m.mode == mode})
        bar_width = min(0.25, 0.8 / max(len(engines), 1))
        x_positions = list(range(len(cities)))

        for idx, engine in enumerate(engines):
            heights, errs = [], []
            for city in cities:
                hit = [m for m in metrics
                       if m.city == city and m.engine == engine and m.mode == mode]
                heights.append(hit[0].avg_runtime if hit else 0)
                errs.append(hit[0].ci95_runtime if hit else 0)
            offset = (idx - (len(engines) - 1) / 2) * bar_width
            ax.bar([x + offset for x in x_positions], heights, bar_width,
                   yerr=errs, capsize=3,
                   color=ENGINE_COLORS.get(engine, 'gray'),
                   edgecolor='black', linewidth=0.5,
                   label=engine.upper())

        ax.set_title(f"{mode.title()}", fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities])
        ax.set_xlim(-0.5, len(cities) - 0.5)
        ax.set_ylim(bottom=0)
        ax.margins(y=0.15)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(title='Engine', loc='upper right')

    axes[0].set_ylabel('Runtime (seconds)', fontweight='bold')
    fig.suptitle('Figure 5.1: Runtime Comparison by City, Engine, and Mode (error bars: 95 % CI)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_1_runtime_comparison", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.2 — Reproducibility heatmap (rows = engine × mode, NaN = grey)
# ---------------------------------------------------------------------------

def plot_reproducibility_heatmap(metrics: list[ScenarioMetrics],
                                 output_dir: Path) -> Path:
    _require_matplotlib()
    setup_style()

    cities = sorted({m.city for m in metrics})
    rows = sorted({(m.engine, m.mode) for m in metrics})

    nan = float('nan')
    matrix = []
    for (engine, mode) in rows:
        row = []
        for city in cities:
            hit = [m for m in metrics
                   if m.engine == engine and m.mode == mode and m.city == city]
            row.append(hit[0].reproducibility if hit else nan)
        matrix.append(row)

    row_labels = [f"{e.upper()} ({m})" for (e, m) in rows]
    col_labels = [_city_label(c) for c in cities]

    _, ax = plt.subplots(figsize=(max(8, 1.5 * len(cities) + 4),
                                  max(4, 0.8 * len(rows) + 2)))

    if SEABORN_AVAILABLE and NUMPY_AVAILABLE:
        arr = np.array(matrix, dtype=float)
        mask = np.isnan(arr)
        sns.heatmap(arr, annot=True, fmt='.4f', cmap='RdYlGn',
                    xticklabels=col_labels, yticklabels=row_labels,
                    vmin=0.9, vmax=1.0, ax=ax, mask=mask,
                    cbar_kws={'label': 'Reproducibility Score (R)'},
                    linewidths=0.5, linecolor='white')
        # Overlay grey hatch on missing cells
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                if mask[i, j]:
                    ax.add_patch(mpatches.Rectangle(
                        (j, i), 1, 1, fill=True, facecolor='#dcdcdc',
                        hatch='///', edgecolor='white', linewidth=0.5))
                    ax.text(j + 0.5, i + 0.5, 'n/a',
                            ha='center', va='center',
                            color='#555', fontsize=9, style='italic')
    else:
        # Manual fallback without seaborn
        display = [[(0.95 if v != v else v) for v in row] for row in matrix]
        im = ax.imshow(display, cmap='RdYlGn', vmin=0.9, vmax=1.0,
                       aspect='auto')
        for i in range(len(rows)):
            for j in range(len(cities)):
                v = matrix[i][j]
                if v != v:  # NaN
                    ax.add_patch(mpatches.Rectangle(
                        (j - 0.5, i - 0.5), 1, 1, fill=True,
                        facecolor='#dcdcdc', hatch='///',
                        edgecolor='white'))
                    ax.text(j, i, 'n/a', ha='center', va='center',
                            color='#555', fontsize=9, style='italic')
                else:
                    ax.text(j, i, f'{v:.4f}', ha='center', va='center',
                            color='black', fontsize=10)
        ax.set_xticks(range(len(cities)))
        ax.set_xticklabels(col_labels)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(row_labels)
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Reproducibility Score (R)')

    ax.set_title('Figure 5.2: Reproducibility Analysis\n'
                 '(R = 1 − CV; grey = not run)',
                 fontweight='bold', pad=20)
    ax.set_xlabel('City', fontweight='bold')
    ax.set_ylabel('Engine (mode)', fontweight='bold')
    plt.tight_layout()
    return _save("fig_5_2_reproducibility_heatmap", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.3 — Travel time comparison (faceted by mode)
# ---------------------------------------------------------------------------

def plot_travel_time_comparison(metrics: list[ScenarioMetrics],
                                output_dir: Path) -> Path:
    _require_matplotlib()
    setup_style()

    cities = sorted({m.city for m in metrics})
    modes = sorted({m.mode for m in metrics})

    fig, axes = plt.subplots(1, len(modes),
                             figsize=(6 * len(modes), 6), sharey=True)
    if len(modes) == 1:
        axes = [axes]

    for ax, mode in zip(axes, modes):
        engines = sorted({m.engine for m in metrics if m.mode == mode})
        bar_width = min(0.25, 0.8 / max(len(engines), 1))
        x_positions = list(range(len(cities)))

        for idx, engine in enumerate(engines):
            heights, errs = [], []
            for city in cities:
                hit = [m for m in metrics
                       if m.city == city and m.engine == engine and m.mode == mode]
                heights.append(hit[0].avg_travel_time if hit else 0)
                errs.append(hit[0].ci95_travel_time if hit else 0)
            offset = (idx - (len(engines) - 1) / 2) * bar_width
            ax.bar([x + offset for x in x_positions], heights, bar_width,
                   yerr=[e if e > 0 else 0 for e in errs], capsize=3,
                   color=ENGINE_COLORS.get(engine, 'gray'),
                   edgecolor='black', linewidth=0.5,
                   label=engine.upper())

        ax.set_title(f"{mode.title()}", fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities])
        ax.set_xlim(-0.5, len(cities) - 0.5)
        ax.set_ylim(bottom=0)
        ax.margins(y=0.15)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(title='Engine', loc='upper right')

    axes[0].set_ylabel('Mean Travel Time (seconds)', fontweight='bold')
    fig.suptitle('Figure 5.3: Travel Time Comparison by Engine and Mode (error bars: 95 % CI)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_3_travel_time_comparison", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.4 — Engine performance summary (per-mode)
# ---------------------------------------------------------------------------

def plot_engine_summary(metrics: list[ScenarioMetrics],
                        output_dir: Path) -> Path:
    _require_matplotlib()
    setup_style()

    pairs = sorted({(m.engine, m.mode) for m in metrics})
    labels = [f"{e.upper()}\n({m})" for (e, m) in pairs]

    runtimes, repros, throughputs = [], [], []
    for engine, mode in pairs:
        cell = [m for m in metrics if m.engine == engine and m.mode == mode]
        avg_rt = statistics.mean([m.avg_runtime for m in cell])
        avg_r = statistics.mean([m.reproducibility for m in cell])
        # Throughput per run (trips per second), averaged across cells
        per_run = [m.avg_trips / m.avg_runtime
                   for m in cell if m.avg_runtime > 0]
        runtimes.append(avg_rt)
        repros.append(avg_r)
        throughputs.append(statistics.mean(per_run) if per_run else 0)

    bar_colors = [ENGINE_COLORS.get(e, 'gray') for (e, _) in pairs]

    fig, axes = plt.subplots(1, 3, figsize=(5 * len(pairs) // 2 + 8, 5))

    def _bar(ax, values, ylabel, title, fmt):
        bars = ax.bar(range(len(pairs)), values,
                      color=bar_colors, edgecolor='black', linewidth=0.5)
        ax.set_xticks(range(len(pairs)))
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel(ylabel, fontweight='bold')
        ax.set_title(title, fontweight='bold')
        ax.grid(axis='y', alpha=0.3)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    fmt.format(val),
                    ha='center', va='bottom', fontsize=9)
        return bars

    _bar(axes[0], runtimes, 'Average Runtime (seconds)', 'Runtime', '{:.2f}s')

    _bar(axes[1], repros, 'Average R-Score', 'Reproducibility', '{:.4f}')
    if repros:
        lo = min(repros + [0.99])
        axes[1].set_ylim(max(0.0, lo - 0.005), 1.005)

    _bar(axes[2], throughputs,
         'Throughput (trips/second)', 'Throughput', '{:.0f}')

    fig.suptitle('Figure 5.4: Engine Performance Summary (per mode)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_4_engine_summary", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.5 — Speedup vs MATSim baseline (within-mode)
# ---------------------------------------------------------------------------

def plot_speedup_analysis(metrics: list[ScenarioMetrics],
                          output_dir: Path) -> Optional[Path]:
    _require_matplotlib()
    setup_style()

    cities = sorted({m.city for m in metrics})
    modes = sorted({m.mode for m in metrics})

    # Restrict to modes where MATSim has a baseline run
    eligible_modes = [
        mode for mode in modes
        if any(m.engine == 'matsim' and m.mode == mode for m in metrics)
    ]
    if not eligible_modes:
        print("    (skipped — no MATSim baseline)")
        return None

    fig, axes = plt.subplots(1, len(eligible_modes),
                             figsize=(6 * len(eligible_modes), 6),
                             sharey=True)
    if len(eligible_modes) == 1:
        axes = [axes]

    plotted_any = False
    for ax, mode in zip(axes, eligible_modes):
        engines = sorted({m.engine for m in metrics
                          if m.mode == mode and m.engine != 'matsim'})
        bar_width = min(0.25, 0.8 / max(len(engines), 1))
        x_positions = list(range(len(cities)))
        max_h = 0.0

        for idx, engine in enumerate(engines):
            heights = []
            for city in cities:
                base = [m for m in metrics
                        if m.engine == 'matsim' and m.city == city
                        and m.mode == mode]
                cmp = [m for m in metrics
                       if m.engine == engine and m.city == city and m.mode == mode]
                if base and cmp and cmp[0].avg_runtime > 0:
                    heights.append(base[0].avg_runtime / cmp[0].avg_runtime)
                else:
                    heights.append(0)
            offset = (idx - (len(engines) - 1) / 2) * bar_width
            bars = ax.bar([x + offset for x in x_positions], heights,
                          bar_width,
                          color=ENGINE_COLORS.get(engine, 'gray'),
                          edgecolor='black', linewidth=0.5,
                          label=engine.upper())
            for bar in bars:
                h = bar.get_height()
                if h > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, h,
                            f'{h:.1f}×', ha='center', va='bottom', fontsize=9)
                    plotted_any = True
                    max_h = max(max_h, h)

        ax.axhline(y=1, color='gray', linestyle='--', linewidth=1, alpha=0.7)
        ax.set_title(f"{mode.title()} (vs MATSim)", fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities])
        ax.set_xlim(-0.5, len(cities) - 0.5)
        if max_h > 0:
            ax.set_ylim(0, max_h * 1.25)
        else:
            ax.set_ylim(bottom=0)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(loc='upper left', framealpha=0.9)

    if not plotted_any:
        plt.close()
        print("    (skipped — no comparable engine/MATSim pairs in any mode)")
        return None

    axes[0].set_ylabel('Speedup (× faster than MATSim)', fontweight='bold')
    fig.suptitle('Figure 5.5: Speedup vs MATSim Baseline (within-mode)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_5_speedup_analysis", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.6 — Micro vs Meso runtime per engine
# ---------------------------------------------------------------------------

def plot_micro_vs_meso(metrics: list[ScenarioMetrics],
                       output_dir: Path) -> Optional[Path]:
    _require_matplotlib()
    setup_style()

    engines = sorted({m.engine for m in metrics})
    cities = sorted({m.city for m in metrics})
    modes = sorted({m.mode for m in metrics})

    if len(modes) < 2:
        print("    (skipped — only one mode in results)")
        return None

    fig, axes = plt.subplots(1, len(engines),
                             figsize=(5 * len(engines), 6), sharey=True)
    if len(engines) == 1:
        axes = [axes]

    rendered = False
    for ax, engine in zip(axes, engines):
        bar_width = 0.25
        x_positions = list(range(len(cities)))
        for idx, mode in enumerate(['micro', 'meso']):
            heights, errs = [], []
            for city in cities:
                hit = [m for m in metrics
                       if m.engine == engine and m.city == city and m.mode == mode]
                heights.append(hit[0].avg_runtime if hit else 0)
                errs.append(hit[0].ci95_runtime if hit else 0)
            if any(h > 0 for h in heights):
                rendered = True
            offset = (idx - 0.5) * bar_width
            ax.bar([x + offset for x in x_positions], heights, bar_width,
                   yerr=errs, capsize=3,
                   color=MODE_COLORS.get(mode, 'gray'),
                   edgecolor='black', linewidth=0.5,
                   label=mode.title())

        ax.set_title(engine.upper(), fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities], fontsize=9)
        ax.set_xlim(-0.5, len(cities) - 0.5)
        ax.set_ylim(bottom=0)
        ax.margins(y=0.15)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(title='Mode', loc='upper right')

    if not rendered:
        plt.close()
        return None

    axes[0].set_ylabel('Runtime (seconds)', fontweight='bold')
    fig.suptitle('Figure 5.6: Micro vs Meso Runtime by Engine',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_6_micro_vs_meso", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.7 — Runtime variability (boxplot per engine × mode)
# ---------------------------------------------------------------------------

def plot_runtime_variability(results_paths: list[Path],
                             output_dir: Path) -> Optional[Path]:
    _require_matplotlib()
    setup_style()

    by_pair: dict[tuple[str, str], list[float]] = {}
    for rp in results_paths:
        data = load_results(rp)
        for run in data.get("results", data.get("runs", [])):
            if run.get("status") != "success":
                continue
            _, engine, mode = _identify(run)
            rt = run.get("runtime_s", run.get("wall_time_s", 0))
            if rt > 0:
                by_pair.setdefault((engine, mode), []).append(rt)

    if not by_pair:
        return None

    pairs = sorted(by_pair.keys())
    data_lists = [by_pair[p] for p in pairs]
    labels = [f"{e.upper()}\n({m})" for (e, m) in pairs]

    _, ax = plt.subplots(figsize=(max(8, 1.5 * len(pairs) + 2), 6))
    bp = ax.boxplot(
        data_lists,
        tick_labels=labels,
        patch_artist=True,
        showmeans=True,
        meanprops=dict(marker='D', markerfacecolor='red', markersize=6),
    )
    for patch, (engine, _) in zip(bp['boxes'], pairs):
        patch.set_facecolor(ENGINE_COLORS.get(engine, 'gray'))
        patch.set_alpha(0.7)

    ax.set_ylabel('Runtime (seconds)', fontweight='bold')
    ax.set_title('Figure 5.7: Runtime Variability by Engine × Mode\n'
                 '(box = IQR, diamond = mean, line = median)',
                 fontweight='bold', pad=20)
    ax.grid(axis='y', alpha=0.3)
    for i, pair in enumerate(pairs):
        n = len(by_pair[pair])
        ax.text(i + 1, ax.get_ylim()[1] * 0.95, f'n={n}',
                ha='center', fontsize=9, color='gray')

    plt.tight_layout()
    return _save("fig_5_7_runtime_variability", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.8 — P95 tail latency vs mean (faceted by mode)
# ---------------------------------------------------------------------------

def plot_p95_travel_time(metrics: list[ScenarioMetrics],
                         output_dir: Path) -> Optional[Path]:
    _require_matplotlib()
    setup_style()

    has_p95 = [m for m in metrics if m.p95_travel_time > 0]
    if not has_p95:
        print("    (skipped — no P95 data)")
        return None

    cities = sorted({m.city for m in has_p95})
    modes = sorted({m.mode for m in has_p95})

    fig, axes = plt.subplots(1, len(modes),
                             figsize=(6 * len(modes), 6), sharey=True)
    if len(modes) == 1:
        axes = [axes]

    for ax, mode in zip(axes, modes):
        engines = sorted({m.engine for m in has_p95 if m.mode == mode})
        bar_width = min(0.25, 0.8 / max(len(engines), 1))
        x_positions = list(range(len(cities)))

        for idx, engine in enumerate(engines):
            offset = (idx - (len(engines) - 1) / 2) * bar_width
            for ci, city in enumerate(cities):
                hit = [m for m in has_p95
                       if m.city == city and m.engine == engine and m.mode == mode]
                if not hit:
                    continue
                m = hit[0]
                xpos = ci + offset
                ax.bar(xpos, m.p95_travel_time, bar_width,
                       color=ENGINE_COLORS.get(engine, 'gray'),
                       edgecolor='black', linewidth=0.5,
                       label=engine.upper() if ci == 0 else None)
                ax.plot(xpos, m.avg_travel_time, 'k_',
                        markersize=14, markeredgewidth=2)

        ax.set_title(f"{mode.title()}", fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities])
        ax.set_xlim(-0.5, len(cities) - 0.5)
        ax.set_ylim(bottom=0)
        ax.margins(y=0.15)
        ax.grid(axis='y', alpha=0.3)

        # De-dupe legend entries
        handles, labels_ = ax.get_legend_handles_labels()
        seen = {}
        for h, l in zip(handles, labels_):
            seen.setdefault(l, h)
        seen['Mean'] = plt.Line2D([0], [0], marker='_', color='black',
                                  markersize=12, linewidth=0)
        ax.legend(seen.values(), seen.keys(),
                  title='Engine', loc='upper right')

    axes[0].set_ylabel('Travel Time (seconds)', fontweight='bold')
    fig.suptitle('Figure 5.8: P95 Tail Latency vs Mean Travel Time\n'
                 '(bar = P95, dash = mean)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_8_p95_tail_latency", output_dir)


# ---------------------------------------------------------------------------
# Figure 5.9 — Trip-count parity (validates the SCC/feasibility filter)
# ---------------------------------------------------------------------------

def plot_trip_count_parity(metrics: list[ScenarioMetrics],
                           output_dir: Path) -> Optional[Path]:
    _require_matplotlib()
    setup_style()

    if not metrics:
        return None

    cities = sorted({m.city for m in metrics})
    modes = sorted({m.mode for m in metrics})

    fig, axes = plt.subplots(1, len(modes),
                             figsize=(6 * len(modes), 6), sharey=True)
    if len(modes) == 1:
        axes = [axes]

    for ax, mode in zip(axes, modes):
        engines = sorted({m.engine for m in metrics if m.mode == mode})
        bar_width = min(0.25, 0.8 / max(len(engines), 1))
        x_positions = list(range(len(cities)))

        per_city_max = {}
        for idx, engine in enumerate(engines):
            heights = []
            for city in cities:
                hit = [m for m in metrics
                       if m.city == city and m.engine == engine and m.mode == mode]
                v = hit[0].avg_trips if hit else 0
                heights.append(v)
                per_city_max[city] = max(per_city_max.get(city, 0), v)
            offset = (idx - (len(engines) - 1) / 2) * bar_width
            bars = ax.bar([x + offset for x in x_positions], heights,
                          bar_width,
                          color=ENGINE_COLORS.get(engine, 'gray'),
                          edgecolor='black', linewidth=0.5,
                          label=engine.upper())
            for bar, h in zip(bars, heights):
                if h > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, h,
                            f'{h}', ha='center', va='bottom', fontsize=8)

        ax.set_title(f"{mode.title()}", fontweight='bold')
        ax.set_xticks(x_positions)
        ax.set_xticklabels([_city_label(c) for c in cities])
        ax.set_xlim(-0.5, len(cities) - 0.5)
        ax.set_ylim(bottom=0)
        ax.margins(y=0.15)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(title='Engine', loc='lower right')

    axes[0].set_ylabel('Completed Trips (avg over repeats)',
                       fontweight='bold')
    fig.suptitle('Figure 5.9: Trip-Count Parity\n'
                 '(every engine should complete the same N — '
                 'shows the SCC / feasibility filter is working)',
                 fontweight='bold', y=1.02)
    plt.tight_layout()
    return _save("fig_5_9_trip_count_parity", output_dir)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def generate_all_plots(results_paths: list[Path],
                       output_dir: Path) -> dict:
    if not MATPLOTLIB_AVAILABLE:
        print("ERROR: matplotlib is required for plot generation")
        print("Install with: pip install matplotlib seaborn")
        return {"error": "matplotlib not installed"}

    output_dir.mkdir(parents=True, exist_ok=True)

    all_metrics: list[ScenarioMetrics] = []
    total_runs = 0
    successful_runs = 0

    for rp in results_paths:
        print(f"Loading results from: {rp}")
        data = load_results(rp)
        runs_in_file = data.get("results", data.get("runs", []))
        print(f"  Benchmark: "
              f"{data.get('runspec_name', data.get('timestamp', 'unknown'))}")
        print(f"  Runs: {data.get('total_runs', len(runs_in_file))} total, "
              f"{data.get('successful_runs', data.get('summary', {}).get('completed', '?'))} successful")
        total_runs += data.get('total_runs', len(runs_in_file))
        successful_runs += data.get('successful_runs',
                                    data.get('summary', {}).get('completed', 0))
        all_metrics.extend(analyze_results(data))

    # Dedup by (city, engine, mode); later entries win
    seen: dict[tuple[str, str, str], ScenarioMetrics] = {}
    for m in all_metrics:
        seen[(m.city, m.engine, m.mode)] = m
    metrics = list(seen.values())
    print(f"\nCombined: {total_runs} total runs, "
          f"{len(metrics)} unique (city, engine, mode) cells")

    generated: dict[str, str] = {}
    print("\nGenerating plots...")

    plot_specs = [
        ("Runtime comparison (Fig 5.1)", 'runtime',
         lambda: plot_runtime_comparison(metrics, output_dir)),
        ("Reproducibility heatmap (Fig 5.2)", 'reproducibility',
         lambda: plot_reproducibility_heatmap(metrics, output_dir)),
        ("Travel time comparison (Fig 5.3)", 'travel_time',
         lambda: plot_travel_time_comparison(metrics, output_dir)),
        ("Engine summary (Fig 5.4)", 'engine_summary',
         lambda: plot_engine_summary(metrics, output_dir)),
        ("Speedup analysis (Fig 5.5)", 'speedup',
         lambda: plot_speedup_analysis(metrics, output_dir)),
        ("Micro vs Meso (Fig 5.6)", 'micro_vs_meso',
         lambda: plot_micro_vs_meso(metrics, output_dir)),
        ("Runtime variability (Fig 5.7)", 'runtime_variability',
         lambda: plot_runtime_variability(results_paths, output_dir)),
        ("P95 tail latency (Fig 5.8)", 'p95_tail_latency',
         lambda: plot_p95_travel_time(metrics, output_dir)),
        ("Trip-count parity (Fig 5.9)", 'trip_count_parity',
         lambda: plot_trip_count_parity(metrics, output_dir)),
    ]
    for label, key, fn in plot_specs:
        print(f"  → {label}...")
        path = fn()
        if path:
            generated[key] = str(path)

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
        help="Output directory for plots (default: plots/ next to first results file)"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Delete existing plots in output directory before generating"
    )
    args = parser.parse_args()

    for rp in args.results:
        if not rp.exists():
            print(f"Error: Results file not found: {rp}")
            return 1

    output_dir = args.output or args.results[0].resolve().parent / "plots"

    if args.clean and output_dir.exists():
        old = list(output_dir.glob("*.png")) + list(output_dir.glob("*.pdf"))
        for p in old:
            p.unlink()
        if old:
            print(f"Cleaned {len(old)} existing plots from {output_dir}")

    generated = generate_all_plots(args.results, output_dir)
    if "error" in generated:
        return 1

    print("\nGenerated files:")
    for name, path in generated.items():
        print(f"  • {name}: {path}")
    return 0


if __name__ == "__main__":
    exit(main())
