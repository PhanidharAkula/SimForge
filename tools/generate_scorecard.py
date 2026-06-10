#!/usr/bin/env python3
"""
Emit a single ``reproducibility_scorecard.md`` for a SimForge benchmark run.

The scorecard is a one-shot summary of *whether the run's numbers are
reproducible and fair*, meant to ship next to the per-cell artefacts and the
headline tables. It rolls up the four things a thesis defender (or a future
replicator) wants to see at a glance:

  1. Provenance: OSM PBF hashes (osm_data/manifest.json), the scenario
     bundle manifest, the git commit. Anyone re-running with these inputs
     should get the same numbers.
  2. Environment: Python and key dependency versions, SUMO + Java + OpenMP
     availability. The same content ``tools/env_report.py`` audits.
  3. Cross-engine fairness: Q1-style byte-identity of the feasibility
     verdicts across the three engines, per scenario.
  4. Reproducibility R = 1 − CV per (scenario, engine, mode) cell, read from
     the same ``benchmark_results_<runspec>.json`` that
     ``analyze_benchmark`` consumes.

It's a summary, not a re-audit: the full Q1-Q5 detail still lives in
``python -m evaluation.audit_fairness``. The scorecard stays deliberately
self-contained, with no engine-output parsing and no replays.

Usage
-----
    python -m tools.generate_scorecard <run-dir>
    python -m tools.generate_scorecard <run-dir>/<results>.json

If a directory is passed, the tool finds the single
``benchmark_results_*.json`` inside it. Output is written to
``<run-dir>/reproducibility_scorecard.md`` and the path printed to
stdout.

Closes the Thesis Plan §3.4 / §4.2 reproducibility-artefact gap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
from collections import defaultdict
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OSM_MANIFEST = REPO_ROOT / "osm_data" / "manifest.json"
SCENARIOS_DIR = REPO_ROOT / "scenarios"

_PY_DEPS = (
    "numpy", "scipy", "pandas", "lxml", "shapely", "osmium", "osmnx",
    "networkx", "matplotlib", "pytest", "eclipse-sumo", "path4gmns",
)


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _git_branch() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dep_version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _binary_version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5,
        )
        text = (out.stdout + out.stderr).strip().splitlines()
        return text[0] if text else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _resolve_results_json(arg: Path) -> Path:
    """Accept either a results JSON or the run-dir that contains one."""
    if arg.is_file():
        return arg
    if arg.is_dir():
        candidates = sorted(arg.glob("benchmark_results_*.json"))
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            sys.exit(f"No benchmark_results_*.json in {arg}")
        sys.exit(
            f"Multiple benchmark_results_*.json in {arg}; pass an explicit path."
        )
    sys.exit(f"Not a file or directory: {arg}")


def _discover_run_layout(run_dir: Path, scenario: str, engine: str,
                         mode: str, seed: int) -> Path | None:
    """Mirror of audit_fairness._find_cell_dir: the same four-layout detector."""
    candidates = [
        run_dir / f"{scenario}_{engine}_{mode}_seed{seed}" / "native_files",
        run_dir / scenario / engine / mode / f"seed_{seed}",
        run_dir / scenario / scenario / engine / mode / f"seed_{seed}",
        run_dir / engine / mode / f"seed_{seed}",
        # Pre-Phase-12 mode-less fallbacks
        run_dir / scenario / engine / f"seed_{seed}",
        run_dir / scenario / scenario / engine / f"seed_{seed}",
        run_dir / engine / f"seed_{seed}",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _collect_feasibility(run_dir: Path, results: list[dict]) -> dict:
    """Per (scenario, engine, mode) → loaded feasibility_report.json (seed 42)."""
    found: dict[tuple[str, str, str], dict] = {}
    # Derive the seeds actually present per cell from the results, rather than
    # assuming seed 42, so a runspec using a different seed is not silently
    # reported as "no feasibility found". Feasibility is seed-independent, so
    # the first seed whose report loads is enough.
    cell_seeds: dict[tuple[str, str, str], set] = {}
    for r in results:
        key = (r["scenario"], r["engine"], r["mode"])
        cell_seeds.setdefault(key, set()).add(r.get("seed", 42))
    for (sc, eng, md), seeds in cell_seeds.items():
        for seed in sorted(seeds):
            cell = _discover_run_layout(run_dir, sc, eng, md, seed=seed)
            if cell is None:
                continue
            fp = cell / "feasibility_report.json"
            if not fp.is_file():
                continue
            try:
                found[(sc, eng, md)] = json.loads(fp.read_text())
                break
            except json.JSONDecodeError:
                continue
    return found


def _scenario_provenance(scenarios: list[str]) -> dict:
    """SHA-256 of the canonical-bundle files we can find on this host."""
    out: dict[str, dict] = {}
    for sc in scenarios:
        bundle = SCENARIOS_DIR / sc
        if not bundle.is_dir():
            out[sc] = {"present": False}
            continue
        entry: dict[str, Any] = {"present": True, "files": {}}
        for name in ("network.xml", "demand.csv", "config.xml",
                     "signals.xml", "manifest.xml"):
            sha = _file_sha256(bundle / name)
            if sha is not None:
                entry["files"][name] = sha
        out[sc] = entry
    return out


def _q1_verdict(feas: dict[tuple[str, str, str], dict]) -> dict[str, str]:
    """Per-scenario: are feasibility verdicts byte-identical across engines?"""
    by_scenario: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (sc, eng, _md), rpt in feas.items():
        by_scenario[sc].append((eng, rpt))
    keys = ("feasible_trips", "total_trips", "scc_nodes", "scc_links",
            "skipped_outside_scc", "skipped_unknown_nodes",
            "skipped_missing_fields", "skipped_unsupported_mode")
    verdict: dict[str, str] = {}
    for sc, pairs in by_scenario.items():
        if len(pairs) < 2:
            verdict[sc] = "N/A (single engine)"
            continue
        first = pairs[0][1]
        same = all(
            rpt.get(k, 0) == first.get(k, 0) for _eng, rpt in pairs for k in keys
        )
        verdict[sc] = "PASS" if same else "FAIL"
    return verdict


def _r_per_cell(results: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Compute R = 1 − CV of travel_time.mean per (scenario, engine, mode)."""
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in results:
        if r.get("status") != "success":
            continue
        tt = (r.get("metrics") or {}).get("travel_time") or {}
        mean = tt.get("mean")
        if mean is None:
            continue
        grouped[(r["scenario"], r["engine"], r["mode"])].append(float(mean))
    out: dict[tuple[str, str, str], dict] = {}
    for key, values in grouped.items():
        if len(values) < 2:
            out[key] = {"n": len(values), "R": None, "mean_tt": values[0]
                        if values else None, "stdev_tt": 0.0}
            continue
        mu = statistics.mean(values)
        sigma = statistics.stdev(values)
        r_index = 1.0 - (sigma / mu) if mu else None
        out[key] = {
            "n": len(values), "R": r_index, "mean_tt": mu, "stdev_tt": sigma,
        }
    return out


def _interpret_r(r: float | None) -> str:
    if r is None:
        return "N/A"
    if r >= 0.99:
        return "EXCELLENT"
    if r >= 0.95:
        return "GOOD"
    if r >= 0.80:
        return "ACCEPTABLE"
    return "POOR"


def _render(results_json: Path) -> str:
    """Build the Markdown scorecard from the inputs."""
    payload = json.loads(results_json.read_text())
    results = payload.get("results", [])
    run_dir = results_json.parent
    runspec_name = payload.get("runspec_name", results_json.stem)

    scenarios = sorted({r["scenario"] for r in results})

    # ---------------------------------------------------------------- prov.
    git_head = _git_head() or "unknown"
    git_branch = _git_branch() or "unknown"
    osm_pbfs: dict[str, Any] = {}
    if OSM_MANIFEST.is_file():
        try:
            osm_pbfs = json.loads(OSM_MANIFEST.read_text()).get("files", {})
        except json.JSONDecodeError:
            osm_pbfs = {}
    scen_prov = _scenario_provenance(scenarios)

    # ---------------------------------------------------------------- env
    py_ver = platform.python_version()
    plat = f"{platform.system()} {platform.release()} {platform.machine()}"
    deps = {pkg: _dep_version(pkg) for pkg in _PY_DEPS}
    sumo_v = _binary_version(["sumo", "--version"])
    java_v = _binary_version(["java", "--version"])

    # ---------------------------------------------------------------- fair.
    feas = _collect_feasibility(run_dir, results)
    q1 = _q1_verdict(feas)

    # ---------------------------------------------------------------- repro.
    r_per_cell = _r_per_cell(results)
    r_values = [v["R"] for v in r_per_cell.values()
                if v["R"] is not None and v["n"] >= 2]
    overall_r = statistics.mean(r_values) if r_values else None

    # ---------------------------------------------------------------- verdict
    total = payload.get("total_runs", len(results))
    successful = payload.get("successful_runs",
                             sum(1 for r in results if r.get("status") == "success"))
    q1_fail = any(v == "FAIL" for v in q1.values())
    r_warn = any(v["R"] is not None and v["R"] < 0.80 for v in r_per_cell.values())
    if q1_fail:
        overall = "FAIL — feasibility verdict drift across engines"
    elif r_warn:
        overall = "WARN — at least one cell has R < 0.80"
    elif successful < total:
        overall = f"WARN — {total - successful}/{total} cell(s) failed"
    else:
        overall = "PASS"

    # ---------------------------------------------------------------- emit
    lines: list[str] = []
    lines.append(f"# Reproducibility Scorecard — `{runspec_name}`")
    lines.append("")
    lines.append(f"_Generated from `{results_json.name}` in `{run_dir}`._")
    lines.append("")
    lines.append(f"**Overall verdict: `{overall}`**")
    lines.append("")
    lines.append("> One-shot summary of provenance, environment, cross-engine "
                 "fairness, and reproducibility for this benchmark run. Sits "
                 "alongside `python -m evaluation.audit_fairness <run-dir>` "
                 "(full Q1–Q5 detail) and "
                 "`python -m evaluation.analyze_benchmark <results.json>` "
                 "(headline tables).")
    lines.append("")

    # 1. Provenance
    lines.append("## 1. Provenance")
    lines.append("")
    lines.append(f"- **Git HEAD:** `{git_head}` on branch `{git_branch}`")
    lines.append(f"- **OSM manifest:** `{OSM_MANIFEST.relative_to(REPO_ROOT) if OSM_MANIFEST.is_file() else 'missing'}`")
    if osm_pbfs:
        lines.append("")
        lines.append("  | PBF | SHA-256 | Size (MB) |")
        lines.append("  |---|---|---:|")
        for key, meta in sorted(osm_pbfs.items()):
            sha = (meta.get("sha256") or "")[:16] + "…"
            sz = meta.get("size_bytes", 0) // (1024 * 1024)
            lines.append(f"  | `{key}` | `{sha}` | {sz} |")
    lines.append("")
    lines.append("### Per-scenario bundle hashes")
    lines.append("")
    for sc, info in sorted(scen_prov.items()):
        if not info.get("present"):
            lines.append(f"- `{sc}` — bundle directory not present on this host (run-only artefact)")
            continue
        files = info["files"]
        lines.append(f"- `{sc}`")
        for name in ("network.xml", "demand.csv", "signals.xml",
                     "config.xml", "manifest.xml"):
            if name in files:
                lines.append(f"  - `{name}` — `{files[name][:32]}…`")
    lines.append("")

    # 2. Environment
    lines.append("## 2. Environment")
    lines.append("")
    lines.append(f"- **Platform:** `{plat}`")
    lines.append(f"- **Python:** `{py_ver}`")
    lines.append(f"- **SUMO binary:** `{sumo_v or 'not on PATH'}`")
    lines.append(f"- **Java runtime:** `{java_v or 'not on PATH'}`")
    lines.append("")
    lines.append("| Python dep | Version |")
    lines.append("|---|---|")
    for pkg, ver in deps.items():
        lines.append(f"| `{pkg}` | `{ver or 'not installed'}` |")
    lines.append("")

    # 3. Fairness (Q1 summary)
    lines.append("## 3. Cross-engine fairness (Q1 byte-identity)")
    lines.append("")
    if not feas:
        lines.append("_No `feasibility_report.json` files found under this run "
                     "directory; rerun with adapter feasibility-reports written "
                     "(default since V5)._")
    else:
        lines.append("Each adapter writes its own `feasibility_report.json` "
                     "from `adapters/common/feasibility.py`. Q1 asks: are the "
                     "verdicts byte-identical across engines for the same "
                     "scenario? Full Q1–Q5 detail: `python -m evaluation.audit_fairness`.")
        lines.append("")
        lines.append("| Scenario | Q1 verdict | Engines reporting |")
        lines.append("|---|---|---|")
        by_scenario: dict[str, list[str]] = defaultdict(list)
        for (sc, eng, _md) in feas:
            by_scenario[sc].append(eng)
        for sc in sorted({sc for (sc, _e, _m) in feas}):
            engs = sorted(set(by_scenario[sc]))
            lines.append(f"| `{sc}` | `{q1.get(sc, '?')}` | {', '.join(engs)} |")
    lines.append("")

    # 4. Reproducibility R per cell
    lines.append("## 4. Reproducibility R = 1 − CV per cell")
    lines.append("")
    if not r_per_cell:
        lines.append("_No successful cells with travel-time metrics; cannot compute R._")
    else:
        lines.append("R = 1 − σ/μ on travel_time.mean across seed reps. "
                     "≥0.99 EXCELLENT, ≥0.95 GOOD, ≥0.80 ACCEPTABLE, <0.80 POOR.")
        lines.append("")
        lines.append("| Scenario | Engine | Mode | N reps | mean TT (s) | σ (s) | R | Verdict |")
        lines.append("|---|---|---|---:|---:|---:|---:|---|")
        for (sc, eng, md), info in sorted(r_per_cell.items()):
            n = info["n"]
            mu = info["mean_tt"]
            sigma = info["stdev_tt"]
            r = info["R"]
            r_str = f"{r:.4f}" if isinstance(r, float) else "—"
            mu_str = f"{mu:.2f}" if mu is not None else "—"
            sigma_str = f"{sigma:.2f}" if sigma is not None else "—"
            lines.append(f"| `{sc}` | `{eng}` | `{md}` | {n} | {mu_str} | "
                         f"{sigma_str} | {r_str} | {_interpret_r(r)} |")
        if overall_r is not None:
            lines.append("")
            lines.append(f"**Overall R (mean across cells with N≥2):** "
                         f"`{overall_r:.4f}` ({_interpret_r(overall_r)})")
    lines.append("")

    # 5. Run summary
    lines.append("## 5. Run summary")
    lines.append("")
    lines.append(f"- **Total cells:** {total}")
    lines.append(f"- **Successful:** {successful}")
    lines.append(f"- **Failed:** {total - successful}")
    failed = [r for r in results if r.get("status") != "success"]
    if failed:
        lines.append("")
        lines.append("### Failed cells")
        lines.append("")
        lines.append("| Scenario | Engine | Mode | Seed | Error (truncated) |")
        lines.append("|---|---|---|---:|---|")
        for r in failed:
            msg = (r.get("error_message") or "").splitlines()[0][:72]
            lines.append(f"| `{r['scenario']}` | `{r['engine']}` | "
                         f"`{r['mode']}` | {r['seed']} | {msg} |")
    lines.append("")

    # 6. Footer
    lines.append("---")
    lines.append("")
    lines.append("_Scorecard schema v1 — see `tools/generate_scorecard.py`._")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit reproducibility_scorecard.md for a SimForge run",
    )
    parser.add_argument(
        "target", type=Path,
        help="Either a benchmark_results_*.json or a run directory containing one",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output path (default: <run-dir>/reproducibility_scorecard.md)",
    )
    args = parser.parse_args()

    results_json = _resolve_results_json(args.target)
    out_path = args.output or (results_json.parent / "reproducibility_scorecard.md")
    out_path.write_text(_render(results_json))
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
