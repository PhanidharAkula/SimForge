# Reproducing This Thesis

This guide explains how to reproduce all experiments from the SimForge thesis using the code in this repository.

## Prerequisites

### Hardware Requirements

**Minimum (for the bundled 1K scenarios + full unit suite):**

- Any modern laptop/desktop
- 8 GB RAM
- 5 GB disk space (caches included)

**Recommended (regenerating the larger 50K – 500K tiers):**

- 16+ GB RAM
- 50+ GB disk space
- (No GPU required — all three primary engines (SUMO, MATSim, DTALite) are CPU-only after the LPSim removal in Version_5)

### Software Requirements

| Software   | Version       | Required For                                            |
| ---------- | ------------- | ------------------------------------------------------- |
| Python     | 3.10+         | Framework                                               |
| SUMO       | 1.26+ (via `eclipse-sumo` in `requirements.lock`) | SUMO simulation                                         |
| Java       | 17+           | MATSim simulation                                       |
| Git        | 2.0+          | Repository cloning                                      |
| osmium-tool| 1.14+ (opt)   | Optional CLI sanity checks on PBFs; not required        |

Python dependencies (installed via `requirements.txt`):

| Package     | Version pin        | Used For                                                          |
| ----------- | ------------------ | ----------------------------------------------------------------- |
| `osmnx`     | `>=2.0,<3`         | OSM graph parsing + bbox truncation (network stage); v2.x positional `bbox=(W,S,E,N)` API |
| `osmium`    | `>=4.0` (pyosmium) | PBF slicing (`FileProcessor` + `BackReferenceWriter`)             |
| `networkx`  | (latest)           | Graph representation between osmnx and the canonical writer       |
| `geopandas` | `>=1.0,<2`         | Transitive dep of osmnx 2.x (we don't import it directly)          |
| `pandas`    | (latest)           | Demand + census data frames                                       |

---

## Quick Setup (5 minutes)

The canonical install path uses **`uv` + [`requirements.lock`](../requirements.lock)** so every machine ends up on byte-identical dep versions (Python 3.13.13 + 35 lockfile-pinned packages, plus `eclipse-sumo==1.26.0` installed separately because the eclipse-sumo wheel is manylinux_2_28_x86_64-only and cannot ship in a cross-platform lockfile).

> **Alternative:** for bit-identical reproduction of the thesis numbers, pull the pinned-digest container instead of installing host-side. See [`doc/CONTAINER_USAGE.md`](CONTAINER_USAGE.md) for the full workflow; the thesis-default image is `ghcr.io/phanidharakula/simforge:db8d786` and is recorded in [`lib/container/manifest.json`](../lib/container/manifest.json).

```bash
# Install uv (manages Python + venv; user-space, no admin)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

git clone <repo-url>
cd SimForge

uv python install 3.13                          # downloads Python 3.13.13
uv venv --python 3.13 .venv
source .venv/bin/activate

uv pip install --upgrade pip
uv pip install -r requirements.lock             # 35 lockfile-pinned packages
uv pip install eclipse-sumo==1.26.0             # SUMO wheel (separate; manylinux_2_28 only)

# Fetch the hash-pinned OSM PBFs (~2.1 GB across IL / NY / CA state extracts).
# Required before regenerating any scenario; skipped if files are already present.
python tools/download_osm.py

# Confirm the bundled scenario validates cleanly
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
# Expected: ✓ VALID

# Print the toolchain report (used to verify cross-machine parity — see §Cross-Platform Reproducibility below)
python tools/env_report.py
```

> **Why `uv` and the lockfile?** `requirements.txt` declares loose dep ranges for development; `requirements.lock` records the exact versions used to produce the thesis bundles. `uv` additionally installs the exact Python interpreter (3.13.13), so `python --version` matches across machines without depending on whatever the system Python happens to be.

(For a deeper install walkthrough, see [SETUP.md](../SETUP.md). For the OSM data source, coverage, and hash-pinning, see [doc/SCENARIO_GENERATION.md §4](SCENARIO_GENERATION.md).)

### Running vs. regenerating — PBF requirement

The pre-built `scenarios/*_1k_car/` bundles already contain `network.xml`; reproducing the published simulation results does **not** require any OSM data. You only need the PBFs when:

- Regenerating any scenario (e.g. `scripts/02_nyc_10k_car.py` onwards), **or**
- Running `python -m pipeline.network.warmup` against a scenario whose network was removed.

### Optional: pre-warm a scenario that was regenerated

The network stage is fully deterministic, so pre-warming is only necessary when a bundle has been (re)generated from scratch on a machine without a warm disk cache:

```bash
python -m pipeline.network.warmup            # warm every scenarios/* bundle
python -m pipeline.network.warmup --dry-run  # report only
```

If `osm_data/<state>-<date>.osm.pbf` is missing for a target city, the pipeline falls back to the Overpass API (slower, not hash-pinned). The fallback is intentionally preserved for cities we have not yet committed a PBF for.

---

## Installing Simulators

### SUMO

**Already done.** `eclipse-sumo==1.26.0` is in [`requirements.lock`](../requirements.lock); the `uv pip install -r requirements.lock` step above installs the SUMO binary into `.venv/bin/sumo` and `.venv/bin/netconvert` automatically. No `brew install sumo` or `apt install sumo` needed. Same wheel works on macOS arm64 and Linux x86_64.

Verify:

```bash
sumo --version       # Eclipse SUMO sumo 1.26.0
netconvert --version # Eclipse SUMO netconvert 1.26.0
```

### MATSim

The MATSim 15.0 release JAR lives under `lib/matsim-15.0/` (gitignored). Download once:

```bash
mkdir -p lib
curl -L -o matsim-15.0-release.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip
unzip matsim-15.0-release.zip -d lib/
rm matsim-15.0-release.zip
```

Verify Java + the JAR:

```bash
java -version                                 # openjdk 17.x or newer
ls lib/matsim-15.0/matsim-15.0.jar            # should exist
```

### DTALite (CPU)

DTALite is the 3rd primary engine in Version_5: CPU mesoscopic Dynamic Traffic Assignment, Apache 2.0 licensed, bundled inside [`path4gmns`](https://github.com/jdlph/Path4GMNS).

**Pinned for reproducibility** in [`lib/dtalite/manifest.json`](../lib/dtalite/manifest.json):

```json
{"dtalite": {
  "path4gmns_version": "0.10.0",
  "upstream_repo":    "https://github.com/jdlph/Path4GMNS",
  "dtalite_repo":     "https://github.com/asu-trans-ai-lab/DTALite",
  "binary":           "DTALiteClassic (mode 1: path-based UE)",
  "format_standard":  "GMNS",
  "license":          "Apache-2.0"
}}
```

Install:

```bash
uv pip install path4gmns
# On macOS the bundled binary needs the OpenMP runtime:
brew install libomp
```

The pinned version also lives in `requirements.lock` so a fresh `uv pip sync requirements.lock` brings it in. The adapter at `adapters/dtalite/` auto-detects the bundled binary via `is_dtalite_available()`. With path4gmns not installed, every `dtalite` cell records a clean failure with the install command — there is no silent fallback.

> Versions 1–4 reserved this slot for LPSim (GPU mesoscopic). After exhaustive Pitzer debugging, LPSim was abandoned in Version_5 — the bundled `LivingCity` binary crashed on networks larger than a few-K nodes, and an in-container source rebuild SIGSEGV'd at first kernel launch. Full retrospective: [`doc/engines/LPSIM_RETROSPECTIVE.md`](engines/LPSIM_RETROSPECTIVE.md). Selection rationale for DTALite over the alternative third engines (CityFlow, POLARIS): [`doc/engines/THIRD_ENGINE_OPTIONS.md`](engines/THIRD_ENGINE_OPTIONS.md).

### V5 realism phases (affect bundle hashes)

Beyond the engine swap, Version_5 ships a sequence of demand- and
network-generation realism upgrades. Each phase modifies the *generated*
bundle and is reflected in `manifest.xml`'s SHA-256:

| Phase | What changed | File(s) |
|---|---|---|
| 5  | JWTRNS code mapping fixed using cityscape Schedule-generator branch (6 of 12 codes were wrong pre-V5: e.g., bus → transit, walk → walk, WFH → excluded). Corrects ~30-40 % drift in eligible commuter pool size on Chicago. | `pipeline/demand/parse_model_file.py` |
| 6  | OSM-grounded signal placement: `network.xml` `<node has_signal="true">` set populated from real `highway=traffic_signals` OSM tags. signals.xml signalizes only those (was: every `degree ≥ 4` node, ~85 %). Empirical drop: chicago 85 → 2.8 %; LA 85 → 1.4 %. | `pipeline/network/load_network_from_pbf.py`, `pipeline/signals/build_signals_default.py` |
| 7  | OSM turn restrictions: new `<turn_restrictions>` block in `network.xml`. SUMO + MATSim adapters enforce via state-aware BFS pre-routing; DTALite emits sibling `movement.csv` (path4gmns 0.10.0 doesn't ingest — documented asymmetry). | `pipeline/network/turn_restrictions.py`, all three adapters |
| 8  | PUMS-grounded per-person departure times: `departure = arrival_s − commute_min × 60`. Replaces V4 Gaussian peak. | `pipeline/demand/generate_census_demand.py` |
| 9a | PM HBW return trips read cityscape `schedule[1]` (work → home @ 17:00). | same |
| 9b | HBSchool_AM chains: parents with AGEP<18 dependents emit 2-row `home → school + school → work`. | same |
| 9c | HBSchool_PM chains: symmetric `work → school + school → home`. | same |
| 10 | Audit-tooling wiring: `evaluation/demand_composition.py` (new), Q5 section in `audit_fairness`, demand-composition table in `analyze_benchmark`. | `evaluation/` |

The committed `chicago_1k_car/`, `nyc_10k_car/`, and `la_50k_car/`
bundles are V5+ (regenerated 2026-04-30 onwards) — their hashes will
not match a V4 `generate.py` run. The two largest tiers
(`chicago_200k_car/`, `nyc_500k_car/`) are gitignored and must be
regenerated locally or on Pitzer/Cardinal with the current code path
before benchmarking; see `scripts/04_chicago_200k_car.py` and
`scripts/05_nyc_500k_car.py` for the canonical generation commands
(or `cluster/jobs/04_chicago_200k_car.sbatch` /
`cluster/jobs/05_nyc_500k_car.sbatch` for HPC).

---

## Running the Canonical Benchmark

The thesis figures are produced by `runspecs/benchmark_small.yaml` — an
11-cell matrix across the three reference scenarios:

- `chicago_1k_car × {SUMO meso, SUMO micro, MATSim meso, DTALite meso}` (4 cells)
- `nyc_10k_car   × {SUMO meso, SUMO micro, MATSim meso, DTALite meso}` (4 cells)
- `la_50k_car    × {SUMO meso,             MATSim meso, DTALite meso}` (3 cells; SUMO micro skipped at 50K — wall-times past 4 h on arm64)

with **N=5 repeats per cell** = 55 runs total.

```bash
# 1. Sanity check (one run, ~30 s)
python run.py --scenario chicago_1k_car --engine sumo --mode meso --repeats 1

# 2. Full benchmark (~1 minute on a laptop, ~2 minutes on cluster CPU)
python -m execution.run_benchmark runspecs/benchmark_small.yaml

# 3. Generate analysis tables
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json

# 4. Audit cross-engine fairness (Q1: same trip set, Q2: same network,
#    Q3: same trip count, Q4: paradigm-spread travel-time ratios,
#    Q5: V5+ demand composition / trip-purpose breakdown)
python -m evaluation.audit_fairness runs/benchmark_small

# 5. Render the 10 thesis figures
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json

# 6. (Optional, Wave 1+) The reproducibility scorecard is auto-emitted by
#    run_benchmark next to benchmark_results_*.json. Regenerate manually if
#    needed (e.g., from a run dir copied across hosts):
python -m tools.generate_scorecard runs/benchmark_small
# Produces runs/benchmark_small/reproducibility_scorecard.md with provenance
# hashes + environment + Q1 byte-identity verdict + R = 1 − CV per cell
# + pass/warn/fail rollup.
```

---

## Generating the Larger Tiers (Optional)

The repo only commits the `chicago_1k_car` bundle. To recreate the 10K/50K/200K/500K tiers used for scalability discussion:

```bash
python scripts/02_nyc_10k_car.py     # 10K NYC car, 7–9 AM
python scripts/03_la_50k_car.py # 50K LA car+transit+bike, 6–10 AM
python scripts/04_chicago_200k_car.py    # 200K Chicago car+transit, 24 h
python scripts/05_nyc_500k_car.py       # 500K NYC car, 6–10 AM
```

Each writes a fresh bundle into `scenarios/<id>/` and is then runnable through `run.py` or by adding it to a runspec.

> **Apple Silicon caveat:** `netconvert` on macOS arm64 has historically segfaulted on large networks (>~3,000 nodes) under SUMO 1.20.x; behaviour under the locked SUMO 1.26.0 wheel may differ but has not been re-verified at scale. The 1K bundles run cleanly on Mac; for the 200K and 500K tiers, run on Linux/HPC (Pitzer) where the same `eclipse-sumo` wheel installs without the macOS-specific issue.

### Regenerating on a Supercomputer (OSC Pitzer)

The 200K and 500K tiers were produced on the Ohio Supercomputer Center's Pitzer cluster. The full workflow — module setup, PBF / ModelGen rsync, per-tier SLURM templates, monitoring, and troubleshooting — is documented in [doc/PITZER.md](PITZER.md). Short version:

```bash
# From your laptop
rsync -avh osm_data/   pitzer:SimForge/osm_data/
rsync -avh modelgen/   pitzer:SimForge/modelgen/

# On Pitzer (login node)
module load python/3.12 openjdk/21.0.3_9
cd ~/SimForge && source .venv/bin/activate
sbatch jobs/gen_nyc_500k.sbatch        # template in doc/PITZER.md §7
```

> **When to use Pitzer for generation.** With the schedule-first hybrid in place, the per-trip cost of demand generation is O(1) instead of O(network nodes), and the dominant cost shifts back to network extraction (PBF slice + osmnx parse). On a Pitzer `cpu` node those two steps are ~3× slower than an M4 Pro Mac due to per-core clock and shared-filesystem latency, so **generate locally on a modern laptop and reserve Pitzer for the parallel benchmark matrix at scale** — see [doc/PITZER.md §1](PITZER.md). The full Version_5 matrix is CPU-only; the GPU partition is no longer required since LPSim was removed. The `rsync` recipe above remains the right way to seed Pitzer with the OSM PBFs and ModelGen files when you do regenerate there.

### Cross-Platform Reproducibility (Verified)

The schedule-first census demand generator is **byte-reproducible across architectures** for the simulator-input artefacts. Verified empirically on the `la_50k_car` bundle (50K LA car + transit + bike trips, 06:00–10:00, 10 km radius, seed 42, modelgen file with cityscape schedules):

| File          | Mac (ARM64, Python 3.13.13, osmnx 2.0.7) | Pitzer (x86_64, Python 3.13.13, osmnx 2.1.0) | Status |
| ------------- | ------------------------------------- | ----------------------------------------- | ------ |
| `demand.csv`  | `0af9ea231b2d6efc872be0d5bb4330a5`    | `0af9ea231b2d6efc872be0d5bb4330a5`        | ✅ byte-identical |
| `signals.xml` | `4388b4eca436be69349ea1fede8e07e5`    | `4388b4eca436be69349ea1fede8e07e5`        | ✅ byte-identical |
| `network.xml` | `aef23159dd9b0d96088ef84410fc2dea`    | `ebde743b57d330544f8e9dede8e61911`        | ⚠️ semantic-identical, serialization differs |

The `network.xml` MD5 differs only because of **lxml-version-dependent XML serialization** (attribute ordering, float-precision rendering). The semantic content — node IDs, edge `from`/`to` pairs, lengths, lane counts, SCC membership — is identical, as evidenced by the two downstream artefacts being byte-equal: `signals.xml` and `demand.csv` reference network node IDs by string, so any drift in the underlying node set would have propagated and broken those matches.

What this means in practice: feeding either the Mac-generated or the Pitzer-generated `demand.csv` into a SUMO/MATSim simulation will produce the same engine inputs and (under the same engine version + seed) the same simulation outputs. The generation step is fully reproducible at the level the simulators care about.

**Reproduce locally** to verify your install matches the reference:

```bash
python scripts/03_la_50k_car.py
md5sum scenarios/la_50k_car/demand.csv \
       scenarios/la_50k_car/signals.xml
# Expected:
#   0af9ea231b2d6efc872be0d5bb4330a5  scenarios/la_50k_car/demand.csv
#   4388b4eca436be69349ea1fede8e07e5  scenarios/la_50k_car/signals.xml
```

If those two MD5s match, your local install reproduces the reference bundle exactly. Each bundle's `generation_metadata.json::toolchain` block additionally records the exact Python and dependency versions that produced it, so any future divergence is diagnosable without guesswork.

### Reference toolchain — `env_report.py` baseline

Before running the simulation pipeline, verify your install matches the canonical thesis-build environment:

```bash
python tools/env_report.py
```

The full reference output is committed at [`cluster/example_runs/env_report_canonical.txt`](../cluster/example_runs/env_report_canonical.txt) — diff your local output against it. Inline reference (Mac side, captured 2026-04-26 after the `uv` migration):

```text
============================================================
Python:     3.13.13                              # MUST match
Platform:   Darwin arm64                         # differs by host (Linux x86_64 on Pitzer)
Executable: <repo>/.venv/bin/python              # differs by host (full path is local)

--- Python deps (importable from current venv) ---
  osmnx        2.0.7                             # MUST match
  numpy        2.3.5                             # MUST match
  networkx     3.6.1                             # MUST match
  lxml         6.0.2                             # MUST match
  shapely      2.1.2                             # MUST match
  geopandas    1.1.2                             # MUST match
  pandas       2.3.3                             # MUST match
  osmium       4.3.1                             # MUST match
  matplotlib   3.10.8                            # MUST match
  seaborn      0.13.2                            # MUST match
  yaml         6.0.3                             # MUST match (PyYAML imports as `yaml`)
  pytest       9.0.2                             # MUST match

--- External tools (PATH-resolved) ---
  sumo         Eclipse SUMO sumo 1.26.0          # MUST match (eclipse-sumo wheel via lockfile)
  netconvert   Eclipse SUMO netconvert 1.26.0    # MUST match
  java         openjdk 17.0.13 2024-10-15        # patch may differ; major (17) MUST match

--- Project files ---
  matsim jar:    lib/matsim-15.0/matsim-15.0.jar # MUST match (after MATSim JAR install)
  osm pbfs:      3                               # MUST match (after `python tools/download_osm.py`)
  modelgen txts: 3                               # MUST match (after rsync from dev machine)
  scenarios:     5                               # depends on what's locally generated/synced
============================================================
```

Any line marked **MUST match** that differs in your output is a real toolchain drift — your install is on a different version than the canonical environment. Re-run `uv pip install -r requirements.lock` to reconcile, or check `cluster/example_runs/env_report_canonical.txt` for the Pitzer comparison block (Linux x86_64 reference).

The Mac↔Pitzer empirical verification we ran on 2026-04-26: every dep version matched exactly across both machines; the only differences were `Platform`, `Executable`, and a Java patch (17.0.13 vs 17.0.17 — both LTS).

---

## Collecting Results

### Output Layout

Phase 12+ layout (mode-segmented per-cell paths, scenario-scoped
benchmark-results JSON, BFS-prep cache):

```
runs/benchmark_small/
└── chicago_1k_car/
    ├── benchmark_results_benchmark_small.json   # per-scenario JSON (Phase 12)
    ├── .cache/                                   # BFS-prep cache (Phase 12)
    │   ├── sumo/    .prepared (SHA-256 of bundle manifest) + prepared inputs
    │   ├── matsim/  .prepared + ...
    │   └── dtalite/ .prepared + ...
    ├── sumo/
    │   ├── meso/
    │   │   ├── seed_42/
    │   │   │   ├── feasibility_report.json
    │   │   │   ├── tripinfo.xml
    │   │   │   └── (SUMO native files, hardlinked from .cache)
    │   │   ├── seed_43/  ...
    │   └── micro/
    │       └── seed_42/  ...
    ├── matsim/meso/seed_<N>/
    └── dtalite/meso/seed_<N>/
```

(Pre-Phase-12.2 doubly-nested layout `<scenario>/<scenario>/<engine>/<mode>/seed_<N>/`
is also still detected by `audit_fairness` — Layout C back-compat.)

`feasibility_report.json` is the audit trail proving every engine was fed the same trip set (see [CHANGELOG.md](../CHANGELOG.md), Addenda 1–2).

### Extracting Metrics

```bash
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --markdown --latex
python -m evaluation.audit_fairness    runs/benchmark_small
```

Produces:

- Summary table (one row per `(scenario, engine, mode)` cell)
- Runtime performance table
- Reproducibility table (R = 1 − σ/μ across repeats)
- **Coverage diagnostic** — flags low-sample (`n < 3`) cells, asymmetric coverage, and silently-failed cells

### Generating Plots

```bash
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json
```

Renders Fig 5.1 – Fig 5.10 (PNG + PDF) into `runs/benchmark_small/plots/`. See [doc/RESULTS_GUIDE.md](RESULTS_GUIDE.md) for what each figure shows.

---

## Expected Results (Canonical 11-Cell Matrix — Pitzer Intel Xeon Skylake, post-Phase-12.5)

The canonical numbers come from Pitzer SLURM jobs `47237978` (initial) + `47248311` (post-Phase-12.4 re-queue) + `tools/recover_partial_summary.py` (Phase 12.5 synthesis for la_50k_car DTALite cells). See [CHANGELOG.md](../CHANGELOG.md) Phase 12 series for the diagnostic chain. Table 5.1 in [`doc/chapters/results.md`](chapters/results.md) is the canonical source; a compact summary here:

| Scenario | Engine | Mode | Trips completed | Avg TT (s) | Runtime (s) | R-Score |
|---|---|---|---|---|---|---|
| chicago_1k_car | sumo | meso | 794 (79.4 %) | 268.3 ± 0.61 | 9.50 ± 0.125 | 0.9982 |
| chicago_1k_car | sumo | micro | 754 (75.4 %) | 343.1 ± 2.11 | 15.70 ± 0.623 | 0.9950 |
| chicago_1k_car | matsim | meso | 1,000 (100.0 %) | 309.6 ± 0.00 | 8.00 ± 0.511 | 1.0000 |
| chicago_1k_car | dtalite | meso | 999 (99.9 %) | 172.2 ± 0.00 | 22.26 ± 0.102 | 1.0000 |
| nyc_10k_car | sumo | meso | 10,000 (100.0 %) | 661.6 ± 35.78 | 19.90 ± 0.330 | 0.9564 |
| nyc_10k_car | sumo | micro | 9,320 (93.2 %) | 1143.8 ± 39.08 | 179.38 ± 6.916 | 0.9725 |
| nyc_10k_car | matsim | meso | 10,000 (100.0 %) | 568.4 ± 0.03 | 15.24 ± 0.200 | 1.0000 |
| nyc_10k_car | dtalite | meso | 10,544 (105.4 %)\* | 334.7 ± 0.00 | 583.06 ± 2.241 | 1.0000 |
| la_50k_car | sumo | meso | 38,947 (77.9 %) | 2621.1 ± 63.86 | 91.68 ± 1.324 | 0.9804 |
| la_50k_car | matsim | meso | 50,000 (100.0 %) | 2551.7 ± 2.25 | 52.98 ± 2.043 | 0.9993 |
| la_50k_car | dtalite | meso | _did not converge — path4gmns 0.10.0 4-thread cap; see results.md §5.7_ |

\* DTALite per-route trip count exceeds `feasible_trips` when the column-gen pool finds multiple equilibrium paths per OD pair.

The trip-count gap on SUMO is **engine-internal mobsim behaviour** (SUMO refuses congested edge insertions; MATSim's queue mobsim never refuses; DTALite assigns route paths to all OD pairs). It is the simulation outcome we want to *measure*, not an input asymmetry — every `feasibility_report.json` records `feasible_trips == total_trips`. Verified by Q1 of `audit_fairness` (PASS on all three scenarios).

**Headline cross-engine alignment:** SUMO/MATSim mean-TT ratio is 0.869 (-13.1 %) at 1 K, 1.132 (+13.2 %) at 10 K, and **1.046 (+4.6 %) at 50 K** — alignment improves with scale (law of large numbers). See `doc/chapters/results.md` §5.3 for the discussion.

---

## Troubleshooting

| Problem                          | Solution                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `MATSim ClassNotFoundException`  | The classpath includes everything in `libs/` automatically. Re-run `setup_simforge.py` to repair the JAR. |
| `SUMO command not found`         | `brew install sumo` (macOS) or `apt-get install sumo` (Linux).                                           |
| `Java version too old`           | `brew install openjdk@17` (macOS) or `apt-get install openjdk-17-jdk` (Linux).                            |
| Slow MATSim runs                 | MATSim has ~5 – 7 s JVM startup overhead per run; this dominates wall-clock for the 1K tier.              |
| `FileNotFoundError: osm_data/illinois-*.osm.pbf` during generation | Run `python tools/download_osm.py` to fetch the hash-pinned PBFs.                      |
| `SHA-256 mismatch` on a PBF      | A partial download — delete the offending file in `osm_data/` and re-run `tools/download_osm.py`.       |
| `osmnx.truncate` TypeError on `bbox` kwargs | osmnx 1.x is installed. `requirements.txt` now requires `osmnx>=2.0,<3` (positional `bbox=(W,S,E,N)`). Run `pip install -U "osmnx>=2.0,<3"`. |
| Overpass fallback hangs          | Only reachable for cities without a committed PBF. Pre-fetch with `pipeline.network.warmup`, or add the PBF to `osm_data/manifest.json`. |
| `cache/` grows large             | `tools/clean.sh --all` to wipe both Python bytecode and the OSM HTTP cache. (PBFs in `osm_data/` are kept.) |

---

## Reproducing Specific Figures

All nine thesis figures are emitted by a single command:

```bash
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json
```

| Figure   | What it shows                                              |
| -------- | ---------------------------------------------------------- |
| Fig 5.1  | Cross-engine **engine** runtime bar chart (mean + error bars; engine subprocess only) |
| Fig 5.2  | Reproducibility heatmap (R-Score per cell)                 |
| Fig 5.3  | Travel-time comparison (mean + error bars)                 |
| Fig 5.4  | Speedup analysis (relative to MATSim baseline, within-mode) |
| Fig 5.5  | Micro vs meso engine runtime comparison                    |
| Fig 5.6  | Engine runtime variability (boxplot per cell)              |
| Fig 5.7  | P95 tail-latency analysis                                  |
| Fig 5.8  | Trip-count parity (validates SCC/feasibility filter)       |
| Fig 5.9  | Demand composition — V5+ trip-purpose stacked bar           |
| Fig 5.10 | Wall vs engine breakdown (Phase 11.6+ result files only)   |

See [doc/RESULTS_GUIDE.md](RESULTS_GUIDE.md) for each figure's full interpretation.

---

## Version Information

This thesis was produced with:

| Component | Version |
| --------- | ------- |
| SimForge  | Version_5 (DTALite + Phases 5-10 realism work — see `CHANGELOG.md`) |
| Python    | 3.13.2  |
| SUMO      | 1.26.0 (`eclipse-sumo` wheel via `requirements.lock`) |
| MATSim    | 15.0    |
| Java      | 17.0.13 |
| osmnx     | 2.x (`requirements.txt` pins `>=2.0,<3`) |
| osmium (pyosmium) | 4.x |
| path4gmns | 0.10.0 (DTALite bundled binary) |
| OSM PBF snapshots | Geofabrik extracts — exact SHA-256 hashes in `osm_data/manifest.json` |

To reproduce exactly, use these versions.

---

## Citation

```bibtex
@mastersthesis{simforge2026,
  author = {Dharakula, Phani},
  title  = {SimForge: A Reproducible Cross-Simulator Benchmarking Framework
            for Urban Traffic Simulation},
  school = {University of Texas at Austin},
  year   = {2026}
}
```
