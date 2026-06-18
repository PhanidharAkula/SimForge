# SimForge Licensing

This document declares the license under which each component of the
SimForge artefact is distributed, and the upstream licenses that govern
the third-party software and data SimForge consumes. It documents
SimForge's data-management and ethics posture.

---

## 1. SimForge code

The SimForge codebase, every file in `adapters/`, `pipeline/`,
`evaluation/`, `execution/`, `visualization/`, `tools/`, `tests/`,
`cluster/`, top-level entry points (`run.py`, `generate.py`, `help.py`,
`setup_simforge.py`), runspecs in `runspecs/`, and SBATCH wrappers in
`cluster/jobs/`, is licensed under the **Apache License, Version 2.0**.

The full license text is at `LICENSE` in the repository root, and a
copyright notice is included in the license appendix.

Apache 2.0 permits redistribution, modification, sublicensing, and
commercial use, requires preservation of attribution + license notice,
and grants an explicit patent license to downstream users.

## 2. Canonical scenario bundles (output artefacts)

The canonical scenario bundles in `scenarios/<scenario_id>/` (the
five-file bundles `network.xml` + `demand.csv` + `signals.xml` +
`config.xml` + `manifest.xml`) are derived from upstream public-domain
or open-data sources (see §3 below). The bundles themselves, as
*derived* datasets produced by SimForge's deterministic pipeline, are
distributed under **Creative Commons Attribution 4.0 International
(CC BY 4.0)** when published. Re-distribution must preserve attribution
to SimForge and to the upstream sources via the bundle's `manifest.xml`
provenance block.

Note that an OSM-derived bundle inherits a stricter `ODbL` obligation
on the network component, see §3.1.

## 3. Upstream data sources

### 3.1 OpenStreetMap (network topology)

Source: hash-pinned Geofabrik PBF snapshots under `osm_data/`, listed in
`osm_data/manifest.json` with SHA-256 hashes.

License: **Open Database License (ODbL) v1.0** by the OpenStreetMap
Foundation. Share-alike: any derived database (canonical `network.xml`
files) must remain available under ODbL. Attribution: © OpenStreetMap
contributors.

The bundle's `manifest.xml` records the upstream PBF source, the
extraction date, and the bbox used for the per-scenario slice.

### 3.2 US Census Bureau, PUMS microdata + cityscape ModelGen

Source: Cityscape's Schedule-generator branch synthesizes population +
schedules from US Census Public Use Microdata Sample (PUMS) records.
Input files at `modelgen/<city>_model.txt` are gitignored due to size;
generation provenance documented in `doc/MODELGEN_AND_MODES.md`.

License: PUMS itself is **US Federal Government public domain**
(17 U.S.C. § 105). Cityscape's ModelGen output inherits the public-domain
status. SimForge's derived `demand.csv` is therefore unencumbered.

Attribution: US Census Bureau, American Community Survey (ACS) PUMS.

### 3.3 US Census Bureau, TIGER/Line Cartographic Boundary

Source: tract polygons (`cb_2024_<fips>_tract_500k.shp`) and roads
(`tl_2024_<fips>_prisecroads.shp`) cached under `cache/census/` and
`cache/tiger/`, populated by `tools/download_census_tracts.py` and
`tools/download_tiger_roads.py`.

License: **US Federal Government public domain**.

Used only by the opt-in `visualization/` component (on the
`visualization` branch) for choropleth + basemap rendering. Not part of
the canonical benchmark pipeline.

## 4. Third-party software dependencies

Pinned in `requirements.lock`. Each package retains its own upstream
license; SimForge does not redistribute the binary wheels, they are
fetched at install time by `uv pip install`.

| Component | Version pin | Upstream license |
|---|---|---|
| `eclipse-sumo` (includes SUMO binary) | 1.26.0 | **Eclipse Public License 2.0 (EPL-2.0)** |
| MATSim runtime JAR | 15.0 | **GPL v2 or MIT/Apache (per release jar)**, distribution governed by MATSim's per-release notices in `lib/matsim-15.0/` |
| `path4gmns` (includes DTALite binary) | 0.10.0 | **Apache 2.0** (path4gmns); DTALite C++ upstream Apache 2.0 |
| Python 3.13 | 3.13.13 (pinned by `uv`) | **PSF License** |
| `numpy`, `scipy`, `pandas`, `lxml`, `matplotlib`, `shapely`, `pyshp`, `osmium`, `osmnx`, `networkx`, `psutil`, `pytest` (+ transitive) | per `requirements.lock` | Varies (BSD, MIT, LGPL, Apache 2.0), each retains its own |
| OpenJDK 17/21 (runtime) | per system / Cardinal `module load openjdk/21.0.3_9` | **GPL v2 with Classpath exception** |
| `libomp` (DTALite OpenMP runtime) | per system | **MIT-style (LLVM)** |

Re-distribution of SimForge container images (see
`doc/CONTAINER_USAGE.md` once Phase 14 containerization lands) bundles
these third-party binaries; the container's `LICENSES/` directory will
include each upstream notice file.

## 5. Documentation

`doc/`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `TESTING.md`,
`SETUP.md`, and the opt-in `visualization/README.md`, same as the code:
**Apache 2.0**. (The thesis chapters live outside this repository and are
not covered by its license.)

## 6. Re-use guidance for downstream users

If you cite or build on SimForge:

1. Acknowledge SimForge + the thesis (BibTeX in `doc/REPRODUCING.md`
   §Citation when it lands).
2. Preserve the `manifest.xml` provenance block in any redistributed
   canonical bundle.
3. Honor OSM's ODbL share-alike obligation on derived network data.
4. Refer to each third-party engine's own license when redistributing
   them inside a container.

## 7. Contact

Licensing questions: file an issue at the SimForge GitHub repository
or email the author (see `README.md`).
