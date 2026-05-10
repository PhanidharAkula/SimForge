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

    links: list[tuple[str, str, str]] = field(default_factory=list)
    """List of ``(from_node_id, to_node_id, highway_type)``.

    ``highway_type`` is the OSM tag (``motorway``, ``primary``, ``residential``,
    ``footway``, etc.) used by the basemap renderer to decide line weight.
    """

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
        elif elem.tag == "link":
            f = elem.get("from")
            t = elem.get("to")
            ht = elem.get("highway_type", "unclassified")
            if f and t:
                network.links.append((f, t, ht))
        elem.clear()
    return network


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


def bundle_paths(bundle_dir: Path) -> dict[str, Path]:
    """Return canonical file paths inside a bundle. Missing files are absent."""
    candidates = {
        "manifest": bundle_dir / "manifest.xml",
        "network": bundle_dir / "network.xml",
        "demand": bundle_dir / "demand.csv",
        "signals": bundle_dir / "signals.xml",
    }
    return {name: path for name, path in candidates.items() if path.is_file()}
