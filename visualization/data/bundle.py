"""Load network + demand from a SimForge canonical bundle.

A bundle is a directory like ``scenarios/chicago_1k_car/`` containing
``network.xml``, ``demand.csv``, and ``manifest.xml`` (plus optional
``signals.xml``, ``modelgen/``, etc.). This module exposes only the
geometry + demand pieces the visualizer needs — no engine-specific
knowledge.

Coordinates are EPSG:4326 (lon/lat). The visualizer does not reproject;
it plots in raw degrees with axis aspect set to ``equal`` so the
perceived scale is correct for small areas (city-level).
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree


@dataclass
class Network:
    """Subset of a SimForge bundle's network.xml that the visualizer needs."""

    nodes: dict[str, tuple[float, float]] = field(default_factory=dict)
    """Map ``node_id`` (e.g. ``"n42"``) to ``(lon, lat)``."""

    node_osm_ids: dict[str, int] = field(default_factory=dict)
    """Map ``node_id`` to its underlying OSM node ID (int). Used by the
    OSM-way curve-extraction pipeline to find where each SimForge link's
    endpoints land within the parent OSM way's vertex sequence."""

    links: list[tuple[str, str, str, str]] = field(default_factory=list)
    """List of ``(link_id, from_node_id, to_node_id, highway_type)``."""

    link_osm_way_ids: dict[str, list[int]] = field(default_factory=dict)
    """Map ``link_id`` to the OSM way IDs the link came from. Most links
    map to one way; some (where SimForge merged adjacent collinear ways)
    map to a list. Used by the OSM curve extractor to fetch the original
    way geometry for proper curved rendering of link_load / congestion."""

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        """Return ``(min_lon, min_lat, max_lon, max_lat)`` or None if empty."""
        if not self.nodes:
            return None
        lons = [c[0] for c in self.nodes.values()]
        lats = [c[1] for c in self.nodes.values()]
        return (min(lons), min(lats), max(lons), max(lats))


@dataclass
class Demand:
    """Subset of a SimForge bundle's demand.csv that the visualizer needs."""

    origins: list[str] = field(default_factory=list)
    """Per-trip origin ``node_id``."""

    destinations: list[str] = field(default_factory=list)
    """Per-trip destination ``node_id``."""

    purposes: list[str] = field(default_factory=list)
    """Per-trip ``purpose`` column (e.g. ``HBW_AM``); empty string if absent."""

    @property
    def trip_count(self) -> int:
        return len(self.origins)

    @property
    def origin_counts(self) -> dict[str, int]:
        """Map node_id -> # trips originating there."""
        return dict(Counter(self.origins))

    @property
    def destination_counts(self) -> dict[str, int]:
        """Map node_id -> # trips destined there."""
        return dict(Counter(self.destinations))


def load_network(network_path: Path) -> Network:
    """Parse ``network.xml`` lazily and return a Network.

    Uses ``lxml.etree.iterparse`` so the full DOM never lives in memory —
    important for la_50k_car (470k links, ~70 MB XML).
    """
    network = Network()
    context = etree.iterparse(str(network_path), events=("end",), tag=("node", "link"))
    for _, elem in context:
        if elem.tag == "node":
            nid = elem.get("id")
            try:
                x = float(elem.get("x"))
                y = float(elem.get("y"))
            except (TypeError, ValueError):
                elem.clear()
                continue
            network.nodes[nid] = (x, y)
            osm_id_str = elem.get("osm_id")
            if osm_id_str:
                try:
                    network.node_osm_ids[nid] = int(osm_id_str)
                except ValueError:
                    pass
        elif elem.tag == "link":
            lid = elem.get("id") or ""
            f = elem.get("from")
            t = elem.get("to")
            ht = elem.get("highway_type", "unclassified")
            if lid and f and t:
                network.links.append((lid, f, t, ht))
                osm_way_str = (elem.get("osm_way_id") or "").strip()
                if osm_way_str:
                    way_ids = _parse_osm_way_id_field(osm_way_str)
                    if way_ids:
                        network.link_osm_way_ids[lid] = way_ids
        elem.clear()
    return network


def _parse_osm_way_id_field(s: str) -> list[int]:
    """Parse the ``osm_way_id`` attribute, which is either a single int
    (``"123"``) or a Python-list-style string (``"[123, 456]"``).
    """
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        out: list[int] = []
        for part in s[1:-1].split(","):
            part = part.strip()
            if part:
                try:
                    out.append(int(part))
                except ValueError:
                    pass
        return out
    try:
        return [int(s)]
    except ValueError:
        return []


def load_demand(demand_path: Path) -> Demand:
    """Parse ``demand.csv`` and return per-trip origin/destination/purpose.

    Tolerates pre-V5 bundles missing the ``purpose`` column (purposes list
    will contain empty strings).
    """
    demand = Demand()
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            o = (row.get("origin_node_id") or "").strip()
            d = (row.get("destination_node_id") or "").strip()
            p = (row.get("purpose") or "").strip()
            if o and d:
                demand.origins.append(o)
                demand.destinations.append(d)
                demand.purposes.append(p)
    return demand


def figsize_for_bbox(
    bbox: tuple[float, float, float, float],
    target_height_in: float = 10.0,
    extra_width_in: float = 1.5,
    min_aspect: float = 0.5,
    max_aspect: float = 2.5,
) -> tuple[float, float]:
    """Pick a matplotlib figsize matching the data's lon/lat aspect.

    Avoids the "lots of white space" problem when a portrait-shaped
    scenario (e.g. nyc_500k_car: tall + narrow Manhattan + boroughs)
    is rendered into a hard-coded 14x10 landscape figure.

    Returns ``(width, height)`` in inches:
      - height = ``target_height_in``
      - width = height × data_aspect + ``extra_width_in`` (room for colorbar)

    Aspect is clamped to ``[min_aspect, max_aspect]`` so degenerate
    near-1D scenarios don't produce absurd figure shapes.
    """
    lon_range = bbox[2] - bbox[0]
    lat_range = bbox[3] - bbox[1]
    if lat_range <= 0:
        return (target_height_in, target_height_in)
    aspect = lon_range / lat_range
    aspect = max(min_aspect, min(max_aspect, aspect))
    plot_width = target_height_in * aspect
    return (plot_width + extra_width_in, target_height_in)


def bundle_paths(bundle_dir: Path) -> dict[str, Path]:
    """Return canonical file paths inside a bundle. Missing files are absent."""
    candidates = {
        "manifest": bundle_dir / "manifest.xml",
        "network": bundle_dir / "network.xml",
        "demand": bundle_dir / "demand.csv",
        "signals": bundle_dir / "signals.xml",
    }
    return {name: path for name, path in candidates.items() if path.is_file()}
