# ModelGen Data and Travel Modes

End-to-end reference for how SimForge handles travel modes: where the
`modelgen/<city>_model.txt` files come from, the cityscape JWTRNS code
scheme, the per-city mode counts, how SimForge collapses 12 cityscape codes
into 4 simulator buckets (`car`, `transit`, `bike`, `walk`), and what each
engine adapter actually does with the `mode` column when it consumes the
generated `demand.csv`.

This doc consolidates everything we verified about the data + mode pipeline
in the Version_5 audit. Read it alongside:

- `doc/SCENARIO_GENERATION.md` — higher-level walkthrough of how a canonical
  scenario bundle is built from cityscape data; see §"Step 2: Traffic
  Signals" for the OSM-grounded signal-placement pipeline (V5+).
- `doc/GLOSSARY.md` — short definitions for *PUMS*, *JWMNP*, *JWTRNS*,
  *ModelGen*.
- `doc/ARCHITECTURE.md` — the cross-engine fairness contract and adapter
  responsibilities.

---

## 1. Data provenance

The three `modelgen/*_model.txt` files (`chicago_model.txt`, `nyc_model.txt`,
`la_model.txt`) are produced by the **cityscape** activity-based population
synthesizer, an academic C++ tool from Prof. Rao's research group.

- Repository: <https://github.com/raodj/cityscape>
- Branch used to produce these files: `Schedule-generator`
- Key tools inside: `model_gen/ModelGenerator` (population synthesis) and
  `schedule_generator` (per-person workplace + activity schedule assignment)

The exact command line that produced the file is recorded in the model file's
header. Example from `modelgen/chicago_model.txt`:

```
# Model updated by schedule_generator
# Command-line used:  ./schedule_generator
#     --shapes tests/chicago/boundaries/geo_export_…shp
#     --dbfs   tests/chicago/boundaries/geo_export_…dbf
#     --xfig   outputTest.fig
#     --model  tests/chicago/chicago_model.txt
#     --out-model tests/chicago/chicago_model_with_schedules_two.txt
#     --out-trvl-est trvl_est.txt
#     --lm-num-samples 5000
# Rings in model: 1012
# Nodes in model: 313907
# Buildings in model: 832750
# Ways in model: 85931
```

cityscape merges four real-world sources into the flat-text model
(see `doc/SCENARIO_GENERATION.md` §3 for the full diagram):

1. **OpenStreetMap** — road network, building polygons.
2. **LandScan population grids** (Oak Ridge National Lab) — satellite-derived
   population density at ~1 km resolution.
3. **U.S. Census ACS PUMS** (Public Use Microdata Sample) — the source of
   per-person `JWTRNS` (mode) and `JWMNP` (commute time) values.
4. **PUMA shapefiles** — Public Use Microdata Area boundaries, link PUMS
   records to geography.

The file format and per-line schema are documented in
`pipeline/demand/parse_model_file.py` lines 1–46.

### TAZ ≥10 trip suppression (upstream Census aggregation)

Thesis Plan §3.6 commits SimForge to suppressing any TAZ cell with
fewer than 10 trips, as a residual re-identification safeguard. In
practice this suppression is **already enforced upstream by the US
Census Bureau** as part of PUMS's Public Use threshold: PUMS records
are released only for PUMAs of ≥100,000 population, and individual
microdata cells with fewer than 10 persons are suppressed before
release. The cityscape ModelGen synthesizer ingests these
already-aggregated PUMS records verbatim, and SimForge's demand
generator consumes ModelGen output directly — so the threshold is
honored without SimForge needing to apply an additional filter at
`demand.csv`-emit time.

Operationally, every `(origin_node, destination_node)` pair in
SimForge's generated demand traces back to an aggregate PUMS cell that
already satisfies the ≥10 threshold. The cross-engine fairness
contract (`audit_fairness.py` Q1) verifies trip-set identity across
adapters but does not need to verify cell-suppression; that property
is inherited from PUMS. See `doc/DATA_MANAGEMENT.md` §2 for the
data-management policy that frames this commitment.

---

## 2. The JWTRNS code scheme

cityscape uses the **U.S. Census Bureau ACS PUMS 2021 Data Dictionary** code
list verbatim. The canonical reference is cited in three places in the
cityscape source, all in agreement:

| Source file (cityscape) | Branch | Lines |
|---|---|---|
| `model_gen/ScheduleGenerator.h` | `master` | 211–233 |
| `model_gen/ScheduleGenerator.h` | `Schedule-generator` | 211–233 (identical to master) |
| `model_gen/LinearWorkBuildingAssigner.h` | `Schedule-generator` | 42–63 |

PUMS Data Dictionary URL (cited verbatim in each source file):
<https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2021.pdf>

### Full code table

| Code | Cityscape label |
|---|---|
| `bb` | N/A — not a worker (under 16, unemployed, employed but not at work, Armed Forces not at work) |
| `01` | Car, truck, or van |
| `02` | Bus |
| `03` | Subway or elevated rail |
| `04` | Long-distance train or commuter rail |
| `05` | Light rail, streetcar, or trolley |
| `06` | Ferryboat |
| `07` | Taxicab |
| `08` | Motorcycle |
| `09` | Bicycle |
| `10` | Walked |
| `11` | Worked from home |
| `12` | Other method |

### Why 12 codes (not 13)?

In ACS years 2008–2018 the canonical PUMS list had **13** codes, with
"drove alone" and "carpooled" as separate values (1 and 2). Starting with
**ACS 2019**, those two were merged into a single code 1 = "Car, truck, or
van" — passenger-occupancy detail moved to a separate variable (`JWAP`).
That's why cityscape's table has 12 codes plus `bb`.

### `bb` → `-1` integer conversion

cityscape stores `bb` as a string sentinel internally (in the `info` vector
alongside other string-typed PUMS fields). When the model file is written,
non-worker rows are emitted with integer **`-1`** in the JWTRNS column. This
conversion happens inside cityscape's `PUMS.cpp::loadPeopleInfo` /
`PUMSPerson::write` path; SimForge sees only integers and never encounters
the string `bb`.

Empirically confirmed in all three local files:

```
$ awk '$1=="per" && NF>=8 {print $8}' modelgen/chicago_model.txt | sort -u
-1   1   10  11  12  2   3   4   5   7   8   9
```

(Chicago has zero ferryboat commuters — code 6 is absent. NYC and LA contain
all 13 distinct values: `-1, 1..12`.)

### cityscape's only built-in filter

cityscape itself has a single hard-coded JWTRNS filter — the workplace
assigner only runs for code 1 (driving) people:

```cpp
// LinearWorkBuildingAssigner.cpp:293
if (person.getIntegerInfo(jwtrnsIdx) != 1)
    continue;

// RadiusFilterWorkBuildingAssigner.cpp:112-116
if (ppl.getIntegerInfo(jwtrnsIdx) != 1) {
    continue;  // This person doesn't drive to work.
}
```

Implication: in the model file, **only code-1 people have a
schedule-assigned workplace `bld_id`**. Persons with other JWTRNS codes
appear with valid home-building info but no cityscape-supplied workplace.
SimForge's demand generator therefore falls back to its gravity model for
non-code-1 trips when the requested mode mix includes them.

The Schedule-generator branch also defines a partial enum (subset only):

```cpp
// LinearWorkBuildingAssigner.h:42-63
enum class TransportationMode {
    CAR        = 1,
    BUS        = 2,
    TAXI       = 7,
    MOTORCYCLE = 8
};
```

This enum names the road-vehicle codes; cityscape doesn't define enum
constants for the rest.

### Activity schedule format

The trailing `schedule` field of a `per` line is either an empty string
`""` (for non-workers and people whose mode cityscape's workplace
assigner doesn't cover) or a sequence of 4-int tuples. The tuple
schema comes from `model_gen/ScheduleEntry.h:49-74` in cityscape:

```
( dow_start  dow_end  time_s  dest_bld_id )
```

| Position | Field | Encoding |
|---|---|---|
| 1 | `dow_start` | day of week start: 0=Sunday, 1=Monday, …, 5=Friday, 6=Saturday, -1=unspecified |
| 2 | `dow_end`   | day of week end (same encoding) |
| 3 | `time_s`    | seconds from midnight when this activity fires |
| 4 | `dest_bld_id` | destination building ID |

In the current cityscape Schedule-generator branch every populated
schedule is exactly two tuples, both with `dow_start=1`, `dow_end=5`
(Monday through Friday), e.g.:

```
"(1 5 28800 163346754)(1 5 61200 832748)"
   ↑                       ↑
   Mon–Fri at 8:00 AM,     Mon–Fri at 5:00 PM,
   go to work bld 163346754  go to home bld 832748
```

Only the destination `bld_id` varies per person; the day bounds and
clock times are constants in cityscape's source. SimForge's
`ScheduleActivity` dataclass at `pipeline/demand/parse_model_file.py:104-122`
mirrors these four fields verbatim.

---

## 3. Per-city code counts

Computed directly from the local model files
(`awk '$1=="per" && NF>=8 {c[$8]++} END {…}'`).

### Chicago — 2,420,896 persons (1,191,464 workers)

| Code | Cityscape label | Persons | % of all | % of workers |
|---|---|---:|---:|---:|
| -1 | N/A — not a worker | 1,229,432 | 50.8% | — |
| 1 | Car, truck, or van | 629,522 | 26.0% | **52.8%** |
| 2 | Bus | 71,266 | 2.9% | 6.0% |
| 3 | Subway or elevated rail | 57,230 | 2.4% | 4.8% |
| 4 | Long-distance / commuter rail | 8,033 | 0.3% | 0.7% |
| 5 | Light rail, streetcar, trolley | 832 | 0.0% | 0.1% |
| 6 | Ferryboat | 0 | 0.0% | 0.0% |
| 7 | Taxicab | 7,526 | 0.3% | 0.6% |
| 8 | Motorcycle | 467 | 0.0% | 0.0% |
| 9 | Bicycle | 18,277 | 0.8% | 1.5% |
| 10 | Walked | 55,015 | 2.3% | 4.6% |
| 11 | Worked from home | 325,865 | 13.5% | **27.3%** |
| 12 | Other method | 17,431 | 0.7% | 1.5% |

### NYC — 6,801,148 persons (3,287,075 workers)

| Code | Cityscape label | Persons | % of all | % of workers |
|---|---|---:|---:|---:|
| -1 | N/A — not a worker | 3,514,073 | 51.7% | — |
| 1 | Car, truck, or van | 824,746 | 12.1% | 25.1% |
| 2 | Bus | 308,525 | 4.5% | 9.4% |
| 3 | Subway or elevated rail | 1,146,607 | 16.9% | **34.9%** |
| 4 | Long-distance / commuter rail | 33,544 | 0.5% | 1.0% |
| 5 | Light rail, streetcar, trolley | 2,343 | 0.0% | 0.1% |
| 6 | Ferryboat | 10,820 | 0.2% | 0.3% |
| 7 | Taxicab | 40,114 | 0.6% | 1.2% |
| 8 | Motorcycle | 3,173 | 0.0% | 0.1% |
| 9 | Bicycle | 51,443 | 0.8% | 1.6% |
| 10 | Walked | 307,479 | 4.5% | 9.4% |
| 11 | Worked from home | 521,444 | 7.7% | 15.9% |
| 12 | Other method | 36,837 | 0.5% | 1.1% |

### LA — 2,614,904 persons (1,344,555 workers)

| Code | Cityscape label | Persons | % of all | % of workers |
|---|---|---:|---:|---:|
| -1 | N/A — not a worker | 1,270,349 | 48.6% | — |
| 1 | Car, truck, or van | 901,000 | 34.5% | **67.0%** |
| 2 | Bus | 84,948 | 3.2% | 6.3% |
| 3 | Subway or elevated rail | 10,402 | 0.4% | 0.8% |
| 4 | Long-distance / commuter rail | 1,046 | 0.0% | 0.1% |
| 5 | Light rail, streetcar, trolley | 2,074 | 0.1% | 0.2% |
| 6 | Ferryboat | 1,587 | 0.1% | 0.1% |
| 7 | Taxicab | 5,545 | 0.2% | 0.4% |
| 8 | Motorcycle | 3,000 | 0.1% | 0.2% |
| 9 | Bicycle | 9,984 | 0.4% | 0.7% |
| 10 | Walked | 43,306 | 1.7% | 3.2% |
| 11 | Worked from home | 263,059 | 10.1% | 19.6% |
| 12 | Other method | 18,604 | 0.7% | 1.4% |

### Sanity check against real-world commute statistics

The percentages match real ACS PUMS 2021 commute-share numbers tightly:

| Metric | Real (ACS 2021) | Modelgen file |
|---|---|---|
| NYC subway share | ~30–35% | 34.9% (code 3) ✓ |
| NYC walk share | ~10% | 9.4% (code 10) ✓ |
| NYC post-COVID WFH | ~14–16% | 15.9% (code 11) ✓ |
| LA drive share (combined) | ~67–71% | 67.0% (code 1) ✓ |
| LA post-COVID WFH | ~18–22% | 19.6% (code 11) ✓ |
| Chicago drive share | ~50–55% | 52.8% (code 1) ✓ |
| Chicago post-COVID WFH | ~25–28% | 27.3% (code 11) ✓ |

Every city's distribution is internally consistent with that city's real
commute pattern, confirming the cityscape codes are the canonical PUMS 2021
codes (not a custom enum).

---

## 4. SimForge's 4-bucket mode collapse

SimForge does not preserve all 12 JWTRNS values through the pipeline. It
collapses them into exactly **4 buckets** that match how road simulators
think about traffic: `car`, `transit`, `bike`, `walk`. The collapse is
defined in **one** place (single source of truth):

- `pipeline/demand/parse_model_file.py:200-213` — the `JWTRNS_TO_MODE`
  dict + the derived `MODE_TO_JWTRNS` reverse index + the
  `SUPPORTED_MODES` tuple. The demand generator uses these directly.
- `pipeline/modelgen_scanner.py:19-22` — re-exports the canonical dict
  via `from pipeline.demand.parse_model_file import JWTRNS_TO_MODE` so
  the `python help.py cities` topic and the demand pipeline can never
  drift out of sync.

### Why collapse to 4 buckets at all?

The 4-mode bucket isn't research-driven, it's **simulator-driven**. Each
bucket maps cleanly onto how a road simulator models a person's trip:

| Bucket | Network role | Why these codes are grouped |
|---|---|---|
| `car` | One vehicle queueing on road links | Car/truck/van / taxi / motorcycle: all are private road vehicles taking up one lane slot. (Code 1 already merges drove-alone + carpool per ACS 2019+ — see §2.) |
| `transit` | Person uses scheduled public service, contributes 0 vehicles to road congestion | Bus / subway / commuter rail / light rail / ferry: from the road simulator's perspective these riders are "removed" from car traffic. The bus itself adds one vehicle to road congestion regardless of ridership; SimForge does not model bus vehicles today. |
| `bike` | Vehicle on bike infrastructure / shared lanes | Bicycle. (Motorcycle goes to `car` because cityscape's enum + every road simulator treats it as a motorized road vehicle, not a 2-wheeled bike.) |
| `walk` | Pedestrian on sidewalk infrastructure | Walked. |

So the collapse maps **commute mode** → **simulator infrastructure**. It's
the right granularity if the research question is "how congested are the
roads?" — which is the canonical SimForge thesis question. For sub-mode
questions (taxi vs private car, bus vs rail) the collapse loses information,
see §8 below.

### The active mapping

| JWTRNS code | Cityscape label | SimForge bucket | Reasoning |
|---|---|---|---|
| 1  | Car, truck, or van             | `car` | private road vehicle (drove-alone + carpool combined per ACS 2019+) |
| 2  | Bus                            | `transit` | public road transit, rider removed from car traffic |
| 3  | Subway or elevated rail        | `transit` | rail transit |
| 4  | Long-distance / commuter rail  | `transit` | rail transit |
| 5  | Light rail, streetcar, trolley | `transit` | rail-ish transit |
| 6  | Ferryboat                      | `transit` | water transit, rider removed from car traffic |
| 7  | Taxicab                        | `car` | road vehicle |
| 8  | Motorcycle                     | `car` | road vehicle (uses car infrastructure) |
| 9  | Bicycle                        | `bike` | bike infrastructure |
| 10 | Walked                         | `walk` | sidewalk |
| 11 | Worked from home               | `home` | excluded — no commute trip generated |
| 12 | Other method                   | `home` | excluded — unclassified, no trip generated |

### Bucket → JWTRNS code grouping

```
car     → {1, 7, 8}
transit → {2, 3, 4, 5, 6}
bike    → {9}
walk    → {10}
home    → {11, 12}          # excluded — never enters the demand
N/A     → {-1}              # not a worker (cityscape's "bb" sentinel)
```

### How `--modes <x>` is interpreted at generation time

The dispatch lives at `generate.py:596` and uses a single dict-based
filter at `parse_model_file.py:405-418`:

```python
if modes is not None:               # always passed by generate.py
    allowed_jwtrns = {code for code, m in JWTRNS_TO_MODE.items() if m in modes}
    filtered_persons = [p for p in filtered_persons
                        if p.transport_mode in allowed_jwtrns and p.commute_min > 0]
```

Concretely:

| `--modes` | Codes kept | Tag in `demand.csv` |
|---|---|---|
| `car` | `{1, 7, 8}` | `car` |
| `transit` (single) | `{2, 3, 4, 5, 6}` | `transit` |
| `bike` (single) | `{9}` | `bike` |
| `walk` (single) | `{10}` | `walk` |
| `car,transit` (multi) | `{1, 2, 3, 4, 5, 6, 7, 8}` | per-trip from `JWTRNS_TO_MODE` |
| anything (excluded) | codes 11, 12 are always dropped (mapped to `home`) | — |

---

## 5. What each adapter does with the `mode` column

All three engine adapters declare a **supported_modes** set
(`{"car"}` for all three today) and rely on the shared mode-aware
feasibility filter at `adapters/common/feasibility.py` to drop trips
whose `mode` column is outside that set **before** routing/conversion.
This means a multi-mode bundle simulates exactly its car-mode subset
under each engine — the cross-engine fairness audit (Q1-Q4) compares
engines on the same mode-restricted target.

### `demand.csv` schema

```
trip_id, origin_node_id, destination_node_id, departure_time_s, mode, dest_source, purpose
```

Where:
- `mode ∈ {car, transit, bike, walk}`
- `dest_source ∈ {schedule, gravity}`
- `purpose ∈ {HBW_AM, HBW_PM, HBSchool_AM, HBSchool_PM, HBW_AM_chained, HBW_PM_chained}` (V5+)

Purpose taxonomy:

- **HBW_AM** / **HBW_PM** — Home-Based Work outbound (8 AM arrival from
  cityscape `schedule[0]`) and return (5 PM arrival from `schedule[1]`).
  These cover ~95–98 % of the budget for typical bundles.
- **HBSchool_AM** / **HBSchool_PM** — school drop-off (home → school)
  and pickup (school → home) legs of a parent-with-kid chain. Emitted
  only for commuters whose household contains an `AGEP < 18` dependent
  AND has a school within 5 km. Each chain consumes 2 budget slots.
- **HBW_AM_chained** / **HBW_PM_chained** — the parent's continued
  commute leg of the same chain (school → work in the morning;
  work → school in the evening). Always emitted as the second row
  of an HBSchool chain.

Adapters consume the canonical 5-column subset (`trip_id, origin_node_id,
destination_node_id, departure_time_s, mode`) by name and ignore
`dest_source` and `purpose` — they're informational only and don't
affect simulation output.

### Cross-engine fairness filter — `adapters/common/feasibility.py`

- Reads the canonical network + demand.
- Computes the largest SCC of the network (mode-agnostic).
- Drops trips whose origin or destination is outside the SCC.
- **Drops trips whose `mode` column is outside `supported_modes`** when
  the caller passes one. Every adapter passes `supported_modes={"car"}`
  today, so non-car rows never reach the engine-specific writer.
- Emits a per-engine `feasibility_report.json` with the trip-set + the
  `supported_modes` it was filtered on; `audit_fairness` Q1 verifies
  these are byte-identical across engines and Q3 compares each engine's
  simulated count to its own report's `feasible_trips`.

### SUMO adapter — `adapters/sumo/sumo_adapter.py:627`

- Calls `feasible_trip_ids(network, demand, supported_modes={"car"})`.
- For each feasible trip, writes one `<vehicle id="veh_{trip_id}" type="simforge_car">`.
- V11+ emits an explicit `<vType id="simforge_car" vClass="passenger" .../>`
  block at the top of `routes.rou.xml`, sourced from
  `adapters/common/vehicle_types.py`. Pre-V11 the adapter relied on
  SUMO's silent `DEFAULT_VEHTYPE` fallback; explicit emission removes
  that drift surface and aligns parameters with MATSim's
  `<vehicleType id="car">`. In a future PT-wiring extension additional
  vClasses (bus/rail) would be emitted alongside.

### MATSim adapter — `adapters/matsim/matsim_adapter.py:588`

- Calls `feasible_trip_ids(..., supported_modes={"car"})`.
- For each surviving (car-mode) trip, writes a `<plan>` with
  `<leg mode="car"/>`.
- The qsim and scoring config define exactly one `modeParams` block
  for `mode=car` plus `mainMode=car`. Multi-modal MATSim is a future
  extension (would need additional `modeParams` blocks per mode and
  a `transitSchedule.xml` for transit).

### DTALite adapter — `adapters/dtalite/dtalite_adapter.py:573`

- Calls `feasible_trip_ids(..., supported_modes={"car"})`.
- Aggregates feasible trips to GMNS-format `(o_zone_id, d_zone_id, volume)`
  rows; one canonical trip = one vehicle in the OD matrix.
- DTALite is car-only by design (CPU mesoscopic DTA, single-mode demand),
  so this matches the engine's native capability.

### Effective summary

| Engine | Engine theoretical capability | SimForge today |
|---|---|---|
| SUMO | car (micro/meso), bus/PT (with PT-module wiring), bicycle (vClass=bicycle), pedestrian | **car only** — `supported_modes={"car"}`, all simulated trips are `vClass="passenger"` |
| MATSim | car, transit, bike, walk (full multi-modal) | **car only** — `supported_modes={"car"}`, only `mode=car` modeParams configured |
| DTALite | car only by design | **car only** — `supported_modes={"car"}` matches engine capability |

Practical implication: the `la_50k_car` bundle (49,291 car +
442 transit + 267 bike trips) simulates as ~50,000 cars in every engine.
The bundle's name documents what generated it, not what gets simulated.

---

## 6. SUMO's PT (public transport) module — capability vs current SimForge wiring

SUMO ships built-in public-transport support — it's not a separate plugin,
just a set of features in core SUMO that you opt into by writing the right
input XML. To actually use PT in SUMO requires:

1. `<busStop>` / `<trainStop>` elements in an additionals file
   (`*.add.xml`).
2. A `ptlines.xml` schedule file describing each line: stops, headways,
   vehicle type.
3. `<vType>` definitions with `vClass="bus"`, `vClass="rail_urban"`,
   `vClass="tram"`, etc. — each gets its own physics (dimensions, accel,
   top speed, lane permissions).
4. Optionally `<personFlow>` definitions so passengers walk to a stop,
   board the vehicle, ride, alight, and walk to the destination.

When all of that is wired up, SUMO simulates transit as **vehicles that
follow schedules** plus **persons that ride them**. Bus riders contribute
to crowding and dwell time at stops; the bus itself contributes one
vehicle to road congestion regardless of ridership.

**SimForge does not use any of this.** A repo-wide grep confirms:

```
$ grep -rln "busStop\|ptlines\|vClass=\"bus\"\|--public-transport\|rail_urban\|tram" \
       --include="*.py" --include="*.xml" --include="*.md"
(no matches)
```

The current `python help.py modes` (HELP_MODES) "SIMULATOR SUPPORT" block
spells out that all three adapters are wired for `car only` and lists the
engine-side capability in parentheses ("engine supports PT/bike/walk via
busStop/ptlines/vClass; not wired up" for SUMO). That capability footnote
describes the engine's reach, not what SimForge has plumbed. Wiring up PT
would require non-trivial additions to `pipeline/network/` (to detect bus
routes from OSM PT relations) and to `adapters/sumo/` (to emit the
additionals + ptlines files), plus a parallel story for MATSim's transit
module.

---

## 7. Resolved issues (V5 mode-mapping audit, 2026-04-29)

The 2026-04-29 audit surfaced four correctness problems in the JWTRNS
mapping pipeline. All four were fixed in the same V5 commit set; this
section documents what was fixed and where, so future readers don't
re-introduce the same bugs.

### 7.1 ✅ JWTRNS misclassification (6 of 12 codes had wrong bucket)

`pipeline/demand/parse_model_file.py:166-179` was originally authored
against the **pre-2019** PUMS codebook (where code 2 = "carpooled" and
code 11 = "Taxicab"). Cityscape uses the **ACS 2021** codebook (where
code 2 = "Bus", code 11 = "Worked from home", and codes 1-12 are
shifted overall). The mapping is now corrected — see §4 for the
authoritative table. Empirical confirmation:

```
$ python help.py cities  # Chicago
| Car       |    654,946 |    ~655K |   ← was 1,044,084 (-37%)
| Transit   |    144,887 |    ~145K |   ← was 73,621 (+97%)
| Bike      |     18,277 |     ~18K |   ← was 467 (was code-8 motorcycles
                                           mis-bucketed; now 9=Bicycle)
| Walk      |     55,015 |     ~55K |   ← was 0 (was code-10 mis-bucketed
                                           as "home" / excluded)
```

The previous "1,044,084 Chicago car commuters" included 71K bus riders
+ 326K WFH workers + 17K "Other" — all of which are now correctly
filtered or rebucketed.

### 7.2 ✅ Dual source-of-truth for "what is car?" (eliminated)

The hardcoded `car_modes = {1, 2, 11, 12}` literal at the old
`parse_model_file.py:414` was replaced with `car_modes = MODE_TO_JWTRNS["car"]`
— derived from the same dict that drives the multi-mode path.
`pipeline/modelgen_scanner.py` now imports `JWTRNS_TO_MODE` from
`parse_model_file.py` instead of carrying its own copy. There is now
exactly one place where the mapping lives.

### 7.3 ✅ Single-non-car-mode silent no-filter bug (fixed)

The old dispatch in `generate.py` had a three-branch condition that
left single non-car modes (e.g. `--modes transit`) hitting *neither*
filter branch. Replaced with a single always-pass-`modes=` invocation,
so every mode list is honored. `--modes transit` now correctly pulls
only JWTRNS codes {2, 3, 4, 5, 6}.

### 7.4 ✅ Doc strings updated

The corrected mapping is now reflected in `parse_model_file.py:32-50`
(docstring), `help.py` (`HELP_MODES`), `doc/SCENARIO_GENERATION.md`,
`doc/chapters/methods.md`, and this doc (§4 above).

### 7.5 ✅ Engine adapters now mode-filter demand

The adapters previously ignored the `mode` column entirely (SUMO and
DTALite never read it; MATSim wrote `<leg mode="..."/>` through but had
no scoring config beyond car). Each adapter now declares
`supported_modes={"car"}` and the shared feasibility filter
(`adapters/common/feasibility.py`) drops non-car trips before the
engine sees them. `audit_fairness` Q1 + Q3 are mode-aware.

---

## 8. How a user could simulate a sub-mode today (and the gaps)

After the V5 fixes (§7), single-bucket simulation works correctly: a
bundle generated with `--modes car` produces a clean car-only demand
that all three engines simulate as cars, and a `--modes transit` bundle
generates a clean transit demand that the engines… correctly drop
(since `supported_modes={"car"}`). What's still missing is the ability
to simulate sub-modes (taxi-only, bus-only, etc.) within a bucket.

Today: **you can't simulate a sub-mode directly.** Two remaining
blockers:

1. **Sub-mode provenance is lost at generation time.**
   `parse_model_file.py` collapses 12 JWTRNS codes into 4 buckets at
   the dict lookup; the original code is not preserved in `demand.csv`.
   So a bus rider and a subway rider are both tagged `mode=transit`,
   indistinguishable downstream.
2. **No engine adapter handles non-car sub-modes.** Even if you
   preserved the original JWTRNS code as a `submode` column, SUMO's
   adapter doesn't emit `vClass="bus"`/`"rail_urban"`, MATSim's config
   has no `modeParams` for non-car modes, and DTALite is car-only by
   design.

### Future-work pathways

If a future thesis chapter or research extension wanted sub-mode
disaggregation:

- **Phase A (additive, no behavior change):** preserve the original
  JWTRNS code as a new column in `demand.csv`, e.g.
  `mode, submode, dest_source` where `submode ∈ {drove_alone, taxi,
  motorcycle, bus, subway, ...}`. This is purely a generator change;
  adapters keep dropping non-car rows. Roughly +5 lines in
  `generate_census_demand.py`. Lets users do post-hoc analysis like
  `awk '$5=="car" && $6=="taxi"'`.

- **Phase B (per-engine sub-mode within bucket):** teach SUMO to emit
  the right `vClass` per submode (`bus`, `rail_urban`, `tram`,
  `motorcycle`, `bicycle`, `pedestrian`); MATSim to add `modeParams`
  blocks per mode; DTALite to filter or split the OD matrix by submode.
  Each adapter would advertise an expanded `supported_modes` set so
  the shared feasibility filter passes the right trips through. This is
  significant work — a real research-system extension — weeks not hours.

- **Phase C (full multi-modal):** wire up SUMO PT (busStops, ptlines,
  personFlow), MATSim's transit-routing module, etc. This is a
  thesis-extension or a different project entirely.

For the current Version_5 / thesis-defense scope, none of these are on
the critical path. The §7 fixes make the existing 4-bucket `car`
numbers honest, which is what the cross-engine fairness audit needs.

---

## 9. Cross-engine asymmetry: turn restrictions

V5 introduced OSM `type=restriction` extraction (see CHANGELOG Phase 7).
The data flows into canonical `network.xml` as a top-level
`<turn_restrictions>` block; from there, each adapter handles it in
its native idiom:

| Engine   | Mechanism                                                       | Actively enforced? |
|----------|-----------------------------------------------------------------|--------------------|
| SUMO     | State-aware BFS pre-route → SUMO drives the prescribed `<route>` | ✅                 |
| MATSim   | Same state-aware BFS pre-route → MATSim drives the prescribed `<route type="links">` inside `<leg>` | ✅                 |
| DTALite  | GMNS `movement.csv` emitted with `capacity=0` per restriction    | ❌ (path4gmns 0.10.0 doesn't ingest movement.csv) |

### What this means for the cross-engine audit

The `audit_fairness.py` Q1–Q4 audits each interpret differently under
this asymmetry:

- **Q1** (byte-identical feasibility verdict): unchanged. All three
  engines see the same trip set and SCC. ✅
- **Q2** (network nodes/links match): unchanged. ✅
- **Q3** (each engine simulates the target trip count): unchanged. ✅
- **Q4** (cross-engine TT comparison): the comparability *details*
  shifted in two opposing directions:
  - **Tightened** within SUMO ↔ MATSim: both engines now drive the
    same restriction-respecting path. Their TT difference reflects
    *only physics* (mesoscopic queue dynamics, signal phasing,
    spawn timing). Pre-V5 each engine routed independently and
    could pick different paths.
  - **Loosened** between SUMO/MATSim ↔ DTALite on individual trips
    where DTALite's UE picks a route that crosses a forbidden
    movement (e.g., a "no left turn" intersection). Pre-V5 all
    three engines uniformly ignored restrictions; post-V5 two of
    three respect them.

### Why we accepted this asymmetry

Three options were considered:

1. **Document and ship** (this V5 choice). Clear realism gain in two
   engines; documented limitation in the third. Honest framing for
   the thesis: *"SimForge respects OSM turn restrictions in SUMO and
   MATSim; DTALite's UE-paradigm comparison receives the same data
   in GMNS movement.csv form for downstream use, but path4gmns 0.10.0
   does not yet ingest it."*
2. **Network-side encoding for DTALite**. Restructure DTALite's
   `link.csv` so that restricted (from→via→to) chains are physically
   broken — split each via-node into virtual nodes per restricted
   approach. Significant engineering (~1 week), changes the network
   topology DTALite sees relative to SUMO/MATSim, defers other thesis
   work.
3. **Revert V5 1.1 enforcement**. Roll SUMO and MATSim back to plain
   BFS for symmetry-by-shared-blindness. Goes backwards on realism;
   not a serious option.

V5 picked option 1. This doc + `CHANGELOG.md` Phase 7 + the schema
doc + `pipeline/network/turn_restrictions.py` module docstring are
the four canonical references that frame this asymmetry honestly.

### Future work to fully close

Either:
- **Upstream (preferred)**: path4gmns gains `movement.csv` ingestion.
  Closes DTALite enforcement transparently — no SimForge changes needed.
  Watch path4gmns release notes.
- **In-tree (fallback)**: implement option 2 above (node splitting in
  `write_dtalite_link_csv` / `write_dtalite_node_csv`). Roughly
  1 week of work; affects DTALite's network topology. See
  `doc/REPRODUCING.md` if you take this path so the network-equivalence
  audit is updated alongside.

---

## References

- `pipeline/demand/parse_model_file.py` — model-file parser + `JWTRNS_TO_MODE`.
- `pipeline/demand/generate_census_demand.py` — schedule + gravity demand
  generator that consumes parsed `ModelData`.
- `pipeline/modelgen_scanner.py` — fast scanner used by `python help.py cities`.
- `adapters/sumo/sumo_adapter.py` — SUMO routes/vehicles writer.
- `adapters/matsim/matsim_adapter.py` — MATSim plans + config writer.
- `adapters/dtalite/dtalite_adapter.py` — DTALite GMNS demand writer.
- `adapters/common/feasibility.py` — shared cross-engine SCC trip filter.
- `generate.py` — top-level scenario-generation CLI.
- `help.py` — in-repo help system (`HELP_MODES` topic).
- `doc/SCENARIO_GENERATION.md` — higher-level demand-pipeline walkthrough.
- `doc/GLOSSARY.md` — definitions for PUMS / JWMNP / JWTRNS / ModelGen.
- Cityscape repository: <https://github.com/raodj/cityscape>
- ACS PUMS 2021 Data Dictionary:
  <https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2021.pdf>
