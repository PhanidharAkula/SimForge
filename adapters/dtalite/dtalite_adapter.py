"""
DTALite adapter for SimForge.

DTALite is an open-source C++ mesoscopic dynamic-traffic-assignment engine,
shipped as a bundled binary inside the `path4gmns` Python package
(https://github.com/jdlph/Path4GMNS). It took the third-engine slot in the
Version_5 matrix once LPSim was abandoned (the story is in
`doc/engines/LPSIM_RETROSPECTIVE.md`).

It speaks GMNS (the General Modeling Network Specification):

  * ``node.csv``: ``node_id, x_coord, y_coord, zone_id``
  * ``link.csv``: ``link_id, from_node_id, to_node_id, length, lanes,
                   capacity, free_speed, link_type, VDF_*``
  * ``demand.csv``: ``o_zone_id, d_zone_id, volume``
  * ``settings.yml``: agents, demand periods, demand files

DTALite is CPU-only, deterministic, and runs natively on Mac (arm64 and
x86_64), Linux x86_64, and Windows. ctypes picks the right bundled binary
from path4gmns/bin/ at run time. On Mac you need the OpenMP runtime:
``brew install libomp``.

What it writes into the run directory:

  * ``link_performance.csv``: per-link volume, travel time (min), VOC
  * ``agent.csv``: per-agent path_id, volume, travel time (min),
                   distance (km), node and link sequences
  * ``od_performance.csv``, ``log_main.txt``, ``log_DTA.txt``

One thing to watch: DTALite measures length in kilometres and speed in
km/h, while the canonical schema is meters and m/s, so the writers below
convert at the boundary. DTALite's travel times come out in minutes, and
``parse_dtalite_output`` turns them back into seconds for the shared
TripStats schema.

Usage::

    from adapters.dtalite import prepare_dtalite_inputs, run_dtalite
    prepare_dtalite_inputs("scenarios/chicago_1k_car", "out/dtalite")
    success, runtime, error = run_dtalite("out/dtalite")
"""

from __future__ import annotations

import csv
import logging
import math
import platform
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapters.common import feasibility as _feasibility
from adapters.common.vehicle_types import CAR_PCE as _CAR_PCE
from adapters.sumo.sumo_adapter import (
    NetworkGraph,
    ScenarioSummary,
    parse_canonical_network,
    summarize_scenario,
)
from pipeline.network.scc import compute_largest_scc


def _import_path4gmns():
    """Import path4gmns quietly.

    Its __init__.py prints `path4gmns, version 0.10.0` to stdout on import,
    every time, with no way to turn it off. We swallow that one line by
    redirecting stdout just for the import. After the first call the module
    is cached, so the cost is paid once per process.

    Returns the path4gmns module, or raises ImportError if it's missing.
    """
    import io
    saved = sys.stdout
    sys.stdout = io.StringIO()
    try:
        import path4gmns as pg
        return pg
    finally:
        sys.stdout = saved


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unit conversions: canonical (m, m/s) -> GMNS (km, km/h)
# ---------------------------------------------------------------------------

_M_TO_KM = 1.0 / 1000.0
_MS_TO_KMH = 3.6  # 1 m/s = 3.6 km/h
_MIN_TO_SEC = 60.0
_KM_TO_M = 1000.0

# DTALite's GMNS link.csv loader won't take zero-length links. The canonical
# extract already drops length<=0 (see pipeline/network/build_network_from_osm.py),
# but a few sub-meter edges slip through, so floor to 1 m and DTA's free-flow
# time (length/free_speed) stays non-zero on every link.
_DTALITE_MIN_EDGE_LENGTH_M = 1.0

# Default per-lane hourly capacity. GMNS doesn't carry capacity over from OSM,
# so we use the standard urban-arterial figure from the FHWA HCM (1800 vph per
# lane). DTALite's BPR VDF works realised capacity back out from this plus the
# calibrated alpha/beta.
_DEFAULT_CAPACITY_VPH_PER_LANE = 1800

# Free-flow speed floor. DTALite's BPR cost divides by free_speed, and below
# ~1 km/h that gets numerically nasty. Real road speeds are always at least
# walking pace anyway.
_DTALITE_MIN_SPEED_KMH = 5.0


@dataclass
class DTALiteConfig:
    """The part of DTALite's ``settings.yml`` that SimForge sets.

    The two knobs that matter are ``number_of_iterations`` (outer DTA
    iterations chasing user equilibrium) and
    ``number_of_column_updating_iterations`` (inner column-pool refinement
    within each outer iteration). At our scenario sizes the defaults below
    get UE under a 1% gap in well under a minute.
    """

    iterations: int = 5
    column_updating_iterations: int = 5
    # 0 = assignment only; 1 = also write per-link and per-agent performance.
    # We need the per-agent output for travel-time stats.
    simulation_output: int = 1
    # Demand period (4-digit, 24-hour clock). It has to span every trip's
    # departure_time; the 0700-0800 default matches the bundled scenarios'
    # morning-peak focus.
    demand_period_start_hhmm: str = "0700"
    demand_period_end_hhmm: str = "0800"

    # NOTE: DTALite Classic (the stable path4gmns 0.10.0 entry point we drive,
    # see run_dtalite) takes only (assignment_mode, column_gen_num,
    # column_upd_num) and its settings.csv [assignment] section has no column
    # for a UE convergence percent or a CPU-processor count. Earlier versions
    # of this config carried ue_convergence_percent and number_of_cpu_processors
    # fields, but nothing ever wrote them to a file the binary reads, so they
    # were silently ignored. They have been dropped to avoid implying control
    # the engine doesn't expose here.

    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "column_updating_iterations": self.column_updating_iterations,
            "simulation_output": self.simulation_output,
            "demand_period_start_hhmm": self.demand_period_start_hhmm,
            "demand_period_end_hhmm": self.demand_period_end_hhmm,
        }


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def is_dtalite_available() -> bool:
    """True when path4gmns imports and its bundled binary is actually there.

    The binary is platform-specific (arm.dylib / x86.dylib on Mac, .so on
    Linux, .dll on Windows), and path4gmns's ctypes loader picks the right
    one at run time. We also confirm the file exists, in case pip's wheel
    shipped a broken layout.
    """
    try:
        _import_path4gmns()
    except ImportError:
        return False
    return find_dtalite_binary() is not None


def find_dtalite_binary() -> Optional[Path]:
    """Find the bundled DTALiteMM binary for this platform.

    Returns the .so / .dylib / .dll that path4gmns will dlopen at run time.
    ``tools/env_report.py`` uses this to show which binary will run;
    ``run_dtalite`` doesn't, since it lets path4gmns pick.

    Returns None if path4gmns isn't installed or the binary for this
    platform isn't in the package.
    """
    try:
        pg = _import_path4gmns()
    except ImportError:
        return None
    bin_dir = Path(pg.__file__).parent / "bin"
    if not bin_dir.is_dir():
        return None
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        # Mac: arm64 wants DTALiteMM_arm.dylib, x86_64 wants DTALiteMM_x86.dylib.
        suffix = "arm" if machine in ("arm64", "aarch64") else "x86"
        cand = bin_dir / f"DTALiteMM_{suffix}.dylib"
    elif system == "Linux":
        cand = bin_dir / "DTALiteMM.so"
    elif system == "Windows":
        cand = bin_dir / "DTALiteMM.dll"
    else:
        return None
    return cand if cand.is_file() else None


# ---------------------------------------------------------------------------
# Index helpers: canonical "n123" / "l456" -> GMNS integer node/link IDs
# ---------------------------------------------------------------------------


_NODE_INT_RE = re.compile(r"^[a-zA-Z]*(\d+)$")


def _to_int_index(canonical_id: str) -> int:
    """Strip canonical prefix and return integer; reject malformed IDs.

    DTALite/GMNS uses integer node/link IDs. Canonical IDs are
    ``n<int>`` / ``l<int>`` per the SimForge schema. Tolerates a raw
    integer for hand-rolled fixtures.
    """
    m = _NODE_INT_RE.match(canonical_id)
    if not m:
        raise ValueError(
            f"Cannot map canonical id {canonical_id!r} to an integer DTALite "
            f"index — expected pattern '<prefix><int>' (e.g. 'n42', 'l17')."
        )
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Input writers
# ---------------------------------------------------------------------------


def write_dtalite_node_csv(
    graph: NetworkGraph,
    out_path: Path,
    zone_node_ids: Optional[set] = None,
) -> int:
    """Write GMNS ``node.csv``. Returns row count.

    Schema (from path4gmns sample networks + GMNS spec):
        ``name, node_id, zone_id, node_type, control_type,
          x_coord, y_coord, geometry, production, attraction``

    DTALite's UE assignment iterates over **zones** (Traffic Analysis
    Zones), running label-correcting shortest-path from each zone in
    every outer iteration. With one zone per intersection on a 20k-node
    network that's 20k × outer_iters shortest-path calls per run, which
    is intractable.

    SimForge therefore assigns ``zone_id`` ONLY to nodes that appear as
    an origin or destination in the demand. Pure transit intersections
    keep ``zone_id`` empty so DTALite skips them in the UE loop while
    still using them for path reconstruction. For chicago_1k_car this
    drops the zone count from 20,058 to ~1,800.

    ``zone_node_ids`` is the set of canonical node IDs that should be
    promoted to zones; pass ``None`` to make every node a zone (only
    sane for tiny test fixtures).
    """
    sorted_nodes = sorted(graph.nodes.values(), key=lambda n: _to_int_index(n.id))
    seen_idx: dict[int, str] = {}
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "name", "node_id", "zone_id", "node_type", "control_type",
            "x_coord", "y_coord", "geometry", "production", "attraction",
        ])
        for node in sorted_nodes:
            idx = _to_int_index(node.id)
            # Canonical ids strip their prefix to a GMNS integer, so two ids
            # that differ only in prefix (or by zero-padding) would collide to
            # the same node_id and silently emit conflicting rows. Fail loudly.
            if idx in seen_idx:
                raise ValueError(
                    f"DTALite node_id collision: canonical ids {seen_idx[idx]!r} "
                    f"and {node.id!r} both map to integer {idx}."
                )
            seen_idx[idx] = node.id
            is_zone = zone_node_ids is None or node.id in zone_node_ids
            zone_cell = idx if is_zone else ""
            production = 1 if is_zone else 0
            attraction = 1 if is_zone else 0
            w.writerow([
                "", idx, zone_cell, "", "",
                f"{node.x:.6f}", f"{node.y:.6f}",
                "", production, attraction,
            ])
    return len(sorted_nodes)


def collect_demand_node_ids(
    demand_path: Path,
    feasible_trip_ids: set,
) -> set:
    """Collect canonical node IDs that appear as origin or destination.

    Used to compute the zone set for ``write_dtalite_node_csv`` so
    DTALite only iterates over zones that actually carry demand. The
    same iteration over demand.csv that the demand writer does, factored
    out so prepare_dtalite_inputs can compute the zone set BEFORE
    writing nodes.
    """
    demand_nodes: set = set()
    with demand_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in feasible_trip_ids:
                continue
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            if origin:
                demand_nodes.add(origin)
            if dest:
                demand_nodes.add(dest)
    return demand_nodes


def write_dtalite_link_csv(graph: NetworkGraph, out_path: Path) -> int:
    """Write GMNS ``link.csv``. Returns row count.

    Schema (from path4gmns sample networks):
        ``name, link_id, from_node_id, to_node_id, facility_type, dir_flag,
          length, lanes, capacity, free_speed, link_type, cost,
          VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1``

    Conversions at the boundary:
      * length: canonical meters to GMNS kilometers
      * speed:  canonical m/s to GMNS km/h

    We drop self-loops (u == v) and sub-meter edges, the same filters we
    used for LPSim. Zero-length links would divide by zero in the BPR cost
    function.

    The VDF (volume delay function) parameters use the standard BPR form
    with FHWA HCM defaults: ``alpha=0.15, beta=4`` and capacity = lanes
    times 1800 vph. ``VDF_fftt1`` is the free-flow travel time in minutes
    (length_km / free_speed_kmh times 60).
    """
    rows = 0
    skipped_self = 0
    skipped_short = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "name", "link_id", "from_node_id", "to_node_id", "facility_type",
            "dir_flag", "length", "lanes", "capacity", "free_speed",
            "link_type", "cost",
            "VDF_fftt1", "VDF_cap1", "VDF_alpha1", "VDF_beta1",
        ])
        for link in sorted(graph.links, key=lambda lk: _to_int_index(lk.id)):
            if link.from_node == link.to_node:
                skipped_self += 1
                continue
            if link.length < _DTALITE_MIN_EDGE_LENGTH_M:
                skipped_short += 1
                continue
            link_id = _to_int_index(link.id)
            from_id = _to_int_index(link.from_node)
            to_id = _to_int_index(link.to_node)
            length_km = max(link.length * _M_TO_KM,
                            _DTALITE_MIN_EDGE_LENGTH_M * _M_TO_KM)
            speed_kmh = max(link.speed * _MS_TO_KMH, _DTALITE_MIN_SPEED_KMH)
            lanes = max(int(link.lanes), 1)
            capacity = lanes * _DEFAULT_CAPACITY_VPH_PER_LANE
            fftt_min = (length_km / speed_kmh) * 60.0
            w.writerow([
                "", link_id, from_id, to_id, "Highway",
                1, f"{length_km:.5f}", lanes, capacity, f"{speed_kmh:.1f}",
                1, 0,
                f"{fftt_min:.5f}", capacity, "0.15", 4,
            ])
            rows += 1
    if skipped_self:
        logger.info(
            "DTALite link.csv: dropped %d self-loop edges (BPR can't divide by zero)",
            skipped_self,
        )
    if skipped_short:
        logger.info(
            "DTALite link.csv: dropped %d sub-meter edges (would round to 0 km in GMNS)",
            skipped_short,
        )
    return rows


def write_dtalite_movement_csv(
    network_path: Path,
    out_path: Path,
) -> int:
    """Write GMNS ``movement.csv`` with OSM turn restrictions, if present.

    Schema (per zephyr-data-specs/GMNS):
        ``mvmt_id, node_id, ib_link_id, ob_link_id, type, penalty,
        capacity, ctrl_type, geometry``

    One row per ``<turn_restriction>`` in ``network.xml``. ``capacity=0``
    and ``penalty=99999`` mark the movement forbidden; most GMNS loaders
    treat either one as a hard block.

    A V5 caveat: path4gmns 0.10.0 (our DTA backend) doesn't read
    ``movement.csv`` yet, so for now this file is documentary. It keeps the
    OSM ground truth in the bundle for cross-tool conformance and later
    audits, but DTALite's UE assignment won't actually steer around the
    restricted movements. SUMO and MATSim both pre-route via the
    state-aware BFS, so they do enforce them; this is the one cross-engine
    asymmetry V5 leaves open. doc/MODELGEN_AND_MODES.md (future work) covers
    the path4gmns change that would close it.

    Returns how many movement rows were written, or 0 (quietly) when the
    network has no ``<turn_restrictions>`` block.
    """
    from pipeline.network.turn_restrictions import parse_turn_restrictions

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    restrictions = parse_turn_restrictions(network_path)
    if not restrictions:
        # Skip the file rather than write a header-only CSV, which some DTA
        # tools choke on. A missing file is unambiguous: no restrictions here.
        return 0

    # Map OSM restriction values to GMNS movement types when possible.
    # Anything not in the table emits with type=other (still valid GMNS).
    OSM_TO_GMNS_TYPE = {
        "no_left_turn": "left",
        "no_right_turn": "right",
        "no_u_turn": "u_turn",
        "no_straight_on": "thru",
        "only_left_turn": "left",
        "only_right_turn": "right",
        "only_straight_on": "thru",
    }

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "mvmt_id", "node_id", "ib_link_id", "ob_link_id",
            "type", "penalty", "capacity", "ctrl_type", "geometry",
            "osm_restriction",  # provenance, non-standard but handy
        ])
        # Sort by (via_node, from_link, to_link) for deterministic output.
        for i, r in enumerate(sorted(
            restrictions, key=lambda x: (x.via_node, x.from_link, x.to_link),
        )):
            mvmt_id = f"m{i}"
            mvmt_type = OSM_TO_GMNS_TYPE.get(r.restriction, "other")
            w.writerow([
                mvmt_id, r.via_node, r.from_link, r.to_link,
                mvmt_type, "99999", "0", "no_control", "",
                r.restriction,
            ])

    return len(restrictions)


def write_dtalite_demand_csv(
    demand_path: Path,
    out_path: Path,
    feasible_trip_ids: set,
) -> int:
    """Write GMNS ``demand.csv``. Returns row count (unique OD pairs, not trips).

    Schema: ``o_zone_id, d_zone_id, volume``.

    Rolls the per-trip demand up into (origin, destination) trip counts.
    DTALite's UE assignment reads `volume` as the OD-matrix entry in
    vehicles per demand period, and one canonical trip is one vehicle.

    Only feasible trips go in, per the cross-engine SCC filter, the same
    one SUMO and MATSim use, so every engine runs the same trip set.
    """
    od_counts: Counter = Counter()
    with demand_path.open(encoding="utf-8", newline="") as in_f:
        reader = csv.DictReader(in_f)
        for row in reader:
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
                continue
            if o_idx == d_idx:
                # Skip intra-zonal trips. DTALite calls them zero-cost, which
                # pads the agreement metric without simulating anything, and
                # SUMO and MATSim drop them too.
                continue
            od_counts[(o_idx, d_idx)] += 1
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["o_zone_id", "d_zone_id", "volume"])
        # Sort so the output is deterministic: adapter files have to be
        # byte-identical across re-runs (test_adapter_determinism checks this).
        for (o, d), volume in sorted(od_counts.items()):
            w.writerow([o, d, volume])
    return len(od_counts)


def write_dtalite_settings_yml(
    out_path: Path,
    config: DTALiteConfig,
) -> None:
    """Write DTALite ``settings.yml`` (consumed by path4gmns Python wrapper).

    Mirrors the format path4gmns's bundled samples use. Defines a single
    agent type ``a``=auto, one demand period AM, one demand file.

    NOTE: DTALite's underlying C++ binary reads its assignment / agent /
    link-type sections from ``settings.csv``, not from this YAML file.
    The two files coexist in every working path4gmns sample. See
    :func:`write_dtalite_settings_csv`.
    """
    period_window = (
        f"{config.demand_period_start_hhmm}-{config.demand_period_end_hhmm}"
    )
    yml = f"""---
# DTALite settings.yml — generated by adapters/dtalite/dtalite_adapter.py
# Do not hand-edit; regenerate via prepare_dtalite_inputs().

agents:
  - type: a
    name: auto
    vot: 10
    flow_type: 0
    pce: 1
    free_speed: 60
    use_link_ffs: true

demand_periods:
  - period: AM
    time_period: {period_window}

demand_files:
  - file_name: demand.csv
    period: AM
    agent_type: a
"""
    out_path.write_text(yml, encoding="utf-8")


def write_dtalite_settings_csv(
    out_path: Path,
    config: DTALiteConfig,
) -> None:
    """Write DTALite ``settings.csv`` (the section file the C++ binary reads).

    DTALite's C++ binary reads its assignment parameters, agent type, link
    type, demand period, and demand file list from this sectioned CSV. The
    layout is deliberately spreadsheet-friendly: a section header alone in
    one column, then a column-header row, then data rows. path4gmns's Python
    wrapper reads ``settings.yml`` instead, but the C++ binary ignores the
    YAML for these sections, so both files have to be present.

    Sections written:
      * ``[assignment]``: DTA mode, iteration counts, UE gap
      * ``[agent_type]``: a single auto agent (cars only)
      * ``[link_type]``: Highway/Expressway with type_code=f, traffic=0
      * ``[demand_period]``: a single AM period, 0700-0800
      * ``[demand_file_list]``: points at demand.csv with agent_type=p
    """
    period_window = (
        f"{config.demand_period_start_hhmm}_{config.demand_period_end_hhmm}"
    )
    rows = [
        # [assignment]
        ["[assignment]", "", "assignment_mode", "number_of_iterations",
         "column_updating_iterations", "signal_updating_iterations",
         "signal_updating_output", "remarks"],
        ["", "", "ue", config.iterations, config.column_updating_iterations,
         -1, 0, "assignment_mode can be ue, dta or odme"],
        ["", "", "", "", "", "", "", ""],
        # [agent_type]. Since V11 the PCE comes from
        # adapters/common/vehicle_types.py (CAR_PCE = 1.0). DTALite has no
        # length or width of its own; link capacity carries the storage and
        # spacing that SUMO's length+minGap and MATSim's effective length do,
        # and PCE = 1.0 lines up with both.
        ["[agent_type]", "agent_type", "name", "", "VOT", "flow_type",
         "PCE", ""],
        ["", "p", "passenger", "", 10, 0, _CAR_PCE, ""],
        ["", "", "", "", "", "", "", ""],
        # [link_type]
        ["[link_type]", "link_type", "link_type_name", "",
         "agent_type_blocklist", "type_code", "traffic_flow_code", ""],
        ["", 1, "Highway/Expressway", "", "", "f", 0, ""],
        ["", "", "", "", "", "", "", ""],
        # [demand_period]
        ["[demand_period]", "demand_period_id", "demand_period", "",
         "time_period", "", "", ""],
        ["", 1, "AM", "", period_window, "", "", ""],
        ["", "", "", "", "", "", "", ""],
        # [demand_file_list]
        ["[demand_file_list]", "file_sequence_no", "file_name", "",
         "format_type", "demand_period", "agent_type", ""],
        ["", 1, "demand.csv", "", "column", "AM", "p", ""],
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# Top-level prepare
# ---------------------------------------------------------------------------


def prepare_dtalite_inputs(
    scenario_path: Path,
    output_dir: Path,
    config: Optional[DTALiteConfig] = None,
) -> ScenarioSummary:
    """Convert a canonical scenario bundle into DTALite's GMNS layout.

    Layout written under ``output_dir``::

        output_dir/
        ├── settings.yml      ← DTALite reads this from CWD
        ├── node.csv
        ├── link.csv
        └── demand.csv

    Returns the same :class:`ScenarioSummary` shape the SUMO/MATSim
    adapters return so the harness can stay engine-agnostic.
    """
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = config or DTALiteConfig()

    network_path = scenario_path / "network.xml"
    demand_path = scenario_path / "demand.csv"
    if not network_path.is_file():
        raise FileNotFoundError(f"missing canonical network.xml at {network_path}")
    if not demand_path.is_file():
        raise FileNotFoundError(f"missing canonical demand.csv at {demand_path}")

    summary = summarize_scenario(scenario_path)
    graph = parse_canonical_network(network_path)

    # The cross-engine feasibility filter, the same one SUMO and MATSim use,
    # so every engine runs the same trip subset. DTALite is car-only by
    # design (CPU mesoscopic DTA, single-mode demand), so transit/bike/walk
    # drop out here too.
    feasible, feas_report = _feasibility.feasible_trip_ids(
        network_path, demand_path, supported_modes={"car"},
    )
    _feasibility.log_report(feas_report, engine="dtalite")
    _feasibility.write_feasibility_report(
        feas_report, output_dir / "feasibility_report.json"
    )

    # Fairness: prune to the largest SCC before writing the network. It's the
    # same filter the feasibility check uses, and the same set MATSim emits,
    # so all three engines see byte-identical node and link sets, not just
    # identical trips. Skip it and DTALite would write the full canonical
    # network, dead-ends included, while MATSim writes only the SCC, and that
    # gap would taint the cross-engine travel-time comparison.
    scc_node_ids = compute_largest_scc(
        set(graph.nodes.keys()),
        [(lk.from_node, lk.to_node) for lk in graph.links],
    )
    scc_graph = NetworkGraph(
        nodes={nid: n for nid, n in graph.nodes.items() if nid in scc_node_ids},
        links=[lk for lk in graph.links
               if lk.from_node in scc_node_ids and lk.to_node in scc_node_ids],
        adjacency={},
        edge_lookup={},
    )

    # Work out the zone set first, so write_dtalite_node_csv knows which
    # nodes to promote. DTALite's UE iteration cost is linear in the zone
    # count, so keeping only the demand-carrying nodes is the difference
    # between a 5-second and a 5-minute run on chicago_1k.
    demand_node_ids = collect_demand_node_ids(demand_path, feasible)
    nodes_written = write_dtalite_node_csv(
        scc_graph, output_dir / "node.csv", zone_node_ids=demand_node_ids
    )
    links_written = write_dtalite_link_csv(scc_graph, output_dir / "link.csv")
    od_pairs_written = write_dtalite_demand_csv(
        demand_path, output_dir / "demand.csv", feasible
    )
    # V5+: write GMNS movement.csv to carry the OSM turn-restriction
    # provenance. See write_dtalite_movement_csv for the path4gmns 0.10.0
    # caveat; the file is documentary for now, not enforced.
    movement_rows = write_dtalite_movement_csv(
        network_path, output_dir / "movement.csv",
    )
    write_dtalite_settings_yml(output_dir / "settings.yml", config)
    write_dtalite_settings_csv(output_dir / "settings.csv", config)

    if od_pairs_written == 0:
        logger.warning(
            "DTALite demand.csv for %s has zero OD pairs (%d feasible trips): "
            "DTALite would run a vacuous assignment with no travel-time output. "
            "Check the scenario's demand and feasibility filter.",
            summary.scenario_id, len(feasible),
        )

    logger.info(
        "DTALite inputs ready at %s — %d nodes, %d links, %d unique OD pairs "
        "from %d feasible trips, %d turn restrictions in movement.csv",
        output_dir, nodes_written, links_written, od_pairs_written,
        len(feasible), movement_rows,
    )

    return ScenarioSummary(
        scenario_id=summary.scenario_id,
        node_count=nodes_written,
        link_count=links_written,
        trip_count=len(feasible),  # Upstream-comparable trip count, not aggregated OD pairs
        has_signals=summary.has_signals,
        start_time_s=summary.start_time_s,
        end_time_s=summary.end_time_s,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_dtalite(
    output_dir: Path,
    timeout_s: int = 3600,
    iterations: int = 5,
    column_updating_iterations: int = 5,
) -> tuple[bool, float, Optional[str]]:
    """Invoke DTALite via ``path4gmns.DTALiteClassic()`` in ``output_dir``.

    DTALite reads ``settings.csv + node.csv + link.csv + demand.csv``
    from the current working directory and writes its outputs there.
    We run it as a subprocess so each run gets its own cwd, timeout, and
    stderr (path4gmns's in-process API chdirs the whole process, which
    tangles multi-run pytest sessions).

    Why ``DTALiteClassic`` and not the newer ``DTALiteMultimodal`` (aka
    ``run_DTALite``): in path4gmns 0.10.0 the Multimodal binary has a
    regression that wants a ``mode_type.csv`` in a schema upstream never
    published. Even path4gmns's own bundled samples fail with ``[ERROR]
    File mode_type does not have information`` on a fresh run. Classic is
    the stable path; it takes (assignment_mode, column_gen_num,
    column_upd_num) directly, and mode 1 (path-based UE) writes both
    ``link_performance.csv`` and ``agent.csv``, which is what we need for
    the travel-time stats.

    Returns ``(success, runtime_seconds, error_message)``.
    """
    output_dir = Path(output_dir).resolve()
    if not (output_dir / "settings.csv").is_file():
        return False, 0.0, (
            f"settings.csv missing in {output_dir} — call prepare_dtalite_inputs first."
        )

    if int(iterations) < 1 or int(column_updating_iterations) < 0:
        return False, 0.0, (
            f"invalid DTALite iteration counts: iterations={iterations} "
            f"(must be >= 1), column_updating_iterations="
            f"{column_updating_iterations} (must be >= 0)."
        )

    if not is_dtalite_available():
        return False, 0.0, (
            "DTALite not available. Install via: uv pip install path4gmns\n"
            "On Mac, the bundled binary also needs OpenMP: brew install libomp"
        )

    # Success is decided by the presence of fresh output files (the path4gmns
    # macOS wrapper can raise after the binary has already written them). Delete
    # any stale outputs from a prior run in this dir first, so "link_performance
    # .csv exists" unambiguously means "this run produced it" rather than a
    # leftover that would mask a silent failure.
    for stale in ("link_performance.csv", "agent.csv", "od_performance.csv"):
        (output_dir / stale).unlink(missing_ok=True)

    # The subprocess prints path4gmns's noisy "version 0.10.0" banner on
    # import; route it to /dev/null via a brief stdout redirect inside
    # the same -c snippet so the harness's per-cell row stays clean.
    cmd = [
        sys.executable, "-c",
        "import sys, io; _saved = sys.stdout; sys.stdout = io.StringIO();"
        " import path4gmns as pg; sys.stdout = _saved;"
        f" pg.DTALiteClassic(1, {int(iterations)}, "
        f"{int(column_updating_iterations)})",
    ]
    logger.info("Running DTALite: %s  (cwd=%s)", " ".join(cmd), output_dir)
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        elapsed = time.monotonic() - start
        # We decide success from the output files, not the exit code.
        # path4gmns 0.10.0's DTALiteClassic wrapper has a macOS
        # multiprocessing bug: it raises a SemLock error AFTER the binary has
        # already written full output. The wrapper tries to spawn a
        # `multiprocessing.Process` for the call, and macOS on Python 3.8+
        # refuses the start, but the DTALite C++ binary finishes the
        # assignment in-process before that fork and has already dropped
        # link_performance.csv and agent.csv on disk. So we trust the files,
        # not the return code.
        link_perf = output_dir / "link_performance.csv"
        if link_perf.is_file() and link_perf.stat().st_size > 0:
            return True, elapsed, None

        # A real failure: no output file. Surface an [ERROR] line from the
        # log if there is one, else the wrapper's stderr.
        log_text = ""
        for log_name in ("log.txt", "log_main.txt", "log_DTA.txt"):
            p = output_dir / log_name
            if p.is_file():
                log_text += p.read_text(encoding="utf-8", errors="ignore")
        err_line = next(
            (ln for ln in log_text.splitlines() if "ERROR" in ln.upper()),
            None,
        )
        tail = (result.stderr or result.stdout or "no output")[:400]
        if result.returncode != 0:
            msg = err_line.strip() if err_line else tail
            return False, elapsed, f"DTALite exit {result.returncode}: {msg}"
        msg = err_line.strip() if err_line else tail
        return False, elapsed, f"DTALite produced no link_performance.csv: {msg}"
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start, f"DTALite timeout after {timeout_s}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, time.monotonic() - start, f"DTALite failed to launch: {exc}"


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


@dataclass
class DTALiteTripStats:
    trip_count: int          # Total agents (rows) in agent.csv
    completed_count: int     # Agents with travel_time > 0 (UE-converged)
    mean_travel_time_s: float
    p95_travel_time_s: float
    mean_distance_m: float


def parse_dtalite_output(output_dir: Path) -> Optional[DTALiteTripStats]:
    """Parse DTALite's ``agent.csv`` into shared travel-time stats.

    Schema (from path4gmns Chicago_Sketch sample):
        ``agent_id, o_zone_id, d_zone_id, path_id, agent_type,
          demand_period, volume, toll, travel_time, distance,
          node_sequence, link_sequence, time_sequence, ...``

    DTALite's ``agent.csv`` has one row per OD pair, not per trip, with
    ``volume`` being the number of vehicles on that path. So we expand each
    row by ``volume`` for the trip-level stats, which keeps the means
    comparable to SUMO's and MATSim's per-vehicle output.

    The file is in minutes for travel_time and kilometers for distance; we
    convert to seconds and meters for the shared TripStats schema.

    Returns ``None`` when there's no ``agent.csv`` (DTALite failed before
    writing per-agent output). DTALiteClassic with assignment_mode=1 always
    emits agent.csv on a successful run, so a missing file means failure, not
    a quiet output toggle.
    """
    output_dir = Path(output_dir)
    agent_csv = output_dir / "agent.csv"
    if not agent_csv.is_file():
        return None

    travel_times_s: list[float] = []
    distances_m: list[float] = []
    total_vehicle_trips = 0  # Sum of `volume` across all rows
    with agent_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                tt_min = float(row.get("travel_time", "0") or 0)
                dist_km = float(row.get("distance", "0") or 0)
                volume = float(row.get("volume", "1") or 1)
            except ValueError:
                continue
            # Drop non-finite values (NaN/inf): a single NaN travel time would
            # poison the mean and percentiles for the whole run, and the row
            # would still be counted as a completed trip.
            if not math.isfinite(tt_min) or not math.isfinite(dist_km) \
                    or not math.isfinite(volume):
                continue
            if volume <= 0:
                continue
            # Round to nearest integer vehicle count; a volume that rounds to 0
            # (a sub-0.5 fractional assignment) contributes no vehicle, matching
            # the comment below rather than being force-counted as one.
            n = int(round(volume))
            if n <= 0:
                continue
            total_vehicle_trips += n
            if tt_min <= 0:
                continue
            tt_s = tt_min * _MIN_TO_SEC
            dist_m = dist_km * _KM_TO_M
            # Expand by volume so stats are per-vehicle, comparable to
            # SUMO/MATSim's per-trip outputs. DTA may output fractional
            # volumes for partial assignments; round to nearest integer.
            travel_times_s.extend([tt_s] * n)
            distances_m.extend([dist_m] * n)

    if not travel_times_s:
        return DTALiteTripStats(
            trip_count=total_vehicle_trips,
            completed_count=0,
            mean_travel_time_s=0.0,
            p95_travel_time_s=0.0,
            mean_distance_m=0.0,
        )

    travel_times_s.sort()
    p95_idx = max(0, int(0.95 * (len(travel_times_s) - 1)))
    return DTALiteTripStats(
        trip_count=total_vehicle_trips,
        completed_count=len(travel_times_s),
        mean_travel_time_s=statistics.mean(travel_times_s),
        p95_travel_time_s=travel_times_s[p95_idx],
        mean_distance_m=statistics.mean(distances_m) if distances_m else 0.0,
    )
