#!/bin/bash
# ============================================================================
# SimForge benchmark — large tier (chicago_200k_car + nyc_500k_car).
#
# ⚠️ THIS JOB CURRENTLY EXCEEDS WALL TIME on the unmodified codebase.
#    The SUMO adapter pre-routes every trip via BFS on the canonical graph
#    BEFORE handing off to the simulator. Measured cost on chicago_200k:
#    ~17 h per (engine, seed). With 5 sumo + 5 matsim + 5 dtalite runs that's
#    ~255 h of SUMO routing alone — past the cpu-partition wall. DTALite and
#    MATSim run from already-prepared inputs so they're not affected, but
#    the SUMO bottleneck dominates the wall.
#
#    Until the SUMO adapter caches routes per (origin, destination) — or
#    parallelises the BFS pass — this sbatch may SLURM-timeout. Use
#    cluster/jobs/benchmark_small.sbatch for jobs that finish today.
#
# Resources:
#   --partition=cpu — all three engines (SUMO, MATSim, DTALite) are CPU-only
#                            after the LPSim removal in Version_5.
#   --cpus-per-task=16, --mem=96G, --time=96:00:00.
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
python -c "from adapters.dtalite import is_dtalite_available, find_dtalite_binary; print(f'DTALite:   {find_dtalite_binary() if is_dtalite_available() else \"NOT INSTALLED — run uv pip install path4gmns\"}')"
echo
echo "⚠️  Reminder: SUMO BFS routing pre-step may exceed the wall."
echo "    See header comment for context."
echo

# ---------------------------------------------------------------------------
# 1. Preflight — both 200K and 500K bundles must be present (gitignored,
#    rsync from your dev box first).
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundles ==="
SCENARIOS=(chicago_200k_car nyc_500k_car)
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
