"""Parse MATSim event streams for time-resolved link load.

MATSim's ``output_events.xml.gz`` records every link enter/leave event
with a timestamp. Aggregating "entered link" events into time bins
gives per-link throughput (vehicles per bin) over the simulation
horizon — the data behind the ``animated_flow`` map.

Cached at ``cache/events/<scenario>/<engine>_<seed>_<bin>s.json`` so
subsequent renders skip the slow XML parse.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections import defaultdict
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)


def cache_path(
    scenario_id: str,
    engine: str,
    seed: int,
    time_bin_seconds: int,
) -> Path:
    return (
        Path("cache") / "events" / scenario_id /
        f"{engine}_seed{seed}_bin{time_bin_seconds}s.json"
    )


def traversals_cache_path(scenario_id: str, engine: str, seed: int) -> Path:
    return (
        Path("cache") / "events" / scenario_id /
        f"{engine}_seed{seed}_traversals.json"
    )


def parse_matsim_vehicle_traversals(
    events_path: Path,
    scenario_id: str | None = None,
    seed: int | None = None,
    force_refresh: bool = False,
) -> dict[str, list[tuple[str, float, float]]]:
    """Parse a MATSim events.xml.gz into per-vehicle link traversal records.

    Returns ``{vehicle_id: [(link_id, enter_time_s, leave_time_s), ...]}``
    sorted by enter_time per vehicle.

    Used by the flowing-particle animation to interpolate each
    vehicle's continuous position over time.
    """
    cache_fp: Path | None = None
    if scenario_id and seed is not None:
        cache_fp = traversals_cache_path(scenario_id, "matsim", seed)
        if cache_fp.is_file() and not force_refresh:
            try:
                data = json.loads(cache_fp.read_text())
                logger.info("MATSim traversals cache hit: %d vehicles from %s",
                            len(data), cache_fp)
                return {
                    vid: [(t[0], float(t[1]), float(t[2])) for t in records]
                    for vid, records in data.items()
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Traversals cache corrupt at %s: %s — re-parsing",
                               cache_fp, e)

    open_intervals: dict[tuple[str, str], float] = {}  # (vehicle, link) -> enter_time
    out: dict[str, list[tuple[str, float, float]]] = defaultdict(list)

    logger.info("Parsing MATSim vehicle traversals: %s", events_path)
    with gzip.open(events_path, "rb") as gz:
        ctx = etree.iterparse(gz, events=("end",), tag="event")
        for _, elem in ctx:
            etype = elem.get("type")
            if etype not in ("entered link", "left link"):
                elem.clear()
                continue
            try:
                t = float(elem.get("time", 0))
            except (TypeError, ValueError):
                elem.clear()
                continue
            link = elem.get("link")
            veh = elem.get("vehicle") or elem.get("person")
            if not link or not veh:
                elem.clear()
                continue
            key = (veh, link)
            if etype == "entered link":
                open_intervals[key] = t
            else:  # left link
                enter_t = open_intervals.pop(key, None)
                if enter_t is not None and t > enter_t:
                    out[veh].append((link, enter_t, t))
            elem.clear()

    # Sort each vehicle's records by enter_time (already in order from
    # event stream, but defensive).
    for veh in out:
        out[veh].sort(key=lambda r: r[1])

    n_traversals = sum(len(v) for v in out.values())
    logger.info("MATSim traversals: %d vehicles, %d total link visits",
                len(out), n_traversals)

    if cache_fp is not None:
        cache_fp.parent.mkdir(parents=True, exist_ok=True)
        cache_fp.write_text(json.dumps(
            dict(out), separators=(",", ":"),
        ))
        logger.info("Cached traversals -> %s", cache_fp)
    return dict(out)


def parse_matsim_throughput(
    events_path: Path,
    time_bin_seconds: int = 300,
    scenario_id: str | None = None,
    seed: int | None = None,
    force_refresh: bool = False,
) -> dict[int, dict[str, int]]:
    """Parse a MATSim events.xml.gz into per-time-bin per-link throughput.

    Returns ``{bin_start_seconds: {link_id: vehicles_entered}}``.

    Bins are aligned to ``time_bin_seconds`` boundaries (e.g., 300s
    bins starting at 25200, 25500, 25800, ...).

    Caches result keyed on (scenario_id, "matsim", seed, time_bin_seconds)
    if those args are provided. Cache is a JSON dict {bin_start: {link: count}}.
    """
    cache_fp: Path | None = None
    if scenario_id and seed is not None:
        cache_fp = cache_path(scenario_id, "matsim", seed, time_bin_seconds)
        if cache_fp.is_file() and not force_refresh:
            try:
                data = json.loads(cache_fp.read_text())
                logger.info("MATSim events cache hit: %d bins from %s",
                            len(data), cache_fp)
                return {int(k): {l: int(c) for l, c in v.items()}
                        for k, v in data.items()}
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Events cache corrupt at %s: %s — re-parsing",
                               cache_fp, e)

    bins: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    logger.info("Parsing MATSim events: %s (binning to %ds windows)...",
                events_path, time_bin_seconds)
    with gzip.open(events_path, "rb") as gz:
        ctx = etree.iterparse(gz, events=("end",), tag="event")
        for _, elem in ctx:
            if elem.get("type") != "entered link":
                elem.clear()
                continue
            try:
                t = float(elem.get("time", 0))
            except (TypeError, ValueError):
                elem.clear()
                continue
            link = elem.get("link")
            if link:
                bin_key = int(t // time_bin_seconds) * time_bin_seconds
                bins[bin_key][link] += 1
            elem.clear()

    out = {k: dict(v) for k, v in bins.items()}
    n_links = len({l for v in out.values() for l in v})
    n_events = sum(sum(v.values()) for v in out.values())
    logger.info("MATSim events: %d bins covering %d unique links, %d total enters",
                len(out), n_links, n_events)

    if cache_fp is not None:
        cache_fp.parent.mkdir(parents=True, exist_ok=True)
        cache_fp.write_text(json.dumps(
            {str(k): v for k, v in out.items()},
            separators=(",", ":"),
        ))
        logger.info("Cached events -> %s", cache_fp)
    return out
