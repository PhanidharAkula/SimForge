"""Cross-engine fidelity metrics (RMSE / GEH / KS) for RQ1.

No observed sensor baseline exists, so these statistics are computed
*inter-simulator*: one engine's output is the reference, the other is the
comparison. This directly answers RQ1 ("how closely do engines reproduce each
other's outputs on identical inputs?") with the standard fidelity statistics
the framework defines in evaluation/metrics/fidelity.py.

  * RMSE : root-mean-square per-trip travel-time difference (seconds), over
           trips both engines completed (matched by canonical trip id).
  * GEH  : link-level vehicle-count agreement. SUMO/MATSim drive the *same*
           canonical BFS routes (the fairness contract), so per-link counts
           differ only by which trips each engine completed. Reported as mean
           GEH and the share of links with GEH < 5 (the acceptance gate).
  * KS   : Kolmogorov-Smirnov statistic between the two engines' per-trip
           travel-time distributions, with the alpha=0.05 critical value.

RMSE and GEH require canonical per-trip identity and shared routes, so they are
reported for the SUMO/MATSim/micro pairs; DTALite (UE, OD-aggregated, its own
routes) gets the distribution-level KS only.

Usage:  python -m evaluation.cross_engine_fidelity
"""

from __future__ import annotations

import csv
import gzip
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from evaluation.metrics.fidelity import (
    compute_rmse,
    compute_geh_batch,
    compute_ks_statistic,
)

SEEDS = [42, 43, 44, 45, 46]

# (scenario, run_dir)
SCENARIOS = [
    ("chicago_1k_car", Path("runs/benchmark_small")),
    ("nyc_10k_car", Path("runs/benchmark_small")),
    ("la_50k_car", Path("runs/benchmark_small")),
    ("chicago_200k_car", Path("runs/benchmark_large")),
    ("nyc_500k_car", Path("runs/benchmark_large")),
]

# (label, engine_a, mode_a, engine_b, mode_b)
PAIRS = [
    ("SUMO meso / MATSim meso", "sumo", "meso", "matsim", "meso"),
    ("SUMO micro / SUMO meso", "sumo", "micro", "sumo", "meso"),
    ("DTALite / MATSim meso", "dtalite", "meso", "matsim", "meso"),
    ("DTALite / SUMO meso", "dtalite", "meso", "sumo", "meso"),
]


# ---------- per-engine per-trip travel time ----------
def _sumo_tt(d: Path) -> dict[str, float] | None:
    p = d / "tripinfo.xml"
    if not p.exists():
        return None
    out: dict[str, float] = {}
    for _, e in ET.iterparse(str(p), events=("end",)):
        if e.tag == "tripinfo":
            vid = e.get("id", "")
            dur = e.get("duration")
            if dur is not None:
                out[vid[4:] if vid.startswith("veh_") else vid] = float(dur)
            e.clear()
    return out


def _matsim_tt(d: Path) -> dict[str, float] | None:
    p = d / "output" / "output_trips.csv.gz"
    if not p.exists():
        p = d / "output" / "output_trips.csv"
    if not p.exists():
        return None
    opener = gzip.open if str(p).endswith(".gz") else open
    out: dict[str, float] = {}
    with opener(p, "rt") as f:
        for row in csv.DictReader(f, delimiter=";"):
            person = row["person"]
            h, m, s = row["trav_time"].split(":")
            out[person[7:] if person.startswith("person_") else person] = (
                int(h) * 3600 + int(m) * 60 + float(s)
            )
    return out


def _dtalite_tt(d: Path) -> list[float] | None:
    """DTALite per-vehicle TT distribution (seconds). No canonical trip id, so
    KS-only. Matches parse_dtalite_output: expand each equilibrium path by
    round(volume) and keep travel_time > 0 (agent.csv is in minutes)."""
    p = d / "agent.csv"
    if not p.exists():
        return None
    out: list[float] = []
    with open(p, "rt", newline="") as f:
        for row in csv.DictReader(f):
            try:
                tt_min = float(row.get("travel_time", "0") or 0)
                volume = float(row.get("volume", "1") or 1)
            except ValueError:
                continue
            if not (math.isfinite(tt_min) and math.isfinite(volume)) or volume <= 0:
                continue
            n = int(round(volume))
            if n <= 0 or tt_min <= 0:
                continue
            out.extend([tt_min * 60.0] * n)
    return out or None


def engine_tt(base: Path, engine: str, mode: str, seed: int):
    """Return (tt_by_trip | None, tt_list | None)."""
    d = base / engine / mode / f"seed_{seed}"
    if engine == "sumo":
        tt = _sumo_tt(d)
    elif engine == "matsim":
        tt = _matsim_tt(d)
    elif engine == "dtalite":
        lst = _dtalite_tt(d)
        return (None, lst) if lst else None
    else:
        return None
    return (tt, list(tt.values())) if tt else None


def _routes(base: Path, seed: int) -> dict[str, list[str]]:
    """Shared canonical routes (read from SUMO meso)."""
    p = base / "sumo" / "meso" / f"seed_{seed}" / "routes.rou.xml"
    out: dict[str, list[str]] = {}
    if not p.exists():
        return out
    for _, e in ET.iterparse(str(p), events=("end",)):
        if e.tag == "vehicle":
            r = e.find("route")
            vid = e.get("id", "")
            if r is not None and r.get("edges"):
                out[vid[4:] if vid.startswith("veh_") else vid] = r.get("edges").split()
            e.clear()
    return out


def _link_counts(routes: dict[str, list[str]], completed: set[str]) -> Counter:
    c: Counter = Counter()
    for tid in completed:
        for link in routes.get(tid, ()):
            c[link] += 1
    return c


def compare(a, b, routes) -> dict:
    a_by, a_list = a
    b_by, b_list = b
    ks, kscrit = compute_ks_statistic(a_list, b_list)
    res = {
        "n_a": len(a_list), "n_b": len(b_list),
        "ks": ks, "kscrit": kscrit, "differ": ks > kscrit,
        "rmse": None, "geh": None, "geh_pct": None, "matched": 0,
    }
    if a_by is not None and b_by is not None:
        matched = sorted(set(a_by) & set(b_by))
        res["matched"] = len(matched)
        if matched:
            res["rmse"] = compute_rmse([a_by[t] for t in matched], [b_by[t] for t in matched])
        if routes:
            ac, bc = _link_counts(routes, set(a_by)), _link_counts(routes, set(b_by))
            links = sorted(set(ac) | set(bc))
            obs = [float(bc.get(l, 0)) for l in links]  # reference engine = b
            sim = [float(ac.get(l, 0)) for l in links]
            res["geh"], res["geh_pct"], _ = compute_geh_batch(obs, sim)
    return res


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _fmt(x, w, p=1):
    return f"{x:{w}.{p}f}" if isinstance(x, float) else f"{'-':>{w}}"


def main() -> None:
    print("Cross-engine fidelity (inter-simulator RMSE / GEH / KS), mean over seeds 42-46\n")
    hdr = (f"{'pair':24} {'scenario':16} {'RMSE(s)':>9} {'GEH':>6} {'%GEH<5':>7} "
           f"{'KS':>7} {'KScrit':>7} {'differ?':>8}")
    print(hdr)
    print("-" * len(hdr))
    for label, ea, ma, eb, mb in PAIRS:
        any_row = False
        for sc, run_dir in SCENARIOS:
            base = run_dir / sc
            rows = []
            for seed in SEEDS:
                a = engine_tt(base, ea, ma, seed)
                b = engine_tt(base, eb, mb, seed)
                rt = _routes(base, seed)
                if a is None or b is None:
                    continue
                rows.append(compare(a, b, rt))
            if not rows:
                continue
            any_row = True
            differ = "yes" if all(r["differ"] for r in rows) else "mixed"
            print(
                f"{label:24} {sc:16} {_fmt(_mean([r['rmse'] for r in rows]),9)} "
                f"{_fmt(_mean([r['geh'] for r in rows]),6,2)} {_fmt(_mean([r['geh_pct'] for r in rows]),7)} "
                f"{_mean([r['ks'] for r in rows]):7.3f} {_mean([r['kscrit'] for r in rows]):7.3f} {differ:>8}"
            )
        if any_row:
            print()


if __name__ == "__main__":
    main()
