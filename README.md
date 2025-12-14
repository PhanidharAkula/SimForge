# 🌉 SimForge

SimForge is a reproducible, cross-simulator testing framework for urban traffic simulation.

The goal is to standardize **scenario representation, validation, execution, and measurement** so that different traffic simulators can be compared under identical conditions.

This repository currently implements a complete **v0 pipeline** from canonical inputs to runnable SUMO artifacts.

---

## 🛠️ What Exists Right Now (No Hype)

This repo is not a plan anymore. It contains working code:

- **Canonical schema v0** (documented in Markdown)
- **Canonical toy scenario** (`toy_2x2_grid`)
- **Validator** enforcing cross-file consistency
- **SUMO adapter v0** that generates real:
  - `net.net.xml`
  - `routes.rou.xml`
  - `toy.sumocfg`
- **End-to-end pipeline runner** (validate → adapter)
- **Pytest test suite** for validator and adapter

Everything below actually runs.

---

## 💻 Requirements

- Python **3.10+**
- macOS or Linux
- SUMO **optional** (only needed if you want to actually execute simulations)

> This project uses a local virtual environment (`.venv`).
> Do **not** install dependencies into system Python.

---

## ⚙️ Setup

From the repository root:

### 1\. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` in your shell prompt.

### 2\. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 🗺️ Canonical Scenario Bundle

The canonical toy scenario lives at:

```text
scenarios/toy_2x2_grid/
├── network.xml
├── demand.csv
├── signals.xml
├── config.xml
└── manifest.xml
```

This bundle is **fully self-contained** and is used for:

- Validator testing
- SUMO adapter testing
- Pipeline demonstrations

---

## ✅ Validator

The validator enforces:

- `manifest.xml` structure
- Required canonical files (`network`, `demand`, `config`)
- Scenario ID consistency (`manifest` $\leftrightarrow$ `config`)
- Unit consistency (`network` $\leftrightarrow$ `config`)
- Node references (`network.xml` $\leftrightarrow$ `demand.csv`)
- Basic demand sanity checks

### Run the validator

```bash
python -m pipeline.validation.validate_bundle scenarios/toy_2x2_grid
```

**Expected output:**

```text
[VALID] Scenario bundle at: .../scenarios/toy_2x2_grid
```

If you intentionally corrupt the scenario (e.g., invalid node IDs), the validator will fail with explicit errors.

---

## ➡️ SUMO Adapter (v0)

The SUMO adapter converts a canonical bundle into runnable SUMO inputs.

For the toy scenario it generates:

```text
out/<run_name>/
├── net.net.xml      # SUMO network
├── routes.rou.xml   # SUMO routes
└── toy.sumocfg      # SUMO configuration
```

Internally, the adapter:

- Parses the canonical network into a directed graph
- Uses BFS to compute routes for each trip
- Maps canonical links directly to SUMO edges
- Preserves the scenario time horizon

### Run the adapter directly

```bash
python -m adapters.sumo.cli scenarios/toy_2x2_grid out/sumo_toy
```

**Expected output:**

```text
[SUMO ADAPTER] Prepared SUMO inputs at: .../out/sumo_toy
  Scenario ID : toy_2x2_grid
  Nodes       : 4
  Links       : 8
  Trips       : 6
  Has signals : True
  Time horizon: 0 -> 3600 seconds
```

---

## 🏃 End-to-End Pipeline Runner

The pipeline runner chains:

1.  Canonical bundle validation
2.  SUMO input generation

### Run the full pipeline

```bash
python -m execution.run_sumo_scenario scenarios/toy_2x2_grid out/sumo_pipeline
```

If validation fails, the pipeline aborts before adapter execution.

---

## 🧪 Tests

Tests are written using `pytest` and cover:

- Validator correctness
- SUMO adapter output structure and summaries

**Test files:**

```text
tests/
├── test_validator_toy.py
└── test_sumo_adapter_toy.py
```

### Run tests

```bash
pytest
```

**Expected result:**

```text
3 passed in <time>s
```

---

## 📂 Repository Structure

```text
SimForge/
├── adapters/
│   └── sumo/
│       ├── sumo_adapter.py
│       └── cli.py
├── canonical/
│   └── schema/
│       ├── network_v0.md
│       ├── demand_v0.md
│       ├── signals_v0.md
│       ├── config_v0.md
│       └── manifest_v0.md
├── execution/
│   └── run_sumo_scenario.py
├── pipeline/
│   └── validation/
│       └── validate_bundle.py
├── scenarios/
│   └── toy_2x2_grid/
├── tests/
├── out/                # generated (gitignored)
├── .venv/              # virtual environment (gitignored)
├── requirements.txt
├── README.md
└── TODO.md
```

---

## 📝 Current Status

| Feature                 | Status                      |
| :---------------------- | :-------------------------- |
| Canonical schema v0     | **implemented**             |
| Validator               | **implemented + tested**    |
| SUMO adapter            | **implemented** (toy scale) |
| Pipeline runner         | **implemented**             |
| Evaluation / metrics    | not yet implemented         |
| Multi-simulator support | future work                 |

This repository represents the **implementation baseline** for the SimForge thesis work.

---

## 🚀 Next Steps (Planned)

- Add standardized **output metrics** (e.g., travel time, throughput).
- Execute real SUMO runs and parse outputs.
- Introduce additional simulators using the same canonical schema.
- Scale beyond toy scenarios.
