#!/bin/bash
# ============================================================================
# SimForge benchmark — large tier, chicago_200k_car ONLY (Phase 13.2, Cardinal).
#
# 2-cell matrix: 1 scenario × 2 engines (SUMO meso + MATSim meso) × 5 seeds
# = 10 simulator invocations. Same engine + seed selection as the umbrella
# `benchmark_large.sbatch` but isolated to chicago_200k_car so it gets its
# own wall budget — paired with `benchmark_large_nyc_500k.sbatch` for the
# 500K scenario, this fully removes the wall-margin risk that arose when
# both scenarios shared one wall window under Pitzer.
#
# DTALite still excluded at this tier per Phase 12.5/12.7 finding (the
# bundled path4gmns 0.10.0 binary caps internal OpenMP at 4 threads,
# which extrapolates to ~100 h/seed at 200K — structurally unfit for any
# practical wall). SUMO + MATSim alignment remains the reportable
# cross-engine signal.
#
# CLUSTER: OSC Cardinal (`cardinal.osc.edu`)
#   Node type:  Dell c6620, Xeon Max 9470 (Sapphire Rapids + HBM2e,
#               104 cores @ 3.5 GHz boost), 515,424 MB RAM (~503 G).
#   Why Cardinal vs Pitzer: ~20-30% faster single-thread for the BFS-prep
#   + MATSim qsim loop (newer Intel IPC + HBM); 503 G/node removes the
#   memory ceiling Pitzer's 192 G nodes imposed. Same `openjdk/21.0.3_9`
#   module, same eclipse-sumo wheel — zero porting work, $HOME shared.
#
# Wall-clock budget (with Phase 12 BFS-prep cache, Cardinal speeds):
#   cold BFS-prep:  ~20-30 h per engine (Pitzer was ~30-40 h)
#   cached mobsim:  5 seeds × ~5-10 min per engine
#   total per engine: ~20-30 h + ~25-50 min
#   total job (sequential prep across engines, since same machine):
#     ~45-65 h. Fits the 7-day cpu wall (168 h) with massive margin.
#
# Resources:
#   --partition=cpu       : SUMO + MATSim are CPU-only. Cardinal's cpu
#                           partition has ~100 nodes at 104 cores / 503 G.
#   --cpus-per-task=16    : Cardinal's cpu partition caps memory at
#                           MaxMemPerCPU=4956 MB, so --mem and --cpus
#                           are coupled: max --mem allowed = cpus × 4.84 G.
#                           16 CPUs → ~77 G ceiling, enough for the 32 G
#                           MATSim heap + ~5 G JVM overhead + ~10 G OS
#                           and workspace ≈ ~47 G actual peak. SimForge
#                           cells are single-process; extra cores absorb
#                           pytest + analyzer at the end without GIL
#                           contention.
#   --mem=72G             : Phase 13.3 sizing for Cardinal (Pitzer was
#                           --mem=128/180 G with no per-CPU coupling).
#                           72 G sits comfortably below the 16-CPU cap,
#                           covers the ~47 G actual peak with a 1.5×
#                           safety margin, and frees the rest of the
#                           node for other users.
#   --time=7-00:00:00     : 7 days, the cpu partition's max. The estimate
#                           comes in well under 65 h — use `longcpu` only
#                           if a margin-of-safety run busts this for any
#                           reason (the 14-day `longcpu` partition is the
#                           escape hatch).
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_large_chicago_200k
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=72G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail
shopt -s nullglob   # see umbrella sbatch header for rationale

mkdir -p logs
module load openjdk/21.0.3_9
cd ~/SimForge
source .venv/bin/activate
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
echo "Engines:   SUMO + MATSim (DTALite excluded — see CHANGELOG Phase 12.7)"
echo "Scenario:  chicago_200k_car ONLY (dedicated wall budget — see header)"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — chicago_200k bundle must be present (gitignored, rsync first).
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundle ==="
if [ ! -f "scenarios/chicago_200k_car/manifest.xml" ]; then
    echo "MISSING bundle: scenarios/chicago_200k_car/ — rsync from your dev box first."
    echo "    rsync -avh --progress scenarios/chicago_200k_car/ pitzer:SimForge/scenarios/chicago_200k_car/"
    exit 1
fi
python -m pipeline.validation.validate_bundle scenarios/chicago_200k_car
echo

# ---------------------------------------------------------------------------
# 2. Run the benchmark harness scoped to chicago_200k_car.
# ---------------------------------------------------------------------------
echo "=== Running benchmark for chicago_200k_car ==="
mkdir -p runs/benchmark_large/chicago_200k_car
python -u -m execution.run_benchmark runspecs/benchmark_large.yaml \
    --scenario chicago_200k_car \
    --output   runs/benchmark_large/chicago_200k_car
echo "=== Worker complete at $(date) ==="
echo

# ---------------------------------------------------------------------------
# 3. Per-scenario analysis. Combined aggregation across chicago + nyc lives
#    in the umbrella `benchmark_large.sbatch` — once both per-scenario JSONs
#    exist on disk, run that script's merge step manually, or just re-submit
#    the umbrella (it's idempotent against existing JSONs).
# ---------------------------------------------------------------------------
RESULTS=(runs/benchmark_large/chicago_200k_car/benchmark_results_benchmark_large.json)
if [ ${#RESULTS[@]} -eq 0 ]; then
    echo "No per-scenario result JSON found."
    echo "  Worker likely hit walltime before writing JSON."
    echo "  Recover with:"
    echo "    python -m tools.recover_partial_summary --runspec runspecs/benchmark_large.yaml \\"
    echo "        --scenario chicago_200k_car --base-dir runs/benchmark_large/chicago_200k_car \\"
    echo "        --harness-log logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}.out"
    echo "Skipping analysis."
    exit 0
fi

echo "--- Markdown summary table (chicago_200k_car only) ---"
python -m evaluation.analyze_benchmark "${RESULTS[0]}" --markdown \
    | tee runs/benchmark_large/chicago_200k_car/summary.md

echo
echo "--- Generating thesis figures (chicago_200k_car only) ---"
python -m evaluation.generate_plots "${RESULTS[0]}" \
    --output runs/benchmark_large/chicago_200k_car/plots
echo

echo "--- Audit cross-engine fairness (chicago_200k_car only) ---"
python -m evaluation.audit_fairness runs/benchmark_large/chicago_200k_car \
    | tee runs/benchmark_large/chicago_200k_car/audit_fairness.txt
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSON:  ${RESULTS[0]}"
echo "Per-scenario plots: runs/benchmark_large/chicago_200k_car/plots/"
echo "Audit:              runs/benchmark_large/chicago_200k_car/audit_fairness.txt"
echo
echo "To combine with nyc_500k_car results (assuming it's already run):"
echo "  re-submit cluster/jobs/benchmark_large.sbatch — its merge step is"
echo "  idempotent and will pick up both per-scenario JSONs."
