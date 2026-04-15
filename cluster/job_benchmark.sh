#!/bin/bash
# ==============================================================
# SimForge — Full Benchmark Execution (Slurm Job)
# ==============================================================
# Runs the SUMO simulation benchmark on all available scenarios.
# This assumes SUMO is available via module or the adapter
# is already configured.
#
# Submit:    sbatch cluster/job_benchmark.sh
# Monitor:   squeue -u $USER
# Output:    cluster/logs/job_benchmark_<jobid>.out
# ==============================================================

#SBATCH --job-name=simforge_bench
#SBATCH --output=cluster/logs/job_benchmark_%j.out
#SBATCH --error=cluster/logs/job_benchmark_%j.err
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
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
echo "  SimForge — Benchmark Job"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Node:       $(hostname)"
echo "  Start:      $(date)"
echo "  Python:     $(python3 --version)"
echo "============================================"

# -----------------------------------------------------------
# 1. Check which engines are available
# -----------------------------------------------------------
echo ""
echo "Checking engines..."
SUMO_OK=0
if command -v sumo &>/dev/null; then
    echo "  ✓ SUMO: $(sumo --version 2>&1 | head -1)"
    SUMO_OK=1
else
    echo "  ✗ SUMO not found"
fi

JAVA_OK=0
if command -v java &>/dev/null && [ -f "lib/matsim-15.0/matsim-15.0.jar" ]; then
    echo "  ✓ MATSim: $(java -version 2>&1 | head -1)"
    JAVA_OK=1
else
    echo "  ✗ MATSim not available"
fi

# -----------------------------------------------------------
# 2. Validate all scenarios
# -----------------------------------------------------------
echo ""
echo "Validating scenarios..."
python run.py --validate-only

# -----------------------------------------------------------
# 3. Run benchmark (all scenarios × available engines × modes)
# -----------------------------------------------------------
echo ""
echo "Running benchmark..."

# Use run.py which auto-detects installed engines
time python run.py --repeats 3 --timeout 1800

echo ""
echo "============================================"
echo "  Benchmark Complete"
echo "============================================"
echo "  End:      $(date)"
echo "============================================"

# List results
echo ""
ls -lh runs/benchmark_*/benchmark_results.json 2>/dev/null || echo "No results files found"
