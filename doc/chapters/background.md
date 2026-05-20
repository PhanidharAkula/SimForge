# Chapter 2: Background and Related Work

## 2.0 Overview

This chapter situates SimForge within the broader context of
traffic-simulation research, computational-reproducibility practice,
and cross-tool benchmarking efforts in adjacent computational fields.
It begins with the historical evolution of traffic simulation
paradigms (macroscopic, mesoscopic, microscopic, agent-based,
dynamic traffic assignment), defines the operational vocabulary
used throughout the thesis, surveys the specific simulators that
were considered for integration (with both shipped and ruled-out
engines documented), catalogs the structural incompatibilities that
have historically prevented fair cross-simulator comparison, reviews
the prior benchmark efforts in transportation simulation and in
adjacent computational fields, and closes with a summary of the
research gap that SimForge addresses.

The chapter aligns with the December 2025 thesis plan's
Chapter 2 in scope and citation set, while incorporating
retrospective updates: the engine roster reflects what was actually
integrated (SUMO, MATSim, DTALite) versus ruled out (POLARIS,
LPSim, QarSUMO, CityFlow), and §2.7 includes the cross-platform
reproducibility finding that the framework empirically measured
during Wave 2 (Chapter 5 §5.6.3).

---

## 2.1 Evolution of traffic simulation

Traffic simulation has undergone more than six decades of
methodological evolution, progressing through four major paradigm
families that today coexist in the simulator ecosystem the thesis
benchmarks.

**Macroscopic models** (1950s–1970s) treated traffic as a
continuous fluid, with each road link characterized by aggregate
quantities — density (vehicles per kilometer), flow (vehicles per
hour), and average velocity — related by the fundamental
traffic-flow equation flow = density × velocity. The Lighthill-
Whitham-Richards (LWR) kinematic-wave model is the canonical
formulation. Macroscopic models are computationally cheap and
suitable for network-wide capacity studies but cannot represent
individual vehicle interactions.

**Microscopic models** (1980s–present) reversed the abstraction
by simulating each vehicle as an independent agent with
car-following, lane-changing, and gap-acceptance dynamics. The
Krauss [Krauss 1998] and Intelligent Driver Model (IDM) [Treiber
et al. 2000] car-following formulations are widely used; SUMO's
default behavior model is a stochastic variant of Krauss with a
configurable σ parameter. Microscopic models capture the rich
vehicle-level dynamics relevant for intersection-design and
ITS-evaluation studies, at the cost of substantial per-vehicle
computational expense.

**Mesoscopic models** (1990s–present) struck a deliberate balance
by representing groups of vehicles as packets flowing through
per-link queue structures, abstracting away lane-level dynamics
while preserving network-level congestion patterns. The mesoscopic
abstraction is appropriate for regional planning studies where
network-level travel-time and throughput are the metrics of
interest. SUMO meso, MATSim qsim, and DTALite's underlying
formulation all sit in the mesoscopic family.

**Agent-based and activity-based models** (2000s–present) extend
microscopic and mesoscopic foundations by assigning each traveler
a daily activity schedule (home → work → shop → home), behavioral
attributes (mode preferences, value-of-time), and an iterative
re-planning capability under feedback from network conditions.
MATSim is the canonical activity-based agent simulator; POLARIS
extends the paradigm with integrated supply-side land-use and
behavioral econometric models.

**Dynamic Traffic Assignment (DTA)** is a distinct paradigm that
sits algorithmically alongside but operates differently from
event-driven mobsim. Rather than simulating each vehicle's
moment-by-moment behavior, a DTA solver iteratively computes the
network-wide user-equilibrium (UE) flow pattern: each OD pair's
demand is assigned to one or more paths such that no traveler can
unilaterally reduce their travel cost by switching paths. DTALite
[Zhou and Taylor 2014] is a path-based UE/SUE solver; its outputs
are link-level equilibrium flows + per-OD path travel times rather
than per-vehicle trajectories. The DTA paradigm is appropriate for
regional studies where long-run equilibrium is the question and
transient dynamics are not.

The mesoscopic and hybrid frameworks have benefited from advances
in high-performance computing, particularly distributed-memory
architectures and GPU acceleration, enabling city-scale scenarios
to run in near real-time on modern hardware [Cao et al. 2022;
Boulmakoul et al. 2023; Chan et al. 2018]. This technological
progression has produced unprecedented spatial and temporal
detail in urban-mobility modeling, while simultaneously revealing
challenges in cross-simulator compatibility, standardization, and
reproducibility that this thesis directly addresses.

---

## 2.2 Simulation scope and terminology

This work focuses on **commute-scale urban traffic simulation**,
where outputs include link-level flow and trip-time statistics at
minute-level temporal resolution. SimForge targets large metropolitan
networks (Chicago, New York City, Los Angeles) modeled under
realistic demand and congestion patterns. For clarity, the following
operational terms are used throughout the thesis:

- **Microscopic, mesoscopic, and agent-based simulation**:
  Microscopic models capture individual vehicle dynamics (acceleration,
  car-following, lane changing); mesoscopic models represent grouped
  vehicle packets or flow quanta; agent-based models extend these by
  assigning travel plans and behavioral attributes to individual
  travelers.

- **Dynamic Traffic Assignment (DTA)**: A path-based equilibrium
  formulation in which the assignment problem is solved iteratively
  until the user-equilibrium (or stochastic user-equilibrium)
  condition is met across all OD pairs. DTALite's UE solver is a
  representative instance.

- **Key performance dimensions**: *Fidelity* denotes agreement with
  observed link counts and trip-time distributions; *scalability*
  measures runtime or throughput growth relative to the number of
  simulated agents; and *reproducibility* refers to run-to-run
  invariance under fixed random seeds and identical configurations.
  Chapter 5 reports measurements along all three dimensions.

- **Canonical inputs**: A simulator-independent, normalized input
  bundle (Chapter 3 §3.2) consisting of standardized network, demand,
  signal, configuration, and manifest files, designed to support
  direct conversion into the native input formats of multiple
  engines via deterministic adapters.

- **Fairness contract**: The set of programmatic checks (Chapter 3
  §3.6.4, audit Q1-Q5) that verify every engine in a cross-simulator
  comparison received byte-identical inputs derived from the same
  canonical bundle, simulated the same trip-count target, and is
  measured under identical execution policies. The contract is the
  methodological substrate that makes cross-engine output
  differences attributable to paradigm choice rather than
  input asymmetry.

These terms are used consistently throughout the thesis and are
also defined in the glossary at `doc/GLOSSARY.md`.

---

## 2.3 Major urban mobility simulation systems

Cross-engine benchmarking demands working knowledge of the simulators
that constitute the field. This section reviews the eight major
candidates that were considered during the SimForge build,
distinguishing the three engines that were integrated and shipped
(SUMO, MATSim, DTALite) from the five that were considered and
ruled out for documented reasons (POLARIS, LPSim, QarSUMO, CityFlow,
SimMobility). The ruleout rationale is detailed in
`doc/engines/THIRD_ENGINE_OPTIONS.md` and discussed further in
Chapter 6 §6.5.4.

### 2.3.1 Engines integrated in the SimForge framework

**SUMO** (Simulation of Urban MObility) [Krajzewicz et al. 2012] is
an open-source microscopic traffic simulator originally developed at
the German Aerospace Center (DLR) and now maintained by the Eclipse
Foundation. SUMO models detailed vehicle interactions, lane
changing, and traffic-signal control, and supports both microscopic
and mesoscopic execution modes through a single binary. It is widely
used for transportation research and supports a broad range of import
formats (OSM, OpenDRIVE, VISUM, etc.), routing algorithms, and
calibration tools. SUMO's lead-developer is open about its
limitations: limited GPU utilization, single-threaded mobsim per
default, and a configuration ecosystem with substantial historical
accumulation. SimForge integrates SUMO via its Python adapter
(`adapters/sumo/`) and runs SUMO 1.26.0 from the eclipse-sumo
PyPI wheel.

**MATSim** (Multi-Agent Transport Simulation) [Horni et al. 2016]
is a mesoscopic, agent-based framework built around iterative
replanning and activity-based demand generation. It emphasizes
individual traveler behavior and long-term equilibrium modeling
under feedback. SimForge configures MATSim with `lastIteration=0`
to suppress the iterative replanning loop and produce a single-pass
deterministic mobsim output for cross-engine comparison; this
configuration choice is documented in Chapter 3 §3.4.3. SimForge
integrates MATSim 15.0 via the matsim-15.0-release.zip from the
matsim-org/matsim-libs GitHub repository.

**DTALite** [Zhou and Taylor 2014] is a path-based dynamic traffic
assignment solver distributed in C++ via the path4gmns Python wheel
[Path4GMNS]. DTALite's input format is the General Modeling Network
Specification (GMNS) [Zephyr Foundation], a CSV-based open standard
for traffic-network exchange. SimForge integrates DTALite as the
third engine in Version 5 of the framework, after the original
LPSim integration was abandoned (see §2.3.2). DTALite contributes
the user-equilibrium DTA paradigm to the cross-engine comparison,
providing the methodological breadth that the plan's original
"three paradigm" framing required.

### 2.3.2 Engines considered and ruled out

**POLARIS** [Auld et al. 2016], developed by Argonne National
Laboratory, is a multithreaded agent-based simulator that integrates
land-use, travel-demand, and behavioral models within a unified
architecture. POLARIS is designed for detailed policy analysis and
scenario testing at the metropolitan scale and has been used in
several Argonne-affiliated studies. SimForge research determined
that POLARIS source distribution is currently license-gated:
official build instructions point to a request-only access portal
at Argonne, and no major published 2023-2025 paper documents a
non-Argonne user building POLARIS from source on their own hardware.
The integration was therefore deferred (see
`doc/engines/THIRD_ENGINE_OPTIONS.md` §2.3 for the deep-research
diagnostic).

**LPSim** [Cao et al. 2022] introduces a GPU-accelerated mesoscopic
design that models lane-level traffic flow with extreme scalability,
claimed capable of simulating millions of vehicle movements per
second on modern GPUs. SimForge integrated LPSim in Version 4
(Phase B); after multiple integration attempts and a documented
spike-test failure on Pitzer's V100 GPU nodes, the integration was
abandoned in Version 5. The full retrospective is at
`doc/engines/LPSIM_RETROSPECTIVE.md`. The original GPU-comparator
role LPSim was meant to play in the cross-engine matrix is
unfilled in the shipped framework.

**QarSUMO** [Boulmakoul et al. 2023] extends SUMO with CUDA-based
multi-GPU kernels and ghost-zone synchronization, with the goal of
deterministic parallelism and faster execution on heterogeneous
computing systems. SimForge research determined that QarSUMO is
not publicly distributable: the upstream repository returns
HTTP 404 to anonymous users, no PyPI package or container image
exists, and the published cross-engine validations in the QarSUMO
literature appear to use unpublished binary distributions. The
retrospective is at `doc/engines/QARSUMO_RETROSPECTIVE.md`.

**CityFlow** [Zhang et al. 2019] is a microscopic simulator
designed for reinforcement-learning research, optimized for fast
batch simulation of small networks. SimForge research determined
that CityFlow is effectively abandoned (1 commit in the last 12
months, 0 PyPI releases, broken on Python 3.12+, and a documented
segfault pattern on real-world networks larger than ~16
intersections) and is structurally unfit for metropolitan-scale
benchmarks at the scale SimForge targets.

**SimMobility** (MIT) is a heavy in-house Linux-toolchain simulator
that was considered but estimated to require ~5× the integration
effort of DTALite. The deferral is documented in
`doc/engines/THIRD_ENGINE_OPTIONS.md` §2.4.

### 2.3.3 The shipped paradigm coverage

After the substitution and ruleouts, the shipped SimForge framework
provides three engines covering three distinct simulation paradigms:

| Engine | Paradigm | Language | Cross-engine role |
|---|---|---|---|
| SUMO meso | Microscopic queue (FIFO with insertion-refusal) | C++ | Time-stepped queue with vehicle-by-vehicle insertion |
| SUMO micro | Microscopic vehicle dynamics (Krauss car-following) | C++ | Full per-vehicle physics (lane-change, gap-acceptance) |
| MATSim | Activity-based queue (qsim with hold-and-wait) | Java/JVM | Agent-based mobsim with iterative re-planning support |
| DTALite | Dynamic Traffic Assignment (path-based UE) | C++ | Equilibrium assignment, no transient dynamics |

The three-paradigm coverage is sufficient for the cross-engine
comparison the plan originally needed; the loss of the
GPU-mesoscopic paradigm (LPSim) is documented as an open future-work
item (Chapter 6 §6.5.4).

---

## 2.4 Incompatibilities across simulators

Although major traffic simulators share similar conceptual
foundations, they diverge sharply in data models, configuration
semantics, and runtime assumptions. These differences complicate
experiment replication and make direct cross-simulator benchmarking
infeasible without standardized data structures or conversion logic.

Key incompatibilities include the following:

- **Network representation.** Each simulator encodes road networks
  differently. SUMO uses its own XML format (`.net.xml`) with
  internal lane-junction representation. MATSim uses
  `network.xml` with simpler node/link semantics. DTALite uses GMNS
  CSVs (`node.csv` + `link.csv` + `movement.csv`). Lane-level
  attributes, turn permissions, and signal phases are encoded with
  different granularities and semantic conventions across the three.

- **Demand modeling.** SUMO specifies explicit trip records
  (origin, destination, departure time) in XML; MATSim uses daily
  activity plans expressed in `plans.xml` with home/work/...
  sequences; DTALite consumes OD matrices in GMNS-format CSV.

- **Signal control.** SUMO and MATSim use different representations
  for traffic-light systems: SUMO uses flat phase tables (`*.add.xml`
  with `<tlLogic>` elements), MATSim uses nested hierarchical
  programs (`signalSystems.xml` + `signalGroups.xml` +
  `signalControl.xml`), and DTALite encodes turn restrictions via
  GMNS `movement.csv` (which path4gmns 0.10.0 does not currently
  ingest, see `doc/MODELGEN_AND_MODES.md` §9). Each representation
  has different defaults for offset, cycle length, and
  green-split assumptions.

- **Temporal and physical units.** SUMO uses seconds and m/s,
  MATSim uses seconds and m/s with iteration-driven scheduling,
  DTALite uses minutes and km/h with event-driven solver iterations.

- **Configuration parameters.** Per-engine parameters controlling
  car-following behavior, route replanning, iteration limits, and
  random-number seeds differ in naming conventions, ranges, and
  internal meaning across engines.

These inconsistencies make genuine apples-to-apples evaluation of
fidelity or performance impossible without a canonical data schema
and a set of audited converter modules — precisely the role of
SimForge's Chapter 3 §3.2 (canonical schema), §3.4 (deterministic
adapters), and §3.6.4 (programmatic fairness audit).

---

## 2.5 Existing mobility benchmarks

Previous benchmarking efforts in transportation modeling have
primarily focused on evaluating individual simulators or conducting
small-scale bake-offs under limited experimental control [TRB 2022,
Nagel and Bazzan 2019]. While informative, these studies share
several methodological limitations that restrict reproducibility and
generalizability:

1. They are often tied to a *single simulator's native input format*,
   lacking a canonical, simulator-agnostic schema for cross-engine
   evaluation. A cross-engine claim built on per-engine input
   conversions cannot rule out the possibility that the conversion
   itself produced the observed differences.

2. They typically omit *seed control*, version pinning, or
   hardware-normalized performance metrics, making results
   sensitive to environment-specific variability [Goodman et al.
   2016; Studer et al. 2019].

3. They rarely include *release-grade artifacts* such as manifests,
   checksums, or container images that would allow other researchers
   to replicate reported findings exactly [Stodden et al. 2018;
   Goodman et al. 2016].

4. They frequently apply *inconsistent or engine-specific tuning
   parameters*, introducing bias in fidelity and runtime comparisons
   across platforms [Krajzewicz et al. 2012; Horni et al. 2016;
   Auld et al. 2016; Cao et al. 2022; Boulmakoul et al. 2023].

In contrast, the SimForge framework presented in this thesis
enforces a unified canonical data bundle (Chapter 3 §3.2),
deterministic adapters for each engine (§3.4), a fixed-seed
execution policy (§3.5), hardware-normalized performance reporting
including per-core (§3.6.3), and a pinned-digest container
distribution mechanism (§3.11). These design principles align with
best practices in computational reproducibility and open
benchmarking established in other scientific domains (§2.6 below).

A critical methodological contribution of SimForge — the
programmatic cross-engine fairness audit (`evaluation/audit_fairness.py`,
Chapter 3 §3.6.4) — has no direct analog in the prior
transportation-simulation cross-comparison literature. The audit
verifies Q1 byte-identical feasibility verdicts, Q2 byte-identical
SCC networks, and Q3 identical simulated trip-count targets across
all engines in a comparison. Without programmatic Q1-Q3
verification, cross-engine TT comparisons (Q4) cannot be
attributed cleanly to paradigm differences vs input asymmetry —
exactly the gap that has limited the interpretive value of prior
cross-simulator literature.

---

## 2.6 Benchmark frameworks in adjacent domains

Standardized benchmarking has played a transformative role across
multiple fields of computational research. Frameworks such as
**MLPerf** for machine learning [Studer et al. 2019, Mattson et al.
2020], **SPEC** for system and processor performance, and **ReproZip**
for computational experiment packaging [Stodden et al. 2018; Goodman
et al. 2016] have demonstrated how controlled inputs, fixed
environments, and open reporting protocols accelerate scientific
progress and ensure comparability. These initiatives typically
mandate dataset versioning, environment specification, and public
result repositories — practices that have become foundational to
reproducible computational science.

In contrast, the traffic simulation community has lacked a
standardized, cross-simulator benchmark with equivalent
methodological rigor. Studies are typically conducted in isolation,
relying on bespoke datasets and heterogeneous computing setups, which
hinders direct comparison and long-term reproducibility [TRB 2022;
Nagel and Bazzan 2019]. The disparity is particularly visible in
the absence of community-standard input bundles: where MLPerf
specifies the exact ImageNet snapshot to use for image-recognition
benchmarks, transportation studies typically describe their inputs
in prose and provide no hash-verified artifact.

SimForge draws explicit inspiration from these established
benchmarking ecosystems, particularly **MLPerf**'s structured
reproducibility checklist (closed-division vs open-division
submission rules, accuracy gates, reference implementations) and
the **FAIR** (Findable, Accessible, Interoperable, Reusable) data
principles [Wilkinson et al. 2016], which collectively inform the
design of the SimForge canonical schema, execution policies, and
validation workflows.

Three operational analogs are worth naming explicitly:

- **MLPerf's reference implementations** correspond to SimForge's
  per-engine adapter implementations (`adapters/sumo/`,
  `adapters/matsim/`, `adapters/dtalite/`). Each is the canonical
  way to run that engine in the SimForge framework, and each is
  byte-deterministic by construction.

- **MLPerf's accuracy gate** (every submission must hit a minimum
  accuracy) corresponds to SimForge's Q1-Q3 fairness audit (every
  engine must produce byte-identical feasibility verdicts on the
  same canonical bundle).

- **MLPerf's submission packaging** (model + dataset + result
  archive) corresponds to SimForge's run-output structure
  (`benchmark_results_*.json` + per-cell `feasibility_report.json`
  + auto-emitted `reproducibility_scorecard.md`).

The cross-pollination is intentional: the cross-simulator
benchmarking community can benefit from porting well-validated
patterns from adjacent fields, and SimForge is a concrete
demonstration of that import.

---

## 2.7 Reproducibility in HPC and scientific computing

Reproducibility in high-performance computing (HPC) environments
remains a persistent challenge due to factors such as non-associative
floating-point arithmetic, nondeterministic thread scheduling,
divergent random-number streams, and compiler-dependent
optimizations [Krajzewicz et al. 2012; Cao et al. 2022; Studer
et al. 2019]. Even small numerical variations can cascade into
macroscopic differences in traffic dynamics when running agent-based
or mesoscopic simulations at scale.

To mitigate these threats, SimForge adopts a multi-layered
reproducibility strategy:

- **Containerization.** All simulations can execute within
  pinned-digest containers (OCI / Singularity), ensuring that
  dependencies, libraries, and compilers remain consistent across
  platforms and reruns. The shipped framework provides a
  `Dockerfile` at repo root, an automated GitHub Actions workflow
  publishing to GHCR, and an opt-in Singularity/Apptainer
  pull workflow for HPC. Chapter 3 §3.11 documents the design;
  Chapter 5 §5.6.3 reports the empirical reproducibility benefit.

- **Seed discipline.** A structured seeding scheme assigns one
  deterministic seed per unique (city, load, engine, hardware)
  tuple, with all random-number-generator paths explicitly logged
  for auditability and replay. The shipped framework uses seeds
  42-46 (N=5 per cell) as the canonical thesis matrix.

- **Time-step policy.** A uniform canonical `time_step` is enforced
  across all engines; simulator-specific adapters perform up- or
  down-sampling as needed while preserving a documented temporal
  mapping.

- **Hash verification.** All inputs and outputs are cryptographically
  hashed (SHA-256). The OSM PBFs are pinned in
  `osm_data/manifest.json` with SHA-256 digests; canonical bundles
  are pinned in per-scenario `manifest.xml` files; container images
  are pinned by git SHA and by OCI digest in
  `lib/container/manifest.json`. Any detected hash mismatch triggers
  an operator review (the framework does not auto-rerun, but the
  audit surfaces drift immediately).

These mechanisms align SimForge with emerging best practices for
deterministic replay, containerized workflows, and verifiable
computational pipelines in large-scale scientific simulation
[Goodman et al. 2016; Stodden et al. 2018].

### 2.7.1 Empirical contribution: cross-platform reproducibility limits

Beyond the design-time reproducibility provisions above, SimForge
contributes an empirical measurement to the reproducibility
literature: even with identical version pins and identical canonical
inputs, nominally identical software produces approximately 0.2 - 3 %
per-engine output divergence across execution contexts. The largest
measured shift in the thesis is a 2.95 % MATSim mean-TT divergence
between Homebrew and Debian builds of OpenJDK 17, with the same
MATSim 15.0 JAR and identical `numberOfThreads=1` / `lastIteration=0`
configuration. Chapter 5 §5.6.3 reports the measurement; Chapter 6
§6.2.3 discusses the implication: the pinned-digest container is the
operational mechanism that closes the cross-platform gap, providing
bit-identical results across machines as the canonical citation
target. Host-venv installs (the brew + apt path) are trace-
equivalent but not bit-identical.

To the best of our awareness of the cross-simulator benchmarking
literature, this 2.95 % cross-JVM shift is the first such empirical
measurement reported for activity-based mesoscopic traffic
simulation, though similar JVM-build-induced numerical drift has
been documented in other scientific-computing domains [for example,
high-energy physics analysis pipelines and computational
biology workflows].

---

## 2.8 Summary of research gap

Despite substantial progress in simulation modeling and
high-performance computing, several gaps continue to limit the
reliability and comparability of urban mobility research [TRB
2022; Goodman et al. 2016; Studer et al. 2019]. The most critical
limitations include:

- **Lack of standardized datasets and evaluation protocols**:
  existing studies employ heterogeneous input formats, city
  networks, and calibration procedures, preventing reproducible
  cross-study validation [Krajzewicz et al. 2012; Horni et al. 2016].

- **Inconsistent reproducibility documentation**: few simulation
  experiments provide fixed seeds, containerized environments, or
  artifact manifests, making replication and auditability difficult
  [Stodden et al. 2018; Goodman et al. 2016].

- **Absence of a neutral, open benchmark**: there is no established
  framework that allows fair, transparent comparison of major
  simulators under equivalent workloads and hardware conditions
  [Mattson et al. 2020; TRB 2022; Wilkinson et al. 2016].

- **Absence of programmatic cross-engine fairness verification**:
  prior cross-simulator studies do not include audit tooling that
  programmatically verifies input-byte-identity across engines.
  Without this verification, cross-engine output differences cannot
  be cleanly attributed to paradigm versus input-interpretation.

- **Unmeasured cross-platform reproducibility limits**: the
  transportation simulation literature does not typically report
  empirical measurements of cross-platform numerical drift, even
  though the drift exists and bounds the reproducibility of any
  cross-simulator study not run inside a pinned-digest container.

Collectively, these limitations underscore the need for a
reproducible, cross-simulator testing framework that unifies
methodology, data handling, execution-environment specification, and
fairness verification — precisely the role that **SimForge** is
designed to fulfill. The remainder of the thesis (Chapters 3-6)
describes how the framework is built, what was measured with it, and
what the measurements imply for the cross-simulator benchmarking
community.

---

## 2.9 Notation conventions for this chapter

Citations in this chapter follow the convention of the December 2025
thesis plan, using author-year style ([Krajzewicz et al. 2012]
rather than numbered references) for accessibility and to preserve
forward-compatibility with the bibliography section (which is
maintained in BibTeX form for LaTeX-based final assembly). Where a
specific document or repository URL is more precise than an
author-year citation (for example, `doc/engines/THIRD_ENGINE_OPTIONS.md`
or `path4gmns` GitHub URL), the URL is cited inline.

Engine names are written as in the upstream documentation:
*SUMO*, *MATSim*, *DTALite*, *POLARIS*, *LPSim*, *QarSUMO*,
*CityFlow*, *SimMobility*. Cross-references to other chapters
follow the form *Chapter X §Y.Z*. References to the December 2025
thesis plan use the form *plan §X.Y*.
