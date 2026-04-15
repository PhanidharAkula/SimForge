#!/bin/bash
# ==============================================================
# SimForge — Full Benchmark Execution (OSC Pitzer)
# ==============================================================
# Runs the SUMO simulation benchmark on all available scenarios.
# SUMO is installed via pip (eclipse-sumo) in the venv.
#
# Submit:    sbatch cluster/job_pitzer_benchmark.sh
# Monitor:   squeue -u $USER
# Output:    cluster/logs/job_benchmark_<jobid>.out
# ==============================================================

#SBATCH --job-name=simforge_bench
#SBATCH --output=cluster/logs/job_benchmark_%j.out
#SBATCH --error=cluster/logs/job_benchmark_%j.err
#SBATCH --account=PMIU0110
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulap2@miamioh.edu

set -euo pipefail

cd "$HOME/SimForge"
module purge 2>/dev/null || true
module load python/3.12
source .venv/bin/activate
mkdir -p cluster/logs

# Set SUMO_HOME from pip-installed eclipse-sumo
export SUMO_HOME=$(python -c "import os, sumolib; print(os.path.dirname(os.path.dirname(sumolib.__file__)))" 2>/dev/null || echo "")

echo "============================================"
echo "  SimForge — Benchmark Job (Pitzer)"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Node:       $(hostname)"
echo "  Start:      $(date)"
echo "  Python:     $(python3 --version)"
echo "  SUMO_HOME:  $SUMO_HOME"
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
    echo "  ✗ SUMO binary not in PATH"
    # Check if eclipse-sumo pip package provides the binary
    SUMO_BIN=$(python -c "import shutil; print(shutil.which('sumo') or '')" 2>/dev/null || echo "")
    if [ -n "$SUMO_BIN" ]; then
        echo "  ✓ SUMO (pip): $SUMO_BIN"
        SUMO_OK=1
    fi
fi

JAVA_OK=0
if command -v java &>/dev/null; then
    echo "  ✓ Java: $(java -version 2>&1 | head -1)"
    JAVA_OK=1
else
    echo "  ✗ Java not available (MATSim will be skipped)"
fi

if [ "$SUMO_OK" -eq 0 ]; then
    echo ""
    echo "ERROR: SUMO not found. Run setup_pitzer.sh first."
    exit 1
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

time python run.py --repeats 3 --timeout 1800

echo ""
echo "============================================"
echo "  Benchmark Complete"
echo "============================================"
echo "  End:      $(date)"
echo "============================================"

ls -lh runs/benchmark_*/benchmark_results.json 2>/dev/null || echo "No results files found"
