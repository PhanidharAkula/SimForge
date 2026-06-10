# SimForge Data Management

This document describes how SimForge handles data sources, storage,
access control, retention, and ethics. It corresponds to the
commitments in Thesis Plan §3.6 ("Data Management and Ethics").
Licensing is documented separately in [`doc/LICENSING.md`](LICENSING.md).

---

## 1. Data sources used

SimForge relies *exclusively* on publicly available datasets. No
private, proprietary, license-restricted, or institutionally-gated
data is used at any stage of the pipeline.

| Source | Role | License | Provenance recorded in |
|---|---|---|---|
| **OpenStreetMap** (hash-pinned Geofabrik state-level PBF snapshots) | Road network topology, OSM `highway=traffic_signals` for signal placement, OSM `type=restriction via=node` relations for V5+ turn restrictions | ODbL v1.0 | `osm_data/manifest.json` (SHA-256 per PBF) + per-scenario `manifest.xml` (extraction date + bbox) |
| **US Census PUMS microdata** (via cityscape's ModelGen `<city>_model.txt`) | Aggregate population synthesis: households, persons, building locations, JWMNP commute times, JWTRNS mode codes | US Federal public domain (17 U.S.C. § 105) | `doc/MODELGEN_AND_MODES.md` §1 + per-scenario `manifest.xml` |
| **US Census TIGER/Line Cartographic Boundary** (CB 2024 tracts + PRISECROADS) | Visualization-only: choropleth tract polygons + roads basemap on the `visualization` branch | US Federal public domain | `tools/download_census_tracts.py` + `tools/download_tiger_roads.py` README headers |

## 2. No personally identifiable information (PII)

SimForge never processes individual-level trip records, vehicle GPS
traces, license plates, or any other personally identifiable data.
Specifically:

- **Demand data** comes from PUMS *microdata*, which the US Census
  Bureau pre-aggregates and suppresses below ≥10-person threshold per
  Public Use rules. SimForge consumes the released aggregates only.
- **Trip generation** produces *synthetic* trip records seeded by a
  fixed RNG: each trip is a (origin_node, destination_node, departure_time,
  mode) tuple referencing canonical-network nodes, not real persons or
  vehicles. The synthetic generator is deterministic and reproducible
  (`pipeline/demand/generate_census_demand.py`).
- **Network data** comes from OSM, which is itself a non-PII geographic
  database.

The plan §3.6 commits to suppressing TAZ cells with fewer than 10
trips. Because SimForge ingests PUMS which has already applied this
threshold upstream, no additional suppression is required. See
`doc/MODELGEN_AND_MODES.md` for the empirical per-city counts.

The plan also describes "uniform random jitter of ±60s to reduce
residual re-identification risk" on departure timestamps. SimForge's
PUMS-derived demand operates at PUMS's existing aggregate granularity
(integer-minute JWMNP), so departure jitter would only smooth a
visualization artefact (the "departure bursts" documented in
`visualization/README.md` and `methods.md` §3.3 step 9), not provide
additional PII protection. The jitter is feature-ready in
`pipeline/demand/generate_census_demand.py` but disabled by default to
preserve byte-deterministic `demand.csv` across regenerations.

## 3. Storage and access control

| Tier | What lives there | Access |
|---|---|---|
| **GitHub repository (public)** | Code, documentation, runspecs, SBATCH wrappers, manifest hashes, the canonical `chicago_1k_car` bundle. No raw PBFs, no large generated bundles, no run results | Public (open-source) |
| **Local developer machine** | Full local SimForge checkout, the venv, generated bundles for development, runs under `runs/`, modelgen text files under `modelgen/` | Single user; not shared |
| **OSC HPC (Pitzer / Cardinal / Ascend shared `$HOME`)** | Full repository clone, large generated bundles (`scenarios/chicago_200k_car/`, `scenarios/nyc_500k_car/`), benchmark run outputs under `runs/benchmark_large/` | University-authenticated SSH (Duo 2FA); single user account |
| **GitHub Container Registry (Phase 14 forward)** | Pinned container images for reproducible re-execution | Public (read), authenticated push only |

Raw datasets (PBFs, PUMS modelgen text files) and large generated
bundles are **not** distributed via GitHub due to size; they're either
fetched at build time (`tools/download_osm.py`) from upstream public
URLs hash-verified against `osm_data/manifest.json`, or generated on
demand by `python generate.py --preset <name>` from those hash-pinned
upstream sources.

## 4. Retention

| Asset | Retention |
|---|---|
| Code, docs, runspecs | Indefinite (in git history) |
| Hash-pinned OSM PBFs in `osm_data/` | Indefinite (matched against `osm_data/manifest.json` SHA-256) |
| Modelgen text files in `modelgen/` | Per the upstream cityscape release; SimForge does not redistribute |
| Generated canonical bundles (1K/10K/50K tracked; 200K/500K gitignored) | Regeneratable from hash-pinned inputs; untracked tiers not retained beyond active development |
| Run results under `runs/` | Per thesis-defense + 12-month post-graduation period, then archived or deleted per OSC storage policy |
| Container images on GHCR | Same as code (indefinite) |

The 12-month post-completion retention window for run results matches
plan §3.6 and OSC's standard storage-allocation policy. After that
point, only the manifests, hashes, and the pinned container digest are
retained, so re-execution remains possible but the prior run outputs
are not held indefinitely.

## 5. Ethics and oversight

- **No IRB approval required.** The work uses only publicly released
  aggregate data; no human-subjects research is conducted.
- **No animal subjects, no clinical data, no sensitive populations.**
- **Synthetic data labeling.** All generated trip records carry a
  `dest_source` provenance column (V5+) marking each row as either
  `schedule` (cityscape PUMS-derived) or `gravity` (synthetic gravity
  fallback). This is the audit-trail used by `audit_fairness` Q5 and
  thesis Fig 5.9.
- **Reproducibility-as-ethic.** SimForge's whole-stack hash pinning +
  byte-deterministic adapters + post-run `audit_fairness` make every
  number in Chapter 5 independently verifiable. The plan's
  reproducibility commitments (§2.7, §3.4, §4.2) are themselves an
  ethical posture: claims that can't be reproduced shouldn't drive
  policy.

## 6. Reproducibility chain (for citing or building on SimForge)

To reproduce a SimForge benchmark exactly:

1. Clone the repository at a specific commit (or use the pinned
   container digest once Phase 14 containerization lands).
2. `tools/download_osm.py` (hash-verified against
   `osm_data/manifest.json`).
3. Acquire the cityscape ModelGen `<city>_model.txt` files from the
   upstream cityscape release (citing `doc/MODELGEN_AND_MODES.md` §1).
4. `python generate.py --preset <name>` to materialize the canonical
   bundle.
5. `python -m execution.run_benchmark runspecs/benchmark_*.yaml` to
   run the matrix.
6. `python -m evaluation.audit_fairness <run-dir>` to verify Q1–Q5.
7. `python -m evaluation.analyze_benchmark <run-dir>/benchmark_results_*.json --markdown`
   to regenerate Table 5.1 / 5.2.
8. `python -m evaluation.generate_plots <run-dir>/benchmark_results_*.json`
   to regenerate the 10 Chapter-5 figures.

Every step is deterministic, file-based, and re-verifiable against the
hash-pinned inputs.

## 7. Contact

Data-management questions: file a GitHub issue or email the author
(see `README.md`).
