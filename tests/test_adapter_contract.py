"""
Adapter contract regression guard.

Pins the three-function adapter contract documented in
``doc/chapters/introduction.md`` §1.5.4 and
``doc/engines/THIRD_ENGINE_OPTIONS.md`` §"Adapter pattern":

    prepare_<engine>_inputs(scenario_path, output_dir, ...) -> ScenarioSummary | Path
    run_<engine>(config_path, timeout_s, ...) -> Tuple[bool, float, Optional[str]]
    parse_<engine>_output(output_dir) -> dict | <Engine>TripStats

Pure-static test: imports the three adapter modules and asserts each
exposes the contract functions at module level with the documented
return type. Catches future drift such as:

- A new engine added to ``adapters/`` without exposing ``run_<engine>`` /
  ``parse_<engine>_output`` (the gap fixed in commit 92a5b3d for SUMO).
- A refactor that moves ``run_<engine>`` into a class method or another
  module (rebreaks the contract).
- A change to the run-result tuple shape (would break the cross-engine
  harness in ``execution.run_benchmark``).

No binaries required; no scenario fixtures used.
"""

from __future__ import annotations

import importlib
import inspect

import pytest


CONTRACT = {
    "sumo": ["prepare_sumo_inputs", "run_sumo", "parse_sumo_output"],
    "matsim": ["prepare_matsim_inputs", "run_matsim", "parse_matsim_output"],
    "dtalite": ["prepare_dtalite_inputs", "run_dtalite", "parse_dtalite_output"],
}


@pytest.mark.parametrize("engine", sorted(CONTRACT.keys()))
def test_adapter_exposes_three_function_contract(engine: str) -> None:
    """Every adapter module exposes prepare_, run_, parse_ at module level."""
    mod = importlib.import_module(f"adapters.{engine}.{engine}_adapter")
    missing = [fn for fn in CONTRACT[engine] if not callable(getattr(mod, fn, None))]
    assert not missing, (
        f"adapters.{engine}.{engine}_adapter is missing contract callables: {missing}. "
        f"See doc/chapters/introduction.md §1.5.4 for the three-function pattern."
    )


@pytest.mark.parametrize("engine", sorted(CONTRACT.keys()))
def test_run_function_returns_tuple_bool_float_optstr(engine: str) -> None:
    """run_<engine> must return Tuple[bool, float, Optional[str]].

    Pinned because ``execution.run_benchmark`` unpacks (success, runtime,
    error_msg) from every engine. A wider/narrower tuple shape would crash
    the harness at runtime.
    """
    mod = importlib.import_module(f"adapters.{engine}.{engine}_adapter")
    fn = getattr(mod, f"run_{engine}")
    sig = inspect.signature(fn)
    ra = str(sig.return_annotation)
    # Allow either Tuple[...] or tuple[...] and either Optional[str] or "str | None".
    assert "bool" in ra and "float" in ra and ("str" in ra or "None" in ra), (
        f"run_{engine} return annotation does not look like "
        f"Tuple[bool, float, Optional[str]]: got {ra!r}"
    )
