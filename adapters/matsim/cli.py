"""
CLI for MATSim adapter.

Usage:
    python -m adapters.matsim.cli scenarios/toy_2x2_grid out/matsim
    python -m adapters.matsim.cli scenarios/sioux_falls_tier50k out/matsim --run
"""

import argparse
import sys

from adapters.matsim.matsim_adapter import (
    MATSimConfig,
    prepare_matsim_inputs,
    run_matsim,
    parse_matsim_output,
    check_java_available,
    find_matsim_jar,
)
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="MATSim Adapter - Convert canonical bundles to MATSim inputs"
    )
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory for generated files")
    parser.add_argument(
        "--iterations", type=int, default=0,
        help="Number of MATSim iterations (0 = single run, default: 0)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Also run the simulation after generating inputs"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for simulation (default: 42)"
    )
    parser.add_argument(
        "--heap", type=int, default=4,
        help="Java heap size in GB (default: 4)"
    )
    parser.add_argument(
        "--timeout", type=int, default=86400,
        help="Simulation timeout in seconds (default: 86400 = 24h)"
    )
    parser.add_argument(
        "--mesoscopic", action="store_true",
        help="Enable mesoscopic mode (default for MATSim, included for API consistency)"
    )
    
    args = parser.parse_args()
    
    # Check environment
    print("=" * 60)
    print("MATSim Adapter")
    print("=" * 60)
    
    java_ok, java_version = check_java_available()
    if java_ok:
        print(f"\n✓ Java: {java_version}")
    else:
        print(f"\n⚠ Java not found")
        print("  MATSim requires Java 11+ (JDK 17 recommended)")
        print("  Install: brew install openjdk@17")
    
    matsim_jar = find_matsim_jar()
    if matsim_jar:
        print(f"✓ MATSim: {matsim_jar}")
    else:
        print("⚠ MATSim JAR not found")
        print("  Download from: https://github.com/matsim-org/matsim-libs/releases")
        print("  Set MATSIM_HOME environment variable or place in working directory")
    
    print(f"\nScenario: {args.scenario}")
    print(f"Output: {args.output}")
    
    # Create MATSim config
    config = MATSimConfig(
        iterations=args.iterations,
        java_heap_gb=args.heap,
    )
    
    print(f"\nMATSim Config:")
    print(f"  Iterations: {config.iterations} (0 = single run, no replanning)")
    print(f"  Java heap: {config.java_heap_gb} GB")
    
    # Generate inputs
    print("\n" + "-" * 60)
    print("Generating MATSim inputs...")
    print("-" * 60)
    
    try:
        config_path = prepare_matsim_inputs(
            args.scenario, 
            args.output, 
            config, 
            random_seed=args.seed
        )
        print(f"\n✓ MATSim config: {config_path}")
    except Exception as e:
        print(f"\n✗ Failed to generate inputs: {e}")
        sys.exit(1)
    
    # Optionally run simulation
    if args.run:
        print("\n" + "-" * 60)
        print("Running MATSim simulation...")
        print("-" * 60)
        
        if not java_ok:
            print("\n✗ Cannot run without Java")
            print("  Install Java 11+ and try again")
            sys.exit(1)
        
        if not matsim_jar:
            print("\n✗ Cannot run without MATSim")
            print("  Download MATSim JAR and set MATSIM_HOME")
            sys.exit(1)
        
        success, runtime, error = run_matsim(
            config_path,
            timeout_s=args.timeout,
            java_heap_gb=args.heap
        )
        
        if success:
            print(f"\n✓ Simulation completed in {runtime:.2f}s")
            
            # Parse and display results
            output_dir = Path(args.output) / "output"
            stats = parse_matsim_output(output_dir)
            if stats:
                print(f"\nTravel Time Statistics:")
                print(f"  Total trips: {stats['trip_count']}")
                print(f"  Mean: {stats['mean_travel_time_s']:.1f}s")
                print(f"  Median: {stats['median_travel_time_s']:.1f}s")
                print(f"  P95: {stats['p95_travel_time_s']:.1f}s")
                print(f"  Range: {stats['min_travel_time_s']:.1f}s - {stats['max_travel_time_s']:.1f}s")
        else:
            print(f"\n✗ Simulation failed: {error}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
