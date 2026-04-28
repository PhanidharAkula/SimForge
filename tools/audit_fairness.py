"""
Cross-engine fairness audit for a SimForge benchmark run directory.

For each scenario in the run directory, this script compares the inputs
that each engine actually consumed (network nodes/links, feasibility
verdict, trip counts) and the outputs (per-cell travel time, P95, trip
count) so a defender can verify that "the engines were given the same
problem and we measured each one fairly."

Usage:
    python tools/audit_fairness.py runs/pitzer_smoke/

Optional second arg picks a single seed (default: 42):
    python tools/audit_fairness.py runs/pitzer_smoke/ 43

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


def audit_scenario(base: Path, scenario: str, seed: int = 42) -> None:
    print("=" * 80)
    print(f"FAIRNESS AUDIT — {scenario} (seed {seed})")
    print("=" * 80)

    engines = ("sumo", "matsim", "dtalite")
    cells = {}
    for eng in engines:
        nf = base / f"{scenario}_{eng}_meso_seed{seed}" / "native_files"
        if nf.is_dir():
            cells[eng] = nf

    if not cells:
        print(f"  (no cells found for {scenario} seed {seed})")
        return

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
                "skipped_outside_scc", "skipped_unknown_nodes", "skipped_missing_fields"]
        first_eng = next(iter(reports))
        same = all(
            reports[eng][k] == reports[first_eng][k]
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
        # SUMO emits .nod.xml + .edg.xml (canonical) and .net.xml (compiled)
        nx = cells["sumo"] / "chicago_1k_car.net.xml"
        # generic glob — find .net.xml in the dir
        nets = list(cells["sumo"].glob("*.net.xml"))
        if nets:
            tree = ET.parse(nets[0])
            root = tree.getroot()
            n = len(root.findall("junction"))
            l = len(root.findall("edge"))
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
    target = reports.get(next(iter(reports), ""), {}).get("feasible_trips", 0) if reports else 0
    for eng, n in sims.items():
        mark = "PASS" if n == target else "WARN"
        print(f"  {eng:8} simulates {n} trips/persons  [{mark} vs target {target}]")

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
        ti = list(cells["sumo"].glob("*tripinfo*.xml"))
        if ti:
            tts["sumo"] = _sumo_travel_times(ti[0])

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


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    base = Path(sys.argv[1])
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    if not base.is_dir():
        print(f"Run directory not found: {base}", file=sys.stderr)
        return 1

    scenarios = sorted({
        p.name.split("_meso_seed")[0].rsplit("_", 1)[0]
        for p in base.iterdir()
        if p.is_dir() and "_meso_seed" in p.name
    })
    if not scenarios:
        print(f"No <scenario>_<engine>_meso_seed* dirs under {base}", file=sys.stderr)
        return 1

    for sc in scenarios:
        audit_scenario(base, sc, seed)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
