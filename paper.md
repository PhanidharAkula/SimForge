---
title: 'SimForge: A reproducible, cross-simulator benchmarking framework for urban traffic simulation'
tags:
  - Python
  - traffic simulation
  - urban mobility
  - reproducibility
  - benchmarking
  - SUMO
  - MATSim
  - DTALite
authors:
  - name: Phanidhar Akula
    orcid: 0009-0002-1414-2934
    corresponding: true
    affiliation: 1
affiliations:
  - name: Department of Computer Science and Software Engineering, Miami University, Oxford, OH, USA
    index: 1
date: 26 June 2026
bibliography: paper.bib
---

# Summary

SimForge is a Python framework for reproducible, cross-simulator benchmarking of urban traffic microsimulators. From a single canonical description of a city, a five-file bundle (road network, travel demand, traffic signals, run configuration, and a SHA-256 hash manifest) generated from open data such as OpenStreetMap, the U.S. Census, and LandScan population grids, SimForge drives three structurally different simulators, SUMO [@krajzewicz2012sumo], MATSim [@horni2016matsim], and DTALite [@zhou2014dtalite] (via Path4GMNS [@path4gmns2024]), from one shared, validated input. The fairness-critical machinery lives in a shared layer rather than in the engines: a strongly-connected-component and feasibility filter produces a single admissible trip set that every engine must run, and shared routes are computed once with a deterministic breadth-first search and reused across engines, so the per-engine adapters only translate the already-fair, already-routed inputs into each simulator's native format. Before any comparison is reported, a machine-checked fairness audit (questions Q1 through Q5) verifies that every engine received byte-identical inputs and computed a byte-identical feasible trip set. Each benchmark cell runs inside a content-addressed container so that results are reproducible by construction, and SimForge reports cross-engine fidelity using the root-mean-square error, the GEH statistic [@dowling2004geh], and the Kolmogorov-Smirnov distance [@smirnov1948ks], alongside scalability, throughput, and a per-cell reproducibility index computed over repeated seeds with confidence intervals, all collected into an automatically emitted scorecard.

# Statement of need

Traffic microsimulators each encode decades of modeling expertise, yet they disagree, and a reported difference between two of them is hard to interpret. When two engines report travel times that differ by, for example, 10% on the same scenario, that difference conflates the one quantity a researcher wants to isolate, a genuine paradigm-level disagreement between the engines, with several confounds: each engine may silently read the inputs differently, ship different default settings, exhibit floating-point or thread-scheduling non-determinism, or drift between undocumented software versions. Existing cross-simulator studies, including single-engine calibration efforts, small two-engine comparisons, and feature surveys [@bazzan2014review], generally do not programmatically verify that the engines received identical inputs, so a measured difference cannot be confidently attributed to the modeling paradigm.

SimForge closes this attribution gap with four mechanisms: a canonical input schema with field-level validators, deterministic fixed-seed adapters, a machine-checked Q1 to Q5 fairness audit executed before every comparison, and a content-addressed container that pins code, toolchain, and data by digest. Together these make a cross-simulator difference attributable to the modeling paradigm rather than to formatting, tuning, randomness, or version drift, in the spirit of community benchmarks such as MLPerf [@mattson2020mlperf] and the FAIR principles for reproducible research [@wilkinson2016fair; @pineau2021reproducibility]. SimForge also generates structured, activity-based travel demand (home-to-work, home-to-school, and chained trips) from open population and land-use data using a CITYSCAPE-style model [@rao2023cityscape], so that demand is realistic and reproducible rather than uniformly random.

The framework targets transportation researchers who need defensible cross-engine comparisons and practitioners who must choose a simulator for a specific planning decision. Applied across three cities and five demand tiers spanning three orders of magnitude (1,000 to 500,000 trips), SimForge showed that cross-engine agreement is regime-dependent: the engines converge at small scale but diverge sharply once the network saturates, reaching a travel-time gap of roughly 96% at the largest tier, a divergence attributable to a paradigm-level difference in congestion handling (SUMO's insertion-refusal versus MATSim's queue-hold) that engages only beyond network capacity. Because every such claim rests on a passing fairness audit and a pinned container, the result is reproducible and the difference is attributable by construction.

# Acknowledgements

The author thanks Dhananjai M. Rao for advising this work, and the maintainers of SUMO, MATSim, and Path4GMNS, whose open-source simulators make it possible.

# References
