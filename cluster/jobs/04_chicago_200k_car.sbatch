#!/bin/bash
# ============================================================================
# SimForge: 04_chicago_200k_car: 200K trips (car), Chicago, 24-hour
# horizon, 15 km radius.
#
# Large full-day tier. Larger bbox + trip count than 03 means more memory
# headroom and more network-extraction time; demand-step is still ~minutes
# under the schedule-first pipeline.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root. Create logs/ first: SLURM resolves the
# relative --output/--error paths at submit time, so an in-script
# mkdir would be too late for its own %x_%j.out/.err files.
#   mkdir -p logs && sbatch cluster/jobs/04_chicago_200k_car.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_chicago_200k_car
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
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

python -u scripts/04_chicago_200k_car.py

echo
echo "=== Job complete at $(date) ==="
