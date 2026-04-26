#!/bin/bash
# ============================================================================
# One-time QarSUMO build on Pitzer's GPU partition.
#
# After this job completes successfully:
#   $HOME/qarsumo/build/qarsumo  exists and is on the qarsumo adapter's
#   auto-discovery path (see adapters/qarsumo/qarsumo_adapter.py:find_qarsumo_binary).
# Future SimForge benchmark jobs that include qarsumo entries will then
# get GPU-accelerated runs instead of the standard-SUMO fallback.
#
# Re-run this only when CUDA / GCC versions on Pitzer change. Otherwise
# build once and use the binary across all benchmark jobs.
#
# Wall: ~30 min including clone + cmake + make. 1 h budget is generous.
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#
# Submit from the repo root:   sbatch cluster/jobs/build_qarsumo.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_build_qarsumo
#SBATCH --partition=gpu
#SBATCH --gres=gpu:v100:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail

mkdir -p logs
# Pitzer's lmod requires explicit versions. As of 2026-04 the latest pair is
# gcc/13.2.0 + cuda/12.6.2 (check current options with `module avail gcc cuda`).
module load gcc/13.2.0 cuda/12.6.2

echo "=== Job starting on $(hostname) at $(date) ==="
echo "CUDA:   $(nvcc --version 2>&1 | tail -1)"
echo "GCC:    $(gcc --version | head -1)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | head -1)"
echo

# ---------------------------------------------------------------------------
# 1. Clone or refresh the QarSUMO source tree.
# ---------------------------------------------------------------------------
QSDIR="$HOME/qarsumo"
if [ -d "$QSDIR/.git" ]; then
    echo "=== Refreshing existing clone at $QSDIR ==="
    cd "$QSDIR"
    git fetch --quiet
    git reset --hard origin/HEAD
else
    echo "=== Cloning LLNL/QarSUMO into $QSDIR ==="
    rm -rf "$QSDIR"
    git clone https://github.com/LLNL/QarSUMO.git "$QSDIR"
    cd "$QSDIR"
fi
echo

# ---------------------------------------------------------------------------
# 2. Configure + build.
# ---------------------------------------------------------------------------
echo "=== Building (cmake + make -j$SLURM_CPUS_PER_TASK) ==="
mkdir -p build && cd build
cmake .. 2>&1 | tail -20
make -j"$SLURM_CPUS_PER_TASK" 2>&1 | tail -10
echo

# ---------------------------------------------------------------------------
# 3. Verify binary location.
# ---------------------------------------------------------------------------
BIN="$HOME/qarsumo/build/qarsumo"
if [ -x "$BIN" ]; then
    echo "=== Build OK ==="
    echo "Binary: $BIN"
    ls -lh "$BIN"
    echo
    echo "The SimForge qarsumo adapter (adapters/qarsumo/qarsumo_adapter.py)"
    echo "will auto-find this binary — no env var or config needed."
else
    echo "=== Build FAILED — binary not found at expected path ==="
    echo "Expected: $BIN"
    echo "Look at the cmake/make output above to diagnose."
    exit 1
fi

echo
echo "=== Job complete at $(date) ==="
