# SimForge Test Suite

**324 tests** across **11 test files** covering adapters, metrics, validation, data integrity, and end-to-end pipeline stress tests.

## Quick Start

```bash
source .venv/bin/activate
python -m pytest tests/ -v            # full suite (~9 min)
python -m pytest tests/ -v -x         # stop on first failure
python -m pytest tests/test_scenario_data_integrity.py -v   # data checks only
```

---

## Test Files

### 1. `test_adapter_determinism.py` — Determinism (8 tests)

Verifies the SUMO adapter produces **byte-identical** outputs across repeated runs.

| Test | What it checks |
|------|---------------|
| `test_hash_file_*` | SHA-256 hashing utility correctness |
| `test_deterministic_full_output` | Full adapter output is identical across runs |
| `test_deterministic_routes` | Route files match exactly |
| `test_deterministic_nodes` | Node XML matches exactly |
| `test_deterministic_edges` | Edge XML matches exactly |
| `test_deterministic_config` | SUMO config matches exactly |

### 2. `test_sumo_adapter.py` — SUMO Adapter (5 tests)

Tests the core SUMO adapter's file generation and correctness.

| Test | What it checks |
|------|---------------|
| `test_prepare_sumo_inputs_creates_expected_files` | Creates net.net.xml, routes, config |
| `test_edges_have_length_attribute` | Every edge in nodes/edges XML has `length` ≥ 0.1m |
| `test_net_xml_has_realistic_lane_lengths` | Geo projection produces mean lane length > 10m |
| `test_sumo_adapter_all_scenarios` | Runs adapter on **every** available scenario |

### 3. `test_matsim_adapter.py` — MATSim Adapter (18 tests)

Tests the MATSim adapter (file generation only — no Java/JAR required).

| Test | What it checks |
|------|---------------|
| `test_seconds_to_time_string_*` | Time conversion: 0 → "00:00:00", 45296 → "12:34:56" |
| `test_matsim_config_defaults` | Default config values (iterations=10, etc.) |
| `test_build_matsim_vehicles_xml` | Valid vehicles XML with car vehicleType |
| `test_load_canonical_network` | Loads nodes/links from canonical network XML |
| `test_build_matsim_network_xml` | Valid MATSim network XML with nodes and links |
| `test_build_matsim_plans_xml` | Valid MATSim plans with person/activity/leg elements |
| `test_build_matsim_config_xml` | Config has module elements for network, plans, etc. |
| `test_prepare_matsim_inputs` | Full pipeline: generates all 4 output files |
| `test_all_scenarios` | Runs adapter on every available scenario |

### 4. `test_qarsumo_adapter.py` — QarSUMO Adapter (12 tests)

Tests the QarSUMO GPU-accelerated SUMO adapter.

| Test | What it checks |
|------|---------------|
| `test_default_config` | Default batch_size=1024, precision=float32 |
| `test_custom_config` | Custom config values are accepted |
| `test_config_to_dict` | Config serializes to dictionary correctly |
| `test_gpu_detection_safe` | GPU detection returns bool without crashing |
| `test_gpu_info_safe` | GPU info returns dict without crashing |
| `test_extend_config_adds_qarsumo_section` | Adds `<qarsumo>` XML section with GPU settings |
| `test_qarsumo_section_values` | gpu-device, batch-size, precision are correct |
| `test_prepare_qarsumo_inputs` | Full pipeline: generates SUMO files + QarSUMO config |
| `test_all_scenarios` | Runs adapter on every available scenario |

### 5. `test_fidelity_metrics.py` — Fidelity Metrics (16 tests)

Tests statistical fidelity metrics used to compare simulation outputs.

| Test | What it checks |
|------|---------------|
| `test_rmse_*` | Root Mean Squared Error: zeros, known values, single elements |
| `test_geh_*` | GEH statistic for traffic volumes |
| `test_ks_*` | Kolmogorov-Smirnov test for distribution comparison |
| `test_fidelity_*` | Combined fidelity score computation |

### 6. `test_metrics_travel_time.py` — Travel Time Metrics (2 tests)

Tests parsing of SUMO tripinfo XML output.

| Test | What it checks |
|------|---------------|
| `test_parse_tripinfo` | Correct extraction of travel times from tripinfo.xml |
| `test_parse_tripinfo_empty` | Handles empty tripinfo gracefully |

### 7. `test_reproducibility_metrics.py` — Reproducibility Metrics (15 tests)

Tests metrics for measuring run-to-run consistency.

| Test | What it checks |
|------|---------------|
| `test_coefficient_of_variation_*` | CV computation for identical, varying, single values |
| `test_hash_match_fraction_*` | File hash comparison across runs |
| `test_reproducibility_score_*` | Combined reproducibility score |

### 8. `test_scalability_metrics.py` — Scalability Metrics (8 tests)

Tests metrics for measuring performance at scale.

| Test | What it checks |
|------|---------------|
| `test_speedup_*` | Speedup ratio calculation |
| `test_throughput_*` | Trips-per-second throughput |
| `test_scalability_*` | Combined scalability score |

### 9. `test_validator.py` — Bundle Validator (2 tests)

Tests the pipeline validator on real scenario bundles.

| Test | What it checks |
|------|---------------|
| `test_generated_bundle_is_valid` | A generated scenario passes validation |
| `test_bundle_with_bad_node_in_demand_is_invalid` | Validator catches invalid node references |

### 10. `test_scenario_data_integrity.py` — Data Integrity (35+ tests × N scenarios)

**The most critical test file.** Parametrized over ALL available scenarios. Catches data errors before any simulation runs.

| Test Class | What it checks |
|------------|---------------|
| `TestFileExistence` | All 5 required files exist (manifest, network, demand, config, signals) |
| `TestXMLParsing` | All XML files are well-formed |
| `TestNetworkIntegrity` | No duplicate node/link IDs, valid WGS84 coordinates (lon ∈ [-180,180], lat ∈ [-90,90]), link endpoints reference existing nodes, positive length/speed/lanes |
| `TestDemandIntegrity` | Required CSV columns, no duplicate trip IDs, all origins/destinations exist in network, non-negative departures, departures within time horizon, origin ≠ destination, valid modes |
| `TestConfigIntegrity` | Has metadata, scenario_id matches directory name, valid time horizon (>0), valid units (meters, m/s, seconds), has seed |
| `TestManifestIntegrity` | Manifest ID matches config scenario_id, all declared files physically exist |
| `TestSignalsIntegrity` | All junction node references exist in the network |

### 11. `test_pipeline_e2e.py` — End-to-End Pipeline (17 tests)

Stress tests for the full pipeline, including negative testing (bad data detection).

| Test Class | What it checks |
|------------|---------------|
| `TestValidatorCatchesBadData` | 11 tests: missing files, corrupt XML, empty demand, missing columns, nonexistent nodes, negative departure, scenario ID mismatch, nonexistent directory |
| `TestSUMOAdapterRobustness` | All-scenarios conversion, valid route edges, tripinfo output configured |
| `TestNetworkRouting` | BFS pathfinding, unreachable paths return None, same-node paths, real network >80% routeable |

---

## Platform Notes

### Apple Silicon (arm64) — netconvert segfault

SUMO 1.20.0's `netconvert` binary can segfault on large networks (>3000 nodes) on Apple Silicon Macs. This is a **SUMO platform bug**, not a SimForge issue.

**Affected scenarios:** `chicago_200k_car_transit` (27,536 nodes), `nyc_10k_car` (4,041 nodes)

The `test_*_all_scenarios` tests automatically detect arm64 and skip scenarios that crash netconvert, emitting a warning:

```
UserWarning: Skipped 2 scenarios (netconvert crash on arm64): ['chicago_200k_car_transit', 'nyc_10k_car']
```

These scenarios work correctly on Linux/HPC.

---

## Test Coverage Summary

| Area | Tests | Coverage |
|------|-------|----------|
| SUMO Adapter | 13 | File generation, determinism, geo projection, all scenarios |
| MATSim Adapter | 18 | Unit + integration, all scenarios |
| QarSUMO Adapter | 12 | Config, GPU detection, all scenarios |
| Fidelity Metrics | 16 | RMSE, GEH, KS, combined score |
| Travel Time | 2 | Tripinfo parsing |
| Reproducibility | 15 | CV, hash matching, combined score |
| Scalability | 8 | Speedup, throughput, combined score |
| Validator | 2 | Valid/invalid bundles |
| Data Integrity | ~210 | All scenarios × 35 checks each |
| E2E Pipeline | 17 | Bad data detection, routing, adapter robustness |
| **Total** | **~324** | |
