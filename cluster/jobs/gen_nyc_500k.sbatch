#!/bin/bash
# ============================================================================
# SimForge stress_test — NYC, 500K trips, 6–10 AM commute window.
#
# Recorded thesis run: JobID 47063986 on Pitzer cpu, 8 cores, 64 GB.
#   Submitted 2026-04-23 14:51, completed 18:43 (3 h 52 min, exit 0:0,
#   MaxRSS 9.4 GB). See cluster/example_runs/nyc_500k_47063986.md for the
#   annotated stderr and per-step timings.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#   --mail-user=...   your address, or remove --mail-type/--mail-user
#
# Submit from the repo root:   sbatch cluster/jobs/gen_nyc_500k.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_nyc_500k
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x_%j.out      # progress + INFO/WARNING/ERROR (Python logging routes to stdout)
#SBATCH --error=logs/%x_%j.err       # uncaught Python tracebacks + external-tool stderr (SUMO, MATSim, …)
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulaphanidhar30@gmail.com

set -euo pipefail

module load python/3.12 openjdk/21.0.3_9
cd ~/SimForge
source .venv/bin/activate

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python: $(which python)"
echo "Free memory: $(free -h | awk 'NR==2{print $4}')"
echo

python -u scripts/05_stress_test.py

echo
echo "=== Job complete at $(date) ==="
