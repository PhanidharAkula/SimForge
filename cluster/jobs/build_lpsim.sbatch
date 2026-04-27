#!/bin/bash
# ============================================================================
# One-time LPSim build / image-pull on Pitzer's GPU partition.
#
# After this job completes successfully, ONE of the following will exist:
#   $HOME/lpsim/LivingCity/LivingCity   (native binary built from source)
#   $HOME/lpsim/lpsim.sif               (Singularity image pulled from Docker)
#
# The SimForge LPSim adapter (adapters/lpsim/lpsim_adapter.py) auto-finds
# either at run time — no env var or config tweak needed.
#
# Re-run this only when CUDA / GCC versions on Pitzer change, or when the
# pin in lib/lpsim/manifest.json is bumped to track a new upstream LPSim
# commit. Otherwise build once and use the binary across all benchmark jobs.
#
# Wall: ~30-60 min for native build (clone + dependency install + cmake +
# make), ~10-20 min for Singularity pull. 2 h budget covers both paths.
#
# REPRODUCIBILITY — what gets pinned:
#   * LPSim source: git checkout to the SHA recorded in lib/lpsim/manifest.json
#     (currently 452067ee… from 2024-11-27).
#   * Singularity image: pulled by tag (yibo123/lpsim:cuda12.4) on first
#     build; the resolved digest is then sha256-locked in lib/lpsim/manifest.json
#     (digest field) so subsequent re-pulls land on the same image. Today
#     the digest is null because no Pitzer build has run yet — bump the
#     manifest after the first successful build.
#
# Override either pin via env vars on the sbatch line, e.g.:
#   sbatch --export=LPSIM_GIT_SHA=abc123… cluster/jobs/build_lpsim.sbatch
#
# Edit before submitting on a different OSC project:
#   --account=...     your project allocation (replaces PMIU0110)
#
# Submit from the repo root:   sbatch cluster/jobs/build_lpsim.sbatch
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_build_lpsim
#SBATCH --partition=gpu
#SBATCH --gres=gpu:v100:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail

mkdir -p logs

# Pitzer's lmod requires explicit versions. As of 2026-04 the matching pair is
# gcc/13.2.0 + cuda/12.6.2 (check current options with `module avail gcc cuda`).
# LPSim's Dockerfile pins cuda/11.2 but newer CUDA back-compat is fine.
module load gcc/13.2.0 cuda/12.6.2

echo "=== Job starting on $(hostname) at $(date) ==="
echo "CUDA:   $(nvcc --version 2>&1 | tail -1)"
echo "GCC:    $(gcc --version | head -1)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | head -1)"
echo

# ---------------------------------------------------------------------------
# Resolve pinned LPSim version from lib/lpsim/manifest.json (overridable).
# Falls back to a hard-coded default if jq isn't available.
# ---------------------------------------------------------------------------
MANIFEST="$(pwd)/lib/lpsim/manifest.json"
DEFAULT_SHA="452067ee831e6ecb4c906bae96fb77fdf71fa92e"
DEFAULT_DOCKER_REF="yibo123/lpsim:cuda12.4"

if [ -z "${LPSIM_GIT_SHA:-}" ]; then
    if command -v jq >/dev/null 2>&1 && [ -f "$MANIFEST" ]; then
        LPSIM_GIT_SHA="$(jq -r '.lpsim.git_sha' "$MANIFEST")"
    else
        LPSIM_GIT_SHA="$DEFAULT_SHA"
    fi
fi
if [ -z "${LPSIM_DOCKER_REF:-}" ]; then
    if command -v jq >/dev/null 2>&1 && [ -f "$MANIFEST" ]; then
        LPSIM_DOCKER_REF="$(jq -r '.lpsim.docker_image + ":" + .lpsim.docker_tag' "$MANIFEST")"
    else
        LPSIM_DOCKER_REF="$DEFAULT_DOCKER_REF"
    fi
fi

echo "Pinned LPSim git SHA:    $LPSIM_GIT_SHA"
echo "Pinned LPSim Docker ref: $LPSIM_DOCKER_REF"
echo

LPSIM_DIR="$HOME/lpsim"
mkdir -p "$LPSIM_DIR"

# ---------------------------------------------------------------------------
# Path A — Singularity image pull (preferred when available).
# Fast, reproducible, and skips the dependency-install dance entirely.
# ---------------------------------------------------------------------------
if command -v singularity >/dev/null 2>&1; then
    SIF_PATH="$LPSIM_DIR/lpsim.sif"
    if [ -f "$SIF_PATH" ]; then
        echo "=== Singularity image already present at $SIF_PATH — skipping pull ==="
    else
        echo "=== Pulling LPSim Singularity image ($LPSIM_DOCKER_REF) ==="
        singularity pull --force "$SIF_PATH" "docker://$LPSIM_DOCKER_REF" \
            && echo "    Pulled to $SIF_PATH" \
            || { echo "    Singularity pull failed — falling through to source build."; rm -f "$SIF_PATH"; }
    fi
    if [ -f "$SIF_PATH" ]; then
        echo
        echo "=== Verifying Singularity image ==="
        singularity exec --nv "$SIF_PATH" bash -c 'which LivingCity && nvcc --version | tail -1' \
            || echo "    Verification command failed (image may still be usable; the adapter will retry at run time)"
        echo
        echo "=== TODO — record image digest in lib/lpsim/manifest.json ==="
        echo "    Run on a login node:"
        echo "      sha256sum $SIF_PATH"
        echo "    Then update lib/lpsim/manifest.json::lpsim.docker_digest with"
        echo "    the returned hex string (or the registry digest from"
        echo "    'singularity inspect $SIF_PATH'), and commit the manifest."
        echo
        echo "=== Done — Singularity image ready at $SIF_PATH ==="
        echo "    The lpsim adapter (adapters/lpsim/lpsim_adapter.py) will auto-find it."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Path B — clone + build LPSim from source.
# Use this when Singularity is unavailable or the pull failed.
# ---------------------------------------------------------------------------
SRC_DIR="$LPSIM_DIR/source"
if [ -d "$SRC_DIR/.git" ]; then
    echo "=== Refreshing existing LPSim clone at $SRC_DIR ==="
    cd "$SRC_DIR"
    git fetch --quiet
else
    echo "=== Cloning Xuan-1998/LPSim into $SRC_DIR ==="
    rm -rf "$SRC_DIR"
    git clone https://github.com/Xuan-1998/LPSim.git "$SRC_DIR"
    cd "$SRC_DIR"
fi

echo "=== Checking out pinned SHA $LPSIM_GIT_SHA ==="
git checkout --detach "$LPSIM_GIT_SHA"
git --no-pager log -1 --format='Now at: %h  %s  (%ad)' --date=short
echo

echo "=== Installing Python dependencies (if any) ==="
if [ -f requirements.txt ]; then
    pip install --user -r requirements.txt || \
        echo "    pip install failed — proceeding anyway; build itself doesn't need them."
fi
echo

echo "=== Building LivingCity (make -j$SLURM_CPUS_PER_TASK) ==="
cd "$SRC_DIR/LivingCity"
make -j"$SLURM_CPUS_PER_TASK" 2>&1 | tail -30
echo

# ---------------------------------------------------------------------------
# Verify the binary landed where the adapter expects it.
# adapters/lpsim/lpsim_adapter.find_lpsim_binary checks:
#   1. $LPSIM_BINARY
#   2. $HOME/lpsim/LivingCity/LivingCity
#   3. $HOME/lpsim/LivingCity
# We expose path 2 by symlinking the built binary into place.
# ---------------------------------------------------------------------------
EXPECTED_DIR="$LPSIM_DIR/LivingCity"
mkdir -p "$EXPECTED_DIR"
if [ -x "$SRC_DIR/LivingCity/LivingCity" ]; then
    ln -sf "$SRC_DIR/LivingCity/LivingCity" "$EXPECTED_DIR/LivingCity"
    echo "=== Build OK ==="
    echo "Binary: $EXPECTED_DIR/LivingCity (symlinked from source tree)"
    ls -lh "$EXPECTED_DIR/LivingCity"
    echo
    echo "Provenance:"
    echo "  LPSim git SHA: $LPSIM_GIT_SHA"
    echo "  Pinned in:     lib/lpsim/manifest.json"
    echo
    echo "The SimForge LPSim adapter (adapters/lpsim/lpsim_adapter.py)"
    echo "will auto-find this binary — no env var or config needed."
else
    echo "=== Build FAILED — binary not found at expected path ==="
    echo "Expected: $SRC_DIR/LivingCity/LivingCity"
    echo "Look at the make output above to diagnose."
    exit 1
fi

echo
echo "=== Job complete at $(date) ==="
