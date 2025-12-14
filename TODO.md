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

- [ ] Create base folders: `canonical/`, `adapters/`, `pipeline/`, `execution/`, `evaluation/`, `scenarios/`
- [ ] Add `README.md` with a short project description

#### 2. Canonical schema v0 docs

- [ ] `canonical/schema/network_v0.md` — nodes, links, CRS, units, required attributes
- [ ] `canonical/schema/demand_v0.md` — `trip_id`, `origin_node_id`, `destination_node_id`, `departure_time_s`, `mode`
- [ ] `canonical/schema/signals_v0.md` — `signal_controller`, phases, link references
- [ ] `canonical/schema/config_v0.md` — `scenario_id`, `city`, `tier`, `horizon_start_s`, `horizon_end_s`, `time_step_s`, `random_seed`, `crs`, `schema_version`
- [ ] `canonical/schema/manifest_v0.md` — file list, `sha256`, roles, generator metadata

#### 3. Toy scenario bundle (`toy_2x2_grid`)

- [ ] `scenarios/toy_2x2_grid/network.xml` — small 2×2-style network (3–5 nodes, a few links)
- [ ] `scenarios/toy_2x2_grid/demand.csv` — 10–20 trips with basic fields
- [ ] `scenarios/toy_2x2_grid/signals.xml` — 1 signal controller with 2 phases
- [ ] `scenarios/toy_2x2_grid/config.xml` — simple horizon, time step, seed
- [ ] `scenarios/toy_2x2_grid/manifest.xml` — list files and placeholder or real `sha256` hashes

#### 4. Validator v0

- [ ] Implement `pipeline/validation/validate_bundle.py`:
  - [ ] Load `network.xml`, `demand.csv`, `signals.xml`, `config.xml`, `manifest.xml`
  - [ ] Check: `origin_node_id` and `destination_node_id` exist in `network.xml`
  - [ ] Check: CRS present in `network.xml` or `config.xml`
  - [ ] Check: basic unit strings (e.g., `"meters"`, `"seconds"`) are present
  - [ ] Check: each file listed in `manifest.xml` actually exists
- [ ] Add SHA256 hash computation for files and compare to manifest if hashes are present
- [ ] CLI: `python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid` should print `VALID` or clear error messages

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

- [ ] Install SUMO locally or define a SUMO Docker image.
- [ ] Manually run a tiny SUMO example to confirm the install works.

#### 2. Mapping design: canonical → SUMO

- [ ] Create `adapters/sumo/MAPPING.md` describing:
  - [ ] How `network.xml` maps to SUMO network (nodes, edges, lanes, speeds).
  - [ ] How `demand.csv` maps to `.rou.xml` (trips or flows).
  - [ ] How `signals.xml` maps to SUMO traffic lights.
  - [ ] How `config.xml` maps to `.sumocfg` (horizon, time step, seed).

#### 3. SUMO adapter implementation

- [ ] Implement `adapters/sumo/build_sumo_inputs.py`:
  - [ ] Read canonical bundle path.
  - [ ] Generate SUMO network, route, and config files in a deterministic way.
  - [ ] Log key mapping decisions (default lane count, signal mapping, etc.).
- [ ] Add a simple test or script to compare hashes of outputs across two runs to confirm determinism.

#### 4. End-to-end SUMO run (toy)

- [ ] Validate bundle:
  - [ ] `python pipeline/validation/validate_bundle.py scenarios/toy_2x2_grid`
- [ ] Generate SUMO inputs:
  - [ ] `python adapters/sumo/build_sumo_inputs.py scenarios/toy_2x2_grid`
- [ ] Run SUMO on the generated config (e.g., `sumo -c toy.sumocfg` or equivalent).
- [ ] Confirm simulation completes and produces some outputs (even simple summary).

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

- [ ] Choose City 1 and define a clear AOI.
- [ ] Download OSM extract for the AOI.
- [ ] Implement `pipeline/network/build_network_from_osm.py` to:
  - [ ] Clip AOI and extract nodes/links.
  - [ ] Convert to canonical `network.xml` using schema v0.
- [ ] Run the validator to check `network.xml` + corresponding `config.xml`.

#### 2. Synthetic demand v0 (City 1, lowest tier)

- [ ] Implement `pipeline/demand/generate_synthetic_demand.py`:
  - [ ] Start from simple OD zones or distributions.
  - [ ] Generate ~50k trips following the canonical demand schema.
  - [ ] Use a fixed seed and record it in `config.xml` and `manifest.xml`.
- [ ] Validate:
  - [ ] All origin/destination node IDs exist in `network.xml`.
  - [ ] Row count roughly matches planned tier size.

#### 3. Signals v0 (City 1)

- [ ] Implement `pipeline/signals/build_signals_default.py`:
  - [ ] Either parse existing signals (if available) or apply a consistent default template.
- [ ] Validate:
  - [ ] Signal controller node IDs exist in `network.xml`.
  - [ ] Link references exist for each phase.

#### 4. Bundle builder

- [ ] Implement `pipeline/scenariobuilder/build_bundle.py` to:
  - [ ] Assemble `network.xml`, `demand.csv`, `signals.xml`, `config.xml`, `manifest.xml` into `scenarios/city1_tier50k/`.
  - [ ] Populate `manifest.xml` with file hashes and basic metadata.
- [ ] Run `validate_bundle.py` on the full City 1 bundle.

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

- [ ] Define `runspecs/runspec_city1_toy.xml` (or `.csv`) with fields like:
  - [ ] `scenario_id`
  - [ ] `engine` (e.g., `sumo`)
  - [ ] `environment` (e.g., `local_cpu`)
  - [ ] `repeats`
  - [ ] `seed` or seed pattern

#### 2. Execution harness

- [ ] Implement `execution/run_benchmark.py`:
  - [ ] Parse a runspec entry.
  - [ ] Validate the referenced canonical bundle.
  - [ ] Call the correct adapter (e.g., SUMO).
  - [ ] Launch the simulator with appropriate command.
  - [ ] Store outputs under a structured path, e.g.:
    - `runs/<scenario>/<engine>/<env>/<seed>/`

#### 3. Metrics library (v0)

- [ ] Fidelity metrics in `evaluation/metrics/fidelity.py`:
  - [ ] Implement RMSE helper.
  - [ ] Implement GEH helper.
  - [ ] Implement KS statistic helper.
- [ ] Scalability metrics in `evaluation/metrics/scalability.py`:
  - [ ] Compute runtime, vehicles/sec.
  - [ ] Add hooks for per-core/per-watt when hardware info is available.
- [ ] Reproducibility metrics in `evaluation/metrics/reproducibility.py`:
  - [ ] Implement `R = 1 − σ/μ` for repeated runs.
- [ ] Write small tests using toy or synthetic outputs to confirm functions work.

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

- [ ] Document differences from SUMO in `adapters/qarsumo/MAPPING.md`.
- [ ] Implement `adapters/qarsumo/build_qarsumo_inputs.py` (can reuse SUMO mapping heavily).
- [ ] Confirm deterministic behavior on toy scenario.
- [ ] Run toy + City 1 tier 50k on CPU vs GPU and store outputs.

#### 2. MATSim adapter

- [ ] Design mapping in `adapters/matsim/MAPPING.md`:
  - [ ] Canonical network → MATSim network.
  - [ ] `demand.csv` → MATSim `plans.xml`.
  - [ ] `config.xml` → MATSim config (iterations, replanning, etc.).
- [ ] Implement `adapters/matsim/build_matsim_inputs.py`.
- [ ] Validate toy + City 1 with MATSim and ensure runs complete.

#### 3. Expand canonical bundles to all cities & tiers

- [ ] Build canonical bundles for City 2 (tiers 50k, 500k, 5M).
- [ ] Build canonical bundles for City 3 (tiers 50k, 500k, 5M).
- [ ] Ensure validator passes on all 3×3 bundles.

#### 4. Full run matrix definition

- [ ] Create a master runspec file capturing:
  - [ ] 3 cities × 3 tiers × selected engines × environments (CPU/GPU/HPC).
  - [ ] Repeats per scenario.

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

- [ ] Turn schema docs into formal text for the Methods chapter (canonical bundle, validation).
- [ ] Document adapter contracts and mapping rules per engine.
- [ ] Describe execution harness, environments (CPU/GPU/HPC), and containerization.

#### 2. Experiments & results chapters

- [ ] Describe experiment design and run matrix.
- [ ] Define which tables and plots you will include (fidelity, scalability, reproducibility, trade-offs).
- [ ] As results become available, fill in tables/figures rather than waiting until the end.

#### 3. Packaging & release

- [ ] Clean up repo (folder names, README, docs).
- [ ] Write a short “Reproducing this thesis” guide.
- [ ] Tag a release (e.g., `v1.0.0-thesis`) that corresponds to the final state used in the thesis.

### Definition of Done

- Thesis draft contains complete Methods and Experiments sections that match the actual implementation.
- Final results are plotted and integrated into the thesis.
- The code repository is in a state where someone else can run at least one benchmark scenario without your help.
