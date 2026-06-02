"""Shared canonical-routes BFS (Phase 14).

For every feasible trip, both the SUMO and MATSim adapters need its
shortest path through the canonical network, honoring OSM turn
restrictions when the V5+ Phase 7 metadata is there. Before Phase 14 each
adapter ran its own copy of that same BFS over the same network. This
module does it once: compute the routes per ``(scenario,
feasible_trip_set)``, cache them to a JSONL file keyed by content hash,
and hand both adapters the same `Dict[trip_id, List[node_id]]`.

The byte-identity rule (an adapter's route XML must match what it produced
before Phase 14) is pinned by
``tests/test_canonical_routes.py::TestByteIdentityVsLegacy``.
``doc/PHASE_14_DESIGN.md`` has the design rationale, the cache-key
derivation, and the Phase 14.x sub-commit plan.

This file is Phase 14.5: serial and parallel BFS plus the JSONL cache.
Pass ``workers > 1`` and it fans out to a ``multiprocessing.Pool``; the
parallel output is byte-identical to the serial output at any worker count
(TestParallelDeterminism pins that).

How the parallelism works (full detail in doc/PHASE_14_DESIGN.md §2.3):

  This is task parallelism over trips, not data parallelism over the
  network. Every worker gets the whole graph; only the trip list is split
  up. Workers never talk to each other mid-BFS, each is a self-contained
  BFS session that just happens to be running at the same time as the
  others. In detail:

    - **Replicated graph.** Each worker keeps the full SCC-filtered graph
      in its own heap (~150 MB on chicago_200k, ~250 MB on nyc_500k). At 16
      workers that's ~2.4 GB / ~4 GB, nothing against Cardinal cpu's
      503 GB per node.
    - **Partitioned trips.** The feasible trip list, sorted by trip_id, is
      cut into ~1,000 small chunks of ~200 trips. ``Pool.imap`` hands them
      out as workers finish, so cores running at slightly different speeds
      (NUMA, neighbouring jobs) balance themselves for free.
    - **No worker-to-worker IPC.** The only traffic is main to worker
      (chunk in) and worker to main (chunk out). There's no shared state
      for workers to race on, because there isn't any.
    - **Determinism is just a pure-function argument.** Every
      ``shortest_path_with_restrictions(origin, dest, adjacency,
      edge_lookup, forbidden_moves)`` is a pure function of inputs that are
      bit-identical across workers (all read from the hash-pinned bundle),
      so the merged dict matches a serial run no matter how many workers
      ran it. ``TestParallelDeterminism`` checks this on chicago_1k_car for
      workers in {1, 2, 4}.
    - **Forced `spawn` start method.** We use
      ``multiprocessing.get_context("spawn")`` instead of the platform
      default so workers behave the same on macOS (spawn since Python 3.8+)
      and Linux (fork by default). Each worker boots a fresh interpreter
      and rebuilds its state in ``_init_worker(network_path)``, ~1-2 s at
      startup, which is nothing next to the multi-hour BFS it then runs.

  doc/PHASE_14_DESIGN.md §2.3 has the diagram, the alternatives we turned
  down (threads/GIL, shared_memory, partitioning the network), and the
  measured per-worker efficiency on Cardinal.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import multiprocessing
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET

from adapters.common.feasibility import feasible_trip_ids as _feasible_trip_ids
from pipeline.network.scc import compute_largest_scc
from pipeline.network.turn_restrictions import (
    build_forbidden_moves,
    parse_turn_restrictions,
    shortest_path_with_restrictions,
)

# Cache schema version. Bump when changing how routes are computed or
# stored on disk; the version is part of the cache key, so a bump
# invalidates every existing cache file in one go.
_CACHE_SCHEMA_VERSION = 1

# Minimum wall-clock seconds between progress emissions. Rate-limit by
# time, not trip count, so the heartbeat is meaningful at any hardware
# speed. 60 s is a defense-presentable cadence: for a ~4 h chicago_200k
# Phase 14 run that's ~240 progress lines, one per minute; for a ~25 h
# nyc_500k Phase 14 run that's ~1,500 lines. Both readable; both
# tight enough that the operator sees the job is alive.
_PROGRESS_INTERVAL_S = 60.0

# Progress lines go out at WARNING so they show without --verbose. It isn't
# WARNING because anything's wrong; it's just the only stdlib level the
# StickyProgress capture_logs handler always routes above the sticky bar,
# whatever verbosity the user picked. (The harness drops the threshold to
# INFO under --verbose, but progress should be visible either way.)
_BFS_LOGGER_NAME = "adapters.common.canonical_routes"
logger = logging.getLogger(_BFS_LOGGER_NAME)


def _fmt_dur(seconds: float) -> str:
    """Format seconds as `Xs` / `Xm YYs` / `Xh YYm` for log readability."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, s = divmod(s, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


def _fmt_int(n: int) -> str:
    """1234 → '1,234'. Aligns columns visually in the log."""
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_canonical_routes(
    *,
    scenario_dir: Path,
    feasible_trip_ids: Set[str],
    workers: int = 1,
    cache_root: Optional[Path] = None,
    progress: bool = True,
) -> Dict[str, List[str]]:
    """Compute canonical shortest-path routes for every feasible trip.

    Returns a dict mapping ``trip_id -> list of node ids`` (origin first,
    destination last). The result is content-addressed: cached on disk
    when ``cache_root`` is provided; subsequent calls with the same
    inputs read from cache without re-routing.

    Parameters
    ----------
    scenario_dir:
        Path to the canonical bundle (must contain ``network.xml`` and
        ``demand.csv``).
    feasible_trip_ids:
        The shared cross-engine feasibility set, typically the output
        of ``adapters.common.feasibility.feasible_trip_ids``. Only
        these trip IDs are routed.
    workers:
        How many subprocesses to fan the BFS out to. ``1`` (default) runs
        serially in the calling process; more than that uses a
        ``multiprocessing.Pool``.
    cache_root:
        Directory under which the JSONL cache file is written. When
        ``None`` (default), no caching is performed and every call
        re-computes. When provided, the directory is created if
        absent and a single JSONL named ``canonical_routes_<hash>.jsonl``
        is written/read.
    progress:
        Whether to emit progress updates. When ``True``, a structured
        heartbeat is logged via ``logger.warning`` on a wall-clock
        interval (``_PROGRESS_INTERVAL_S``, 60 s) so both interactive
        and SBATCH logs show live progress.

    Returns
    -------
    Dict[str, List[str]]:
        Routes keyed by trip_id. A trip with no restriction-respecting path
        falls back to plain BFS, same as the old adapters did. A trip that's
        genuinely unroutable (which the feasibility filter should have caught
        already) maps to an empty list, so adapters can spot it and report it.
    """
    scenario_dir = Path(scenario_dir).resolve()
    network_path = scenario_dir / "network.xml"
    demand_path = scenario_dir / "demand.csv"

    if not feasible_trip_ids:
        return {}

    # Cache lookup (content-addressed).
    cache_key = _cache_key(
        network_path=network_path,
        demand_path=demand_path,
        feasible_trip_ids=feasible_trip_ids,
    )
    cache_file: Optional[Path] = None
    if cache_root is not None:
        cache_root = Path(cache_root)
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_file = cache_root / f"canonical_routes_{cache_key}.jsonl"
        cached = _load_cache(cache_file, expected_count=len(feasible_trip_ids))
        if cached is not None:
            logger.warning(
                "[bfs] cache hit  : %s routes loaded from %s",
                _fmt_int(len(cached)), cache_file.name,
            )
            return cached
        logger.warning(
            "[bfs] cache miss : computing %s routes  (workers=%d)",
            _fmt_int(len(feasible_trip_ids)), workers,
        )

    # Compute. ``workers > 1`` dispatches to multiprocessing.Pool with one
    # chunk per worker. Below that the IPC overhead would swamp the BFS
    # savings, so we run serial instead, just never quietly for tests, which
    # set workers on purpose and expect the parallel path to actually run.
    t0 = time.monotonic()
    if workers > 1:
        routes = _compute_parallel(
            network_path=network_path,
            demand_path=demand_path,
            feasible_trip_ids=feasible_trip_ids,
            workers=workers,
            progress=progress,
        )
    else:
        routes = _compute_serial(
            network_path=network_path,
            demand_path=demand_path,
            feasible_trip_ids=feasible_trip_ids,
            progress=progress,
        )
    elapsed = time.monotonic() - t0
    rate = len(routes) / elapsed if elapsed > 0 else 0
    logger.warning(
        "[bfs] done       : %s routes in %s  (%.0f trips/s, workers=%d)",
        _fmt_int(len(routes)), _fmt_dur(elapsed), rate, workers,
    )

    # Cache write (atomic).
    if cache_file is not None:
        _write_cache(cache_file, routes, cache_key)
        logger.warning(
            "[bfs] cached     : %s routes -> %s",
            _fmt_int(len(routes)), cache_file.name,
        )

    return routes


# ---------------------------------------------------------------------------
# Cache: hashing, reading, writing
# ---------------------------------------------------------------------------


def _cache_key(
    *,
    network_path: Path,
    demand_path: Path,
    feasible_trip_ids: Set[str],
) -> str:
    """SHA-256 over inputs that fully determine the BFS output.

    Any change to network topology, demand bytes, or the feasibility
    filter changes the key and forces a re-computation. The schema
    version is included so a future Phase 14.x can invalidate the
    whole cache namespace by bumping ``_CACHE_SCHEMA_VERSION``.
    """
    h = hashlib.sha256()
    h.update(f"canonical_routes_v{_CACHE_SCHEMA_VERSION}\0".encode())
    h.update(b"network:\0")
    h.update(network_path.read_bytes())
    h.update(b"\0demand:\0")
    h.update(demand_path.read_bytes())
    h.update(b"\0feasible:\0")
    for tid in sorted(feasible_trip_ids):
        h.update(tid.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _load_cache(
    cache_file: Path, expected_count: int,
) -> Optional[Dict[str, List[str]]]:
    """Read a JSONL cache file. Returns ``None`` if absent, malformed,
    or truncated. The header line records the expected count; we cross-
    check against the body length to detect partial writes (e.g. from
    an interrupted previous run).
    """
    if not cache_file.is_file():
        return None
    try:
        routes: Dict[str, List[str]] = {}
        header: Optional[dict] = None
        with cache_file.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                obj = json.loads(line)
                if i == 0 and obj.get("_meta"):
                    header = obj
                    continue
                tid = obj["trip_id"]
                path = obj["path"]
                routes[tid] = list(path)
        if header is None:
            logger.warning(
                "[canonical_routes] cache file missing header: %s — ignoring",
                cache_file,
            )
            return None
        if header.get("trip_count") != len(routes):
            logger.warning(
                "[canonical_routes] cache file truncated (header=%s, body=%d): %s",
                header.get("trip_count"), len(routes), cache_file,
            )
            return None
        if expected_count and len(routes) != expected_count:
            logger.warning(
                "[canonical_routes] cache file count mismatch "
                "(expected %d, got %d): %s — ignoring",
                expected_count, len(routes), cache_file,
            )
            return None
        return routes
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(
            "[canonical_routes] cache file unreadable (%s): %s",
            type(e).__name__, cache_file,
        )
        return None


def _write_cache(
    cache_file: Path, routes: Dict[str, List[str]], cache_key: str,
) -> None:
    """Write the JSONL cache atomically: temp file in the same dir,
    then rename. Avoids leaving partial writes that look like valid
    caches but truncate mid-stream.
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="canonical_routes_", suffix=".jsonl.tmp",
        dir=str(cache_file.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            header = {
                "_meta": True,
                "version": _CACHE_SCHEMA_VERSION,
                "trip_count": len(routes),
                "cache_key": cache_key,
                "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            out.write(json.dumps(header, separators=(",", ":")) + "\n")
            # Sort by trip_id so the cache file itself is deterministic
            # (useful for diffing and content-addressing future formats).
            for tid in sorted(routes.keys()):
                out.write(json.dumps(
                    {"trip_id": tid, "path": routes[tid]},
                    separators=(",", ":"),
                ) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_name, cache_file)
    except Exception:
        # Best-effort cleanup on failure; the rename is the only step
        # that can leave a partial cache file.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Network parsing: minimal subset, no dependency on any specific adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LinkRef:
    """Carries just the link id, matching what
    ``shortest_path_with_restrictions`` needs from each edge_lookup entry.
    """
    id: str


def _parse_network_for_routing(
    network_path: Path,
) -> Tuple[Set[str], Dict[str, List[str]], Dict[Tuple[str, str], _LinkRef]]:
    """A bare-bones network parse, returning (nodes, adjacency, edge_lookup).

    It ignores coordinates, length, speed, and lanes, none of which the BFS
    needs. Living here keeps canonical_routes free of any dependency on a
    specific adapter package.
    """
    nodes: Set[str] = set()
    adjacency: Dict[str, List[str]] = {}
    edge_lookup: Dict[Tuple[str, str], _LinkRef] = {}

    root = ET.parse(str(network_path)).getroot()
    if root.tag != "network":
        raise ValueError(
            f"network.xml root must be <network>, found <{root.tag}>"
        )

    nodes_elem = root.find("nodes")
    if nodes_elem is not None:
        for n in nodes_elem.findall("node"):
            nid = n.get("id")
            if nid:
                nodes.add(nid)

    links_elem = root.find("links")
    if links_elem is not None:
        for l in links_elem.findall("link"):
            lid = l.get("id")
            f = l.get("from")
            t = l.get("to")
            if not (lid and f and t):
                continue
            adjacency.setdefault(f, []).append(t)
            edge_lookup[(f, t)] = _LinkRef(id=lid)

    return nodes, adjacency, edge_lookup


def _scc_filter(
    nodes: Set[str],
    adjacency: Dict[str, List[str]],
    edge_lookup: Dict[Tuple[str, str], _LinkRef],
) -> Tuple[Set[str], Dict[str, List[str]], Dict[Tuple[str, str], _LinkRef]]:
    """Restrict the graph to its largest SCC.

    Matches the SCC filter in ``adapters/sumo/sumo_adapter.py:prepare_sumo_inputs``
    (lines ~605-624) and the equivalent step in the MATSim adapter.
    Without this filter the BFS adjacency would include non-SCC dead-end
    stubs, producing routes the feasibility filter then rejects.
    """
    edges = list(edge_lookup.keys())
    scc = compute_largest_scc(nodes, edges)
    scc_nodes = nodes & scc
    scc_adjacency: Dict[str, List[str]] = {}
    scc_edge_lookup: Dict[Tuple[str, str], _LinkRef] = {}
    for (u, v), link in edge_lookup.items():
        if u in scc and v in scc:
            scc_adjacency.setdefault(u, []).append(v)
            scc_edge_lookup[(u, v)] = link
    return scc_nodes, scc_adjacency, scc_edge_lookup


# ---------------------------------------------------------------------------
# Plain BFS: the fallback when the state-aware version can't find a path
# ---------------------------------------------------------------------------


def _plain_bfs(
    adjacency: Dict[str, List[str]], origin: str, dest: str,
) -> Optional[List[str]]:
    """Plain BFS on the node graph; mirrors
    ``adapters.sumo.sumo_adapter.shortest_path_nodes``. Inlined to keep
    this module free of adapter imports.
    """
    if origin == dest:
        return [origin]
    if origin not in adjacency:
        return None
    visited: Set[str] = {origin}
    parent: Dict[str, str] = {}
    queue: deque = deque([origin])
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, []):
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = node
            if nxt == dest:
                path: List[str] = [nxt]
                cur = nxt
                while cur in parent:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                return path
            queue.append(nxt)
    return None


# ---------------------------------------------------------------------------
# Serial driver
# ---------------------------------------------------------------------------


def _compute_serial(
    *,
    network_path: Path,
    demand_path: Path,
    feasible_trip_ids: Set[str],
    progress: bool,
) -> Dict[str, List[str]]:
    """Run the BFS in the calling process, one trip at a time.

    Matches the legacy in-adapter BFS exactly: SCC-filter the network,
    build forbidden-moves from turn restrictions, then for each feasible
    trip call ``shortest_path_with_restrictions`` (state-aware) and fall
    back to plain BFS when no restriction-respecting path exists.
    """
    nodes, adjacency, edge_lookup = _parse_network_for_routing(network_path)
    nodes, adjacency, edge_lookup = _scc_filter(nodes, adjacency, edge_lookup)

    # Turn restrictions → forbidden-moves table (V5+).
    restrictions = parse_turn_restrictions(network_path)
    forbidden_moves: Dict[Tuple[str, str], FrozenSet[str]] = {}
    if restrictions:
        outgoing: Dict[str, List[str]] = {}
        for u, neighbors in adjacency.items():
            outgoing[u] = [
                edge_lookup[(u, v)].id for v in neighbors
                if (u, v) in edge_lookup
            ]
        forbidden_moves = build_forbidden_moves(restrictions, outgoing)
        logger.warning(
            "[bfs] state-aware: %d turn restrictions, %s forbidden moves",
            len(restrictions), _fmt_int(len(forbidden_moves)),
        )

    # Read the demand once into a list of (trip_id, origin, dest), keeping
    # only the feasible trips. Sorting by trip_id makes the BFS order
    # deterministic no matter how dicts iterate downstream, and the parallel
    # path needs it too, since the chunking has to be deterministic.
    work: List[Tuple[str, str, str]] = []
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = (row.get("trip_id") or "").strip()
            if tid not in feasible_trip_ids:
                continue
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            work.append((tid, origin, dest))
    work.sort(key=lambda r: r[0])

    routes: Dict[str, List[str]] = {}
    total = len(work)
    fallback_count = 0
    bfs_start = time.monotonic()
    # Start at -inf so the first heartbeat fires right away. Otherwise a
    # short job (the 1K bundle finishes in ~3 s) would never show one, just
    # the final "done" line.
    last_progress_at = float("-inf")
    for i, (tid, origin, dest) in enumerate(work, start=1):
        path: Optional[List[str]]
        if forbidden_moves:
            path = shortest_path_with_restrictions(
                origin=origin, dest=dest,
                adjacency=adjacency,
                edge_lookup=edge_lookup,
                forbidden_moves=forbidden_moves,
            )
            if path is None:
                fallback_count += 1
                path = _plain_bfs(adjacency, origin, dest)
        else:
            path = _plain_bfs(adjacency, origin, dest)
        routes[tid] = path or []

        # Heartbeat every _PROGRESS_INTERVAL_S wall-clock seconds, not every
        # N trips, so the cadence stays steady no matter how fast the
        # hardware is. It goes through the logger so
        # StickyProgress.print_above() lands it cleanly above the sticky bar
        # rather than fighting the bar's TTY writes.
        now = time.monotonic()
        if progress and (now - last_progress_at) >= _PROGRESS_INTERVAL_S:
            _emit_progress(i, total, bfs_start, now, workers=1)
            last_progress_at = now

    if fallback_count:
        logger.warning(
            "[bfs] fallback   : %s trips used plain BFS (no restriction-respecting path)",
            _fmt_int(fallback_count),
        )
    return routes


def _emit_progress(
    routed: int, total: int, bfs_start: float, now: float, workers: int,
) -> None:
    """Single column-aligned progress line. Format:

        [bfs] progress  :   53,028/200,000 (26.5%)  ⏱  8h 30m   2,937 trips/s  w=16

    Width-aligned so successive lines stack cleanly in any log viewer.
    """
    elapsed = now - bfs_start
    rate = routed / elapsed if elapsed > 0 else 0.0
    pct = 100.0 * routed / total if total else 100.0
    # Number widths: routed is at most total, so align to total's width
    # plus the thousands separators that _fmt_int introduces.
    routed_str = _fmt_int(routed)
    total_str = _fmt_int(total)
    width = len(total_str)
    logger.warning(
        "[bfs] progress   : %*s/%s (%5.1f%%)  elapsed %-9s %6.0f trips/s  w=%d",
        width, routed_str, total_str, pct,
        _fmt_dur(elapsed), rate, workers,
    )


# ---------------------------------------------------------------------------
# Parallel driver: multiprocessing.Pool with one chunk per worker
# ---------------------------------------------------------------------------


# Worker-local state. Each subprocess loads the network once via
# _init_worker, then keeps it in this dict for every _route_chunk call it
# handles. The dict is private to the worker; there's no IPC after init.
_WORKER_STATE: Dict[str, object] = {}


def _init_worker(network_path_str: str) -> None:
    """Pool initializer: load the network and restrictions once per worker.

    A worker is handed only the network_path and rebuilds everything else
    from disk, which keeps the pickled `initargs` small. The parse, SCC
    filter, and forbidden_moves build run ~1-2 s for chicago_200k (~50K
    nodes), and spread over thousands of trips that's nothing.

    We stash it in the module-global ``_WORKER_STATE`` instead of passing it
    per chunk because subprocesses don't share memory, and a global is the
    cheapest way to reach the graph from ``_route_chunk`` without re-pickling
    it on every call.
    """
    network_path = Path(network_path_str)
    nodes, adjacency, edge_lookup = _parse_network_for_routing(network_path)
    nodes, adjacency, edge_lookup = _scc_filter(nodes, adjacency, edge_lookup)

    restrictions = parse_turn_restrictions(network_path)
    forbidden_moves: Dict[Tuple[str, str], FrozenSet[str]] = {}
    if restrictions:
        outgoing: Dict[str, List[str]] = {}
        for u, neighbors in adjacency.items():
            outgoing[u] = [
                edge_lookup[(u, v)].id for v in neighbors
                if (u, v) in edge_lookup
            ]
        forbidden_moves = build_forbidden_moves(restrictions, outgoing)

    _WORKER_STATE["adjacency"] = adjacency
    _WORKER_STATE["edge_lookup"] = edge_lookup
    _WORKER_STATE["forbidden_moves"] = forbidden_moves


def _route_chunk(
    chunk: List[Tuple[str, str, str]],
) -> List[Tuple[str, List[str]]]:
    """Route a chunk of trips in the worker.

    Receives a list of ``(trip_id, origin_node, dest_node)`` tuples;
    returns a list of ``(trip_id, path)`` in the same order. The
    worker uses the module-global ``_WORKER_STATE`` populated by
    ``_init_worker``.
    """
    adjacency = _WORKER_STATE["adjacency"]
    edge_lookup = _WORKER_STATE["edge_lookup"]
    forbidden_moves = _WORKER_STATE["forbidden_moves"]

    out: List[Tuple[str, List[str]]] = []
    for trip_id, origin, dest in chunk:
        path: Optional[List[str]]
        if forbidden_moves:
            path = shortest_path_with_restrictions(
                origin=origin, dest=dest,
                adjacency=adjacency,
                edge_lookup=edge_lookup,
                forbidden_moves=forbidden_moves,
            )
            if path is None:
                path = _plain_bfs(adjacency, origin, dest)
        else:
            path = _plain_bfs(adjacency, origin, dest)
        out.append((trip_id, path or []))
    return out


def _compute_parallel(
    *,
    network_path: Path,
    demand_path: Path,
    feasible_trip_ids: Set[str],
    workers: int,
    progress: bool,
) -> Dict[str, List[str]]:
    """Parallel BFS via multiprocessing.Pool.

    Chunks the sorted-by-trip_id work list into ``workers`` slices,
    one per worker; each slice is processed serially inside its
    subprocess. Pool.map preserves submission order, so the merged
    dict is byte-identical to what ``_compute_serial`` produces with
    the same inputs (verified by ``TestParallelDeterminism``).

    Uses the ``spawn`` start method explicitly for macOS portability.
    fork-inherited globals work on Linux but are unreliable on macOS;
    spawn pickles ``initargs`` only and re-imports the module in each
    worker, which is what ``_init_worker`` needs anyway.
    """
    # Read demand into the work list, filtered + sorted for determinism.
    work: List[Tuple[str, str, str]] = []
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = (row.get("trip_id") or "").strip()
            if tid not in feasible_trip_ids:
                continue
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            work.append((tid, origin, dest))
    work.sort(key=lambda r: r[0])

    if not work:
        return {}

    # Aim for ~1,000 chunks total, so each worker chews through many small
    # chunks instead of one giant slab. Two reasons:
    #  1. Progress visibility. The progress emitter only fires when a chunk
    #     returns. With one chunk per worker (the first design) the first
    #     heartbeat didn't show until a worker finished its whole share,
    #     ~4 hours into a 200K run, when ~25% of the work was already done.
    #     Smaller chunks return more often, so progress shows within minutes.
    #  2. Load balancing. If one worker draws a slow CPU or a noisy
    #     neighbour, its big slab finishes late and drags out the whole job's
    #     wall. Fine-grained chunks let the others push ahead and soak up the
    #     imbalance.
    # Floor at 100 trips per chunk so the per-chunk IPC (pickle in, pickle the
    # result back) stays tiny next to the BFS time (~100 * 1.2 s = ~2 minutes
    # of BFS per chunk on a 200K bundle, against ~1 ms of IPC).
    n = len(work)
    target_chunks = 1_000
    chunk_size = max(100, (n + target_chunks - 1) // target_chunks)
    chunks = [work[i:i + chunk_size] for i in range(0, n, chunk_size)]

    ctx = multiprocessing.get_context("spawn")
    routes: Dict[str, List[str]] = {}
    completed = 0
    bfs_start = time.monotonic()
    # -inf so the first returned chunk always emits, giving an early "alive
    # and on track" signal instead of waiting a full _PROGRESS_INTERVAL_S for
    # the first heartbeat.
    last_progress_at = float("-inf")
    with ctx.Pool(
        processes=workers,
        initializer=_init_worker,
        initargs=(str(network_path),),
    ) as pool:
        # imap (not imap_unordered) preserves submission order, which
        # is what we need for deterministic output.
        for chunk_result in pool.imap(_route_chunk, chunks):
            for tid, path in chunk_result:
                routes[tid] = path
            completed += len(chunk_result)
            now = time.monotonic()
            if progress and (now - last_progress_at) >= _PROGRESS_INTERVAL_S:
                _emit_progress(completed, n, bfs_start, now, workers=workers)
                last_progress_at = now

    return routes


# ---------------------------------------------------------------------------
# Convenience: compute everything from a scenario dir alone
# ---------------------------------------------------------------------------


def compute_canonical_routes_for_scenario(
    scenario_dir: Path,
    *,
    workers: int = 1,
    cache_root: Optional[Path] = None,
    supported_modes: Optional[Set[str]] = None,
) -> Dict[str, List[str]]:
    """One-shot helper: derive the feasibility set + compute routes.

    Used by callers that don't already have a feasible-trip set in hand
    (CLI utilities, tests, the harness's pre-prep step). Internally
    calls ``feasibility.feasible_trip_ids`` and forwards to
    ``compute_canonical_routes``.
    """
    scenario_dir = Path(scenario_dir).resolve()
    feasible, _report = _feasible_trip_ids(
        network_path=scenario_dir / "network.xml",
        demand_path=scenario_dir / "demand.csv",
        supported_modes=supported_modes,
    )
    return compute_canonical_routes(
        scenario_dir=scenario_dir,
        feasible_trip_ids=feasible,
        workers=workers,
        cache_root=cache_root,
    )
