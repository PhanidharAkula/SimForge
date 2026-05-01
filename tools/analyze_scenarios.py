#!/usr/bin/env python3
"""SimForge Scenario Analyzer.

End-to-end analysis of one or more canonical scenario bundles in
`scenarios/`. All output is tabular — every section is one table with
metrics as rows and scenarios as columns. When only one scenario is
analysed the tables degenerate to a single data column. When more
scenarios than the terminal can hold, each section auto-paginates
into multiple pages with a `(scenarios X–Y of N)` suffix.

Tables emitted (in order):

  1. CONFIGURATION   city, trips, modes, time window, radius, seed,
                     strategy, generation time, OSM source
  2. NETWORK         nodes, links, has_signal nodes, turn restrictions,
                     speed range/mean, lane range/mean
  3. ROAD CLASSES    per-OSM-highway-type link counts, top 12 + (other)
  4. SIGNALS         junction count, cycle, phase pattern, density
  5. DEMAND          totals (mode mix, schedule vs gravity, departure
                     window) + Trip-purpose breakdown subsection +
                     Peak split & chain summary subsection
  6. ARTEFACTS       per-file sizes + total
  7. TOOLCHAIN       env recorded at generation time

Default: every complete bundle in `scenarios/`. Pass scenario names
(without the `scenarios/` prefix) or full paths to analyse a subset.

Usage:
  python tools/analyze_scenarios.py                    # all bundles
  python tools/analyze_scenarios.py chicago_1k_car
  python tools/analyze_scenarios.py chicago_1k_car nyc_10k_car
  python tools/analyze_scenarios.py --section network  # one section only
  python tools/analyze_scenarios.py --section demand --section road_classes
  python tools/analyze_scenarios.py --no-color         # plain ASCII

Pagination is automatic: when the terminal isn't wide enough, each
section splits into pages of N scenarios with a `(scenarios X–Y of N)`
suffix on the title.

Standard library only — no new dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.demand_composition import read_demand_composition  # noqa: E402

# ANSI colour codes — disabled when not a TTY or --no-color is passed.
_USE_COLOR = sys.stdout.isatty()
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"
_RED = "\033[31m"

REQUIRED_BUNDLE_FILES = (
    "manifest.xml", "network.xml", "demand.csv",
    "config.xml", "signals.xml",
)


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------


@dataclass
class ScenarioReport:
    path: Path
    name: str
    config: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    demand: dict = field(default_factory=dict)
    artefact_sizes: dict[str, int] = field(default_factory=dict)


def _is_complete_bundle(path: Path) -> bool:
    return path.is_dir() and all(
        (path / f).is_file() for f in REQUIRED_BUNDLE_FILES
    )


def _discover_all() -> list[Path]:
    scenarios_dir = REPO_ROOT / "scenarios"
    if not scenarios_dir.is_dir():
        return []
    return sorted(p for p in scenarios_dir.iterdir() if _is_complete_bundle(p))


def _resolve(args: list[str]) -> list[Path]:
    if not args:
        return _discover_all()
    out: list[Path] = []
    for raw in args:
        p = Path(raw)
        if not p.is_absolute() and not (p.exists() and p.is_dir()):
            p = REPO_ROOT / "scenarios" / raw
        if not _is_complete_bundle(p):
            print(f"  ⚠  skipping {raw}: not a complete bundle at {p}",
                  file=sys.stderr)
            continue
        out.append(p)
    return out


def _parse_config(path: Path) -> dict:
    try:
        root = ET.parse(path).getroot()
        meta = root.find("metadata")
        if meta is None:
            return {}
        return {k: meta.get(k) for k in meta.keys()}
    except ET.ParseError:
        return {}


def _parse_metadata_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_network(path: Path) -> dict:
    n_nodes = n_links = n_has_signal = n_turn_restrictions = 0
    speeds: list[float] = []
    lanes: list[int] = []
    highway_types: Counter = Counter()
    try:
        for _, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "node":
                n_nodes += 1
                if elem.get("has_signal") == "true":
                    n_has_signal += 1
                elem.clear()
            elif elem.tag == "link":
                n_links += 1
                try:
                    speeds.append(float(elem.get("speed_limit", 0)))
                except (TypeError, ValueError):
                    pass
                try:
                    lanes.append(int(elem.get("lanes", 0)))
                except (TypeError, ValueError):
                    pass
                ht = elem.get("highway_type")
                if ht:
                    highway_types[ht] += 1
                elem.clear()
            elif elem.tag == "turn_restriction":
                n_turn_restrictions += 1
                elem.clear()
    except ET.ParseError as exc:
        return {"error": f"parse failed: {exc}"}

    return {
        "nodes": n_nodes,
        "links": n_links,
        "has_signal_count": n_has_signal,
        "turn_restrictions": n_turn_restrictions,
        "speed_min": min(speeds) if speeds else None,
        "speed_max": max(speeds) if speeds else None,
        "speed_mean": (sum(speeds) / len(speeds)) if speeds else None,
        "lanes_min": min(lanes) if lanes else None,
        "lanes_max": max(lanes) if lanes else None,
        "lanes_mean": (sum(lanes) / len(lanes)) if lanes else None,
        "highway_types": dict(highway_types),  # full counter for the road-classes section
    }


def _parse_signals(path: Path) -> dict:
    n_junctions = 0
    cycle_lengths: list[int] = []
    phase_counts: Counter = Counter()
    try:
        for _, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "junction":
                n_junctions += 1
                try:
                    cycle_lengths.append(int(elem.get("cycle_length_s", 0)))
                except (TypeError, ValueError):
                    pass
                phases = len(elem.findall("phase"))
                if phases:
                    phase_counts[phases] += 1
                elem.clear()
    except ET.ParseError as exc:
        return {"error": f"parse failed: {exc}"}

    return {
        "junctions": n_junctions,
        "cycle_min": min(cycle_lengths) if cycle_lengths else None,
        "cycle_max": max(cycle_lengths) if cycle_lengths else None,
        "phase_pattern": dict(phase_counts),
    }


def _parse_demand(path: Path) -> dict:
    composition = read_demand_composition(path)
    mode_counts: Counter = Counter()
    dest_sources: Counter = Counter()
    depart_min = depart_max = None
    n_rows = 0
    try:
        with path.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                n_rows += 1
                m = r.get("mode", "").strip()
                if m:
                    mode_counts[m] += 1
                ds = r.get("dest_source", "").strip()
                if ds:
                    dest_sources[ds] += 1
                try:
                    t = int(r.get("departure_time_s", "0"))
                    if depart_min is None or t < depart_min:
                        depart_min = t
                    if depart_max is None or t > depart_max:
                        depart_max = t
                except ValueError:
                    pass
    except OSError as exc:
        return {"error": f"open failed: {exc}"}

    return {
        "total": n_rows,
        "modes": dict(mode_counts),
        "dest_sources": dict(dest_sources),
        "depart_min_s": depart_min,
        "depart_max_s": depart_max,
        "composition": composition,
    }


def analyze(path: Path) -> ScenarioReport:
    rep = ScenarioReport(path=path, name=path.name)
    rep.config = _parse_config(path / "config.xml")
    rep.metadata = _parse_metadata_json(path / "generation_metadata.json")
    rep.network = _parse_network(path / "network.xml")
    rep.signals = _parse_signals(path / "signals.xml")
    rep.demand = _parse_demand(path / "demand.csv")
    rep.artefact_sizes = {
        f.name: f.stat().st_size for f in path.iterdir() if f.is_file()
    }
    return rep


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def color(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def fmt_count(n) -> str:
    if n is None:
        return "—"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def fmt_size(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}M"
    if n >= 1024:
        return f"{n / 1024:.1f}K"
    return f"{n}B"


def fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60:02d}m {s % 60:02d}s"
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


def fmt_seconds_window(start_s, end_s) -> str:
    if start_s is None or end_s is None:
        return "—"
    def hms(s: int) -> str:
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return f"{hms(start_s)}–{hms(end_s)}"


def fmt_pct(num, denom) -> str:
    if not denom:
        return "—"
    return f"{100.0 * num / denom:.2f}%"


def fmt_count_pct(num, denom) -> str:
    """`1,234 (56.78%)` — count plus percent of denom."""
    if num is None:
        return "—"
    if not denom:
        return fmt_count(num)
    return f"{fmt_count(num)} ({fmt_pct(num, denom)})"


def _safe_int(x):
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_configuration(reports: list[ScenarioReport]) -> list[tuple[str, list[str]]]:
    rows = []

    def row(label: str, fn) -> None:
        rows.append((label, [fn(r) for r in reports]))

    row("City", lambda r: r.metadata.get("city_name", r.metadata.get("city", "—")))
    row("Trips (gen / req)", lambda r: f"{fmt_count(r.metadata.get('trips_generated', 0))} / "
                                       f"{fmt_count(r.metadata.get('trips_requested', 0))}")
    row("Modes", lambda r: ", ".join(r.metadata.get("modes", [])) or "—")
    row("Time window",
        lambda r: fmt_seconds_window(
            r.metadata.get("start_time_s") or _safe_int(r.config.get("start_time")),
            r.metadata.get("end_time_s") or _safe_int(r.config.get("end_time")),
        ))
    row("Horizon (s)",
        lambda r: fmt_count((r.metadata.get("end_time_s") or 0)
                            - (r.metadata.get("start_time_s") or 0)))
    row("Radius",
        lambda r: f"{r.metadata.get('radius_km', '—')} km" if r.metadata.get("radius_km") else "—")
    row("Seed", lambda r: str(r.metadata.get("seed", "—")))
    row("Demand strategy", lambda r: r.metadata.get("demand_strategy", "—"))
    row("Generation time",
        lambda r: fmt_dur(r.metadata.get("generation_time_s")))
    row("OSM source",
        lambda r: r.metadata.get("osm_source", {}).get("name", "—"))
    return rows


def _section_network(reports):
    """Network shape: counts + speed/lane stats. Highway-type breakdown
    lives in its own ROAD CLASSES table so this one stays narrow."""
    rows: list[tuple[str, list[str] | None]] = []

    rows.append(("Nodes",
                 [fmt_count(r.network.get("nodes", 0)) for r in reports]))
    rows.append(("Links",
                 [fmt_count(r.network.get("links", 0)) for r in reports]))
    rows.append((
        "has_signal nodes",
        [fmt_count_pct(r.network.get("has_signal_count", 0),
                       r.network.get("nodes", 0))
         for r in reports]
    ))
    rows.append((
        "Turn restrictions",
        [fmt_count(r.network.get("turn_restrictions", 0)) for r in reports]
    ))
    rows.append((
        "Speed range (m/s)",
        [
            f"{r.network['speed_min']:.1f}–{r.network['speed_max']:.1f}"
            if r.network.get("speed_min") is not None else "—"
            for r in reports
        ]
    ))
    rows.append((
        "Speed mean (m/s)",
        [f"{r.network['speed_mean']:.2f}" if r.network.get("speed_mean") is not None else "—"
         for r in reports]
    ))
    rows.append((
        "Lane range",
        [
            f"{r.network['lanes_min']}–{r.network['lanes_max']}"
            if r.network.get("lanes_min") is not None else "—"
            for r in reports
        ]
    ))
    rows.append((
        "Lane mean",
        [f"{r.network['lanes_mean']:.2f}" if r.network.get("lanes_mean") is not None else "—"
         for r in reports]
    ))
    return rows


def _section_road_classes(reports):
    """One row per OSM highway type, columns are link counts per scenario.

    Picks the union of types present across all scenarios, sorts by total
    cross-scenario link count descending, caps at 12 to keep the table
    readable. Less-common types collapsed into an `(other)` row.
    """
    all_types: dict[str, int] = {}
    for r in reports:
        for ht, c in r.network.get("highway_types", {}).items():
            all_types[ht] = all_types.get(ht, 0) + c

    sorted_types = sorted(all_types, key=lambda t: -all_types[t])
    top = sorted_types[:12]
    others = sorted_types[12:]

    rows: list[tuple[str, list[str] | None]] = []
    for ht in top:
        rows.append((
            ht,
            [fmt_count(r.network.get("highway_types", {}).get(ht, 0))
             for r in reports]
        ))
    if others:
        rows.append((
            f"(other × {len(others)})",
            [fmt_count(sum(r.network.get("highway_types", {}).get(ht, 0)
                           for ht in others))
             for r in reports]
        ))
    return rows


def _section_signals(reports: list[ScenarioReport]) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    rows.append(("Junctions",
                 [fmt_count(r.signals.get("junctions", 0)) for r in reports]))

    def cycle_str(r: ScenarioReport) -> str:
        cmin = r.signals.get("cycle_min")
        cmax = r.signals.get("cycle_max")
        if cmin is None:
            return "—"
        return f"{cmin}s" if cmin == cmax else f"{cmin}–{cmax}s"

    rows.append(("Cycle length",
                 [cycle_str(r) for r in reports]))
    rows.append((
        "Phase pattern",
        [
            ", ".join(f"{n}-phase × {fmt_count(c)}"
                      for n, c in sorted(r.signals.get("phase_pattern", {}).items()))
            or "—"
            for r in reports
        ]
    ))
    rows.append((
        "Density (% of nodes)",
        [fmt_pct(r.signals.get("junctions", 0), r.network.get("nodes", 0))
         for r in reports]
    ))
    return rows


def _section_demand(reports):
    """One DEMAND table with three subsections separated by header rows:
        - top-level totals (mode mix, provenance split, departure window)
        - Trip-purpose breakdown (per-purpose row counts)
        - Peak split (AM/PM subtotals + school-chain counts)

    Subsection headers are emitted as `(label, None)` rows; render_table
    formats them as a divider line in the metric column.
    """
    rows: list[tuple[str, list[str] | None]] = []

    # --- top-level totals ---------------------------------------------
    rows.append(("Total trips",
                 [fmt_count(r.demand.get("total", 0)) for r in reports]))

    def mode_mix(r: ScenarioReport) -> str:
        modes = r.demand.get("modes", {})
        total = r.demand.get("total", 0) or 1
        return ", ".join(
            f"{m}: {fmt_count(c)} ({fmt_pct(c, total)})"
            for m, c in modes.items()
        ) or "—"

    rows.append(("Mode mix", [mode_mix(r) for r in reports]))
    rows.append((
        "Schedule-driven",
        [fmt_count_pct(r.demand.get("dest_sources", {}).get("schedule", 0),
                       r.demand.get("total", 0))
         for r in reports]
    ))
    rows.append((
        "Gravity fallback",
        [fmt_count_pct(r.demand.get("dest_sources", {}).get("gravity", 0),
                       r.demand.get("total", 0))
         for r in reports]
    ))
    rows.append((
        "Schedule pool size",
        [fmt_count(r.metadata.get("demand_provenance", {}).get("scheduled_pool_size"))
         for r in reports]
    ))
    rows.append((
        "Departure window",
        [fmt_seconds_window(r.demand.get("depart_min_s"), r.demand.get("depart_max_s"))
         for r in reports]
    ))

    # If no bundle has the purpose column we stop here — pre-V5 bundles
    # only carry the canonical 5 columns and the per-purpose / peak-split
    # subsections would be all-zero clutter.
    if not any(r.demand.get("composition") for r in reports):
        return rows

    # --- per-purpose subsection ---------------------------------------
    rows.append(("─── Trip-purpose breakdown ───", None))

    def purpose_cell(r: ScenarioReport, key: str) -> str:
        comp = r.demand.get("composition")
        if comp is None:
            return color("(pre-V5)", _DIM)
        c = comp["by_purpose"].get(key, 0)
        return fmt_count_pct(c, comp["total"])

    for purpose in ("HBW_AM", "HBSchool_AM", "HBW_AM_chained",
                    "HBW_PM", "HBSchool_PM", "HBW_PM_chained"):
        rows.append((purpose, [purpose_cell(r, purpose) for r in reports]))

    # --- peak split subsection ----------------------------------------
    rows.append(("─── Peak split & chain summary ───", None))

    def subtotal(r: ScenarioReport, key: str) -> str:
        comp = r.demand.get("composition")
        if comp is None:
            return color("—", _DIM)
        return fmt_count_pct(comp[key], comp["total"])

    rows.append(("AM peak", [subtotal(r, "am_peak") for r in reports]))
    rows.append(("PM peak", [subtotal(r, "pm_peak") for r in reports]))
    rows.append(("School-related (chain legs)",
                 [subtotal(r, "chain_legs") for r in reports]))

    def chain_count(r: ScenarioReport, side: str) -> str:
        comp = r.demand.get("composition")
        if comp is None:
            return color("—", _DIM)
        return fmt_count(comp[side])

    rows.append(("AM chains (parent×kid pairs)",
                 [chain_count(r, "school_chains_am") for r in reports]))
    rows.append(("PM chains (parent×kid pairs)",
                 [chain_count(r, "school_chains_pm") for r in reports]))
    return rows


def _section_artefacts(reports: list[ScenarioReport]) -> list[tuple[str, list[str]]]:
    """One row per canonical filename + a Total row."""
    canonical_files = ("network.xml", "demand.csv", "signals.xml",
                       "config.xml", "manifest.xml", "generation_metadata.json")
    rows: list[tuple[str, list[str]]] = []
    for fname in canonical_files:
        rows.append((fname,
                     [fmt_size(r.artefact_sizes.get(fname)) for r in reports]))
    rows.append(("Total",
                 [fmt_size(sum(r.artefact_sizes.values())) for r in reports]))
    return rows


def _section_toolchain(reports: list[ScenarioReport]) -> list[tuple[str, list[str]]]:
    """Env recorded at generation time."""
    rows: list[tuple[str, list[str]]] = []
    keys = ["python", "platform", "osmnx", "numpy", "networkx",
            "lxml", "pandas", "shapely", "osmium", "geopandas"]
    for k in keys:
        rows.append((
            k,
            [r.metadata.get("toolchain", {}).get(k, "—") for r in reports]
        ))
    return rows


# ---------------------------------------------------------------------------
# Table renderer (ANSI-aware width calculation)
# ---------------------------------------------------------------------------


def _visible_len(s: str) -> int:
    """Length of string with ANSI escape codes stripped."""
    out, in_esc = [], False
    for ch in s:
        if ch == "\033":
            in_esc = True
        elif in_esc:
            if ch == "m":
                in_esc = False
        else:
            out.append(ch)
    return len(out)


def _pad(s: str, width: int, right: bool = False) -> str:
    """Left/right pad accounting for ANSI escape codes."""
    pad_len = width - _visible_len(s)
    if pad_len <= 0:
        return s
    return (" " * pad_len + s) if right else (s + " " * pad_len)


def _render_single_page(
    title: str,
    headers: list[str],
    rows: list[tuple[str, list[str] | None]],
    label_width: int,
    value_widths: list[int],
) -> str:
    def render_cells(cells: list[str], bold: bool = False) -> str:
        out = "  " + _pad(cells[0], label_width)
        for i, c in enumerate(cells[1:]):
            out += "  " + _pad(c, value_widths[i], right=True)
        return color(out, _BOLD) if bold else out

    lines = ["", color("▼ " + title, _BOLD + _CYAN),
             render_cells(headers, bold=True)]
    sep_widths = [label_width] + value_widths
    lines.append("  " + "  ".join("─" * w for w in sep_widths))
    for label, vals in rows:
        if vals is None:
            # Subsection separator: blank row + dim header line.
            lines.append("")
            lines.append("  " + color(label, _DIM + _BOLD))
        else:
            lines.append(render_cells([label] + vals))
    return "\n".join(lines)


def render_table(
    title: str,
    headers: list[str],
    rows: list[tuple[str, list[str] | None]],
    *,
    term_width: int | None = None,
) -> str:
    """Render a side-by-side table; auto-paginate if the table is wider
    than the terminal.

    Column 0 is the metric label (left-aligned). Columns 1.. are scenario
    values (right-aligned). Widths auto-fit to the longest cell. ANSI
    escape codes are stripped before width calculation so columns line
    up regardless of colour. Rows where ``vals is None`` are subsection
    headers, rendered as a divider line in the metric column.

    When the rendered width would exceed ``term_width`` (default: actual
    terminal columns), the scenario columns are chunked across multiple
    pages — the metric column repeats on every page, each page shows a
    contiguous subset of scenarios with a `(p/N)` page suffix on the
    title.
    """
    data_rows = [(label, vals) for label, vals in rows if vals is not None]
    label_width = max(
        [_visible_len(headers[0])]
        + [_visible_len(label) for label, _ in rows]
    )
    value_widths = [
        max(
            [_visible_len(headers[i + 1])]
            + [_visible_len(row_vals[i]) for _, row_vals in data_rows]
        )
        for i in range(len(headers) - 1)
    ]

    if term_width is None:
        term_width = shutil.get_terminal_size((120, 24)).columns

    # Reserve 2 spaces for left margin + 2 spaces between columns.
    fixed_overhead = 2 + label_width  # "  " + label
    available = max(term_width - fixed_overhead, 20)

    # Greedily pack scenarios into pages.
    pages: list[list[int]] = []
    current_page: list[int] = []
    current_used = 0
    for i, w in enumerate(value_widths):
        col_w = w + 2  # column + gutter
        if current_page and current_used + col_w > available:
            pages.append(current_page)
            current_page = [i]
            current_used = col_w
        else:
            current_page.append(i)
            current_used += col_w
    if current_page:
        pages.append(current_page)

    # Single-page fast path.
    if len(pages) == 1:
        return _render_single_page(title, headers, rows, label_width, value_widths)

    # Multi-page rendering: render each page with a (p/N) suffix.
    chunks: list[str] = []
    n_total = len(value_widths)
    for p_idx, col_idxs in enumerate(pages):
        first, last = col_idxs[0] + 1, col_idxs[-1] + 1
        if first == last:
            page_title = f"{title}  (scenario {first} of {n_total})"
        else:
            page_title = f"{title}  (scenarios {first}–{last} of {n_total})"
        sub_headers = [headers[0]] + [headers[i + 1] for i in col_idxs]
        sub_rows: list[tuple[str, list[str] | None]] = []
        for label, vals in rows:
            if vals is None:
                sub_rows.append((label, None))
            else:
                sub_rows.append((label, [vals[i] for i in col_idxs]))
        sub_value_widths = [value_widths[i] for i in col_idxs]
        chunks.append(_render_single_page(
            page_title, sub_headers, sub_rows, label_width, sub_value_widths
        ))
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


SECTIONS = {
    "configuration": ("CONFIGURATION", _section_configuration),
    "network":       ("NETWORK", _section_network),
    "road_classes":  ("ROAD CLASSES (link counts by OSM highway type)",
                      _section_road_classes),
    "signals":       ("SIGNALS", _section_signals),
    "demand":        ("DEMAND", _section_demand),
    "artefacts":     ("ARTEFACTS (file sizes)", _section_artefacts),
    "toolchain":     ("TOOLCHAIN (recorded at generation time)", _section_toolchain),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tabular end-to-end analysis of SimForge scenario bundles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "scenarios", nargs="*",
        help="Scenario names (relative to scenarios/) or full paths. "
             "Default: every complete bundle in scenarios/.",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colours (useful when piping to file or pager).",
    )
    parser.add_argument(
        "--section", choices=list(SECTIONS.keys()), action="append",
        help="Emit only the named section(s). Repeatable. "
             "Default: all sections.",
    )
    args = parser.parse_args()

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False

    paths = _resolve(args.scenarios)
    if not paths:
        print("No complete scenario bundles found.", file=sys.stderr)
        if not args.scenarios:
            print(f"  Looked under: {REPO_ROOT}/scenarios", file=sys.stderr)
            print("  Generate one with: python scripts/01_chicago_1k_car.py",
                  file=sys.stderr)
        return 1

    reports = [analyze(p) for p in paths]
    headers = ["Metric"] + [r.name for r in reports]

    print()
    title = (f"SimForge Scenario Analyzer — {len(paths)} bundle"
             f"{'s' if len(paths) != 1 else ''}")
    print(color("═" * 78, _CYAN))
    print(color(f"  {title}", _BOLD + _CYAN))
    print(color("═" * 78, _CYAN))

    selected = args.section or list(SECTIONS.keys())
    for key in selected:
        title, builder = SECTIONS[key]
        rows = builder(reports)
        if rows is None:
            continue  # Section opted to suppress (e.g. all bundles pre-V5)
        print(render_table(title, headers, rows))

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
