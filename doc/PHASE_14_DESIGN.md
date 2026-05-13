# Phase 14 — Canonical Routes + Parallel BFS

**Branch**: `phase-14-canonical-routes`
**Status**: implementation landed 2026-05-12 (sub-commits 14.0–14.5);
cluster re-measurement pending (Phase 14.7 addendum).
**Problem owner**: BFS-prep wall dominates large-tier benchmarks

---

## 1. Motivation

The Phase 13 benchmark run on Cardinal (job 9332478, 9332482) made an
unmodeled cost visible: at 200K trips on the chicago bundle, the
state-aware BFS routes trips at **~1.5 s/trip**; at 500K on the nyc
bundle, **~2.16 s/trip**. Both rates are ~25× slower than I had
estimated in Phase 13's wall-time budgets. The empirical projection:

| Scenario | Cold BFS per engine | × 2 engines (SUMO + MATSim) | Wall budget |
|---|---|---|---|
| chicago_200k_car | ~82 h | **~164 h** | 168 h (7 days) → marginal fit |
| nyc_500k_car | ~300 h | **~600 h (~25 days)** | 168 h → ~4× over the cap |

The nyc_500k job was cancelled (`scancel 9332482`) after the 22 h
data point made the wall-bust certain. chicago_200k continues; expected
to complete within its 168 h cap.

### Why the BFS cost is so high

Three compounding factors the original architecture didn't optimize for:

1. **Per-adapter duplication.** SUMO and MATSim each run the identical
   state-aware BFS over the identical canonical network with the
   identical feasible-trip set. Two passes for the same paths.
   (`adapters/sumo/sumo_adapter.py:496`,
   `adapters/matsim/matsim_adapter.py:475`).

2. **Single-threaded routing.** The per-trip loop is a serial Python
   `for` over `demand.csv` (`adapters/sumo/sumo_adapter.py:481`). Each
   sbatch already allocates 16-24 CPUs but only 1 does routing work;
   the rest idle. State-aware BFS per call is O(V + E) on a graph of
   ~80K nodes / ~200K links; CPython per-step overhead (~5 µs/state)
   amortizes to seconds per trip.

3. **Network size scaling.** The 200K and 500K bundles use 15-20 km
   bbox radii (vs 2-10 km for chicago_1k_car / nyc_10k_car), producing
   ~50K-80K node graphs. BFS state-space scales linearly with V+E and
   sublinearly with restriction count (state = `(node, last_link_id)`
   doubles to triples the visited set).

### What this phase fixes

Two compounding optimizations that combine multiplicatively:

| Lever | Mechanism | Expected speedup |
|---|---|---|
| **Phase 14a — canonical routes** | Compute BFS once per scenario, share between SUMO and MATSim adapters | 2× on cold prep (eliminates the duplication) |
| **Phase 14b — parallel BFS** | `multiprocessing.Pool` across trips with deterministic merge | ~12-15× (16-core Amdahl, serial setup + merge ~5% of wall) |

Combined, expected `cold_prep_wall` on Cardinal:

| Scenario | Today (Phase 13) | Phase 14a only | Phase 14a + 14b |
|---|---|---|---|
| chicago_200k_car | ~164 h | ~82 h | **~5-8 h** |
| nyc_500k_car | ~600 h | ~300 h | **~20-30 h** |

The nyc_500k run becomes feasible inside the 7-day `cpu` partition
wall, with a comfortable 4-6× margin.

---

## 2. Design

### 2.1 The shared canonical routes module

**New file**: `adapters/common/canonical_routes.py`

**Public API** (single function):

```python
def compute_canonical_routes(
    *,
    scenario_dir: Path,
    feasible_trip_ids: set[str],
    workers: int = 1,
    cache_root: Optional[Path] = None,
    progress: bool = True,
) -> dict[str, list[str]]:
    """
    Run state-aware BFS once per feasible trip on the canonical network.

    Returns trip_id → list of node_ids (origin first, destination last).
    Both SUMO and MATSim adapters consume this dict to emit their
    engine-specific route XML — no per-adapter BFS pass.

    Determinism: byte-identical output regardless of `workers` value.
    The parallel implementation chunks trips by sorted trip_id, dispatches
    to a Pool, and merges results back in sorted trip_id order.

    Caching: if `cache_root` is provided, results are cached at
    `cache_root / canonical_routes_<hash>.jsonl` where `<hash>` is
    SHA-256 over (manifest.xml || demand.csv hash || sorted feasible_ids).
    A second call with the same inputs reads from cache without re-routing.

    Progress: when `progress=True` and stdout is a TTY, prints a sticky
    progress bar via `pipeline.progress.StickyProgress`. When stdout is
    redirected (sbatch logs), falls back to a `print(... flush=True)`
    every PROGRESS_EVERY trips (currently 5000).
    """
```

**Cache file format** (`canonical_routes_<hash>.jsonl`):

One JSON object per line, sorted by `trip_id`:

```jsonl
{"trip_id":"t1","path":["n100","n101","n205","n307"]}
{"trip_id":"t10","path":["n100","n400","n402"]}
{"trip_id":"t100","path":["n205","n500"]}
```

JSON-Lines is chosen over a monolithic JSON object because:
- Streaming write: a partial dump on `scancel` can be detected (header line at the start records the expected count; if the count mismatches the cache file is invalidated)
- Streaming read: adapters can build the dict without parsing the whole file into memory first (helpful at 500K entries)
- Diff-friendly for debugging: line-aligned with trip_id ordering

**Cache header** (first line, JSON object):

```jsonl
{"_meta":true,"version":1,"trip_count":500000,"hash":"<hex>","computed_at":"2026-05-12T..."}
```

Adapters reading the cache check `trip_count == lines_after_header` to
detect truncated files.

### 2.2 Cache key (SHA-256 over the inputs)

```python
hasher = hashlib.sha256()
hasher.update(b"canonical_routes_v1\0")
hasher.update(network_xml_bytes)
hasher.update(b"\0demand:\0")
hasher.update(demand_csv_bytes)
hasher.update(b"\0feasible:\0")
for tid in sorted(feasible_trip_ids):
    hasher.update(tid.encode("utf-8"))
    hasher.update(b"\n")
key = hasher.hexdigest()
```

Reasoning: any change to network (turn restrictions, link/node set),
demand (added/removed/rewritten trips), or feasibility filter changes
the cache key and forces recomputation. Adding the `_v1` salt lets us
invalidate the entire cache namespace if the algorithm changes in a
future Phase 14.x.

### 2.3 Parallel BFS implementation

**Strategy**: `multiprocessing.Pool` with a per-worker initializer that
loads the graph from disk into worker-local globals. Trips are chunked
by sorted trip_id; each worker processes its chunk; results merge in
trip_id order.

**Worker code skeleton**:

```python
_GRAPH = None  # worker-local
_FORBIDDEN = None

def _init_worker(network_path, demand_path):
    global _GRAPH, _FORBIDDEN
    _GRAPH = parse_canonical_network(network_path)
    restrictions = parse_turn_restrictions(network_path)
    _FORBIDDEN = build_forbidden_moves(restrictions, ...)

def _route_chunk(trip_chunk: list[tuple[str, str, str]]) -> list[tuple[str, list[str]]]:
    """Each tuple = (trip_id, origin_node, dest_node). Returns same order."""
    out = []
    for trip_id, origin, dest in trip_chunk:
        path = shortest_path_with_restrictions(
            origin=origin, dest=dest,
            adjacency=_GRAPH.adjacency, edge_lookup=_GRAPH.edge_lookup,
            forbidden_moves=_FORBIDDEN,
        )
        if path is None:
            path = shortest_path_nodes(_GRAPH.adjacency, origin, dest)
        out.append((trip_id, path or []))
    return out
```

**Why this is deterministic**:

1. Trips are sorted by trip_id before chunking → each worker gets a
   deterministic chunk regardless of `workers` value.
2. `Pool.map()` preserves input order → output chunks come back in the
   same order they were submitted.
3. Within a chunk, the worker's serial loop is deterministic (same
   BFS, same inputs).
4. The merged dict is built by iterating the in-order chunks.

The byte-identity test (`tests/test_canonical_routes.py`) pins this:
running with `workers=1` and `workers=4` on `chicago_1k_car` must
produce identical route dicts.

**Why graph is reloaded per worker rather than fork-inherited**:

`fork()`-inherited globals work on Linux but are unreliable on macOS
(default `spawn` start method). Loading once per worker (~1-2 sec
overhead) is platform-portable and amortizes over thousands of trips.

### 2.4 Adapter integration

Both `prepare_sumo_inputs` and `prepare_matsim_inputs` gain an
optional `canonical_routes` parameter. When provided, the adapter
skips its internal BFS loop and consumes the dict directly.
When `None` (legacy path), the adapter falls back to its own BFS —
back-compat for standalone runs that don't go through the harness.

**SUMO** (`adapters/sumo/sumo_adapter.py:build_sumo_routes_xml`):

```python
def build_sumo_routes_xml(
    summary, graph, demand_path, feasible,
    *,
    canonical_routes: Optional[dict[str, list[str]]] = None,
):
    ...
    for row in reader:
        if trip_id not in feasible:
            continue
        if canonical_routes is not None:
            path_nodes = canonical_routes.get(trip_id, [])
        else:
            # Legacy: in-loop BFS (kept for standalone CLI usage)
            path_nodes = shortest_path_with_restrictions(...)
        # ... convert to edge IDs, emit XML (unchanged)
```

**MATSim** (`adapters/matsim/matsim_adapter.py:build_matsim_plans_xml`):

```python
def build_matsim_plans_xml(
    demand_path, links, feasible, network_path=None,
    *,
    canonical_routes: Optional[dict[str, list[str]]] = None,
):
    ...
    for row in reader:
        if trip_id not in feasible:
            continue
        if canonical_routes is not None:
            path_nodes = canonical_routes.get(trip_id)
        else:
            # Legacy: in-loop BFS
            path_nodes = shortest_path_with_restrictions(...)
```

### 2.5 Harness wiring (Phase 14c)

`execution/run_benchmark.py:_ensure_prepared_cache` orchestrates the
shared BFS pass. Refactored flow:

```python
def _ensure_prepared_cache(self, scenario_path, scenario_id, engine, engine_options):
    cache_dir = self._scoped_base(scenario_id) / ".cache" / engine
    sentinel = cache_dir / ".prepared"

    if sentinel.is_file() and sentinel.read_text().strip() == self._bundle_hash(scenario_path):
        return cache_dir  # adapter cache hit

    # Phase 14: compute canonical routes once, share across adapters
    routes = self._compute_canonical_routes(scenario_path, scenario_id)

    if engine == "matsim":
        prepare_matsim_inputs(scenario_path, cache_dir, cfg,
                              canonical_routes=routes)
    elif engine == "sumo":
        self.prepare_sumo_inputs(scenario_path, cache_dir,
                                  canonical_routes=routes)
    elif engine == "dtalite":
        # No BFS pre-routing for DTALite — runs its own UE assignment
        prepare_dtalite_inputs(scenario_path, cache_dir, cfg)
    ...
```

`_compute_canonical_routes` calls `compute_canonical_routes()` with
`cache_root=self._scoped_base(scenario_id) / ".canonical_routes"`,
which sits next to (not inside) the per-engine `.cache/` directories.
The cache key incorporates the bundle hash, so a regenerated bundle
invalidates both layers.

---

## 3. Implementation plan (small commits)

| Commit | Scope | Tests | Status |
|---|---|---|---|
| 14.0 | Design doc + skeleton tests | 9 contract tests, all skip (module absent) | ✅ landed |
| 14.1 | `canonical_routes.py` serial impl + JSONL cache | 7 tests pass (4 API + 2 cache + 1 byte-identity) | ✅ landed |
| 14.2 | SUMO adapter accepts `canonical_routes=` kwarg | `TestSumoRoutesXmlByteIdentity` passes | ✅ landed |
| 14.3 | MATSim adapter accepts `canonical_routes=` kwarg | `TestMatsimPlansXmlByteIdentity` passes | ✅ landed |
| 14.4 | Harness wires shared BFS pass | 12 cache-management tests pass (stubs added) | ✅ landed |
| 14.5 | `multiprocessing.Pool` in `canonical_routes.py` | `TestParallelDeterminism` passes (workers=2,4) | ✅ landed |
| 14.6 | Documentation pass | — | ✅ landed |
| 14.7 | Cluster re-measurement on Cardinal | post-run wall numbers vs Phase 13 projections | ⏳ pending next sbatch |

Each commit passes `python -m pytest tests/test_canonical_routes.py
tests/test_sumo_adapter.py tests/test_matsim_adapter.py
tests/test_adapter_determinism.py tests/test_run_benchmark.py`
(51 passed, 9 arm64-skipped, 0 failed at the 14.5 head).

---

## 4. Risk + safety

### Determinism

The byte-identity invariant is non-negotiable — this is what
`audit_fairness` Q1/Q3 measure. The test file pins:

1. `compute_canonical_routes(...)` with `workers=1, 2, 4` produces
   the same dict on `chicago_1k_car`.
2. `build_sumo_routes_xml(...)` with `canonical_routes=` produces
   byte-identical `routes.rou.xml` to the legacy in-loop BFS path.
3. `build_matsim_plans_xml(...)` with `canonical_routes=` produces
   byte-identical `plans.xml` to the legacy in-loop BFS path.

Mutation tests inherit the existing baseline at `doc/MUTATION_BASELINE.md`.

### Cache poisoning

The cache file is content-addressed (SHA-256 of inputs). A corrupted
cache file fails the `trip_count` check in the header and is
discarded. The cache is local, so no cross-host trust issue.

### Memory footprint of routes dict

500K trips × avg path length 50 nodes × ~10 bytes per node_id ≈ 250 MB
in RAM. Fits comfortably in any reasonable allocation. The JSONL
on-disk size is similar (~400 MB at 500K).

### Backward compatibility

The adapter functions keep their pre-Phase-14 signature working when
`canonical_routes=None` (default). Standalone CLI users
(`python -m adapters.sumo.cli ...`) see no behavior change.

---

## 5. Measurement plan

After Phase 14 lands, re-run the benchmark to quantify the speedup:

1. **Baseline**: the chicago_200k_car job (9332478) currently running.
   Captures pre-Phase-14 wall on Cardinal Xeon Max 9470.
2. **Post Phase 14**: re-submit `cluster/jobs/benchmark_large_chicago_200k.sbatch`
   (after cache invalidation). Compare cold-prep wall.
3. **Post Phase 14**: re-submit `cluster/jobs/benchmark_large_nyc_500k.sbatch`
   with the cancelled run's full matrix. Compare against the
   extrapolated Pitzer pre-Phase-14 baseline (600 h).

Numbers go into:
- `CHANGELOG.md` Phase 14 entry, in a measured-speedup table.
- `doc/chapters/methods.md` §3.X — added as the engineering
  contribution narrative (problem → measurement → fix → re-measurement).
- `doc/chapters/results.md` — referenced if the speedup affects any
  Chapter 5 figure (e.g., Fig 5.10 wall-vs-engine breakdown gains a
  Phase 14 column).

The thesis defense story: "we built the cross-engine fairness
contract; measured a previously-uncosted duplication in BFS routing;
deduplicated and parallelized; re-measured a 30-40× speedup on
large-tier cold prep; verified byte-identity of the produced routes."

---

## 6. Open questions

- **Should the Phase 12 per-engine `.cache/<engine>/` layer be deprecated
  after Phase 14?** It currently caches the *full adapter output* (XML
  files), which is still useful when re-running the same engine with a
  different seed. Decision: keep it. Phase 14 sits *above* it.

- **Worker count default**: 16 matches the typical SBATCH `--cpus-per-task`
  but might over-parallelize on small bundles. Likely use `min(workers,
  feasible_count // 1000)` to skip the multiprocessing overhead when
  there are too few trips. Decision pending Phase 14.5 measurement.

- **Cache eviction**: how to clean stale `canonical_routes_<hash>.jsonl`
  files when bundles are regenerated. For now: human-driven `rm -rf
  runs/*/.canonical_routes/`. Future: add a `tools/clean_caches.py`
  with an `--older-than` flag.
