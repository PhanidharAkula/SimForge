#!/bin/bash
# ============================================================================
# SimForge benchmark — large tier (chicago_200k_car_transit + nyc_500k_car).
#
# ⚠️ THIS JOB CURRENTLY EXCEEDS WALL TIME on the unmodified codebase.
#    The SUMO adapter pre-routes every trip via BFS on the canonical graph
#    BEFORE handing off to the simulator. Measured cost on chicago_200k:
#    ~17 h per (engine, seed). With 3 sumo + 2 matsim runs that's ~85 h
#    of routing — inside the cpu wall (168 h) but tight. nyc_500k is worse.
#
#    Until the SUMO adapter caches routes per (origin, destination) — or
#    parallelises the BFS pass — this sbatch may SLURM-timeout. Use
#    cluster/jobs/benchmark_small.sbatch for jobs that finish today.
#
# Resources (when the bottleneck is fixed):
#   --partition=cpu, 16 cores, 96 GB, 168 h wall (max for cpu partition).
#
# Note: the GPU partition is no longer required. Once LPSim lands as the
# 3rd primary engine (todo.md Phase B), switch back to:
#   --partition=gpu --gres=gpu:v100:1
# since LPSim needs CUDA.
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_large
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=96:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail

mkdir -p logs                # defensive: SLURM silently fails if logs/ missing
module load openjdk/21.0.3_9 # MATSim runtime — Pitzer's lmod requires explicit version
cd ~/SimForge
source .venv/bin/activate

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
echo
echo "⚠️  Reminder: BFS routing pre-step may exceed the wall."
echo "    See header comment for context."
echo

# ---------------------------------------------------------------------------
# 1. Preflight — both 200K and 500K bundles must be present (gitignored,
#    rsync from your dev box first).
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundles ==="
SCENARIOS=(chicago_200k_car_transit nyc_500k_car)
for s in "${SCENARIOS[@]}"; do
    if [ ! -f "scenarios/$s/manifest.xml" ]; then
        echo "MISSING bundle: scenarios/$s/ — rsync from your dev box first."
        echo "    rsync -avh --progress scenarios/$s/ pitzer:SimForge/scenarios/$s/"
        exit 1
    fi
    python -m pipeline.validation.validate_bundle "scenarios/$s"
done
echo

# ---------------------------------------------------------------------------
# 2. Launch 2 parallel benchmark workers, one per scenario.
# ---------------------------------------------------------------------------
echo "=== Launching 2 parallel workers (one per scenario) ==="
mkdir -p runs/benchmark_large

for s in "${SCENARIOS[@]}"; do
    out="runs/benchmark_large/$s"
    log="logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}_${s}.log"
    echo "  -> $s  (output=$out, log=$log)"
    python -u -m execution.run_benchmark runspecs/benchmark_large.yaml \
        --scenario "$s" \
        --output   "$out" \
        > "$log" 2>&1 &
done

echo
echo "=== Waiting for all 2 workers to finish ==="
wait
echo "=== All 2 workers complete at $(date) ==="
echo

# ---------------------------------------------------------------------------
# 3. Combined analysis over the 2 per-scenario result JSONs (whatever
#    completed before the wall expired).
# ---------------------------------------------------------------------------
echo "=== Aggregating results across all scenarios ==="
RESULTS=(runs/benchmark_large/*/benchmark_results_benchmark_large.json)
if [ ! -f "${RESULTS[0]}" ]; then
    echo "No result files produced — both workers likely hit the wall before finishing."
    exit 0
fi
echo "Found ${#RESULTS[@]} result files:"
printf '  %s\n' "${RESULTS[@]}"
echo

echo "--- Markdown summary table ---"
python -m evaluation.analyze_benchmark "${RESULTS[@]}" --markdown \
    | tee runs/benchmark_large/summary.md

echo
echo "--- Generating thesis figures ---"
python -m evaluation.generate_plots "${RESULTS[@]}" \
    --output runs/benchmark_large/plots
echo

echo "=== Job complete at $(date) ==="
