"""
Tests for the OSM network-fetching module.

These tests run offline.  `osmnx.graph_from_bbox` is monkeypatched so we can
exercise the full `build_network_from_osm` pipeline — bbox validation, cache
folder pinning, error translation, canonical-schema extraction, and the
`PREDEFINED_CITIES` table — without hitting the public Overpass API.

Catches regressions in:
  - `BoundingBox.__post_init__` invariant enforcement (north>south, east>west)
  - `BoundingBox.from_string` / `from_center` parse contracts
  - The CRS-aware `ox.settings.cache_folder` pinning that keeps OSM responses
    in `<repo>/cache` rather than `~/.osmnx`
  - The translation of any `ox.graph_from_bbox` exception into a RuntimeError
    with a human-readable "possible causes" block
  - The empty-result guard (`ValueError` when OSM returns a zero-node graph)
  - The lookup table for predefined cities (five entries: sioux_falls,
    anaheim, austin_downtown, manhattan_midtown, sf_downtown)
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pipeline.network import build_network_from_osm as osm_mod
from pipeline.network.build_network_from_osm import (
    DEFAULT_LANES,
    DEFAULT_SPEEDS_MPS,
    PREDEFINED_CITIES,
    BoundingBox,
    build_network_from_osm,
    download_osm_network,
    extract_canonical_network,
    get_city_bbox,
)


# ---------------------------------------------------------------------------
# Stub osmnx-style graph (no networkx dependency in the stub itself)
# ---------------------------------------------------------------------------


class _StubGraph:
    """Minimal duck-type of `networkx.MultiDiGraph` used by the fetch module.

    Only the methods actually called by `download_osm_network` /
    `extract_canonical_network` are implemented; anything else would raise."""

    def __init__(self, nodes: list[tuple[int, dict]], edges: list[tuple[int, int, int, dict]]):
        self._nodes = nodes
        self._edges = edges
        self._adj: dict[int, list[int]] = {}
        self._rev: dict[int, list[int]] = {}
        for u, v, _key, _data in edges:
            self._adj.setdefault(u, []).append(v)
            self._rev.setdefault(v, []).append(u)
            self._adj.setdefault(v, [])
            self._rev.setdefault(u, [])

    def number_of_nodes(self) -> int:
        return len(self._nodes)

    def number_of_edges(self) -> int:
        return len(self._edges)

    def nodes(self, data: bool = False):
        if data:
            return list(self._nodes)
        return [n for n, _ in self._nodes]

    def edges(self, keys: bool = False, data: bool = False):
        out = []
        for u, v, k, d in self._edges:
            if keys and data:
                out.append((u, v, k, d))
            elif data:
                out.append((u, v, d))
            elif keys:
                out.append((u, v, k))
            else:
                out.append((u, v))
        return out

    def in_degree(self, n):
        return len(self._rev.get(n, []))

    def out_degree(self, n):
        return len(self._adj.get(n, []))


def _sample_graph() -> _StubGraph:
    """Tiny 4-node graph used by the successful-fetch tests."""
    nodes = [
        (1001, {"x": -87.65, "y": 41.88}),
        (1002, {"x": -87.64, "y": 41.88}),
        (1003, {"x": -87.64, "y": 41.89}),
        (1004, {"x": -87.65, "y": 41.89}),
    ]
    edges = [
        (1001, 1002, 0, {"highway": "residential", "length": 111.0, "maxspeed": "30 mph"}),
        (1002, 1003, 0, {"highway": "primary",     "length": 150.0, "lanes": 3}),
        (1003, 1004, 0, {"highway": "residential", "length": 111.0}),
        (1004, 1001, 0, {"highway": "residential", "length": 150.0, "maxspeed": "50"}),
    ]
    return _StubGraph(nodes, edges)


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------


class TestBoundingBox:

    def test_basic_construction(self):
        bbox = BoundingBox(north=41.9, south=41.8, east=-87.6, west=-87.7)
        assert bbox.north == 41.9
        assert bbox.south == 41.8
        assert bbox.east == -87.6
        assert bbox.west == -87.7

    def test_rejects_inverted_latitude(self):
        with pytest.raises(ValueError, match="North"):
            BoundingBox(north=41.8, south=41.9, east=-87.6, west=-87.7)

    def test_rejects_equal_latitude(self):
        with pytest.raises(ValueError, match="North"):
            BoundingBox(north=41.9, south=41.9, east=-87.6, west=-87.7)

    def test_rejects_inverted_longitude(self):
        with pytest.raises(ValueError, match="East"):
            BoundingBox(north=41.9, south=41.8, east=-87.7, west=-87.6)

    def test_from_string_parses_four_values(self):
        bbox = BoundingBox.from_string("41.9, 41.8, -87.6, -87.7")
        assert (bbox.north, bbox.south, bbox.east, bbox.west) == (41.9, 41.8, -87.6, -87.7)

    def test_from_string_rejects_wrong_arity(self):
        with pytest.raises(ValueError, match="Expected 4 values"):
            BoundingBox.from_string("41.9, 41.8, -87.6")

    def test_from_center_shape(self):
        # ~1 km radius around Chicago.
        bbox = BoundingBox.from_center(lat=41.88, lon=-87.65, radius_km=1.0)
        lat_delta = 1.0 / 111.0
        assert bbox.north == pytest.approx(41.88 + lat_delta, abs=1e-6)
        assert bbox.south == pytest.approx(41.88 - lat_delta, abs=1e-6)
        # Longitude delta must account for latitude (smaller box in ° lon).
        lon_delta = 1.0 / (111.0 * math.cos(math.radians(41.88)))
        assert bbox.east == pytest.approx(-87.65 + lon_delta, abs=1e-6)
        assert bbox.west == pytest.approx(-87.65 - lon_delta, abs=1e-6)
        # And the invariants still hold.
        assert bbox.north > bbox.south
        assert bbox.east > bbox.west


# ---------------------------------------------------------------------------
# Predefined cities
# ---------------------------------------------------------------------------


class TestPredefinedCities:

    def test_catalogue_has_expected_entries(self):
        expected = {"sioux_falls", "anaheim", "austin_downtown", "manhattan_midtown", "sf_downtown"}
        assert expected.issubset(PREDEFINED_CITIES.keys())

    def test_every_city_has_center_and_radius(self):
        for key, city in PREDEFINED_CITIES.items():
            assert "center" in city, f"{key} missing 'center'"
            assert "radius_km" in city, f"{key} missing 'radius_km'"
            lat, lon = city["center"]
            assert -90 <= lat <= 90, f"{key}: invalid latitude {lat}"
            assert -180 <= lon <= 180, f"{key}: invalid longitude {lon}"
            assert city["radius_km"] > 0, f"{key}: non-positive radius"

    def test_get_city_bbox_returns_valid_bbox(self):
        bbox = get_city_bbox("sioux_falls")
        assert isinstance(bbox, BoundingBox)
        assert bbox.north > bbox.south
        assert bbox.east > bbox.west

    def test_get_city_bbox_unknown_city_lists_options(self):
        with pytest.raises(ValueError) as excinfo:
            get_city_bbox("atlantis")
        assert "atlantis" in str(excinfo.value)
        # Every available city should be mentioned in the error — helps users
        # notice a typo without reading the source.
        for key in PREDEFINED_CITIES:
            assert key in str(excinfo.value)


# ---------------------------------------------------------------------------
# Default tables are sensible (cheap sanity — catches copy-paste typos)
# ---------------------------------------------------------------------------


def test_default_speed_table_uses_mps_not_kmh():
    # 120 km/h ≈ 33.3 m/s.  If someone accidentally stored km/h the motorway
    # value would be ~120 and the adapters would produce unrealistic sims.
    assert DEFAULT_SPEEDS_MPS["motorway"] < 50
    assert DEFAULT_SPEEDS_MPS["motorway"] > 20
    assert DEFAULT_SPEEDS_MPS["service"] < DEFAULT_SPEEDS_MPS["primary"]


def test_default_lanes_table_monotonic():
    # Motorways get more lanes than residential streets in every reasonable
    # default set.  Sanity-check the ordering.
    assert DEFAULT_LANES["motorway"] >= DEFAULT_LANES["primary"]
    assert DEFAULT_LANES["primary"] >= DEFAULT_LANES["residential"]


# ---------------------------------------------------------------------------
# Cache folder pinning
# ---------------------------------------------------------------------------


def test_cache_folder_is_pinned_to_repo_cache(monkeypatch):
    """`_configure_osmnx_cache` must always point osmnx at `<repo>/cache`."""
    osm_mod._OSM_CACHE_CONFIGURED = False  # force reconfigure in this test

    class _Settings:
        use_cache = False
        cache_folder = None
        log_console = True

    class _FakeOx:
        settings = _Settings()

    monkeypatch.setitem(__import__("sys").modules, "osmnx", _FakeOx)

    osm_mod._configure_osmnx_cache()

    assert _FakeOx.settings.use_cache is True
    assert _FakeOx.settings.log_console is False
    # Must resolve to <repo>/cache, not ~/.osmnx or /tmp.
    repo_cache = Path(osm_mod.__file__).resolve().parents[2] / "cache"
    assert _FakeOx.settings.cache_folder == str(repo_cache)


# ---------------------------------------------------------------------------
# download_osm_network — exercises the full error / success paths with a stub
# ---------------------------------------------------------------------------


def _install_fake_ox(monkeypatch, graph_from_bbox):
    """Install a fake `osmnx` module with just the surface area used here."""

    class _Settings:
        use_cache = True
        cache_folder = "/tmp/fake-osm-cache"
        log_console = False

    class _FakeOx:
        settings = _Settings()

    _FakeOx.graph_from_bbox = staticmethod(graph_from_bbox)
    monkeypatch.setitem(__import__("sys").modules, "osmnx", _FakeOx)
    # Mark the cache as already-configured so the function doesn't try to
    # reassign settings on our _Settings class.
    osm_mod._OSM_CACHE_CONFIGURED = True
    return _FakeOx


def test_download_osm_network_returns_graph(monkeypatch):
    captured: dict = {}

    def _fake_graph_from_bbox(*, bbox, network_type, simplify, truncate_by_edge):
        captured["bbox"] = bbox
        captured["network_type"] = network_type
        captured["simplify"] = simplify
        captured["truncate_by_edge"] = truncate_by_edge
        return _sample_graph()

    _install_fake_ox(monkeypatch, _fake_graph_from_bbox)

    bbox = BoundingBox(north=41.89, south=41.88, east=-87.64, west=-87.65)
    G = download_osm_network(bbox)

    assert G.number_of_nodes() == 4
    # Osmnx 2.x takes bbox as (west, south, east, north) — regression guard.
    assert captured["bbox"] == (-87.65, 41.88, -87.64, 41.89)
    assert captured["simplify"] is True
    assert captured["truncate_by_edge"] is True


def test_download_osm_network_translates_exceptions(monkeypatch):
    def _raise(*args, **kwargs):
        raise ConnectionError("Overpass returned 429")

    _install_fake_ox(monkeypatch, _raise)

    with pytest.raises(RuntimeError) as excinfo:
        download_osm_network(BoundingBox(north=41.89, south=41.88, east=-87.64, west=-87.65))
    msg = str(excinfo.value)
    # Human-readable error block — users must be told what to check.
    assert "Overpass" in msg or "rate-limited" in msg
    assert "ConnectionError" in msg
    assert "Bbox" in msg


def test_download_osm_network_rejects_empty_graph(monkeypatch):
    _install_fake_ox(monkeypatch, lambda **kw: _StubGraph(nodes=[], edges=[]))

    with pytest.raises(ValueError, match="empty road network"):
        download_osm_network(BoundingBox(north=41.89, south=41.88, east=-87.64, west=-87.65))


def test_download_osm_network_reports_missing_osmnx(monkeypatch):
    # Simulate an environment where osmnx isn't installed.
    import sys

    monkeypatch.setitem(sys.modules, "osmnx", None)  # None triggers ImportError on import
    with pytest.raises(ImportError, match="osmnx"):
        download_osm_network(BoundingBox(north=41.89, south=41.88, east=-87.64, west=-87.65))


# ---------------------------------------------------------------------------
# extract_canonical_network — speed unit parsing
# ---------------------------------------------------------------------------


def test_extract_canonical_network_basic():
    G = _sample_graph()
    nodes, links, turn_restrictions = extract_canonical_network(G)
    # No OSM relations passed — turn_restrictions should be empty.
    assert turn_restrictions == []

    assert len(nodes) == 4
    assert {n.id for n in nodes} == {"n0", "n1", "n2", "n3"}
    # OSM IDs must round-trip so downstream tooling can trace back to OSM.
    assert {n.osm_id for n in nodes} == {1001, 1002, 1003, 1004}

    assert len(links) == 4
    # Link IDs monotonically increment.
    assert [l.id for l in links] == ["l0", "l1", "l2", "l3"]

    # mph string must be correctly converted: 30 mph → ~13.4 m/s.
    mph_link = next(l for l in links if l.from_node == "n0" and l.to_node == "n1")
    assert mph_link.speed_limit_mps == pytest.approx(13.4, abs=0.2)

    # Unitless "50" → km/h → ~13.9 m/s.
    kmh_link = next(l for l in links if l.from_node == "n3" and l.to_node == "n0")
    assert kmh_link.speed_limit_mps == pytest.approx(13.9, abs=0.2)

    # Explicit lanes tag wins over default.
    primary_link = next(l for l in links if l.from_node == "n1")
    assert primary_link.lanes == 3


# ---------------------------------------------------------------------------
# build_network_from_osm — full end-to-end with fake OSM backend
# ---------------------------------------------------------------------------


def test_build_network_from_osm_writes_xml(tmp_path, monkeypatch):
    _install_fake_ox(monkeypatch, lambda **kw: _sample_graph())

    out = tmp_path / "network.xml"
    result = build_network_from_osm(
        BoundingBox(north=41.89, south=41.88, east=-87.64, west=-87.65),
        output_path=out,
    )

    assert result["node_count"] == 4
    assert result["link_count"] == 4
    assert out.is_file()

    # Parse it back — must be valid XML containing nodes and links.
    from lxml import etree

    root = etree.parse(str(out)).getroot()
    assert len(root.findall(".//node")) == 4
    assert len(root.findall(".//link")) == 4
