#!/bin/bash
# ==============================================================
# SimForge — OSC Pitzer Cluster Setup
# ==============================================================
# Run this ONCE after SSH-ing into Pitzer to set up the project.
#
# Usage (on the cluster):
#   bash cluster/setup_pitzer.sh
# ==============================================================

set -euo pipefail

REPO_URL="https://github.com/PhanidharAkula/SimForge.git"
BRANCH="modelgen"
PROJECT_DIR="$HOME/SimForge"
VENV_DIR="$PROJECT_DIR/.venv"

echo "============================================"
echo "  SimForge — OSC Pitzer Setup"
echo "============================================"

# -----------------------------------------------------------
# 1. Clone or update repo
# -----------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "[1/5] Repo exists — pulling latest..."
    cd "$PROJECT_DIR"
    git pull origin "$BRANCH"
else
    echo "[1/5] Cloning repo..."
    git clone -b "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# -----------------------------------------------------------
# 2. Load Python module
# -----------------------------------------------------------
echo "[2/5] Loading Python 3.12 module..."
module purge 2>/dev/null || true
module load python/3.12

python3 --version

# -----------------------------------------------------------
# 3. Create venv and install deps
# -----------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "[3/5] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[3/5] Venv already exists, skipping creation..."
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# -----------------------------------------------------------
# 4. Install eclipse-sumo (no module on Pitzer)
# -----------------------------------------------------------
echo "[4/5] Installing SUMO via pip..."
pip install eclipse-sumo

# Verify SUMO
if python -c "import sumolib; print('sumolib OK')" 2>/dev/null; then
    echo "  ✓ sumolib installed"
fi

# Set SUMO_HOME for the adapter
SUMO_HOME_PATH=$(python -c "import os, sumolib; print(os.path.dirname(os.path.dirname(sumolib.__file__)))" 2>/dev/null || true)
if [ -n "$SUMO_HOME_PATH" ]; then
    echo "  SUMO_HOME: $SUMO_HOME_PATH"
fi

# -----------------------------------------------------------
# 5. Check modelgen files
# -----------------------------------------------------------
echo "[5/5] Checking modelgen data files..."
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
    echo "  scp modelgen/chicago_model.txt phanidharakula@pitzer.osc.edu:/users/PMIU0110/phanidharakula/SimForge/modelgen/"
fi

# -----------------------------------------------------------
# Summary
# -----------------------------------------------------------
echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo "  Python:   $(python3 --version)"
echo "  Venv:     $VENV_DIR"
echo "  Project:  $PROJECT_DIR"
echo "  Account:  PMIU0110"
echo ""
echo "Next steps:"
echo "  1. Transfer modelgen files (if missing above)"
echo "  2. Run tests:   python -m pytest tests/ -v"
echo "  3. Generate:    sbatch cluster/job_pitzer_200k.sh"
echo "============================================"
