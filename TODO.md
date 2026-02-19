# SimForge Development Roadmap

## Scope

- **Simulators**: SUMO, QarSUMO, MATSim
- **Tier**: 5K trips (thesis-scale)
- **Cities**: Chicago, New York City, Los Angeles

---

## Milestone 1 — Canonical Schema & Pipeline ✅

- [x] Define canonical schema v0 (network.xml, demand.csv, signals.xml, config.xml, manifest.xml)
- [x] Write schema documentation
- [x] Implement bundle validator with SHA-256 integrity checks
- [x] Build OSM → canonical network pipeline
- [x] Build synthetic demand generator (gravity model)
- [x] Build traffic signal inference from OSM

## Milestone 2 — Simulator Adapters ✅

- [x] SUMO adapter: canonical → net.xml, rou.xml, sumocfg (micro + meso)
- [x] QarSUMO adapter: wraps SUMO with GPU config, CPU fallback
- [x] MATSim adapter: canonical → MATSim network.xml, plans.xml, config
- [x] CLI entry points for each adapter

## Milestone 3 — Execution Harness & Metrics ✅

- [x] Runspec schema (YAML) for benchmark configuration
- [x] Benchmark runner with timeout, seed control, repeat support
- [x] Travel-time metrics parser (SUMO tripinfo.xml)
- [x] Fidelity metrics: RMSE, GEH, KS statistic
- [x] Scalability metrics: throughput, runtime
- [x] Reproducibility metrics: R = 1 − σ/μ
- [x] Main CLI (`run.py`) with auto-detection

## Milestone 4 — 5K City Scenarios ✅

- [x] Chicago 5K scenario (3,343 nodes, 8,362 links, 5,000 trips)
- [x] NYC 5K scenario (1,913 nodes, 3,877 links, 5,000 trips)
- [x] LA 5K scenario (6,333 nodes, 17,685 links, 5,000 trips)
- [x] All scenarios validated (manifest hash checks pass)
- [x] Per-city standalone generation scripts

## Milestone 5 — Benchmark & Analysis ✅

- [x] Unified runspec for 5K benchmark (3 cities × 3 engines × meso × 3 repeats)
- [x] Benchmark analysis tools (analyze_benchmark.py)
- [x] Comparison mode analysis (compare_modes.py)
- [x] Plot generation for thesis figures (generate_plots.py)

## Milestone 6 — Test Suite ✅

- [x] Adapter determinism test (SUMO hash stability)
- [x] SUMO adapter integration test
- [x] Bundle validator test (valid + corruption detection)
- [x] Travel-time metrics unit test
- [x] Fidelity, scalability, reproducibility metric unit tests
- [x] All 57 tests passing

---

## Remaining Work

### Thesis Execution

- [ ] Run full benchmark matrix (27 runs) and collect results
- [ ] Generate thesis figures from benchmark data
- [ ] Fill in results tables in thesis chapters

### Thesis Writing

- [ ] Complete Chapter 4 (Experimental Setup) with actual parameters
- [ ] Complete Chapter 5 (Results) with benchmark data
- [ ] Complete Chapter 6 (Conclusion)
- [ ] Abstract and acknowledgments

### Future Enhancements (Post-Thesis)

- [ ] Higher demand tiers (50K, 500K, 5M)
- [ ] Additional cities
- [ ] POLARIS / LPSim adapter (backup simulators)
- [ ] HPC execution support (SLURM)
- [ ] Microscopic mode benchmarks
- [ ] Real OD demand integration
