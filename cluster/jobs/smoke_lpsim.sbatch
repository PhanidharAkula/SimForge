#!/bin/bash
# ============================================================================
# LPSim smoke test on Pitzer.
#
# Runs prepare_lpsim_inputs + run_lpsim on the bundled chicago_1k_car
# scenario via the rebuilt source binary (preferred) or bundled binary
# (fallback). Use this to verify a fresh LPSim build before committing
# to the full N=5 benchmark matrix.
#
# Submit from the repo root:   sbatch cluster/jobs/smoke_lpsim.sbatch
#
# Override the scenario:
#   sbatch --export=ALL,SCENARIO=scenarios/sf_5k_car cluster/jobs/smoke_lpsim.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_smoke_lpsim
#SBATCH --partition=gpudebug
#SBATCH --gres=gpu:v100:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail

mkdir -p logs

module load gcc/13.2.0 cuda/11.8.0

echo "=== Smoke job starting on $(hostname) at $(date) ==="
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | head -1)"
echo

REPO_ROOT="$(pwd)"
SCENARIO="${SCENARIO:-scenarios/chicago_1k_car}"
OUTDIR="out/lpsim_smoke_${SLURM_JOB_ID:-local}"

if [ ! -d "$REPO_ROOT/.venv" ]; then
    echo "ERROR: .venv not found at $REPO_ROOT/.venv"
    exit 2
fi

source "$REPO_ROOT/.venv/bin/activate"

echo "Scenario: $SCENARIO"
echo "Output:   $OUTDIR"
echo

python -c "
from pathlib import Path
from adapters.lpsim import prepare_lpsim_inputs, run_lpsim, find_lpsim_source_binary, find_lpsim_singularity_image

src = find_lpsim_source_binary()
sif = find_lpsim_singularity_image()
print(f'Source binary: {src}')
print(f'SIF image:     {sif}')

out = Path('$OUTDIR')
out.mkdir(parents=True, exist_ok=True)
summary = prepare_lpsim_inputs(Path('$SCENARIO'), out)
print(f'Inputs: {summary.node_count} nodes, {summary.link_count} edges, {summary.trip_count} trips')

ok, t, err = run_lpsim(out)
print(f'Result: {\"OK\" if ok else \"FAIL\"} in {t:.1f}s')
if err:
    print(f'Error: {err}')
"

echo
echo "=== Smoke job finished at $(date) ==="
