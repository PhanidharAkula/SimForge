#!/bin/bash
# ============================================================================
# LPSim diagnostic — runs both binaries against the BUNDLED berkeley_2018
# sample (no SimForge inputs) so we can isolate "is the binary OK?" from
# "are our inputs OK?". If either binary completes here, the engine works
# on this GPU and the SimForge-side adapter is the divergence.
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_diag_lpsim
#SBATCH --partition=gpudebug
#SBATCH --gres=gpu:v100:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -uo pipefail
mkdir -p logs

module load gcc/13.2.0 cuda/11.8.0

SIF="$HOME/lpsim/lpsim.sif"
SRC="$HOME/lpsim/source"
BOOST="$HOME/lpsim/boost_1_59_0"

echo "=== Diag job starting on $(hostname) at $(date) ==="
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
echo

echo "=== 0. nvidia-smi inside container ==="
singularity exec --nv "$SIF" nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1
echo

echo "=== 1. What does /LivingCity look like in the container? ==="
singularity exec "$SIF" bash -c "ls /LivingCity/ ; echo '---' ; ls /LivingCity/berkeley_2018/ 2>&1 | head -20 ; echo '---' ; cat /LivingCity/command_line_options.ini 2>&1 | head -30"
echo

echo "=== 2. Bundled binary, bundled sample, no SimForge — first 60 lines ==="
singularity exec --nv "$SIF" bash -c "cd /LivingCity && ./LivingCity 2>&1" | head -60
RC2=${PIPESTATUS[0]}
echo "[bundled-on-bundled exit code: $RC2]"
echo

echo "=== 3. Rebuilt source binary, bundled sample, with /lpsim_src bind ==="
singularity exec --nv \
    --bind "$SRC:/lpsim_src" \
    --bind "$BOOST:/usr/local/boost_1_59_0" \
    "$SIF" bash -c "cd /LivingCity && /lpsim_src/LivingCity/LivingCity 2>&1" | head -60
RC3=${PIPESTATUS[0]}
echo "[rebuilt-on-bundled exit code: $RC3]"
echo

echo "=== 4. Library resolution under the rebuilt binary (LD_DEBUG=libs) ==="
echo "(filtered to CUDA-related lookups only)"
singularity exec --nv \
    --bind "$SRC:/lpsim_src" \
    --bind "$BOOST:/usr/local/boost_1_59_0" \
    --env "LD_DEBUG=libs" \
    "$SIF" bash -c "cd /LivingCity && /lpsim_src/LivingCity/LivingCity 2>&1" \
    | grep -iE "cuda|cublas|curand|nvrtc|nvidia" | head -30
echo

echo "=== Diag job finished at $(date) ==="
