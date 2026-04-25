# SimForge on OSC Pitzer

This is the authoritative guide for running SimForge on the Ohio Supercomputer
Center's Pitzer cluster — the HPC target used for all 50K – 500K scenarios in
the thesis. Everything below is verified against the actual end-to-end run
that produced the published numbers.

> Local development (Apple Silicon / Linux laptop) is covered in
> [`SETUP.md`](../SETUP.md). This doc focuses on what changes on Pitzer:
> accounts, filesystems, module loads, PBF transfers, and SLURM submission.

---

## Table of Contents

1. [What runs on Pitzer](#1-what-runs-on-pitzer)
2. [Hardware and filesystems](#2-hardware-and-filesystems)
3. [Account setup and SSH](#3-account-setup-and-ssh)
4. [First-time bootstrap](#4-first-time-bootstrap)
5. [Transferring OSM PBFs and ModelGen files](#5-transferring-osm-pbfs-and-modelgen-files)
6. [Interactive testing with srun](#6-interactive-testing-with-srun)
7. [SLURM batch jobs](#7-slurm-batch-jobs)
8. [Monitoring jobs](#8-monitoring-jobs)
9. [Benchmark matrix on Pitzer](#9-benchmark-matrix-on-pitzer)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What runs on Pitzer

| SimForge component                  | Status | Notes                                                              |
| ----------------------------------- | ------ | ------------------------------------------------------------------ |
| Scenario generation (synthetic)     | Works  | Pure Python, no external data required                             |
| Scenario generation (PBF + census)  | Works  | PBFs rsynced from local (see §5); no Overpass hits on compute node |
| SUMO meso + micro                   | Works  | `pip install eclipse-sumo` inside the venv                         |
| MATSim 15.0                         | Works  | `module load openjdk` + `lib/matsim-15.0/matsim-15.0.jar`          |
| QarSUMO (real GPU)                  | Works  | Build from source on a `gpu` partition node                        |
| Evaluation + plot rendering         | Works  | Pure Python (matplotlib in venv)                                   |
| Bundle validation + SHA-256 hashing | Works  | Pure Python                                                        |

The meaningful upgrade versus running locally is QarSUMO: on a V100 node the
adapter exercises the real GPU kernels instead of falling back to bit-identical
SUMO meso, so the speedup story can be measured rather than asserted.

---

## 2. Hardware and filesystems

### Cluster profile

| Feature             | Specification                                                              |
| ------------------- | -------------------------------------------------------------------------- |
| Operator            | Ohio Supercomputer Center (state-funded)                                   |
| Login nodes         | 4 × `pitzer.osc.edu` (round-robin DNS to `pitzer-login01` … `04`)          |
| OS                  | RHEL 9                                                                     |
| Scheduler           | SLURM                                                                      |
| Standard CPU nodes  | 564 nodes — Skylake (40 cores, 192 GB) or Cascade Lake (48 cores, 192 GB)  |
| Large-memory nodes  | 12 × ~744 GB + 4 × 3 TB (huge-mem, 80 cores)                               |
| GPU nodes           | 74 × dual-V100 (16 GB or 32 GB) + 4 × quad-V100 (32 GB)                    |
| Aggregate           | 658 nodes / 29,664 cores                                                   |
| Project account     | `PMIU0110` (advisor's allocation — passed via `--account=PMIU0110`)        |

### Filesystems

| Filesystem                      | Quota  | Backed up | Purge       | Use for                               |
| ------------------------------- | ------ | --------- | ----------- | ------------------------------------- |
| `$HOME` = `/users/PMIU0110/<u>` | 500 GB | yes       | never       | Repo clone, venv, MATSim JAR          |
| `/fs/ess/PMIU0110/`             | 500 GB | yes       | never       | Shared project data (advisor approval)|
| `/fs/scratch/PMIU0110/<u>/`     | 100 TB | no        | ~90 days    | Large benchmark runs, intermediate IO |
| `$TMPDIR` (per-job)             | node   | no        | end of job  | Per-job local scratch                 |

**Recommended layout:**

- **Repo + venv** → `$HOME/SimForge` (owns quota, survives reboots)
- **PBFs + ModelGen** → `$HOME/SimForge/osm_data/` and `$HOME/SimForge/modelgen/` (committed paths, gitignored data)
- **Benchmark runs** → `/fs/scratch/PMIU0110/$USER/runs/` (symlink `runs/ -> /fs/scratch/.../runs/`)

### Internet access

Outbound HTTPS works on both login and compute nodes, routed through OSC's
NAT (`192.148.249.248–251`). This means:

- `pip install eclipse-sumo` works in batch jobs ✓
- `git clone`, `git pull`, `gh` work ✓
- Package fetches from PyPI, GitHub releases succeed ✓
- **Inbound is blocked** — you can't expose a service on a compute node.

If a public endpoint is ever blocked, email `oschelp@osc.edu`.

> **Note on Overpass:** SimForge no longer requires live Overpass access
> because it reads hash-pinned local PBFs (see §5 and the top-level
> [`SETUP.md`](../SETUP.md#osm-data)). Pitzer can reach Overpass if needed
> for ad-hoc fetches, but no part of the thesis pipeline depends on it.

---

## 3. Account setup and SSH

1. **Request an OSC account** (if you don't already have one) through your
   advisor's project at <https://my.osc.edu/>. You will receive a username
   (e.g., `phanidharakula`) under project `PMIU0110`.

2. **Set up SSH key** (recommended — avoids password prompts):

   ```bash
   # On your local machine
   ssh-keygen -t ed25519 -C "osc-pitzer"
   ssh-copy-id <username>@pitzer.osc.edu
   ```

3. **Add a config block to `~/.ssh/config`**:

   ```ssh
   Host pitzer
       HostName pitzer.osc.edu
       User <your-osc-username>
       IdentityFile ~/.ssh/id_ed25519
       ServerAliveInterval 60
   ```

   After this, `ssh pitzer` is enough.

4. **Verify project membership:**

   ```bash
   ssh pitzer
   id          # groups should include "PMIU0110"
   groups      # same
   myquota     # shows home + project usage
   ```

---

## 4. First-time bootstrap

After SSH'ing into Pitzer, run this sequence once. Expect ~15 minutes
including the pip install and MATSim JAR download.

```bash
# 4.1 — clone into $HOME (500 GB quota, no advisor permission needed)
cd $HOME
git clone -b Version_2 https://github.com/PhanidharAkula/SimForge.git
cd SimForge

# 4.2 — load modules (persistent: add to ~/.bashrc if you want)
module load python/3.12
module load openjdk     # needed only for MATSim

# 4.3 — create venv and install Python deps
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest-cov, pytest-xdist, mutmut

# 4.4 — install SUMO (not a module on Pitzer; pip wheel works)
pip install eclipse-sumo
sumo --version        # expect 1.20+

# 4.5 — download MATSim 15.0 JAR (~65 MB)
mkdir -p lib
curl -L -o matsim-15.0-release.zip \
    https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip
unzip matsim-15.0-release.zip -d lib/
rm matsim-15.0-release.zip
ls lib/matsim-15.0/matsim-15.0.jar       # should exist

# 4.6 — verify the unit suite before doing anything expensive
python -m pytest tests/ -m "not slow" -q
```

### Module cheatsheet

Authoritative list: `module spider <name>` on a logged-in shell (module
versions rebump after cluster upgrades). As of 2026-04:

| Software   | Module command               | Purpose                         |
| ---------- | ---------------------------- | ------------------------------- |
| Python     | `module load python/3.12`    | Standard runtime                |
| GCC        | `module load gcc`            | Usually unneeded (modern default) |
| OpenJDK    | `module load openjdk`        | MATSim runtime                  |
| CUDA       | `module load cuda`           | QarSUMO build / run             |
| Git        | pre-installed                | —                               |
| SUMO       | **not** a module             | use `pip install eclipse-sumo`  |

Add the modules to `~/.bashrc` if you hate typing them every session:

```bash
echo 'module load python/3.12 openjdk' >> ~/.bashrc
```

---

## 5. Transferring OSM PBFs and ModelGen files

SimForge reads road networks from hash-pinned Geofabrik PBFs listed in
[`osm_data/manifest.json`](../osm_data/manifest.json). The PBFs themselves
are **not** in git (they're too large — 348 MB – 1.3 GB per state). ModelGen
population files (`modelgen/*_model.txt`, 281 MB – 608 MB each) are also
gitignored.

There are two ways to land these files on Pitzer:

### Option A — rsync from your local machine (recommended)

If you already have the PBFs and ModelGen files locally (e.g., from your dev
laptop), rsync is fastest because OSC's inbound pipe is ~Gbps:

```bash
# From your local machine (not from Pitzer)
cd /path/to/SimForge

rsync -avh --progress osm_data/ pitzer:SimForge/osm_data/
rsync -avh --progress modelgen/ pitzer:SimForge/modelgen/
```

Rsync preserves mtime and skips already-transferred files, so re-running is
cheap.

### Option B — download on Pitzer itself

Everything needed is reachable from Pitzer's NAT:

```bash
# On Pitzer, inside .venv
python tools/download_osm.py
# downloads the 3 PBFs listed in osm_data/manifest.json (~2.1 GB total)
# and verifies SHA-256 against the manifest

# ModelGen files must be sourced separately (not in a public repo);
# coordinate with your advisor or regenerate them with the C++ tool.
```

### Verify the transfer

```bash
ls -lh osm_data/*.pbf
# illinois-2026-04-22.osm.pbf      332M
# new-york-2026-04-22.osm.pbf      467M
# california-2026-04-22.osm.pbf    1.2G

# Re-run the downloader as a hash check (no-op if hashes match)
python tools/download_osm.py
# Expect:   [illinois] OK (sha256 matches manifest)
#           [new-york] OK (sha256 matches manifest)
#           [california] OK (sha256 matches manifest)
```

---

## 6. Interactive testing with srun

Before submitting batch jobs, smoke-test the pipeline interactively on a
compute node. This avoids wasting queue time if a dependency is missing.

```bash
# Get a 30-min CPU node (debug-cpu is fast; standard cpu has longer queue)
srun --account=PMIU0110 --partition=debug-cpu \
     --nodes=1 --ntasks=1 --cpus-per-task=4 \
     --time=00:30:00 --pty bash

# Once you land on cpuXXXX:
cd $HOME/SimForge
source .venv/bin/activate
module load python/3.12 openjdk

# Generate the bundled small scenario — ~30 s on Pitzer CPU
python generate.py --city chicago --trips 1000

# Run a single SUMO meso simulation — ~5 s
python run.py --scenario chicago_1k_car --engine sumo --mode meso --repeats 1

# Exit the compute node
exit
```

If this works end-to-end, the full 1K matrix (~1 minute wall-clock) is ready:

```bash
srun --account=PMIU0110 --partition=cpu \
     --nodes=1 --ntasks=1 --cpus-per-task=8 \
     --time=00:20:00 --pty bash
# ... inside the node ...
python -m execution.run_benchmark runspecs/stress_test.yaml
```

---

## 7. SLURM batch jobs

The generation tiers above 10K are submitted as batch jobs (they can take
minutes to hours). A typical `sbatch` script lives under `jobs/` (gitignored
— keep per-user scripts out of the repo).

### Per-tier template

Save as `~/jobs/gen_nyc_500k.sbatch`:

```bash
#!/bin/bash
#SBATCH --account=PMIU0110
#SBATCH --partition=cpu
#SBATCH --job-name=gen-nyc-500k
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00     # NYC-500K demand step alone takes ~3h 43m (single-threaded gravity loop); see budgets table below
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.err

set -euo pipefail

cd $HOME/SimForge
source .venv/bin/activate
module load python/3.12

echo "=== $(date) === job $SLURM_JOB_ID on $(hostname) ==="
python --version
python -c "import osmium, osmnx; print('osmium', osmium.__version__, '/ osmnx', osmnx.__version__)"

# The actual work — 500K NYC trips, 6 AM – 10 AM window
python scripts/05_stress_test.py

# Validate before declaring success
python -m pipeline.validation.validate_bundle scenarios/nyc_500k_car
```

Submit and capture the job ID:

```bash
sbatch ~/jobs/gen_nyc_500k.sbatch
# Submitted batch job 47060176
```

### Wall-clock budgets

The `stress_test` row is **measured** on JobID 47063986 (Pitzer `cpu`,
8 cores, 64 GB, NYC @ 20 km radius, `new-york-2026-04-22.osm.pbf`,
`scripts/05_stress_test.py`). The smaller tier rows are pre-measurement
estimates that assume a mid-size US city (~50k SCC nodes); demand-gen scales
as O(trips × SCC destination nodes), so any tier pointed at a larger graph
will run proportionally longer.

| Tier             | Trips   | PBF slice   | osmnx parse | Demand gen      | Total           | Partition   |
| ---------------- | ------- | ----------- | ----------- | --------------- | --------------- | ----------- |
| `quick_test`     | 1K      | 5 – 15 s    | < 5 s       | 1 – 2 s         | < 1 min         | `debug-cpu` |
| `small_commute`  | 10K     | 15 – 45 s   | 10 – 20 s   | 5 – 10 s        | 1 – 2 min       | `cpu`       |
| `medium_multi`   | 50K     | 45 – 90 s   | 30 – 60 s   | 30 – 60 s       | 3 – 5 min       | `cpu`       |
| `large_full_day` | 200K    | 60 – 120 s  | 60 – 120 s  | 2 – 4 min*      | 5 – 10 min*     | `cpu`       |
| `stress_test`    | 500K    | **211 s**   | **217 s**   | **3 h 43 min**  | **3 h 52 min**  | `cpu`       |

\* `large_full_day` demand is estimated for a mid-size city; a 200K NYC-class
run would land much closer to the `stress_test` row. The gravity sampler is a
single-threaded NumPy loop over all SCC destination nodes, so wall-time scales
near-linearly with both trip count and graph size — `--cpus-per-task` past 1
buys nothing for this step.

The PBF + osmnx numbers above assume the California PBF (~1.2 GB) — the
heaviest case. Smaller states finish faster. These are **generation**
numbers; the actual simulation runs (SUMO / MATSim / QarSUMO) are separate
jobs. Always set `--time` to ≥ 1.5× the relevant row; the example sbatch
above uses `--time=06:00:00` for the `stress_test` tier.

### Running the benchmark matrix

Once the bundles exist, run the 4-cell canonical matrix (or a subset):

```bash
# ~/jobs/run_benchmark.sbatch
#!/bin/bash
#SBATCH --account=PMIU0110
#SBATCH --partition=cpu
#SBATCH --job-name=simforge-bench
#SBATCH --nodes=1 --ntasks=1 --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=%x-%j.out

cd $HOME/SimForge
source .venv/bin/activate
module load python/3.12 openjdk

python -m execution.run_benchmark runspecs/stress_test.yaml
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --markdown
python -m evaluation.generate_plots    runs/stress_test/benchmark_results_stress_test.json
```

### QarSUMO on GPU

QarSUMO requires a one-time build on a GPU partition node. After that, point
the adapter at the built binary:

```bash
# Build (interactive, once per CUDA upgrade)
srun --account=PMIU0110 --partition=gpu --gres=gpu:v100:1 \
     --cpus-per-task=8 --time=01:00:00 --pty bash

module load cuda gcc
cd $HOME
git clone https://github.com/LLNL/QarSUMO.git qarsumo
cd qarsumo && mkdir build && cd build
cmake .. && make -j8

# Run (in an sbatch — GPU partitions bill by GPU-hour)
export QARSUMO_BINARY=$HOME/qarsumo/build/qarsumo
python run.py --scenario nyc_500k_car --engine qarsumo --mode meso
```

---

## 8. Monitoring jobs

### Live queue

```bash
squeue --user=$USER                       # my jobs only
squeue --user=$USER --start                # estimated start time for pending jobs
squeue --job 47060176                      # one specific job
squeue --user=$USER -o "%.18i %.9P %.16j %.2t %.10M %R"   # custom columns
```

States:

| Code | Meaning                                            |
| ---- | -------------------------------------------------- |
| `PD` | Pending (waiting for resources)                    |
| `R`  | Running                                            |
| `CF` | Configuring (node being prepared)                  |
| `CG` | Completing (cleanup phase)                         |
| `F`  | Failed (non-zero exit)                             |
| `TO` | Timed out (hit `--time` limit — increase and resubmit) |
| `CA` | Cancelled (by user or admin)                       |

### Historical queue (sacct)

`squeue` drops a job immediately after completion; `sacct` keeps history.

```bash
# Jobs from last 24 h
sacct --user=$USER --starttime=now-24hours -o JobID,JobName,State,ExitCode,Elapsed,MaxRSS

# One specific job
sacct -j 47060176 -o JobID,JobName,State,ExitCode,Elapsed,MaxRSS,NodeList

# Failure autopsy (exit code + wall-clock — correlate with the .err file)
sacct -j 47060176 --format=JobID,State,ExitCode,Elapsed,DerivedExitCode
```

### Watch logs

```bash
# Live stream — Ctrl-C to detach
tail -f ~/SimForge/gen-nyc-500k-47060176.out
tail -f ~/SimForge/gen-nyc-500k-47060176.err

# Grep for errors across all recent logs
grep -E "(Error|Traceback|FAILED)" ~/SimForge/*.err
```

### Cancel

```bash
scancel 47060176                    # one job
scancel --user=$USER                # all your jobs (be careful!)
```

---

## 9. Benchmark matrix on Pitzer

The thesis numbers come from running `runspecs/stress_test.yaml` on Pitzer
with all four engines present. After a successful benchmark job you should
have:

```
runs/stress_test/
├── benchmark_results_stress_test.json
├── chicago_1k_car/
│   ├── sumo/     {seed_42,seed_43,seed_44}/tripinfo.xml
│   ├── qarsumo/  {seed_42,seed_43,seed_44}/tripinfo.xml   # real V100 kernels
│   └── matsim/   {seed_42,seed_43}/output_trips.csv.gz
└── plots/
    └── fig_5_{1..9}.{png,pdf}
```

Copy the plots and `benchmark_results_*.json` back to your local machine for
inclusion in the thesis:

```bash
# From your local machine
rsync -avh pitzer:SimForge/runs/stress_test/ ./runs/stress_test_pitzer/
```

---

## 10. Troubleshooting

| Problem                                                | Diagnosis / fix                                                                                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `module: command not found`                            | Log out and back in — `module` is loaded by Pitzer's login shell. If still missing, `source /etc/profile.d/lmod.sh`.             |
| `ImportError: osmium` after a fresh pull               | Pitzer was on an older commit before `git pull`. Re-run `pip install -r requirements.txt` so `osmium>=4.0` is installed.         |
| `TypeError` from `truncate_graph_bbox` on `bbox` kwarg | osmnx 1.x is installed. `requirements.txt` now requires `>=2.0,<3` — run `pip install -U "osmnx>=2.0,<3"`.                       |
| `FileNotFoundError: osm_data/<state>.osm.pbf`          | PBF not transferred. See §5. Re-run `python tools/download_osm.py` to fetch + SHA-256-verify against the manifest.              |
| Job sits in `PD` for hours                             | `squeue --start -j <id>` shows estimated start. `cpu` partition is oversubscribed during semester peaks — try `debug-cpu` (≤1 h) or reduce `--time`.  |
| `ValueError: Found no graph nodes within the requested polygon` | Likely an osmnx version mismatch. `requirements.txt` requires `>=2.0,<3` — confirm with `python -c "import osmnx; print(osmnx.__version__)"` and `pip install -U "osmnx>=2.0,<3"` if older. |
| `MATSim ClassNotFoundException`                        | `module load openjdk` (must be in the sbatch, not just your login shell) and verify `lib/matsim-15.0/matsim-15.0.jar` exists.     |
| Job killed with `OUT_OF_MEMORY`                        | Increase `--mem` in the sbatch. 200K tier needs ≥ 48 GB; 500K needs ≥ 64 GB; multi-engine benchmark needs ≥ 96 GB.                |
| `Disk quota exceeded` on `$HOME`                       | `myquota` to confirm. Move `runs/` to `/fs/scratch/PMIU0110/$USER/runs/` and symlink: `ln -s /fs/scratch/.../runs $HOME/SimForge/runs`. |
| Scratch files disappeared                              | Scratch is purged after ~90 days of inactivity. Copy anything precious back to `$HOME` or `/fs/ess/PMIU0110/`.                    |
| `git push` fails with `Permission denied`              | Use HTTPS with a GitHub PAT — key-based auth is not set up by default. Or `gh auth login` once in a login-node shell.             |
| Queue wait is multi-hour and I need to test a fix      | Submit to `debug-cpu` (partition for ≤ 1 h jobs) or start an `srun --pty` interactive shell — these usually land in < 5 min.      |

### Getting help

- OSC support email: `oschelp@osc.edu` (usually responds within a few hours)
- OSC documentation: <https://www.osc.edu/supercomputing/knowledge-base>
- Cluster status & outages: <https://www.osc.edu/supercomputing/status>

---

## Appendix: quick-reference cheat sheet

```bash
# Daily workflow
ssh pitzer
cd $HOME/SimForge && git pull && source .venv/bin/activate
module load python/3.12 openjdk

# Submit / watch
sbatch ~/jobs/gen_nyc_500k.sbatch
squeue --user=$USER
tail -f ~/SimForge/gen-nyc-500k-*.out

# Postmortem
sacct --user=$USER --starttime=now-1day -o JobID,JobName,State,Elapsed,MaxRSS

# Transfer results home
rsync -avh pitzer:SimForge/runs/ ~/Projects/SimForge/runs-pitzer/
```
