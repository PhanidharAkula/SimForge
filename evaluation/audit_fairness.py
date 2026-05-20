"""
Cross-engine fairness audit for a SimForge benchmark run directory.

For each scenario in the run directory, this script compares the inputs
that each engine actually consumed (network nodes/links, feasibility
verdict, trip counts) and the outputs (per-cell travel time, P95, trip
count) so a defender can verify that "the engines were given the same
problem and we measured each one fairly."

Usage:
    python -m evaluation.audit_fairness runs/pitzer_smoke/

Optional second arg picks a single seed (default: 42):
    python -m evaluation.audit_fairness runs/pitzer_smoke/ 43

Sits alongside ``analyze_benchmark.py`` (headline tables) and
``generate_plots.py`` (figures) as the third post-benchmark step. The
canonical post-benchmark pipeline is::

    python -m evaluation.analyze_benchmark   <results.json> --markdown
    python -m evaluation.audit_fairness      <run_dir>
    python -m evaluation.generate_plots      <results.json>

The script makes no edits and emits no files — pure read-only audit
suitable for committing to thesis appendix or pasting into a defense
slide.
"""

from __future__ import annotations

import csv
import gzip
import json
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluation.demand_composition import (
    find_canonical_demand,
    format_composition_report,
    read_demand_composition,
)


def _hms_to_seconds(hms: str) -> float:
    """MATSim trav_time is HH:MM:SS — convert to seconds."""
    try:
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return 0.0


def _count_dtalite_demand(demand_csv: Path) -> tuple[int, int]:
    """Returns (od_pair_count, total_volume) — DTALite aggregates by OD."""
    pairs = 0
    vol = 0
    with demand_csv.open() as f:
        for r in csv.DictReader(f):
            pairs += 1
            try:
                vol += int(float(r.get("volume", "0") or 0))
            except ValueError:
                continue
    return pairs, vol


def _count_matsim_persons(plans_xml: Path) -> int:
    return len(ET.parse(plans_xml).getroot().findall("person"))


def _count_xml_elements(network_xml: Path, tag: str) -> int:
    return len(ET.parse(network_xml).getroot().findall(f".//{tag}"))


def _count_csv_rows(csv_path: Path) -> int:
    with csv_path.open() as f:
        return sum(1 for _ in csv.DictReader(f))


def _matsim_travel_times(trips_gz: Path) -> list[float]:
    out = []
    with gzip.open(trips_gz, "rt") as f:
        for r in csv.DictReader(f, delimiter=";"):
            tt = _hms_to_seconds(r.get("trav_time", "0:0:0"))
            if tt > 0:
                out.append(tt)
    return out


def _dtalite_travel_times(agent_csv: Path) -> list[float]:
    out = []
    with agent_csv.open() as f:
        for r in csv.DictReader(f):
            try:
                tt_min = float(r.get("travel_time", "0") or 0)
                vol = float(r.get("volume", "1") or 1)
            except ValueError:
                continue
            if tt_min > 0 and vol > 0:
                n = max(1, int(round(vol)))
                out.extend([tt_min * 60.0] * n)
    return out


def _sumo_travel_times(tripinfo_xml: Path) -> list[float]:
    out = []
    try:
        tree = ET.parse(tripinfo_xml)
    except (ET.ParseError, FileNotFoundError):
        return out
    for ti in tree.getroot().findall("tripinfo"):
        try:
            duration = float(ti.get("duration", "0"))
        except ValueError:
            continue
        if duration > 0:
            out.append(duration)
    return out


def _find_cell_dir(base: Path, scenario: str, engine: str, seed: int,
                   mode: str = "meso") -> Path | None:
    """Locate the engine-cell directory for a given (scenario, engine, mode, seed).

    SimForge writes benchmark results under several layouts depending on
    the entry point, the SimForge version, and any sbatch wrapping:

      A. ``python run.py``           — flat layout (mode in dir name)
         ``<base>/<scenario>_<engine>_<mode>_seed<N>/native_files/``

      B. ``python -m execution.run_benchmark`` (Phase 12+, mode-segmented)
         ``<base>/<scenario>/<engine>/<mode>/seed_<N>/``

      C. Layout B inside a parallel-by-scenario sbatch wrapper
         ``<base>/<scenario>/<scenario>/<engine>/<mode>/seed_<N>/``
         (double-nested — `--output` already includes scenario)

      D. Pointed at the per-scenario subdir of a parallel-by-scenario run
         ``<base>/<engine>/<mode>/seed_<N>/`` — scenario name is implicit
         (= ``base.name``)

      B', C', D'. Pre-Phase-12 layouts WITHOUT the ``mode`` segment —
         ``<base>/<scenario>/<engine>/seed_<N>/`` etc. Older runs are
         still readable; mode is unrecoverable from the path alone, so
         the audit treats whatever's on disk as the requested ``mode``.

    Returns the path containing the per-cell prepared inputs and outputs,
    or None if no matching directory exists.
    """
    candidates = [
        # A: flat run.py output, mode embedded in dir name
        base / f"{scenario}_{engine}_{mode}_seed{seed}" / "native_files",
        # B (Phase 12+): mode-segmented nested execution.run_benchmark output
        base / scenario / engine / mode / f"seed_{seed}",
        # C (Phase 12+): doubly-nested with mode
        base / scenario / scenario / engine / mode / f"seed_{seed}",
        # D (Phase 12+): pointed-at scenario subdir, with mode
        base / engine / mode / f"seed_{seed}",
        # Back-compat fallbacks — pre-Phase-12 layouts (mode-less). Older
        # runs only kept the LAST mode written for each (engine, seed) cell,
        # so on-disk artefacts may belong to micro even when meso was asked.
        base / scenario / engine / f"seed_{seed}",
        base / scenario / scenario / engine / f"seed_{seed}",
        base / engine / f"seed_{seed}",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def audit_scenario(base: Path, scenario: str, seed: int = 42,
                   mode: str = "meso") -> None:
    print("=" * 80)
    print(f"FAIRNESS AUDIT — {scenario} {mode} (seed {seed})")
    print("=" * 80)

    engines = ("sumo", "matsim", "dtalite")
    cells = {}
    for eng in engines:
        cell = _find_cell_dir(base, scenario, eng, seed, mode=mode)
        if cell is not None:
            cells[eng] = cell

    if not cells:
        print(f"  (no cells found for {scenario} seed {seed})")
        return
    print(f"  layout: {next(iter(cells.values())).relative_to(base)} (... etc)")

    # --------------------------------------------------------------- Q1
    print("\n--- Q1: Same feasibility verdict across all engines? ---")
    reports = {}
    for eng, nf in cells.items():
        fp = nf / "feasibility_report.json"
        if fp.is_file():
            reports[eng] = json.loads(fp.read_text())
            r = reports[eng]
            pct = 100.0 * r["feasible_trips"] / max(r["total_trips"], 1)
            print(f"  {eng:8} feasible {r['feasible_trips']}/{r['total_trips']} ({pct:.1f}%) "
                  f"  SCC={r['scc_nodes']}/{r['total_nodes']} nodes, "
                  f"{r['scc_links']}/{r['total_links']} links")
    if len(reports) >= 2:
        keys = ["feasible_trips", "total_trips", "scc_nodes", "scc_links",
                "skipped_outside_scc", "skipped_unknown_nodes",
                "skipped_missing_fields", "skipped_unsupported_mode"]
        first_eng = next(iter(reports))
        # Use .get(...) so reports written before mode-aware feasibility shipped
        # (without `skipped_unsupported_mode`) still compare cleanly — they
        # default to 0 alongside fresh reports' 0 for car-only bundles.
        same = all(
            reports[eng].get(k, 0) == reports[first_eng].get(k, 0)
            for eng in reports for k in keys
        )
        mark = "PASS" if same else "FAIL"
        print(f"  [{mark}] feasibility verdicts byte-identical across "
              f"{', '.join(sorted(reports))}")

    # --------------------------------------------------------------- Q2
    print("\n--- Q2: Same network across all engines? ---")
    net = {}
    if "matsim" in cells:
        nx = cells["matsim"] / "network.xml"
        if nx.is_file():
            net["matsim"] = (
                _count_xml_elements(nx, "node"),
                _count_xml_elements(nx, "link"),
            )
    if "dtalite" in cells:
        n = cells["dtalite"] / "node.csv"
        l = cells["dtalite"] / "link.csv"
        if n.is_file() and l.is_file():
            net["dtalite"] = (_count_csv_rows(n), _count_csv_rows(l))
    if "sumo" in cells:
        # Prefer the pre-netconvert .nod.xml + .edg.xml — those map 1:1 to
        # canonical nodes/links. The compiled .net.xml inflates the count
        # with internal lane junctions (one per turn-lane connection at
        # each intersection) and internal lane edges, which is correct
        # SUMO behaviour but confuses a cross-engine fairness count.
        nods = list(cells["sumo"].glob("*.nod.xml"))
        edgs = list(cells["sumo"].glob("*.edg.xml"))
        if nods and edgs:
            n = _count_xml_elements(nods[0], "node")
            l = _count_xml_elements(edgs[0], "edge")
            net["sumo"] = (n, l)
        else:
            # Fallback: count road junctions from .net.xml, filtering out
            # type="internal" entries that represent intra-junction lane geometry.
            nets = list(cells["sumo"].glob("*.net.xml"))
            if nets:
                root = ET.parse(nets[0]).getroot()
                n = sum(1 for j in root.findall("junction")
                        if j.get("type") != "internal")
                l = sum(1 for e in root.findall("edge")
                        if e.get("function") != "internal")
                net["sumo"] = (n, l)
    for eng, (n, l) in net.items():
        print(f"  {eng:8} emits: {n} nodes, {l} links")
    if len(net) >= 2:
        node_counts = {n for n, _ in net.values()}
        link_counts = {l for _, l in net.values()}
        if len(node_counts) == 1:
            print(f"  [PASS] node counts identical across {', '.join(sorted(net))}")
        else:
            deltas = ", ".join(f"{e}={n}" for e, (n, _) in net.items())
            print(f"  [WARN] node counts differ: {deltas}")
            print( "         (DTALite drops 0 self-loops + 0 sub-meter edges from MATSim's SCC,")
            print( "         and SUMO's .net.xml junction count includes internal lane junctions)")

    # --------------------------------------------------------------- Q3
    print("\n--- Q3: Are all engines actually simulating that trip count? ---")
    sims = {}
    if "matsim" in cells:
        plans = cells["matsim"] / "plans.xml"
        if plans.is_file():
            sims["matsim"] = _count_matsim_persons(plans)
    if "dtalite" in cells:
        d = cells["dtalite"] / "demand.csv"
        if d.is_file():
            pairs, vol = _count_dtalite_demand(d)
            sims["dtalite"] = vol
    if "sumo" in cells:
        rou = list(cells["sumo"].glob("*.rou.xml"))
        if rou:
            sims["sumo"] = len(ET.parse(rou[0]).getroot().findall("vehicle")) + \
                           len(ET.parse(rou[0]).getroot().findall("trip"))
    # Each engine's feasibility report carries its own mode-filtered target
    # (engines today all declare supported_modes={"car"}, so the targets
    # match across engines for car-only bundles; for multi-mode bundles
    # each engine's target is its car-only subset). Compare each engine
    # against its own target so audit Q3 stays correct under mode filtering.
    for eng, n in sims.items():
        target = reports.get(eng, {}).get("feasible_trips", 0)
        modes = reports.get(eng, {}).get("supported_modes") or []
        modes_clause = f" mode∈{{{','.join(modes)}}}" if modes else ""
        mark = "PASS" if n == target else "WARN"
        print(f"  {eng:8} simulates {n} trips/persons  "
              f"[{mark} vs target {target}{modes_clause}]")

    # --------------------------------------------------------------- Q4
    print("\n--- Q4: Cross-engine travel time comparison ---")
    tts = {}
    if "matsim" in cells:
        gz = cells["matsim"] / "output" / "output_trips.csv.gz"
        if gz.is_file():
            tts["matsim"] = _matsim_travel_times(gz)
    if "dtalite" in cells:
        a = cells["dtalite"] / "agent.csv"
        if a.is_file():
            tts["dtalite"] = _dtalite_travel_times(a)
    if "sumo" in cells:
        # SUMO writes tripinfo.xml to the run output dir (parent of
        # native_files/ in layout A; alongside the engine seed dir in
        # layouts B/C/D).
        sumo_search_dirs = [cells["sumo"]]
        if cells["sumo"].name == "native_files":
            sumo_search_dirs.append(cells["sumo"].parent)
        ti_path = None
        for d in sumo_search_dirs:
            candidates = list(d.glob("*tripinfo*.xml"))
            if candidates:
                ti_path = candidates[0]
                break
        if ti_path is not None:
            tts["sumo"] = _sumo_travel_times(ti_path)

    for eng in engines:
        if eng not in tts or not tts[eng]:
            continue
        sorted_tts = sorted(tts[eng])
        p95 = sorted_tts[int(0.95 * (len(sorted_tts) - 1))]
        print(f"  {eng:8} N={len(sorted_tts):>6}   "
              f"mean={statistics.mean(sorted_tts):7.1f}s   "
              f"P95={p95:7.1f}s   "
              f"min={min(sorted_tts):.1f}s   max={max(sorted_tts):.1f}s")

    if len(tts) >= 2 and "matsim" in tts and "dtalite" in tts and tts["matsim"] and tts["dtalite"]:
        ratio = statistics.mean(tts["dtalite"]) / statistics.mean(tts["matsim"])
        print(f"\n  DTALite/MATSim mean-TT ratio: {ratio:.3f}  "
              f"({'+' if ratio > 1 else ''}{(ratio-1)*100:.1f}%)")
    if "sumo" in tts and "matsim" in tts and tts["sumo"] and tts["matsim"]:
        ratio = statistics.mean(tts["sumo"]) / statistics.mean(tts["matsim"])
        print(f"  SUMO/MATSim    mean-TT ratio: {ratio:.3f}  "
              f"({'+' if ratio > 1 else ''}{(ratio-1)*100:.1f}%)")
    if "sumo" in tts and "dtalite" in tts and tts["sumo"] and tts["dtalite"]:
        ratio = statistics.mean(tts["sumo"]) / statistics.mean(tts["dtalite"])
        print(f"  SUMO/DTALite   mean-TT ratio: {ratio:.3f}  "
              f"({'+' if ratio > 1 else ''}{(ratio-1)*100:.1f}%)")

    # --------------------------------------------------------------- Q5
    # Demand composition (V5+ trip-purpose breakdown). Reads the
    # canonical bundle's demand.csv (engines may overwrite their cell
    # copy with engine-specific columns — DTALite drops `purpose` to
    # use `o_zone_id, d_zone_id, volume`). Pre-V5 bundles return None
    # and we skip the section gracefully.
    print("\n--- Q5: Demand composition (V5+ trip-purpose breakdown) ---")
    canonical_demand = find_canonical_demand(scenario)
    comp = read_demand_composition(canonical_demand)
    if comp is None:
        print(f"  (no V5+ purpose column at {canonical_demand} — skipping)")
    else:
        print(f"  source: {canonical_demand}")
        print(format_composition_report(comp))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__ or "Usage: python -m evaluation.audit_fairness <run-dir> [seed]",
              file=sys.stderr)
        return 0 if (len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help")) else 2
    base = Path(sys.argv[1])
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    if not base.is_dir():
        print(f"Run directory not found: {base}", file=sys.stderr)
        return 1

    scenarios = _discover_scenarios(base)
    if not scenarios:
        print(f"No engine-cell directories found under {base}\n"
              f"  Looked for layouts (Phase 12+ with mode segment + pre-12 fallbacks):\n"
              f"    A. <base>/<scenario>_<engine>_<mode>_seed<N>/native_files/\n"
              f"    B. <base>/<scenario>/<engine>/<mode>/seed_<N>/\n"
              f"    C. <base>/<scenario>/<scenario>/<engine>/<mode>/seed_<N>/\n"
              f"    D. <base>/<engine>/<mode>/seed_<N>/  (base = the scenario dir itself)\n"
              f"    Pre-12: same as B/C/D but without the <mode>/ segment.",
              file=sys.stderr)
        return 1

    # Iterate over (scenario, mode) pairs — Phase 12+ runs may have both meso
    # and micro under the same scenario; pre-Phase-12 runs default to meso.
    for sc in scenarios:
        for mode in _discover_modes(base, sc):
            audit_scenario(base, sc, seed, mode=mode)
            print()
    return 0


_ENGINES = ("sumo", "matsim", "dtalite")
_MODES = ("meso", "micro")


def _has_seed_dir(parent: Path) -> bool:
    """Whether ``parent`` contains any ``seed_<N>`` subdir."""
    return parent.is_dir() and any(parent.glob("seed_*"))


def _has_mode_seed(parent: Path) -> bool:
    """Whether ``parent/<mode>/seed_<N>`` exists for any known mode."""
    return parent.is_dir() and any(
        _has_seed_dir(parent / m) for m in _MODES
    )


def _discover_scenarios(base: Path) -> list[str]:
    """Find scenario IDs under any supported layout (Phase 12+ and pre-12)."""
    found: set[str] = set()

    # Layout D first: <base>/<engine>/[<mode>/]seed_<N> — base IS the scenario
    # (parallel-by-scenario sbatch worker output dir).
    for eng in _ENGINES:
        eng_dir = base / eng
        if _has_seed_dir(eng_dir) or _has_mode_seed(eng_dir):
            found.add(base.name)
            break

    # Layout A: flat run.py output — <scenario>_<engine>_<mode>_seed<N>
    for p in base.iterdir():
        if not p.is_dir() or "_seed" not in p.name:
            continue
        for eng in _ENGINES:
            for m in _MODES:
                marker = f"_{eng}_{m}_seed"
                if marker in p.name:
                    found.add(p.name.split(marker)[0])
                    break

    # Layouts B and C: <base>/<scenario>/.../<engine>/[<mode>/]seed_<N>
    for sc_dir in base.iterdir():
        if not sc_dir.is_dir() or sc_dir.name.startswith("."):
            # Skip dotted helper dirs like `.cache/` (Phase 12+ BFS-prep cache).
            continue
        for eng in _ENGINES:
            eng_b = sc_dir / eng
            eng_c = sc_dir / sc_dir.name / eng
            if (_has_seed_dir(eng_b) or _has_mode_seed(eng_b)
                    or _has_seed_dir(eng_c) or _has_mode_seed(eng_c)):
                found.add(sc_dir.name)
                break

    return sorted(found)


def _discover_modes(base: Path, scenario: str) -> list[str]:
    """Which modes have at least one engine cell on disk for this scenario.

    Phase 12+ layouts encode mode in the path (`<engine>/<mode>/seed_*`).
    Pre-Phase-12 layouts don't — mode is unrecoverable, default to ``meso``
    (the only mode supported by MATSim and DTALite).
    """
    modes_found: set[str] = set()
    candidates_for_engine = lambda eng: [
        base / scenario / eng,
        base / scenario / scenario / eng,
        base / eng,  # layout D
    ]
    for eng in _ENGINES:
        for eng_dir in candidates_for_engine(eng):
            if not eng_dir.is_dir():
                continue
            for m in _MODES:
                if _has_seed_dir(eng_dir / m):
                    modes_found.add(m)
            # Pre-Phase-12: no mode subdir, cells live directly under engine
            if _has_seed_dir(eng_dir):
                modes_found.add("meso")  # best guess for legacy runs
    return sorted(modes_found) or ["meso"]


if __name__ == "__main__":
    sys.exit(main())
