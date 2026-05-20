"""Generate the 5 high-impact architecture/flow figures for the thesis.

These are NOT data plots (those live in evaluation/generate_plots.py).
These are box-and-arrow conceptual diagrams: SimForge overview, three-layer
architecture, fairness-audit flow, Phase 14 BFS deduplication, and the
two-paradigm-spread synthesis.

Output: doc/figures/fig_{1_1,3_1,3_6,3_8,6_1}_*.png (300 dpi PNG).

Layout discipline notes (rewrite 2026-05-20 after first-pass review):
- All container boxes use a clearly-positioned title ABOVE the content area,
  never overlapping inner boxes.
- Side annotations are placed in dedicated coordinate-space columns to avoid
  collision with the main flow.
- Coordinate space matches the figure aspect ratio (set_xlim / set_ylim
  proportional to figsize so 1 unit = same visual size in x and y).
- Box widths sized to fit the longest text line at the chosen font size,
  not arbitrarily.
- Vertical gaps between flow steps are explicit (no "almost touching").

Run:
    python -m tools.generate_architecture_figures
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


# -----------------------------------------------------------------------------
# Shared style
# -----------------------------------------------------------------------------

C_BUNDLE = "#e3f2fd"
C_ADAPTER = "#fff3e0"
C_EVAL = "#f1f8e9"
C_PIPELINE = "#fce4ec"
C_HIGHLIGHT = "#ffcdd2"
C_OK = "#c8e6c9"
C_INFO = "#bbdefb"
C_BORDER = "#37474f"
C_ARROW = "#455a64"
C_TEXT = "#212121"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial"],
    "axes.edgecolor": C_BORDER,
    "axes.labelcolor": C_TEXT,
    "text.color": C_TEXT,
})


def box(ax, x, y, w, h, text, *, color=C_BUNDLE, edgecolor=C_BORDER,
        fontsize=10, fontweight="normal", radius=0.05, va="center"):
    """Rounded rectangle with centered text. (x,y) = lower-left corner."""
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={radius}",
        facecolor=color, edgecolor=edgecolor, linewidth=1.2,
    )
    ax.add_patch(patch)
    if text:
        ty = y + h / 2 if va == "center" else (y + h - 0.15 if va == "top" else y + 0.15)
        ax.text(x + w / 2, ty, text,
                ha="center", va=va, fontsize=fontsize, fontweight=fontweight,
                color=C_TEXT)


def container(ax, x, y, w, h, title, *, color, fontsize=11):
    """Outer container with title printed inside, top-aligned."""
    box(ax, x, y, w, h, "", color=color)
    ax.text(x + w / 2, y + h - 0.30, title,
            ha="center", va="center", fontsize=fontsize, fontweight="bold",
            color=C_TEXT)


def arrow(ax, x1, y1, x2, y2, *, color=C_ARROW, lw=1.5, style="-|>", label=None,
          label_offset=(0, 0)):
    arr = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style, mutation_scale=15,
        color=color, linewidth=lw,
    )
    ax.add_patch(arr)
    if label:
        mx = (x1 + x2) / 2 + label_offset[0]
        my = (y1 + y2) / 2 + label_offset[1]
        ax.text(mx, my, label, ha="center", va="center", fontsize=8, color=color,
                bbox=dict(facecolor="white", edgecolor="none", pad=2))


def save(fig, name, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{name}.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.2, facecolor="white")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# F1 — SimForge at a glance
# -----------------------------------------------------------------------------


def fig_1_1_simforge_overview(output_dir):
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.suptitle("SimForge: a canonical-bundle → multi-adapter → fairness-audit framework",
                 fontsize=13, fontweight="bold", y=0.98)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.set_aspect("equal")
    ax.axis("off")

    # LEFT: Canonical bundle container + 5 file sub-boxes
    container(ax, 0.3, 0.5, 2.6, 6.0, "Canonical bundle\n(per scenario)",
              color=C_BUNDLE)
    sub_files = ["network.xml", "demand.csv", "signals.xml", "config.xml",
                 "manifest.xml +\nSHA-256"]
    for i, text in enumerate(sub_files):
        y = 4.5 - i * 0.85
        box(ax, 0.5, y, 2.2, 0.7, text, color="white", fontsize=8.5, radius=0.03)

    # SCC + feasibility filter annotation (between bundle and adapters)
    ax.text(3.7, 6.4, "shared SCC +\nfeasibility filter",
            ha="center", va="center", fontsize=8.5, fontweight="bold",
            color="#c62828",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=C_HIGHLIGHT,
                      edgecolor="#c62828", linewidth=1.0))

    # CENTER: three adapters
    adapter_x = 4.7
    adapter_w = 2.6
    adapters = [
        ("SUMO adapter\n(micro + meso)", 4.95, "C++ subprocess"),
        ("MATSim adapter\n(qsim, lastIter=0)", 3.10, "JVM subprocess"),
        ("DTALite adapter\n(UE DTA)", 1.25, "path4gmns wheel"),
    ]
    for label, y, sub in adapters:
        box(ax, adapter_x, y, adapter_w, 1.30, label,
            color=C_ADAPTER, fontsize=10.5, fontweight="bold")
        ax.text(adapter_x + adapter_w / 2, y - 0.20, sub,
                ha="center", va="center", fontsize=8, style="italic", color="#666")
        arrow(ax, 2.95, 3.5, adapter_x, y + 0.65)

    # RIGHT: outputs (sized to fit longest line)
    out_x = 8.0
    out_w = 3.0
    outputs = [
        ("tripinfo.xml\n+ feasibility_report.json", 4.95),
        ("output_trips.csv.gz\n+ feasibility_report.json", 3.10),
        ("agent.csv +\nlink_performance.csv\n+ feasibility_report.json", 1.10),
    ]
    for text, y in outputs:
        h = 1.6 if "\n+ " in text and text.count("\n") > 1 else 1.3
        box(ax, out_x, y, out_w, h, text, color="white", fontsize=8.5, radius=0.03)
        arrow(ax, adapter_x + adapter_w, y + 0.65, out_x, y + 0.65)

    # FAR-RIGHT: evaluation container + 4 items
    eval_x = 11.3
    eval_w = 2.5
    container(ax, eval_x, 0.5, eval_w, 6.0, "Evaluation layer", color=C_EVAL)
    eval_items = [
        ("audit_fairness\n(Q1-Q5)", 4.95),
        ("analyze_benchmark\n(Tables 5.1+5.2)", 3.65),
        ("generate_plots\n(Figs 5.1-5.10)", 2.35),
        ("reproducibility_\nscorecard", 1.05),
    ]
    for text, y in eval_items:
        box(ax, eval_x + 0.15, y, eval_w - 0.30, 0.95, text,
            color="white", fontsize=8.5, radius=0.03)
        arrow(ax, out_x + out_w + 0.05, 3.0, eval_x, y + 0.475, lw=0.6,
              color="#90a4ae")

    # Bottom caption
    ax.text(7.0, 0.05,
            "Three engines × identical canonical input + identical SCC/feasibility filter  →  "
            "fairness-attributable cross-engine differences",
            ha="center", va="bottom", fontsize=9, style="italic", color="#555")

    return save(fig, "fig_1_1_simforge_overview", output_dir)


# -----------------------------------------------------------------------------
# F2 — Three-layer architecture
# -----------------------------------------------------------------------------


def fig_3_1_three_layer_architecture(output_dir):
    fig, ax = plt.subplots(figsize=(14, 8.5))
    fig.suptitle("SimForge three-layer architecture: pipeline → adapters → evaluation",
                 fontsize=13, fontweight="bold", y=0.97)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # Layer geometry — non-overlapping, with explicit inter-layer gap for arrows
    LAYER_H = 2.2
    LAYER_GAP = 0.6
    layer_specs = [
        ("PIPELINE LAYER", "(canonical-bundle generation)", 6.5, C_PIPELINE,
         ["pipeline/network/\n(OSM → GMNS → SCC)",
          "pipeline/demand/\n(ModelGen + PUMS\n→ demand.csv)",
          "pipeline/signals/\n(OSM-grounded\nsignal placement)",
          "pipeline/validation/\n(validate_bundle)"]),
        ("ADAPTER LAYER", "(canonical → engine-native + run + parse)", 3.7, C_ADAPTER,
         ["adapters/common/\n(feasibility,\ncanonical_routes,\nvehicle_types)",
          "adapters/sumo/\n(prepare +\nrun + parse)",
          "adapters/matsim/\n(prepare +\nrun + parse)",
          "adapters/dtalite/\n(prepare +\nrun + parse)"]),
        ("EVALUATION LAYER", "(audit + metrics + scorecard)", 0.9, C_EVAL,
         ["evaluation/\naudit_fairness.py\n(Q1-Q5)",
          "evaluation/\nanalyze_benchmark.py\n(Tables 5.1+5.2)",
          "evaluation/metrics/\n(R, fidelity,\nscalability, CI)",
          "evaluation/\ngenerate_plots.py +\ngenerate_scorecard"]),
    ]

    # Reserve right column (x = 12.4 - 13.7) for inter-layer flow labels
    layer_left = 0.3
    layer_right = 12.1
    layer_w = layer_right - layer_left
    label_x = 12.95

    for title, sub, y_bottom, color, modules in layer_specs:
        # Layer container
        box(ax, layer_left, y_bottom, layer_w, LAYER_H, "", color=color)
        # Title row inside container, at top, with explicit breathing room
        ax.text(layer_left + 0.25, y_bottom + LAYER_H - 0.30, title,
                ha="left", va="center", fontsize=11, fontweight="bold",
                color="#37474f")
        ax.text(layer_left + 0.25 + 2.4, y_bottom + LAYER_H - 0.30, sub,
                ha="left", va="center", fontsize=9.5, style="italic",
                color="#555")
        # Module boxes — placed below the title row, with margins
        n = len(modules)
        module_top_y = y_bottom + LAYER_H - 0.65
        module_bottom_y = y_bottom + 0.15
        module_h = module_top_y - module_bottom_y
        slot_w = (layer_w - 0.5) / n
        for i, mod in enumerate(modules):
            mx = layer_left + 0.25 + i * slot_w
            box(ax, mx, module_bottom_y, slot_w - 0.15, module_h, mod,
                color="white", fontsize=8.5, radius=0.03)

    # Inter-layer arrows: cleanly inside the gap (no overlap with layers)
    # PIPELINE bottom = 6.5; ADAPTER top = 3.7 + 2.2 = 5.9; arrow 6.45 → 5.95
    arrow(ax, 6.0, 6.45, 6.0, 5.95, lw=2.2)
    # ADAPTER bottom = 3.7; EVALUATION top = 0.9 + 2.2 = 3.1; arrow 3.65 → 3.15
    arrow(ax, 6.0, 3.65, 6.0, 3.15, lw=2.2)

    # Flow labels in dedicated right column
    ax.text(label_x, 6.20, "canonical\nbundle\n(5 files)",
            ha="center", va="center", fontsize=8.5, style="italic", color="#555",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor="#999", linewidth=0.8))
    ax.text(label_x, 3.40, "per-engine\noutputs +\nfeasibility report",
            ha="center", va="center", fontsize=8.5, style="italic", color="#555",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor="#999", linewidth=0.8))

    # Bottom caption
    ax.text(7.0, 0.30,
            "Each layer is independently testable. The adapter layer is the substitution point "
            "for new engines (prepare/run/parse contract; see §3.4).",
            ha="center", va="center", fontsize=9, style="italic", color="#555")

    return save(fig, "fig_3_1_three_layer_architecture", output_dir)


# -----------------------------------------------------------------------------
# F6 — Fairness audit Q1-Q5 flow
# -----------------------------------------------------------------------------


def fig_3_6_fairness_audit_flow(output_dir):
    fig, ax = plt.subplots(figsize=(10, 11))
    fig.suptitle("Cross-engine fairness audit: Q1-Q5 verification flow",
                 fontsize=13, fontweight="bold", y=0.985)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 11)
    ax.axis("off")

    # Top: input box
    box(ax, 2.0, 10.0, 6.0, 0.85,
        "Run directory  <runs/.../scenario/engine/mode/seed_N/>",
        color="white", fontsize=10, fontweight="bold")

    # Q1-Q5 stacked
    q_specs = [
        ("Q1 — Byte-identical feasibility verdict?",
         "Compare feasibility_report.json across all engines\n"
         "→ feasible_trip_ids set must be byte-equal",
         8.5, C_OK, "MANDATORY", "#388e3c"),
        ("Q2 — Byte-identical SCC network?",
         "Compare adapter-emitted network node + link counts\n"
         "→ SCC sizes must match",
         7.1, C_OK, "MANDATORY", "#388e3c"),
        ("Q3 — Identical simulated-trip count target?",
         "Count completed trips in each engine output\n"
         "→ all engines target the same |feasible|",
         5.7, C_OK, "MANDATORY", "#388e3c"),
        ("Q4 — Cross-engine mean travel-time spread",
         "Compute per-engine mean TT + report spread\n"
         "→ INTERPRETIVE: paradigm-divergence signal",
         4.3, C_INFO, "INFORMATIONAL", "#1976d2"),
        ("Q5 — Demand composition (V5+)",
         "Tally trip purposes from demand.csv\n"
         "→ INFORMATIONAL: HBW + HBSchool breakdown",
         2.9, C_INFO, "INFORMATIONAL", "#1976d2"),
    ]

    arrow_y_pairs = []
    prev_bottom = 10.0  # bottom of Run-directory box

    for title, body, y, color, badge, badge_color in q_specs:
        h = 1.10
        top_y = y + h / 2
        bottom_y = y - h / 2
        # Arrow from previous to top of this step
        arrow_y_pairs.append((prev_bottom, top_y))
        prev_bottom = bottom_y

        box(ax, 0.5, bottom_y, 9.0, h, "", color=color)
        ax.text(0.8, y + 0.30, title,
                ha="left", va="center", fontsize=10.5, fontweight="bold",
                color="#1b5e20" if color == C_OK else "#0d47a1")
        ax.text(0.8, y - 0.18, body,
                ha="left", va="center", fontsize=8.5, color="#333")
        # Badge on top-right
        ax.text(8.7, y + 0.30, badge,
                ha="right", va="center", fontsize=7.5, fontweight="bold",
                color="white",
                bbox=dict(boxstyle="round,pad=0.3", facecolor=badge_color,
                          edgecolor=badge_color))

    # Bottom: output (with explicit gap above)
    output_top_y = 1.0
    output_bottom_y = 0.2
    box(ax, 2.0, output_bottom_y, 6.0, 0.85,
        "→ PASS / FAIL verdict  +  scorecard row",
        color="white", fontsize=10, fontweight="bold")
    arrow_y_pairs.append((prev_bottom, output_top_y))

    # Draw all arrows
    for y_src, y_dst in arrow_y_pairs:
        arrow(ax, 5.0, y_src, 5.0, y_dst, lw=2.0)

    return save(fig, "fig_3_6_fairness_audit_flow", output_dir)


# -----------------------------------------------------------------------------
# F7 — Phase 14 BFS deduplication
# -----------------------------------------------------------------------------


def fig_3_8_phase14_bfs_dedup(output_dir):
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5))
    fig.suptitle("Phase 14 canonical_routes BFS deduplication  "
                 "(chicago_200k_car: 141.87 h → 7.14 h cold-vs-cold, ~20×)",
                 fontsize=12, fontweight="bold", y=0.97)

    for ax in axes:
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 7)
        ax.set_aspect("equal")
        ax.axis("off")

    # --- BEFORE (left) ---
    ax = axes[0]
    ax.text(5.0, 6.55, "BEFORE Phase 14  (Phase 12 / 13)",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color="#c62828")

    box(ax, 0.3, 4.4, 1.8, 1.3, "Canonical\nbundle",
        color=C_BUNDLE, fontsize=10, fontweight="bold")

    # Two adapter rows with own BFS
    box(ax, 2.6, 4.4, 7.0, 1.3,
        "SUMO adapter\n200K trips × BFS @ 1.5 s/trip  ≈  82 h",
        color=C_ADAPTER, fontsize=9.5)
    box(ax, 2.6, 2.6, 7.0, 1.3,
        "MATSim adapter\n200K trips × BFS @ 1.5 s/trip  ≈  82 h",
        color=C_ADAPTER, fontsize=9.5)

    arrow(ax, 2.15, 5.4, 2.6, 5.05, lw=1.5)
    arrow(ax, 2.15, 4.8, 2.6, 3.25, lw=1.5)

    box(ax, 1.0, 0.6, 8.0, 1.4, "", color=C_HIGHLIGHT)
    ax.text(5.0, 1.30,
            "→ Total ~164 h adapter-prep wall  (96 % of run time)\n"
            "    nyc_500k_car structurally infeasible (~600 h projected)",
            ha="center", va="center", fontsize=9.5, fontweight="bold",
            color="#c62828")

    # --- AFTER (right) ---
    ax = axes[1]
    ax.text(5.0, 6.55, "AFTER Phase 14  (canonical_routes shared BFS)",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color="#1b5e20")

    box(ax, 0.3, 4.4, 1.8, 1.3, "Canonical\nbundle",
        color=C_BUNDLE, fontsize=10, fontweight="bold")

    # Shared compute box (wider to fit text)
    box(ax, 2.6, 4.4, 4.4, 1.3,
        "canonical_routes.\ncompute_canonical_routes()\nparallel BFS, 16 workers",
        color=C_HIGHLIGHT, fontsize=9.5, fontweight="bold")

    # Cache box below
    box(ax, 2.6, 2.7, 4.4, 1.0,
        "cache/canonical_routes/\n<hash>.jsonl  (Phase 14.13 global cache)",
        color="white", fontsize=8.5)

    # Two adapters consuming the shared dict
    box(ax, 7.4, 5.05, 2.2, 0.7, "SUMO adapter",
        color=C_ADAPTER, fontsize=9.5, fontweight="bold")
    box(ax, 7.4, 4.20, 2.2, 0.7, "MATSim adapter",
        color=C_ADAPTER, fontsize=9.5, fontweight="bold")

    arrow(ax, 2.15, 5.05, 2.6, 5.05, lw=1.5)
    arrow(ax, 7.0, 5.30, 7.4, 5.40, lw=1.2, label="dict")
    arrow(ax, 7.0, 4.80, 7.4, 4.55, lw=1.2, label="dict")
    arrow(ax, 4.8, 4.4, 4.8, 3.7, lw=1.0, color="#888")

    box(ax, 1.0, 0.6, 8.0, 1.4, "", color=C_OK)
    ax.text(5.0, 1.30,
            "→ Total ~7.14 h adapter-prep wall (cold)   ~37 min (warm-cache re-run, 228×)\n"
            "    nyc_500k_car feasible: 12 h 8 min on Cardinal",
            ha="center", va="center", fontsize=9.5, fontweight="bold",
            color="#1b5e20")

    plt.tight_layout(rect=(0, 0, 1, 0.94))
    out = output_dir / "fig_3_8_phase14_bfs_dedup.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.2, facecolor="white")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# F9 — Two paradigm-spread phenomena
# -----------------------------------------------------------------------------


def fig_6_1_paradigm_spread(output_dir):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Two paradigm-spread phenomena from the same insertion-refusal vs queue-hold mechanism at network saturation",
                 fontsize=11.5, fontweight="bold", y=0.97)

    # --- LEFT: cross-engine ---
    ax = axes[0]
    tiers = ["chicago\n1K", "nyc\n10K", "la\n50K", "chicago\n200K", "nyc\n500K"]
    ratios = [0.869, 0.945, 1.046, 0.645, 0.037]
    colors = ["#2196f3"] * 3 + ["#f44336"] * 2

    bars = ax.bar(range(len(tiers)), ratios, color=colors, edgecolor=C_BORDER,
                  linewidth=1.0, width=0.7)
    ax.set_xticks(range(len(tiers)))
    ax.set_xticklabels(tiers, fontsize=9)
    ax.set_ylabel("SUMO meso / MATSim meso  mean-TT ratio", fontsize=10)
    ax.set_title("§6.2.2 — Cross-engine paradigm spread\n"
                 "(SUMO insertion-refusal ↔ MATSim queue-hold)",
                 fontsize=11, fontweight="bold", pad=10)
    ax.axhline(y=1.0, color="#999", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_ylim(0, 1.55)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5])
    # "parity" label placed where there's empty space (above 50K bar, before
    # the dashed line so it doesn't collide with bar value labels)
    ax.text(0.05, 1.04, "parity (ratio = 1.0)", fontsize=8, color="#666",
            ha="left", va="bottom")
    for bar, ratio in zip(bars, ratios):
        offset = 0.04 if ratio > 0.05 else 0.04
        ax.text(bar.get_x() + bar.get_width() / 2, ratio + offset,
                f"{ratio:.3f}", ha="center", va="bottom", fontsize=8.5,
                fontweight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Annotation arrow — tip lands inside the chicago_200k bar body
    # (well below its 0.645 value label) for visual clarity
    ax.annotate("", xy=(3, 0.35), xytext=(3.5, 1.30),
                arrowprops=dict(arrowstyle="->", color="#c62828", lw=1.5))
    ax.text(3.5, 1.38, "saturation\nparadigm divergence",
            ha="center", va="bottom", fontsize=9, color="#c62828",
            fontweight="bold")

    # --- RIGHT: within-engine ---
    ax = axes[1]
    tiers2 = ["chicago\n1K", "nyc\n10K", "chicago\n200K"]
    ratios2 = [1.272, 1.729, 1.078]
    deltas = ["+27.2 %", "+72.9 %", "+7.8 %"]
    colors2 = ["#ff9800", "#ff5722", "#4caf50"]

    bars = ax.bar(range(len(tiers2)), ratios2, color=colors2, edgecolor=C_BORDER,
                  linewidth=1.0, width=0.6)
    ax.set_xticks(range(len(tiers2)))
    ax.set_xticklabels(tiers2, fontsize=9)
    ax.set_ylabel("SUMO micro / SUMO meso  mean-TT ratio", fontsize=10)
    ax.set_title("§6.2.4 — Within-engine paradigm spread\n"
                 "(SUMO micro ↔ SUMO meso mobsim resolution)",
                 fontsize=11, fontweight="bold", pad=10)
    ax.axhline(y=1.0, color="#999", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_ylim(0, 2.3)
    # "parity" label placed at left edge to avoid bar value-label collisions
    ax.text(-0.45, 1.02, "parity (no gap)", fontsize=8, color="#666",
            ha="left", va="bottom")
    for bar, ratio, d in zip(bars, ratios2, deltas):
        ax.text(bar.get_x() + bar.get_width() / 2, ratio + 0.05,
                f"{ratio:.3f}  ({d})", ha="center", va="bottom", fontsize=8.5,
                fontweight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Annotation arrow — tip lands inside the chicago_200k bar body
    # (well below its 1.078 value label) for visual clarity
    ax.annotate("", xy=(2, 0.55), xytext=(1.25, 2.00),
                arrowprops=dict(arrowstyle="->", color="#1b5e20", lw=1.5))
    ax.text(1.25, 2.08, "saturation\nresolution convergence",
            ha="center", va="bottom", fontsize=9, color="#1b5e20",
            fontweight="bold")

    plt.tight_layout(rect=(0, 0.05, 1, 0.92))

    fig.text(0.5, 0.015,
             "Both findings emerge from the same controlling mechanism: at saturation density, "
             "origin-edge insertion-refusal dominates the dynamics for both mobsim paradigms (SUMO) and both resolutions (micro/meso).",
             ha="center", va="bottom", fontsize=9, style="italic", color="#555")

    out = output_dir / "fig_6_1_paradigm_spread.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.2, facecolor="white")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# F3 — Canonical 5-file bundle schema (Methods §3.2)
# -----------------------------------------------------------------------------


def fig_3_2_canonical_bundle_schema(output_dir):
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.suptitle("Canonical scenario bundle: 5-file simulator-agnostic schema",
                 fontsize=13, fontweight="bold", y=0.97)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis("off")

    # Five file boxes laid out in a row across the top
    file_specs = [
        ("network.xml", "XML", [
            "<node id='n0' x=… y=…/>",
            "<link from='n0' to='n1'",
            "      length= speed= lanes=/>",
            "<turn_restriction …/>",
        ]),
        ("demand.csv", "CSV", [
            "trip_id, origin_node_id,",
            "  destination_node_id,",
            "  departure_time_s,",
            "  mode, purpose (V5+)",
        ]),
        ("signals.xml", "XML", [
            "<junction id='n0'>",
            "  <phase duration='30'",
            "         state='Gr'/>",
            "  <phase …/>  …",
        ]),
        ("config.xml", "XML", [
            "<horizon start='25200'",
            "         end='36000'/>",
            "<seed value='42'/>",
            "<units length='m' speed='m/s'/>",
        ]),
        ("manifest.xml", "XML", [
            "<file path='network.xml'",
            "  sha256='abc…' size=… />",
            "<file path='demand.csv'",
            "  sha256='def…' …/>  …",
        ]),
    ]

    bx, by, bw, bh = 0.3, 3.3, 2.65, 3.3
    gap = 0.10
    for i, (name, ftype, lines) in enumerate(file_specs):
        x = bx + i * (bw + gap)
        # File-name header
        box(ax, x, by + bh - 0.7, bw, 0.6, "",
            color=C_BUNDLE, edgecolor=C_BORDER)
        ax.text(x + bw / 2, by + bh - 0.4, name,
                ha="center", va="center", fontsize=11, fontweight="bold",
                color=C_TEXT)
        ax.text(x + bw - 0.15, by + bh - 0.65, ftype,
                ha="right", va="bottom", fontsize=7.5, style="italic",
                color="#666")
        # Content area (white)
        box(ax, x, by, bw, bh - 0.7, "", color="white")
        for j, line in enumerate(lines):
            ax.text(x + 0.13, by + bh - 1.05 - j * 0.45, line,
                    ha="left", va="top", fontsize=8, family="monospace",
                    color="#333")

    # Caption box at top noting the manifest verification.
    # (We don't draw per-file SHA-256 arrows here — they all originate at the
    # manifest.xml column and target the other 4 headers at the same y, which
    # renders as a single overlapping horizontal line rather than 4 distinct
    # arrows. The textual caption + the per-file `<file path=... sha256=...>`
    # entries shown inside manifest.xml's content box convey the same point
    # without the visual confusion.)
    ax.text(7.0, 6.75,
            "manifest.xml hash-verifies the other 4 files (SHA-256) at validate_bundle time — "
            "see the <file path=... sha256=.../> entries inside manifest.xml above.",
            ha="center", va="center", fontsize=9.5, color="#c62828",
            style="italic",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#c62828", linewidth=0.8))

    # Bottom: bundle ID + downstream consumer
    box(ax, 2.0, 1.30, 10.0, 1.30, "",
        color=C_BUNDLE, edgecolor=C_BORDER)
    ax.text(7.0, 2.30,
            "scenarios/<scenario_id>/  (e.g. chicago_1k_car, nyc_500k_car)",
            ha="center", va="center", fontsize=11, fontweight="bold",
            color=C_TEXT)
    ax.text(7.0, 1.65,
            "Consumed by every adapter (SUMO / MATSim / DTALite) → fairness contract requires byte-identical input",
            ha="center", va="center", fontsize=9, style="italic", color="#555")

    # Arrow from the file row down to the bundle box
    arrow(ax, 7.0, 3.2, 7.0, 2.65, lw=2.0)

    # Bottom caption
    ax.text(7.0, 0.35,
            "Field-level validation in pipeline/validation/validate_bundle.py; "
            "see Chapter 3 §3.2 for full schema.",
            ha="center", va="center", fontsize=9, style="italic", color="#555")

    return save(fig, "fig_3_2_canonical_bundle_schema", output_dir)


# -----------------------------------------------------------------------------
# F4 — Scenario generation pipeline (Methods §3.3)
# -----------------------------------------------------------------------------


def fig_3_3_generation_pipeline(output_dir):
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.suptitle("Scenario generation pipeline: data sources → SimForge transforms → canonical bundle",
                 fontsize=12.5, fontweight="bold", y=0.97)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # LEFT column: data sources
    container(ax, 0.3, 0.7, 3.0, 6.5, "Data sources", color="#eceff1")
    sources = [
        ("OSM PBF\n(Geofabrik state extracts)", 6.3),
        ("LandScan rasters\n(ORNL pop. density)", 5.2),
        ("ACS PUMS 5-yr\n(US Census Bureau)", 4.1),
        ("IPUMS PUMA\nshapefiles", 3.0),
        ("ModelGen .txt\n(cityscape; Rao 2023)", 1.6),
    ]
    for label, y in sources:
        box(ax, 0.5, y - 0.40, 2.6, 0.80, label,
            color="white", fontsize=8.5, radius=0.03)

    # CENTER column: pipeline stages
    container(ax, 4.0, 0.7, 5.8, 6.5, "Pipeline stages", color=C_PIPELINE)
    stages = [
        ("pipeline/network/load_network_from_pbf.py\n(pyosmium bbox slice)", 6.4),
        ("pipeline/network/build_network_from_osm.py\n(osmnx → GMNS graph)", 5.4),
        ("pipeline/network/scc.py\n(Kosaraju largest-SCC filter)", 4.4),
        ("pipeline/signals/build_signals_default.py\n(OSM has_signal='true' → phase tables)", 3.4),
        ("pipeline/demand/parse_model_file.py\n(cityscape → buildings + persons + schedules)", 2.4),
        ("pipeline/demand/generate_census_demand.py\n(schedule-first + gravity fallback)", 1.3),
    ]
    for label, y in stages:
        box(ax, 4.2, y - 0.42, 5.4, 0.85, label,
            color="white", fontsize=8.5, radius=0.03)

    # Inter-stage arrows in CENTER (vertical flow downward)
    for y1, y2 in [(6.0, 5.85), (5.0, 4.85), (4.0, 3.85), (3.0, 2.85), (2.0, 1.75)]:
        arrow(ax, 7.0, y1, 7.0, y2, lw=1.2, color="#999")

    # RIGHT column: canonical bundle output
    container(ax, 10.5, 0.7, 3.3, 6.5, "Canonical bundle\n(5 files)", color=C_BUNDLE)
    outs = [
        ("network.xml", 6.0),
        ("demand.csv", 4.6),
        ("signals.xml", 3.3),
        ("config.xml", 2.0),
        ("manifest.xml +\nSHA-256", 0.85),
    ]
    for name, y in outs:
        box(ax, 10.7, y - 0.30, 2.9, 0.60, name,
            color="white", fontsize=9, radius=0.03)

    # Arrows from data sources to relevant pipeline stages
    arrow(ax, 3.10, 6.3, 4.20, 6.4, lw=0.8, color="#888")  # OSM PBF → load_network
    arrow(ax, 3.10, 5.2, 4.20, 2.4, lw=0.6, color="#888")  # LandScan → parse_model
    arrow(ax, 3.10, 4.1, 4.20, 2.4, lw=0.6, color="#888")  # ACS PUMS → parse_model
    arrow(ax, 3.10, 3.0, 4.20, 2.4, lw=0.6, color="#888")  # IPUMS PUMA → parse_model
    arrow(ax, 3.10, 1.6, 4.20, 2.4, lw=0.8, color="#888")  # ModelGen → parse_model

    # Arrows from pipeline stages to output files
    arrow(ax, 9.6, 4.4, 10.7, 6.0, lw=0.8, color="#1976d2")  # SCC + network → network.xml
    arrow(ax, 9.6, 1.3, 10.7, 4.6, lw=0.8, color="#1976d2")  # demand gen → demand.csv
    arrow(ax, 9.6, 3.4, 10.7, 3.3, lw=0.8, color="#1976d2")  # signals → signals.xml

    return save(fig, "fig_3_3_generation_pipeline", output_dir)


# -----------------------------------------------------------------------------
# F5 — Adapter contract (3 engines × 3 functions)  (Methods §3.4)
# -----------------------------------------------------------------------------


def fig_3_4_adapter_contract(output_dir):
    fig, ax = plt.subplots(figsize=(15, 7))
    fig.suptitle("Three-function adapter contract: uniform prepare / run / parse across all engines",
                 fontsize=12.5, fontweight="bold", y=0.97)
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 7)
    ax.axis("off")

    engines = ["SUMO", "MATSim", "DTALite"]
    # Shorter descriptions designed to fit a 4.2-wide label column
    functions = [
        ("prepare_<engine>_inputs",
         "Read canonical bundle →\n"
         "emit engine-native inputs\n"
         "(SCC + feasibility filter applied)",
         "→ ScenarioSummary | Path"),
        ("run_<engine>",
         "Subprocess-invoke the engine\n"
         "binary or JVM",
         "→ Tuple[bool, float, Optional[str]]"),
        ("parse_<engine>_output",
         "Read engine-native output\n"
         "→ shared travel-time stats",
         "→ dict (SUMO + MATSim) | DTALiteTripStats"),
    ]

    # Layout: label column (4.2 wide) + 3 engine columns (3.3 each, gap 0.20)
    label_x, label_w = 0.3, 4.2
    header_x = 4.7
    header_w = 3.3
    gap = 0.20

    # Header row (engine names)
    for i, eng in enumerate(engines):
        x = header_x + i * (header_w + gap)
        box(ax, x, 5.5, header_w, 0.7,
            f"adapters/{eng.lower()}/", color=C_ADAPTER,
            fontsize=11, fontweight="bold")

    # Function rows
    row_specs = [
        (functions[0], 4.2),
        (functions[1], 2.6),
        (functions[2], 1.0),
    ]
    for (fn_name, fn_desc, return_type), y in row_specs:
        # Left label column (wider)
        box(ax, label_x, y, label_w, 1.3, "", color=C_PIPELINE)
        ax.text(label_x + 0.20, y + 1.05, fn_name,
                ha="left", va="center", fontsize=10, fontweight="bold",
                color="#37474f")
        ax.text(label_x + 0.20, y + 0.55, fn_desc,
                ha="left", va="center", fontsize=8.5, color="#333")
        ax.text(label_x + 0.20, y + 0.13, return_type,
                ha="left", va="center", fontsize=8, style="italic",
                color="#1976d2")
        # 3 engine columns
        for i, eng in enumerate(engines):
            x = header_x + i * (header_w + gap)
            box(ax, x, y, header_w, 1.3, "", color="white")
            sig = fn_name.replace("<engine>", eng.lower())
            ax.text(x + header_w / 2, y + 0.65, f"{sig}(...)",
                    ha="center", va="center", fontsize=9, family="monospace",
                    color="#333")

    # Footer note
    ax.text(7.5, 0.30,
            "Pinned by tests/test_adapter_contract.py (6 tests, 3 engines × 2 assertions). "
            "Adding a 4th engine follows the same three-function template.",
            ha="center", va="center", fontsize=9, style="italic", color="#555")

    return save(fig, "fig_3_4_adapter_contract", output_dir)


# -----------------------------------------------------------------------------
# F8 — Wave 2 container distribution chain (Methods §3.11)
# -----------------------------------------------------------------------------


def fig_3_11_container_chain(output_dir):
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.suptitle("Wave 2 pinned-digest container distribution chain: "
                 "Dockerfile → GHA → GHCR → Apptainer → SBATCH",
                 fontsize=12.5, fontweight="bold", y=0.97)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # Five horizontal stages
    stages = [
        ("Dockerfile\n(repo root)",
         "python:3.13-slim-bookworm\n+ openjdk-17 + libgomp1\n+ uv → 35 lockfile pkgs\n+ eclipse-sumo==1.26.0\n+ MATSim 15.0 JAR",
         "#fce4ec"),
        ("GitHub Actions\n(build-container.yml)",
         "On push to main or\nphase-14-canonical-routes\n→ docker build\n→ tag with git SHA",
         "#fff3e0"),
        ("GHCR\n(container registry)",
         "ghcr.io/phanidharakula/\nsimforge:db8d786\n(immutable digest)\nlib/container/manifest.json",
         "#e3f2fd"),
        ("Apptainer pull\n(on Cardinal)",
         "apptainer pull \\\n  simforge_db8d786.sif \\\n  docker://...:db8d786\n(SHA-tag workaround for\n1.4.5 progress bar bug)",
         "#f1f8e9"),
        ("SBATCH wrapper\n(opt-in)",
         "SIMFORGE_USE_CONTAINER=1 \\\nsbatch cluster/jobs/\n  benchmark_large.sbatch\n→ bit-identical x86_64\n  reproduction",
         "#c8e6c9"),
    ]

    box_w = 2.55
    gap = 0.18
    start_x = 0.2
    for i, (title, body, color) in enumerate(stages):
        x = start_x + i * (box_w + gap)
        # Outer container
        box(ax, x, 1.0, box_w, 4.0, "", color=color)
        # Title bar at top
        ax.text(x + box_w / 2, 4.55, title,
                ha="center", va="center", fontsize=10, fontweight="bold",
                color=C_TEXT)
        # Body (white sub-box)
        box(ax, x + 0.15, 1.20, box_w - 0.30, 2.95, "",
            color="white", radius=0.03)
        ax.text(x + box_w / 2, 2.65, body,
                ha="center", va="center", fontsize=8.5, family="monospace",
                color="#333")
        # Arrow to next stage
        if i < len(stages) - 1:
            arrow(ax,
                  x + box_w + 0.02, 2.9,
                  x + box_w + gap - 0.02, 2.9,
                  lw=1.8)

    # Top labels for the stage chain
    ax.text(7.0, 5.55,
            "Source-of-truth (Dockerfile + GHA) → Distribution (GHCR digest) → Consumption (Apptainer + SBATCH)",
            ha="center", va="center", fontsize=9.5, color="#555", style="italic")

    # Bottom note
    ax.text(7.0, 0.45,
            "Thesis-canonical image pinned at lib/container/manifest.json (db8d786, 2026-05-19, verified Cardinal). "
            "See Chapter 3 §3.11 + doc/CONTAINER_USAGE.md.",
            ha="center", va="center", fontsize=9, style="italic", color="#555")

    return save(fig, "fig_3_11_container_chain", output_dir)


# -----------------------------------------------------------------------------
# F10 — Four reproducibility regimes (Discussion §6.2.3)
# -----------------------------------------------------------------------------


def fig_6_2_reproducibility_regimes(output_dir):
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.suptitle("Four reproducibility regimes: cross-platform variability at fixed code is small; "
                 "cross-code-version variability is the dominant risk",
                 fontsize=12, fontweight="bold", y=0.97)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # 4 horizontal rows, each a regime
    regimes = [
        ("REGIME 1", "Within single execution context",
         "Re-runs on same machine, same git SHA, same fixed seed",
         "R = 1.0000  (MATSim + DTALite; SUMO R ≥ 0.95 due to Krauss-σ)",
         "BIT-IDENTICAL", C_OK, "#1b5e20", 6.4),
        ("REGIME 2", "Same CPU architecture, cross-distribution",
         "Cardinal RHEL host venv (Adoptium OpenJDK 21) ↔\n"
         "Cardinal Debian container (apt OpenJDK 17)",
         "20/20 cells byte-identical at chicago_200k + nyc_500k (§5.6.3.1)",
         "BIT-IDENTICAL", C_OK, "#1b5e20", 4.7),
        ("REGIME 3", "Cross-CPU-architecture",
         "Mac arm64 (Apple OpenJDK 17) ↔ Cardinal Sapphire Rapids x86_64",
         "MATSim 318.774 ↔ 318.77 s   |   DTALite 172.5605 ↔ 172.56 s\n"
         "(matches to 4 sig figs; consistent with bit-identity, §5.6.3.2)",
         "≈ BIT-IDENTICAL", C_INFO, "#0d47a1", 3.0),
        ("REGIME 4", "Cross-code-version (time-separated)",
         "Pitzer Phase 12 (2026-05-02) ↔ Cardinal Phase 14.13 (2026-05-20)\n"
         "Phase 14 canonical_routes BFS replaces legacy per-adapter BFS",
         "MATSim 2.95 % shift   |   DTALite 0.24 % shift   "
         "(§5.6.3 original measurement, reinterpreted in §5.6.3.3)",
         "0.2-3 % DRIFT", C_HIGHLIGHT, "#c62828", 1.3),
    ]

    for regime_id, name, what_varies, result, verdict, color, badge_color, y in regimes:
        # Container
        box(ax, 0.3, y, 13.4, 1.45, "", color=color)
        # Regime ID badge (left)
        ax.text(0.7, y + 0.72, regime_id,
                ha="left", va="center", fontsize=10, fontweight="bold",
                color=badge_color,
                bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                          edgecolor=badge_color, linewidth=1.0))
        # Title
        ax.text(2.4, y + 1.15, name,
                ha="left", va="center", fontsize=11, fontweight="bold",
                color=C_TEXT)
        # What varies (sub-line)
        ax.text(2.4, y + 0.78, what_varies,
                ha="left", va="center", fontsize=9, style="italic", color="#555")
        # Empirical result
        ax.text(2.4, y + 0.32, result,
                ha="left", va="center", fontsize=8.5, color="#333")
        # Verdict badge (right)
        ax.text(12.8, y + 0.72, verdict,
                ha="right", va="center", fontsize=10, fontweight="bold",
                color="white",
                bbox=dict(boxstyle="round,pad=0.4", facecolor=badge_color,
                          edgecolor=badge_color))

    # Bottom synthesis
    ax.text(7.0, 0.30,
            "Practical implication: cite the container digest (pins code+bundle+toolchain), not the version number. "
            "Cross-platform variability at fixed code is small; cross-code-version drift on the same platform is the real risk.",
            ha="center", va="center", fontsize=9.5, style="italic", color="#555")

    return save(fig, "fig_6_2_reproducibility_regimes", output_dir)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main():
    output_dir = Path(__file__).resolve().parents[1] / "doc" / "figures"
    print(f"Output dir: {output_dir}\n")
    fns = [
        ("F1 SimForge at a glance", fig_1_1_simforge_overview),
        ("F2 Three-layer architecture", fig_3_1_three_layer_architecture),
        ("F3 Canonical 5-file bundle schema", fig_3_2_canonical_bundle_schema),
        ("F4 Scenario generation pipeline", fig_3_3_generation_pipeline),
        ("F5 Adapter contract (3 × 3)", fig_3_4_adapter_contract),
        ("F6 Fairness audit Q1-Q5 flow", fig_3_6_fairness_audit_flow),
        ("F7 Phase 14 BFS dedup", fig_3_8_phase14_bfs_dedup),
        ("F8 Wave 2 container chain", fig_3_11_container_chain),
        ("F9 Two paradigm spread phenomena", fig_6_1_paradigm_spread),
        ("F10 Four reproducibility regimes", fig_6_2_reproducibility_regimes),
    ]
    for label, fn in fns:
        out = fn(output_dir)
        size_kb = out.stat().st_size // 1024
        print(f"  ✓ {label:40} → {out.name} ({size_kb} KB)")
    print(f"\nGenerated {len(fns)} architecture/flow figures at 300 dpi PNG.")


if __name__ == "__main__":
    main()
