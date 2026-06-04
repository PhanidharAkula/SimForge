"""SimForge visualization component.

A standalone, opt-in module for geographic visualizations from SimForge
bundles and benchmark results. The main workflow (generate.py /
run_benchmark.py / analyze_benchmark) never calls it; you run it yourself
once the data is on disk.

Entry point::

    python -m visualization.generate_maps --scenario <id> --maps <list>

See visualization/README.md for the full user guide and the data-tier
matrix that determines which maps are generatable from which inputs.
"""
