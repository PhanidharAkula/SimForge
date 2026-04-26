#!/bin/bash
# ============================================================================
# SimForge benchmark — small tier (3 scenarios × SUMO + MATSim × meso+micro).
#
# Runs runspecs/benchmark_small.yaml with three parallel python workers,
# one per scenario, each writing to its own --output dir to avoid the
# per-runspec result JSON colliding (the harness names that JSON after
# the runspec, not the scenario).
#
# Wall-clock budget:
#   Sequential worst case ~16 h dominated by la_50k microscopic (sumo
#   × 3 repeats × 4 h timeout each = 12 h). Parallelising per-scenario
#   doesn't help la_50k itself, but chicago_1k and nyc_10k workers finish
#   in ~30 min and ~2 h respectively, leaving la_50k as the wall-time floor.
#   Budget set to 18 h for headroom.
#
# Resources:
#   --partition=hugemem-cascade or cpu : SUMO + MATSim are CPU-only with
#                            QarSUMO dropped. Use the standard cpu partition.
#   --cpus-per-task=16     : 3 parallel scenarios × ~2 cores each + python
#                            overhead + post-step analyzer fits comfortably.
#   --mem=64G              : Peak per-scenario memory ~5 GB; 3 in parallel
#                            ≤ 20 GB; 64 GB has headroom (la_50k microscopic
#                            can spike).
#   --time=18:00:00        : See wall-clock budget above.
#
# Note: the GPU partition is no longer required. Once LPSim lands as the
# 3rd primary engine (todo.md Phase B), switch back to:
#   --partition=gpu --gres=gpu:v100:1
# since LPSim needs CUDA.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/benchmark_small.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_small
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=18:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail

mkdir -p logs                # defensive: SLURM silently fails if logs/ missing
module load openjdk/21.0.3_9 # MATSim runtime — Pitzer's lmod requires explicit version
cd ~/SimForge
source .venv/bin/activate    # uv-managed venv with eclipse-sumo + matsim

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — every scenario referenced in the runspec must validate.
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundles ==="
SCENARIOS=(chicago_1k_car nyc_10k_car la_50k_bike_car_transit)
for s in "${SCENARIOS[@]}"; do
    if [ ! -f "scenarios/$s/manifest.xml" ]; then
        echo "MISSING bundle: scenarios/$s/ — git pull (it should be tracked)."
        exit 1
    fi
    python -m pipeline.validation.validate_bundle "scenarios/$s"
done
echo

# ---------------------------------------------------------------------------
# 2. Launch 3 parallel benchmark workers, one per scenario.
# ---------------------------------------------------------------------------
echo "=== Launching 3 parallel workers (one per scenario) ==="
mkdir -p runs/benchmark_small

for s in "${SCENARIOS[@]}"; do
    out="runs/benchmark_small/$s"
    log="logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}_${s}.log"
    echo "  -> $s  (output=$out, log=$log)"
    python -u -m execution.run_benchmark runspecs/benchmark_small.yaml \
        --scenario "$s" \
        --output   "$out" \
        > "$log" 2>&1 &
done

echo
echo "=== Waiting for all 3 workers to finish ==="
wait
echo "=== All 3 workers complete at $(date) ==="
echo

# ---------------------------------------------------------------------------
# 3. Combined analysis over the 3 per-scenario result JSONs.
# ---------------------------------------------------------------------------
echo "=== Aggregating results across all scenarios ==="
RESULTS=(runs/benchmark_small/*/benchmark_results_benchmark_small.json)
echo "Found ${#RESULTS[@]} result files:"
printf '  %s\n' "${RESULTS[@]}"
echo

echo "--- Markdown summary table ---"
python -m evaluation.analyze_benchmark "${RESULTS[@]}" --markdown \
    | tee runs/benchmark_small/summary.md

echo
echo "--- Generating thesis figures ---"
python -m evaluation.generate_plots "${RESULTS[@]}" \
    --output runs/benchmark_small/plots
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSONs: runs/benchmark_small/*/benchmark_results_benchmark_small.json"
echo "Combined summary:    runs/benchmark_small/summary.md"
echo "Plots:               runs/benchmark_small/plots/"
