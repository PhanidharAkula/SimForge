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
date: 14 July 2026
bibliography: paper.bib
---

# Summary

SimForge is a Python framework for reproducible, cross-simulator benchmarking of urban traffic simulators. From a single canonical description of a city, a five-file bundle (road network, travel demand, traffic signals, run configuration, and a SHA-256 hash manifest) generated from open data such as OpenStreetMap, the U.S. Census, and LandScan population grids, SimForge drives three structurally different simulators, SUMO [@krajzewicz2012sumo], MATSim [@horni2016matsim], and DTALite [@zhou2014dtalite] (via Path4GMNS [@path4gmns2024]), from one shared, validated input. The fairness-critical machinery lives in a shared layer rather than in the engines: a strongly-connected-component and feasibility filter produces a single admissible trip set that every engine must run, and shared routes are computed once with a deterministic breadth-first search and reused across engines, so the per-engine adapters only translate the already-fair, already-routed inputs into each simulator's native format. Before any comparison is reported, a machine-checked fairness audit (questions Q1 through Q5) verifies that every engine received byte-identical inputs and computed a byte-identical feasible trip set. Each benchmark cell runs inside a content-addressed container so that results are reproducible by construction, and SimForge reports cross-engine fidelity using the root-mean-square error, the GEH statistic [@dowling2004geh], and the Kolmogorov-Smirnov distance [@smirnov1948ks], alongside scalability, throughput, and a per-cell reproducibility index computed over repeated seeds with confidence intervals, all collected into an automatically emitted scorecard.

# Statement of need

Traffic simulators each encode decades of modeling expertise, yet they disagree, and a reported difference between two of them is hard to interpret. When two engines report travel times that differ by, for example, 10% on the same scenario, that difference conflates the one quantity a researcher wants to isolate, a genuine paradigm-level disagreement between the engines, with several confounds: each engine may silently read the inputs differently, ship different default settings, exhibit floating-point or thread-scheduling non-determinism, or drift between undocumented software versions. Existing cross-simulator studies, including single-engine calibration efforts, small two-engine comparisons, and feature surveys [@bazzan2014review], generally do not programmatically verify that the engines received identical inputs, so a measured difference cannot be confidently attributed to the modeling paradigm.

SimForge closes this attribution gap with four mechanisms: a canonical input schema with field-level validators, deterministic fixed-seed adapters, a machine-checked Q1 to Q5 fairness audit executed before every comparison, and a content-addressed container that pins code, toolchain, and data by digest. Together these make a cross-simulator difference attributable to the modeling paradigm rather than to formatting, tuning, randomness, or version drift, in the spirit of community benchmarks such as MLPerf [@mattson2020mlperf] and the FAIR principles for reproducible research [@wilkinson2016fair; @pineau2021reproducibility]. SimForge also generates structured, activity-based travel demand (home-to-work, home-to-school, and chained trips) from open population and land-use data using a CITYSCAPE-style model [@rao2023cityscape], so that demand is realistic and reproducible rather than uniformly random. The framework targets transportation researchers who need defensible cross-engine comparisons and practitioners who must choose a simulator for a specific planning decision.

# State of the field

The engines SimForge orchestrates are mature, widely used systems: SUMO [@krajzewicz2012sumo] for microscopic and mesoscopic simulation, MATSim [@horni2016matsim] for agent-based queue simulation, and DTALite [@zhou2014dtalite] for dynamic-traffic-assignment user equilibrium, run through Path4GMNS [@path4gmns2024]. Around them sits a rich open-source ecosystem in which each tool addresses one layer of the workflow: dyntapy [@ortmann2022dyntapy] provides static and dynamic traffic assignment in Python, ActivitySim [@activitysim] generates activity-based travel demand for planning agencies, and CityFlow [@zhang2019cityflow] offers a fast simulator aimed at reinforcement-learning research. Each of these is an engine or a modeling layer; none is a neutral harness for comparing engines against one another.

Cross-simulator evidence in the literature therefore comes largely from ad hoc pairwise comparisons and qualitative feature surveys [@bazzan2014review], which rarely verify programmatically that every engine consumed identical inputs, leaving paradigm effects confounded with input-translation artifacts, configuration defaults, and version drift. Adjacent fields solved the analogous problem with community benchmark harnesses such as MLPerf [@mattson2020mlperf], which made claims comparable by standardizing inputs, rules, and audits. Urban traffic simulation has lacked an equivalent. SimForge fills that role: it is not another simulator but the benchmarking layer that runs existing simulators under a machine-checked fairness contract.

# Software design

SimForge is organized as three layers with one deliberate rule: everything fairness-critical lives in shared code, never in per-engine code. The generation pipeline builds the canonical five-file bundle from open data; thin adapters translate that bundle into each engine's native format under a three-function contract (prepare, run, parse); and the evaluation layer runs the fairness audit and computes all metrics. Adding an engine means implementing the three functions, while the audit and metrics apply unchanged.

Four trade-offs shaped the design. First, the canonical schema is deliberately a common denominator: it carries validated, hash-pinned data that every engine can consume symmetrically. For example, traffic-signal phase tables are validated and hash-pinned in the bundle but not yet wired into engine dynamics, so all engines simulate the same unsignalized network rather than asymmetrically signalized ones. Second, feasibility and routing are computed once, upstream of every engine: a shared strongly-connected-component filter fixes the admissible trip set, and a deterministic parallel breadth-first search produces one route set that SUMO and MATSim both drive, so differences between them isolate traffic-flow dynamics rather than routing disagreement; DTALite retains its native equilibrium assignment, and the audit reports this as a documented asymmetry instead of hiding it. Third, comparability wins over engine-optimal tuning: fixed seeds and deterministic single-run configurations are the defaults, and the same seed and horizon propagate to every engine from one configuration file. Fourth, reproducibility is anchored to content digests rather than version numbers: results are tied to a container image pinned by SHA-256 digest, a choice motivated by the observation that identical version pins can still admit output drift between time-separated runs when surrounding code or data changes.

# Research impact statement

SimForge underpins the author's master's thesis (Miami University, defended July 2026), whose cross-engine findings, obtained across Chicago, New York City, and Los Angeles at demand tiers from 1,000 to 500,000 trips, are reported separately, and a companion research manuscript for a transportation venue is in preparation. The repository ships the complete materials to reproduce that evidence base: pinned canonical scenario bundles, runspecs for the canonical 55-run benchmark matrix, a 668-test suite exercised in continuous integration, versioned releases, and a published container image pinned by SHA-256 digest, so the benchmark reproduces end-to-end from a single command per scenario. The near-term significance is practical: researchers comparing engines gain a harness in which any reported difference is backed by a passing fairness audit, practitioners selecting a simulator for a planning decision gain audit-backed evidence in place of anecdote, and engine developers gain a controlled rig in which paradigm-level behavioral differences become visible and attributable.

# AI usage disclosure

The author used Anthropic's Claude, a large language model, as an assistant during development, helping draft code, tests, and documentation, and helping edit this manuscript. The framework's design, the experimental methodology, and all reported results are the author's own; the author reviewed, tested, and validated all AI-assisted output and takes full responsibility for the software and this paper.

# Acknowledgements

The author thanks Dhananjai M. Rao for advising this work, and the maintainers of SUMO, MATSim, and Path4GMNS, whose open-source simulators make it possible.

# References
