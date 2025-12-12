# SIMFORGE

**SIMFORGE** is a reproducible cross-simulator testing framework for **urban commute simulation**.

It does **not** implement a new traffic simulator.  
Instead, it provides a standardized way to:

- Define **canonical scenarios** (network, demand, signals, config, manifest)
- Convert them into **engine-native inputs** via deterministic adapters
- Run engines on **CPU, GPU, and HPC** under controlled conditions
- Evaluate **fidelity, scalability, and reproducibility** with consistent metrics

This repository contains the code and artifacts for my MS thesis.

---

## Goals

SIMFORGE aims to:

1. **Standardize inputs**  
   A canonical bundle (XML/CSV/JSON) that all supported simulators can consume.

2. **Enforce reproducibility**  
   Deterministic adapters, pinned containers, and a validation pipeline that catches broken scenarios before they run.

3. **Enable fair comparison**  
   Same city, same demand, same signals, same environment → differences come from the **engines**, not from experiment noise.

4. **Provide reusable benchmarks**  
   Scenarios and pipelines that others can extend with new simulators, cities, or hardware.

---

## High-Level Architecture

The framework is organized into five main pieces:

1. **Canonical Schema & Bundles**

   - `network.xml` — nodes, links, geometry, capacities
   - `demand.csv` — trip-level demand (origins, destinations, departure times, modes)
   - `signals.xml` — signal controllers, phases, timings
   - `config.xml` — global scenario settings (horizon, time step, seeds, CRS)
   - `manifest.xml` — file hashes, roles, and provenance

2. **Validation Pipeline**

   - Checks ID consistency, CRS and units, and referential integrity
   - Verifies file hashes against the manifest
   - Rejects broken scenarios before any simulator runs

3. **Deterministic Adapters**

   - Engine-specific scripts that map the canonical bundle → engine-native inputs
   - Same canonical input → same native files (byte-for-byte)
   - Per-engine mapping rules documented in `MAPPING.md` files

4. **Execution Harness**

   - Reads a run specification (scenario, engine, environment, seed)
   - Validates the bundle, runs the adapter, launches the simulator
   - Stores outputs in a structured directory layout for analysis

5. **Metrics & Evaluation**
   - Fidelity: RMSE, GEH, KS
   - Scalability: runtime, throughput (vehicles/sec, per core, per watt when available)
   - Reproducibility: stability score \( R = 1 - \sigma / \mu \) across repeated runs

---

## Repository Structure

Planned structure (will evolve as the project matures):

```text
canonical/
  schema/           # Markdown docs describing v0 schema for each file type
  examples/         # Small example bundles or schema snippets

scenarios/
  toy_2x2_grid/     # Toy scenario for end-to-end testing
  city1_tier50k/    # Real city scenarios (later: multiple cities, tiers)
  ...

pipeline/
  validation/       # validate_bundle.py and helpers
  network/          # OSM → canonical network
  demand/           # OD/synthetic demand → canonical demand.csv
  signals/          # DOT or defaults → canonical signals.xml
  scenariobuilder/  # Orchestrate building complete canonical bundles

adapters/
  sumo/             # SUMO adapter + MAPPING.md
  qarsumo/          # QarSUMO adapter (GPU/parallel)
  matsim/           # MATSim adapter
  ...

execution/
  runspecs/         # JSON/CSV run definitions
  run_benchmark.py  # Orchestration entrypoint

evaluation/
  metrics/          # Fidelity, scalability, reproducibility metrics
  plots/            # Plotting scripts / notebooks for results

docs/
  thesis_notes/     # Notes that map implementation → thesis text
  diagrams/         # Architecture diagrams, figures for the thesis

TODO.md             # Project milestones and task checklist
README.md           # This file
```
