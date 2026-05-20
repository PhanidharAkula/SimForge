# SimForge Container Usage

The SimForge container packages Python 3.13 + uv-pinned dependencies +
OpenJDK 17 + MATSim 15.0 + eclipse-sumo + path4gmns/DTALite + all
SimForge source code into a single immutable image. Closes the
plan §1.10 Objective 3 / §1.11 C3 / §2.7 / §4.2 container-execution
commitments.

Images are built by GitHub Actions on every push and published to
**`ghcr.io/phanidharakula/simforge`**.

---

## Quick start

### Docker (local dev / x86_64 hosts)

```bash
# Pull the latest stable
docker pull ghcr.io/phanidharakula/simforge:latest

# Or pin to a specific commit for reproducibility
docker pull ghcr.io/phanidharakula/simforge:phase-14-canonical-routes

# Run a benchmark
docker run --rm \
    -v $(pwd)/scenarios:/workspace/SimForge/scenarios:ro \
    -v $(pwd)/runs:/workspace/SimForge/runs \
    -v $(pwd)/cache:/workspace/SimForge/cache \
    ghcr.io/phanidharakula/simforge:latest \
    python -m execution.run_benchmark runspecs/benchmark_small.yaml
```

### Singularity / Apptainer (OSC Cardinal + most HPC)

```bash
# Pull once (Cardinal $HOME storage). Resolves Docker → Singularity SIF.
singularity pull docker://ghcr.io/phanidharakula/simforge:latest

# Run with bind-mounts. SimForge's gitignored dirs stay on the host:
singularity exec \
    --bind scenarios:/workspace/SimForge/scenarios:ro \
    --bind runs:/workspace/SimForge/runs \
    --bind cache:/workspace/SimForge/cache \
    --bind osm_data:/workspace/SimForge/osm_data:ro \
    simforge_latest.sif \
    python -m execution.run_benchmark runspecs/benchmark_large.yaml
```

---

## What's in the image

| Layer | Contents |
|---|---|
| Base OS | Debian Bookworm (slim, ~150 MB) |
| Java | OpenJDK 17 JRE headless (MATSim runtime; plan §1.10 Java 17+) |
| System libs | `libgomp1` (OpenMP for DTALite), `libxml2`, `git`, `curl`, `ca-certificates`, `tini` |
| Python | 3.13 from the official `python:3.13-slim-bookworm` |
| Package manager | `uv` 0.5.18 (deterministic + fast) |
| Python deps | All `requirements.lock` pins installed via `uv pip install --system` |
| Engine wheels | `eclipse-sumo` (1.26.0) + `path4gmns` (0.10.0, bundled DTALite) — both pulled from `requirements.lock` |
| MATSim | `lib/matsim-15.0/matsim-15.0.jar` (~3 MB, COPY'd directly) |
| SimForge source | `adapters/`, `pipeline/`, `evaluation/`, `execution/`, `visualization/`, `tools/`, `runspecs/`, `scripts/`, `canonical/`, `lib/`, `tests/`, `doc/`, top-level entry points |

Approximate image size: **~1.0-1.2 GB**.

## What's NOT in the image (bind-mount at runtime)

| Host dir | Mount as | Why excluded |
|---|---|---|
| `scenarios/` | `:ro` | Bundles (some gitignored, generated on host; can be GB-scale) |
| `runs/` | `:rw` | Benchmark outputs; you want these on the host for analysis |
| `osm_data/` | `:ro` | OSM PBFs (~2.1 GB, hash-pinned, license-bound under ODbL) |
| `cache/` | `:rw` | `canonical_routes/`, `events/`, `osm_ways/`, `census/`, `tiger_roads/` |
| `modelgen/` | `:ro` | (optional) cityscape ModelGen demand source files |
| `logs/` | `:rw` | (optional) harness/SLURM log capture |

The image is the deterministic execution environment; the host provides the data + persists the outputs. Standard container-with-bind-mounts pattern.

---

## Opt-in container mode in SLURM sbatchs

The `cluster/jobs/benchmark_small.sbatch` and `benchmark_large.sbatch`
wrappers support an opt-in `SIMFORGE_USE_CONTAINER=1` environment
variable. When set, the sbatch invokes the SimForge harness inside
the pinned-digest Singularity container instead of the host venv:

```bash
# Default (host venv — current behaviour):
sbatch cluster/jobs/benchmark_large.sbatch

# Container mode (Singularity exec inside the sbatch):
SIMFORGE_USE_CONTAINER=1 sbatch cluster/jobs/benchmark_large.sbatch
```

The sbatch picks up `SIMFORGE_CONTAINER_TAG` if set (default: `latest`),
so you can pin to a specific git SHA for the thesis-tier benchmark
runs that need a frozen execution environment:

```bash
SIMFORGE_USE_CONTAINER=1 \
SIMFORGE_CONTAINER_TAG=c5229dc \
sbatch cluster/jobs/benchmark_large.sbatch
```

---

## Manual build (if not using GitHub Actions)

```bash
docker buildx build --platform linux/amd64 -t simforge:local .

# Test that imports + smoke checks pass
docker run --rm simforge:local python -c "
import adapters.sumo.sumo_adapter
import adapters.matsim.matsim_adapter
import adapters.dtalite.dtalite_adapter
import evaluation.audit_fairness
print('  ✓ All load-bearing modules import')
"
```

For Cardinal, build locally (or via CI), save as a `.sif`, and `scp` to
Cardinal:

```bash
# On dev box with Docker + Singularity:
docker save simforge:local | singularity build simforge_local.sif docker-archive://-

# Then scp to Cardinal:
scp simforge_local.sif phanidharakula@cardinal.osc.edu:~/SimForge/containers/
```

---

## Verifying a pulled image

After `singularity pull` or `docker pull`, you can verify the image
matches the digest you expected:

```bash
# Docker
docker inspect ghcr.io/phanidharakula/simforge:latest --format='{{index .RepoDigests 0}}'

# Singularity (inside the pulled SIF)
singularity inspect simforge_latest.sif | grep -E 'Schema|Created|Digest'
```

Compare the `sha256:...` digest against `lib/container/manifest.json`
(thesis-tier benchmark runs pin a specific digest; see CHANGELOG
Wave 2 entry).

---

## Reproducibility chain (plan §3.4 + §4.2 alignment)

A complete cross-machine SimForge reproduction now looks like:

1. `singularity pull docker://ghcr.io/phanidharakula/simforge:<sha>` (immutable image, hash-verified by Singularity)
2. `tools/download_osm.py` on the host (hash-verified PBFs from `osm_data/manifest.json`)
3. `python generate.py --preset <name>` inside the container (deterministic canonical bundle)
4. `python -m execution.run_benchmark runspecs/<runspec>.yaml` inside the container
5. `python -m evaluation.audit_fairness <run-dir>` inside the container
6. `python -m tools.generate_scorecard <run-dir>` inside the container (auto-emitted by step 4)

Every step is hash-verified end-to-end:
- Container digest pins the execution environment
- OSM manifest pins the network input
- canonical_routes cache (Phase 14.13) is content-addressable
- Adapter outputs are byte-deterministic (determinism test marker)
- Scorecard records every hash + version in `reproducibility_scorecard.md`

---

## Troubleshooting

**`singularity pull` says "Image is private"**

The `phanidharakula/simforge` package on GHCR defaults to private when
the source repo is private. Either:
- Make the GHCR package public (GitHub repo Settings → Packages → make public)
- Or authenticate Singularity with a GHCR token (see Apptainer docs)

**`apptainer pull` panics with `index out of range [N] with length N` (Apptainer ≤ 1.4.5)**

Apptainer 1.4.x has an off-by-one bug in `progress_roundtrip.go:75` that
fires when ALL the OCI layers finish downloading. Stack trace ends with:

```
panic: runtime error: index out of range [11] with length 11
github.com/apptainer/apptainer/internal/pkg/client.(*RoundTripper).ProgressComplete(...)
    github.com/apptainer/apptainer/internal/pkg/client/progress_roundtrip.go:75
```

The download itself usually succeeds — all blobs are cached — but the
SIF conversion never starts because of the panic. Two workarounds:

1. **Pull by the immutable short SHA tag, not the branch tag.** For some
   reason this takes a different code path that avoids the panic:

   ```bash
   # Fails on Apptainer 1.4.5:
   apptainer pull docker://ghcr.io/phanidharakula/simforge:phase-14-canonical-routes

   # Works:
   apptainer pull docker://ghcr.io/phanidharakula/simforge:db8d786
   ```

   The full git SHA also works. Look up the current tag on the GHCR
   package page or in `lib/container/manifest.json`.

2. **Retry — sometimes the second pull succeeds.** The first pull
   populated the cache; the panic happens on the progress-complete code
   path, not the download. Retrying may skip enough of the affected
   code to land cleanly. Less reliable than option 1.

Tracked upstream at the Apptainer GitHub issues; fixed in newer
versions. Cardinal as of 2026-05-20 ships Apptainer 1.4.5; the
SHA-tag workaround is the operational recommendation.

**`MATSim ClassNotFoundException` inside container**

The JAR path inside the container is `lib/matsim-15.0/matsim-15.0.jar`.
The MATSim adapter resolves this relative to repo root. If you bind-mount
a different repo over `/workspace/SimForge`, you need to also mount the
`lib/` dir or the JAR won't be found.

**`netconvert` segfault on Apple Silicon when running container with
QEMU emulation**

This is a known SUMO + arm64 issue documented in `tests/conftest.py::is_arm64_netconvert_crash`.
Container is built for `linux/amd64`; running it on arm64 via QEMU
inherits this segfault. Use `--platform linux/amd64` only on x86_64
hosts (Cardinal works fine; arm64 Macs don't).

---

## Related docs

- `doc/REPRODUCING.md` — end-to-end thesis reproduction recipe
- `doc/PITZER.md` — Cardinal-specific SLURM setup
- `doc/LICENSING.md` — per-component license stack (Apache + EPL + GPL + ODbL + public domain)
- `doc/DATA_MANAGEMENT.md` — data sources, retention, PII policy
- `CHANGELOG.md` — Wave 2 entry for the container release
