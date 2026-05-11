"""Tests for the visualization component (Phase A)."""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Bundle loaders
# ---------------------------------------------------------------------------


@pytest.fixture
def chicago_bundle(tmp_path: Path) -> Path:
    """Tiny synthetic bundle: 4 nodes, 3 links, 5 trips."""
    bundle = tmp_path / "tiny_car"
    bundle.mkdir()
    (bundle / "manifest.xml").write_text("<manifest/>", encoding="utf-8")
    (bundle / "network.xml").write_text(
        "<?xml version='1.0'?>\n"
        "<network>\n"
        "  <nodes>\n"
        "    <node id='n1' x='-87.6' y='41.88' type='intersection' osm_id='100'/>\n"
        "    <node id='n2' x='-87.62' y='41.88' type='intersection' osm_id='200'/>\n"
        "    <node id='n3' x='-87.6' y='41.89' type='intersection' osm_id='300'/>\n"
        "    <node id='n4' x='-87.62' y='41.89' type='intersection' osm_id='400'/>\n"
        "  </nodes>\n"
        "  <links>\n"
        "    <link id='l1' from='n1' to='n2' length='10' lanes='2' speed_limit='13.9' highway_type='primary' osm_way_id='1000'/>\n"
        "    <link id='l2' from='n2' to='n3' length='10' lanes='1' speed_limit='13.9' highway_type='residential' osm_way_id='2000'/>\n"
        "    <link id='l3' from='n3' to='n4' length='10' lanes='1' speed_limit='13.9' highway_type='footway' osm_way_id='[3000, 3001]'/>\n"
        "  </links>\n"
        "</network>\n",
        encoding="utf-8",
    )
    (bundle / "demand.csv").write_text(
        "trip_id,origin_node_id,destination_node_id,departure_time_s,mode,purpose\n"
        "t1,n1,n4,25200,car,HBW_AM\n"
        "t2,n1,n4,25260,car,HBW_AM\n"
        "t3,n2,n3,25320,car,HBW_AM\n"
        "t4,n3,n2,25380,car,HBW_AM\n"
        "t5,n1,n2,25440,car,HBW_AM\n",
        encoding="utf-8",
    )
    return bundle


class TestBundleLoaders:
    def test_load_network_parses_nodes_and_links(self, chicago_bundle: Path) -> None:
        from visualization.data.bundle import load_network
        net = load_network(chicago_bundle / "network.xml")
        assert len(net.nodes) == 4
        assert net.nodes["n1"] == (-87.6, 41.88)
        assert len(net.links) == 3
        # Each link tuple is (link_id, from, to, highway_type)
        assert ("l1", "n1", "n2", "primary") in net.links
        assert ("l3", "n3", "n4", "footway") in net.links

    def test_network_bbox(self, chicago_bundle: Path) -> None:
        from visualization.data.bundle import load_network
        net = load_network(chicago_bundle / "network.xml")
        bbox = net.bbox
        assert bbox == (-87.62, 41.88, -87.6, 41.89)

    def test_load_demand_parses_origins_destinations(self, chicago_bundle: Path) -> None:
        from visualization.data.bundle import load_demand
        dem = load_demand(chicago_bundle / "demand.csv")
        assert dem.trip_count == 5
        assert dem.origins == ["n1", "n1", "n2", "n3", "n1"]
        assert dem.destinations == ["n4", "n4", "n3", "n2", "n2"]
        assert dem.purposes[0] == "HBW_AM"

    def test_demand_origin_counts(self, chicago_bundle: Path) -> None:
        from visualization.data.bundle import load_demand
        dem = load_demand(chicago_bundle / "demand.csv")
        assert dem.origin_counts == {"n1": 3, "n2": 1, "n3": 1}
        assert dem.destination_counts == {"n4": 2, "n3": 1, "n2": 2}

    def test_bundle_paths_finds_present_files(self, chicago_bundle: Path) -> None:
        from visualization.data.bundle import bundle_paths
        paths = bundle_paths(chicago_bundle)
        assert "network" in paths
        assert "demand" in paths
        assert "manifest" in paths
        # signals not present in fixture
        assert "signals" not in paths


# ---------------------------------------------------------------------------
# Coverage scanner
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_bundle_only_coverage(self, chicago_bundle: Path) -> None:
        from visualization.coverage import discover_bundle
        cov = discover_bundle(chicago_bundle, scenario_id="tiny")
        assert cov.has_bundle
        assert cov.engines_with_results == set()
        ok, _ = cov.map_generatable("od_origins")
        assert ok
        ok, _ = cov.map_generatable("od_destinations")
        assert ok
        ok, _ = cov.map_generatable("link_load")
        assert not ok
        ok, _ = cov.map_generatable("route_diversity")
        assert not ok

    def test_missing_bundle_coverage(self, tmp_path: Path) -> None:
        from visualization.coverage import discover_bundle
        cov = discover_bundle(tmp_path / "does_not_exist", scenario_id="ghost")
        assert not cov.has_bundle
        ok, reason = cov.map_generatable("od_origins")
        assert not ok
        assert "missing" in reason.lower()

    def test_run_dir_with_one_engine(self, chicago_bundle: Path, tmp_path: Path) -> None:
        from visualization.coverage import discover_bundle, discover_run_cells
        # Synthesize a run dir with sumo seed_42 only
        run_dir = tmp_path / "run"
        cell_dir = run_dir / "sumo" / "meso" / "seed_42"
        cell_dir.mkdir(parents=True)
        (cell_dir / "tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")

        cov = discover_bundle(chicago_bundle, scenario_id="tiny")
        cov = discover_run_cells(run_dir, cov)
        assert cov.engines_with_results == {"sumo"}
        ok, _ = cov.map_generatable("link_load")
        assert ok
        ok, reason = cov.map_generatable("route_diversity")
        assert not ok
        assert "need >= 2 engines" in reason

    def test_run_dir_with_two_engines_unlocks_route_diversity(
        self, chicago_bundle: Path, tmp_path: Path
    ) -> None:
        from visualization.coverage import discover_bundle, discover_run_cells
        run_dir = tmp_path / "run"
        for engine, fname in [("sumo", "tripinfo.xml"),
                              ("matsim", "output/output_trips.csv.gz")]:
            cell_dir = run_dir / engine / "meso" / "seed_42"
            cell_dir.mkdir(parents=True)
            (cell_dir / fname).parent.mkdir(parents=True, exist_ok=True)
            (cell_dir / fname).write_text("x", encoding="utf-8")

        cov = discover_bundle(chicago_bundle, scenario_id="tiny")
        cov = discover_run_cells(run_dir, cov)
        assert cov.engines_with_results == {"sumo", "matsim"}
        ok, _ = cov.map_generatable("route_diversity")
        assert ok

    def test_format_coverage_matrix_includes_all_map_types(
        self, chicago_bundle: Path
    ) -> None:
        from visualization.coverage import (
            ALL_MAP_TYPES, discover_bundle, format_coverage_matrix,
        )
        cov = discover_bundle(chicago_bundle, scenario_id="tiny")
        report = format_coverage_matrix(cov)
        for map_type in ALL_MAP_TYPES:
            assert map_type in report


# ---------------------------------------------------------------------------
# OD density renderer
# ---------------------------------------------------------------------------


class TestOdDensityRenderer:
    def test_renders_origin_png(self, chicago_bundle: Path, tmp_path: Path) -> None:
        from visualization.data.bundle import load_demand, load_network
        from visualization.render.od_density import render_od_density

        net = load_network(chicago_bundle / "network.xml")
        dem = load_demand(chicago_bundle / "demand.csv")
        out = tmp_path / "od_origins.png"
        result = render_od_density(net, dem, side="origin", output_path=out, gridsize=10)
        assert result == out
        assert out.is_file()
        assert out.stat().st_size > 1000  # non-trivial PNG

    def test_renders_destination_png(self, chicago_bundle: Path, tmp_path: Path) -> None:
        from visualization.data.bundle import load_demand, load_network
        from visualization.render.od_density import render_od_density

        net = load_network(chicago_bundle / "network.xml")
        dem = load_demand(chicago_bundle / "demand.csv")
        out = tmp_path / "od_destinations.png"
        render_od_density(net, dem, side="destination", output_path=out, gridsize=10)
        assert out.is_file()

    def test_invalid_side_raises(self, chicago_bundle: Path, tmp_path: Path) -> None:
        from visualization.data.bundle import load_demand, load_network
        from visualization.render.od_density import render_od_density

        net = load_network(chicago_bundle / "network.xml")
        dem = load_demand(chicago_bundle / "demand.csv")
        with pytest.raises(ValueError):
            render_od_density(net, dem, side="bogus", output_path=tmp_path / "x.png")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_dry_run_prints_coverage_and_returns_zero(
        self, chicago_bundle: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        from visualization.generate_maps import main
        monkeypatch.chdir(tmp_path)
        rc = main([
            "--scenario", "tiny",
            "--bundle-dir", str(chicago_bundle),
            "--dry-run",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tiny" in out
        assert "od_origins" in out
        assert "dry run" in out.lower()

    def test_unknown_map_type_errors(
        self, chicago_bundle: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        from visualization.generate_maps import main
        monkeypatch.chdir(tmp_path)
        rc = main([
            "--scenario", "tiny",
            "--bundle-dir", str(chicago_bundle),
            "--maps", "od_origins,bogus_map",
        ])
        assert rc == 2
        err = capsys.readouterr().err
        assert "bogus_map" in err

    def test_render_writes_png(
        self, chicago_bundle: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from visualization.generate_maps import main
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "out"
        rc = main([
            "--scenario", "tiny",
            "--bundle-dir", str(chicago_bundle),
            "--maps", "od_origins",
            "--output", str(out_dir),
            "--gridsize", "10",
        ])
        assert rc == 0
        assert (out_dir / "od_origins.png").is_file()
