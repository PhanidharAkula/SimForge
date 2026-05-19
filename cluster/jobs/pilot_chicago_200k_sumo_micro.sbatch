#!/bin/bash
# ============================================================================
# SimForge pilot — chicago_200k_car SUMO microscopic (single seed).
#
# 1-cell pilot: chicago_200k_car × SUMO × micro × seed 42 = 1 simulator
# invocation. Decision gate before committing to the full 5-seed SUMO micro
# matrix at the 200K tier. See `runspecs/pilot_chicago_200k_sumo_micro.yaml`
# header for the full rationale + projection table + post-pilot decision
# gate (green/yellow/red).
#
# Wall-clock budget:
#   Projection (from doc/SIMULATION_PARADIGMS.md §6):
#     chicago_1k_car SUMO micro engine_wall = 343 s on 1K trips
#     chicago_200k_car linear extrapolation = ~19 h
#     chicago_200k_car super-linear (1.5-2×)= 28-38 h (congestion interactions)
#   Pilot --time = 2 days (48 h) provides 1.3-1.7× margin over upper bound.
#
#   Phase 14 cache: the canonical_routes BFS cache for chicago_200k_car
#   already exists on Cardinal (built by job 9971041, SUMO meso seed=42 cold
#   pass). Pilot will hit warm cache and pay ~1 s prep; engine_wall is the
#   entire cost. NO 6.5 h BFS pass needed.
#
# Resources:
#   --partition=cpu        : SUMO is CPU-only.
#   --cpus-per-task=16     : SUMO single-process per cell; spare cores absorb
#                            preflight + analyzer + scorecard at the end.
#   --mem=128G             : SUMO micro tracks per-vehicle state (lane,
#                            position, speed, accel). Phase 14 SUMO meso at
#                            chicago_200k peaked at ~23 G; micro is 2-5×
#                            heavier on heap. 128 G is conservative — Cardinal
#                            cpu nodes have 503 G so margin is comfortable.
#                            Bump to --partition=hugemem if pilot OOMs.
#   --time=2-00:00:00      : 48 h. Margin over the 28-38 h super-linear
#                            projection. Cancel + investigate if it spends
#                            >40 h at <50 % simulated-time progress.
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_pilot_chicago_200k_sumo_micro
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail
shopt -s nullglob

mkdir -p logs
cd ~/SimForge
source .venv/bin/activate

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:    $(which python)"
echo "SUMO:      $(sumo --version 2>&1 | head -1)"
echo "Free mem:  $(free -h | awk 'NR==2{print $4}')"
echo

# ---------------------------------------------------------------------------
# 1. Preflight — chicago_200k_car bundle must be present.
# ---------------------------------------------------------------------------
echo "=== Preflight: validating bundle ==="
if [ ! -f "scenarios/chicago_200k_car/manifest.xml" ]; then
    echo "MISSING bundle: scenarios/chicago_200k_car/ — rsync from your dev box first."
    exit 1
fi
python -m pipeline.validation.validate_bundle scenarios/chicago_200k_car
echo

# ---------------------------------------------------------------------------
# 2. Run the pilot. The canonical_routes cache from job 9971041 should be
#    present at runs/benchmark_large/chicago_200k_car/.canonical_routes/ —
#    Phase 14 will hardlink from there into the pilot's output dir, skipping
#    the 6.5 h cold BFS pass.
# ---------------------------------------------------------------------------
echo "=== Launching SUMO micro pilot (1 cell, seed 42) ==="
mkdir -p runs/pilots/chicago_200k_sumo_micro
python -u -m execution.run_benchmark runspecs/pilot_chicago_200k_sumo_micro.yaml \
    --output runs/pilots/chicago_200k_sumo_micro/
echo

# ---------------------------------------------------------------------------
# 3. Headline summary — single cell, no aggregation needed.
# ---------------------------------------------------------------------------
echo "=== Pilot result summary ==="
python -c "
import json
j = json.load(open('runs/pilots/chicago_200k_sumo_micro/benchmark_results_pilot_chicago_200k_sumo_micro.json'))
r = j['results'][0]
print(f'  status:      {r[\"status\"]}')
print(f'  engine_wall: {r.get(\"engine_wall_s\", 0):.1f} s = {r.get(\"engine_wall_s\", 0) / 3600:.2f} h')
print(f'  cell_wall:   {r.get(\"cell_wall_s\", 0):.1f} s = {r.get(\"cell_wall_s\", 0) / 3600:.2f} h')
print(f'  prep_wall:   {(r.get(\"cell_wall_s\", 0) - r.get(\"engine_wall_s\", 0)):.1f} s')
if r.get('metrics', {}).get('travel_time'):
    tt = r['metrics']['travel_time']
    print(f'  mean TT:     {tt.get(\"mean\", 0):.1f} s')
    print(f'  p95 TT:      {tt.get(\"p95\", 0):.1f} s')
    print(f'  trip count:  {tt.get(\"trip_count\", 0)}')
print()
print('Decision gate (per runspec header):')
ew_h = r.get('engine_wall_s', 0) / 3600
if r['status'] != 'success':
    print(f'  RED — pilot did not complete ({r.get(\"error_message\", \"unknown error\")[:80]})')
elif ew_h <= 30:
    print(f'  GREEN — engine_wall {ew_h:.1f} h ≤ 30 h. Full 5-seed matrix is feasible.')
elif ew_h <= 48:
    print(f'  YELLOW — engine_wall {ew_h:.1f} h between 30-48 h. 5-seed matrix needs 7-day wall.')
else:
    print(f'  RED — engine_wall {ew_h:.1f} h > 48 h. Not practical at 200K tier.')
"
echo

echo "=== Job complete at $(date) ==="
echo "Pilot JSON:    runs/pilots/chicago_200k_sumo_micro/benchmark_results_pilot_chicago_200k_sumo_micro.json"
echo "Scorecard:     runs/pilots/chicago_200k_sumo_micro/reproducibility_scorecard.md"
echo "Cell artifacts: runs/pilots/chicago_200k_sumo_micro/chicago_200k_car/sumo/micro/seed_42/"
