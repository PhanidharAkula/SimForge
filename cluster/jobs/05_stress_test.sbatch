#!/bin/bash
# ============================================================================
# SimForge — 05_stress_test: 500K car trips, NYC, 6–10 AM, 20 km radius.
#
# Largest tier; the canonical scalability stress test. Under the
# schedule-first pipeline expect ~10–15 minutes on a Pitzer `cpu` compute
# node (vs the ~4 hour gravity-only baseline that produced JobID 47063986
# — see cluster/example_runs/nyc_500k_47063986.md for the historical run).
# The 8 hour wall-clock here is generous headroom.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/05_stress_test.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_stress_test
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail

module load python/3.12
cd ~/SimForge
source .venv/bin/activate

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python: $(which python)"
echo "Free memory: $(free -h | awk 'NR==2{print $4}')"
echo

python -u scripts/05_stress_test.py

echo
echo "=== Job complete at $(date) ==="
