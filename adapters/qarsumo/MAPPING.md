# QarSUMO Adapter Mapping

## Overview

QarSUMO is a GPU-accelerated traffic simulator that provides a SUMO-compatible interface with significantly improved performance on large-scale scenarios. It maintains compatibility with SUMO's network and route formats while replacing the core simulation engine with GPU-based parallelization.

**Key Reference**: QarSUMO: A Parallel, Congestion-optimized Traffic Simulator (IEEE ITSC 2020)

## Relationship to SUMO

QarSUMO reuses SUMO's input formats:

- **Network files** (`.net.xml`): 100% compatible
- **Route files** (`.rou.xml`): 100% compatible
- **Configuration files** (`.sumocfg`): Mostly compatible with additional GPU options
- **Traffic lights**: Fully compatible

This means our SUMO adapter can be reused with minimal modifications.

## Key Differences from SUMO

| Aspect          | SUMO                      | QarSUMO                      |
| --------------- | ------------------------- | ---------------------------- |
| Execution       | CPU, single-threaded core | GPU, massively parallel      |
| Scalability     | ~100K vehicles practical  | 1M+ vehicles demonstrated    |
| Output format   | XML files                 | Same XML + optional binary   |
| Installation    | `apt install sumo`        | Custom build with CUDA       |
| Mesoscopic mode | `--mesosim`               | Not needed (fast by default) |

## Canonical → QarSUMO Mapping

Since QarSUMO uses SUMO's input formats, the mapping is identical:

### Network Mapping

Same as SUMO adapter - see `adapters/sumo/MAPPING.md`.

### Demand Mapping

Same as SUMO adapter - generates identical `.rou.xml` files.

### Signals Mapping

Same as SUMO adapter - identical traffic light format.

### Config Mapping

The `.sumocfg` file is extended with QarSUMO-specific options:

```xml
<configuration>
    <input>
        <net-file value="network.net.xml"/>
        <route-files value="routes.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="86400"/>
        <step-length value="0.1"/>
    </time>
    <output>
        <tripinfo-output value="tripinfo.xml"/>
    </output>

    <!-- QarSUMO-specific options -->
    <qarsumo>
        <gpu-device value="0"/>
        <batch-size value="10000"/>
        <stream-count value="4"/>
    </qarsumo>
</configuration>
```

## QarSUMO-Specific Options

| Option         | Default | Description                       |
| -------------- | ------- | --------------------------------- |
| `gpu-device`   | 0       | CUDA device index                 |
| `batch-size`   | 10000   | Vehicles processed per GPU batch  |
| `stream-count` | 4       | CUDA streams for parallelism      |
| `precision`    | float32 | `float32` or `float16` for memory |

## Adapter Implementation Strategy

1. **Reuse SUMO adapter**: Call `prepare_sumo_inputs()` to generate base files
2. **Extend config**: Add QarSUMO options to `.sumocfg`
3. **Execution**: Replace `sumo` command with `qarsumo`

```python
# Pseudo-code
def prepare_qarsumo_inputs(scenario_path, output_dir, gpu_options=None):
    # Step 1: Generate SUMO inputs (network, routes, base config)
    prepare_sumo_inputs(scenario_path, output_dir)

    # Step 2: Extend config with QarSUMO options
    extend_config_for_qarsumo(output_dir, gpu_options)

    return output_dir
```

## Output Format

QarSUMO produces the same `tripinfo.xml` format as SUMO:

```xml
<tripinfos>
    <tripinfo id="trip_1"
              depart="100.0"
              arrival="450.5"
              duration="350.5"
              waitingTime="25.3"
              routeLength="1523.7"/>
</tripinfos>
```

This means our existing metrics (`evaluation/metrics/travel_time.py`) work without modification.

## Environment Requirements

| Component | Requirement                     |
| --------- | ------------------------------- |
| GPU       | NVIDIA, Compute Capability 6.0+ |
| CUDA      | 11.0+                           |
| Memory    | 8GB+ VRAM for 500K vehicles     |
| Driver    | 450.0+                          |

## Execution Commands

```bash
# Local GPU
qarsumo -c scenario.sumocfg --gpu-device 0

# Multi-GPU (data parallel)
mpirun -np 4 qarsumo -c scenario.sumocfg --gpu-device 0,1,2,3

# HPC with SLURM
srun --gres=gpu:1 qarsumo -c scenario.sumocfg
```

## Expected Performance

Based on QarSUMO paper benchmarks:

| Scenario Size | SUMO (CPU) | QarSUMO (GPU) | Speedup |
| ------------- | ---------- | ------------- | ------- |
| 50K trips     | ~3 hours   | ~5 minutes    | ~36x    |
| 500K trips    | ~30 hours  | ~20 minutes   | ~90x    |
| 5M trips      | Days       | ~3 hours      | ~100x+  |

## Validation Strategy

1. Run both SUMO and QarSUMO on toy scenario
2. Compare `tripinfo.xml` outputs
3. Compute fidelity metrics (RMSE, MAPE) between outputs
4. Expected: Near-identical results (< 1% deviation due to floating point)
