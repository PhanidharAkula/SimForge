#!/bin/bash
# ============================================================================
# SimForge — 01_chicago_1k_car: 1K car trips, Chicago, 7–8 AM, 2 km radius.
#
# Smallest tier; intended as a sanity check after a fresh Pitzer install
# or pipeline change. Should land well under 5 minutes wall-clock under
# the schedule-first census demand pipeline.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/01_chicago_1k_car.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_chicago_1k_car
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x_%j.out      # progress + INFO/WARNING/ERROR (Python logging routes to stdout)
#SBATCH --error=logs/%x_%j.err       # uncaught Python tracebacks + external-tool stderr
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

python -u scripts/01_chicago_1k_car.py

echo
echo "=== Job complete at $(date) ==="
