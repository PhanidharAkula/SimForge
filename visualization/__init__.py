"""SimForge visualization component.

Standalone, opt-in module for generating geographic visualizations from
SimForge bundles and benchmark results. Not invoked by the main workflow
(generate.py / run_benchmark.py / analyze_benchmark) — users run it
explicitly after data is on disk.

Entry point::

    python -m visualization.generate_maps --scenario <id> --maps <list>

See visualization/README.md for the full user guide and the data-tier
matrix that determines which maps are generatable from which inputs.
"""
