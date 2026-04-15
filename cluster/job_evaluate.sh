#!/bin/bash
# ==============================================================
# SimForge — Evaluation & Analysis (Slurm Job)
# ==============================================================
# Analyzes benchmark results, generates plots and tables.
# Run AFTER benchmark job completes.
#
# Submit:    sbatch cluster/job_evaluate.sh
# Output:    cluster/logs/job_evaluate_<jobid>.out
# ==============================================================

#SBATCH --job-name=simforge_eval
#SBATCH --output=cluster/logs/job_evaluate_%j.out
#SBATCH --error=cluster/logs/job_evaluate_%j.err
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=akulap@miamioh.edu

set -euo pipefail

cd "$HOME/SimForge"
module purge 2>/dev/null || true
module load anaconda-python3.10
source .venv/bin/activate
mkdir -p cluster/logs doc/figures

echo "============================================"
echo "  SimForge — Evaluation Job"
echo "============================================"
echo "  Job ID:     $SLURM_JOB_ID"
echo "  Start:      $(date)"
echo "============================================"

# Find the most recent benchmark results
RESULTS=$(ls -t runs/benchmark_*/benchmark_results.json 2>/dev/null | head -1)

if [ -z "$RESULTS" ]; then
    echo "ERROR: No benchmark results found in runs/"
    echo "Run the benchmark first: sbatch cluster/job_benchmark.sh"
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
# 3. Compare modes (if applicable)
# -----------------------------------------------------------
echo ""
echo "[3/3] Mode comparison..."
for scenario_dir in scenarios/*/; do
    scenario=$(basename "$scenario_dir")
    echo "  Comparing modes for $scenario..."
    python -m evaluation.compare_modes "$scenario_dir" --seed 42 || echo "  (skipped — engine not available)"
done

echo ""
echo "============================================"
echo "  Evaluation Complete"
echo "============================================"
echo "  End:        $(date)"
echo "  Figures:    doc/figures/"
echo "============================================"
ls -lh doc/figures/ 2>/dev/null || echo "No figures generated"
