# Abstract

Urban-mobility simulators inform high-stakes infrastructure decisions
in transportation planning, congestion management, and policy
evaluation, yet a foundational methodological gap persists: cross-
simulator results are not directly comparable because each simulator
uses different input formats, different execution conventions, and
different metric definitions. A 10 % difference in mean travel time
between two simulators on a nominally identical scenario could
reflect genuine paradigm-level disagreement or any of several
input-interpretation, configuration-tuning, version-pinning,
floating-point, threading, and platform-binary effects. Practitioners
who must choose a simulator for an actual planning decision have no
operational way to distinguish these.

This thesis presents **SimForge**, a reproducible cross-simulator
testing framework for urban mobility simulation that closes this gap
through four contributions: (C1) a canonical, simulator-agnostic
input bundle with field-level validation; (C2) byte-deterministic
adapters for SUMO, MATSim, and DTALite that translate the canonical
bundle into each engine's native input format and apply a shared
strongly-connected-component + feasibility filter; (C3) a
pinned-digest container image
(`ghcr.io/phanidharakula/simforge`) published to GitHub Container
Registry via an automated GitHub Actions workflow, providing
bit-identical reproducibility across machines; and (C4) a programmatic
cross-engine fairness audit that verifies byte-identical feasibility
verdicts (Q1), byte-identical SCC networks (Q2), identical simulated
trip-count targets (Q3), and a cross-engine mean travel-time
comparison (Q4), together with a reproducibility index R = 1 − σ/μ
and 95 % confidence intervals on every reported mean.

The framework integrates three simulator paradigms (microscopic queue
via SUMO, activity-based queue via MATSim, user-equilibrium dynamic
traffic assignment via DTALite) and is benchmarked across three U.S.
metropolitan networks (Chicago, New York City, Los Angeles) at
demand tiers from 1 K to 500 K trips per scenario. The fairness
audit (Q1-Q3) PASSes at every shipped tier, empirically demonstrating
that the canonical-input + deterministic-adapter design isolates
engine-paradigm differences from input-interpretation differences.

Three empirical findings emerged from the build and contribute to
the cross-simulator benchmarking literature beyond the original
framework deliverables. First, a shared canonical-routes BFS module
(Phase 14) reduced the chicago_200k_car benchmark wall by
approximately 20 × cold-vs-cold (from 141.87 h to 7.14 h on OSC
Cardinal) and 228 × for warm-cache re-runs, making the 500 K-trip
tier (nyc_500k_car) tractable for the first time (12 h 8 min wall
vs an ~600 h pre-Phase-14 projection). Second, the SUMO ↔ MATSim
mean travel-time ratio is regime-dependent: small-tier convergence
(within ±5 % at 50 K trips) sharply reverses at saturation, reaching
a 96.3 % gap at 500 K trips on NYC's bridge-and-corridor topology,
where SUMO's insertion-refusal model and MATSim's queue-hold model
engage divergent paradigm-level behaviors that the fairness contract
makes attributable to mobsim choice rather than input asymmetry.
Third, even with identical canonical inputs and identical version
pins, nominally identical software produces 0.2-3 % per-engine
output shifts across execution contexts; the largest measured shift
is a 2.95 % MATSim mean-TT divergence between Homebrew and Debian
OpenJDK 17 builds, with the same MATSim 15.0 JAR. To the best of
our awareness of the cross-simulator benchmarking literature, this
is the first such empirical measurement reported for activity-based
mesoscopic traffic simulation, and it establishes the pinned-digest
container as the operational mechanism that closes the
cross-platform reproducibility gap.

SimForge is open-source under the Apache License 2.0 and available
at `github.com/PhanidharAkula/SimForge`. The framework, the
canonical bundles, the audit tooling, and the pinned-digest
container are intended as a foundation for future cross-simulator
research that can build on a bit-reproducible benchmark target
rather than re-deriving fairness from scratch for each comparison.

**Keywords:** urban mobility simulation, cross-simulator benchmarking,
reproducibility, SUMO, MATSim, DTALite, dynamic traffic assignment,
agent-based simulation, container reproducibility, scientific
computing.
