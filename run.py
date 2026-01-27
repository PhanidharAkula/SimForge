#!/usr/bin/env python3
"""
SimForge Runner - Unified CLI for running traffic simulations.

This script provides a simple interface for:
  - Selecting scenarios (cities, demand tiers)
  - Selecting engines (SUMO, QarSUMO, MATSim)
  - Selecting simulation mode (microscopic vs mesoscopic)
  - Running benchmarks

Usage:
    # Interactive mode
    python run.py
    
    # Quick commands
    python run.py --scenario toy_2x2_grid --engine sumo --mode meso
    python run.py --scenario sioux_falls_tier50k --engine sumo --mode micro
    python run.py --runspec runspecs/dev_mesoscopic.yaml
    
    # List available options
    python run.py --list
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Available scenarios
SCENARIOS = {
    "toy": {
        "path": "scenarios/toy_2x2_grid",
        "id": "toy_2x2_grid",
        "description": "Tiny 2x2 grid (6 trips) - for quick testing"
    },
    # City 1: Sioux Falls, SD
    "sioux_falls_50k": {
        "path": "scenarios/sioux_falls_tier50k", 
        "id": "sioux_falls_tier50k",
        "description": "Sioux Falls (~50K trips) - City 1"
    },
    # City 2: Austin, TX
    "austin_50k": {
        "path": "scenarios/austin_tier50k",
        "id": "austin_tier50k", 
        "description": "Austin, TX (~50K trips) - City 2"
    },
    # City 3: Berlin, Germany
    "berlin_50k": {
        "path": "scenarios/berlin_tier50k",
        "id": "berlin_tier50k",
        "description": "Berlin, Germany (~50K trips) - City 3"
    },
}

# Available engines
ENGINES = {
    "sumo": {
        "name": "SUMO",
        "description": "CPU-based microscopic/mesoscopic simulator",
        "installed": True,
    },
    "qarsumo": {
        "name": "QarSUMO", 
        "description": "GPU-accelerated SUMO (falls back to SUMO without GPU)",
        "installed": False,  # Requires NVIDIA GPU + CUDA
    },
    "matsim": {
        "name": "MATSim",
        "description": "Activity-based mesoscopic simulator (requires Java + MATSim JAR)",
        "installed": True,  # Now installed in lib/matsim-15.0/
    },
}

# Simulation modes
MODES = {
    "micro": {
        "name": "microscopic",
        "description": "High fidelity, slower (~3-4 hours for 50K trips)",
        "flag": "",
    },
    "meso": {
        "name": "mesoscopic", 
        "description": "Faster approximation (~5 seconds for 50K trips)",
        "flag": "--mesoscopic",
    },
}

# Predefined runspecs
RUNSPECS = {
    "dev": "runspecs/dev_mesoscopic.yaml",
    "final": "runspecs/final_microscopic.yaml",
    "multi": "runspecs/multi_engine.yaml",
    "hpc": "runspecs/hpc_matrix_sumo.yaml",
}


def list_options():
    """Print all available options."""
    print("\n" + "=" * 60)
    print("SimForge - Available Options")
    print("=" * 60)
    
    print("\n📦 SCENARIOS:")
    print("-" * 40)
    for key, info in SCENARIOS.items():
        print(f"  {key:20} - {info['description']}")
    
    print("\n🔧 ENGINES:")
    print("-" * 40)
    for key, info in ENGINES.items():
        status = "✓ installed" if info["installed"] else "⚠ not installed"
        print(f"  {key:20} - {info['description']}")
        print(f"  {' '*20}   ({status})")
    
    print("\n⚙️  MODES:")
    print("-" * 40)
    for key, info in MODES.items():
        print(f"  {key:20} - {info['description']}")
    
    print("\n📋 RUNSPECS (predefined configs):")
    print("-" * 40)
    for key, path in RUNSPECS.items():
        print(f"  {key:20} - {path}")
    
    print("\n" + "=" * 60)


def run_quick(scenario: str, engine: str, mode: str, repeats: int = 1):
    """Run a quick single scenario."""
    if scenario not in SCENARIOS:
        print(f"❌ Unknown scenario: {scenario}")
        print(f"   Available: {list(SCENARIOS.keys())}")
        return 1
    
    if engine not in ENGINES:
        print(f"❌ Unknown engine: {engine}")
        print(f"   Available: {list(ENGINES.keys())}")
        return 1
    
    if mode not in MODES:
        print(f"❌ Unknown mode: {mode}")
        print(f"   Available: {list(MODES.keys())}")
        return 1
    
    scenario_info = SCENARIOS[scenario]
    mode_info = MODES[mode]
    engine_info = ENGINES[engine]
    
    print("\n" + "=" * 60)
    print("SimForge - Quick Run")
    print("=" * 60)
    print(f"  Scenario: {scenario_info['id']}")
    print(f"  Engine:   {engine_info['name']}")
    print(f"  Mode:     {mode_info['name']}")
    print(f"  Repeats:  {repeats}")
    print("=" * 60 + "\n")
    
    # Build command based on engine
    if engine == "matsim":
        # MATSim uses its own CLI
        output_dir = f"out/{scenario}_{engine}"
        cmd = [
            sys.executable, "-m", "adapters.matsim.cli",
            scenario_info["path"],
            output_dir,
        ]
        if mode == "meso":
            cmd.append("--mesoscopic")
    else:
        # SUMO and QarSUMO use the standard runner
        cmd = [
            sys.executable, "-m", "execution.run_sumo_scenario",
            scenario_info["path"],
            "--engine", engine,
        ]
        
        if mode == "meso":
            cmd.append("--mesoscopic")
        
        if repeats > 1:
            cmd.extend(["--repeats", str(repeats)])
    
    print(f"Running: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd)
        return result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted")
        return 130


def run_runspec(runspec_key_or_path: str, scenario_filter: str = None):
    """Run a predefined or custom runspec."""
    # Check if it's a predefined key
    if runspec_key_or_path in RUNSPECS:
        runspec_path = RUNSPECS[runspec_key_or_path]
    else:
        runspec_path = runspec_key_or_path
    
    if not Path(runspec_path).exists():
        print(f"❌ Runspec not found: {runspec_path}")
        return 1
    
    print("\n" + "=" * 60)
    print("SimForge - Runspec Execution")
    print("=" * 60)
    print(f"  Runspec: {runspec_path}")
    if scenario_filter:
        print(f"  Filter:  {scenario_filter}")
    print("=" * 60 + "\n")
    
    cmd = [
        sys.executable, "-m", "execution.run_benchmark",
        runspec_path,
    ]
    
    if scenario_filter:
        cmd.extend(["--scenario", scenario_filter])
    
    print(f"Running: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd)
        return result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted")
        return 130


def interactive_mode():
    """Interactive menu for running simulations."""
    print("\n" + "=" * 60)
    print("SimForge - Interactive Mode")
    print("=" * 60)
    
    print("\nWhat would you like to do?")
    print("  1. Quick run (select scenario, engine, mode)")
    print("  2. Run predefined runspec")
    print("  3. List all options")
    print("  4. Exit")
    
    choice = input("\nChoice [1-4]: ").strip()
    
    if choice == "1":
        print("\n--- Select Scenario ---")
        for i, (key, info) in enumerate(SCENARIOS.items(), 1):
            print(f"  {i}. {key}: {info['description']}")
        scenario_idx = int(input("Scenario [1]: ").strip() or "1") - 1
        scenario = list(SCENARIOS.keys())[scenario_idx]
        
        print("\n--- Select Engine ---")
        for i, (key, info) in enumerate(ENGINES.items(), 1):
            status = "✓" if info["installed"] else "⚠"
            print(f"  {i}. {key}: {info['name']} ({status})")
        engine_idx = int(input("Engine [1]: ").strip() or "1") - 1
        engine = list(ENGINES.keys())[engine_idx]
        
        print("\n--- Select Mode ---")
        for i, (key, info) in enumerate(MODES.items(), 1):
            print(f"  {i}. {key}: {info['description']}")
        mode_idx = int(input("Mode [2=meso]: ").strip() or "2") - 1
        mode = list(MODES.keys())[mode_idx]
        
        repeats = int(input("\nRepeats [1]: ").strip() or "1")
        
        return run_quick(scenario, engine, mode, repeats)
    
    elif choice == "2":
        print("\n--- Select Runspec ---")
        for i, (key, path) in enumerate(RUNSPECS.items(), 1):
            print(f"  {i}. {key}: {path}")
        runspec_idx = int(input("Runspec [1]: ").strip() or "1") - 1
        runspec = list(RUNSPECS.keys())[runspec_idx]
        
        filter_input = input("Scenario filter (blank for all): ").strip()
        
        return run_runspec(runspec, filter_input if filter_input else None)
    
    elif choice == "3":
        list_options()
        return 0
    
    else:
        print("Goodbye!")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="SimForge Runner - Run traffic simulations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python run.py
  
  # Quick run with options
  python run.py --scenario toy --engine sumo --mode meso
  python run.py --scenario sioux_falls_50k --engine sumo --mode micro
  
  # Run predefined runspec
  python run.py --runspec dev
  python run.py --runspec final --filter sioux_falls
  
  # List options
  python run.py --list
"""
    )
    
    parser.add_argument("--scenario", "-s", help="Scenario key (toy, sioux_falls_50k)")
    parser.add_argument("--engine", "-e", default="sumo", help="Engine (sumo, qarsumo, matsim)")
    parser.add_argument("--mode", "-m", default="meso", help="Mode (micro, meso)")
    parser.add_argument("--repeats", "-r", type=int, default=1, help="Number of repeats")
    parser.add_argument("--runspec", help="Run a predefined or custom runspec")
    parser.add_argument("--filter", help="Scenario filter for runspec")
    parser.add_argument("--list", "-l", action="store_true", help="List available options")
    
    args = parser.parse_args()
    
    # List mode
    if args.list:
        list_options()
        return 0
    
    # Runspec mode
    if args.runspec:
        return run_runspec(args.runspec, args.filter)
    
    # Quick mode
    if args.scenario:
        return run_quick(args.scenario, args.engine, args.mode, args.repeats)
    
    # Interactive mode
    return interactive_mode()


if __name__ == "__main__":
    sys.exit(main())
