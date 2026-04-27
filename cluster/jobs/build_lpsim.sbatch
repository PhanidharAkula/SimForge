#!/bin/bash
# ============================================================================
# LPSim build job for Pitzer.
#
# Three modes, in priority order:
#
# 1. **Singularity image pull** (default, ~10–20 min)
#    Pulls yibo123/lpsim:cuda12.4 to $HOME/lpsim/lpsim.sif. The image's
#    bundled binary is at /LivingCity/LivingCity inside the container.
#    KNOWN ISSUE (diagnosed Pitzer 2026-04-27): the bundled binary
#    crashes with a GPUassert / SIGSEGV inside the simulation kernel on
#    networks > a few thousand nodes. Use mode 2 if you hit this.
#
# 2. **In-container source rebuild** (set LPSIM_FORCE_SOURCE=1)
#    Reuses the pulled SIF as a BUILD environment (its Qt5/Boost/Pandana
#    deps are intact) and runs `qmake + make` on a fresh checkout of the
#    pinned LPSim SHA. Outputs the binary to
#    $HOME/lpsim/source/LivingCity/LivingCity on the host filesystem,
#    bind-mounted into the container at run time. The adapter prefers
#    this binary over the bundled one when it's present.
#    Submit:
#      sbatch --export=ALL,LPSIM_FORCE_SOURCE=1 cluster/jobs/build_lpsim.sbatch
#    Wall: ~30–45 min (clone + qmake + make inside the container).
#
# 3. **Native source build** (no SIF, no Docker, host-side toolchain)
#    Falls through if Singularity isn't on $PATH. Requires Qt5, Boost,
#    OpenCV, Pandana visible to the host compiler — which Pitzer does
#    NOT provide as modules. Mostly a placeholder; use mode 2 instead.
#
# REPRODUCIBILITY:
#   * git_sha and docker_image:tag are pinned in lib/lpsim/manifest.json.
#   * Override per-submit:
#       sbatch --export=ALL,LPSIM_GIT_SHA=abc123…,LPSIM_DOCKER_REF=foo:bar \
#         cluster/jobs/build_lpsim.sbatch
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

# Pitzer modules. cuda/11.8.0 is for the runtime injection in
# adapters/lpsim/lpsim_adapter.run_lpsim — even when we rebuild from
# source against the container's CUDA 12.4, the adapter still binds in
# CUDA 11.8 so the bundled-image fallback path keeps working too.
module load gcc/13.2.0 cuda/11.8.0

echo "=== Job starting on $(hostname) at $(date) ==="
echo "CUDA host:  $(nvcc --version 2>&1 | tail -1)"
echo "GCC host:   $(gcc --version | head -1)"
echo "GPU:        $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | head -1)"
echo "Mode:       LPSIM_FORCE_SOURCE=${LPSIM_FORCE_SOURCE:-0}"
echo

# ---------------------------------------------------------------------------
# Resolve pinned LPSim version from lib/lpsim/manifest.json (overridable).
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
SIF_PATH="$LPSIM_DIR/lpsim.sif"
SRC_DIR="$LPSIM_DIR/source"
SOURCE_BIN="$SRC_DIR/LivingCity/LivingCity"

# ---------------------------------------------------------------------------
# Mode 1 — Singularity image pull.
# Skipped when LPSIM_FORCE_SOURCE=1 AND a SIF already exists (we just need
# the SIF as a runtime / build env; no need to re-pull).
# ---------------------------------------------------------------------------
if command -v singularity >/dev/null 2>&1; then
    if [ -f "$SIF_PATH" ]; then
        echo "=== Singularity image already at $SIF_PATH — skipping pull ==="
    else
        echo "=== Pulling LPSim Singularity image ($LPSIM_DOCKER_REF) ==="
        singularity pull --force "$SIF_PATH" "docker://$LPSIM_DOCKER_REF" \
            && echo "    Pulled to $SIF_PATH" \
            || { echo "    Singularity pull failed."; rm -f "$SIF_PATH"; }
    fi

    # Verify the bundled binary is intact (mode 1's product).
    if [ -f "$SIF_PATH" ]; then
        echo "=== Verifying bundled binary inside SIF ==="
        IN_CONTAINER_BIN="${LPSIM_CONTAINER_BINARY:-/LivingCity/LivingCity}"
        if singularity exec --nv "$SIF_PATH" test -x "$IN_CONTAINER_BIN"; then
            echo "    OK: $IN_CONTAINER_BIN present in image."
        else
            echo "    WARN: $IN_CONTAINER_BIN missing inside SIF."
        fi
    fi
fi

# If we're not forcing source rebuild, exit here. The bundled binary in
# the SIF is the deliverable. Mode 1 ends.
if [ "${LPSIM_FORCE_SOURCE:-0}" != "1" ]; then
    if [ -f "$SIF_PATH" ]; then
        echo
        echo "=== Done — Singularity image ready at $SIF_PATH ==="
        echo "    Bundled binary: /LivingCity/LivingCity (inside the SIF)"
        echo "    The adapter (adapters/lpsim/lpsim_adapter.py) will auto-find it."
        echo
        echo "    If LPSim crashes on your network shape, re-run this job with:"
        echo "      sbatch --export=ALL,LPSIM_FORCE_SOURCE=1 cluster/jobs/build_lpsim.sbatch"
        exit 0
    fi
    # No SIF and no force-source — fall through to mode 3 (native build).
fi

# ---------------------------------------------------------------------------
# Mode 2 — In-container source rebuild (LPSIM_FORCE_SOURCE=1).
# Uses the SIF as a build environment so we don't have to install Qt5,
# Boost, Pandana, etc. on the host.
# ---------------------------------------------------------------------------
if [ "${LPSIM_FORCE_SOURCE:-0}" = "1" ] && [ -f "$SIF_PATH" ]; then
    echo
    echo "=== Mode 2: in-container source rebuild ==="
    echo "    SIF (build env): $SIF_PATH"
    echo "    Source dir:      $SRC_DIR"
    echo "    Pinned SHA:      $LPSIM_GIT_SHA"
    echo

    # Clone or refresh the source on the host.
    if [ -d "$SRC_DIR/.git" ]; then
        echo "--- Refreshing existing clone ---"
        cd "$SRC_DIR"
        git fetch --quiet
    else
        echo "--- Cloning Xuan-1998/LPSim into $SRC_DIR ---"
        rm -rf "$SRC_DIR"
        git clone https://github.com/Xuan-1998/LPSim.git "$SRC_DIR"
        cd "$SRC_DIR"
    fi

    echo "--- Checking out pinned SHA $LPSIM_GIT_SHA ---"
    git checkout --detach "$LPSIM_GIT_SHA"
    git --no-pager log -1 --format='Now at: %h  %s  (%ad)' --date=short
    echo

    # The upstream repo commits a pre-built LivingCity binary (yes, really).
    # Delete it so a stale binary can't masquerade as a successful build —
    # we only want a fresh compile to count.
    echo "--- Removing any pre-committed binary so stale builds can't pass ---"
    rm -f "$SRC_DIR/LivingCity/LivingCity"
    rm -rf "$SRC_DIR/LivingCity/obj"

    # Boost 1.59 inside the SIF lives at /usr/local/boost_1_59_0/ but is
    # mode 0700 owned by nobody:nogroup under Apptainer's user-namespace
    # remapping — completely unreadable to our build user. The container
    # also has no system Boost at /usr/include/boost. Workaround: download
    # the Boost 1.59 tarball to a host-writable location and bind-mount
    # it OVER the broken path inside the container at build time.
    # Diagnosed Pitzer 2026-04-27.
    BOOST_HOST_DIR="$LPSIM_DIR/boost_1_59_0"
    if [ ! -d "$BOOST_HOST_DIR" ]; then
        echo "--- Downloading Boost 1.59.0 to $BOOST_HOST_DIR (~80 MB tarball, ~600 MB extracted) ---"
        BOOST_TARBALL="$LPSIM_DIR/boost_1_59_0.tar.gz"
        if [ ! -f "$BOOST_TARBALL" ]; then
            # Boost.org's official jfrog mirror — reliable, no SourceForge
            # interstitial nonsense.
            wget --quiet --show-progress \
                -O "$BOOST_TARBALL" \
                "https://boostorg.jfrog.io/artifactory/main/release/1.59.0/source/boost_1_59_0.tar.gz" \
                || { echo "    Boost download failed; abort."; exit 1; }
        fi
        echo "--- Extracting Boost ---"
        tar -xzf "$BOOST_TARBALL" -C "$LPSIM_DIR"
        if [ ! -d "$BOOST_HOST_DIR" ]; then
            echo "    Tarball extracted but $BOOST_HOST_DIR not present — wrong tarball layout?"
            exit 1
        fi
        echo "    Extracted: $BOOST_HOST_DIR"
        ls -la "$BOOST_HOST_DIR" | head -5
    else
        echo "--- Boost 1.59 already extracted at $BOOST_HOST_DIR — reusing ---"
    fi

    # Patch LivingCity.pro to use the container's CUDA 12.4 instead of
    # hard-coded 11.2 / 10.1 / 9.0 paths. Without this, qmake falls
    # through to the 9.0 default and make then dies on
    # `/usr/local/cuda-9.0/bin/nvcc: No such file or directory`.
    # Diagnosed Pitzer 2026-04-27.
    echo "--- Patching LivingCity.pro to point at CUDA 12.4 ---"
    if [ -f "$SRC_DIR/LivingCity/LivingCity.pro" ]; then
        # Show the original CUDA references for the audit trail, then patch.
        echo "  (original CUDA references):"
        grep -n 'cuda-' "$SRC_DIR/LivingCity/LivingCity.pro" || echo "    (none)"
        sed -i \
            -e 's|/usr/local/cuda-11.2|/usr/local/cuda-12.4|g' \
            -e 's|/usr/local/cuda-10.1|/usr/local/cuda-12.4|g' \
            -e 's|/usr/local/cuda-9.0|/usr/local/cuda-12.4|g' \
            -e 's|cuda-11.2|cuda-12.4|g' \
            -e 's|cuda-10.1|cuda-12.4|g' \
            -e 's|cuda-9.0|cuda-12.4|g' \
            "$SRC_DIR/LivingCity/LivingCity.pro"
        echo "  (after patch):"
        grep -n 'cuda-' "$SRC_DIR/LivingCity/LivingCity.pro" || echo "    (none)"
    fi

    # Run qmake + make INSIDE the container, with the host source dir
    # bind-mounted at /lpsim_src AND the host-side Boost bind-mounted
    # over the broken /usr/local/boost_1_59_0/ inside. Capture the exit
    # status explicitly so we don't get fooled by a partial-write binary.
    echo "--- Building LivingCity inside the container ---"
    echo "    (uses container's qmake / make / g++ / nvcc against its CUDA 12.4)"
    echo "    (Boost mounted from $BOOST_HOST_DIR → /usr/local/boost_1_59_0)"
    set +e
    singularity exec --nv \
        --bind "$SRC_DIR:/lpsim_src" \
        --bind "$BOOST_HOST_DIR:/usr/local/boost_1_59_0" \
        "$SIF_PATH" \
        bash -lc "set -eo pipefail; cd /lpsim_src/LivingCity && \
                  echo '--- qmake ---' && qmake LivingCity.pro && \
                  echo '--- make ---' && make -j$SLURM_CPUS_PER_TASK 2>&1 | tail -80"
    BUILD_RC=$?
    set -e
    echo
    echo "in-container build exit code: $BUILD_RC"
    echo

    if [ "$BUILD_RC" -ne 0 ] || [ ! -x "$SOURCE_BIN" ]; then
        echo "=== In-container build FAILED ==="
        echo "  Build exit code:  $BUILD_RC"
        echo "  Binary present:   $([ -x "$SOURCE_BIN" ] && echo yes || echo no)"
        echo "  Look at the qmake/make output above to diagnose."
        echo
        echo "  Common fixes:"
        echo "    * CUDA detection broken — patch the sed substitutions in"
        echo "      this sbatch (lines around 'Patching LivingCity.pro')."
        echo "    * Missing source file (benchmarker.cpp etc.) — already"
        echo "      ignored by upstream; the warnings above are benign."
        echo "    * nvcc -arch mismatch — V100 is sm_70; the .pro may pin sm_50."
        echo "    * Boost permissions — confirm $BOOST_HOST_DIR is readable"
        echo "      and the bind-mount in the singularity exec line above"
        echo "      is correct."
        exit 1
    fi

    echo "=== In-container build OK ==="
    echo "Binary:    $SOURCE_BIN"
    ls -lh "$SOURCE_BIN"
    file "$SOURCE_BIN" 2>/dev/null || true
    echo
    echo "Provenance:"
    echo "  LPSim git SHA:      $LPSIM_GIT_SHA"
    echo "  Built against:      container's CUDA 12.4 + Qt5"
    echo "  Pinned in manifest: lib/lpsim/manifest.json"
    echo
    echo "The adapter will prefer this binary over the bundled one."
    echo "It runs as: singularity exec --nv --bind \$SRC:/lpsim_src \$SIF /lpsim_src/LivingCity/LivingCity"
    echo
    echo "=== Job complete at $(date) ==="
    exit 0
fi

# ---------------------------------------------------------------------------
# Mode 3 — Native source build (fallback when no SIF and not forcing source).
# Pitzer doesn't provide Qt5/Boost-1.59/OpenCV4/Pandana as modules, so this
# almost certainly fails. Kept as a stub for future hosts that DO provide
# the deps; current Pitzer should always use Mode 1 or Mode 2.
# ---------------------------------------------------------------------------
echo
echo "=== Mode 3: native source build (no SIF available) ==="
echo "    NOTE: this path requires Qt5 + Boost 1.59 + OpenCV 4.x + Pandana"
echo "    on the host's compiler search path — Pitzer does NOT supply these"
echo "    as lmod modules. Use Mode 1 (default) or Mode 2 (LPSIM_FORCE_SOURCE=1)"
echo "    instead unless you've installed those deps yourself."
echo

if [ -d "$SRC_DIR/.git" ]; then
    cd "$SRC_DIR"
    git fetch --quiet
else
    rm -rf "$SRC_DIR"
    git clone https://github.com/Xuan-1998/LPSim.git "$SRC_DIR"
    cd "$SRC_DIR"
fi
git checkout --detach "$LPSIM_GIT_SHA"

cd "$SRC_DIR/LivingCity"
qmake LivingCity.pro
make -j"$SLURM_CPUS_PER_TASK" 2>&1 | tail -30

if [ -x "$SOURCE_BIN" ]; then
    echo "=== Native build OK ==="
    ls -lh "$SOURCE_BIN"
else
    echo "=== Native build FAILED ==="
    exit 1
fi
echo
echo "=== Job complete at $(date) ==="
