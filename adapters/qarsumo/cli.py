"""
CLI for QarSUMO adapter.

Usage:
    python -m adapters.qarsumo.cli scenarios/toy_2x2_grid out/qarsumo
    python -m adapters.qarsumo.cli scenarios/sioux_falls_tier50k out/qarsumo --run
"""

from adapters.qarsumo.qarsumo_adapter import (
    QarSUMOConfig,
    prepare_qarsumo_inputs,
    run_qarsumo,
    get_gpu_info,
)

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="QarSUMO Adapter - Convert canonical bundles to QarSUMO inputs"
    )
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory for generated files")
    parser.add_argument(
        "--gpu-device", type=int, default=0,
        help="CUDA device index (default: 0)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10000,
        help="GPU batch size for vehicle processing (default: 10000)"
    )
    parser.add_argument(
        "--stream-count", type=int, default=4,
        help="Number of CUDA streams (default: 4)"
    )
    parser.add_argument(
        "--precision", choices=["float32", "float16"], default="float32",
        help="Floating point precision (default: float32)"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Also run the simulation after generating inputs"
    )
    parser.add_argument(
        "--seed", type=int,
        help="Random seed for simulation"
    )
    parser.add_argument(
        "--timeout", type=int, default=86400,
        help="Simulation timeout in seconds (default: 86400 = 24h)"
    )
    
    args = parser.parse_args()
    
    # Check GPU availability
    print("=" * 60)
    print("QarSUMO Adapter")
    print("=" * 60)
    
    gpu_info = get_gpu_info()
    if gpu_info["available"]:
        print(f"\n✓ GPU(s) detected: {gpu_info['count']}")
        for dev in gpu_info["devices"]:
            marker = " ← selected" if dev["index"] == args.gpu_device else ""
            print(f"  [{dev['index']}] {dev['name']} ({dev['memory']}){marker}")
    else:
        print("\n⚠ No NVIDIA GPU detected")
        print("  QarSUMO will fall back to SUMO (CPU-based)")
    
    print(f"\nScenario: {args.scenario}")
    print(f"Output: {args.output}")
    
    # Create QarSUMO config
    config = QarSUMOConfig(
        gpu_device=args.gpu_device,
        batch_size=args.batch_size,
        stream_count=args.stream_count,
        precision=args.precision,
    )
    
    print(f"\nGPU Config:")
    print(f"  Device: {config.gpu_device}")
    print(f"  Batch size: {config.batch_size}")
    print(f"  Streams: {config.stream_count}")
    print(f"  Precision: {config.precision}")
    
    # Generate inputs
    print("\n" + "-" * 60)
    print("Generating QarSUMO inputs...")
    print("-" * 60)
    
    try:
        config_path = prepare_qarsumo_inputs(args.scenario, args.output, config)
        print(f"\n✓ QarSUMO config: {config_path}")
    except Exception as e:
        print(f"\n✗ Failed to generate inputs: {e}")
        sys.exit(1)
    
    # Optionally run simulation
    if args.run:
        print("\n" + "-" * 60)
        print("Running QarSUMO simulation...")
        print("-" * 60)
        
        success, runtime, error = run_qarsumo(
            config_path,
            timeout_s=args.timeout,
            seed=args.seed,
            gpu_device=args.gpu_device
        )
        
        if success:
            print(f"\n✓ Simulation completed in {runtime:.2f}s")
            
            # Check for output files
            output_dir = config_path.parent
            tripinfo = output_dir / "tripinfo.xml"
            if tripinfo.exists():
                print(f"  Trip info: {tripinfo}")
        else:
            print(f"\n✗ Simulation failed: {error}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
