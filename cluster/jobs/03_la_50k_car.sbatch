#!/bin/bash
# ============================================================================
# SimForge: 03_la_50k_car: 50K trips (car+transit+bike), LA,
# 6–10 AM, 10 km radius.
#
# Medium multi-modal tier. Reference cross-platform-reproducibility bundle
# (see doc/REPRODUCING.md §Cross-Platform Reproducibility). Empirical
# Pitzer wall-clock on a login node was ~20 min; on a `cpu` compute node
# expect closer to 12–15 min under the schedule-first pipeline.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   uncomment + fill if you want completion notifications
#
# Submit from the repo root:   sbatch cluster/jobs/03_la_50k_car.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_la_50k_car
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
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

python -u scripts/03_la_50k_car.py

echo
echo "=== Job complete at $(date) ==="
