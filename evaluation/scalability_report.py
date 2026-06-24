"""Scalability metrics (SRT, throughput, per-core) for RQ2.

Wires evaluation.metrics.scalability.compute_scalability_metrics to the
benchmark JSONs. The harness records the engine runtime and the completed-trip
count; the simulated horizon comes from each scenario's config window and the
per-core figure normalizes by the 16-core Pitzer worker allocation.

Usage:  python -m evaluation.scalability_report
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

from evaluation.metrics.scalability import compute_scalability_metrics, HardwareInfo

CORES = 16  # --cpus-per-task=16 (Pitzer worker)
HORIZON_S = {  # end_time_s - start_time_s from each scenario's config.xml
    "chicago_1k_car": 3600,
    "nyc_10k_car": 7200,
    "la_50k_car": 14400,
    "chicago_200k_car": 86400,
    "nyc_500k_car": 14400,
}
RUNSPECS = [
    Path("runs/benchmark_small/benchmark_results_benchmark_small.json"),
    Path("runs/benchmark_large/benchmark_results_benchmark_large.json"),
]
ORDER = list(HORIZON_S)


def cells(path: Path):
    if not path.exists():
        return
    d = json.load(open(path))
    by: dict = {}
    for r in d.get("results", []):
        if r.get("status") != "success":
            continue
        rt = r.get("engine_wall_s") or r.get("runtime_s")
        tc = r.get("metrics", {}).get("travel_time", {}).get("trip_count")
        if rt and tc:
            by.setdefault((r["scenario"], r["engine"], r["mode"]), []).append((rt, tc))
    for (sc, eng, mode), vals in by.items():
        yield sc, eng, mode, st.mean(v[0] for v in vals), st.mean(v[1] for v in vals)


def main() -> None:
    hw = HardwareInfo()
    hw.cpu_cores = CORES
    print(f"Scalability (RQ2): SRT, throughput, per-core (cores={CORES}), 5-seed mean\n")
    hdr = (f"{'scenario':16} {'engine':8} {'mode':6} {'runtime(s)':>11} "
           f"{'thr(trips/s)':>13} {'per-core':>9} {'SRT':>8}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for rp in RUNSPECS:
        for sc, eng, mode, rt, tc in cells(rp):
            m = compute_scalability_metrics(rt, HORIZON_S.get(sc, 0), round(tc), hw)
            rows.append((sc, eng, mode, rt, m))
    rows.sort(key=lambda r: (ORDER.index(r[0]) if r[0] in ORDER else 99, r[1], r[2]))
    for sc, eng, mode, rt, m in rows:
        print(f"{sc:16} {eng:8} {mode:6} {rt:11.2f} {m.trips_per_second:13.1f} "
              f"{m.trips_per_second_per_core:9.1f} {m.simulated_to_realtime_ratio:6.0f}x")


if __name__ == "__main__":
    main()
