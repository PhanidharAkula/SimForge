#!/usr/bin/env python3
"""
SimForge Unified Scenario Generator

Generate fully customizable canonical scenario bundles using census
(ModelGen) data as the default demand source.

Users can specify any combination of: city, trip count, time window,
travel modes, network radius, and random seed.

Usage:
  # Basic: 5K car trips in Chicago, 1-hour window (census default)
  python generate.py --city chicago --trips 5000

  # Custom: 200K mixed-mode trips, morning rush
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400

  # Full control
  python generate.py --city nyc --trips 170000 --modes car \\
         --start-time 0 --end-time 86400 --radius 5.0 --seed 123

  # Use a preset configuration
  python generate.py --preset morning_rush

  # Use synthetic demand (fallback if no model file)
  python generate.py --city chicago --trips 5000 --synthetic

  # List presets and cities
  python generate.py --list
"""

import argparse
import importlib
import json
import math
import platform
import shutil
import sys
import time
import logging
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.network.build_network_from_osm import build_network_from_osm, BoundingBox
from pipeline.demand.generate_synthetic_demand import generate_synthetic_demand
from pipeline.demand.generate_census_demand import generate_census_demand
from pipeline.demand.parse_model_file import parse_model_file
from pipeline.signals.build_signals_default import build_signals_default
from pipeline.modelgen_scanner import scan_modelgen_dir

# force=True + explicit stream because library modules under pipeline/ call
# basicConfig at import time; without force this entry-point config would be a
# no-op and logs would land on stderr (SLURM .err) instead of stdout (.out).
# Default level is WARNING so the user-facing print() banners aren't drowned
# in pipeline INFO chatter (osmnx, demand, signals). Pass --verbose on the
# CLI to restore INFO and see the firehose for debugging.
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger(__name__)


def _fmt_dur(seconds: float) -> str:
    """Format a duration as Xs / Xm YYs / Xh YYm YYs for human consumption."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


# ---------------------------------------------------------------------------
# Sticky progress bar with optional heartbeat thread.
# Pattern matches run.py: TTY-only, two-line erase (bar + blank above),
# cyan/dim ━/─ box-drawing fill. Plus a background thread that re-renders
# the bar every second so long-running steps (60+s OSM extraction, 30+s
# demand generation) don't look like the script is frozen.
# ---------------------------------------------------------------------------

import threading

_TOTAL_STEPS = 4
_BAR_FILL = "\033[1;36m"
_BAR_EMPTY = "\033[2m"
_BAR_RESET = "\033[0m"
# Braille spinner — 10 frames cycling once per second so the operator can
# see motion even when a single step takes 60+ seconds (OSM extraction,
# demand generation) with no internal progress signal to drive the bar
# forward.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _StepProgress:
    """Single-line progress bar that re-renders every second on a TTY."""

    def __init__(self, total_steps: int):
        self.total = total_steps
        self.completed = 0
        self.current_label = ""
        self.t0 = time.time()
        self.is_tty = sys.stdout.isatty()
        self._drawn = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick = 0  # spinner frame counter

    # ---- public API --------------------------------------------------
    def start(self) -> None:
        """Spawn the heartbeat thread (no-op on non-TTY)."""
        if not self.is_tty:
            return
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def begin_step(self, label: str) -> None:
        """Record the label of the step currently in progress."""
        self.current_label = label
        self._render()

    def complete_step(self) -> None:
        """Mark the current step as finished and bump the count."""
        self.completed += 1
        self._render()

    def stop(self) -> None:
        """Halt the heartbeat thread and erase the bar."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._erase()

    def print_above(self, line: str) -> None:
        """Print a line that should appear ABOVE the sticky bar.
        Erases the bar first so the line lands cleanly, then re-renders."""
        if self.is_tty:
            self._erase()
        print(line)
        if self.is_tty:
            self._render()

    # ---- rendering ---------------------------------------------------
    def _heartbeat(self) -> None:
        # Cycle the spinner ~5x per second so the motion is obvious but
        # the redraw rate stays modest.
        while not self._stop.is_set():
            if self.is_tty:
                self._tick += 1
                self._render()
            self._stop.wait(0.2)

    def _render(self) -> None:
        if not self.is_tty:
            return
        if self._drawn:
            sys.stdout.write("\r\033[K\033[1A\r\033[K")
        bar_len = 32
        elapsed = time.time() - self.t0
        progress = self.completed
        pct = 100.0 * progress / max(self.total, 1)
        filled = int(bar_len * progress / max(self.total, 1))
        bar = (_BAR_FILL + ("━" * filled) + _BAR_RESET
               + _BAR_EMPTY + ("─" * (bar_len - filled)) + _BAR_RESET)
        if progress > 0 and progress < self.total:
            eta = (elapsed / progress) * (self.total - progress)
            eta_s = _fmt_dur(eta)
        elif progress >= self.total:
            eta_s = "0s"
        else:
            eta_s = "--"
        label = self.current_label or "..."
        # Spinner: cyan-bold so it stands out; freeze on ✓ once all steps done
        if progress >= self.total:
            spinner = _BAR_FILL + "✓" + _BAR_RESET
        else:
            spinner = _BAR_FILL + _SPINNER_FRAMES[self._tick % len(_SPINNER_FRAMES)] + _BAR_RESET
        sys.stdout.write(
            "\n  " + bar
            + f"  {spinner}  {pct:5.1f}%  "
            + f"step {min(progress + 1, self.total)}/{self.total}: {label}  "
            + f"elapsed {_fmt_dur(elapsed)}  ETA {eta_s}"
        )
        sys.stdout.flush()
        self._drawn = True

    def _erase(self) -> None:
        if not self.is_tty or not self._drawn:
            return
        sys.stdout.write("\r\033[K\033[1A\r\033[K")
        sys.stdout.flush()
        self._drawn = False


# =============================================================================
# Toolchain capture — recorded into generation_metadata.json so any bundle
# carries the exact code+dep stack that produced it. Critical for cross-machine
# reproducibility audits — minor osmnx releases have observably altered network
# extraction in the past, so the bundle must say which version it was built on.
# =============================================================================

# (module name, distribution name) — the second is for importlib.metadata when
# the import-time __version__ attribute isn't exposed (pyosmium is the case).
_TOOLCHAIN_PACKAGES = (
    ("osmnx", "osmnx"),
    ("numpy", "numpy"),
    ("networkx", "networkx"),
    ("lxml", "lxml"),
    ("shapely", "shapely"),
    ("osmium", "osmium"),
    ("geopandas", "geopandas"),
    ("pandas", "pandas"),
)


def _toolchain_versions() -> dict[str, str]:
    """Snapshot of dep versions for the metadata record. Tries the module's
    ``__version__`` first, then falls back to ``importlib.metadata.version``
    so packages that don't expose ``__version__`` (e.g. pyosmium) still
    report their installed version."""
    from importlib import metadata as _md
    versions: dict[str, str] = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
    }
    for mod_name, dist_name in _TOOLCHAIN_PACKAGES:
        ver: str
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "")
        except ImportError:
            versions[mod_name] = "not installed"
            continue
        if not ver:
            try:
                ver = _md.version(dist_name)
            except _md.PackageNotFoundError:
                ver = "unknown"
        versions[mod_name] = ver
    return versions


# =============================================================================
# CITY REGISTRY
# =============================================================================

CITIES = {
    "chicago": {
        "name": "Chicago, IL",
        "lat": 41.8781,
        "lon": -87.6298,
        "default_radius_km": 2.0,
        "model_file": "modelgen/chicago_model.txt",
        "pbf_file": "osm_data/illinois-2026-04-22.osm.pbf",
        "description": "Chicago urban core — The Loop and surrounding neighbourhoods",
    },
    "nyc": {
        "name": "New York City, NY",
        "lat": 40.7580,
        "lon": -73.9855,
        "default_radius_km": 2.0,
        "model_file": "modelgen/nyc_model.txt",
        "pbf_file": "osm_data/new-york-2026-04-22.osm.pbf",
        "description": "Manhattan Midtown and surrounding boroughs",
    },
    "la": {
        "name": "Los Angeles, CA",
        "lat": 34.0522,
        "lon": -118.2437,
        "default_radius_km": 5.0,
        "model_file": "modelgen/la_model.txt",
        "pbf_file": "osm_data/california-2026-04-22.osm.pbf",
        "description": "Downtown LA and surrounding urban area",
    },
}

# All supported travel modes
VALID_MODES = {"car", "transit", "bike", "walk"}


# =============================================================================
# PRESET CONFIGURATIONS
# =============================================================================

PRESETS = {
    "quick_test": {
        "description": "Quick test — 1K car trips, Chicago, 1-hour window",
        "city": "chicago",
        "trips": 1_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 28800,     # 8:00 AM
        "radius_km": 2.0,
        "seed": 42,
    },
    "small_commute": {
        "description": "Small commute — 10K car trips, NYC, 7–9 AM",
        "city": "nyc",
        "trips": 10_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 32400,     # 9:00 AM
        "radius_km": 4.0,
        "seed": 42,
    },
    "medium_multimodal": {
        "description": "Medium multi-modal — 50K trips (car+transit+bike), LA, 6–10 AM",
        "city": "la",
        "trips": 50_000,
        "modes": ["car", "transit", "bike"],
        "start_time": 21600,   # 6:00 AM
        "end_time": 36000,     # 10:00 AM
        "radius_km": 10.0,
        "seed": 42,
    },
    "large_full_day": {
        "description": "Large full-day — 200K car+transit trips, Chicago, 24-hour",
        "city": "chicago",
        "trips": 200_000,
        "modes": ["car", "transit"],
        "start_time": 0,
        "end_time": 86400,     # 24 hours
        "radius_km": 15.0,
        "seed": 42,
    },
    "stress_test": {
        "description": "Stress test — 500K car trips, NYC, 6–10 AM",
        "city": "nyc",
        "trips": 500_000,
        "modes": ["car"],
        "start_time": 21600,   # 6:00 AM
        "end_time": 36000,     # 10:00 AM
        "radius_km": 20.0,
        "seed": 42,
    },
}


# =============================================================================
# HELPERS
# =============================================================================

def _bbox_from_center(lat: float, lon: float, radius_km: float) -> BoundingBox:
    """Create a bounding box from a center point and radius."""
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return BoundingBox(
        north=lat + lat_delta,
        south=lat - lat_delta,
        east=lon + lon_delta,
        west=lon - lon_delta,
    )


def _seconds_to_hhmm(seconds: int) -> str:
    """Convert seconds since midnight to HH:MM format."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h:02d}:{m:02d}"


def _make_scenario_id(city: str, trips: int, modes: list[str]) -> str:
    """Generate a descriptive scenario ID."""
    # Compact trip count
    if trips >= 1_000_000:
        count_str = f"{trips // 1_000_000}m"
    elif trips >= 1_000:
        count_str = f"{trips // 1_000}k"
    else:
        count_str = str(trips)

    mode_str = "_".join(sorted(modes)) if len(modes) > 1 else modes[0]
    return f"{city}_{count_str}_{mode_str}"


def _write_config_xml(
    path: Path,
    scenario_id: str,
    description: str,
    horizon_start: int,
    horizon_end: int,
    seed: int,
) -> None:
    """Write canonical config.xml."""
    root = etree.Element("config")

    meta = etree.SubElement(root, "metadata")
    meta.set("scenario_id", scenario_id)
    meta.set("created_by", "simforge_generator")
    etree.SubElement(meta, "description").text = description

    t = etree.SubElement(root, "time")
    t.set("start_time_s", str(horizon_start))
    t.set("end_time_s", str(horizon_end))
    t.set("time_step_s", "1")

    r = etree.SubElement(root, "random")
    r.set("seed", str(seed))
    r.set("engine_seed_mode", "fixed")

    u = etree.SubElement(root, "units")
    u.set("length", "meters")
    u.set("speed", "m/s")
    u.set("time", "seconds")

    s = etree.SubElement(root, "simulation")
    s.set("warmup_time_s", "0")
    s.set("aggregation_interval_s", "300")

    etree.ElementTree(root).write(
        str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8",
    )


def _write_manifest_xml(path: Path, scenario_id: str) -> None:
    """Write canonical manifest.xml."""
    root = etree.Element("manifest", version="0.1")
    etree.SubElement(root, "scenario", id=scenario_id)

    cf = etree.SubElement(root, "canonical_files")
    for ftype, fname in [
        ("network", "network.xml"),
        ("demand", "demand.csv"),
        ("config", "config.xml"),
        ("signals", "signals.xml"),
    ]:
        etree.SubElement(cf, "file", type=ftype, path=fname)

    etree.ElementTree(root).write(
        str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8",
    )


# =============================================================================
# DISPLAY
# =============================================================================

def show_list():
    """Show available cities and presets with live census data."""
    # Get live census stats
    scan_data = scan_modelgen_dir()
    city_stats = scan_data.get("cities", {})

    print("\n" + "=" * 65)
    print("  SimForge — Available Cities & Presets")
    print("=" * 65)

    print("\n  SUPPORTED CITIES:")
    print("  " + "-" * 61)
    for key, city in CITIES.items():
        model_path = Path(__file__).parent / city["model_file"]
        has_model = model_path.exists()
        status = "census: YES" if has_model else "census: NO"
        print(f"    {key:<12} {city['name']:<25} {status}  "
              f"r={city['default_radius_km']}km")
        print(f"    {'':12} {city['description']}")
        if key in city_stats:
            stats = city_stats[key]
            car = stats['mode_counts'].get('car', 0)
            total = stats['commuters']
            print(f"    {'':12} Census: {car:,} car, {total:,} total commuters")
        print()

    print("  PRESETS (use --preset <name>):")
    print("  " + "-" * 61)
    for name, preset in PRESETS.items():
        modes_str = ",".join(preset["modes"])
        time_str = (f"{_seconds_to_hhmm(preset['start_time'])}"
                    f"–{_seconds_to_hhmm(preset['end_time'])}")
        print(f"    {name:<20} {preset['description']}")
        print(f"    {'':20} city={preset['city']}  trips={preset['trips']:,}  "
              f"modes={modes_str}  time={time_str}")
        print()

    print("  VALID MODES:", ", ".join(sorted(VALID_MODES)))
    print()
    print("  Tip: Run 'python help.py cities' for detailed census limits.")
    print("=" * 65 + "\n")


# =============================================================================
# MAIN GENERATION PIPELINE
# =============================================================================

def generate_scenario(
    city: str,
    trips: int,
    modes: list[str],
    start_time: int,
    end_time: int,
    radius_km: float,
    seed: int,
    output_dir: str | None = None,
    scenario_id: str | None = None,
    synthetic: bool = False,
    allow_oversample: bool = False,
) -> dict:
    """
    Generate a complete canonical scenario bundle.

    Args:
        city: City key (chicago, nyc, la).
        trips: Number of OD trips to generate.
        modes: List of travel modes (car, transit, bike, walk).
        start_time: Simulation start time in seconds from midnight.
        end_time: Simulation end time in seconds from midnight.
        radius_km: Network extraction radius in km.
        seed: Random seed for reproducibility.
        output_dir: Custom output directory. Default: scenarios/<scenario_id>/
        scenario_id: Custom scenario ID. Default: auto-generated.
        synthetic: Force synthetic demand instead of census.
        allow_oversample: Allow more trips than raw census commuters.

    Returns:
        Summary dict with generation results.
    """
    if city not in CITIES:
        raise ValueError(f"Unknown city: {city}. Available: {', '.join(CITIES)}")

    for m in modes:
        if m not in VALID_MODES:
            raise ValueError(f"Invalid mode: {m}. Valid: {', '.join(VALID_MODES)}")

    city_info = CITIES[city]

    # Resolve scenario ID and output path
    if scenario_id is None:
        scenario_id = _make_scenario_id(city, trips, modes)

    project_root = Path(__file__).parent
    if output_dir is not None:
        out = Path(output_dir)
    else:
        out = project_root / "scenarios" / scenario_id

    bbox = _bbox_from_center(city_info["lat"], city_info["lon"], radius_km)

    # Resolve model file
    model_path = project_root / city_info["model_file"]
    use_census = model_path.exists() and not synthetic

    if not use_census and not synthetic:
        logger.warning("Census model file not found: %s — falling back to synthetic",
                       model_path)

    # Time description
    time_desc = f"{_seconds_to_hhmm(start_time)}–{_seconds_to_hhmm(end_time)}"
    modes_desc = "+".join(modes)
    description = (f"{city_info['name']} — {trips:,} {modes_desc} trips, "
                   f"{time_desc}, r={radius_km}km")

    print("\n" + "=" * 60)
    print("  SimForge Scenario Generator")
    print("=" * 60)
    print("\n📊 CONFIGURATION:")
    print("-" * 60)
    print(f"  Scenario:   {scenario_id}")
    print(f"  City:       {city_info['name']}")
    print(f"  Trips:      {trips:,}")
    print(f"  Modes:      {', '.join(modes)}")
    print(f"  Time:       {time_desc} ({start_time}–{end_time} s)")
    print(f"  Radius:     {radius_km:.1f} km")
    print(f"  Seed:       {seed}")
    print(f"  Demand:     {'census (ModelGen)' if use_census else 'synthetic (gravity)'}")
    print(f"  Output:     {out}")
    print("-" * 60)
    print("\n" + "=" * 60)
    print("  Generation Pipeline")
    print("=" * 60)

    t0 = time.time()
    step_times: dict[str, float] = {}
    progress = _StepProgress(_TOTAL_STEPS)
    progress.start()

    # ---- 1. Network from OSM ----
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Resolve hash-pinned PBF for this city (required; see osm_data/manifest.json).
    pbf_rel = city_info.get("pbf_file")
    pbf_path = project_root / pbf_rel if pbf_rel else None
    if pbf_path is None or not pbf_path.exists():
        raise FileNotFoundError(
            f"OSM PBF required for city '{city}' but not found: {pbf_path}\n"
            f"  Download it with:  python tools/download_osm.py\n"
            f"  Provenance lives in osm_data/manifest.json (URL + SHA256)."
        )

    progress.print_above(f"\n▶ Step 1/4: OSM network ({radius_km:.1f} km radius)")
    progress.begin_step(f"OSM network ({radius_km:.1f} km)")
    t_step = time.time()
    net = build_network_from_osm(
        bbox, out / "network.xml", network_type="drive", pbf_path=pbf_path
    )
    step_times["Network"] = time.time() - t_step
    progress.print_above(f"  ✓ network.xml: {net['node_count']:,} nodes, "
                         f"{net['link_count']:,} links  ({_fmt_dur(step_times['Network'])})")
    progress.complete_step()

    # ---- 2. Signals ----
    progress.print_above("\n▶ Step 2/4: Traffic signals")
    progress.begin_step("Traffic signals")
    t_step = time.time()
    sig = build_signals_default(
        network_path=out / "network.xml",
        output_path=out / "signals.xml",
        min_degree=4,
    )
    step_times["Signals"] = time.time() - t_step
    progress.print_above(f"  ✓ signals.xml: {sig['signal_count']:,} controllers  "
                         f"({_fmt_dur(step_times['Signals'])})")
    progress.complete_step()

    # ---- 3. Config / Manifest ----
    progress.print_above("\n▶ Step 3/4: Config + manifest")
    progress.begin_step("Config + manifest")
    t_step = time.time()
    _write_config_xml(out / "config.xml", scenario_id, description,
                      start_time, end_time, seed)
    _write_manifest_xml(out / "manifest.xml", scenario_id)
    step_times["Config"] = time.time() - t_step
    progress.print_above(f"  ✓ config.xml + manifest.xml  ({_fmt_dur(step_times['Config'])})")
    progress.complete_step()

    # ---- 4. Demand ----
    demand_label = "census (ModelGen)" if use_census else "synthetic (gravity)"
    progress.print_above(f"\n▶ Step 4/4: Demand ({demand_label})")
    progress.begin_step(f"Demand ({demand_label})")
    t_step = time.time()
    if use_census:
        multi_mode = len(modes) > 1
        model_data = parse_model_file(
            model_path,
            bbox=(bbox.south, bbox.north, bbox.west, bbox.east),
            car_only=False if multi_mode else ("car" in modes and len(modes) == 1),
            modes=modes if multi_mode else None,
        )
        dem = generate_census_demand(
            model_data=model_data,
            network_path=out / "network.xml",
            output_path=out / "demand.csv",
            num_trips=trips,
            seed=seed,
            horizon_start=start_time,
            horizon_end=end_time,
            mode=modes[0] if len(modes) == 1 else "car",
            modes=modes if multi_mode else None,
            allow_oversample=allow_oversample,
        )
    else:
        dem = generate_synthetic_demand(
            network_path=out / "network.xml",
            output_path=out / "demand.csv",
            num_trips=trips,
            strategy="gravity",
            seed=seed,
            horizon_start=start_time,
            horizon_end=end_time,
            mode=modes[0] if len(modes) == 1 else "car",
        )

    step_times["Demand"] = time.time() - t_step
    elapsed = round(time.time() - t0, 1)
    strategy = dem.get("strategy", "synthetic")
    provenance = dem.get("provenance")  # only present for census_schedule_first

    if provenance:
        sched_pct = provenance["schedule_driven_pct"]
        demand_summary = (f"{dem['trip_count']:,} trips "
                          f"({sched_pct:.1f}% schedule-driven, "
                          f"{provenance['gravity_fallback_count']:,} gravity)")
    else:
        demand_summary = f"{dem['trip_count']:,} trips"
    progress.print_above(f"  ✓ demand.csv: {demand_summary}  "
                         f"({_fmt_dur(step_times['Demand'])})")
    progress.complete_step()
    progress.stop()

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"\n  Wall time:    {_fmt_dur(elapsed)}")
    print(f"  Scenario:     {scenario_id}")
    print(f"  Output:       {out}/")

    print("\n  Step timing:")
    total_step = sum(step_times.values()) or 1.0
    name_w = max(len(n) for n in step_times)
    for name, dt in step_times.items():
        pct = 100.0 * dt / total_step
        print(f"    {name:<{name_w}}  {_fmt_dur(dt):>8}   ({pct:4.1f}%)")

    print("\n  Artifacts:")
    print(f"    network.xml   {net['node_count']:>7,} nodes  /  "
          f"{net['link_count']:>7,} links")
    print(f"    signals.xml   {sig['signal_count']:>7,} controllers")
    print(f"    demand.csv    {dem['trip_count']:>7,} trips ({strategy})")
    print(f"    config.xml    {time_desc} simulation window, seed={seed}")
    print(f"    manifest.xml  SHA-256 checksummed")
    print("=" * 60 + "\n")

    # Save generation metadata (includes OSM provenance so any scenario can be
    # traced back to the exact PBF snapshot it was built from).
    metadata = {
        "scenario_id": scenario_id,
        "city": city,
        "city_name": city_info["name"],
        "trips_requested": trips,
        "trips_generated": dem["trip_count"],
        "modes": modes,
        "start_time_s": start_time,
        "end_time_s": end_time,
        "radius_km": radius_km,
        "seed": seed,
        "demand_strategy": strategy,
        "node_count": net["node_count"],
        "link_count": net["link_count"],
        "signal_count": sig["signal_count"],
        "generation_time_s": elapsed,
        "osm_source": net.get("osm_source"),
        # Toolchain snapshot pins the bundle to its exact build environment.
        # Cross-machine bundles produced under different osmnx/python/numpy
        # versions can diverge byte-wise even with the same seed; this block
        # gives reviewers and the methods chapter the receipts.
        "toolchain": _toolchain_versions(),
    }
    if provenance:
        # demand_provenance documents how each trip's destination was selected:
        # schedule (real PUMS workplace via cityscape ScheduleGenerator) vs
        # gravity (degree-weighted fallback). fallback_reasons records why
        # any scheduled persons were rejected at validation time.
        metadata["demand_provenance"] = provenance
    with open(out / "generation_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return metadata


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description=(
            "SimForge Unified Scenario Generator\n"
            "Generate customizable canonical scenario bundles using census data.\n\n"
            "Census (ModelGen) data is used by default. Use --synthetic to\n"
            "force the gravity-model fallback."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick 5K car scenario in Chicago
  python generate.py --city chicago --trips 5000

  # 200K mixed-mode trips in LA, morning rush (6-9 AM)
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400

  # Full-day 170K car trips in NYC
  python generate.py --city nyc --trips 170000 --start-time 0 --end-time 86400

  # Use a preset configuration
  python generate.py --preset morning_rush

  # Force synthetic demand
  python generate.py --city chicago --trips 5000 --synthetic

  # List all cities, presets, and modes
  python generate.py --list

Supported cities:  chicago, nyc, la
Supported modes:   car, transit, bike, walk
Census limit:      ~500K car trips per city without --allow-oversample
        """,
    )

    # Display commands
    parser.add_argument("--list", action="store_true",
                        help="List available cities, presets, and modes")

    # Preset
    parser.add_argument("--preset", "-p", type=str, default=None,
                        choices=list(PRESETS.keys()),
                        help="Use a built-in preset configuration")

    # City & location
    parser.add_argument("--city", "-c", type=str, default=None,
                        choices=list(CITIES.keys()),
                        help="City to generate (chicago, nyc, la)")
    parser.add_argument("--radius", "-r", type=float, default=None,
                        help="Network radius in km (default: city-specific)")

    # Demand parameters
    parser.add_argument("--trips", "-t", type=int, default=None,
                        help="Number of OD trips to generate (default: 5000)")
    parser.add_argument("--modes", type=str, default=None,
                        help="Comma-separated travel modes: car,transit,bike,walk "
                             "(default: car)")
    parser.add_argument("--start-time", type=int, default=None,
                        help="Simulation start time in seconds from midnight "
                             "(default: 25200, i.e. 07:00 AM)")
    parser.add_argument("--end-time", type=int, default=None,
                        help="Simulation end time in seconds from midnight "
                             "(default: 28800, i.e. 08:00 AM)")

    # Control
    parser.add_argument("--seed", "-s", type=int, default=None,
                        help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Custom output directory")
    parser.add_argument("--id", type=str, default=None,
                        help="Custom scenario ID (default: auto-generated)")

    # Demand source
    parser.add_argument("--synthetic", action="store_true",
                        help="Force synthetic gravity-model demand instead of census")
    parser.add_argument("--allow-oversample", action="store_true",
                        help="Allow more trips than raw census commuters "
                             "(resamples origins)")

    # Verbosity
    parser.add_argument("--verbose", action="store_true",
                        help="Show pipeline INFO logs (default: WARNING and above only)")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Verbosity gate (matches the run.py pattern). Default-suppress
    # pipeline.* INFO chatter so the user-facing print() banners are
    # readable. WARNING+ from any source still surfaces. Pass --verbose
    # to restore INFO when debugging a single failing step.
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        for name in ("pipeline", "pipeline.network", "pipeline.demand",
                     "pipeline.signals", "adapters"):
            logging.getLogger(name).setLevel(logging.INFO)
    else:
        for name in ("pipeline", "pipeline.network", "pipeline.demand",
                     "pipeline.signals", "adapters"):
            logging.getLogger(name).setLevel(logging.WARNING)

    # Handle --list
    if args.list:
        show_list()
        return

    # Handle --preset (load defaults, then allow overrides)
    if args.preset:
        preset = PRESETS[args.preset]
        city = args.city or preset["city"]
        trips = args.trips if args.trips is not None else preset["trips"]
        modes = (args.modes.split(",") if args.modes
                 else preset["modes"])
        start_time = (args.start_time if args.start_time is not None
                      else preset["start_time"])
        end_time = (args.end_time if args.end_time is not None
                    else preset["end_time"])
        radius_km = (args.radius if args.radius is not None
                     else preset["radius_km"])
        seed = args.seed if args.seed is not None else preset["seed"]
    else:
        # Require --city if no preset
        if args.city is None:
            print("Error: --city is required (or use --preset).")
            print("  Available cities: chicago, nyc, la")
            print("  Use --list to see all options.")
            sys.exit(1)

        city = args.city
        trips = args.trips if args.trips is not None else 5_000
        modes = args.modes.split(",") if args.modes else ["car"]
        # Default to the 7–8 AM rush-hour window used by the bundled scenario
        # so `generate.py --city chicago --trips 1000` reproduces chicago_1k_car
        # exactly (seed 42, radius 2 km, 25200–28800 s).
        start_time = args.start_time if args.start_time is not None else 25200
        end_time = args.end_time if args.end_time is not None else 28800
        radius_km = (args.radius if args.radius is not None
                     else CITIES[city]["default_radius_km"])
        seed = args.seed if args.seed is not None else 42

    # Validate
    for m in modes:
        if m not in VALID_MODES:
            print(f"Error: Invalid mode '{m}'. Valid modes: {', '.join(sorted(VALID_MODES))}")
            sys.exit(1)

    if start_time >= end_time:
        print(f"Error: --start-time ({start_time}) must be < --end-time ({end_time})")
        sys.exit(1)

    if trips < 1:
        print("Error: --trips must be >= 1")
        sys.exit(1)

    # Run generation
    generate_scenario(
        city=city,
        trips=trips,
        modes=modes,
        start_time=start_time,
        end_time=end_time,
        radius_km=radius_km,
        seed=seed,
        output_dir=args.output,
        scenario_id=args.id,
        synthetic=args.synthetic,
        allow_oversample=args.allow_oversample,
    )


if __name__ == "__main__":
    main()
