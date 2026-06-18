# Mutation-testing baseline

`pytest` counts lines executed; `mutmut` counts *assertions that would have
caught a bug*.  This baseline focuses on the two modules that underpin the
`[1.0.0]` cross-engine fairness fix, `adapters/common/feasibility.py` and
`pipeline/network/scc.py`.  If either grows undetected logic drift, the
mutation score here will fall before the line-coverage number moves.

## Scope

Only the two modules above are mutated.  Mutation testing on the full
SimForge codebase would take hours per run; mutating the thin critical path
that every adapter depends on takes seconds and catches the failure modes
we actually care about (SCC-filter bypass, inverted comparison, off-by-one
on the reachability check).

Configuration is in `pyproject.toml` under `[tool.mutmut]`:

```toml
paths_to_mutate = "adapters/common/feasibility.py,pipeline/network/scc.py"
tests_dir = "tests/"
runner = "python -m pytest -x -q tests/test_feasibility.py tests/test_scc.py"
```

## Running

```bash
pip install -r requirements-dev.txt   # installs mutmut
mutmut run                            # ~30–90 s on the two targeted modules
mutmut results                        # summary of killed / survived / timeout
mutmut show <id>                      # inspect a surviving mutant
```

The `runner` command is intentionally narrow (`test_feasibility` +
`test_scc` only): mutmut re-invokes it once per generated mutant, so
running the full 260-test suite per mutant would take over an hour.  The
two targeted test files assert every observable contract of the two
modules, so the coverage gap is small.

## Baseline (measured 2026-06-18)

Run with `mutmut run` (mutmut 2.5.1) and the configuration above, against
the two targeted test files `test_feasibility` (19 tests) and `test_scc`
(14 tests). Score is killed / mutants generated.

| Module                              | Mutants generated | Killed | Survived | Score |
| ----------------------------------- | ----------------- | ------ | -------- | ----- |
| `adapters/common/feasibility.py`    | 140               | 108    | 32       | 77.1% |
| `pipeline/network/scc.py`           | 62                | 51     | 11       | 82.3% |
| **Combined**                        | **202**           | **159** | **43**  | **78.7%** |

`scc.py`'s 51 includes one mutant caught by timeout (an induced infinite
loop) rather than by a failing assertion; `feasibility.py` had none. The 43
surviving mutants mark assertions worth strengthening (or equivalent
mutants worth justifying); review them with the checklist below.

> Re-run and update this table whenever either module changes. Surviving
> mutants should either be killed by a new test assertion or justified here
> (e.g. equivalent mutants that don't change behaviour).

## Surviving-mutant review checklist

For each surviving mutant:

1. `mutmut show <id>`, see the diff.
2. Ask: would this change any observable behaviour?
   - **Yes** → add or strengthen a test assertion, re-run.
   - **No** (equivalent mutant, e.g. `<=` vs `<` where the boundary is
     unreachable) → note it here with one sentence of justification.

## Why this module set

The `[1.0.0]` release notes call out two regressions that survived the
unit-test suite and shipped to users:

- **Engine input asymmetry**: SUMO silently dropped unroutable trips on a
  per-trip basis; MATSim pre-filtered by SCC.  Both engines then "ran
  different subsets" of the nominal demand and produced incomparable
  metrics.  The fix: one shared `feasible_trip_ids()` function.
- **Inflated R-score from mode collapse**: the benchmark analyser lumped
  SUMO meso + SUMO micro into a single row, inflating the combined
  coefficient of variation.  The fix lives in `evaluation/analyze_benchmark.py`
  (covered by dedicated tests rather than mutation, since its output is
  textual rather than behavioural).

Mutation testing the two modules that ended that class of bug is a
high-signal check that the fix doesn't silently regress.
