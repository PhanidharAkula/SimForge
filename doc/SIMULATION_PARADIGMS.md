# Simulation Paradigms: Macro / Meso / Micro

Reference for how the three traffic-simulation resolutions differ, which
SimForge engines support which, why SimForge defaults to mesoscopic for
cross-engine comparisons, and how the within-SUMO meso-vs-micro
comparison feeds into the thesis Chapter 5 narrative.

This doc is the canonical home for the meso/micro/macro question. The
short glossary entries in `doc/GLOSSARY.md` point here for the full
story.

---

## 1. The three resolutions

Traffic simulators operate at one of three levels of abstraction,
distinguished by *the unit being simulated*:

| Resolution | Unit | What's tracked per unit | Throw away |
|---|---|---|---|
| **Macro** | aggregate flow density per link | flow rate, mean speed, density | individual vehicles entirely |
| **Meso** | vehicle packet / queue on a link | per-link queue length, throughput rate, link travel time | lane choice, car-following, gap acceptance |
| **Micro** | individual vehicle | position, speed, acceleration, lane, headway, car-following decisions, lane-change intents | nothing at the vehicle level |

The trade-off curve is steep:

| | macro | meso | micro |
|---|---|---|---|
| Behavioural realism | low | medium | high |
| Compute cost per simulated hour | tiny | small | large |
| Vehicle identity preserved | no | yes (as packet) | yes (full state) |
| Typical use | regional planning forecasts | network-level operations, DTA equilibrium | intersection-level analysis, ITS evaluation |

SimForge ships **meso** and **micro**. It does not ship a macro mode,
all three engines (SUMO, MATSim, DTALite) operate at meso or micro
resolution; the engines that *do* macro (e.g., legacy four-step models)
are outside SimForge's scope.

---

## 2. What each resolution captures and misses

### Micro, "every vehicle is an agent with full physics"

A microscopic simulator models each vehicle individually with
car-following + lane-changing + intersection-conflict logic. SUMO
micro updates each vehicle's state every `--step-length` seconds
(default 1.0 s, often 0.1 s for high-fidelity studies) using the
Krauss car-following model (see `doc/GLOSSARY.md::Krauss`).

**Captures:**

- Lane changes, lane drops, lane merges (per-car decisions)
- Car-following dynamics (a Toyota braking causes the Honda behind it to brake)
- Gap acceptance at unsignalized intersections ("does this turning car find a gap?")
- Per-vehicle queue position (front-of-queue vehicles depart first when signal turns green)
- Signal-timing effects on individual cars (did this car make the green?)
- Driver heterogeneity (different reaction times, desired speeds)
- Headway distributions

**Misses:**

- Nothing at the vehicle level. (Edge cases: pedestrian interactions,
  weather, mechanical failures, typically modeled by extensions.)

**Cost shape:** Roughly **O(N_vehicles × simulated_seconds /
step_length)**. Doubling vehicles doubles cost; halving step length
doubles cost.

### Meso, "vehicles are packets queueing on links"

A mesoscopic simulator treats each link as a queue with a service rate.
Vehicles enter, wait in queue, get served, and exit. There's no notion
of *which lane* a vehicle is in, the link is one fat aggregated
service unit.

**Captures:**

- Link travel time as a function of queue length
- Queue spillback (when a downstream link's queue overflows back into the upstream link)
- Aggregate signal-controlled throughput (cycle-length, green-split effects)
- Network-level congestion patterns
- OD flow allocation under equilibrium (in DTA variants like DTALite)

**Misses:**

- Lane-level behavior (lane changes are smoothed away)
- Car-following effects (no headway dynamics; throughput is a fixed rate)
- Gap acceptance (intersections are modeled as queue-service points)
- Lane drops and merges (no representation of which lane a vehicle is in)
- Driver heterogeneity (every vehicle is "average")

**Cost shape:** Roughly **O(N_links × simulated_seconds / event_step)**.
Near-constant in vehicle count, adding vehicles only adds to a queue
counter, not new physics calculations. This is why meso is 10–100× faster
than micro on the same scenario.

### Macro, "flow as fluid density"

Not used by SimForge. A macroscopic simulator treats traffic as a
continuous fluid: each link has a density (veh/km), a flow (veh/h),
and a velocity (km/h) related by the fundamental traffic-flow equation
*flow = density × velocity*. Individual vehicles do not exist as
distinct entities.

Mentioned here only for taxonomy completeness, SimForge's `mode`
column (`car`, `transit`, `bike`, `walk` in `demand.csv`) operates
on individual trip records, so macro is out of scope by construction.

---

## 3. Per-engine support matrix

| Engine | Meso | Micro | Macro |
|---|---|---|---|
| **SUMO** | ✓ (`mesosim`) | ✓ (default) | ✗ |
| **MATSim** | ✓ (only mode) | ✗ | ✗ |
| **DTALite** | ✓ (only mode, DTA/UE flavour) | ✗ | ✗ |

**Key implication for SimForge:** cross-engine comparisons can only be
done at **meso**, because that's the only paradigm all three engines
support. Cross-engine comparisons at micro would be a SUMO-only single-
engine table, which is uninteresting for a cross-simulator benchmark.

This drives the runspec design:

- `runspecs/benchmark_small.yaml`, `benchmark_large.yaml`,
  `benchmark_large.yaml` runs **meso** for SUMO + MATSim + DTALite to
  produce cross-engine Q1–Q4 fairness data.
- SUMO **micro** is included separately as a *within-engine* comparison
  on smaller bundles (chicago_1k_car, nyc_10k_car) to characterize the
  meso-vs-micro fidelity gap inside SUMO.

The `ENGINE_SUPPORTED_MODES` constant in `run.py` enforces this:
asking for `--engine matsim --mode micro` raises a validation error
before any cell starts.

---

## 4. Why SimForge defaults to meso for cross-engine comparisons

The fairness contract (`doc/ARCHITECTURE.md` §1) requires that every
adapter receives the same canonical input and runs the same paradigm.
There's no fair way to compare *MATSim meso* to *SUMO micro*, they're
not solving the same problem. So:

- **Cross-engine fairness (Q1–Q4)**: meso for all three engines.
- **Within-engine resolution comparison**: SUMO meso vs SUMO micro on
  the same bundle. Shows how much vehicle-level detail meso throws
  away, and at what cost.

The thesis Chapter 5 has space for both stories: the cross-engine
*paradigm-divergence* finding (SUMO/MATSim mean-TT ratio at meso) and
the within-SUMO *resolution* finding (how much meso under- or
over-estimates trip time relative to its micro counterpart on the
same scenario).

---

## 5. Empirical cost ratios from benchmark_small

From the Wave 1 scorecard on `runs/benchmark_small/` (5 seeds each):

| Scenario | Trips | SUMO meso `engine_wall` | SUMO micro `engine_wall` | Micro / Meso |
|---|---:|---:|---:|---:|
| `chicago_1k_car` | 1,000 | 268 s | 343 s | **1.3×** |
| `nyc_10k_car` | 10,000 | 662 s | 1,144 s | **1.7×** |

The slowdown ratio is mild at low scale because both modes spend most
of the runtime on simulator setup + the same 24 h time-stepping. As
trip count and congestion density grow, micro's per-vehicle
interactions dominate and the ratio widens.

Reproducibility on micro is slightly looser than meso, because the
Krauss model has a stochastic sigma parameter that produces small
seed-driven variance:

| Scenario | SUMO meso R | SUMO micro R |
|---|---:|---:|
| `chicago_1k_car` | 0.998 | 0.995 |
| `nyc_10k_car` | 0.956 | 0.973 |

Both well within the "Excellent" / "Good" bands, micro is not
unreproducible, it just doesn't hit the byte-deterministic R = 1.000
that MATSim and DTALite achieve at `lastIteration=0`.

---

## 6. Scaling SUMO micro to the large tier

Phase 14 (canonical-routes deduplication + parallel BFS + MATSim
O(N)→O(1) link-find) collapsed the BFS *prep* cost. The engine
runtime is unchanged, it scales the same way it always did:

| Scenario | Trips | Linear extrapolation | Super-linear (1.5–2×) | Engine wall per cell |
|---|---:|---:|---:|---|
| `chicago_200k_car` micro | 200,000 | 343 × 200 = **19 h** | **28–38 h** | borderline-feasible |
| `nyc_500k_car` micro | 500,000 | 1144 × 50 = **16 h** | **24–32 h** | feasible per cell, 5-seed matrix expensive |

Why super-linear? Micro models per-vehicle interactions (lane changes,
car-following decisions, gap acceptance). As congestion density grows,
each vehicle interacts with more neighbours per time-step, so cost
scales between O(N) and O(N²) depending on network density. The
shipped 1K-and-10K observations are mostly in the linear regime
because congestion is light; 200K on chicago's network is
medium-density, 500K on NYC is high-density.

**Memory.** SUMO micro tracks per-vehicle state (lane position,
speed, acceleration), typically 2–5× the RAM of meso. Phase 13
chicago_200k_car meso peaked at 23 GB. Micro is expected at 50–115 GB
(fits Cardinal's 192 GB nodes). nyc_500k_car micro could push 150–300 GB
(may require a fat-node allocation or it OOMs).

**Recommended path for the thesis:**

1. Single-seed pilot of `chicago_200k_car` SUMO micro to measure
   actual engine_wall (the linear vs super-linear regime is hard to
   predict from 1K/10K extrapolation).
2. If pilot fits in ~30 h SLURM wall, run the full 5-seed micro
   matrix on `chicago_200k_car`. Gives the within-SUMO meso-vs-micro
   comparison at the headline scale.
3. **Skip nyc_500k_car SUMO micro** for the defense. It's a
   confirmatory data point (we already know micro is slower than
   meso) that would consume disproportionate compute. Document as a
   a deviation in the limitations appendix if needed.

---

## 7. Cost-model intuition for the defense Q&A

A pocket-sized framing if the committee asks why SimForge defaults to
meso:

> **Mesoscopic** treats vehicles as fluid packets flowing on links,
> captures network-level congestion and signal effects, but smooths
> away per-vehicle behavior. **Microscopic** simulates every vehicle
> as a full agent with car-following, lane changes, and gap
> acceptance, captures the rich vehicle-level detail at significant
> compute cost. SimForge runs cross-engine comparisons at meso because
> that's the paradigm all three engines support (SUMO, MATSim,
> DTALite), and runs SUMO micro as a within-engine resolution check
> on smaller bundles. The cross-engine fairness contract requires
> every adapter to receive the same canonical input and run the same
> paradigm; comparing MATSim meso to SUMO micro would be comparing
> different solutions to different problems.

---

## 8. Within-engine meso-vs-micro: the thesis story

The original aim (Chapter 5 implicit) was *fidelity vs reality*,
how close each engine is to observed Chicago/NYC/LA traffic. Without
observed ground truth, SimForge does the next-best thing in two
directions:

- **Across engines (Q4)**: how much do SUMO meso, MATSim meso, and
  DTALite disagree on the same canonical bundle? → paradigm divergence
  finding (the 0.645 SUMO/MATSim TT ratio on chicago_200k Phase 14).
- **Within SUMO (meso vs micro)**: how much does the meso queue model
  under- or over-estimate trip time relative to its micro
  counterpart on the *same* scenario? → resolution-fidelity finding.

The within-SUMO comparison is the closest thing to "ground truth" the
shipped data supports, micro is closer to reality than meso (because
it models more of the relevant physics), so the meso-vs-micro gap
inside SUMO is an upper bound on the meso-only inaccuracy of the
cross-engine results.

If the chicago_200k SUMO micro pilot lands in time, this becomes a
Chapter 5 §5.7 (or similar) result:

> *"At the 200K scale on chicago, SUMO meso reports mean travel time
> X seconds and SUMO micro reports Y seconds, a gap of Z%. This is
> the inherent meso-paradigm error within SUMO on this bundle. The
> cross-engine meso comparison (SUMO meso vs MATSim meso, ratio
> 0.645) is therefore measuring engine-divergence on top of an
> already meso-bounded approximation error."*

If the pilot doesn't land in time, the cross-engine Q4 finding stands
on its own as a paradigm-divergence result.

---

## 9. Where this lives in the code

- `run.py`, `--mode meso|micro` CLI flag; `ENGINE_SUPPORTED_MODES`
  enforces per-engine compatibility.
- `runspecs/*.yaml` `mode:` field per cell; `benchmark_large.yaml`
  declares the full meso + SUMO-micro matrix.
- `adapters/sumo/sumo_adapter.py`, passes `--meso` to SUMO when
  `mode=meso`; default is micro.
- `adapters/matsim/`, `adapters/dtalite/`, mode is informational,
  always run their native (meso) paradigm; raise on `mode=micro`.
- `evaluation/audit_fairness.py::_discover_modes`, walks each
  scenario directory listing modes present on disk per cell.
- `tests/test_adapter_determinism.py`, covers both meso and micro
  byte-identity (where the engine supports both).

---

## References

- `doc/GLOSSARY.md`, short Mesoscopic / Microscopic / Krauss /
  PCE / DTA entries link back to this doc for the long form.
- `doc/ARCHITECTURE.md`, fairness contract, engine compatibility
  matrix.
- the limitations appendix: engine substitution, no grid-search
  calibration, and vehicles/sec/core.
- `doc/MODELGEN_AND_MODES.md`, the *other* meaning of "mode" in
  SimForge: travel mode (car/transit/bike/walk), not simulation
  resolution. Easy source of confusion.
- `doc/RESULTS_GUIDE.md` §2, `run.py` vs `run_benchmark.py`
  side-by-side, including the `--mode` flag and runspec `mode:` field.
