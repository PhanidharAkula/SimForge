#!/bin/bash
# ==============================================================
# SimForge — RedHawk HPC Cluster Setup
# ==============================================================
# Run this ONCE after SSH-ing into RedHawk to set up the project.
#
# Usage (on the cluster):
#   bash cluster/setup_redhawk.sh
# ==============================================================

set -euo pipefail

REPO_URL="https://github.com/PhanidharAkula/simforge.git"
BRANCH="modelgen"
PROJECT_DIR="$HOME/SimForge"
VENV_DIR="$PROJECT_DIR/.venv"

echo "============================================"
echo "  SimForge — RedHawk Setup"
echo "============================================"

# -----------------------------------------------------------
# 1. Clone or update repo
# -----------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "[1/4] Repo exists — pulling latest..."
    cd "$PROJECT_DIR"
    git pull origin "$BRANCH"
else
    echo "[1/4] Cloning repo..."
    git clone -b "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# -----------------------------------------------------------
# 2. Load Python module
# -----------------------------------------------------------
echo "[2/4] Loading Python module..."
module purge 2>/dev/null || true

# Try common module names (varies by cluster config)
if module avail python 2>&1 | grep -q "python/3.10"; then
    module load python/3.10
elif module avail python 2>&1 | grep -q "python/3.11"; then
    module load python/3.11
elif module avail python 2>&1 | grep -q "python3"; then
    module load python3
else
    echo "WARNING: No Python 3.10+ module found. Trying system python3..."
fi

python3 --version

# -----------------------------------------------------------
# 3. Create venv and install deps
# -----------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "[3/4] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[3/4] Venv already exists, skipping creation..."
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# -----------------------------------------------------------
# 4. Check modelgen files
# -----------------------------------------------------------
echo "[4/4] Checking modelgen data files..."
MODELGEN_DIR="$PROJECT_DIR/modelgen"
MISSING=0

for city in chicago la nyc; do
    FILE="$MODELGEN_DIR/${city}_model.txt"
    if [ -f "$FILE" ]; then
        SIZE=$(du -h "$FILE" | cut -f1)
        echo "  ✓ ${city}_model.txt ($SIZE)"
    else
        echo "  ✗ ${city}_model.txt — MISSING"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "WARNING: Some modelgen files are missing."
    echo "Transfer them from your Mac:"
    echo "  scp modelgen/chicago_model.txt akulap@redhawk.hpc.miamioh.edu:~/SimForge/modelgen/"
    echo "  scp modelgen/la_model.txt      akulap@redhawk.hpc.miamioh.edu:~/SimForge/modelgen/"
    echo "  scp modelgen/nyc_model.txt     akulap@redhawk.hpc.miamioh.edu:~/SimForge/modelgen/"
fi

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo "  Project:  $PROJECT_DIR"
echo "  Python:   $(python3 --version)"
echo "  Venv:     $VENV_DIR"
echo ""
echo "Next steps:"
echo "  1. Transfer modelgen files (if missing above)"
echo "  2. Submit job:  sbatch cluster/job_200k.sh"
echo "============================================"
