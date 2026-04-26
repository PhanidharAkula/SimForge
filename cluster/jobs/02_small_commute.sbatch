#!/bin/bash
# ============================================================================
# SimForge — 02_small_commute: 10K car trips, NYC, 7–9 AM, 4 km radius.
#
# Small commute tier; ~5–10 minutes wall-clock under schedule-first.
# Useful for quick iteration on adapter/engine changes before scaling up.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/02_small_commute.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_small_commute
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
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

python -u scripts/02_small_commute.py

echo
echo "=== Job complete at $(date) ==="
