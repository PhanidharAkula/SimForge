#!/usr/bin/env python3
"""
Inspect a SimForge canonical network.xml for degenerate edges and length
distribution. Useful as a sanity sweep after generating a new scenario, and
as a paste-free alternative to ad-hoc Python over SSH.

Usage:
    python tools/inspect_network.py scenarios/nyc_500k_car
    python tools/inspect_network.py scenarios/nyc_500k_car --show-zeros 100

Reports:
    - Total link count
    - Length distribution buckets (=0, <0.1, <1, <10, <100, >=100 m)
    - Sample of zero-length links with their from/to nodes and OSM way IDs
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a canonical network.xml for degenerate edges.",
    )
    parser.add_argument(
        "scenario_dir",
        type=Path,
        help="Path to a scenario directory containing network.xml",
    )
    parser.add_argument(
        "--show-zeros",
        type=int,
        default=20,
        metavar="N",
        help="Print up to N zero-length link entries (default: 20)",
    )
    args = parser.parse_args()

    network_path = args.scenario_dir / "network.xml"
    if not network_path.is_file():
        print(f"ERROR: {network_path} not found", file=sys.stderr)
        return 1

    print(f"Parsing {network_path} ...")
    try:
        tree = ET.parse(network_path)
    except ET.ParseError as e:
        print(f"ERROR: {network_path} is not valid XML: {e}", file=sys.stderr)
        return 1
    links_elem = tree.getroot().find("links")
    if links_elem is None:
        print(f"ERROR: <links> element missing in {network_path}", file=sys.stderr)
        return 1
    links = links_elem.findall("link")

    print(f"Total links: {len(links):,}")
    print()
    print("Length distribution (meters):")

    buckets: Counter[str] = Counter()
    zeros: list[tuple[str, str, str, str | None]] = []
    for link in links:
        try:
            length_m = float(link.get("length", "0"))
        except (TypeError, ValueError):
            # A non-numeric length is malformed; bucket it as zero-length so the
            # report surfaces it rather than crashing on the whole file.
            length_m = 0.0
        if length_m == 0.0:
            zeros.append((
                link.get("id", "?"),
                link.get("from", "?"),
                link.get("to", "?"),
                link.get("osm_way_id"),
            ))
            buckets["=0"] += 1
        elif length_m < 0.1:
            buckets["<0.1"] += 1
        elif length_m < 1:
            buckets["<1"] += 1
        elif length_m < 10:
            buckets["<10"] += 1
        elif length_m < 100:
            buckets["<100"] += 1
        else:
            buckets[">=100"] += 1

    total = len(links) or 1
    for label in ("=0", "<0.1", "<1", "<10", "<100", ">=100"):
        n = buckets.get(label, 0)
        pct = n / total * 100
        print(f"  {label:>6}  {n:>10,}  {pct:>7.4f}%")

    if zeros:
        cap = args.show_zeros
        print()
        print(f"Zero-length links ({len(zeros)} total, showing up to {cap}):")
        for z in zeros[:cap]:
            print(f"  id={z[0]:<10} from={z[1]:<10} to={z[2]:<10} osm_way_id={z[3]}")
        if len(zeros) > cap:
            print(f"  ... {len(zeros) - cap} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
