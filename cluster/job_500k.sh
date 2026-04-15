#!/bin/bash
# ==============================================================
# SimForge — 500K NYC Scenario Generation (Slurm Job)
# ==============================================================
# Generates: nyc_500k_car (500K trips, car, 6-10AM)
#
# Submit:    sbatch cluster/job_500k.sh
# NOTE:      Requires nyc_model.txt in modelgen/
# ==============================================================

#SBATCH --job-name=simforge_500k
#SBATCH --output=cluster/logs/job_500k_%j.out
#SBATCH --error=cluster/logs/job_500k_%j.err
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulap@miamioh.edu

set -euo pipefail

cd "$HOME/SimForge"
module purge 2>/dev/null || true
module load anaconda-python3.10
source .venv/bin/activate
mkdir -p cluster/logs

echo "============================================"
echo "  SimForge — 500K Job Started"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Node:       $(hostname)"
echo "  CPUs:       $SLURM_CPUS_PER_TASK"
echo "  Memory:     64G requested"
echo "  Start:      $(date)"
echo "  Python:     $(python3 --version)"
echo "============================================"

# Verify modelgen file
if [ ! -f "modelgen/nyc_model.txt" ]; then
    echo "ERROR: modelgen/nyc_model.txt not found!"
    echo "Transfer it first: scp modelgen/nyc_model.txt akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/"
    exit 1
fi

echo ""
echo "Running: python scripts/05_stress_test.py"
echo "  City:    NYC"
echo "  Trips:   500,000"
echo "  Modes:   car"
echo "  Window:  6-10AM (21600-36000s)"
echo "  Radius:  20 km"
echo ""

time python scripts/05_stress_test.py

echo ""
echo "Validating generated scenario..."
python -m pipeline.validation.validate_bundle scenarios/nyc_500k_car

echo ""
echo "============================================"
echo "  Job Complete"
echo "============================================"
echo "  End:      $(date)"
echo "  Output:   scenarios/nyc_500k_car/"
echo "============================================"
ls -lh scenarios/nyc_500k_car/
