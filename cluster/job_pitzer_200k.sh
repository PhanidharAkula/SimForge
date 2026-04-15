#!/bin/bash
# ==============================================================
# SimForge — 200K Chicago Scenario Generation (OSC Pitzer)
# ==============================================================
# Generates: chicago_200k_car_transit (200K trips, car+transit, 24h)
#
# Submit:    sbatch cluster/job_pitzer_200k.sh
# Monitor:   squeue -u $USER
# Cancel:    scancel <job_id>
# Output:    cluster/logs/job_200k_<jobid>.out
# ==============================================================

#SBATCH --job-name=simforge_200k
#SBATCH --output=cluster/logs/job_200k_%j.out
#SBATCH --error=cluster/logs/job_200k_%j.err
#SBATCH --account=PMIU0110
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulap2@miamioh.edu

set -euo pipefail

# -----------------------------------------------------------
# Environment setup
# -----------------------------------------------------------
cd "$HOME/SimForge"

module purge 2>/dev/null || true
module load python/3.12

source .venv/bin/activate

# Create log directory
mkdir -p cluster/logs

echo "============================================"
echo "  SimForge — 200K Job Started (Pitzer)"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Node:       $(hostname)"
echo "  CPUs:       $SLURM_CPUS_PER_TASK"
echo "  Memory:     32G requested"
echo "  Start:      $(date)"
echo "  Python:     $(python3 --version)"
echo "============================================"

# -----------------------------------------------------------
# Verify modelgen file exists
# -----------------------------------------------------------
if [ ! -f "modelgen/chicago_model.txt" ]; then
    echo "ERROR: modelgen/chicago_model.txt not found!"
    echo "Transfer it first: scp modelgen/chicago_model.txt phanidharakula@pitzer.osc.edu:~/SimForge/modelgen/"
    exit 1
fi

# -----------------------------------------------------------
# Run 200K generation
# -----------------------------------------------------------
echo ""
echo "Running: python scripts/04_large_full_day.py"
echo "  City:    Chicago"
echo "  Trips:   200,000"
echo "  Modes:   car, transit"
echo "  Window:  0-86400s (24 hours)"
echo "  Radius:  15 km"
echo ""

time python scripts/04_large_full_day.py

# -----------------------------------------------------------
# Validate output
# -----------------------------------------------------------
echo ""
echo "Validating generated scenario..."
python -m pipeline.validation.validate_bundle scenarios/chicago_200k_car_transit

echo ""
echo "============================================"
echo "  200K Generation Complete"
echo "============================================"
echo "  End:      $(date)"
echo "============================================"
ls -lh scenarios/chicago_200k_car_transit/
