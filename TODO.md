# SimForge TODO

High-level phases:

1. Canonical schema & toy scenario
2. City-scale canonical bundles
3. Adapters & containers
4. Execution harness & metrics
5. Full experiments (3 cities × 3 tiers)
6. Thesis writing & packaging

---

## Milestone 1 — Canonical Schema v0 & Toy Scenario

### Goal

Define the first version of the canonical schema and build a validated toy scenario bundle, plus a basic validator script. This is the foundation for everything else.

### Tasks

#### 1. Repo & structure

- [x] Create base folders: `canonical/`, `adapters/`, `pipeline/`, `execution/`, `evaluation/`, `scenarios/`
- [x] Add `README.md` with a short project description

#### 2. Canonical schema v0 docs

- [x] `canonical/schema/network_v0.md` — nodes, links, CRS, units, required attributes
- [x] `canonical/schema/demand_v0.md` — `trip_id`, `origin_node_id`, `destination_node_id`, `departure_time_s`, `mode`
- [x] `canonical/schema/signals_v0.md` — `signal_controller`, phases, link references
- [x] `canonical/schema/config_v0.md` — `scenario_id`, `city`, `tier`, `horizon_start_s`, `horizon_end_s`, `time_step_s`, `random_seed`, `crs`, `schema_version`
- [x] `canonical/schema/manifest_v0.md` — file list, `sha256`, roles, generator metadata

#### 3. Toy scenario bundle (`toy_2x2_grid`)

- [x] `scenarios/toy_2x2_grid/network.xml` — small 2×2-style network (3–5 nodes, a few links)
- [x] `scenarios/toy_2x2_grid/demand.csv` — 10–20 trips with basic fields
- [x] `scenarios/toy_2x2_grid/signals.xml` — 1 signal controller with 2 phases
- [x] `scenarios/toy_2x2_grid/config.xml` — simple horizon, time step, seed
- [x] `scenarios/toy_2x2_grid/manifest.xml` — list files and placeholder or real `sha256` hashes

#### 4. Validator v0

- [x] Implement `pipeline/validation/validate_bundle.py`:
  - [x] Load `network.xml`, `demand.csv`, `signals.xml`, `config.xml`, `manifest.xml`
  - [x] Check: `origin_node_id` and `destination_node_id` exist in `network.xml`
  - [x] Check: CRS present in `network.xml` or `config.xml`
  - [x] Check: basic unit strings (e.g., `"meters"`, `"seconds"`) are present
  - [x] Check: each file listed in `manifest.xml` actually exists
- [x] Add SHA256 hash computation for files and compare to manifest if hashes are present
- [x] CLI: `python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid` should print `VALID` or clear error messages

### Definition of Done

- A toy scenario folder exists under `scenarios/toy_2x2_grid/` with all canonical files.
- `canonical/schema/*.md` clearly describe the v0 schema for each file.
- Running the validator on the toy scenario succeeds:
  - `python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid` → `VALID`.
- This toy bundle + validator can be reused later to test adapters.

---

## Milestone 2 — SUMO Adapter v0 (Toy Scenario End-to-End)

### Goal

Convert the toy canonical bundle into SUMO inputs deterministically and run SUMO locally end-to-end.

### Tasks

#### 1. SUMO environment

- [x] Install SUMO locally or define a SUMO Docker image.
- [x] Manually run a tiny SUMO example to confirm the install works.

#### 2. Mapping design: canonical → SUMO

- [x] Create `adapters/sumo/MAPPING.md` describing:
  - [x] How `network.xml` maps to SUMO network (nodes, edges, lanes, speeds).
  - [x] How `demand.csv` maps to `.rou.xml` (trips or flows).
  - [x] How `signals.xml` maps to SUMO traffic lights.
  - [x] How `config.xml` maps to `.sumocfg` (horizon, time step, seed).

#### 3. SUMO adapter implementation

- [x] Implement `adapters/sumo/sumo_adapter.py`:
  - [x] Read canonical bundle path.
  - [x] Generate SUMO network (via netconvert), route, and config files in a deterministic way.
  - [x] Log key mapping decisions (default lane count, signal mapping, etc.).
- [x] Add a simple test or script to compare hashes of outputs across two runs to confirm determinism.

#### 4. End-to-end SUMO run (toy)

- [x] Validate bundle:
  - [x] `python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid`
- [x] Generate SUMO inputs:
  - [x] `python -m adapters.sumo.cli scenarios/toy_2x2_grid out/`
- [x] Run SUMO on the generated config (e.g., `sumo -c toy.sumocfg` or equivalent).
- [x] Confirm simulation completes and produces some outputs (even simple summary).

### Definition of Done

- Running the SUMO adapter on the toy scenario always produces identical SUMO input files for the same canonical bundle.
- The toy scenario runs successfully in SUMO without manual tweaking.
- The mapping from canonical → SUMO is documented in `MAPPING.md`.

---

## Milestone 3 — City 1 Canonical Bundle (Real Network + Demand + Signals)

### Goal

Produce a validated canonical bundle for City 1 at the smallest demand tier (e.g., ~50k trips).

### Tasks

#### 1. Network from OSM

- [x] Choose City 1 and define a clear AOI.
- [x] Download OSM extract for the AOI.
- [x] Implement `pipeline/network/build_network_from_osm.py` to:
  - [x] Clip AOI and extract nodes/links.
  - [x] Convert to canonical `network.xml` using schema v0.
- [x] Run the validator to check `network.xml` + corresponding `config.xml`.

#### 2. Synthetic demand v0 (City 1, lowest tier)

- [x] Implement `pipeline/demand/generate_synthetic_demand.py`:
  - [x] Start from simple OD zones or distributions.
  - [x] Generate ~50k trips following the canonical demand schema.
  - [x] Use a fixed seed and record it in `config.xml` and `manifest.xml`.
- [x] Validate:
  - [x] All origin/destination node IDs exist in `network.xml`.
  - [x] Row count roughly matches planned tier size.

#### 3. Signals v0 (City 1)

- [x] Implement `pipeline/signals/build_signals_default.py`:
  - [x] Either parse existing signals (if available) or apply a consistent default template.
- [x] Validate:
  - [x] Signal controller node IDs exist in `network.xml`.
  - [x] Link references exist for each phase.

#### 4. Bundle builder

- [x] Implement `pipeline/scenariobuilder/build_bundle.py` to:
  - [x] Assemble `network.xml`, `demand.csv`, `signals.xml`, `config.xml`, `manifest.xml` into `scenarios/sioux_falls_tier50k/`.
  - [x] Populate `manifest.xml` with file hashes and basic metadata.
- [x] Run `validate_bundle.py` on the full City 1 bundle.

### Definition of Done

- A City 1 canonical bundle exists under `scenarios/city1_tier50k/`.
- The validator reports `VALID` on City 1 bundle with no manual hacks.
- Network, demand, and signals follow the documented v0 schemas.

---

## Milestone 4 — Execution Harness & Metrics Library

### Goal

Have a script that can run a scenario with a given engine and a metrics module that can evaluate outputs (even on toy or partial data).

### Tasks

#### 1. Run specification

- [x] Define `runspecs/runspec_city1_toy.xml` (or `.csv`) with fields like:
  - [x] `scenario_id`
  - [x] `engine` (e.g., `sumo`)
  - [x] `environment` (e.g., `local_cpu`)
  - [x] `repeats`
  - [x] `seed` or seed pattern

#### 2. Execution harness

- [x] Implement `execution/run_benchmark.py`:
  - [x] Parse a runspec entry.
  - [x] Validate the referenced canonical bundle.
  - [x] Call the correct adapter (e.g., SUMO, QarSUMO).
  - [x] Launch the simulator with appropriate command.
  - [x] Store outputs under a structured path, e.g.:
    - `runs/<scenario>/<engine>/<env>/<seed>/`

#### 3. Metrics library (v0)

- [x] Fidelity metrics in `evaluation/metrics/fidelity.py`:
  - [x] Implement RMSE helper.
  - [x] Implement GEH helper.
  - [x] Implement KS statistic helper.
- [x] Scalability metrics in `evaluation/metrics/scalability.py`:
  - [x] Compute runtime, vehicles/sec.
  - [x] Add hooks for per-core/per-watt when hardware info is available.
- [x] Reproducibility metrics in `evaluation/metrics/reproducibility.py`:
  - [x] Implement `R = 1 − σ/μ` for repeated runs.
- [x] Write small tests using toy or synthetic outputs to confirm functions work.

### Definition of Done

- You can trigger a benchmark run from a runspec file via `run_benchmark.py`.
- The harness successfully runs at least the toy scenario + City 1 low tier with SUMO.
- The metrics functions produce sensible numbers on test data.

---

## Milestone 5 — Additional Engines & Full Matrix Prep

### Goal

Add QarSUMO and MATSim adapters (at least for toy + City 1) and prepare for the 3 cities × 3 tiers experiment matrix.

### Tasks

#### 1. QarSUMO adapter

- [x] Document differences from SUMO in `adapters/qarsumo/MAPPING.md`.
- [x] Implement `adapters/qarsumo/qarsumo_adapter.py` (reuses SUMO adapter).
- [x] Confirm deterministic behavior on toy scenario.
- [x] Run toy + Sioux Falls tier 50k (falls back to SUMO without GPU).

#### 2. MATSim adapter

- [x] Design mapping in `adapters/matsim/MAPPING.md`:
  - [x] Canonical network → MATSim network.
  - [x] `demand.csv` → MATSim `plans.xml`.
  - [x] `config.xml` → MATSim config (iterations, replanning, etc.).
- [x] Implement `adapters/matsim/matsim_adapter.py`.
- [x] Integrated into benchmark harness (`execution/run_benchmark.py`).
- [x] Added CLI: `python -m adapters.matsim.cli scenarios/toy_2x2_grid out/matsim`.
- [x] Install MATSim JAR and validate toy + City 1 with MATSim runs complete.
  - MATSim 15.0 installed at `lib/matsim-15.0/matsim-15.0.jar`
  - Toy scenario validated: 6 trips, avg travel time 21s

#### 3. Expand canonical bundles to all cities & tiers

- [x] Build canonical bundles for City 2 (Austin TX) - tier 50k complete.
  - 44,861 nodes, 110,533 links, 50K trips, validated
- [x] Build canonical bundles for City 3 (Berlin Germany) - tier 50k complete.
  - 39,866 nodes, 103,309 links, 50K trips, validated
- [ ] Build 500k and 5M tiers for all cities (optional expansion).
- [x] Ensure validator passes on all completed bundles.

#### 4. Full run matrix definition

- [x] Create a master runspec file capturing:
  - [x] 3 cities × 5 engine/mode combos (SUMO micro/meso, QarSUMO micro/meso, MATSim meso).
  - [x] 3 repeats per scenario for reproducibility measurement.
  - Created `runspecs/thesis_benchmark_matrix.yaml` with 15 run configurations.

### Definition of Done

- QarSUMO and MATSim adapters work on toy + at least City 1 low tier.
- Canonical bundles exist and validate for all cities and tiers you plan to use.
- A full run matrix is defined, even if you later run a subset first.

---

## Milestone 6 — Thesis Writing & Packaging

### Goal

Keep writing and packaging in sync with implementation so the thesis and artifacts are ready together.

### Tasks

#### 1. Methods chapter

- [x] Turn schema docs into formal text for the Methods chapter (canonical bundle, validation).
  - Created `doc/chapters/methods.md` with comprehensive coverage of schema, validation, adapters, execution harness, and metrics.
- [x] Document adapter contracts and mapping rules per engine.
  - Documented SUMO, QarSUMO, and MATSim adapters with mapping tables in methods.md.
- [x] Describe execution harness, environments (CPU/GPU/HPC), and containerization.
  - Covered execution pipeline, environment configurations, and future containerization plans.

#### 2. Experiments & results chapters

- [x] Describe experiment design and run matrix.
  - Created `doc/chapters/experiments.md` with RQs, variables, and 108-cell run matrix.
- [x] Define which tables and plots you will include (fidelity, scalability, reproducibility, trade-offs).
  - Defined Table 4.1 (matrix), Table 4.2 (scenario properties), Table 4.3/4.4/4.5 (results by scenario), Figures 4.1-4.4 (plots).
- [ ] As results become available, fill in tables/figures rather than waiting until the end.
  - Templates ready; awaiting benchmark completion to fill in actual values.

#### 3. Packaging & release

- [x] Clean up repo (folder names, README, docs).
  - Updated README.md with comprehensive project documentation.
- [x] Write a short "Reproducing this thesis" guide.
  - Created `doc/REPRODUCING.md` with step-by-step instructions.
- [ ] Tag a release (e.g., `v1.0.0-thesis`) that corresponds to the final state used in the thesis.
  - Will tag after thesis finalization.

### Definition of Done

- Thesis draft contains complete Methods and Experiments sections that match the actual implementation.
- Final results are plotted and integrated into the thesis.
- The code repository is in a state where someone else can run at least one benchmark scenario without your help.
