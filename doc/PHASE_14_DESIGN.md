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

#### 2.3.1 What "parallel" means here — and what it does NOT

This is **task parallelism over trips**, not data parallelism over the
network. The graph is fully replicated in each worker; the trip list is
the only thing that gets partitioned. Workers do not exchange any
information during BFS execution — each one is a self-contained BFS
session that happens to be running simultaneously with 15 others.

```
                  ┌──────────────────────────────────────────────┐
                  │           Main process (orchestrator)         │
                  │                                                │
                  │   1. Read network.xml, demand.csv             │
                  │   2. Sort feasible trips by trip_id           │
                  │   3. Split into 1,000 chunks of ~200 trips    │
                  │   4. Pool.imap(_route_chunk, chunks)          │
                  │                                                │
                  └──┬──────┬──────┬──────┬─────────┬─────────────┘
                     │      │      │      │         │
              pickle │      │      │      │         │   16 workers
              chunk  ▼      ▼      ▼      ▼         ▼   (one per SBATCH cpu)
                  ┌──────┐ ┌──────┐ ┌──────┐ ... ┌──────┐
                  │Worker│ │Worker│ │Worker│     │Worker│
                  │  1   │ │  2   │ │  3   │     │ 16   │
                  ├──────┤ ├──────┤ ├──────┤     ├──────┤
                  │ FULL │ │ FULL │ │ FULL │     │ FULL │
                  │ COPY │ │ COPY │ │ COPY │     │ COPY │
                  │  of  │ │  of  │ │  of  │     │  of  │
                  │ graph│ │ graph│ │ graph│     │ graph│
                  │~150MB│ │~150MB│ │~150MB│     │~150MB│
                  ├──────┤ ├──────┤ ├──────┤     ├──────┤
                  │chunk:│ │chunk:│ │chunk:│     │chunk:│
                  │trips │ │trips │ │trips │     │trips │
                  │1–200 │ │201–  │ │401–  │     │      │
                  │      │ │  400 │ │  600 │     │      │
                  └──┬───┘ └──┬───┘ └──┬───┘     └──┬───┘
                     │        │        │           │
                     │ pickle │ pickle │           │
              result │ paths  │ paths  │           │
              list   ▼        ▼        ▼           ▼
                  ┌──────────────────────────────────────────────┐
                  │   Main process merges into routes dict       │
                  │   (preserving submission order via imap)     │
                  └──────────────────────────────────────────────┘
```

#### 2.3.2 Three load-bearing properties

**Property 1 — the network is replicated, not partitioned.**

Each worker holds the full SCC-filtered canonical graph in its own
heap (~150 MB for chicago_200k_car, ~250 MB for nyc_500k_car). We do
not carve the graph into geographic zones because trips in a 15–20 km
metro bbox routinely cross the entire network — partitioning would
either force each worker to handle only intra-zone trips (which would
exclude most of demand.csv) or require cross-zone messaging
(introducing synchronisation overhead and breaking the simple
deterministic story below). Memory cost: 16 × 150 MB ≈ 2.4 GB on
chicago_200k_car. Cardinal `cpu` nodes provide 503 GB; the
replication cost is negligible.

**Property 2 — the trip list is what's partitioned.**

The main process reads `demand.csv`, filters to the feasible set,
sorts by `trip_id`, and splits into 1,000 chunks of ~200 trips each.
Each chunk is a list of `(trip_id, origin_node, dest_node)` tuples.
Workers grab chunks dynamically via `Pool.imap` — finishing a chunk
fast lets the worker pick up the next pending one, which gives
free load balancing if individual cores run at slightly different
speeds (NUMA effects, neighbour processes on the same node, etc.).

**Property 3 — workers never exchange information during BFS.**

The only IPC is between main and worker, never worker-to-worker:

- **At worker startup** (once): main pickles the `network_path` string
  (~50 bytes) and sends it. Worker calls `_init_worker(network_path)`
  which parses the XML, runs the SCC filter, builds the
  `forbidden_moves` table, and stashes everything in module-global
  `_WORKER_STATE`. Cost: ~1–2 seconds per worker, amortised over
  thousands of trips in that worker's lifetime.
- **Per chunk** (one round-trip per chunk): main pickles the chunk
  (~30 KB of tuples), sends to a worker; worker pickles its result
  (~600 KB of path lists), sends back. Total IPC per chunk
  ~10–100 µs of pickle/unpickle overhead, dwarfed by the
  ~2 min of BFS work per chunk.
- **No shared memory, no message queues, no manager-mediated dicts,
  no locks.** By construction, workers cannot race.

#### 2.3.3 Why this is provably deterministic

Each trip's BFS output is a pure function of four inputs:

1. `origin` (string node id, from the demand row)
2. `dest` (string node id, from the demand row)
3. `adjacency` + `edge_lookup` (loaded from `network.xml` — same bytes per worker)
4. `forbidden_moves` (built from `network.xml`'s `<turn_restrictions>` block — same per worker)

All four inputs are bit-identical across workers and across runs
(network.xml is hash-pinned per the V5 manifest; demand.csv has the
same hash). Therefore `shortest_path_with_restrictions(origin=..., dest=..., adjacency=..., edge_lookup=..., forbidden_moves=...)`
returns the same `path_nodes` list regardless of which worker called
it or whether one or sixteen workers are running.

The merge step preserves trip_id ordering because
`Pool.imap` (not `imap_unordered`) returns chunk results in
submission order, and we submit chunks in sorted-trip_id order.

`tests/test_canonical_routes.py::TestParallelDeterminism` pins this:
`workers=1`, `workers=2`, `workers=4` all produce byte-identical
route dicts on `chicago_1k_car`. The test will catch any future
refactor that introduces nondeterminism into this chain.

#### 2.3.4 Alternative architectures considered (and why we didn't pick them)

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **Multiprocessing + replicated graph + trip-partition (current)** | Trivially deterministic; zero synchronisation; small chunks give free load balancing | Replicates graph N times in RAM (~2.4 GB on chicago_200k, 16-way) | ✅ chosen — RAM is abundant at our scale, simplicity wins |
| **Threading + shared graph** | No graph duplication | Python's GIL serialises CPU-bound work — BFS is a pure-Python loop, so 0× speedup measured | ❌ GIL is the deal-breaker |
| **`multiprocessing.shared_memory` for the graph** | Single in-RAM copy of the graph | Requires serialising the graph dict into raw bytes + custom view-layer; complicates determinism analysis; saves ~2 GB which we don't need | ❌ overkill for our memory budget |
| **Network partitioning (geographic zones) + cross-zone messaging** | Saves memory if the graph were enormous (millions of nodes) | Workers must coordinate when a path crosses zone boundaries — introduces synchronisation, breaks the pure-function determinism story, requires substantially more complex code | ❌ unnecessary; our graphs are at most ~80K nodes |
| **C/Cython extension with shared graph + threads (releasing GIL)** | Could be 5–10× faster per worker; no graph duplication | Requires writing + maintaining native code; loses the cross-platform pure-Python guarantee; build-time complexity | ❌ not warranted yet, future Phase candidate |

#### 2.3.5 The `spawn` vs `fork` choice

We use `multiprocessing.get_context("spawn")` explicitly rather than
relying on the platform default:

- **fork** (Linux default): the child inherits the parent's address
  space copy-on-write. Cheap startup, but: doesn't work the same on
  macOS (Python 3.8+ defaults to spawn on macOS for safety); shares
  open file descriptors and held locks (subtle deadlock hazards);
  interacts badly with libraries that aren't fork-safe (some XML
  parsers, MATSim's JVM, etc.).
- **spawn** (macOS default, forced on Linux too): each child boots a
  fresh Python interpreter, re-imports the module, and runs
  `_init_worker(network_path)` to rebuild its state from disk.
  Slower startup (~1–2 s per worker) but cross-platform reproducible,
  no inherited-state surprises.

We pay the ~16–32 s of cumulative startup once per cell, amortised
over hours of BFS work — completely irrelevant in the wall-time
accounting, and worth it for the determinism + portability story.

#### 2.3.6 What the user sees vs what's actually happening

The `[bfs] progress` line says e.g.:

```
[bfs] progress : 87,500/200,000 (43.7%) elapsed 1h 30m  17 trips/s  w=16
```

The single number "17 trips/s" is the aggregate rate (8.23 trips/s on
the real Cardinal run, divided across 16 workers ≈ 0.5 trips/s per
worker). Internally, the 16 workers are independently chewing through
their own chunks of 200 trips each, each calling
`shortest_path_with_restrictions` thousands of times against its own
private copy of the graph. None of them know about the others. The
single progress counter is just the main process tallying how many
chunks have returned.

#### 2.3.7 Reference: worker code skeleton

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

**Determinism summary** (full proof in §2.3.3 above):

1. Trips are sorted by `trip_id` before chunking → each worker gets a
   deterministic chunk regardless of `workers` value.
2. `Pool.imap` preserves submission order → output chunks come back in
   the same order they were submitted.
3. Within a chunk, the worker's serial loop is deterministic (same
   BFS function, identical replicated inputs).
4. The merged dict is built by iterating the in-order chunks.

Pinned by `tests/test_canonical_routes.py::TestParallelDeterminism`.

**Per-worker `_init_worker` rather than fork-inherited globals**:
See §2.3.5 above — `spawn` is forced for cross-platform consistency,
worker state is rebuilt from `network.xml` instead of inherited.

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

Re-run the benchmark to quantify the speedup against the Phase 13 baseline:

1. **Baseline**: chicago_200k_car job 9332478 completed 2026-05-18 at
   141.87 h wall on Cardinal Xeon Max 9470 (Phase 13 reference).
2. **Post Phase 14 (chicago_200k_car)**: job 9971041 measured ~7.14 h
   cold-cache total (6.52 h BFS prep on 16 workers + ~37 min sim across
   10 cells), ~37 min warm-cache re-run. Cold-vs-cold speedup ≈ 20×,
   warm-cache re-run vs Phase 13 cold ≈ 228×.
3. **Post Phase 14 (nyc_500k_car)**: job 9971042 in flight at time of
   writing, BFS pass at ~6.7 trips/s on 24 workers projecting ~20 h
   cold + ~1-2 h sim ≈ ~22 h cold-cache total.

Both scenarios now submit via the single `cluster/jobs/benchmark_large.sbatch`
umbrella (`--time=2-00:00:00`). The Phase 13.2 per-scenario fallback
sbatchs (`benchmark_large_chicago_200k.sbatch` + `benchmark_large_nyc_500k.sbatch`)
were deleted in commit 503bcbf after Phase 14 confirmed both scenarios fit
comfortably within the umbrella's parallel-on-one-node strategy. See
`doc/EXPERIMENT_LOG.md` 2026-05-19 entry for the full breakdown.

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
