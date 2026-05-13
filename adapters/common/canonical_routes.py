"""Shared canonical-routes BFS (Phase 14).

Both the SUMO and MATSim adapters need to know, for every feasible
trip, the shortest path through the canonical network — under OSM
turn restrictions when V5+ Phase 7 metadata is present. Until
Phase 14 each adapter ran its own copy of the same BFS over the
same network. This module deduplicates that work: compute the
canonical routes once per ``(scenario, feasible_trip_set)``, cache
them to a JSONL file keyed by content hash, and let both adapters
consume the same `Dict[trip_id, List[node_id]]`.

The byte-identity invariant — adapters must produce route XML
byte-identical to their pre-Phase-14 output — is pinned by
``tests/test_canonical_routes.py::TestByteIdentityVsLegacy``. See
``doc/PHASE_14_DESIGN.md`` for the architectural rationale,
cache-key derivation, and Phase 14.x sub-commit plan.

Phase 14.5 (this file): serial + parallel BFS + JSONL cache.
``workers > 1`` dispatches to ``multiprocessing.Pool``. Parallel
output is byte-identical to serial output regardless of worker count
(pinned by TestParallelDeterminism in tests/test_canonical_routes.py).
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import multiprocessing
import os
import sys
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

logger = logging.getLogger(__name__)


# Cache schema version. Bump when changing how routes are computed or
# stored on disk; the version is part of the cache key, so a bump
# invalidates every existing cache file in one go.
_CACHE_SCHEMA_VERSION = 1

# Periodic-print interval when stdout is redirected (no TTY for
# tqdm-style progress bars). Trades log noise for visibility — at
# 5,000 trips per line, chicago_200k_car emits 40 progress lines.
_PROGRESS_EVERY_NON_TTY = 5_000


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
        Number of subprocesses for parallel BFS. ``1`` (default) runs
        serially in the calling process. Phase 14.1 accepts the
        argument but always runs serially regardless; Phase 14.5
        wires in ``multiprocessing.Pool``.
    cache_root:
        Directory under which the JSONL cache file is written. When
        ``None`` (default), no caching is performed and every call
        re-computes. When provided, the directory is created if
        absent and a single JSONL named ``canonical_routes_<hash>.jsonl``
        is written/read.
    progress:
        Whether to emit progress updates. When ``True`` and stdout is
        a TTY, uses the project's ``StickyProgress`` if available;
        otherwise falls back to periodic ``print(... flush=True)``
        every ``_PROGRESS_EVERY_NON_TTY`` trips so SBATCH logs show
        live progress.

    Returns
    -------
    Dict[str, List[str]]:
        Routes keyed by trip_id. For trips with no restriction-
        respecting path, falls back to plain BFS (matching the
        legacy adapter behaviour). Unrouteable trips (which the
        feasibility filter is supposed to exclude) map to an empty
        list — adapters can detect and surface these as failures.
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
            logger.info(
                "[canonical_routes] cache hit: %d routes from %s",
                len(cached), cache_file.name,
            )
            return cached
        logger.info(
            "[canonical_routes] cache miss; computing %d routes (workers=%d)",
            len(feasible_trip_ids), workers,
        )

    # Compute. Phase 14.5: ``workers > 1`` dispatches to
    # multiprocessing.Pool with one chunk per worker. Below the
    # threshold, the IPC overhead dominates the BFS savings, so we
    # fall back to serial — but never silently for tests, which set
    # workers explicitly and expect the parallel path to actually run.
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
    logger.info(
        "[canonical_routes] computed %d routes in %.1fs "
        "(%.0f trips/s, workers=%d)",
        len(routes), elapsed, rate, workers,
    )

    # Cache write (atomic).
    if cache_file is not None:
        _write_cache(cache_file, routes, cache_key)
        logger.info(
            "[canonical_routes] cached %d routes -> %s",
            len(routes), cache_file,
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
# Network parsing — minimal subset, no dep on any specific adapter
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
    """Minimal canonical-network parse: returns (nodes, adjacency,
    edge_lookup).  Skips coordinate, length, speed, lane attributes —
    they aren't needed for BFS routing. Centralised so canonical_routes
    has no dependency on any specific adapter package.
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
# Plain BFS — fallback when the state-aware version can't find a path
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
        logger.info(
            "[canonical_routes] state-aware BFS active: "
            "%d turn restrictions, %d forbidden (via,from)->to entries",
            len(restrictions), len(forbidden_moves),
        )

    # Read the demand once into a list of (trip_id, origin, dest)
    # filtered by the feasibility set. We sort by trip_id so the BFS
    # order is deterministic regardless of dict iteration order
    # downstream (also a prerequisite for the parallel implementation
    # in Phase 14.5 — chunking must be deterministic).
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
    is_tty = sys.stdout.isatty() if progress else False
    fallback_count = 0
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

        # Progress emission. TTY case piggybacks on the existing
        # StickyProgress mechanic via a lazy import; non-TTY (SBATCH)
        # case emits a periodic log line so tail -f shows something.
        if progress and i % _PROGRESS_EVERY_NON_TTY == 0 and not is_tty:
            print(
                f"[canonical_routes] routed {i}/{total} ({100*i/total:.1f}%)",
                flush=True,
            )

    if fallback_count:
        logger.info(
            "[canonical_routes] %d trips fell back to plain BFS "
            "(no restriction-respecting path)", fallback_count,
        )
    return routes


# ---------------------------------------------------------------------------
# Parallel driver — multiprocessing.Pool with one chunk per worker
# ---------------------------------------------------------------------------


# Worker-local state. Each subprocess (re)loads the network on import
# of this module via _init_worker, then keeps the data in this dict
# across all _route_chunk calls in the worker's lifetime. The dict is
# private to each worker — no IPC after init.
_WORKER_STATE: Dict[str, object] = {}


def _init_worker(network_path_str: str) -> None:
    """Pool initializer: load network + restrictions once per worker.

    Workers receive only the network_path; everything else is rebuilt
    from disk to keep the pickled `initargs` small. The graph parse +
    SCC filter + forbidden_moves build typically costs 1-2 s for
    chicago_200k (~50K nodes); amortized across thousands of trips
    in the worker's lifetime, it's negligible.

    Stored in module-global ``_WORKER_STATE`` rather than passed
    per-chunk because subprocesses don't share memory — global state
    is the cheapest way to make the graph reachable from
    ``_route_chunk`` without re-pickling per call.
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

    # Split into one big chunk per worker. We don't want fine-grained
    # tasks because BFS calls are independent and the IPC roundtrip
    # per task would dominate at our per-call cost.
    n = len(work)
    chunk_size = (n + workers - 1) // workers
    chunks = [work[i:i + chunk_size] for i in range(0, n, chunk_size)]

    ctx = multiprocessing.get_context("spawn")
    routes: Dict[str, List[str]] = {}
    completed = 0
    is_tty = sys.stdout.isatty() if progress else False
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
            if progress and not is_tty:
                print(
                    f"[canonical_routes] routed {completed}/{n} "
                    f"({100 * completed / n:.1f}%) "
                    f"[workers={workers}]",
                    flush=True,
                )

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
