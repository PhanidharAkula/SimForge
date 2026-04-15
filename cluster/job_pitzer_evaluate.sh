#!/bin/bash
# ==============================================================
# SimForge — Evaluation & Analysis (OSC Pitzer)
# ==============================================================
# Analyzes benchmark results, generates plots and tables.
# Run AFTER benchmark job completes.
#
# Submit:    sbatch cluster/job_pitzer_evaluate.sh
# Output:    cluster/logs/job_evaluate_<jobid>.out
# ==============================================================

#SBATCH --job-name=simforge_eval
#SBATCH --output=cluster/logs/job_evaluate_%j.out
#SBATCH --error=cluster/logs/job_evaluate_%j.err
#SBATCH --account=PMIU0110
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulap2@miamioh.edu

set -euo pipefail

cd "$HOME/SimForge"
module purge 2>/dev/null || true
module load python/3.12
source .venv/bin/activate
mkdir -p cluster/logs doc/figures

echo "============================================"
echo "  SimForge — Evaluation Job (Pitzer)"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Start:      $(date)"
echo "============================================"

# Find the most recent benchmark results
RESULTS=$(ls -t runs/benchmark_*/benchmark_results.json 2>/dev/null | head -1)

if [ -z "$RESULTS" ]; then
    echo "ERROR: No benchmark results found in runs/"
    echo "Run the benchmark first: sbatch cluster/job_pitzer_benchmark.sh"
    exit 1
fi

echo "Analyzing: $RESULTS"

# -----------------------------------------------------------
# 1. Analyze benchmark results (tables, stats)
# -----------------------------------------------------------
echo ""
echo "[1/3] Analyzing benchmark results..."
python -m evaluation.analyze_benchmark "$RESULTS"

# -----------------------------------------------------------
# 2. Generate plots
# -----------------------------------------------------------
echo ""
echo "[2/3] Generating plots..."
python -m evaluation.generate_plots "$RESULTS" --output doc/figures

# -----------------------------------------------------------
# 3. Compare modes
# -----------------------------------------------------------
echo ""
echo "[3/3] Comparing simulation modes..."
python -m evaluation.compare_modes scenarios/chicago_5k --seed 42

echo ""
echo "============================================"
echo "  Evaluation Complete"
echo "============================================"
echo "  End:        $(date)"
echo "  Figures in: doc/figures/"
echo "============================================"
ls -lh doc/figures/ 2>/dev/null || echo "No figures generated"
