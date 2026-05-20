# Front matter

Scaffolded 2026-05-20 as a single editable markdown source for the
title page, dedication, acknowledgments, table of contents, list of
figures, and list of tables. The LaTeX assembly step (Pandoc or
direct biblatex/biber) re-renders each section into the school's
official thesis template; the markdown here is the prose source.

Placeholders marked **`[FILL]`** require user input before submission.

---

## Title page

> **Note for LaTeX assembly**: replace the markdown below with
> Ohio State University's official thesis title-page template
> (`.cls` or `.sty` file from the graduate school). The placeholders
> below capture the content the title page must include; the
> template controls the formatting.

**Title**: *"SimForge: A Reproducible Cross-Simulator Testing Framework for Urban Mobility Simulation"*

A Thesis Presented in Partial Fulfillment of the Requirements for the Degree

**`[FILL: Master of Science / Master of Engineering / ...]`**

in the Graduate School of **`[FILL: school name]`**

By

**Phanidhar Akula**

Graduate Program in **`[FILL: program name — Computer Science and Engineering?]`**

**`[FILL: University name]`**

2026

Thesis Committee:

- **`[FILL: Advisor name]`**, Advisor
- **`[FILL: Committee member 2]`**
- **`[FILL: Committee member 3]`** *(if required)*

---

## Copyright

Copyright by

**Phanidhar Akula**

2026

Software released under the Apache License 2.0; canonical bundles under CC BY 4.0 + ODbL share-alike; this thesis document under **`[FILL: thesis copyright — typically all rights reserved; or CC BY 4.0 if you opt for open access]`**.

---

## Dedication

To **`[FILL — typical examples: my parents, my advisor, ...]`**

*(One short line is conventional. Some theses include a longer
dedication paragraph; OSU's template allows up to one page.)*

---

## Acknowledgments

*(One-to-two pages typical. The structure below is a template
covering the standard categories. Fill in names and replace bracketed
text. Keep the tone professional but warm — committee members read
this section closely.)*

I am deeply grateful to my advisor, **`[FILL: advisor name]`**, for **`[FILL: e.g., introducing me to cross-simulator benchmarking as a research direction; tolerating ~14 iterations on the canonical schema design; making time for weekly check-ins through the Phase 14 engineering crunch]`**. **`[FILL: 1-2 lines on what the advisor specifically did that mattered most]`**.

I thank my thesis committee members **`[FILL: name 2]`** and **`[FILL: name 3]`** for **`[FILL: their feedback on the plan draft, their patience during the engine roster pivot from LPSim/POLARIS to DTALite, ...]`**.

This work would not have been possible without the open-source
software it builds on. I acknowledge the developers of **SUMO**
(Eclipse Foundation, originating at DLR Berlin); **MATSim**
(ETH Zürich + TU Berlin community); **DTALite** (originally Arizona
State University, distributed via `path4gmns`); and the
**cityscape** activity-based population synthesizer developed by
Prof. Dhananjai M. Rao's research group at Miami University, whose
ModelGen output is the substrate for every SimForge demand bundle.

I thank the **Ohio Supercomputer Center** (OSC) for compute time on
the Pitzer and Cardinal clusters under allocation **PMIU0110**.
The 633-test suite and the 200K + 500K tier benchmarks would have
been infeasible without HPC access. Specific thanks to **`[FILL: any
OSC staff who helped, or omit this line]`** for **`[FILL: troubleshooting,
allocation extensions, etc.]`**.

The pinned-digest container distribution (Wave 2) builds on the
**GitHub Container Registry** + **GitHub Actions** infrastructure
provided free of charge to public repositories. The visualization
component (`visualization/` branch) depends on data from the
**U.S. Census Bureau** (PUMS, TIGER/Line), the **Oak Ridge National
Laboratory** (LandScan), **IPUMS USA** (PUMA shapefiles), and
**OpenStreetMap contributors** (road and building geometry under
ODbL share-alike).

**`[FILL: optional — colleagues / labmates / friends who provided
specific feedback, e.g., "I thank X for the careful read of the
§5.6.3 cross-platform-reproducibility narrative that caught the
JVM-build attribution error" — be specific where possible]`**.

Finally, thanks to **`[FILL: family / partner / personal support
people]`** for **`[FILL: their patience during the multi-week
thesis-writing crunch / etc.]`**.

---

## Table of Contents

*(Auto-generated from chapter headers in `doc/chapters/*.md` as of
commit `e9d3f71`, 2026-05-20. The LaTeX assembly step regenerates
this from `\section{}` / `\subsection{}` commands; the static copy
here is for review.)*

**Abstract**  ........................................................................................................................ iii
**Dedication**  ...................................................................................................................... iv
**Acknowledgments**  .......................................................................................................... v

**Chapter 1: Introduction**  ............................................................................................... 1
- 1.0 Overview
- 1.1 Motivation
- 1.2 Problem statement
- 1.3 Research questions
- 1.4 Contributions
  - 1.4.1 The four delivered C-rows (per plan §1.11)
  - 1.4.2 The four empirical findings
  - 1.4.3 The framework as a citable artefact
- 1.5 Significance and scope
  - 1.5.1 What this thesis is
  - 1.5.2 What this thesis is not
  - 1.5.3 Scope boundaries
  - 1.5.4 Implications for the broader research community
- 1.6 Thesis organization
- 1.7 Notation and conventions

**Chapter 2: Background and Related Work**  ................................................................ ~30
- 2.0 Overview
- 2.1 Evolution of traffic simulation
- 2.2 Simulation scope and terminology
- 2.3 Major urban mobility simulation systems
  - 2.3.1 Engines integrated in the SimForge framework
  - 2.3.2 Engines considered and ruled out
  - 2.3.3 The shipped paradigm coverage
  - 2.3.4 Activity-based demand generation: cityscape and contemporaries
- 2.4 Incompatibilities across simulators
- 2.5 Existing mobility benchmarks
- 2.6 Benchmark frameworks in adjacent domains
- 2.7 Reproducibility in HPC and scientific computing
  - 2.7.1 Empirical contribution: cross-platform reproducibility limits
- 2.8 Summary of research gap
- 2.9 Notation conventions for this chapter

**Chapter 3: Methods**  .................................................................................................. ~65
- 3.1 Overview
- 3.2 Canonical Data Schema (§§3.2.1 – 3.2.8)
- 3.3 Scenario Generation Pipeline (§§3.3.1 – 3.3.4)
- 3.4 Simulator Adapter Layer (§§3.4.1 – 3.4.5)
- 3.5 Execution Harness (§§3.5.1 – 3.5.3)
- 3.6 Evaluation Metrics (§§3.6.1 – 3.6.5)
- 3.7 Implementation Quality (§§3.7.1 – 3.7.3)
- 3.8 Canonical-Routes BFS Deduplication and Parallelization (Phase 14) (§§3.8.1 – 3.8.7)
- 3.9 Geographic Visualization (Opt-in) (§§3.9.1 – 3.9.3)
- 3.10 Wave 1 — Reproducibility Artefact Hardening (§§3.10.1 – 3.10.4)
- 3.11 Wave 2 — Pinned-Digest Container Distribution (§§3.11.1 – 3.11.6)

**Chapter 4: Experiments**  .......................................................................................... ~140
- 4.1 Experimental Design (§§4.1.1 – 4.1.4)
- 4.2 Scenario Descriptions (§§4.2.1 – 4.2.2)
- 4.3 Execution Environment (§§4.3.1 – 4.3.4)
- 4.4 Measured Results (§§4.4.1 – 4.4.5)
- 4.5 Analysis Methods (§§4.5.1 – 4.5.4)
- 4.6 Threats to Validity (§§4.6.1 – 4.6.3)
- 4.7 Reproducibility Checklist

**Chapter 5: Results**  ................................................................................................. ~170
- 5.1 Runtime Performance (Table 5.1)
- 5.2 Reproducibility (Table 5.2)
- 5.3 Cross-engine fidelity (Fig 5.3)
- 5.4 Micro vs Meso Trade-off (Figs 5.5 – 5.7)
- 5.5 Throughput
- 5.6 Cross-engine Fairness Audit
  - 5.6.1 Demand Composition (V5+)
  - 5.6.2 Q4 Paradigm Divergence at Scale (large tier)
  - 5.6.3 Cross-platform reproducibility limits
    - 5.6.3.1 Same-architecture cross-distribution: bit-identical at large tier
    - 5.6.3.2 Mac arm64 at the current code version: matches Cardinal x86_64 to 4 sig figs
    - 5.6.3.3 Re-interpretation of the §5.6.3 2.95 % shift
- 5.7 Discussion
- 5.8 Reproducing this chapter

**Chapter 6: Discussion and Conclusion**  ..................................................................... ~210
- 6.0 Overview
- 6.1 Contributions revisited (§§6.1.1 – 6.1.5)
- 6.2 Synthesis of empirical findings
  - 6.2.1 Phase 14: BFS deduplication makes the large tier tractable
  - 6.2.2 Q4 paradigm divergence at scale
  - 6.2.3 Cross-platform reproducibility limits
  - 6.2.4 Within-engine paradigm spread: SUMO micro vs meso converges at saturation
  - 6.2.5 The fairness contract as the connecting tissue
- 6.3 Relationship to prior work (§§6.3.1 – 6.3.3)
- 6.4 Limitations and threats to validity (§§6.4.1 – 6.4.7)
- 6.5 Future work (§§6.5.1 – 6.5.7)
- 6.6 Conclusion
- 6.7 Reproducing this chapter's claims

**References**  ............................................................................................................ ~270

**Appendix A: Canonical Bundle Example**  .................................................................. ~275
**Appendix B: Plan Deviations Audit**  .................................................................... ~285
**Appendix C: Container Usage Recipe**  ...................................................................... ~295
**Appendix D: Glossary of Acronyms and Domain Terms**  ............................................. ~305

*(Page numbers in this static TOC are illustrative; LaTeX
auto-regenerates real page numbers at compile time.)*

---

## List of Figures

*(Generated from `doc/figures/` + chapter `Fig X.Y` references.
All 10 figures are PNG+PDF and committed under version control;
the LaTeX `\includegraphics` step pulls the PDF variant for
print-quality output.)*

| # | Caption | Source |
|---|---|---|
| 5.1 | Cross-engine runtime bar chart (mean engine-wall per cell, log scale) | `doc/figures/fig_5_1_runtime_comparison.pdf` |
| 5.2 | Reproducibility (R) heatmap across the 11-cell `benchmark_small` matrix | `doc/figures/fig_5_2_reproducibility_heatmap.pdf` |
| 5.3 | Travel-time comparison: cross-engine mean-TT ratios per tier | `doc/figures/fig_5_3_travel_time_comparison.pdf` |
| 5.4 | Speedup analysis: mesoscopic vs microscopic engine speed-ups | `doc/figures/fig_5_4_speedup_analysis.pdf` |
| 5.5 | SUMO micro vs meso comparison (1 K + 10 K tiers; large-tier extension in §5.4 text) | `doc/figures/fig_5_5_micro_vs_meso.pdf` |
| 5.6 | Runtime variability (boxplot of per-seed wall times) | `doc/figures/fig_5_6_runtime_variability.pdf` |
| 5.7 | P95 tail latency vs mean travel time, faceted by mode | `doc/figures/fig_5_7_p95_tail_latency.pdf` |
| 5.8 | Trip-count parity across engines (Q3 audit visualization) | `doc/figures/fig_5_8_trip_count_parity.pdf` |
| 5.9 | Demand composition: HBW + HBSchool purpose breakdown per scenario | `doc/figures/fig_5_9_demand_composition.pdf` |
| 5.10 | Wall-time vs engine-time breakdown (prep / engine / parse / harness overhead) | `doc/figures/fig_5_10_wall_vs_engine.pdf` |

**`[FILL — optional]`**: 7 additional geographic-visualization map types (od_origins, od_destinations, link_load per engine, travel_time per engine, congestion, route_diversity, animated_flow) are available in `visualization/output/<scenario>/` if you want to include 1-2 as illustrative figures (recommended: include `animated_flow_matsim_meso.mp4` first-frame as a single PNG for the chicago_200k_car saturation visualization). These are NOT auto-numbered into the Chapter 5 sequence; they would appear as Figures 5.11+ if added.

---

## List of Tables

| # | Caption | Section |
|---|---|---|
| 5.1 | Wall-clock runtime per cell (engine subprocess only), mean ± 95 % CI | §5.1 |
| 5.2 | Reproducibility R = 1 − σ/μ per cell across 5 repeats | §5.2 |
| 5.3 *(de facto)* | Cross-engine mean-TT ratios at small + large tiers (in-prose) | §5.6.2 |
| 5.4 *(de facto)* | SUMO meso ↔ SUMO micro mean-TT comparison across 3 tiers (in-prose) | §5.4 |
| 5.5 *(de facto)* | Demand-composition purpose breakdown per scenario (audit output) | §5.6.1 |

*(Tables marked "de facto" are currently rendered inline in markdown
tables in the chapter prose. If your school's thesis template
requires a numbered List of Tables for every formal table,
consider promoting §5.6.2 / §5.4 / §5.6.1 inline tables to formal
Table 5.3 / 5.4 / 5.5 with `\caption{}` + `\label{}` at LaTeX
assembly time.)*

---

## Pre-submission checklist (for the LaTeX assembly step)

- [ ] Title page formatted per OSU graduate-school template
- [ ] Committee member names filled in
- [ ] Dedication line chosen
- [ ] Acknowledgments paragraphs filled in (every `[FILL]` resolved)
- [ ] Abstract pulled from `doc/chapters/abstract.md`
- [ ] All 7 chapters compiled in order from `doc/chapters/{introduction,background,methods,experiments,results,discussion}.md`
- [ ] References pulled from `doc/references.bib` via biber + biblatex (one verify-DOI item on `cao2022lpsim`)
- [ ] Appendices A-D drafted (currently scaffolded — `doc/DEVIATIONS.md`, `doc/CONTAINER_USAGE.md`, `doc/GLOSSARY.md` are the source material; canonical bundle example pulled from `scenarios/chicago_1k_car/`)
- [ ] Page numbering correct (roman for front matter, arabic from Chapter 1)
- [ ] Margin / font / line-spacing per OSU template
- [ ] Final PDF reviewed by advisor before submission
