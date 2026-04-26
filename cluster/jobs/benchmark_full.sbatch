#!/bin/bash
# ============================================================================
# SimForge — full end-to-end benchmark (all scenarios × all engines × all
# practical modes × default repeats), parallelised by scenario.
#
# Strategy:
#   The harness in execution/run_benchmark.py is single-threaded — it walks
#   the runspec sequentially. To use Pitzer's cores, we launch FIVE python
#   invocations in parallel (one per scenario), each filtered with --scenario
#   and writing to its own --output subdir so the per-runspec results JSON
#   (which is named after the runspec, not the scenario) doesn't collide.
#
#   After all 5 finish, the post-step runs analyze_benchmark + generate_plots
#   over the combined set of result JSONs (generate_plots accepts multiple
#   positional args).
#
# Wall-clock budget:
#   Sequential total would be roughly 9–12 h on a Pitzer cpu node (bottleneck
#   is the 500K-NYC mesoscopic SUMO/QarSUMO runs at ~30 min each × 3 repeats
#   × 3 engines ≈ 4.5 h, plus la_50k microscopic ≈ 2–4 h). Parallelising
#   per-scenario brings that down to roughly the slowest single scenario's
#   share — about 4–6 h. The 12 h SBATCH wall is generous safety margin.
#
# Resources:
#   --partition=gpu        : QarSUMO needs CUDA. Without GPU it falls back to
#                            standard SUMO and effectively duplicates the SUMO
#                            runs (cheaper but less informative).
#   --gres=gpu:v100:1      : One V100 is enough — concurrent QarSUMO runs
#                            from the parallel scenarios share the GPU via
#                            CUDA's scheduler (slight contention, no failure).
#   --cpus-per-task=16     : Each scenario worker uses 1–2 cores at any moment;
#                            16 covers the 5 parallel processes plus python
#                            overhead and the post-step analyzer comfortably.
#   --mem=96G              : Peak per-scenario memory ~10 GB (NYC-500K demand
#                            generation already proved this); 5 in parallel
#                            ≤ 50 GB; 96 GB has headroom.
#   --time=12:00:00        : See wall-clock budget above.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/benchmark_full.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_full
#SBATCH --partition=gpu
#SBATCH --gres=gpu:v100:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail

module load openjdk/21.0.3_9 # MATSim runtime — Pitzer's lmod requires an explicit version
cd ~/SimForge
source .venv/bin/activate    # uv-managed venv with eclipse-sumo + matsim

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv 2>&1 | head -3 || echo "nvidia-smi unavailable"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — every scenario referenced in the runspec must validate or
#    we fail fast (no point burning 5 h before discovering nyc_500k is missing).
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundles ==="
SCENARIOS=(chicago_1k_car nyc_10k_car la_50k_bike_car_transit chicago_200k_car_transit nyc_500k_car)
for s in "${SCENARIOS[@]}"; do
    if [ ! -f "scenarios/$s/manifest.xml" ]; then
        echo "MISSING bundle: scenarios/$s/ — rsync from your dev box first."
        exit 1
    fi
    python -m pipeline.validation.validate_bundle "scenarios/$s"
done
echo

# ---------------------------------------------------------------------------
# 2. Launch 5 parallel benchmark workers, one per scenario.
#    Each writes to its own --output subdir so per-runspec JSONs are isolated.
# ---------------------------------------------------------------------------
echo "=== Launching 5 parallel workers (one per scenario) ==="
mkdir -p runs/benchmark_full

for s in "${SCENARIOS[@]}"; do
    out="runs/benchmark_full/$s"
    log="logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}_${s}.log"
    echo "  -> $s  (output=$out, log=$log)"
    python -u -m execution.run_benchmark runspecs/benchmark_full.yaml \
        --scenario "$s" \
        --output   "$out" \
        > "$log" 2>&1 &
done

echo
echo "=== Waiting for all 5 workers to finish ==="
wait
echo "=== All 5 workers complete at $(date) ==="
echo

# ---------------------------------------------------------------------------
# 3. Combined analysis over all 5 per-scenario result JSONs.
# ---------------------------------------------------------------------------
echo "=== Aggregating results across all scenarios ==="
RESULTS=(runs/benchmark_full/*/benchmark_results_benchmark_full.json)
echo "Found ${#RESULTS[@]} result files:"
printf '  %s\n' "${RESULTS[@]}"
echo

echo "--- Markdown summary table ---"
python -m evaluation.analyze_benchmark "${RESULTS[@]}" --markdown \
    | tee runs/benchmark_full/summary.md

echo
echo "--- Generating thesis figures ---"
python -m evaluation.generate_plots "${RESULTS[@]}" \
    --output runs/benchmark_full/plots
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSONs: runs/benchmark_full/*/benchmark_results_benchmark_full.json"
echo "Combined summary:    runs/benchmark_full/summary.md"
echo "Plots:               runs/benchmark_full/plots/"
