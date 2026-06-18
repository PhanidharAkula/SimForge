# SimForge, reproducible cross-simulator benchmarking framework
# (SUMO + MATSim + DTALite, byte-deterministic adapters, Q1-Q5 fairness audit)
#
# Containerized execution with pinned-digest reproducibility: an
# OCI/Singularity image bundling the full software and compute
# environment.
#
# Build (local Docker, x86_64 target, Cardinal compatibility):
#   docker buildx build --platform linux/amd64 -t simforge:latest .
#
# Build (GitHub Actions): auto-built on every push to release
# via .github/workflows/build-container.yml; published to
# ghcr.io/phanidharakula/simforge:<branch> and :<sha>.
#
# Run (Docker, single benchmark):
#   docker run --rm \
#     -v $(pwd)/scenarios:/workspace/SimForge/scenarios:ro \
#     -v $(pwd)/runs:/workspace/SimForge/runs \
#     -v $(pwd)/cache:/workspace/SimForge/cache \
#     ghcr.io/phanidharakula/simforge:latest \
#     python -m execution.run_benchmark runspecs/benchmark_small.yaml
#
# Run (Singularity on Cardinal):
#   singularity pull docker://ghcr.io/phanidharakula/simforge:latest
#   singularity exec --bind scenarios:/workspace/SimForge/scenarios:ro \
#                    --bind runs:/workspace/SimForge/runs \
#                    --bind cache:/workspace/SimForge/cache \
#                    simforge_latest.sif \
#                    python -m execution.run_benchmark runspecs/benchmark_large.yaml
#
# Full usage: see doc/CONTAINER_USAGE.md

# Base: official Python 3.13 slim on Debian Bookworm.
# Pinned to a tagged ref. Future hardening: pin by digest
# (FROM python:3.13-slim-bookworm@sha256:...) for bit-deterministic builds.
FROM python:3.13-slim-bookworm

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
# - openjdk-17-jre-headless: MATSim 15.0 runtime (Java 17+)
# - libgomp1:                OpenMP runtime for DTALite (path4gmns bundled binary)
# - libxml2:                 lxml C bindings + SUMO netconvert output
# - libx11-6 + libxext6 +
#   libxrender1 + libxcb1 +
#   libgl1 + libglu1-mesa +
#   libfontconfig1 +
#   libfreetype6:            eclipse-sumo wheel's sumo binary links against
#                            X11 + OpenGL + FOX GUI toolkit even for headless
#                            CLI use (sumo --version triggers full dynamic
#                            link resolution before main()). manylinux_2_28
#                            wheels expect all of these from the host.
#                            Empirically discovered across GHA builds:
#                              a3aaed9 → libX11.so.6 missing
#                              cd5039e → libX11 added, libGL.so.1 missing
#                              780476f → libGL still missing (apt block added)
#                            All four sumo CLI binaries (sumo, netconvert,
#                            duarouter, sumo-gui) link against the same set.
# - git:                     for `git rev-parse HEAD` in tools/generate_scorecard
#                            (falls back to "unknown" if no .git tree, safe)
# - ca-certificates:         TLS verification (pip, OSM downloads)
# - curl:                    tools/download_osm.py (hash-verified PBF fetch)
# - tini:                    proper PID 1 / signal forwarding
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        libgomp1 \
        libatomic1 \
        libxml2 \
        libx11-6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
        libgl1 \
        libglu1-mesa \
        libfontconfig1 \
        libfreetype6 \
        git \
        ca-certificates \
        curl \
        unzip \
        tini \
 && rm -rf /var/lib/apt/lists/* \
 && java -version

# Install uv from the official pinned image layer (faster + more deterministic
# than pip install uv). Pinned tag prevents silent uv-version drift.
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/

WORKDIR /workspace/SimForge

# ---------------------------------------------------------------------------
# Python dependencies layer
# ---------------------------------------------------------------------------
# Cached as long as requirements.lock + pyproject.toml don't change.
# `--system` installs into the container's system Python (no venv needed
# inside the container, the container itself IS the isolation boundary).
# ---------------------------------------------------------------------------
COPY requirements.lock pyproject.toml ./
RUN uv pip install --system --no-cache -r requirements.lock

# eclipse-sumo is already pinned in requirements.lock, so the step above
# installed it. We re-assert the exact version here (a no-op if satisfied)
# only to anchor the binary-verification check below, since SUMO living in
# the immutable image is load-bearing for the container.
#
# Note on sumolib: eclipse-sumo wheel installs the SUMO binaries to
# /usr/local/bin/ (sumo, netconvert, duarouter, etc.) but does NOT put
# sumolib on Python sys.path, sumolib lives at site-packages/sumo/tools/sumolib
# and requires either SUMO_HOME setup or explicit sys.path appending.
# SimForge invokes SUMO as a subprocess (not `import sumolib`), so we
# verify the binary works, not the Python import.
RUN uv pip install --system --no-cache eclipse-sumo==1.26.0 && \
    SUMO_REAL_BIN=/usr/local/lib/python3.13/site-packages/sumo/bin/sumo && \
    if sumo --version 2>&1 | tee /tmp/sumo_version_check | grep -q "Eclipse SUMO"; then \
        rm /tmp/sumo_version_check; \
        echo "  ✓ eclipse-sumo wheel installed, sumo at $(which sumo)"; \
    else \
        echo "=== sumo --version output ==="; cat /tmp/sumo_version_check; \
        echo "=== ldd $SUMO_REAL_BIN (ALL libs, look for 'not found' lines) ==="; ldd "$SUMO_REAL_BIN" 2>&1; \
        echo "=== /usr/local/bin/ sumo-related files ==="; ls -la /usr/local/bin/ | grep -E 'sumo|netconvert|duarouter' | head; \
        exit 1; \
    fi

# ---------------------------------------------------------------------------
# SimForge source code layer
# ---------------------------------------------------------------------------
# Layer rebuilds when source changes. Python deps already installed above.
# Order: code → libs → docs → tests so editor-only changes (docs/tests)
# don't bust the source-code layer cache.
# ---------------------------------------------------------------------------
COPY adapters/      ./adapters/
COPY pipeline/      ./pipeline/
COPY evaluation/    ./evaluation/
COPY execution/     ./execution/
COPY visualization/ ./visualization/
COPY tools/         ./tools/
COPY runspecs/      ./runspecs/
COPY scripts/       ./scripts/
COPY canonical/     ./canonical/
COPY help.py run.py generate.py setup_simforge.py ./

# Engine libs (only manifest.json files for dtalite + container are tracked
# in git; the MATSim 15.0 release is downloaded fresh in the next step).
COPY lib/           ./lib/

# Download MATSim 15.0 runtime + transitive dependency JARs from upstream
# GitHub release. The matsim-15.0.zip is the canonical distribution
# (matsim-15.0.jar ~3 MB + libs/*.jar ~100 MB transitive deps). The git
# tag "matsim-15.0" is immutable on matsim-org/matsim-libs, so the URL
# is content-stable. Total ~100 MB into lib/matsim-15.0/.
#
# Why NOT track in git: the libs/ tree is ~70 JAR blobs totalling ~100 MB.
# Adding to git permanently bloats the history. Container-build download
# from immutable release is the standard pattern.
RUN cd /tmp \
 && curl -fsSL -o matsim-15.0.zip \
        https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip \
 && unzip -q matsim-15.0.zip -d /tmp/matsim-extract \
 && mkdir -p /workspace/SimForge/lib/matsim-15.0 \
 && if [ -d /tmp/matsim-extract/matsim-15.0 ]; then \
        cp -r /tmp/matsim-extract/matsim-15.0/. /workspace/SimForge/lib/matsim-15.0/; \
    else \
        cp -r /tmp/matsim-extract/. /workspace/SimForge/lib/matsim-15.0/; \
    fi \
 && rm -rf /tmp/matsim-15.0.zip /tmp/matsim-extract \
 && test -f /workspace/SimForge/lib/matsim-15.0/matsim-15.0.jar \
 && echo "  ✓ MATSim 15.0 downloaded: $(du -sh /workspace/SimForge/lib/matsim-15.0 | cut -f1) into lib/matsim-15.0/"

# Repo-root docs + license, keeps the image self-describing
COPY LICENSE README.md CHANGELOG.md SETUP.md TESTING.md CONTRIBUTING.md ./
COPY doc/           ./doc/

# Tests included so users can verify the container with `python -m pytest`
COPY tests/         ./tests/

# ---------------------------------------------------------------------------
# Build-time verification (fail-fast if any import/wire-up is broken)
# ---------------------------------------------------------------------------
# Imports the load-bearing modules + runs a tiny smoke. If this fails the
# image isn't published. Cheap insurance against pushing a broken container.
# ---------------------------------------------------------------------------
RUN python -c "import adapters.sumo.sumo_adapter; print('  ✓ SUMO adapter import OK')" \
 && python -c "import adapters.matsim.matsim_adapter; print('  ✓ MATSim adapter import OK')" \
 && python -c "import adapters.dtalite.dtalite_adapter; print('  ✓ DTALite adapter import OK')" \
 && python -c "import adapters.common.canonical_routes; print('  ✓ canonical_routes module OK')" \
 && python -c "import evaluation.audit_fairness, evaluation.analyze_benchmark; print('  ✓ evaluation tools OK')" \
 && python -c "import tools.generate_scorecard; print('  ✓ scorecard tool OK')" \
 && python -c "from execution.run_benchmark import BenchmarkHarness; print('  ✓ harness OK')" \
 && sumo --version 2>&1 | head -1 | grep -q "Eclipse SUMO" && echo "  ✓ eclipse-sumo: sumo binary works" \
 && python -c "import path4gmns; print(f'  ✓ path4gmns: {path4gmns.__version__ if hasattr(path4gmns,\"__version__\") else \"installed\"}')" \
 && test -f lib/matsim-15.0/matsim-15.0.jar \
 && echo "  ✓ MATSim 15.0 JAR present" \
 && echo "  Container build verification: PASS"

# ---------------------------------------------------------------------------
# Runtime metadata
# ---------------------------------------------------------------------------
# Bind mounts at runtime (NOT copied into image):
#   /workspace/SimForge/scenarios   read-only   canonical bundles
#   /workspace/SimForge/runs        read-write  benchmark outputs
#   /workspace/SimForge/osm_data    read-only   hash-pinned OSM PBFs (~2.1 GB)
#   /workspace/SimForge/cache       read-write  canonical_routes + osm_ways + events
#   /workspace/SimForge/modelgen    read-only   (optional) cityscape ModelGen
#   /workspace/SimForge/logs        read-write  harness/SLURM logs
#
# No CMD or ENTRYPOINT, caller invokes the desired SimForge command directly:
#   python -m execution.run_benchmark <runspec.yaml>
#   python -m evaluation.audit_fairness <run-dir>
#   python -m tools.generate_scorecard <run-dir>
#   python -m visualization.generate_maps --scenario <id> --maps all
# ---------------------------------------------------------------------------

ENTRYPOINT ["/usr/bin/tini", "--"]

# OCI image labels (visible in `docker inspect`, GHCR UI, ghcr.io README)
LABEL org.opencontainers.image.title="SimForge"
LABEL org.opencontainers.image.description="Reproducible cross-simulator benchmarking framework (SUMO + MATSim + DTALite). Master's thesis artefact."
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/PhanidharAkula/SimForge"
LABEL org.opencontainers.image.documentation="https://github.com/PhanidharAkula/SimForge/blob/main/doc/CONTAINER_USAGE.md"
LABEL org.opencontainers.image.authors="Phanidhar Akula <akulaphanidhar30@gmail.com>"
