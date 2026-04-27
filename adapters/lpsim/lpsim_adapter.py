"""
LPSim Adapter for SimForge.

LPSim (https://github.com/Xuan-1998/LPSim, MIT) is the GPU-accelerated
mesoscopic traffic simulator that fills the plan's 3rd-engine slot
(QarSUMO was dropped in Version_4 — see todo.md). The native binary is
``LivingCity/LivingCity``, built from the LPSim repo or pulled from the
``yibo123/lpsim:cuda12.4`` Docker image.

LPSim's input contract (cross-checked against
``LivingCity/roadGraphB2018Loader.cpp``):

  * ``nodes.csv`` columns: ``osmid, x, y, highway, index``
  * ``edges.csv`` columns: ``uniqueid, u, v, length, lanes, speed_mph``
                           (we also emit ``osmid_u, osmid_v`` for parity
                           with the bundled berkeley_2018 sample)
  * OD demand CSV columns: ``PERNO, origin, destination``  — note LPSim
    does **not** read per-trip departure times; the ``START_HR/END_HR``
    range in ``command_line_options.ini`` defines the global window and
    LPSim distributes departures inside it.
  * ``command_line_options.ini``: ``[General]`` section with
    ``NETWORK_PATH``, ``OD_DEMAND_FILENAME``, ``START_HR``, ``END_HR``,
    ``USE_CPU``, ``NUM_PASSES``, etc.

LPSim writes one row per simulated person to ``<NUM_PASSES>_people<...>``
with columns ``p, init_intersection, end_intersection, time_departure,
num_steps, travel_time, distance`` — that file is the SimForge fidelity
hook (mean / P95 travel time).

Usage::

    from adapters.lpsim import prepare_lpsim_inputs, run_lpsim
    prepare_lpsim_inputs("scenarios/chicago_1k_car", "out/lpsim")
    success, runtime, error = run_lpsim("out/lpsim")
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging

from adapters.common import feasibility as _feasibility
from adapters.sumo.sumo_adapter import (
    CanonicalLink,
    CanonicalNode,
    NetworkGraph,
    ScenarioSummary,
    parse_canonical_network,
    summarize_scenario,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


# 1 m/s ≈ 2.23694 mph. LPSim's edge schema is mph; canonical is m/s.
_MS_TO_MPH = 2.23693629


@dataclass
class LPSimConfig:
    """Subset of ``command_line_options.ini`` that SimForge controls."""

    use_cpu: bool = False                # USE_CPU=false → run on GPU
    use_sp_routing: bool = True          # USE_SP_ROUTING=true (Dijkstra-style SP)
    use_johnson_routing: bool = False    # USE_JOHNSON_ROUTING=false
    use_prev_paths: bool = False         # USE_PREV_PATHS=false (don't reuse cache)
    add_random_people: bool = False      # ADD_RANDOM_PEOPLE=false
    limit_num_people: int = 0            # 0 → no cap (uses every demand row)
    num_passes: int = 1                  # NUM_PASSES — single pass = comparable
                                         #              to SUMO/MATSim single-iter
    time_step_s: float = 0.5             # TIME_STEP simulation tick
    show_benchmarks: bool = False        # SHOW_BENCHMARKS=false
    reroute_increment: int = 0           # REROUTE_INCREMENT=0 (no mid-sim reroute)

    def to_dict(self) -> dict:
        return {
            "use_cpu": self.use_cpu,
            "use_sp_routing": self.use_sp_routing,
            "use_johnson_routing": self.use_johnson_routing,
            "use_prev_paths": self.use_prev_paths,
            "limit_num_people": self.limit_num_people,
            "num_passes": self.num_passes,
            "time_step_s": self.time_step_s,
        }


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def find_lpsim_binary() -> Optional[Path]:
    """Locate the LPSim ``LivingCity`` binary, in priority order.

    1. ``LPSIM_BINARY`` env var (explicit override).
    2. ``$HOME/lpsim/LivingCity/LivingCity`` — the layout produced by
       ``cluster/jobs/build_lpsim.sbatch`` when building from source.
    3. ``$HOME/lpsim/LivingCity`` — alternative layout if the binary
       lives one level shallower.
    4. ``LivingCity`` on ``PATH``.

    Returns ``None`` if nothing is found; ``run_lpsim`` will then surface
    an actionable error with a build pointer.
    """
    explicit = os.environ.get("LPSIM_BINARY")
    if explicit and Path(explicit).is_file() and os.access(explicit, os.X_OK):
        return Path(explicit)

    home = Path.home()
    candidates = [
        home / "lpsim" / "LivingCity" / "LivingCity",
        home / "lpsim" / "LivingCity",
        Path("LivingCity"),
    ]
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand

    on_path = shutil.which("LivingCity")
    return Path(on_path) if on_path else None


def find_lpsim_singularity_image() -> Optional[Path]:
    """Locate a Singularity ``.sif`` image of LPSim, if pulled.

    The ``build_lpsim.sbatch`` job pulls
    ``docker://yibo123/lpsim:cuda12.4`` to ``$HOME/lpsim/lpsim.sif``.
    Returns ``None`` if no such image is staged.
    """
    sif = Path.home() / "lpsim" / "lpsim.sif"
    return sif if sif.is_file() else None


# ---------------------------------------------------------------------------
# Index helpers — canonical "n123" / "l456" → LPSim integer indices
# ---------------------------------------------------------------------------


_NODE_INT_RE = re.compile(r"^[a-zA-Z]*(\d+)$")


def _to_int_index(canonical_id: str) -> int:
    """Strip the canonical prefix (``n`` / ``l``) and return the integer.

    Canonical IDs are always ``n<int>`` / ``l<int>`` per
    ``pipeline.network.build_network_from_osm.extract_canonical_network``.
    Falling back to the raw int (no prefix) keeps the helper tolerant of
    older bundles or hand-rolled fixtures used in tests.
    """
    m = _NODE_INT_RE.match(canonical_id)
    if not m:
        raise ValueError(
            f"Cannot map canonical id {canonical_id!r} to an integer LPSim "
            f"index — expected pattern '<prefix><int>' (e.g. 'n42', 'l17')."
        )
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Input writers
# ---------------------------------------------------------------------------


def write_lpsim_nodes_csv(graph: NetworkGraph, out_path: Path) -> int:
    """Write LPSim ``nodes.csv``. Returns row count.

    Schema (from ``roadGraphB2018Loader.cpp:116-119``):
        osmid, x, y, highway, index
    """
    sorted_nodes = sorted(graph.nodes.values(), key=lambda n: _to_int_index(n.id))
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["osmid", "x", "y", "highway", "index"])
        for node in sorted_nodes:
            idx = _to_int_index(node.id)
            # `highway` is the OSM tag (traffic_signals etc.). Canonical
            # network.xml doesn't preserve it; an empty string is the
            # documented "untagged" value LPSim's loader accepts.
            w.writerow([idx, f"{node.x:.6f}", f"{node.y:.6f}", "", idx])
    return len(sorted_nodes)


def write_lpsim_edges_csv(graph: NetworkGraph, out_path: Path) -> int:
    """Write LPSim ``edges.csv``. Returns row count.

    Schema (from ``roadGraphB2018Loader.cpp:216-221``):
        uniqueid, u, v, length, lanes, speed_mph
    We additionally write ``osmid_u, osmid_v`` for parity with the
    bundled ``berkeley_2018`` sample edges.csv — LPSim ignores them but
    downstream analysis scripts in the LPSim repo rely on them.

    Self-loops (u == v) are dropped: the canonical SCC also drops them
    and SUMO 1.26 refuses to convert them — keeping the LPSim adapter
    consistent with the rest of the pipeline.
    """
    rows = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uniqueid", "osmid_u", "osmid_v", "u", "v",
                    "length", "lanes", "speed_mph"])
        # Sort for determinism — adapter outputs must be byte-identical
        # across re-runs (see test_adapter_determinism).
        for link in sorted(graph.links, key=lambda lk: _to_int_index(lk.id)):
            if link.from_node == link.to_node:
                continue
            uid = _to_int_index(link.id)
            u = _to_int_index(link.from_node)
            v = _to_int_index(link.to_node)
            speed_mph = link.speed * _MS_TO_MPH
            lanes = max(int(link.lanes), 1)
            w.writerow([uid, u, v, u, v,
                        f"{link.length:.2f}", lanes, f"{speed_mph:.1f}"])
            rows += 1
    return rows


def write_lpsim_demand_csv(
    demand_path: Path,
    out_path: Path,
    feasible_trip_ids: set,
) -> int:
    """Write LPSim OD demand CSV. Returns row count.

    Schema (from ``roadGraphB2018Loader.cpp:319-321``):
        PERNO, origin, destination

    Only feasible trips (per the cross-engine SCC filter) are emitted —
    matches the SUMO and MATSim adapters so every engine simulates the
    same trip set.

    LPSim does not consume per-trip departure times; departure spread is
    governed by ``START_HR`` / ``END_HR`` in the .ini. The canonical
    ``departure_time_s`` is therefore intentionally dropped.
    """
    written = 0
    with out_path.open("w", encoding="utf-8", newline="") as out_f:
        w = csv.writer(out_f)
        w.writerow(["PERNO", "origin", "destination"])
        with demand_path.open(encoding="utf-8", newline="") as in_f:
            reader = csv.DictReader(in_f)
            # Sort for deterministic output (see test_adapter_determinism).
            rows = sorted(reader, key=lambda r: (r.get("trip_id") or ""))
            for row in rows:
                trip_id = (row.get("trip_id") or "").strip()
                if trip_id not in feasible_trip_ids:
                    continue
                origin = (row.get("origin_node_id") or "").strip()
                dest = (row.get("destination_node_id") or "").strip()
                if not origin or not dest:
                    continue
                try:
                    o_idx = _to_int_index(origin)
                    d_idx = _to_int_index(dest)
                except ValueError:
                    # An origin/dest that isn't canonical-format gets
                    # skipped rather than crashing the whole bundle —
                    # surfaces as a low completion count downstream.
                    continue
                w.writerow([trip_id, o_idx, d_idx])
                written += 1
    return written


def _hours_from_seconds(seconds: int) -> int:
    """Floor-divide seconds-since-midnight → hour-of-day (0–24).

    LPSim's ``START_HR``/``END_HR`` are integer hours. We round towards
    the morning peak (floor on START_HR, ceil on END_HR) so the canonical
    7:30 AM trip survives a 7-hr → 8-hr window.
    """
    return max(0, min(24, seconds // 3600))


def write_lpsim_ini(
    out_path: Path,
    network_dir_name: str,
    od_demand_filename: str,
    summary: ScenarioSummary,
    config: LPSimConfig,
) -> None:
    """Write ``command_line_options.ini`` next to the LivingCity binary.

    Mirrors the format LPSim's ``LC_main.cpp`` reads (a Qt .ini file
    with a ``[General]`` section). All keys SimForge sets are listed
    explicitly so a defender can audit every parameter.
    """
    start_hr = _hours_from_seconds(summary.start_time_s)
    # Ceil END_HR so the last trip in the canonical window has a chance
    # to depart even if start_time_s and end_time_s sit on a 30-min mark.
    end_seconds = summary.end_time_s
    end_hr = (end_seconds + 3599) // 3600
    end_hr = max(start_hr + 1, min(24, end_hr))

    lines = [
        "[General]",
        "GUI=false",
        f"USE_CPU={'true' if config.use_cpu else 'false'}",
        f"NETWORK_PATH={network_dir_name}/",
        f"USE_JOHNSON_ROUTING={'true' if config.use_johnson_routing else 'false'}",
        f"USE_SP_ROUTING={'true' if config.use_sp_routing else 'false'}",
        f"USE_PREV_PATHS={'true' if config.use_prev_paths else 'false'}",
        f"LIMIT_NUM_PEOPLE={config.limit_num_people}",
        f"ADD_RANDOM_PEOPLE={'true' if config.add_random_people else 'false'}",
        f"NUM_PASSES={config.num_passes}",
        f"TIME_STEP={config.time_step_s}",
        f"START_HR={start_hr}",
        f"END_HR={end_hr}",
        f"OD_DEMAND_FILENAME={od_demand_filename}",
        f"SHOW_BENCHMARKS={'true' if config.show_benchmarks else 'false'}",
        f"REROUTE_INCREMENT={config.reroute_increment}",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level prepare
# ---------------------------------------------------------------------------


def prepare_lpsim_inputs(
    scenario_path: Path,
    output_dir: Path,
    config: Optional[LPSimConfig] = None,
) -> ScenarioSummary:
    """Convert a canonical scenario bundle into LPSim's input layout.

    Layout written under ``output_dir``::

        output_dir/
        ├── command_line_options.ini   ← read by LivingCity from CWD
        ├── network/
        │   ├── nodes.csv
        │   └── edges.csv
        └── od_demand.csv

    Returns the same :class:`ScenarioSummary` shape the SUMO/MATSim
    adapters return so the harness can stay engine-agnostic.
    """
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = config or LPSimConfig()

    network_path = scenario_path / "network.xml"
    demand_path = scenario_path / "demand.csv"
    if not network_path.is_file():
        raise FileNotFoundError(f"missing canonical network.xml at {network_path}")
    if not demand_path.is_file():
        raise FileNotFoundError(f"missing canonical demand.csv at {demand_path}")

    summary = summarize_scenario(scenario_path)
    graph = parse_canonical_network(network_path)

    # Cross-engine feasibility filter — same one SUMO and MATSim use,
    # ensures every engine simulates exactly the same trip subset.
    feasible, feas_report = _feasibility.feasible_trip_ids(network_path, demand_path)
    _feasibility.log_report(feas_report, engine="lpsim")
    _feasibility.write_feasibility_report(
        feas_report, output_dir / "feasibility_report.json"
    )

    # Network: drop into a sub-folder so NETWORK_PATH points at it cleanly.
    network_dir = output_dir / "network"
    network_dir.mkdir(parents=True, exist_ok=True)
    nodes_written = write_lpsim_nodes_csv(graph, network_dir / "nodes.csv")
    edges_written = write_lpsim_edges_csv(graph, network_dir / "edges.csv")
    demand_written = write_lpsim_demand_csv(
        demand_path, network_dir / "od_demand.csv", feasible
    )

    # The .ini sits next to the LivingCity binary at run time. Emitting
    # it under output_dir lets the run step set CWD to output_dir and
    # find it without further wiring.
    write_lpsim_ini(
        output_dir / "command_line_options.ini",
        network_dir_name="network",
        od_demand_filename="od_demand.csv",
        summary=summary,
        config=config,
    )

    logger.info(
        "LPSim inputs ready at %s — %d nodes, %d edges, %d trips",
        output_dir, nodes_written, edges_written, demand_written,
    )

    return ScenarioSummary(
        scenario_id=summary.scenario_id,
        node_count=nodes_written,
        link_count=edges_written,
        trip_count=demand_written,
        has_signals=summary.has_signals,
        start_time_s=summary.start_time_s,
        end_time_s=summary.end_time_s,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_lpsim(
    output_dir: Path,
    timeout_s: int = 3600,
    use_singularity: bool = True,
) -> tuple[bool, float, Optional[str]]:
    """Invoke LPSim's ``LivingCity`` binary in ``output_dir``.

    LPSim has no command-line flags — it reads
    ``command_line_options.ini`` from the current working directory and
    writes its ``<NUM_PASSES>_people.csv`` output there. We therefore
    ``cd`` into ``output_dir`` for the subprocess call.

    Resolution order:
      1. If a Singularity image exists at ``$HOME/lpsim/lpsim.sif`` and
         ``use_singularity=True``, run via ``singularity exec --nv``.
      2. Otherwise, look up the native binary via :func:`find_lpsim_binary`.
      3. If neither is available, return a clean failure with build
         pointer.

    Returns ``(success, runtime_seconds, error_message)``.
    """
    output_dir = Path(output_dir).resolve()
    if not (output_dir / "command_line_options.ini").is_file():
        return False, 0.0, (
            f"command_line_options.ini missing in {output_dir} — "
            f"call prepare_lpsim_inputs first."
        )

    sif: Optional[Path] = (
        find_lpsim_singularity_image() if use_singularity else None
    )
    binary = find_lpsim_binary()

    if sif is not None and shutil.which("singularity"):
        # The yibo123/lpsim:cuda12.4 image ships the LivingCity binary at the
        # absolute path /LivingCity/LivingCity and does NOT add it to $PATH.
        # We therefore invoke it by full path; configurable via env var for
        # future images that might land it elsewhere.
        in_container_binary = os.environ.get(
            "LPSIM_CONTAINER_BINARY", "/LivingCity/LivingCity"
        )
        cmd = ["singularity", "exec", "--nv"]

        # CUDA 11.x runtime injection.
        # The yibo123/lpsim:cuda12.4 image is mis-tagged: its installed CUDA
        # toolkit is 12.4, but the bundled LivingCity binary was compiled
        # against libcudart.so.11.0. We therefore need a CUDA 11.x runtime
        # available inside the container. On Pitzer:
        #   module load cuda/11.8.0     # exposes /apps/.../cuda-11.8.0/lib64
        # Apptainer / Singularity:
        #   * does NOT auto-mount /apps (host modules dir) — needs --bind
        #   * does NOT inherit the host's LD_LIBRARY_PATH — needs --env
        # We therefore bind /apps and explicitly point LD_LIBRARY_PATH at the
        # host CUDA 11 lib dir, while preserving the container's own CUDA 12.4
        # / pandana / driver-lib paths after it.
        cuda_home = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
        if cuda_home and (Path(cuda_home) / "lib64" / "libcudart.so.11.0").is_file():
            cmd.extend(["--bind", "/apps"])
            ld_library_path = ":".join([
                f"{cuda_home}/lib64",
                "/usr/local/cuda-12.4/lib64",
                "/usr/include/pandana/src",
                "/.singularity.d/libs",
            ])
            cmd.extend(["--env", f"LD_LIBRARY_PATH={ld_library_path}"])
            logger.info("LPSim: bound /apps + injected CUDA 11 runtime from %s", cuda_home)
        else:
            logger.warning(
                "LPSim: CUDA 11.x runtime not detected on host. "
                "Run `module load cuda/11.8.0` on Pitzer before launching — "
                "the LPSim binary needs libcudart.so.11.0 which the container "
                "(CUDA 12.4) does not provide."
            )

        # Bind the output dir into the container at the same path AND set
        # --pwd so LPSim reads our command_line_options.ini instead of the
        # bundled berkeley_2018 sample at /command_line_options.ini.
        # Apptainer 1.3.6 does NOT inherit the host's CWD even when
        # subprocess.run(cwd=...) is set, and may not auto-mount the parent
        # of `output_dir` (e.g. /tmp on some OSC nodes). Belt-and-braces.
        output_str = str(output_dir)
        cmd.extend(["--bind", output_str, "--pwd", output_str])

        cmd.extend([str(sif), in_container_binary])
        binary_label = f"singularity://{sif.name}!{in_container_binary}"
    elif binary is not None:
        cmd = [str(binary)]
        binary_label = str(binary)
    else:
        return False, 0.0, (
            "LPSim binary not found. Build once on a Pitzer GPU node:\n"
            "  sbatch cluster/jobs/build_lpsim.sbatch\n"
            "  (puts LivingCity at $HOME/lpsim/LivingCity/LivingCity)\n"
            "Or set LPSIM_BINARY=/path/to/LivingCity to override."
        )

    logger.info("Running LPSim: %s  (cwd=%s)", " ".join(cmd), output_dir)
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        elapsed = time.time() - start
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error")[:500]
            return False, elapsed, f"LPSim ({binary_label}) exit {result.returncode}: {err}"
        return True, elapsed, None
    except subprocess.TimeoutExpired:
        return False, time.time() - start, f"LPSim timeout after {timeout_s}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, time.time() - start, f"LPSim failed to launch: {exc}"


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


_PEOPLE_FILE_RE = re.compile(r"^(\d+)_people.*\.csv$")


def _find_people_csv(output_dir: Path) -> Optional[Path]:
    """Locate LPSim's ``<numOfPass>_people<...>.csv`` output.

    LPSim names this file ``<NUM_PASSES>_people<timestamp>.csv`` —
    version-dependent suffixes (e.g. ``_5to12``) appear in the wild.
    Match the canonical prefix and pick the lexicographically last (i.e.
    highest-pass) file so multi-pass runs return the final iteration.
    """
    candidates: list[Path] = []
    for child in output_dir.iterdir():
        if child.is_file() and _PEOPLE_FILE_RE.match(child.name):
            candidates.append(child)
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1]


@dataclass
class LPSimTripStats:
    trip_count: int
    completed_count: int
    mean_travel_time_s: float
    p95_travel_time_s: float
    mean_distance_m: float


def parse_lpsim_output(output_dir: Path) -> Optional[LPSimTripStats]:
    """Parse LPSim's ``*_people.csv`` into shared travel-time stats.

    Schema (from ``b18TrafficSimulator::writePeopleFile``):
        p, init_intersection, end_intersection, time_departure,
        num_steps, travel_time, distance

    A trip is considered *completed* iff its ``travel_time > 0`` —
    LPSim leaves zeros (or negative sentinels in some forks) on
    abandoned trips. Returns ``None`` if no output file is found, so
    the harness can record a clean failure instead of crashing.
    """
    people_csv = _find_people_csv(Path(output_dir))
    if people_csv is None:
        return None

    travel_times: list[float] = []
    distances: list[float] = []
    total = 0
    with people_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            try:
                tt = float(row.get("travel_time", "0") or 0)
                dist = float(row.get("distance", "0") or 0)
            except ValueError:
                continue
            if tt > 0:
                travel_times.append(tt)
                distances.append(dist)

    if not travel_times:
        return LPSimTripStats(
            trip_count=total,
            completed_count=0,
            mean_travel_time_s=0.0,
            p95_travel_time_s=0.0,
            mean_distance_m=0.0,
        )

    travel_times.sort()
    p95_idx = max(0, int(0.95 * (len(travel_times) - 1)))
    return LPSimTripStats(
        trip_count=total,
        completed_count=len(travel_times),
        mean_travel_time_s=statistics.mean(travel_times),
        p95_travel_time_s=travel_times[p95_idx],
        mean_distance_m=statistics.mean(distances) if distances else 0.0,
    )
