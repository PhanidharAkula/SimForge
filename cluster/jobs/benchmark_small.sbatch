#!/bin/bash
# ============================================================================
# SimForge benchmark — small tier (3 scenarios × SUMO + MATSim + DTALite × meso+micro).
#
# Runs runspecs/benchmark_small.yaml with three parallel python workers,
# one per scenario, each writing to its own --output dir to avoid the
# per-runspec result JSON colliding (the harness names that JSON after
# the runspec, not the scenario).
#
# Wall-clock budget (N=5 repeats, with Phase 12 BFS-prep cache):
#   Per-scenario worker times — la_50k is the long pole because its
#   per-engine BFS-prep cost on a 50K-trip × 159K-node network is
#   ~10-11 h (paid once per engine thanks to caching, then 5 cheap
#   reps reuse the cached prep). The other workers finish much sooner:
#     chicago_1k_car worker:  ~10 min  (1K trips, small graph)
#     nyc_10k_car   worker:  ~2-3 h   (SUMO micro × 5 is the long pole)
#     la_50k_car    worker:  ~21-23 h (SUMO + MATSim BFS prep × 1 each)
#   Total wall = max(workers) ≈ 23 h. 36 h walltime gives headroom for
#   slow Pitzer I/O, JVM startup variance, and the la_50k engine runs
#   themselves which still take a few min each.
#
# Resources:
#   --partition=cpu        : All three engines (SUMO, MATSim, DTALite) are
#                            CPU-only after the LPSim removal in Version_5.
#   --cpus-per-task=16     : 3 parallel scenarios × ~2 cores each + python
#                            overhead + post-step analyzer fits comfortably.
#                            DTALite uses OpenMP and benefits from the extra
#                            cores via number_of_cpu_processors in settings.yml.
#   --mem=64G              : Peak per-scenario memory ~5 GB; 3 in parallel
#                            ≤ 20 GB; 64 GB has headroom (la_50k microscopic
#                            can spike).
#   --time=24:00:00        : See wall-clock budget above.
#
# DTALite: ships inside the path4gmns Python package (already in
# requirements.lock). No build step required on Pitzer; the bundled
# Linux .so works against the system glibc when run inside the same
# Apptainer/conda environment used for the rest of the harness.
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
#SBATCH --time=36:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail
# nullglob: an unmatched glob expands to *nothing* instead of staying as the
# literal pattern. Critical for the RESULTS=(<base>/*/<glob>.json) line below
# — without it, a missing-files case silently passes the literal "*" path to
# analyze_benchmark and the script appears to "find 1 result" that doesn't
# exist (this happened in production on 2026-05-02 — see CHANGELOG Phase 12).
shopt -s nullglob

mkdir -p logs                # defensive: SLURM silently fails if logs/ missing
module load openjdk/21.0.3_9 # MATSim runtime — Pitzer's lmod requires explicit version
cd ~/SimForge
source .venv/bin/activate    # uv-managed venv with eclipse-sumo + matsim + path4gmns

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
python -c "from adapters.dtalite import is_dtalite_available, find_dtalite_binary; print(f'DTALite:   {find_dtalite_binary() if is_dtalite_available() else \"NOT INSTALLED — run uv pip install path4gmns\"}')"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — every scenario referenced in the runspec must validate.
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundles ==="
SCENARIOS=(chicago_1k_car nyc_10k_car la_50k_car)
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
if [ ${#RESULTS[@]} -eq 0 ]; then
    echo "No per-scenario result JSONs found under runs/benchmark_small/*/."
    echo "  Workers may have hit walltime or all failed before writing JSON."
    echo "  Check the per-scenario logs:"
    echo "    logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}_<scenario>.log"
    echo "Skipping aggregation."
    exit 0
fi
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

echo "--- Audit cross-engine fairness ---"
python -m evaluation.audit_fairness runs/benchmark_small \
    | tee runs/benchmark_small/audit_fairness.txt
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSONs: runs/benchmark_small/*/benchmark_results_benchmark_small.json"
echo "Combined summary:    runs/benchmark_small/summary.md"
echo "Audit:               runs/benchmark_small/audit_fairness.txt"
echo "Plots:               runs/benchmark_small/plots/"
