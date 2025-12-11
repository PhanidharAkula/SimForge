# SimForge TODO

## Milestone 1 — Skeleton & Toy Scenario

- [ ] Create `simforge` repo structure
- [ ] Add base folders: `canonical/`, `adapters/`, `pipeline/`, `execution/`, `evaluation/`
- [ ] Write canonical schema v0 docs
- [ ] Create toy scenario bundle (`network.xml`, `demand.csv`, `signals.xml`, `config.json`, `manifest.json`)
- [ ] Implement `validate_bundle.py` and CLI

## Milestone 2 — SUMO Adapter v0

- [ ] Install SUMO locally / in container
- [ ] Design mapping canonical → SUMO (MAPPING.md)
- [ ] Implement `build_sumo_inputs.py`
- [ ] Run end-to-end toy scenario with SUMO
