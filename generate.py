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
  python generate.py --preset chicago_1k_car

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


from pipeline.progress import StickyProgress, _fmt_dur

_TOTAL_STEPS = 4


def _display_path(p: Path) -> str:
    """Render a Path as it would appear if the user typed it.

    When the path lives under cwd, show the cwd-relative form (e.g.
    ``scenarios/chicago_1k_car``) so the default-output case looks the
    same as ``--output scenarios/foo``. When it doesn't (``/tmp/...``,
    ``--output`` outside the repo), fall back to the absolute path.
    Avoids the inconsistency where the default output was always
    absolute (built from ``Path(__file__).parent``) while user-provided
    ``--output`` values stayed short.
    """
    try:
        return str(p.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(p)


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
    "chicago_1k_car": {
        "description": "Chicago — 1K car trips, 7–8 AM (smallest tier; test fixture)",
        "city": "chicago",
        "trips": 1_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 28800,     # 8:00 AM
        "radius_km": 2.0,
        "seed": 42,
    },
    "nyc_10k_car": {
        "description": "NYC — 10K car trips, 7–9 AM",
        "city": "nyc",
        "trips": 10_000,
        "modes": ["car"],
        "start_time": 25200,   # 7:00 AM
        "end_time": 32400,     # 9:00 AM
        "radius_km": 4.0,
        "seed": 42,
    },
    "la_50k_car": {
        "description": "LA — 50K car trips, 6–10 AM",
        "city": "la",
        "trips": 50_000,
        "modes": ["car"],
        "start_time": 21600,   # 6:00 AM
        "end_time": 36000,     # 10:00 AM
        "radius_km": 10.0,
        "seed": 42,
    },
    "chicago_200k_car": {
        "description": "Chicago — 200K car trips, 24-hour",
        "city": "chicago",
        "trips": 200_000,
        "modes": ["car"],
        "start_time": 0,
        "end_time": 86400,     # 24 hours
        "radius_km": 15.0,
        "seed": 42,
    },
    "nyc_500k_car": {
        "description": "NYC — 500K car trips, 6–10 AM (largest tier; HPC scale)",
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
    allow_overpass: bool = False,
    force_overpass: bool = False,
    verbose: bool = False,
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
    print(f"  Output:     {_display_path(out)}")
    print("-" * 60)
    print("\n" + "=" * 60)
    print("  Generation Pipeline")
    print("=" * 60)

    t0 = time.time()
    step_times: dict[str, float] = {}
    # ALWAYS route logs through the bar's print_above() so any record
    # (including WARNING+ from osmnx / build_network_from_osm.py) lands
    # cleanly above the sticky bar. Pre-V11.1 capture was gated on
    # --verbose, which meant default-mode WARNING records (e.g.
    # "Dropping degenerate edge ...") went straight to stderr and
    # collided with the bar's no-newline redraws — producing mangled
    # `░░░░  ⠦  0%  step 1/4 ... elapsed 3m 07sWARNING ...` lines.
    # The level threshold below decides what passes through:
    #   default  → WARNING+ (errors still surface, no INFO firehose)
    #   verbose  → INFO+    (full adapter chatter)
    capture_log_level = logging.INFO if verbose else logging.WARNING
    progress = StickyProgress(
        _TOTAL_STEPS, unit="step",
        capture_logs=True,
        capture_log_level=capture_log_level,
        capture_log_names=("", "pipeline", "pipeline.network",
                           "pipeline.demand", "pipeline.signals",
                           "adapters"),
    )
    progress.start()

    # ---- 1. Network from OSM ----
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Resolve OSM source. Three modes:
    #   default               : require local PBF, fail hard if missing
    #   allow_overpass=True   : prefer PBF; fall back to Overpass if missing
    #   force_overpass=True   : always use Overpass, ignore PBF
    # PBF is the canonical source (provenance recorded in osm_data/manifest.json
    # with URL + SHA256). Overpass responses are NOT hash-pinned and produce
    # bundles that are NOT byte-reproducible across days.
    pbf_rel = city_info.get("pbf_file")
    pbf_path = project_root / pbf_rel if pbf_rel else None
    pbf_available = pbf_path is not None and pbf_path.exists()
    if force_overpass:
        use_overpass = True
    elif pbf_available:
        use_overpass = False
    elif allow_overpass:
        use_overpass = True
    else:
        raise FileNotFoundError(
            f"OSM PBF required for city '{city}' but not found: {pbf_path}\n"
            f"  Download it with:  python tools/download_osm.py\n"
            f"  Provenance lives in osm_data/manifest.json (URL + SHA256).\n"
            f"  Or pass --allow-overpass to use the live Overpass API as fallback\n"
            f"  when the PBF is missing, or --force-overpass to always use it.\n"
            f"  WARNING: Overpass bundles are NOT byte-reproducible across days."
        )

    progress.print_above(f"\n▶ Step 1/4: OSM network ({radius_km:.1f} km radius)")
    if use_overpass:
        # Loud warning so the operator never confuses an Overpass bundle
        # with a hash-pinned reproducible one.
        if force_overpass and pbf_available:
            note = "forced via --force-overpass; local PBF ignored"
        elif force_overpass:
            note = "forced via --force-overpass"
        else:
            note = f"fallback (PBF not found at osm_data/{pbf_path.name if pbf_path else '?'})"
        progress.print_above(f"           source: Overpass API ⚠ ({note})")
        progress.print_above(f"                   NOT hash-pinned — bundle won't be byte-reproducible")
        effective_pbf = None
    else:
        size_mb = pbf_path.stat().st_size / 1e6
        progress.print_above(f"           source: osm_data/{pbf_path.name} "
                             f"({size_mb:.0f} MB, local PBF — hash-pinned)")
        effective_pbf = pbf_path
    progress.set_label(f"OSM network ({radius_km:.1f} km)")
    t_step = time.time()
    net = build_network_from_osm(
        bbox, out / "network.xml", network_type="drive", pbf_path=effective_pbf
    )
    step_times["Network"] = time.time() - t_step
    # Source provenance: PBF is already announced in the pre-step
    # `source: ...` line (above), so the ✓ line stays clean. Overpass
    # fallback IS worth surfacing on the ✓ line — it's a divergence
    # from what we announced (the default-mode path expected PBF) and
    # the operator should see ⚠ explicitly.
    src = net.get("osm_source", {})
    if src.get("type") == "pbf":
        src_label = ""  # already shown in pre-step "source:" line
    else:
        src_label = f"  from Overpass API ⚠ ({src.get('endpoint','?')})"
    progress.print_above(f"  ✓ network.xml: {net['node_count']:,} nodes, "
                         f"{net['link_count']:,} links{src_label}  "
                         f"({_fmt_dur(step_times['Network'])})")
    progress.advance()

    # ---- 2. Signals ----
    progress.print_above("\n▶ Step 2/4: Traffic signals")
    progress.set_label("Traffic signals")
    t_step = time.time()
    sig = build_signals_default(
        network_path=out / "network.xml",
        output_path=out / "signals.xml",
        min_degree=4,
    )
    step_times["Signals"] = time.time() - t_step
    progress.print_above(f"  ✓ signals.xml: {sig['signal_count']:,} controllers  "
                         f"({_fmt_dur(step_times['Signals'])})")
    progress.advance()

    # ---- 3. Config / Manifest ----
    progress.print_above("\n▶ Step 3/4: Config + manifest")
    progress.set_label("Config + manifest")
    t_step = time.time()
    _write_config_xml(out / "config.xml", scenario_id, description,
                      start_time, end_time, seed)
    _write_manifest_xml(out / "manifest.xml", scenario_id)
    step_times["Config"] = time.time() - t_step
    progress.print_above(f"  ✓ config.xml + manifest.xml  ({_fmt_dur(step_times['Config'])})")
    progress.advance()

    # ---- 4. Demand ----
    if use_census:
        demand_label = "census via ModelGen"
        model_size_mb = model_path.stat().st_size / 1e6
        demand_source = (f"modelgen/{model_path.name} "
                         f"({model_size_mb:.0f} MB, PUMS microdata — hash-pinned)")
    else:
        demand_label = "synthetic via gravity model"
        demand_source = "no input file (gravity model samples origins/destinations)"
    progress.print_above(f"\n▶ Step 4/4: Demand — {demand_label}")
    progress.print_above(f"           source: {demand_source}")
    progress.set_label(f"Demand — {demand_label}")
    t_step = time.time()
    if use_census:
        # Always use the dict-based filter (`modes=`). Previously the dispatch
        # split between a single-mode-car shortcut and a multi-mode path,
        # which left single non-car modes (e.g. `--modes transit`) hitting
        # *neither* branch and silently passing the unfiltered population.
        # With one filter path, every mode list is honored.
        model_data = parse_model_file(
            model_path,
            bbox=(bbox.south, bbox.north, bbox.west, bbox.east),
            modes=modes,
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
            modes=modes,
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
    progress.advance()
    progress.stop()

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"\n  Wall time:    {_fmt_dur(elapsed)}")
    print(f"  Scenario:     {scenario_id}")
    print(f"  Output:       {_display_path(out)}/")

    print("\n  Step timing:")
    total_step = sum(step_times.values()) or 1.0
    name_w = max(len(n) for n in step_times)
    dur_w = max(len(_fmt_dur(dt)) for dt in step_times.values())
    for name, dt in step_times.items():
        pct = 100.0 * dt / total_step
        print(f"    {name:<{name_w}}  {_fmt_dur(dt):<{dur_w}}  ({pct:5.1f}%)")

    print("\n  Artifacts:")
    art_w = len("manifest.xml")  # 12 — widest filename in the block
    print(f"    {'network.xml':<{art_w}}  {net['node_count']:,} nodes / "
          f"{net['link_count']:,} links")
    print(f"    {'signals.xml':<{art_w}}  {sig['signal_count']:,} controllers")
    print(f"    {'demand.csv':<{art_w}}  {dem['trip_count']:,} trips ({strategy})")
    print(f"    {'config.xml':<{art_w}}  {time_desc} simulation window, seed={seed}")
    print(f"    {'manifest.xml':<{art_w}}  SHA-256 checksummed\n")
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
  python generate.py --preset chicago_1k_car

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

    # Network source — three mutually-exclusive modes:
    #   default            : require osm_data/<pbf>, fail hard if missing
    #   --allow-overpass   : prefer PBF if present; fall back to Overpass if missing
    #   --force-overpass   : always use Overpass, ignore PBF even when present
    overpass_group = parser.add_mutually_exclusive_group()
    overpass_group.add_argument("--allow-overpass", action="store_true",
                                help="Use the live Overpass API as a fallback when "
                                     "osm_data/<pbf> is missing. PBF is still preferred "
                                     "when available. WARNING: bundles produced from "
                                     "Overpass are NOT byte-reproducible.")
    overpass_group.add_argument("--force-overpass", action="store_true",
                                help="Always use the live Overpass API, ignoring any "
                                     "local PBF. WARNING: bundles produced this way are "
                                     "NOT byte-reproducible. Use only for one-off "
                                     "experimentation or when you specifically want "
                                     "today's OSM data.")

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

    # Pull through the new OSM-source mode flags.
    allow_overpass = getattr(args, "allow_overpass", False)
    force_overpass = getattr(args, "force_overpass", False)

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
        allow_overpass=allow_overpass,
        force_overpass=force_overpass,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
