#!/bin/bash
# ============================================================================
# SimForge benchmark — large tier (chicago_200k_car + nyc_500k_car).
#
# 4-cell matrix: 2 scenarios × 2 engines (SUMO meso + MATSim meso) × 5 seeds
# = 20 simulator invocations. DTALite intentionally excluded at this tier
# per Phase 12.5 finding — the bundled path4gmns 0.10.0 DTALite C++ binary
# caps at 4 OpenMP threads and would need ~100-250 h per seed at these
# scenario sizes (extrapolated from la_50k observed ~25 h/seed). Documented
# as a path4gmns binary-side scalability ceiling in CHANGELOG Phase 12.5/12.7
# and in doc/chapters/results.md §5.7. SUMO + MATSim alignment is the
# reportable cross-engine signal at the 200K + tier.
#
# Wall-clock budget (Phase 14 canonical_routes cache + parallel BFS):
#   Phase 14 moved BFS routing from per-engine inline cost (Phase 13) to a
#   single shared, parallel-multiprocessing.Pool pass per scenario. Result:
#     chicago_200k_car worker: cold BFS ~6.5 h (1 pass shared by both
#                              engines) + 10 cells × ~200-245 s sim
#                              ≈ ~7.1 h cold, ~37 min warm-cache re-run
#     nyc_500k_car     worker: cold BFS ~20 h (projected, 24 workers,
#                              500K trips on ~2.5 M-link SCC) + 10 cells
#                              × ~3-5 min sim ≈ ~22 h cold,
#                              ~1-2 h warm-cache re-run
#   Total wall = max(workers) ≈ ~22 h cold, comfortable inside the
#   --time=2-00:00:00 (48 h) budget below. Both per-scenario fallback
#   sbatchs (Phase 13.2 wall-margin insurance) deleted post-Phase-14 —
#   this umbrella is now the single source of truth.
#
#   Phase 13 baseline reference (for the CHANGELOG comparison story):
#   chicago_200k under Phase 13 took 141.87 h wall (jobs 9332478).
#   Phase 14 cold-vs-cold speedup ~20×; warm-cache re-run ~228×.
#   See doc/EXPERIMENT_LOG.md 2026-05-19 entry for the full breakdown.
#
# Resources:
#   --partition=cpu        : Both engines (SUMO, MATSim) are CPU-only.
#   --cpus-per-task=16     : SUMO + MATSim both single-process per cell;
#                            the spare cores feed the canonical_routes
#                            multiprocessing.Pool (Phase 14.5) and absorb
#                            pytest + analyzer steps at the end.
#   --mem=180G             : Phase 13 bump (was 128 G). Pitzer cpu nodes
#                            have 192 G physical; 180 G is the safe
#                            ceiling after the OS reserve. Free headroom
#                            for the nyc_500k MATSim qsim peak. Cardinal
#                            cpu nodes have 503 G so 180 G is ample there
#                            too. Only switch to hugemem if 180 G spills.
#   --time=2-00:00:00      : 48 h. ~2× margin over the worst-case ~22 h
#                            nyc_500k cold wall under Phase 14. Was
#                            7-00:00:00 (168 h) under Phase 13; reduced
#                            so SLURM queue priority is higher and we
#                            don't reserve unused budget. Bump back to
#                            7-00:00:00 if you wipe the canonical_routes
#                            cache AND tackle a network larger than NYC.
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_benchmark_large
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=180G
#SBATCH --time=2-00:00:00
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
source .venv/bin/activate    # uv-managed venv with eclipse-sumo + matsim
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK  # Phase 12.4 — defensive even though
                                              # SUMO + MATSim don't use OpenMP at
                                              # the user level. DTALite is excluded
                                              # at this tier so the path4gmns 4-thread
                                              # cap is not relevant here.

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Java:      $(java -version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
echo "Engines:   SUMO + MATSim (DTALite excluded at this tier — see header / CHANGELOG Phase 12.7)"
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
# 3. Combined analysis over the per-scenario result JSONs.
# ---------------------------------------------------------------------------
echo "=== Aggregating results across all scenarios ==="
RESULTS=(runs/benchmark_large/*/benchmark_results_benchmark_large.json)
if [ ${#RESULTS[@]} -eq 0 ]; then
    echo "No per-scenario result JSONs found under runs/benchmark_large/*/."
    echo "  Both workers likely hit walltime before writing JSON."
    echo "  Check the per-scenario logs:"
    echo "    logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}_<scenario>.log"
    echo "  If artifacts are on disk but JSON is missing, recover with:"
    echo "    python -m tools.recover_partial_summary --runspec runspecs/benchmark_large.yaml \\"
    echo "        --scenario <scenario_id> --base-dir runs/benchmark_large/<scenario_id> \\"
    echo "        --harness-log <log file>"
    echo "Skipping aggregation."
    exit 0
fi
echo "Found ${#RESULTS[@]} result files:"
printf '  %s\n' "${RESULTS[@]}"
echo

# Merge per-scenario JSONs into one for analyze_benchmark (which only accepts
# a single positional results file). Phase 12.7: makes the multi-scenario
# pattern work without manual post-processing.
echo "--- Merging per-scenario JSONs ---"
python -c "
import json
from pathlib import Path
files = sorted(Path('runs/benchmark_large').glob('*/benchmark_results_benchmark_large.json'))
merged = {'runspec_name': 'benchmark_large', 'started_at': '', 'completed_at': '',
          'total_runs': 0, 'successful_runs': 0, 'failed_runs': 0, 'results': []}
for f in files:
    d = json.load(open(f))
    merged['total_runs'] += d['total_runs']
    merged['successful_runs'] += d['successful_runs']
    merged['failed_runs'] += d['failed_runs']
    merged['results'].extend(d['results'])
merged['summary'] = {'total': merged['total_runs'], 'completed': merged['successful_runs'], 'failed': merged['failed_runs']}
out = Path('runs/benchmark_large/benchmark_results_benchmark_large.json')
json.dump(merged, open(out, 'w'), indent=2)
print(f'  merged {len(files)} JSONs -> {out}  ({merged[\"successful_runs\"]} ok / {merged[\"failed_runs\"]} fail)')
"
echo

echo "--- Markdown summary table ---"
python -m evaluation.analyze_benchmark runs/benchmark_large/benchmark_results_benchmark_large.json --markdown \
    | tee runs/benchmark_large/summary.md

echo
echo "--- Generating thesis figures ---"
python -m evaluation.generate_plots runs/benchmark_large/benchmark_results_benchmark_large.json \
    --output runs/benchmark_large/plots
echo

echo "--- Audit cross-engine fairness ---"
python -m evaluation.audit_fairness runs/benchmark_large \
    | tee runs/benchmark_large/audit_fairness.txt
echo

echo "=== Job complete at $(date) ==="
echo "Per-scenario JSONs:  runs/benchmark_large/*/benchmark_results_benchmark_large.json"
echo "Merged JSON:         runs/benchmark_large/benchmark_results_benchmark_large.json"
echo "Combined summary:    runs/benchmark_large/summary.md"
echo "Audit:               runs/benchmark_large/audit_fairness.txt"
echo "Plots:               runs/benchmark_large/plots/"
