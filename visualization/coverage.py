"""Data discovery + coverage matrix.

Before any rendering happens, the visualizer scans what's on disk and
reports which maps are generatable. The user can ``--dry-run`` to see
this matrix without producing any PNGs, then re-invoke with the
``--maps`` they want.

The discovery is intentionally loose: missing data is not an error,
it just means certain maps are unavailable. A bundle-only setup
(no benchmark runs) can still produce ``od_origins`` / ``od_destinations``;
post-simulation maps require successful per-cell artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from visualization.data.bundle import bundle_paths


# All known map types. All seven are implemented; this tuple also drives
# the dry-run availability matrix, which reports each one's "generatable
# when" criteria against the data actually on disk.
ALL_MAP_TYPES: tuple[str, ...] = (
    "od_origins",        # Phase A: bundle only
    "od_destinations",   # Phase A: bundle only
    "link_load",         # Phase B: needs successful engine cells
    "travel_time",       # Phase B: needs successful engine cells
    "congestion",        # Phase B: needs successful engine cells
    "route_diversity",   # Phase C: needs >= 2 engines
    "animated_flow",     # Phase C: needs event-level engine output
)

# Engines we expect to find under runs/<runspec>/<scenario>/.
KNOWN_ENGINES: tuple[str, ...] = ("sumo", "matsim", "dtalite")
KNOWN_MODES: tuple[str, ...] = ("meso", "micro")


@dataclass
class CellArtifacts:
    """What's on disk for a single (engine, mode, seed) cell."""

    engine: str
    mode: str
    seed: int
    cell_dir: Path
    has_tripinfo: bool = False              # SUMO only
    has_matsim_trips: bool = False          # MATSim output_trips.csv.gz
    has_dtalite_link_perf: bool = False     # DTALite link_performance.csv
    has_event_output: bool = False          # MATSim events.xml.gz (only engine with the event stream)

    @property
    def has_any_output(self) -> bool:
        return (
            self.has_tripinfo
            or self.has_matsim_trips
            or self.has_dtalite_link_perf
        )


@dataclass
class ScenarioCoverage:
    """What data is available for a single scenario."""

    scenario_id: str
    bundle_dir: Path | None = None
    bundle_files: dict[str, Path] = field(default_factory=dict)
    cells: list[CellArtifacts] = field(default_factory=list)

    @property
    def has_bundle(self) -> bool:
        return "network" in self.bundle_files and "demand" in self.bundle_files

    @property
    def engines_with_results(self) -> set[str]:
        return {c.engine for c in self.cells if c.has_any_output}

    @property
    def has_event_output(self) -> bool:
        return any(c.has_event_output for c in self.cells)

    def map_generatable(self, map_type: str) -> tuple[bool, str]:
        """Return ``(generatable, reason)`` for a given map_type."""
        if map_type in ("od_origins", "od_destinations"):
            if self.has_bundle:
                return True, f"bundle present ({len(self.bundle_files)} files)"
            return False, "missing network.xml or demand.csv in bundle"
        if map_type in ("link_load", "travel_time", "congestion"):
            if self.engines_with_results:
                return True, f"engines with results: {sorted(self.engines_with_results)}"
            return False, "no engine cells with output on disk"
        if map_type == "route_diversity":
            n = len(self.engines_with_results)
            if n >= 2:
                return True, f"{n} engines with results"
            return False, f"need >= 2 engines, found {n}"
        if map_type == "animated_flow":
            if self.has_event_output:
                return True, "event-level output present"
            return False, "no event-level engine output (e.g. MATSim events.xml.gz)"
        return False, f"unknown map type: {map_type}"


def discover_bundle(bundle_dir: Path, scenario_id: str | None = None) -> ScenarioCoverage:
    """Scan a bundle directory and return what's there."""
    coverage = ScenarioCoverage(
        scenario_id=scenario_id or bundle_dir.name,
        bundle_dir=bundle_dir if bundle_dir.is_dir() else None,
    )
    if coverage.bundle_dir:
        coverage.bundle_files = bundle_paths(coverage.bundle_dir)
    return coverage


def discover_run_cells(run_dir: Path, coverage: ScenarioCoverage) -> ScenarioCoverage:
    """Append ``CellArtifacts`` entries for any per-cell output dirs found.

    Walks ``run_dir / <engine> / <mode> / seed_*/`` (Phase 12.2 layout).
    A missing run_dir isn't an error; it just leaves cells empty.
    """
    if not run_dir.is_dir():
        return coverage
    for engine in KNOWN_ENGINES:
        engine_dir = run_dir / engine
        if not engine_dir.is_dir():
            continue
        for mode_dir in engine_dir.iterdir():
            if not mode_dir.is_dir() or mode_dir.name not in KNOWN_MODES:
                continue
            for seed_dir in sorted(mode_dir.iterdir()):
                if not seed_dir.is_dir() or not seed_dir.name.startswith("seed_"):
                    continue
                try:
                    seed_n = int(seed_dir.name.removeprefix("seed_"))
                except ValueError:
                    continue
                cell = CellArtifacts(
                    engine=engine,
                    mode=mode_dir.name,
                    seed=seed_n,
                    cell_dir=seed_dir,
                    has_tripinfo=(seed_dir / "tripinfo.xml").is_file(),
                    has_matsim_trips=(seed_dir / "output" / "output_trips.csv.gz").is_file(),
                    has_dtalite_link_perf=(seed_dir / "link_performance.csv").is_file(),
                    has_event_output=(
                        (seed_dir / "output" / "output_events.xml.gz").is_file()
                        or (seed_dir / "events.xml.gz").is_file()
                    ),
                )
                coverage.cells.append(cell)
    return coverage


def format_coverage_matrix(coverage: ScenarioCoverage) -> str:
    """Render the coverage matrix as a paste-friendly multi-line string."""
    lines: list[str] = []
    lines.append(f"Scenario:  {coverage.scenario_id}")
    if coverage.has_bundle:
        bundle_summary = ", ".join(sorted(coverage.bundle_files.keys()))
        lines.append(f"Bundle:    [OK]    {coverage.bundle_dir}  ({bundle_summary})")
    else:
        lines.append(f"Bundle:    [MISS]  {coverage.bundle_dir} -- network or demand missing")

    if coverage.cells:
        per_engine_seeds: dict[tuple[str, str], list[int]] = {}
        for c in coverage.cells:
            if c.has_any_output:
                per_engine_seeds.setdefault((c.engine, c.mode), []).append(c.seed)
        if per_engine_seeds:
            for (engine, mode), seeds in sorted(per_engine_seeds.items()):
                lines.append(f"Cells:     [OK]    {engine}/{mode}  seeds={sorted(seeds)}")
        else:
            lines.append("Cells:     [EMPTY] run dir scanned, no per-cell output found")
    else:
        lines.append("Cells:     (none -- no run dir provided or empty)")

    lines.append("")
    lines.append("Available maps:")
    for map_type in ALL_MAP_TYPES:
        ok, reason = coverage.map_generatable(map_type)
        marker = "[OK]" if ok else "[--]"
        lines.append(f"  {marker}  {map_type:<20s}  ({reason})")
    return "\n".join(lines)
