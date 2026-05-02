# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

Commit hashes refer to the `Version_2` branch.

## [Unreleased] — Version_5

### Phase 12.1: MATSim route-text format fix (2026-05-02) — CRITICAL

**Symptom.** Every MATSim run completed in normal wall time and reported
`status="success"`, but `output_trips.csv.gz` had ZERO trip rows
(only the header line). MATSim's `logfileWarningsErrors.log` was full of:

```
WARN DefaultTurnAcceptanceLogic:58 Cannot move vehicle person_t82 from link l1502 to link l28738
```

— one warning per agent. Mean travel time computed by `parse_matsim_output`
was 0 (chicago_1k_car) or `~26 s` from a handful of teleport-fallback
trips (nyc_10k_car). The R-score across 5 reps trivially evaluated to
1.0000 because the stddev of zero (or near-zero) trip counts is zero;
this read in analyze_benchmark as "perfect determinism" but was actually
"perfect breakage". Phase 11.6's `engine_wall_s` numbers for MATSim were
*real* JVM time but reflected a mobsim that immediately gave up.

**Root cause — wrong text content for `<route type="links">`.**
SimForge's `build_matsim_plans_xml` emitted:

```xml
<route type="links" start_link="l28784" end_link="l477">
    l28738 l52123 l28688 ... l29310 l55755
</route>
```

— treating the text content as the *interior* of the route (i.e.
excluding `start_link` and `end_link`). MATSim 15 / population_v6
expects the **FULL** link sequence in the text content, with
`start_link` as the first token and `end_link` as the last:

```xml
<route type="links" start_link="l29641" end_link="l29299" ...>
    l29641 l29471 l29644 ... l29310 l29299
</route>
```

(Format confirmed against MATSim's own `output_plans.xml.gz` after
running with the BFS-pre-routing disabled — MATSim's router emits
this redundant idiom.) When SimForge omitted `start_link` and
`end_link` from the text, MATSim's mobsim ended up with a route
disjoint from where the agent physically was, and
`DefaultTurnAcceptanceLogic` rejected every transition.

**Fix.** `adapters/matsim/matsim_adapter.py:build_matsim_plans_xml`
now constructs the full link sequence
`[origin_link, *route_link_ids, dest_link]` (de-duped at the joins
in case BFS happens to land on origin_link or dest_link directly)
and writes the entire list as the route text, while *also* setting
`start_link` and `end_link` to match the surrounding activity links.

**Empirical confirmation against chicago_1k_car/matsim/seed_42:**

| Metric | Before | After |
|---|---|---|
| Trips in `output_trips.csv.gz` | 0 | 1000 |
| `Cannot move vehicle` warnings | 1000 | 0 |
| Engine wall | 10.1 s | 11.0 s |
| Mean travel time | n/a (no trips) | 309.6 s |
| P95 travel time | n/a | 582 s |

**Impact on existing thesis data.** Every MATSim cell in every prior
benchmark run is invalid as a travel-time / trip-count source. The
*runtime* numbers (engine wall) are still meaningful (MATSim really did
spend that time in mobsim), but the trip outputs are not — they
represent a mobsim that rejected every move. Re-run any benchmark that
cites MATSim Q3/Q4 / Table 5.2 / Fig 5.3 / Fig 5.7 / Fig 5.8 / Fig 5.9
numbers. SUMO and DTALite cells are unaffected and don't need re-running.

**Tests added (`tests/test_matsim_adapter.py:TestBuildMATSimPlans`):**
- `test_route_text_includes_start_and_end_links` — pins the requirement
  that the `<route>` text first token == `start_link` and last token ==
  `end_link` for every emitted plan.
- `test_route_start_link_matches_start_activity_link` — pins the
  requirement that the route's `start_link` and `end_link` attributes
  match the activity links that surround the leg.

### Phase 12: Parallel-by-scenario sbatch correctness fixes (2026-05-02)

Two latent bugs in `execution/run_benchmark.py` surfaced when the
canonical small-tier sbatch (`cluster/jobs/benchmark_small.sbatch`) was
run on Pitzer with three parallel-by-scenario workers:

**Bug 1 — `--output` CLI override silently clobbered by runspec.**
`BenchmarkHarness.run_benchmark()` unconditionally re-set
`self.output_base = Path(runspec.global_output_dir)` after the constructor
already accepted the CLI value. All three workers ended up with
`output_base = Path("runs/benchmark_small")` regardless of the per-scenario
`--output` they were launched with. Each worker wrote its aggregate JSON
to the same `runs/benchmark_small/benchmark_results_benchmark_small.json`
path → race condition, last writer wins. The Pitzer dry run lost
chicago_1k_car's full result set this way (only nyc_10k_car's data
survived because nyc finished last).

**Fix:** `BenchmarkHarness.__init__` now tracks `_explicit_output` when
a non-None `output_base` is passed, and `run_benchmark()` only falls back
to the runspec's `output_dir` when the CLI didn't override. Per-scenario
workers now write per-scenario JSONs as documented.

```python
# Before (silently broken):
harness = BenchmarkHarness()
harness.output_base = Path(args.output)  # honored by per-cell paths,
                                         # clobbered for JSON write
# After (clean):
harness = BenchmarkHarness(output_base=Path(args.output) if args.output else None)
```

**Bug 2 — per-cell directory missing the `mode` segment.**
The path was `<base>/<scenario>/<engine>/seed_<N>/`. SUMO meso and SUMO
micro for the same seed both wrote to `<scenario>/sumo/seed_42/`, and the
second invocation overwrote the first's `tripinfo.xml`,
`feasibility_report.json`, and SUMO config files. The aggregate JSON
recorded both cells' metrics correctly (it's built in-memory before any
overwrite hits disk), but the on-disk artefacts that
`audit_fairness` Q1/Q2/Q3 walk to verify the trip set + SCC + per-engine
trip counts were destroyed for the first-written mode.

**Fix:** per-cell path now includes `mode` —
`<base>/<scenario>/<engine>/<mode>/seed_<N>/`. Both meso and micro
artefacts coexist on disk under their respective subdirs.

**Cascade — `evaluation/audit_fairness.py` layout detector extended.**
`_find_cell_dir()` and `_discover_scenarios()` now recognise the new
mode-segmented Phase-12+ layouts as preferred matches, with the
pre-Phase-12 mode-less layouts kept as fallbacks for back-compat
against older run dirs. New `_discover_modes()` helper enumerates which
modes have on-disk cells per scenario, so the orchestrator audits both
meso and micro independently when both exist (instead of silently picking
whichever the layout walker found first). The `audit_scenario()` signature
gained an optional `mode="meso"` parameter; callers without an explicit
mode default to meso.

**Migration note for old run dirs:**
- Pre-Phase-12 results (no `<mode>/` segment in the path) are still
  audit-able — `_find_cell_dir`'s back-compat fallbacks handle them.
- The on-disk artefacts in those old dirs are whatever was written
  *last* (sumo micro overwrites sumo meso). The aggregate JSON is the
  authoritative source for per-cell metrics; the per-cell artefacts are
  for trip-id intersection and feasibility-report verification only.
- Re-running affected benchmarks under Phase 12+ gives clean coverage.

**Bug 3 — `prepare_<engine>_inputs` repeated per cell instead of cached.**
The dominant cost of `prepare_sumo_inputs` / `prepare_matsim_inputs` /
`prepare_dtalite_inputs` on big networks is per-trip BFS routing on the
canonical node graph. Those routes are deterministic given (scenario,
engine) — they never depend on seed, mode, or rep number. The harness
was nevertheless recomputing them from scratch for every cell. On
la_50k_car (50,000 trips × 159K-node network) BFS routing takes ~10 h
**per cell**; the canonical small-tier matrix has 15 la cells, so the
total cost was ~150 h before any engine even started running. Job
walltime budgets had no chance.

**Fix:** new `BenchmarkHarness._ensure_prepared_cache()` runs the
prepare step once per `(scenario_id, engine)` into
`<output_base>/.cache/<scenario_id>/<engine>/`, then
`_mirror_cache_to_run_dir()` populates each cell's `run_dir` by
hardlinking from the cache (falling back to `shutil.copy2` on
`OSError`, e.g. cross-filesystem). The hardlinks keep total disk use
~the same as a single prepped dir regardless of repeat count.

**Cache invalidation by bundle hash.** The `.prepared` sentinel now
stores `sha256(scenario_path/manifest.xml)`. On every cache hit the
harness compares the stored hash against the bundle's current
manifest hash; mismatch triggers `shutil.rmtree(cache_dir)` and a
fresh prepare. So if you regenerate `scenarios/<scenario>/` (e.g.
bump trip count or change radius) and reuse the same `--output`,
the next benchmark invocation automatically detects the change and
re-prepares — no manual `rm -rf .cache/` required. Synthetic /
partial bundles without `manifest.xml` get an empty hash and the
cache remains non-invalidating (best-effort behavior).

For MATSim the cell's seed is written into `config.xml`'s
`global.randomSeed` param; that one file is broken out of the hardlink
chain and re-rendered per cell with the cell's actual seed. SUMO and
DTALite consume seed only at run time (`--seed` flag and settings.yml
RNG respectively), so the cache fully covers them.

Cost collapse on la_50k_car: 150 h → ~10 h (one cold prepare + 14
millisecond-class mirrors). Even chicago_1k_car sees a ~3× speed-up
on a 5-rep matrix because the per-trip BFS overhead, while small in
absolute terms, was being repeated 5 times.

**`evaluation/audit_fairness.py` cache exclusion.**
`_discover_scenarios()` now skips dotted directory names (`.cache/`
in particular). Without this guard, the BFS-prep cache directory
would be walked as if it were a scenario.

**Tests added (`tests/test_run_benchmark.py:TestPreparedCache`):**
- `test_warm_cache_skips_prepare` — pin the sentinel-driven no-op path.
- `test_cold_cache_calls_prepare_and_marks_sentinel` — pin the cold-prep
  path + sentinel write (now containing the bundle's manifest SHA).
- `test_cache_invalidates_when_bundle_changes` — pin the auto-invalidation:
  rewrite the bundle's manifest, observe that a subsequent
  `_ensure_prepared_cache` triggers a fresh prep (called twice across
  two invocations) and the sentinel reflects the new hash.
- `test_warm_hit_when_bundle_unchanged` — pin that repeated calls with
  the SAME manifest content stay as a single cold prep.
- `test_mirror_hardlinks_cache_to_run_dir` — pin the inode-equality
  invariant that proves files are hardlinked, plus verify the
  `.prepared` sentinel doesn't propagate to per-cell dirs.
- `test_mirror_falls_back_to_copy_on_oserror` — pin the cross-filesystem
  fallback path.

Empirical confirmation against a real chicago_1k_car bundle:
- Cold prep: 26 s (BFS routing for 1K trips)
- Warm cache hit: 0.02 ms (sentinel `is_file()` check)
- Mirror to a cell dir: 1.3 ms (4 hardlinks + 1 config rewrite)
- MATSim per-cell `config.xml` correctly carries the cell's seed (seed=42
  vs seed=43 verified to differ).

**Tests added (`tests/test_run_benchmark.py` + `tests/test_audit_fairness.py`):**
- `TestExplicitOutputBase` — pins the `_explicit_output` flag and the
  default-vs-override behaviour of the harness constructor.
- `TestFindCellDir.test_layout_b_phase12_*` — pin the new mode-segmented
  layouts as preferred matches over the legacy mode-less ones.
- `TestFindCellDir.test_back_compat_pre_phase12_layout_b` — pre-Phase-12
  dirs still resolve.
- `TestDiscoverModes` — new test class for the modes-per-scenario helper.
- `TestDiscoverScenarios.test_finds_layout_b_phase12_with_mode_segment` +
  `test_finds_layout_a_micro_seed` — discovery handles the new layouts
  and now also catches micro-mode flat dirs.

109 tests pass (29 audit_fairness original + 14 new layout/discover/modes
+ 3 new harness output + 4 new prep-cache) under
`pytest -m "not requires_sumo"`. The 3 SUMO-binary tests skip on macOS
arm64 due to the pre-existing netconvert incompatibility (unrelated to
this phase).

**Bonus — sbatch wrappers now `shopt -s nullglob`.**
`cluster/jobs/benchmark_small.sbatch` and `cluster/jobs/benchmark_large.sbatch`
both used `RESULTS=(<base>/*/<glob>.json)` to gather per-scenario JSONs.
Without `nullglob`, an unmatched glob stays as the literal pattern
string — the array ends up with one element (`"<base>/*/<glob>.json"`)
that bash treats as a real path. The aggregation step then reports
"Found 1 result file" pointing at a path that doesn't exist, and
`analyze_benchmark` errors with `Results file not found: …/*/…`. Both
sbatchs now `shopt -s nullglob` at the top, and the aggregation block
checks `${#RESULTS[@]} -eq 0` and exits 0 with a helpful pointer to the
per-scenario logs instead of failing opaquely. Both sbatchs also gained
an inline `audit_fairness` invocation so the `audit_fairness.txt`
artefact lands alongside the `summary.md` and `plots/` automatically
(was previously a manual post-step).

**`benchmark_small.sbatch` walltime bumped 24h → 36h.** With the
BFS-prep cache, la_50k_car (the long-pole worker) now needs ~21–23 h
of wall (10–11 h SUMO BFS prep + 10–11 h MATSim BFS prep, then 5
cheap engine reps each + DTALite). 24h was tight; 36h leaves
headroom for slow Pitzer I/O, JVM startup variance, and node-share
slowdowns.

### Phase 11.8: Drop redundant Fig 5.4 (Engine summary panel) + renumber (2026-05-01)

The 3-panel "Engine summary" figure (per-mode runtime + R-score + throughput
side-by-side) was redundant with Fig 5.1 (runtime) and Fig 5.2 (R-score) —
two of its three panels duplicated information the reader had just seen.
Only the throughput panel was unique, and it was a derivative quantity
(`trip_count / runtime`) easily computed from the existing runtime tables.

Removed:

- `plot_engine_summary()` and its driver entry in `evaluation/generate_plots.py`.
- Fig 5.4 section in `doc/chapters/results.md` §5.5 — the section now opens
  directly with the throughput table (the data the section actually needed)
  and references Table 5.1 / Fig 5.1 for the underlying runtime numbers.

Renumbered 5.5 → 5.4, 5.6 → 5.5, … , 5.11 → 5.10 throughout. Total figures:
**11 → 10**. Affected files:

- `evaluation/generate_plots.py` (driver list, suptitles, save names, docstring)
- `help.py` (HELP_EVALUATION figure list)
- `doc/RESULTS_GUIDE.md` (§4.2 figure table, §6 interpretation guide, key claims)
- `doc/REPRODUCING.md` (figure summary table)
- `doc/GLOSSARY.md` (P95 + Throughput entry cross-refs)
- `doc/chapters/results.md` (figure section headers, image paths, body refs)

Verified: `python -m evaluation.generate_plots <results.json>` renders the
10 figures cleanly with the new numbering. Existing audit / analyze tests
still pass — no result-JSON shape change.

### Phase 11.7: Two new thesis figures (Fig 5.10, Fig 5.11) (2026-05-01)

`evaluation/generate_plots.py` now produces 11 figures instead of 9:

- **Fig 5.10 — Demand composition.** Per-scenario stacked bar of the
  V5+ trip-purpose taxonomy (HBW_AM/PM, HBSchool_AM/PM, HBW_*_chained).
  Reads each bundle's canonical `demand.csv` `purpose` column via
  `evaluation/demand_composition.py`. Pre-V5 bundles without that
  column are silently skipped; if no scenario has V5+ data the whole
  figure is omitted.
- **Fig 5.11 — Wall vs engine breakdown.** Per-cell stacked bar:
  engine subprocess at the bottom, adapter prep + output parsing
  (`cell_wall_s − engine_wall_s`) on top, hatched. Documents where
  per-cell wall time actually goes after the Phase 11.6 timing split.
  Skipped when result files don't carry the new fields (pre-Phase
  11.6 results).

Existing runtime figures got minor relabels for honesty: "Runtime"
→ "Engine runtime" in Fig 5.1, 5.6, 5.7 titles + the y-axis labels,
since after the Phase 11.6 split the CLI exposes both wall and engine
numbers and a thesis reader could legitimately ask which one a runtime
figure shows. The values themselves didn't change — every figure has
always been engine subprocess only — only the labels are now explicit.

### Phase 11.6: Wall-vs-engine timing split + cleaner failure display (2026-05-01)

Per-cell timing in `run.py` and `execution/run_benchmark.py` now reports
two numbers, since the previous single number conflated two different
costs:

- **`engine_wall_s`** — engine subprocess only (mobsim / DTA iterations
  / queue net). What Chapter 5 runtime tables cite, since the thesis is
  benchmarking the engine paradigm, not the Python adapter.
- **`cell_wall_s`** — full per-cell wall: adapter prep (canonical →
  engine format, **including the per-trip BFS pre-routing the
  SUMO/MATSim adapters do**) + engine subprocess + output parsing.
  Per-cell `cell_wall_s` values now sum to the harness "Wall time"
  total — the previous single number didn't, which was confusing for
  large scenarios (nyc_10k_car MATSim: ~9.5 min per-cell wall vs the
  ~15 s the cell row used to display).

Per-cell row format (both runners):

```
[1/3]  matsim   meso  seed=42  ✓   25.3s wall  (10.6s engine)
```

Failed cells listed first in the summary block, then per-cell wall +
engine 95 % CIs:

```
✗ Failed cells (full error in benchmark_results.json `error` field):
  chicago_1k_car  sumo  meso   seed=42  Ambiguity in turnarounds at junction 'n10033'. (+4 more)

Per-cell wall time (full prep + engine + parse, mean ± 95 % CI across reps;
engine-only mean in parens — that's the number Chapter 5 tables cite):
  chicago_1k_car  matsim   meso     25.3s ±   0.8s wall  (engine  10.6s)  (3 runs)
```

Failure-line cleanup (`execution/cli_format.py:format_error_oneline`):
strips noise prefixes ("Conversion failed: ", "netconvert failed: ",
"Warning: "), collapses repeated warning lines into "(+N more)", and
truncates at a word boundary with "…" instead of mid-character. Used by
both runners so the display stays consistent.

**Back-compat preserved**: `runtime_s` and `wall_time_s` still mean
engine-subprocess time on success, so `analyze_benchmark`,
`generate_plots`, and the `audit_fairness` Q4 travel-time spread keep
reading the same field they always did. New fields (`cell_wall_s`,
`engine_wall_s`) are additive. Verified: `tests/test_audit_fairness.py`
+ `tests/test_analyze_benchmark.py` (53 tests) all green after the
change.

JSON shape additions per `results[]` entry:

| Field           | Meaning                                                |
|-----------------|--------------------------------------------------------|
| `runtime_s`     | Back-compat alias for `engine_wall_s` on success.      |
| `wall_time_s`   | Same as `runtime_s`. Kept verbatim from prior version. |
| `engine_wall_s` | NEW. Engine subprocess only.                           |
| `cell_wall_s`   | NEW. Full prep + engine + parse per cell.              |

### Phase 11.5: Interactive help TUI (2026-04-30)

`python help.py` (no args, TTY) now opens a full-screen curses TUI
instead of dumping the overview text. Topics are grouped under five
headings — Getting Started, Core Workflows, Reference, Analysis &
Tools, Troubleshooting — and the user navigates with arrow keys.

Key bindings:

| Key             | Effect                                    |
|-----------------|-------------------------------------------|
| ↑ / ↓           | Move selection (or scroll inside a topic) |
| Enter           | Open the highlighted topic                |
| Esc             | Return from a topic to the menu           |
| PgUp / PgDn     | Page through long topics                  |
| Home / End      | Jump to top / bottom of a topic           |
| q  (or Esc)     | Quit (from the menu)                      |

Returning from a topic via Esc redraws the menu cleanly — no leftover
content from the topic appears on screen, because curses owns the
whole viewport and `stdscr.erase()` runs on every redraw.

**Topic view polish**:
- 2-column left margin so content isn't flush against the screen edge
- Leading/trailing blank lines stripped before display (tighter top gap)
- Best-effort syntax highlighting for the patterns SimForge help text
  already uses:
    - `===` / `---` rules     → dim cyan
    - `UPPERCASE TITLE` lines → bold cyan
    - `SECTION HEADER:` lines → bold yellow
    - `python ...` / `$ ...` etc. command examples → green
    - everything else         → default text
- Visual gap between menu category groups so the 5 sections don't
  blur together
- Footer keys with `:` separators and ASCII-friendly arrow glyphs
  (`↑/↓: navigate    Enter: open topic    Esc / q: quit`)
- PgUp/PgDn / Home/End still work inside topics for power users
  (Mac compact keyboards: Fn + ↑/↓ / Fn + ←/→) but kept off the
  footer to reduce visual clutter

Auto-fallback: when `import curses` fails or the terminal can't host
a curses session (rare — dumb terminals, restricted CI), the help
system silently falls back to the numbered-input menu (with `/<word>`
search) introduced in V11.5's first iteration. So Windows shells
without `windows-curses` installed still work.

Other paths preserved:

- `python help.py <topic>` still prints the topic to stdout as before
  (paste-safe; matches all prior SimForge releases).
- `python help.py` with non-TTY stdout still prints the overview text
  (CI logs, file pipes).
- `python help.py --interactive` forces the TUI even in non-TTY
  contexts (mainly for testing).
- `python help.py --no-interactive` forces the overview-text path.

New help topic: `python help.py analyzer` covers the V11.4
`tools/analyze_scenarios.py` bundle analyzer in detail.

The help system continues to use only the standard library
(`curses` ships with CPython on Unix; the legacy fallback covers
Windows without `windows-curses`). No new dependencies introduced.

### Phase 11.4: Scenario analyzer tool (2026-04-30)

New `tools/analyze_scenarios.py` — comprehensive tabular analysis of
canonical scenario bundles. Each section is one side-by-side table
with metrics as rows and scenarios as columns. Auto-paginates per
section when the terminal isn't wide enough (each section splits
based on its own column widths).

Sections (selectable via `--section`):

- `configuration`  — city, trips, time window, radius, seed, strategy,
  generation time, OSM source
- `network`        — nodes, links, has_signal nodes (% of nodes), turn
  restrictions, speed/lane range + means
- `road_classes`   — per-OSM-highway-type link counts, sorted by total
- `signals`        — junction count, cycle, phase pattern, density
- `demand`         — totals + trip-purpose breakdown subsection +
  peak split & chain summary subsection
- `artefacts`      — per-file sizes + total
- `toolchain`      — env recorded at generation time (Python, osmnx,
  numpy, networkx, lxml, etc.)

Default: every complete bundle in `scenarios/`. Pass scenario names
or full paths to subset. `--no-color` disables ANSI for piping.
Pagination is automatic via `shutil.get_terminal_size()` — sections
split into pages of N scenarios when the terminal isn't wide enough,
each page suffixed `(scenarios X–Y of N)`.

Pre-V5 bundles missing the `purpose` column gracefully render only
the totals subsection of DEMAND. Reuses
`evaluation.demand_composition.read_demand_composition` for purpose
tallying so the analyzer's numbers match what
`audit_fairness` Q5 and `analyze_benchmark`'s composition table
report — single source of truth across all three tools.

Standard library only — no new dependencies.

### Phase 11.3: Test-suite session-scoped fixture optimisation (2026-04-30)

`tests/test_matsim_adapter.py` previously ran in ~12 min because every
test that consumed the `bundled_scenario` fixture re-ran the full
prepare/build pipeline (function-scoped pytest default). With V5 Phase
7 state-aware BFS pre-routing landing in `build_matsim_plans_xml`, the
redundancy got more expensive: every pure structural assertion was
implicitly running BFS on every trip in the bundle.

Refactored to share the heavy lifts across tests via session-scoped
fixtures. The new fixtures live at the top of the file:

- `canonical_network_data` — `(nodes, links)` from chicago_1k_car
  (consumes `bundled_scenario`, calls `load_canonical_network` once)
- `built_network_xml` — MATSim network XML string built once
- `built_plans_xml` — MATSim plans XML string built once (the
  expensive BFS pre-routing call)
- `prepared_chicago` — full `prepare_matsim_inputs(chicago_1k_car)`
  output dir + config path, prepared once per session
- `prepared_sweep` — `{scenario_path: (out_dir, config_path)}` map
  for every small bundled scenario, prepared once per session

`TestLoadCanonicalNetwork`, `TestBuildMATSimNetwork`,
`TestBuildMATSimPlans`, `TestPrepareMATSimInputs` updated to consume
these fixtures instead of re-running the work. All 24 tests still
pass; assertions unchanged.

**Measured impact**: 12m 17s → 10m 42s wall time on M-series Mac
(~75 s of cross-test redundancy eliminated). Less than initially
projected because the test_all_scenarios sweep was already only
calling `prepare_matsim_inputs(nyc_10k_car)` once — that single 5-7
min BFS pass is V5 Phase 7's intentional pre-routing cost on 10K
trips × 379 turn restrictions, not redundancy.

**Coverage delta: zero.** Every assertion runs against a real
prepared/built artefact. Determinism of the underlying code paths is
covered by `tests/test_adapter_determinism.py` (which explicitly
runs prepare twice and hash-compares — that pattern is unchanged
and is the proper place for "runs N times consistently" guarantees).

To skip the slow sweep during routine dev:

```bash
python -m pytest tests/test_matsim_adapter.py -k "not test_all_scenarios"
# ~3-4 min wall time; keeps 23 of 24 assertions live
```

### Phase 11.2: Post-V11 correctness pass (2026-04-30)

A round of bugfixes surfaced after re-running the test suite with all
five generated bundles in `scenarios/`:

**HBSchool chain self-trip guard** (`pipeline/demand/generate_census_demand.py`)

The Phase 9b/9c chain emission could produce `origin == destination`
rows when the building-to-network-node snap collapsed home, school, or
work onto the same graph node. Most common in dense urban grids; nyc_500k_car
emitted 1,122 self-trips, la_50k_car 91, chicago_200k_car 170, nyc_10k_car 1.
The bundle validator's `TestDemandIntegrity.test_origin_differs_from_destination`
correctly rejected these, surfacing the bug.

`_maybe_school_chain_for(person, home_node)` is now
`_maybe_school_chain_for(person, home_node, work_node)` and returns
`None` if `school_node ∈ {home_node, work_node}`. The caller falls
back to a bare HBW row, preserving demand realism without breaking
referential integrity. Both AM (Phase 1a) and PM (Phase 1b) call
sites updated.

**MATSim plans format: plans_v4 → population_v6**
(`adapters/matsim/matsim_adapter.py`)

The V5 Phase 7 turn-restriction enforcement code emitted
`<route type="links" start_link="..." end_link="...">` inside
`<plans>` with the plans_v4 DTD. plans_v4 rejects this for two reasons:
(a) its `<route>` ATTLIST only accepts cost-optimisation `type`
values (`dist|trav-time|num-nodes|num-intersects`), and (b) the route
PCDATA content is parsed as a *node* sequence, not links. The
test_engine_smoke `test_matsim_real_jar_produces_output_trips` test
caught the bug the first time it ran with a V5+ bundle (real
MATSim JAR rejected the XML at the SAX layer).

Migrated to `population_v6` DTD (also shipped in MATSim 15 JAR):
- DOCTYPE: `plans_v4.dtd` → `population_v6.dtd`
- Root: `<plans>` → `<population>`
- Activity element: `<act>` → `<activity>`
- `<route>` keeps its V5 idiom — population_v6 explicitly supports
  `type="links" start_link="..." end_link="...">interior</route>`
- `PopulationReaderMatsimV6` honors pre-emitted routes (same
  contract V5 Phase 7 always intended)

**Sticky progress bar — log routing always on**
(`generate.py`, `run.py`, `execution/run_benchmark.py`)

Pre-V11.2 the bar's log-capture handler was gated on `--verbose`,
so default-mode WARNING records (e.g. osmnx's "Dropping degenerate
edge ..." during nyc_500k_car generation) collided with the bar's
no-newline `\r` redraws and produced mangled lines like
`░░░░  ⠦  0%  step 1/4  elapsed 3m 07sWARNING ...`. Capture is now
always installed; the level threshold differs by mode (WARNING+ in
default, INFO+ with `--verbose`).

**ETA removed from progress bars** (`pipeline/progress.py`)

Both `ProgressBar` and `StickyProgress` no longer compute or display
an ETA. SimForge runs are wildly heterogeneous (10ms unit tests next
to 30s SUMO integration tests; 1K-trip bundles next to 500K-trip
ones), so the running-mean ETA swung between unhelpful extremes
(e.g., "5 hours" then "2 hours" within a single suite). Percentage,
counter, and elapsed clock together carry the same information
without misleading the operator.

**Pytest `=== FAILURES ===` traceback block suppressed**
(`tests/_sticky_plugin.py`)

Pytest's default end-of-session output prints the full traceback
for every failed test before the SimForge plugin's unified summary.
The summary already lists each failed nodeid with its first-error
line — the extra traceback was redundant noise. Added
`tr.summary_failures = lambda: None` and `summary_errors = lambda:
None` to the existing monkey-patch block so the failure block is
suppressed alongside warnings/short-test-summary/stats.

**generate.py source-line de-duplication**

The Step 1/4 OSM-network output mentioned the PBF filename twice:
once in the pre-step `source: osm_data/<file>.pbf (...)` line and
once in the post-step `✓ network.xml: ... from <file>.pbf` suffix.
The suffix is dropped for PBF (already announced); kept for the
Overpass fallback path (worth flagging because it diverges from
what the operator expected).

**Test count documented as 477 (3-bundle) / 549 (5-bundle)**

Test-count references in `README.md`, `CONTRIBUTING.md`, `TESTING.md`,
`SETUP.md`, `help.py`, `doc/chapters/methods.md`, and
`doc/chapters/experiments.md` updated. Headline is **~477 tests** —
the count a fresh `git clone && pytest` shows with the 3 tracked
bundles (`chicago_1k_car`, `nyc_10k_car`, `la_50k_car`). Generating
the two larger benchmark tiers (`scripts/04`, `scripts/05`) adds
72 more parametrised integrity tests for a 549-test full local
sweep with proportionally longer wall time (~14 min vs ~3-4 min).

### Phase 11: Cross-engine vehicle-parameter alignment (2026-04-30)

Pre-V11 each adapter declared its own vehicle parameters using engine-
local conventions, with no shared source of truth. SUMO relied on the
implicit ``DEFAULT_VEHTYPE`` (length 5.0 m + minGap 2.5 m); MATSim
hardcoded ``length=7.5`` and ``width=1.0`` inside `matsim_adapter.py`;
DTALite's `[agent_type]` row carried `PCE=1` as a magic number. The
two ostensibly disagreed (5.0 m vs 7.5 m) but were actually equivalent
under different conventions:

- SUMO: ``length`` is the physical body, ``minGap`` is the safety gap
- MATSim: ``length`` is the *effective* spacing (physical + gap)
- DTALite: link capacity expresses the storage equivalent via PCE

V11 publishes a single canonical car description in
``adapters/common/vehicle_types.py`` and lets each adapter translate to
its idiom. The actual *physical* picture is unchanged (still a 5.0 m
sedan with a 2.5 m gap, still PCE 1.0); what changes is that the
parameters now live in one place, the values are explicit in every
output bundle, and the cross-engine equivalence is testable.

**Concrete edits:**

- New ``adapters/common/vehicle_types.py`` with constants
  (``CAR_LENGTH_M=5.0``, ``CAR_MIN_GAP_M=2.5``,
  ``CAR_EFFECTIVE_LENGTH_M=7.5``, ``CAR_WIDTH_M=1.8``,
  ``CAR_MAX_SPEED_MPS=40.0``, ``CAR_PCE=1.0``,
  ``CAR_ACCEL_MPS2=2.6``, ``CAR_DECEL_MPS2=4.5``,
  ``CAR_DRIVER_IMPERFECTION=0.5``) plus two emitters:
  ``sumo_vtype_xml()`` and ``matsim_vehicle_type_xml()``.

- ``adapters/sumo/sumo_adapter.py::build_sumo_routes_xml`` now emits an
  explicit ``<vType id="simforge_car" .../>`` element at the top of
  ``routes.rou.xml`` with all canonical values, and every
  ``<vehicle>`` row carries ``type="simforge_car"``. SUMO no longer
  silently inherits its built-in ``DEFAULT_VEHTYPE``, so any future
  SUMO upgrade that changes the default cannot drift the bundle's
  vehicle physics.

- ``adapters/matsim/matsim_adapter.py::build_matsim_vehicles_xml`` now
  delegates to ``matsim_vehicle_type_xml()``. The MATSim `<width>`
  bug is also fixed: the pre-V11 hardcoded value ``1.0`` (motorcycle
  width) is now ``1.8`` (canonical car width). MATSim's `length`
  stays at ``7.5`` because that's the cross-engine equivalent —
  changing it would *introduce* drift, not remove it.

- ``adapters/dtalite/dtalite_adapter.py`` imports ``CAR_PCE`` and
  uses the constant in its ``[agent_type]`` row instead of a magic
  literal.

**Test coverage:** new ``tests/test_vehicle_types.py`` (19 tests)
pinning the constants, the emitted XML, and the cross-engine
equivalence (``sumo_length + sumo_min_gap == matsim_effective_length``
and ``sumo_max_speed == matsim_max_speed``).

**Cross-engine fairness impact:** Q4 travel-time spread should be
unchanged at the headline (the physical values are identical); the
win is structural — explicit parameters in every bundle, single source
of truth, and a regression-pinning test that catches future drift.
The ``MATSim width 1.0 → 1.8`` change is cosmetic in the queue
mobsim (width isn't used by MATSim's flow model), but visible in
output animations / GIS rendering.

**Known scope limit:** all car-bucket trips still simulate as
identical sedans regardless of original JWTRNS code (1 = car, 7 =
taxi, 8 = motorcycle, 12 = other). Per-code vehicle-type heterogeneity
is the next step (V12), not V11. See ``doc/SCENARIO_GENERATION.md``
§"Vehicle-type realism" for the realism gap and improvement tiers.

### Phase 10: Audit-tooling wiring for trip-purpose composition (2026-04-30)

Phase 9 added the V5+ `purpose` column to `demand.csv` but no evaluation
tool actually read it. Phase 10 wires the column into both post-run
audit tools so a defender can answer "what fraction of AM peak is
school-related?" without re-deriving the chain/peak labels from
coordinates.

New shared helper module `evaluation/demand_composition.py` exposing:

- `read_demand_composition(demand_csv)` — tally the purpose column,
  return a structured breakdown (total, AM peak, PM peak, chain legs,
  per-purpose counts), or `None` for pre-V5 bundles missing the column.
- `format_composition_report(comp)` — multi-line breakdown for terminal
  output (used by `audit_fairness`).
- `find_canonical_demand(scenario)` — resolves
  `<repo_root>/scenarios/<scenario>/demand.csv` (the canonical bundle's
  copy, not the engine-translated copies which drop `purpose`).
- `AM_PURPOSES` / `PM_PURPOSES` / `CHAIN_LEG_PURPOSES` — re-exported
  frozensets that pin the purpose taxonomy. `AM_PURPOSES` and
  `PM_PURPOSES` are hoisted to module-level constants in
  `pipeline/demand/generate_census_demand.py` so both the generator's
  budget split and the audit tooling pull from the same source.

**audit_fairness.py** — new "Q5: Demand composition" section emitted
after Q4 in every per-scenario audit block. Output for chicago_1k_car:

```
--- Q5: Demand composition (V5+ trip-purpose breakdown) ---
  source: scenarios/chicago_1k_car/demand.csv
  total trips:    1000
  AM peak:          1000 (100.0%)
  PM peak:             0 (  0.0%)
  school-related:     16 (  1.6%) — 8 AM chains + 0 PM chains
  by purpose:
    HBW_AM                  984
    HBW_AM_chained            8
    HBSchool_AM               8
```

Pre-V5 bundles (no `purpose` column) print
`(no V5+ purpose column at <path> — skipping)` and the section is
gracefully omitted from the rest of the audit. No new
PASS/WARN/FAIL gate — Q5 is informational, not a fairness check.

**analyze_benchmark.py** — new
`print_demand_composition_table(stats_list)` emits a one-row-per-unique-
scenario table inserted between the Coverage Diagnostic and Runtime
table sections. Pre-V5 bundles cause the whole section to be silently
omitted (so legacy thesis runs render unchanged). Format:

```
================================================================================
DEMAND COMPOSITION (V5+ trip-purpose breakdown from canonical demand.csv)
================================================================================

Scenario                          Total         AM peak        PM peak    School-rel.
------------------------------------------------------------------------------------
chicago_1k_car                    1,000   1,000 (100.0%)      0 (  0.0%)     16 (  1.6%)
nyc_10k_car                      10,000  10,000 (100.0%)      0 (  0.0%)    ...
================================================================================
```

Tests: new `tests/test_demand_composition.py` (7 tests) covering the
happy-path tally, the pre-V5 graceful no-op, missing-file handling,
empty-purpose-column edge case, the `CHAIN_LEG_PURPOSES ⊆
AM_PURPOSES ∪ PM_PURPOSES` invariant, and the canonical-path resolver.

Honesty note: the audit-slicing capability was claimed in Phase 9c's
documentation but was not actually wired through the evaluation tools
until Phase 10. This entry corrects that.

### Phase 9: Trip-purpose realism from modelgen (2026-04-30)

Closes the modelgen-utilization side of the trip-purpose realism gap
documented in `doc/MODELGEN_AND_MODES.md` §"Realism gaps". Two
purposes added; both use data already in modelgen that V4 was
discarding.

#### Phase 9a: PM HBW return trips (`schedule[1]`)

Cityscape's `<city>_model.txt` per-line schedule field has carried a
PM home-return tuple (`(1 5 61200 home_bld)` = Mon-Fri at 17:00, go to
home building) alongside the AM workplace tuple since the
Schedule-generator branch shipped. SimForge V4 only consumed
`schedule[0]` (AM workplace at 28800/8 AM); the PM tuple was parsed
but never read. **V5+ reads both.**

`_generate_departure_time` already accepted an `arrival_time_s`
parameter (added in Phase 8 for per-person commute-derived AM
departures). Phase 9a wires that parameter to a peak-aware allocation:

- Detect whether `horizon ⊇ {AM_PEAK_S=28800}` and/or
  `{PM_PEAK_S=61200}`.
- Both peaks in horizon (e.g. 24h chicago_200k_car bundle): split the
  user's `--trips N` budget 50/50 across AM (HBW outbound,
  home → work) and PM (HBW return, work → home).
- AM-only horizon (chicago_1k_car at 7-8 AM, nyc_10k_car 7-9, la_50k_car
  6-10, nyc_500k_car 6-10): unchanged — all N trips are HBW_AM.
- PM-only or neither (rare): clamp to AM template.

Each PM trip uses `schedule[1].time_s` as the per-person arrival
clock and the same person's `commute_min` for the departure offset:
`departure = pm_arrival - commute*60`. Origin/destination flipped
relative to AM (work → home).

New `purpose` column on `demand.csv`: `HBW_AM` and `HBW_PM`.
Existing canonical 5-column subset (`trip_id, origin_node_id,
destination_node_id, departure_time_s, mode`) unchanged — adapters
read it by name and ignore the new column.

Empirical effect on chicago 24h, 200 trips, seed 42:
- 100 HBW_AM rows (departures cluster 6:30-7:55 AM)
- 100 HBW_PM rows (departures cluster 15:30-16:55 PM)
- Aggregate shape: realistic bimodal AM+PM peak instead of single AM

#### Phase 9b: HBSchool trips (AGEP < 18 + building kind=school)

For commuters whose household contains a school-age dependent
(`AGEP < 18` from PUMS), the V5+ generator emits a chained
home → school → work morning trip pair instead of a bare home → work
trip. Each chain consumes 2 budget slots; non-parent commuters and
parents whose nearest school is > 5 km away still emit single
HBW_AM trips.

Two foundational fixes were required:

1. **`age_by_per_id` carries unfiltered ages**
   (`pipeline/demand/parse_model_file.py:154` ModelData; populated
   at parse time before mode-filtering). Kids have `JWTRNS=-1` (Not
   a worker) and were silently dropped by the existing
   mode/car_only filter, so previous lookups via `per_by_id` could
   never find them. The new map is built from the full
   pre-filter person list, so `_has_school_age_dependent` can
   detect kids in commuter households.

2. **School-building detection** via `Building.kind`
   (`pipeline/demand/generate_census_demand.py::_is_school_kind`).
   Cityscape preserves OSM `building=school|kindergarten|preschool|
   college|university` tags on `bld.kind`. The generator
   pre-computes the school-node array once per scenario, then a
   vectorized haversine lookup picks the nearest school within 5 km
   of each parent's home.

New `purpose` values on `demand.csv`: `HBSchool_AM` (home → school,
parent dropping kid off) and `HBW_AM_chained` (school → work,
parent's continued commute). Both rows share the same per-person
departure time computed from JWMNP — the engine simulates the parent
making both legs from the same vehicle/agent.

Empirical effect on chicago_1k_car bbox (2 km Loop), 200 trips:
- 90 school buildings detected inside SCC (universities, K-12, preschool)
- 713 of 7,937 schedule-bearing persons (~9 %) live with a school-age
  dependent within the bbox
- 8 chains emitted at sample size 200 (consumes 16 budget slots)
- Final demand: 184 HBW_AM + 8 HBSchool_AM + 8 HBW_AM_chained = 200

Tests:
- `tests/test_parse_model_file.py::TestHBSchoolHelpers` — 6 new tests
  covering `_is_school_kind` recognition, `age_by_per_id` filtered-kid
  visibility, household-composition lookup edge cases (solo
  household, all-adult household, PUMS -1 sentinel exclusion).

What's still NOT in modelgen for trip purposes:
- HBO (shopping, leisure, errands): no per-person purpose flag in
  PUMS; would need NHTS or probabilistic inference from
  building-kind diversity.
- NHB (work → meeting → office, etc.): same.
- Weekend / school-out variation: cityscape's schedule encodes
  weekday-only behavior (`dow_start=1, dow_end=5` hardcoded).

Phase 9 closes ~30 % of the urban-VMT gap when the horizon includes
the PM peak (the schedule[1] win); HBSchool adds ~5-10 % more when
the bbox covers households with kids and schools. Together they
move SimForge from "AM HBW only" to "AM + PM HBW + AM HBSchool"
without any external data dependency.

#### Phase 9c: HBSchool_PM (school pickup chain) (2026-04-30)

Symmetric mirror of Phase 9b. Parents with a school-age dependent
in their household now emit a chained `work → school → home` PM
trip pair instead of a bare `work → home` trip when the horizon
spans the 17:00 PM peak. The chain reuses Phase 9b's
`_maybe_school_chain_for` gating (same nearest-school lookup,
`_SCHOOL_MAX_KM=5.0` reach, same household-dependent detection),
just applied to the PM half of the budget split.

Two new `purpose` values on `demand.csv`:
- `HBW_PM_chained` — parent leaves work, drives to school for
  pickup
- `HBSchool_PM` — parent + kid drive from school to home (kid is
  the passenger that justifies the chain detour)

Both rows share the same per-person departure time, computed from
`schedule[1].time_s − commute_min × 60` (same convention as Phase
9a). Each chain consumes 2 PM-budget slots; non-parent commuters
and parents with no school inside `_SCHOOL_MAX_KM` continue to
emit single `HBW_PM` trips.

`PM_PURPOSES` budget set updated:
`{"HBW_PM"} → {"HBW_PM", "HBSchool_PM", "HBW_PM_chained"}`. The
gravity-fallback Phase 2 sees the chained legs as PM-emitted and
skips topping up beyond the requested budget — same accounting
discipline as Phase 9b's AM side.

Empirical effect on chicago 24h horizon, 1,000 trips, seed 42
(same network as `chicago_1k_car`, just full-day instead of 7-8 AM):

```
HBW_AM             474
HBW_AM_chained      13
HBSchool_AM         13
HBW_PM             476
HBW_PM_chained      12
HBSchool_PM         12
                  ─────
Total            1,000   (AM peak=500 + PM peak=500, chain legs=50)
```

The PM chain rate (12/500 = 2.4 %) is slightly below the AM rate
(13/500 = 2.6 %) because the cohort is independently shuffled per
peak, but both peaks see ~2-3 % chain participation — consistent
with the ~9 % bbox-covered parent-with-kid pool in the chicago_1k
SCC.

Back-compat: AM-only horizons (chicago_1k_car at 7-8 AM,
nyc_10k_car 7-9 AM, all bundled tiers) emit zero PM rows and are
byte-identical to Phase 9b output. Verified by regenerating
`scenarios/chicago_1k_car/demand.csv` after the refactor —
distribution unchanged: 984 HBW_AM + 8 HBSchool_AM + 8
HBW_AM_chained = 1,000.

### Phase 8: PUMS-grounded departure times (2026-04-30)

Replaced the synthetic Gaussian peak in `_generate_departure_time` with
**per-person empirical departures** computed from already-available PUMS
data:

```
departure_time_s = arrival_time_s − person.commute_min × 60
```

where `arrival_time_s` is the cityscape-emitted workplace arrival
(28800 s = 08:00 AM for schedule-driven persons; same constant for the
gravity-fallback persons whose schedule is empty) and
`person.commute_min` is the person's PUMS-reported `JWMNP` (Travel time
to work, in minutes).

Pre-V5 behavior:
- Gaussian peak centered at horizon midpoint
- σ = `(end - start) / 6` — so a 1-hour horizon got σ = 10 min
- All trips bell-shaped around the midpoint, regardless of any
  individual's actual commute duration.

V5 behavior:
- **Per-person empirical**: each trip's departure is grounded in that
  person's PUMS-reported commute time
- The aggregate temporal shape emerges naturally from the JWMNP
  distribution of the cohort (long-commute persons depart earlier;
  short-commute persons depart closer to arrival)
- Trips whose computed departure falls outside `[horizon_start,
  horizon_end - 1]` are clamped to the boundary rather than dropped
  (keeps trip counts stable and audit-deterministic)

Empirical effect on a chicago 7-8 AM, 1,000-trip generation:

```
new departure histogram (5-min buckets, seconds from midnight):
  25200-25500  85   ← clamped: JWMNP > 60 min
  25800-26100  38
  26100-26400  76
  26400-26700  43
  26700-27000  10
  27000-27300  147
  27300-27600  42
  27600-27900  125
  27900-28200  121
  28200-28500  237  ← natural peak (short commutes)
  28500-28800  75
```

The natural right-skewed shape mirrors a real US AM peak: most
commuters depart shortly before their 8 AM arrival; long-commute
people stretch the tail backward. Pre-V5 the same population produced
a tight bell centered at 7:30 AM.

Cross-engine fairness invariance is preserved (every adapter consumes
the same demand.csv). Absolute travel times: peak congestion now
concentrates more accurately near the natural surge point rather than
being smeared across the horizon.

Net code change: `pipeline/demand/generate_census_demand.py` —
`_generate_departure_time()` rewritten (no `rng` argument; takes
`arrival_time_s` as a defaulted parameter). Both call sites pass the
person's `schedule[0].time_s` when available, fall back to the
cityscape AM constant otherwise. No new dataset dependency.

### Phase 7: OSM turn restrictions — extraction + adapter enforcement (2026-04-30)

Extracted OSM `type=restriction` relations during the existing PBF
ingestion pass and persisted them to canonical `network.xml` as a new
`<turn_restrictions>` block. **All three adapters now enforce them
symmetrically** in their native formats — SUMO and MATSim pre-route
via the shared state-aware BFS, DTALite gets a GMNS `movement.csv`
that mirrors the OSM data for downstream tools (path4gmns 0.10.0
doesn't ingest movement.csv natively yet, so DTALite's UE assignment
treats this file as documentary; SUMO and MATSim do enforce).

Three concrete code changes:

- **`pipeline/network/load_network_from_pbf.py`** — `_slice_pbf_to_xml`
  now also detects OSM relations with `type=restriction` and
  `via=node` on the same PBF stream that produces the way slice and
  the signal-node set. Returns a 4-tuple
  `(ways_written, nodes_referenced, signal_node_ids, turn_restrictions)`
  where each turn-restriction entry is a dict
  `{"restriction": str, "from_way": int, "via_node": int, "to_way":
  int, "osm_relation_id": int}`. Cost: zero — the relation pass was
  already happening as part of the FileProcessor stream; we just
  added a tag-and-member check.

- **`pipeline/network/build_network_from_osm.py`** — added
  `CanonicalTurnRestriction` dataclass and resolution logic in
  `extract_canonical_network()` that maps OSM way IDs → canonical link
  IDs (using `(osm_way_id, to_node)` for the from-link and
  `(osm_way_id, from_node)` for the to-link). Restrictions whose
  via-node was filtered out by the bbox + SCC truncation, or whose
  ways didn't survive into the canonical link set, are silently
  dropped — those movements can't be made on the canonical network
  anyway. `build_network_xml()` emits a `<turn_restrictions>` block
  after `<links>` when at least one resolved restriction exists.
  `build_network_from_osm()` returns `turn_restriction_count` in its
  result dict.

- **`pipeline/network/turn_restrictions.py`** (new) — three utilities
  for downstream use:
  - `parse_turn_restrictions(network_path)` — reads
    `<turn_restriction>` entries; empty list for V4 / pre-restriction
    networks (back-compat).
  - `build_forbidden_moves(restrictions, outgoing_links_by_node)` —
    compiles a list of restrictions into a fast
    `(via_node, from_link) -> frozenset[forbidden_to_link]` lookup,
    correctly expanding `only_*_turn` restrictions into "everything
    except the named exit is forbidden."
  - `shortest_path_with_restrictions(...)` — state-aware BFS where
    state is `(node, last_link_id)`; outgoing links forbidden by the
    restrictions table are skipped during expansion.

- **`canonical/schema/network_v0.md`** — added `<turn_restriction>`
  documentation with the seven supported OSM restriction values, the
  required attribute table, the `(via=node, from_link)` resolution
  semantics, and the `only_*_turn`-as-inverted-set convention.

### Adapter enforcement (V5 follow-up)

**SUMO** (`adapters/sumo/sumo_adapter.py:build_sumo_routes_xml`):
The pre-V5 `shortest_path_nodes(adjacency, ...)` BFS call site at the
trip-routing loop is now `shortest_path_with_restrictions(...)` from
the new utility module. State is `(node, last_link_id)`; outgoing
links forbidden by the compiled restriction table are skipped during
expansion. When state-aware BFS finds no path (rare — restrictions
typically force detours, not disconnections), the adapter falls back
to plain BFS and logs the count. Empirical fallback rate on
chicago_1k_car: typically 0.

**MATSim** (`adapters/matsim/matsim_adapter.py:build_matsim_plans_xml`):
Each plan now ships with an explicit
`<route type="links" start_link=… end_link=…>…interior link IDs…</route>`
inside its `<leg>` element when the canonical network has turn
restrictions. The route comes from the same state-aware BFS the SUMO
adapter uses — so SUMO and MATSim consume identical paths. The plans
XML uses **MATSim 15 population_v6 DTD** (originally shipped with
plans_v4 in V5.7, corrected to population_v6 in V11.2 after the
plans_v4 DTD was found to reject `type="links"` and treat route text
as a node sequence — see Phase 11.2 entry above). MATSim 15's
`PopulationReaderMatsimV6` honors pre-emitted routes and skips its
internal router. A new `_LinkRef` shim wraps MATSim's dict-based link
records to plug into the generic BFS. When restrictions are absent
(legacy bundles, synthetic networks), MATSim falls back to its V4
self-routing behavior — back-compat preserved.

**DTALite** (`adapters/dtalite/dtalite_adapter.py:write_dtalite_movement_csv`):
New writer emits a GMNS-conformant `movement.csv` next to the engine's
`node.csv` / `link.csv` / `demand.csv` outputs. Each row maps an OSM
turn restriction to a movement record with `capacity=0` and
`penalty=99999` — both standard GMNS signals for "this movement is
forbidden." path4gmns 0.10.0 (the DTA library SimForge uses) doesn't
ingest movement.csv natively yet, so DTALite's UE assignment may
still cross restricted movements in practice. The file is documentary
+ future-proof: any GMNS-aware downstream tool can read it, and
upgrading path4gmns to a movement-aware version closes the loop
without further SimForge changes. This is the one cross-engine
asymmetry the V5 work leaves open.

### Cross-engine fairness analysis

Pre-V5: SUMO pre-routed; MATSim and DTALite routed independently.
Three different routing strategies, three different paths possible
for the same trip — `audit_fairness` Q4 (cross-engine TT comparison)
already absorbed this asymmetry as part of the thesis's
"engines disagree" signal.

V5: SUMO and MATSim now use **identical paths** (both pre-routed via
the same state-aware BFS), so their TT difference reflects only
physics-engine differences (mesoscopic queue dynamics, signal
phasing, vehicle spawn timing). This actually *tightens* their direct
comparability while jointly respecting OSM ground truth. DTALite
remains a UE-assignment paradigm comparison (its routing strategy
differs by design). Q1-Q4 audits all continue to pass.

### Empirical effect on bundle generation

| Bundle           | OSM PBF     | Restrictions extracted (typical) | Wall-time delta |
|------------------|-------------|---------------------------------:|----------------:|
| chicago_1k_car   | IL 348 MB   | 50-200                           | +0 s (free)     |
| nyc_10k_car      | NY 489 MB   | 200-800                          | +0 s (free)     |
| la_50k_car       | CA 1.3 GB   | 1,000-3,000                      | +0 s (free)     |

Cost is zero because relation traversal was already part of the
FileProcessor stream — we just added a member/tag inspection.

### Phase 6: OSM-grounded signal placement (2026-04-29)

Replaced the legacy "signalize every junction with degree ≥ 4"
heuristic in `pipeline/signals/build_signals_default.py` (which
signalized ~85 % of network nodes — every junction, regardless of
real-world reality) with **OSM `highway=traffic_signals` ground
truth**. Empirical effect on the three reference bundles:

| Bundle           | Before   | After     | Change       |
|------------------|---------:|----------:|-------------:|
| chicago_1k_car   | 16,959   |   560     | -97 % (85% → 2.8 %) |
| nyc_10k_car      | ~30,596  | ~1,500-2,000 | (regen pending) |
| la_50k_car       | 134,726  | 2,153     | -98 % (84.7% → 1.4 %) |

Real-world commentary on these counts: 1-3 % of network nodes
matches "5-10 % of *real* intersections" because the OSM-node
denominator counts every junction (including driveways, cul-de-sacs,
alley intersections), not just traffic-engineering-relevant ones.
Absolute counts (560 / 2,153) line up with the actual signalization
density of each city's bbox per LADOT and Chicago DOT public records.

Three concrete code changes:

- **`pipeline/network/load_network_from_pbf.py`** — `_slice_pbf_to_xml`
  now piggybacks signal-node detection on the same PBF stream that
  produces the way-network slice. Returns
  `(ways_written, nodes_referenced_count, signal_node_ids)` instead of
  the previous `(int, int)`. Cost: ~10 s extra on a 1.3 GB CA PBF
  (single pass; a separate scan would have been 30-140 s). The
  standalone `extract_traffic_signal_node_ids()` helper that an earlier
  iteration of this fix introduced was removed in favor of the
  unified scan.

- **`pipeline/network/build_network_from_osm.py`** — `CanonicalNode`
  gains `has_signal: bool = False`. `extract_canonical_network()`
  accepts an `osm_signal_ids: set[int]` argument and sets
  `has_signal=True` on canonical nodes whose source OSM ID is in that
  set. For the Overpass fallback path (rarely used; only fires when no
  local PBF covers the bbox), `data.get("highway") == "traffic_signals"`
  is also accepted because `osmnx.graph_from_bbox` preserves node tags.
  `build_network_xml()` emits `has_signal="true"` on tagged nodes.
  `build_network_from_osm()` returns `osm_signal_node_count` in its
  result dict.

- **`pipeline/signals/build_signals_default.py`** —
  `load_network_topology()` returns the set of nodes with
  `has_signal="true"`. `identify_signalized_intersections()` prefers
  this OSM ground truth as the source of truth and signalizes only
  those nodes. When the set is empty (legacy network.xml without the
  V5 attribute), it falls back to the old degree heuristic with a loud
  WARNING telling the operator to regenerate the network. The module
  docstring was rewritten to describe both paths.

- **`canonical/schema/network_v0.md`** — added `has_signal` (boolean,
  optional) and `osm_id` (string, optional, was emitted but undocumented)
  rows to the `<node>` attribute table.

Wall-time impact: +~10-30 s per `generate.py` run depending on PBF
size (IL 348 MB: +10 s, NY 489 MB: +15 s, CA 1.3 GB: +30 s). Net cost
is paid for the OSM signal scan added to the existing PBF stream.

Cross-engine fairness is unaffected: every adapter still consumes the
same `signals.xml` file, so Q1-Q4 in `audit_fairness` continue to
PASS as before. Absolute simulated travel times will drop noticeably
in dense-bundle benchmarks (~10-30 %, depending on bundle) because
cars no longer stop at every block — they stop only at the actually
signalized intersections OSM records.

The cycle template inside each controller is unchanged: 2-phase 90-second
fixed cycle, no actuation, no coordinated arterial timing. Real-world
signal timing realism is left as future work; this change brings only
the *placement* of signals in line with OSM ground truth.

### Phase 5: JWTRNS code-mapping correction + mode-aware feasibility (2026-04-29)

The 2026-04-29 mode-mapping audit found that SimForge's `JWTRNS_TO_MODE`
dict was authored against the **pre-2019 ACS PUMS codebook** (drove-alone=1,
carpool=2, taxi=11, WFH=10) while the cityscape-produced `<city>_model.txt`
files use the **ACS 2021** codebook (Car/truck/van=1, Bus=2, Taxi=7, WFH=11).
Six of twelve codes had the wrong simulator bucket; the empirical impact
was Chicago's reported "1,044,084 car commuters" silently including ~71K
bus riders + ~326K WFH workers + ~17K "Other" — a 37% inflation of the
car pool. Same arithmetic applied to NYC and LA.

Five fixes shipped together so the regenerated bundles are coherent:

- **`pipeline/demand/parse_model_file.py`** — `JWTRNS_TO_MODE` rewritten
  with the cityscape-correct mapping (`car: {1,7,8}`, `transit: {2,3,4,5,6}`,
  `bike: {9}`, `walk: {10}`, `home: {11,12}` / excluded). Added
  `SUPPORTED_MODES` tuple + `MODE_TO_JWTRNS` reverse index. The hardcoded
  `car_modes = {1, 2, 11, 12}` literal at line 414 is gone — the car-only
  filter path now derives its set from `MODE_TO_JWTRNS["car"]`. Module
  docstring rewritten with cityscape labels and citation.
- **`pipeline/modelgen_scanner.py`** — duplicate `JWTRNS_TO_MODE` dict
  removed; `from pipeline.demand.parse_model_file import JWTRNS_TO_MODE`
  re-export so the scanner and demand pipeline can never drift.
- **`generate.py`** — dispatch at the `parse_model_file` call site
  simplified: always passes `modes=modes`. Fixes the silent no-filter
  bug where single non-car modes (e.g. `--modes transit`) hit neither
  the `modes is not None` branch nor the `car_only` branch and let the
  full unfiltered population through.
- **`adapters/common/feasibility.py`** — `feasible_trip_ids()` accepts a
  `supported_modes` set; trips whose `mode` column is outside this set
  are dropped from the feasible set with a new `skipped_unsupported_mode`
  counter on the report. SUMO/MATSim/DTALite adapters now declare
  `supported_modes={"car"}` so multi-mode bundles automatically narrow
  to their car subset before simulation. The `FeasibilityReport` JSON
  carries the `supported_modes` it was filtered on.
- **`evaluation/audit_fairness.py`** — Q1 includes the new
  `skipped_unsupported_mode` counter in the byte-identical comparison.
  Q3 now compares each engine's simulated count against its own
  `feasibility_report.json::feasible_trips` (per-engine target) instead
  of using one engine's target for all, and prints the `mode∈{...}`
  scope alongside the count.

The `python help.py cities` output now reflects the corrected counts —
Chicago's "Car" drops from 1,044,084 to ~654K (a clean removal of the
WFH/bus inflation), Chicago's "Transit" jumps from 73,621 to ~145K (now
correctly includes bus riders), Chicago's "Bike" jumps from 467 to
~18K (now correctly mapped to PUMS code 9 = Bicycle, was wrongly mapped
from code 8 = Motorcycle), and Chicago's "Walk" goes from 0 to ~55K
(was wrongly excluded under the old `10: "home"` mis-mapping).

Generation scripts and presets renamed to match scenario folder names,
and the medium/large-tier scripts switched to car-only modes (matching
what every adapter today actually simulates):

| Before | After | Notes |
|---|---|---|
| `scripts/01_quick_test.py`        | `scripts/01_chicago_1k_car.py`     | name only |
| `scripts/02_small_commute.py`     | `scripts/02_nyc_10k_car.py`        | name only |
| `scripts/03_medium_multimodal.py` | `scripts/03_la_50k_car.py`         | mode change: `[car,transit,bike] → [car]` |
| `scripts/04_large_full_day.py`    | `scripts/04_chicago_200k_car.py`  | mode change: `[car,transit] → [car]` |
| `scripts/05_stress_test.py`       | `scripts/05_nyc_500k_car.py`       | name only |
| preset `quick_test`               | preset `chicago_1k_car`           | renamed |
| preset `small_commute`            | preset `nyc_10k_car`              | renamed |
| preset `medium_multimodal`        | preset `la_50k_car`               | renamed + mode change |
| preset `large_full_day`           | preset `chicago_200k_car`         | renamed + mode change |
| preset `stress_test`              | preset `nyc_500k_car`             | renamed (runspec name unchanged) |
| `cluster/jobs/0X_*.sbatch`        | matching `0X_<scenario_id>.sbatch` | renamed in lockstep with scripts |
| `scenarios/la_50k_bike_car_transit/` | `scenarios/la_50k_car/`           | git-renamed; user regenerates content |
| `scenarios/chicago_200k_car_transit/` (gitignored) | regen as `chicago_200k_car` | folder will be re-emitted on next run |

`runspecs/{benchmark_small,benchmark_large}.yaml` updated to point at the
new scenario IDs. `runspecs/stress_test.yaml` (the canonical thesis matrix)
is unchanged — its `chicago_1k_car` cell was already correctly named.

Documentation refreshed: `doc/MODELGEN_AND_MODES.md` (new in this phase,
authoritative reference for the data + mode pipeline), `help.py`
(`HELP_MODES`, `HELP_SCRIPTS`, `HELP_ADAPTERS`), `doc/SCENARIO_GENERATION.md`,
`doc/chapters/methods.md`, `README.md`, `SETUP.md`, `.gitignore`.

The three tracked bundles (`chicago_1k_car`, `nyc_10k_car`, `la_50k_car`)
will be regenerated end-to-end by the user after this phase lands; their
existing `demand.csv` files were generated under the wrong mapping and
will change. The two large untracked tiers (`chicago_200k_car`,
`nyc_500k_car`) regenerate on demand on the user's dev box / Pitzer.

### Phase 4: cross-engine fairness audit + paradigm-spread validation

After Phase 3 landed the engine swap end-to-end, Phase 4 added the fairness
audit infrastructure and used it to verify (and fix) the cross-engine
input contract on Pitzer. The narrative log of every commit, job ID, and
measured number lives in [`doc/EXPERIMENT_LOG.md`](doc/EXPERIMENT_LOG.md);
Phase 4-relevant headlines:

- **`evaluation/audit_fairness.py`** — read-only cross-engine fairness
  audit (commits `d42a7f8`, `7c576f6`, `542bd4a`, `59fc7cc`, `4a8eded`,
  `ff33f06`). Four checks per scenario: Q1 same trip set, Q2 same network,
  Q3 same trip count simulated, Q4 cross-engine travel-time spread. Auto-
  detects four output layouts (`run.py` flat, `execution.run_benchmark`
  nested, parallel-by-scenario sbatch nested, and per-scenario worker
  dir). Counts SUMO nodes from `.nod.xml` / `.edg.xml` rather than the
  compiled `.net.xml` (which inflates with internal lane junctions).
  Invocation: `python -m evaluation.audit_fairness <run_dir>`.
- **DTALite SCC-fairness fix** (commit `861c971`) — `prepare_dtalite_inputs`
  now prunes the canonical graph to the largest SCC before emitting
  `node.csv` / `link.csv`, matching MATSim's `clean_network` and (after
  `df5fe4e`) SUMO's prepare path. Verified on chicago_1k_car: DTALite
  emits 19,744 nodes (== MATSim) / 1,184 zones / 58,162 links. The 270-link
  gap from MATSim's 58,432 is the documented self-loop + sub-meter OSM-
  noise filter (BPR cost would divide by zero on those edges).
- **SUMO SCC-fairness fix** (commit `df5fe4e`) — `prepare_sumo_inputs`
  now applies the same `compute_largest_scc` filter the other adapters
  use. Closed the last fairness gap: previously SUMO emitted the full
  canonical network (314 non-SCC dead-end nodes more than MATSim/DTALite
  on chicago_1k_car) because SUMO tolerates dangling links and the prune
  was historically skipped. Trips themselves were already SCC-feasibility-
  filtered, so the dropped nodes were unused; the fix is for cross-engine
  fairness audit defensibility, not for changing simulation results.
- **Engine/mode skip** (commit `c31e087`) — `run.py` now skips
  (engine, mode) cells the engine doesn't support, instead of silently
  re-running mesoscopic-only engines as `mode=micro`. New
  `ENGINE_SUPPORTED_MODES` constant: SUMO supports both, MATSim and
  DTALite support meso only. `--engine sumo,matsim,dtalite --mode meso,micro`
  with N=3 reps × 2 scenarios is now 24 runs (8 valid cells × 3 reps),
  down from 36 in the naive Cartesian product. Banner prints the
  skipped pairs so the operator can audit.
- **`doc/EXPERIMENT_LOG.md`** — chronological journal of every commit,
  SLURM job ID, and measured number on the Version_5 branch. Format
  spec at the top of the file; new entries land at the top of §3.
  Source-of-truth for the thesis writeup: every results-chapter claim
  should cite back to a specific dated entry here.

### Pitzer benchmark_small chicago_1k_car (job 47116156, 2026-04-27)

First three-engine fairness data (Mac couldn't run SUMO due to arm64
`netconvert`). chicago_1k_car worker finished in 8.6 min with 20/20
successful runs:

| Engine | Mean TT | P95 | R-score | Completed |
|---|---|---|---|---|
| SUMO meso | 372.4 s | 689.0 s | 0.9963 | 932/1000 |
| SUMO micro | — | — | 0.9966 | 1000/1000 |
| MATSim meso | 244.5 s | 423.0 s | 1.0000 | 1000/1000 |
| DTALite meso | 174.1 s | 291.4 s | 1.0000 | 997/1000 |

Cross-engine TT ratios (paradigm-spread signal):

- DTALite/MATSim mean-TT: 0.712 (-28.8%) — DTA equilibrium finds optimal
  routes, undercuts queue-mobsim by ~29%
- SUMO/MATSim mean-TT: 1.523 (+52.3%) — SUMO meso adds intersection
  delays, ~52% above MATSim
- SUMO/DTALite mean-TT: 2.139 (+113.9%) — full paradigm spread is 2.1×

This is the headline thesis result the cross-engine framework was built
to produce.

---

### Engine swap: LPSim removed, DTALite added

After exhaustive Pitzer debugging (~12 commits across two debugging sessions in
Version_4), LPSim was abandoned. The bundled `LivingCity` binary had a GPU
kernel OOB at `b18CUDA_trafficSimulator.cu:1682` on networks larger than a few
thousand nodes; an in-container source rebuild against the container's CUDA
12.4 (with sm_70 arch + Boost 1.59 sed-patches for modern g++) succeeded but
the rebuilt binary still SIGSEGV'd at "Starting simulation..." on the
chicago_1k_car scenario. The full integration narrative is in
[`doc/engines/LPSIM_RETROSPECTIVE.md`](doc/engines/LPSIM_RETROSPECTIVE.md).
The third-engine selection rationale is in
[`doc/engines/THIRD_ENGINE_OPTIONS.md`](doc/engines/THIRD_ENGINE_OPTIONS.md);
DTALite was chosen on three grounds: (1) it actually works (smoke-tested
locally during the selection research), (2) it's CPU-only so the full matrix
runs on Mac as well as Linux, (3) it adds a paradigm-distinct comparator
(mesoscopic Dynamic Traffic Assignment with user equilibrium) — vs LPSim
which would have been "another mesoscopic queue-based engine" overlapping with
MATSim. The cross-engine paradigm-spread argument now reads SUMO microscopic +
MATSim queue-based agent + DTALite DTA equilibrium = three distinct paradigms.

### Removed (Phase 1)

- `adapters/lpsim/` package + cli + MAPPING.md
- `tests/test_lpsim_adapter.py` (39 tests)
- `lib/lpsim/manifest.json`
- `cluster/jobs/{build,smoke,diag}_lpsim.sbatch`
- All `lpsim` runspec entries across `stress_test.yaml`,
  `benchmark_small.yaml`, `benchmark_large.yaml`
- `lpsim` membership in `execution/runspec.py::KNOWN_ENGINES`,
  `execution/run_benchmark.py::supported_engines`, `run.py::ALL_ENGINES`,
  and the `evaluation/{generate_plots,analyze_benchmark,compare_modes}.py`
  engine-tuple registries
- LPSim manifest detection in `tools/env_report.py`
- LPSim references in `help.py`, `tests/test_engine_smoke.py`, and
  `tests/conftest.py`
- LPSim sections in `README.md`, `SETUP.md`, `TESTING.md`, `CONTRIBUTING.md`,
  `doc/PITZER.md`, `doc/REPRODUCING.md`, `doc/ARCHITECTURE.md`,
  `doc/RESULTS_GUIDE.md`, `doc/chapters/{methods,results,experiments}.md`
- `cluster/jobs/benchmark_{small,large}.sbatch`: switched off
  `--partition=gpu` (no engine needs CUDA), dropped `cuda/11.8.0` module
  load and the LPSim binary-presence preflight

### Added (Phase 2)

- **`adapters/dtalite/` package** mirroring the SUMO/MATSim structure:
  - `dtalite_adapter.py`: canonical → GMNS conversion (`prepare_dtalite_inputs`),
    UE assignment via `path4gmns.DTALiteClassic` mode 1
    (`run_dtalite`), `agent.csv` parsing with volume expansion + minute→second
    conversion (`parse_dtalite_output`). Includes binary discovery
    (`is_dtalite_available`, `find_dtalite_binary`) and the
    `collect_demand_node_ids` helper that powers the demand-driven zoning
    optimisation (zones only the ~1,800 demand-carrying nodes out of 20,058
    on chicago_1k_car, dropping runtime from "5 minutes" to "5 seconds")
  - `__init__.py` exports the public API
  - `cli.py` standalone CLI mirroring `adapters/matsim/cli.py`
  - `MAPPING.md` documents the canonical → GMNS schema mapping with
    line-level cross-references, unit conversions (m→km, m/s→km/h,
    min→s), the DTALiteClassic-vs-Multimodal choice, the macOS
    multiprocessing wrapper bug workaround, and known limitations
- **`lib/dtalite/manifest.json`** pins `path4gmns==0.10.0` + upstream URLs.
  `.gitignore` updated to re-include the manifest under the otherwise-ignored
  `lib/*` (replaces the LPSim re-include rule that became dead in Phase 1)
- **`tests/test_dtalite_adapter.py`** — 46 unit tests covering all writers,
  schema fidelity (LF endings, GMNS column names), unit conversions, demand
  aggregation by OD pair, intra-zonal trip filtering, sub-meter edge filtering,
  demand-driven zoning, determinism (byte-identical re-runs), output parsing,
  binary discovery, and an end-to-end smoke test gated on path4gmns
  availability that actually runs DTALite
- **DTALite branches** in `execution/runspec.py`, `execution/run_benchmark.py`,
  `run.py`, `evaluation/{generate_plots,analyze_benchmark,compare_modes}.py`,
  `tools/env_report.py`, `help.py`, `tests/test_engine_smoke.py`
- **`runspecs/{stress_test,benchmark_small,benchmark_large}.yaml`** — DTALite
  cells replace the LPSim cells (same scenarios, same N=5 repeats)
- **`requirements.txt` + `requirements.lock`** — `path4gmns>=0.10.0,<1` added
  with a comment noting the macOS `brew install libomp` system dep

### Documented

- `doc/engines/LPSIM_RETROSPECTIVE.md` — full narrative of LPSim integration,
  the five failure classes (4 resolved, GPU kernel SIGSEGV unresolved), and
  why the abandonment frames as evidence FOR SimForge's adapter pattern
- `doc/engines/QARSUMO_RETROSPECTIVE.md` — Version_4 Phase A drop story for
  the QarSUMO 5th-engine slot
- `doc/engines/THIRD_ENGINE_OPTIONS.md` — deep research verdicts on DTALite,
  CityFlow, and POLARIS as third-engine candidates, with DTALite recommended
- `doc/engines/ENGINE_COMPARISON.md` — thesis-writing reference consolidating
  paradigm taxonomy, wallclock estimates, R-score expectations, output
  fidelity comparison, and a thesis-defense quote bank

### Verified

- End-to-end smoke on Mac arm64 (Darwin 25.4): chicago_1k_car
  (20,058 nodes / 58,505 links / 1,000 trips) prepared + run + parsed
  in **8.4 s** total via `python run.py --scenario chicago_1k_car
  --engine dtalite --mode meso`. Mean travel time 174 s (2.9 min),
  P95 291 s, mean distance 2.89 km — values consistent with morning-peak
  Chicago profile.
- Full pytest suite: **429 passed, 1 failed (pre-existing arm64 netconvert
  issue, not introduced by Version_5), 9 skipped** in 226 s.
- `python tools/env_report.py | grep dtalite` surfaces the bundled binary
  path and the path4gmns version pin.

---

## [Unreleased] — Version_4 (superseded by Version_5)

### Fixed (Phase B Pitzer landing patch)

- **LPSim binary failed with `libcudart.so.11.0: not found` on first Pitzer launch** — the `yibo123/lpsim:cuda12.4` image is mis-tagged. The image's installed CUDA toolkit is 12.4, but the bundled `LivingCity` binary was compiled against `libcudart.so.11.0`. Diagnosis: `ldd /LivingCity/LivingCity` inside the SIF showed `libcudart.so.11.0 => not found` as the only unresolved dependency. Resolution:
  - `adapters/lpsim/lpsim_adapter.run_lpsim` now detects `$CUDA_HOME` on the host and, when `libcudart.so.11.0` is present, passes `singularity exec --nv --bind /apps --env LD_LIBRARY_PATH=$CUDA_HOME/lib64:/usr/local/cuda-12.4/lib64:/usr/include/pandana/src:/.singularity.d/libs …`. Apptainer 1.3.6 doesn't auto-mount `/apps` and doesn't inherit host `LD_LIBRARY_PATH`, so both the bind and the env var are required. Logs a clear warning if `$CUDA_HOME` isn't set.
  - `cluster/jobs/benchmark_small.sbatch` + `benchmark_large.sbatch` + `build_lpsim.sbatch` now `module load cuda/11.8.0` (CUDA 11.8 is binary-stable with 11.0; ships `libcudart.so.11.0`).
  - `lib/lpsim/manifest.json` gains `cuda_runtime_required` / `cuda_runtime_note` / `host_cuda_module_pitzer` fields documenting the requirement.
  - `doc/PITZER.md` adds an explicit "CUDA-version pitfall" callout under the LPSim section.

### Added (Phase B reproducibility patch)

- **`lib/lpsim/manifest.json`** — pinned LPSim provenance: git SHA `452067ee831e6ecb4c906bae96fb77fdf71fa92e` (2024-11-27), Docker image `yibo123/lpsim:cuda12.4`, build dependency manifest. Same provenance pattern `osm_data/manifest.json` uses for OSM PBFs. LPSim is **not** in `requirements.lock` because it's a C++ binary — this manifest is the equivalent reproducibility artifact.
- **`cluster/jobs/build_lpsim.sbatch`** now reads the pinned SHA + Docker tag from `lib/lpsim/manifest.json` (via `jq`) and `git checkout --detach` to that SHA before building. Overridable with `--export=LPSIM_GIT_SHA=…,LPSIM_DOCKER_REF=…`.
- **`tools/env_report.py`** reports LPSim binary state (binary, Singularity image, or "NOT BUILT") plus the pinned `git@SHA` and `image:tag` from the manifest — surfaces cross-machine drift in the same diagnostic that already covers SUMO + MATSim.
- **`tests/test_engine_smoke.py::test_lpsim_real_binary_produces_people_csv`** — real-binary smoke test that mirrors the SUMO and MATSim smoke tests. Skips gracefully on hosts without CUDA + LivingCity; runs end-to-end on Pitzer once `build_lpsim.sbatch` has staged the binary.
- **README + SETUP + doc/REPRODUCING + doc/PITZER**: explicit "Will LPSim run on my Mac?" answer (no — but the rest of the matrix is unaffected) plus a step-by-step "how to bump the pin" workflow.

### Added (Phase B — LPSim integration)

- **`adapters/lpsim/`** — full adapter package (`__init__.py`, `lpsim_adapter.py`, `cli.py`, `MAPPING.md`) targeting the LPSim B18 loader's exact column schemas:
  - `nodes.csv`: `osmid, x, y, highway, index`
  - `edges.csv`: `uniqueid, osmid_u, osmid_v, u, v, length, lanes, speed_mph` (with self-loop filter and m/s → mph conversion)
  - OD demand: `PERNO, origin, destination` (LPSim has no per-trip departure column; the canonical `departure_time_s` is intentionally dropped, with departures governed globally by `START_HR`/`END_HR` in the .ini)
  - `command_line_options.ini`: `[General]` section with the keys SimForge controls (`USE_CPU`, `USE_SP_ROUTING`, `NUM_PASSES`, `START_HR`, `END_HR`, `OD_DEMAND_FILENAME`, etc.)
  - Output parser handles `<NUM_PASSES>_people*.csv` and produces `mean_travel_time_s` / `p95_travel_time_s` / `completed_count` for the same KPI surface SUMO and MATSim use
  - Binary discovery: `LPSIM_BINARY` env var → `$HOME/lpsim/LivingCity/LivingCity` → `$HOME/lpsim/LivingCity` → `LivingCity` on `PATH`
  - Singularity fallback: `$HOME/lpsim/lpsim.sif` runs via `singularity exec --nv … LivingCity`
  - **No silent CPU fallback** — when no GPU binary is available the adapter records a clean `RunResult` failure with a build pointer, avoiding the QarSUMO bit-identical-fallback trap.
- **`tests/test_lpsim_adapter.py`** (39 tests) — covers helpers, all four writers (nodes/edges/demand/INI), determinism (byte-identical re-runs), end-to-end input prep on the bundled scenario, output parsing on synthetic `*_people.csv` fixtures, and binary discovery. No GPU required for the fast tier.
- **`cluster/jobs/build_lpsim.sbatch`** — one-time GPU-partition job that pulls the `yibo123/lpsim:cuda12.4` Docker image as a Singularity SIF (preferred, fast) or clones+builds LPSim from source (`make` under `LivingCity/`) and symlinks the binary to `$HOME/lpsim/LivingCity/LivingCity` where the adapter looks for it. Module-loads `gcc/13.2.0` + `cuda/12.6.2` per Pitzer's lmod conventions.
- **Engine registries widened** to include `lpsim` across `execution/runspec.py::KNOWN_ENGINES`, `execution/run_benchmark.py::supported_engines`, `run.py::ALL_ENGINES`, `evaluation/generate_plots.py::ENGINE_COLORS / KNOWN_ENGINES`, the engine tuples in `evaluation/analyze_benchmark.py` and `evaluation/compare_modes.py`. `help.py` lists LPSim alongside SUMO + MATSim.
- **Runspec entries** — `runspecs/stress_test.yaml` is now a 4-cell matrix (SUMO meso, SUMO micro, MATSim meso, LPSim meso); `benchmark_small.yaml` adds an LPSim row per scenario (12 entries / 60 invocations); `benchmark_large.yaml` adds an LPSim row per scenario (6 entries / 30 invocations). All cells use **N=5** repeats per advisor sign-off.
- **Cluster sbatches switched back to the GPU partition** — `cluster/jobs/benchmark_small.sbatch` and `benchmark_large.sbatch` now request `--partition=gpu --gres=gpu:v100:1` since LPSim needs CUDA. Pre-flight diagnostics surface whether the LPSim binary or Singularity image is present.

### Changed (Phase B follow-on)

- **N=5 across the matrix** — `stress_test.yaml`, `benchmark_small.yaml`, `benchmark_large.yaml` all bumped from N=3/2 to N=5. The 95 % CI half-width shrinks ~3.5× vs N=3 (t-factor 2.776 vs 4.303 on top of √(5/3) variance reduction), which is the precision the plan §3.5 commitments need.

### Removed

- **QarSUMO engine completely dropped** (Version_4 Phase A) — the plan listed QarSUMO as a 5th engine, but as of the 2026-04-26 audit no usable public source exists: LLNL/QarSUMO returns 404, QarSUMO/QarSUMO is an empty placeholder, and the Boulmakoul 2023 IEEE HPCS paper cited in the plan hasn't materialised into runnable code. The CPU-fallback path that shipped through Version_3 was bit-identical to standard SUMO meso, contributing no new comparison signal. Removed: `adapters/qarsumo/` package, `tests/test_qarsumo_adapter.py` (10 tests), `cluster/jobs/build_qarsumo.sbatch`, all `qarsumo` runspec entries (`stress_test.yaml`, `benchmark_small.yaml`, `benchmark_large.yaml`), engine registry membership in `execution/runspec.py` and `run.py`, dispatcher branches in `execution/run_benchmark.py`, plot/analyze engine tuples, and all doc references. The 3rd primary engine slot is now reserved for **LPSim** ([Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim), MIT, GPU-accelerated, Docker shipped) — see `todo.md` Phase B.

### Changed

- **`cluster/jobs/benchmark_small.sbatch` and `benchmark_large.sbatch` switched off the GPU partition** — without QarSUMO, no current engine needs CUDA. Both jobs now request `--partition=cpu`. Once LPSim lands in Version_4 Phase B, both will switch back to `--partition=gpu --gres=gpu:v100:1`.
- **`runspecs/stress_test.yaml`** is now a **3-cell matrix** (was 4): `chicago_1k_car × {SUMO meso, SUMO micro, MATSim meso}`.
- **`runspecs/benchmark_small.yaml`** is now **9 entries / ~24 invocations** (was 15 / ~42): SUMO meso+micro + MATSim meso per scenario, no QarSUMO.
- **`runspecs/benchmark_large.yaml`** is now **4 entries / ~10 invocations** (was 6 / ~16): SUMO meso + MATSim meso per scenario, no QarSUMO.

### Added

- **`todo.md`** — Version_4 roadmap with plan-vs-reality gap audit (engines, cities, loads, hardware, repeats, reproducibility, calibration, metrics, deliverables), advisor-approved scope adjustments, phased roadmap (A: foundation → B: LPSim → C: containers → D: optional → E: integration), and open questions for the next advisor meeting. Cross-references `a personal PDF` (December 2025) as the canonical source of truth.
- **`evaluation/metrics/confidence.py`** — 95 % confidence intervals on the mean via Student's t-distribution. Hard-coded t-critical table (df 1–30) with normal-distribution Z=1.960 fallback for df > 30 — no scipy dependency, math is auditable in the thesis appendix. Closes plan §3.5 commitment to "95 % CIs on every KPI". Tested in `tests/test_confidence.py` (11 tests covering edge cases and hand-computable references). Wired into:
  - `evaluation/analyze_benchmark.py` — `ScenarioStats` gains `ci95_runtime` / `ci95_travel_time` fields; Tables 5.1 / 5.2 add a `95% CI` column alongside the existing `Std`; LaTeX and Markdown table generators render `mean ± half-width` instead of bare means.
  - `evaluation/generate_plots.py` — `ScenarioMetrics` gains the same fields; error bars in Figs 5.1 (runtime), 5.3 (travel time), and 5.6 (micro vs meso) now show 95 % CIs instead of ±1σ. Figure titles updated to flag the change.

## [Pre-Version_4 history below]

## [Unreleased]

### Added

- **Hash-pinned local OSM ingest (`osm_data/`)** — SimForge no longer depends on the live Overpass API for the cities it ships. State-level Geofabrik PBF snapshots (Illinois 348 MB, New York 489 MB, California 1.3 GB) are pinned by SHA-256 + MD5 in `osm_data/manifest.json`.
- **`tools/download_osm.py`** — idempotent fetcher that downloads each manifest entry, verifies both hashes, and skips already-present files. Replaces the old per-scenario Overpass warm-up for the committed cities.
- **`pipeline/network/load_network_from_pbf.py`** — pyosmium `FileProcessor().with_locations()` + `BackReferenceWriter` pipeline that bbox-slices a state-level PBF into an `.osm.xml` fragment without materialising the whole file, then hands it to `osmnx.graph_from_xml`.
- **`doc/PITZER.md`** — new end-to-end guide for the OSC Pitzer supercomputer workflow: account setup, module loads, filesystem layout, PBF / ModelGen rsync, `srun` vs. `sbatch` templates per generation tier, job monitoring (`squeue` / `sacct`), QarSUMO GPU build, and troubleshooting.
- **`pyproject.toml`** with `[tool.pytest.ini_options]`: `testpaths`, `--strict-markers`, `--strict-config`, `--tb=short`, and a registered marker set (`slow`, `integration`, `determinism`, `requires_sumo`, `requires_java`, `requires_gpu`). Now also carries `[tool.coverage.run]` / `[tool.coverage.report]` / `[tool.coverage.xml]` (branch coverage, `source = [adapters, evaluation, pipeline]`, renderers + data-dependent modules in `omit`) and `[tool.mutmut]` (mutation-testing scope pinned to the two cross-engine-fairness modules).
- **`tests/conftest.py`** with shared fixtures (`bundled_scenario`, `all_bundled_scenarios`, `small_bundled_scenarios`, `repo_root`) and helpers (`file_sha256`, `directory_sha256`, `is_arm64_netconvert_crash`, `is_large_scenario`, `warn_skipped`). Eliminates the `_CANDIDATES` scenario-discovery duplication that was sitting in five test files.
- **`tests/test_scc.py`** (16 tests) — covers `pipeline/network/scc.py` (iterative Kosaraju + parsing) including a 5 000-node deep-chain test that would blow the recursive form's stack.
- **`tests/test_feasibility.py`** (16 tests) — covers `adapters/common/feasibility.py`, the shared SCC-based trip filter that was the [1.0.0] cross-engine fairness fix. Exercises all four drop reasons (outside-SCC, unknown-node, missing-fields, missing-column), `FeasibilityReport` math, JSON persistence, log-level routing, manifest path resolution, and end-to-end ≥99 % feasibility on bundled scenarios.
- **`tests/test_analyze_benchmark.py`** (25 tests — up from 16) — now also exercises every renderer (`print_runtime_table`, `print_reproducibility_table`, `print_summary_table`, `print_coverage_report` asymmetric + thin-cell detection, `generate_latex_table`, `generate_markdown_table`) alongside the original mode-aware grouping + `_resolve_identity` fallback coverage.
- **`tests/test_osm_fetch.py`** (20 tests) — fully mocked Overpass/osmnx pipeline: `BoundingBox` validation (inverted lat/lon, `from_string` arity, `from_center` geometry), cache folder pinning to `<repo>/cache`, error translation (`ConnectionError → RuntimeError` with a "possible causes" block), empty-result guard (`ValueError`), missing-osmnx guard (`ImportError`), the `PREDEFINED_CITIES` catalogue, and full `build_network_from_osm` end-to-end against a duck-typed stub graph.
- **`tests/test_demand_generators.py`** (21 tests) — `UniformRandomGenerator`, `GravityModelGenerator`, `PeakHourGenerator`, `load_network_for_demand`, and the `generate_synthetic_demand` dispatch. Proves SCC restriction on synthetic grids (dead-end nodes excluded from OD sampling), deterministic seeding (byte-identical `demand.csv` across runs), canonical CSV header, and the peak-hour temporal profile.
- **`tests/test_engine_smoke.py`** (4 tests) — real-binary smoke for `sumo`, `netconvert`, and the MATSim JAR on the bundled scenario; asserts the engine produced non-empty artefacts (`tripinfo.xml`, `output_trips.csv.gz`). Skip-gracefully via `shutil.which()` + `check_java_available()` + `find_matsim_jar()` so `pytest -m "not slow"` stays green on a dev laptop without SUMO/Java installed.
- **`requirements-dev.txt`** — pins `pytest>=7.0`, `pytest-cov>=4.1`, `pytest-xdist>=3.5`, `mutmut>=2.5,<3` on top of the runtime requirements.
- **`doc/MUTATION_BASELINE.md`** — documents the `mutmut` scope (only `adapters/common/feasibility.py` + `pipeline/network/scc.py`, since those are the two modules that make cross-engine comparison *fair*), the narrow runner, the baseline table (populated on first run), and the surviving-mutant review checklist.
- **Schedule-aware demand generation (cityscape ScheduleGenerator integration).** `pipeline/demand/parse_model_file.py` now extracts the trailing `(...)` activity-schedule field on `per` records (added by [raodj/cityscape Schedule-generator branch](https://github.com/raodj/cityscape/tree/Schedule-generator)) into a `Person.schedule: list[ScheduleActivity]`. `pipeline/demand/generate_census_demand.py` flips the per-trip sampler to a **schedule-first hybrid**: persons whose cityscape schedule resolves to a valid (home, workplace) pair inside the bbox + SCC contribute a *real PUMS-derived OD trip* (origin = household home building, destination = `schedule[0].bld_id` workplace, both snapped through the existing building→node mapping). Persons without a usable schedule fall through to the original gravity sampler, which is unchanged. New `dest_source` column in `demand.csv` records `schedule` or `gravity` per trip; new `demand_provenance` block in `generation_metadata.json` reports per-bundle counts and fallback reasons. Adapters consume the canonical 5-column subset of `demand.csv` by name and ignore the extra column. Wall-clock impact is large for high-trip tiers — the gravity loop's O(num_trips × destination_nodes) cost disappears for the schedule-driven fraction (estimated ~99 % drop in Step 4 wall-clock for NYC-500K).
- **`tests/test_parse_model_file.py`** (10 tests) — covers the schedule-tuple regex (`_parse_schedule`), the per-line parser's quoted-field recovery (`_parse_person_line`), and the new `ModelData.home_bld_by_per_id` index that backs schedule-aware home resolution. Includes a regression test for the PUMS SERIALNO replication case (multiple synthesised households share one SERIALNO; each person must resolve to the *specific* household whose `person_ids` list names them).
- **`tests/test_scenario_data_integrity.py::test_dest_source_values_when_column_present`** — when the `dest_source` provenance column is present in `demand.csv`, every value must be in `{schedule, gravity}`. Skips on legacy bundles that predate the column.
- **Per-bundle toolchain capture in `generation_metadata.json`.** New `toolchain` block records `python`, `platform`, `osmnx`, `numpy`, `networkx`, `lxml`, `shapely`, `osmium`, `geopandas`, `pandas` versions for every bundle. Cross-machine reproducibility audits no longer have to guess at which dep stack produced a bundle.
- **Cross-platform reproducibility verified.** Generation produces byte-identical `demand.csv` and `signals.xml` across (Apple Silicon ARM64, macOS, Python 3.13.2, osmnx 2.0.7) and (x86_64, RHEL Pitzer, Python 3.12.4, osmnx 2.1.0) on the `la_50k_car` reference bundle. The `network.xml` MD5 differs only in lxml-version-dependent serialization (attribute ordering, float-precision rendering); semantic content is identical, as proven by both downstream artefacts being byte-equal. Verification recipe and reference MD5s in [`doc/REPRODUCING.md`](doc/REPRODUCING.md#cross-platform-reproducibility-verified); thesis-grade claim in [`doc/chapters/methods.md`](doc/chapters/methods.md) §3.7.2.
- **`requirements.lock` — exact dep + Python pin via uv.** Captures the canonical thesis-build environment as `pkg==X.Y.Z` for every transitive (42 packages including SUMO, see below). Combined with `uv venv --python 3.13` to install Python 3.13.13 in user-space, the lockfile guarantees that any machine — laptop, fresh CI runner, Pitzer compute node — ends up on byte-identical Python + dep versions. The previous loose-pin `requirements.txt` is retained for development but `requirements.lock` is the canonical install path going forward (referenced from README, SETUP, REPRODUCING, and PITZER docs).
- **`eclipse-sumo==1.26.0` bundled in `requirements.lock`.** SUMO is now a Python package install — `uv pip install -r requirements.lock` lands `sumo`, `netconvert`, and `sumo-gui` directly into `.venv/bin/` on both macOS arm64 and Linux x86_64. No more `brew install sumo` (broken on the dlr-ts tap as of 2026-04) or per-cluster module wrangling. Same wheel + version on every platform → cross-machine SUMO output reproducibility.
- **`tools/env_report.py`** — single-command toolchain audit: prints Python version + platform + executable path, all 12 watched Python dep versions, SUMO/netconvert/Java binary versions, and counts of OSM PBFs / ModelGen files / scenarios. Designed for cross-machine parity verification — run on each end and `diff` the outputs.
- **`cluster/jobs/{01_quick_test,02_small_commute,03_medium_multimodal,04_large_full_day,05_stress_test}.sbatch`** — five ready-to-submit per-tier sbatch templates matching `scripts/01..05.py`. Each is sized appropriately for its tier (4–8 cores, 8–64 GB, 30 min – 8 h) and uses the `logs/` subdir convention. Replaces the single tier-specific `gen_nyc_500k.sbatch` (which is preserved as the historical recorded-run artifact for `JobID 47063986`).
- **Three reference scenario bundles tracked in git.** `chicago_1k_car` (~1 MB, original test fixture), `nyc_10k_car` (~36 MB, small commute tier), and `la_50k_car` (~164 MB, multi-modal medium tier and the cross-platform reproducibility reference) are now committed. A fresh clone runs the full test suite and the bundled adapters without first generating data. The 200K and 500K tiers stay untracked — their `network.xml` / `signals.xml` files individually exceed GitHub's 100 MB hard limit.

### Changed

- **Network generation default flipped to PBF.** `pipeline/network/build_network_from_osm.py` now looks up `osm_data/manifest.json` first and dispatches to `load_network_from_pbf.py` when a covering PBF is present; the live Overpass path is reached only when no local file covers the bbox. `generate.py` hard-fails with a pointer to `tools/download_osm.py` if a committed city is requested but its PBF is absent.
- **osmnx 2.x required.** `requirements.txt` now pins `osmnx>=2.0,<3` and `pipeline/network/load_network_from_pbf.py` calls `truncate_graph_bbox` only with the v2.x positional `bbox=(W, S, E, N)` tuple. The 1.9.x compat branch (`north=/south=/east=/west=` kwargs) is gone — clean reinstalls and Pitzer envs need `pip install -U "osmnx>=2.0,<3"` before re-running generation. The `geopandas` pin is bumped to `>=1.0,<2` to satisfy osmnx 2.x's transitive requirement (`geopandas>=1.0.1`); the previous `>=0.9,<1` would break `pip install -r requirements.txt` against the new osmnx range. SimForge code does not import geopandas directly.
- **`requirements.txt`** now declares `osmium>=4.0` (pyosmium) explicitly and documents Overpass as fallback-only in an inline comment.
- **All test files refactored** to use shared `bundled_scenario` / `small_bundled_scenarios` fixtures instead of duplicating the scenario-discovery preamble. Suite-wide adapter sweeps now carry `@pytest.mark.slow` / `@pytest.mark.requires_sumo` so contributors can run the fast tier with `pytest -m "not slow"`.
- **`tests/test_scalability_metrics.py`** — `test_timer_measures_time` no longer relies on a hard-coded 0.05–0.30 s window; it now compares against a `time.monotonic()` reference, removing host-load flakiness.
- **`TESTING.md`** rewritten to document the 17-file / 293-test layout, the coverage summary (76.3 % line coverage; 70 % floor), and the run-command catalogue (full / fast / slow / by-marker / coverage / parallel / mutmut).

### Fixed

- **NYC 500 K generation unblocked** — the previous Overpass path timed out on the full NYC bbox and the alternative (splitting the bbox across multiple Overpass queries) produced non-deterministic topology between runs. The PBF slice is both faster and byte-reproducible.
- **MATSim 15.0 download URL** corrected in `setup_simforge.py`; the old release asset URL had been superseded on GitHub and caused a silent 404 → zero-byte JAR on fresh clones.
- **Test count reconciled to 249.** Removing the redundant `nyc_1k_car`, `la_1k_car`, and three synthetic bundles shrank the parametrised suite in `tests/test_scenario_data_integrity.py` (70 → 35) and `tests/test_scc.py` (16 → 14). Docs across `README.md`, `SETUP.md`, `TESTING.md`, `CONTRIBUTING.md`, `help.py`, and the thesis chapters now consistently report **249 tests** (previously 293).
- **Degenerate zero-length edges filtered at extract time.** `extract_canonical_network` in `pipeline/network/build_network_from_osm.py` now drops edges with `length <= 0` (logged via `logger.warning` with `osmid`/`highway` for traceability) and reports the skipped count in the summary line. Surfaced by `tests/test_scenario_data_integrity.py::test_link_lengths_are_positive` against the NYC-500K bundle, which contained 2 such edges out of 1.3 M from a single OSM way (`1351901326`) whose endpoint nodes shared identical coordinates. SUMO would warn and MATSim would emit teleport routes on these edges; filtering at the canonical extract is the right fix.

---

## [1.1.0] — 2026-04-19

Plot polish, coverage diagnostics, and cache hygiene. Commit `537ae75`.

### Added

- **Coverage diagnostic** in `evaluation/analyze_benchmark.py` (`print_coverage_report`) — flags low-sample cells (`n < 3`), asymmetric coverage across scenarios, and silently-failed cells.
- **`tools/clean.sh`** — wipes Python bytecode (`__pycache__`, `*.pyc`, `.pytest_cache`); `--all` also drops `cache/` (OSM Overpass HTTP cache).
- **Per-bar error bars** confirmed on Figs 5.1 and 5.3 (`yerr=errs, capsize=3`) for cross-engine variance disclosure.

### Changed

- **`runspecs/stress_test.yaml`** now declares the full 8-cell matrix (2 scenarios × {SUMO meso, SUMO micro, QarSUMO meso, MATSim meso}); previously NYC was missing `qarsumo/meso` and `sumo/micro`.
- **Plot save signature** simplified: folded redundant `_save(fig, name, dir)` into `_save(name, dir)` across all 9 figure functions; cleaned up Pylance warnings.

### Removed

- **Fig 5.10 (travel-time spread)** — duplicated information already shown in Fig 5.7 (runtime variability boxplot).

### Fixed

- **`.gitignore`** now covers `.modelgen_cache.json` (per-machine fingerprints — kept causing diff churn). Verified no stray `.DS_Store` files were tracked.

---

## [1.0.0] — 2026-04-18

First end-to-end-correct release: SCC-aware demand, mode-aware analysis, fair cross-engine comparison, unified result schema. Commits `e508d5c`, `cd16a52`, `ac7e483`.

### Added

- **`pipeline/network/scc.py`** — single canonical iterative-Kosaraju + network parser. Used by both demand generators and the adapter-layer post-condition feasibility check.
- **`adapters/common/feasibility.py`** — `feasible_trip_ids(network_path, demand_path)` builds the SCC once and returns the set of trip IDs whose origin AND destination both lie in it.
- **`feasibility_report.json`** — emitted next to every adapter's output, plus a WARNING line: `[sumo] feasibility: 1000/1000 trips (100.0%) — SCC covers 1204/1245 nodes, 2796/2856 links`.
- **`pipeline/network/warmup.py`** — walks `scenarios/*/`, reconstructs each bbox (preferring `generation_metadata.json`'s `city`+`radius_km` so it matches the original Overpass cache key), and forces a fetch through the same `download_osm_network` path used at scenario generation. A fresh clone can pre-warm everything with `python -m pipeline.network.warmup`.
- **OSM cold-start logging** — `download_osm_network()` logs a WARNING (`first-time fetch contacts the Overpass API and may take 10 s–2 min`) on cache miss, INFO (`cached OSM response found`) otherwise, with a `cache hit` / `fresh fetch` label after the call.

### Changed

- **Mode-aware analysis grouping**: `evaluation/analyze_benchmark.py` previously grouped by `(scenario, engine)`, collapsing SUMO meso (mean TT 204 s) and micro (mean TT 288 s) into one row. `_resolve_identity` now returns `(scenario, engine, mode)`; grouping key, `ScenarioStats` dataclass, and all output renderers (summary, runtime, reproducibility, LaTeX, Markdown) carry the mode column. (`generate_plots.py` and `compare_modes.py` already grouped by mode — only the analyze module was buggy.)
- **`pipeline/demand/generate_synthetic_demand.py`** replaced its single-source-BFS SCC approximation with `compute_largest_scc`.
- **`pipeline/demand/generate_census_demand.py`** restricts both origin sampling (residential buildings) and destination sampling (degree-weighted gravity) to SCC members; logs dropped-building count.
- **`adapters/common/feasibility.py`** delegates SCC computation to `pipeline.network.scc` — behaviour unchanged but no longer duplicated.
- **OSM cache pinned**: `pipeline/network/build_network_from_osm.py::_configure_osmnx_cache()` pins `ox.settings.cache_folder` to `<repo>/cache`.
- **Unified result schema**: `run.py` and `execution.run_benchmark` previously emitted slightly different JSON shapes; both code paths now write the same canonical schema. Downstream tools (`analyze_benchmark.py`, `generate_plots.py`, `compare_modes.py`) accept either source uniformly.

### Fixed

- **Engine input asymmetry**: SUMO and MATSim previously simulated *different subsets* of the same demand — SUMO silently dropped per-trip if origin/destination weren't reachable, while MATSim dropped trips whose nodes lay outside the largest strongly-connected component of its cleaned network. Result on `chicago_1k_car`: SUMO ran 988/1000 trips, MATSim ran 981/1000. Now SUMO, MATSim, and QarSUMO all consume the shared SCC filter — verified the per-engine skip lists are byte-identical and `feasibility_report.json` reports `feasible_trips == total_trips == 1000` on both bundles.
- **Inflated R-Score from mode collapse**: combining SUMO meso (TT ≈ 204 s) and micro (TT ≈ 288 s) into one row inflated combined std/mean and dropped the displayed R-Score to 0.8132 ("Poor") despite each individual mode scoring ≥ 0.997 ("Excellent"). Mode-aware grouping (above) restored correct per-mode scores.

---

## [0.9.0] — 2026-04-17

Initial end-to-end stress test: the first comprehensive run-through of the full pipeline (generate → validate → benchmark → analyse → plot). Surfaced the silent failure modes that `[1.0.0]` subsequently fixed, plus four concrete bugs. Commit `d06cf0a`.

### Fixed

- **`--validate-only` `AttributeError` on `Path`** — `run.py` now wraps `scenarios_available[s]["path"]` in `Path(...)`.
- **`test_all_scenarios` hangs on 50K+ scenarios** — added `_LARGE_PATTERNS` filter (`50k`, `200k`, `500k`, `5m`) to all four `test_*_all_scenarios` paths.
- **`RuntimeError` text-matching missed arm64 "crashed"** — tests now match both `"failed"` and `"crashed"` in error text.
- **`nyc_10k_car` arm64 netconvert crash** (4 041 nodes exceeded the ~3 000-node arm64 SUMO threshold) — regenerated with `--radius 2.5` (1 376 nodes).

### Outcome

- 184 unit tests passing.
- Full benchmark matrix 16/16 successful at the time (subsequently expanded to 22/22 in `[1.1.0]` after NYC qarsumo/micro cells were added to the runspec).
- Plots rendering cleanly; all error paths handled.

---

## [0.5.0] — 2026-04-15 → 2026-04-17

Foundation work prior to the first end-to-end stress test. Earlier per-commit detail is in `git log`; the key milestones:

### Added

- **Comprehensive test suite** (`ae4dcb2`) — now 184 tests across 11 files.
- **OSC Pitzer cluster scripts**, 500K jobs, cluster guide, HPC pin updates (`be20205`, `7ac0bb5`, `45188be`).
- **ModelGen integration** (`2315dde`) — PUMS census microdata for population-weighted demand.

### Changed

- **Thesis-defense documentation overhaul** (`e7e156d`, `6d98a7d`, `66f3d5f`) — architecture, scenario generation, methods/experiments chapters.

---

For per-commit detail beyond what's captured here, run `git log` on the `Version_2` branch.
