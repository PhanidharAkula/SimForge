#!/bin/bash
# ============================================================================
# SimForge benchmark — large tier, nyc_500k_car ONLY (Phase 13.2, Cardinal).
#
# 2-cell matrix: 1 scenario × 2 engines (SUMO meso + MATSim meso) × 5 seeds
# = 10 simulator invocations. Same engine + seed selection as the umbrella
# `benchmark_large.sbatch` but isolated to nyc_500k_car so the worker gets
# its own wall budget on the `longcpu` partition (14 days) — this
# completely removes the wall-margin risk that arose on Pitzer's 7-day
# cap, where the pessimistic 500K estimate was within ~3 h of busting.
#
# DTALite still excluded at this tier per Phase 12.5/12.7 finding (the
# bundled path4gmns 0.10.0 binary caps internal OpenMP at 4 threads,
# which extrapolates to ~250 h/seed at 500K — structurally unfit for
# any practical wall). SUMO + MATSim alignment remains the reportable
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
#   cold BFS-prep:  ~55-80 h per engine (Pitzer was ~80-110 h)
#   cached mobsim:  5 seeds × ~5-10 min per engine
#   total per engine: ~55-80 h + ~25-50 min
#   total job (sequential prep across engines, since same machine):
#     ~115-165 h. Fits the 14-day longcpu wall (336 h) with massive
#     margin (50%+ headroom even on the pessimistic estimate).
#
# Resources:
#   --partition=longcpu   : 14-day max wall — the unconditional safety
#                           margin for the BFS-prep estimate's pessimistic
#                           tail. Same node hardware as `cpu` (Xeon Max
#                           9470, 104c, 503 G); only the max-wall differs.
#                           Queue may be slightly busier at any moment
#                           because long-wall jobs dominate, but starting
#                           a single 14-day job is routine.
#   --cpus-per-task=16    : SimForge cells are single-process per cell;
#                           the spare cores absorb pytest + analyzer
#                           steps at the end without GIL contention.
#                           104-core node is overkill — harmless.
#   --mem=480G            : Phase 13.2 sizing — Cardinal nodes have ~503 G
#                           physical, 480 G is the safe ceiling after the
#                           OS reserve. Plenty of headroom for MATSim
#                           qsim at 500K (the unknown workload that
#                           Pitzer's 192 G ceiling worried us about).
#   --time=14-00:00:00    : 14 days, the longcpu partition's max. Drop
#                           back to `--partition=cpu --time=7-00:00:00`
#                           if Cardinal's BFS-prep speedup comes in at
#                           the optimistic end (~115 h fits 7 days with
#                           53 h to spare). Submit conservatively first;
#                           retighten once you have a measured run.
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_large_nyc_500k
#SBATCH --partition=longcpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=480G
#SBATCH --time=14-00:00:00
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
echo "Scenario:  nyc_500k_car ONLY (dedicated wall budget — see header)"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — nyc_500k bundle must be present (gitignored, rsync first).
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundle ==="
if [ ! -f "scenarios/nyc_500k_car/manifest.xml" ]; then
    echo "MISSING bundle: scenarios/nyc_500k_car/ — rsync from your dev box first."
    echo "    rsync -avh --progress scenarios/nyc_500k_car/ pitzer:SimForge/scenarios/nyc_500k_car/"
    exit 1
fi
python -m pipeline.validation.validate_bundle scenarios/nyc_500k_car
echo

# ---------------------------------------------------------------------------
# 2. Run the benchmark harness scoped to nyc_500k_car.
# ---------------------------------------------------------------------------
echo "=== Running benchmark for nyc_500k_car ==="
mkdir -p runs/benchmark_large/nyc_500k_car
python -u -m execution.run_benchmark runspecs/benchmark_large.yaml \
    --scenario nyc_500k_car \
    --output   runs/benchmark_large/nyc_500k_car
echo "=== Worker complete at $(date) ==="
echo

# ---------------------------------------------------------------------------
# 3. Per-scenario analysis. Combined aggregation across chicago + nyc lives
#    in the umbrella `benchmark_large.sbatch` — once both per-scenario JSONs
#    exist on disk, run that script's merge step manually, or just re-submit
#    the umbrella (it's idempotent against existing JSONs).
# ---------------------------------------------------------------------------
RESULTS=(runs/benchmark_large/nyc_500k_car/benchmark_results_benchmark_large.json)
if [ ${#RESULTS[@]} -eq 0 ]; then
    echo "No per-scenario result JSON found."
    echo "  Worker likely hit walltime before writing JSON."
    echo "  Recover with:"
    echo "    python -m tools.recover_partial_summary --runspec runspecs/benchmark_large.yaml \\"
    echo "        --scenario nyc_500k_car --base-dir runs/benchmark_large/nyc_500k_car \\"
    echo "        --harness-log logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}.out"
    echo "Skipping analysis."
    exit 0
fi

echo "--- Markdown summary table (nyc_500k_car only) ---"
python -m evaluation.analyze_benchmark "${RESULTS[0]}" --markdown \
    | tee runs/benchmark_large/nyc_500k_car/summary.md

echo
echo "--- Generating thesis figures (nyc_500k_car only) ---"
python -m evaluation.generate_plots "${RESULTS[0]}" \
    --output runs/benchmark_large/nyc_500k_car/plots
echo

echo "--- Audit cross-engine fairness (nyc_500k_car only) ---"
python -m evaluation.audit_fairness runs/benchmark_large/nyc_500k_car \
    | tee runs/benchmark_large/nyc_500k_car/audit_fairness.txt
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSON:  ${RESULTS[0]}"
echo "Per-scenario plots: runs/benchmark_large/nyc_500k_car/plots/"
echo "Audit:              runs/benchmark_large/nyc_500k_car/audit_fairness.txt"
echo
echo "To combine with chicago_200k_car results (assuming it's already run):"
echo "  re-submit cluster/jobs/benchmark_large.sbatch — its merge step is"
echo "  idempotent and will pick up both per-scenario JSONs."
