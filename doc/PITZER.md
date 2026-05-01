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
| MATSim 15.0                         | Works  | `module load openjdk/21.0.3_9` + `lib/matsim-15.0/matsim-15.0.jar` |
| DTALite (CPU)                       | Works  | `uv pip install path4gmns` (bundled in `requirements.lock`)         |
| Evaluation + plot rendering         | Works  | Pure Python (matplotlib in venv)                                   |
| Bundle validation + SHA-256 hashing | Works  | Pure Python                                                        |

After the LPSim removal in Version_5, **the entire SimForge matrix is CPU-only**
and reproduces from a developer Mac. Pitzer is now reserved purely for the
larger trip tiers (50k–500k) where SUMO microscopic + MATSim wall time
exceeds laptop patience — none of the three engines requires GPU or
specialised hardware. See [`doc/engines/LPSIM_RETROSPECTIVE.md`](engines/LPSIM_RETROSPECTIVE.md)
for the GPU-engine abandonment narrative.

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

After SSH'ing into Pitzer, run this sequence once. Expect ~10 minutes
including the `uv` install, dep install, and MATSim JAR download.

The canonical install uses [`requirements.lock`](../requirements.lock) so Pitzer
ends up on **byte-identical Python + dep versions** as a developer's Mac. SUMO
is included in the lockfile — no `module load sumo` (Pitzer doesn't have one)
and no separate `pip install eclipse-sumo` step.

```bash
# 4.1 — clone into $HOME (500 GB quota, no advisor permission needed)
cd $HOME
git clone -b Version_3 https://github.com/PhanidharAkula/SimForge.git
cd SimForge

# 4.2 — install uv (manages Python + venv; user-space, no admin)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
echo 'source $HOME/.local/bin/env' >> ~/.bashrc      # persist across logins

# 4.3 — install Python 3.13 via uv (Pitzer modules only offer 3.10 / 3.12)
uv python install 3.13                               # downloads 3.13.13

# 4.4 — load OpenJDK module (needed only for MATSim runs)
module load openjdk/21.0.3_9                         # explicit version — Pitzer's lmod requires one
echo 'module load openjdk/21.0.3_9' >> ~/.bashrc     # persist across logins

# 4.5 — create venv and install everything from the lockfile
uv venv --python 3.13 .venv
source .venv/bin/activate
uv pip install --upgrade pip
uv pip install -r requirements.lock                  # 42 packages including SUMO

# 4.6 — download MATSim 15.0 JAR (~65 MB; gitignored)
mkdir -p lib
curl -L -o matsim-15.0-release.zip \
    https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip
unzip matsim-15.0-release.zip -d lib/
rm matsim-15.0-release.zip
ls lib/matsim-15.0/matsim-15.0.jar       # should exist

# 4.7 — verify the env matches your dev machine + run the test suite
python tools/env_report.py                # diff against your laptop's output
python -m pytest
```

### Module cheatsheet

Authoritative list: `module spider <name>` on a logged-in shell (module
versions rebump after cluster upgrades). As of 2026-04:

| Software   | Module command            | Purpose                                                             |
| ---------- | ------------------------- | ------------------------------------------------------------------- |
| Python     | **not used**              | Use `uv` (installs Python 3.13.13 to match the locked dev env)      |
| GCC        | `module load gcc`         | Usually unneeded (modern default)                                   |
| OpenJDK    | `module load openjdk/21.0.3_9` | MATSim runtime — Pitzer's lmod requires an explicit version (`module spider openjdk` lists current options) |
| Git        | pre-installed             | —                                                                   |
| SUMO       | **not** a module          | Bundled in `requirements.lock` (`eclipse-sumo` wheel)               |

Pitzer's `module load python/3.12` provides Python 3.12.x, but the locked dev
environment is on **Python 3.13** — using `uv` to manage Python aligns Pitzer
to the canonical version regardless of what the cluster modules offer.

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
module load python/3.12 openjdk/21.0.3_9

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
python -m execution.run_benchmark runspecs/benchmark_small.yaml
```

---

## 7. SLURM batch jobs

The generation tiers above 10K are submitted as batch jobs (they can take
minutes to hours). Canonical sbatch templates are tracked under
`cluster/jobs/`; user-specific copies you tweak (different `--account`,
different `--mail-user`) belong in `jobs/` at the repo root, which is
gitignored.

### Per-tier template

The recorded thesis run used [`cluster/jobs/gen_nyc_500k.sbatch`](../cluster/jobs/gen_nyc_500k.sbatch).
Submit from the repo root:

```bash
sbatch cluster/jobs/gen_nyc_500k.sbatch
# Submitted batch job 47063986
# Outputs land in ./logs/simforge_nyc_500k_<jobid>.{out,err}
```

For a different OSC project, copy and edit `--account` (and `--mail-user`)
first — `jobs/` is gitignored so your edits stay local:

```bash
cp cluster/jobs/gen_nyc_500k.sbatch jobs/
$EDITOR jobs/gen_nyc_500k.sbatch          # set --account=<your-project>
sbatch jobs/gen_nyc_500k.sbatch
```

The committed file ships with `--time=08:00:00` to leave headroom over the
measured 3 h 52 m runtime (see budgets below).

### Wall-clock budgets

The `stress_test` row is **measured** on JobID 47063986 (Pitzer `cpu`,
8 cores, 64 GB, NYC @ 20 km radius, `new-york-2026-04-22.osm.pbf`,
`scripts/05_nyc_500k_car.py`); the annotated stderr with per-step
breakdowns is at [`cluster/example_runs/nyc_500k_47063986.md`](../cluster/example_runs/nyc_500k_47063986.md).
The smaller tier rows are pre-measurement estimates that assume a mid-size
US city (~50k SCC nodes); demand-gen scales as O(trips × SCC destination
nodes), so any tier pointed at a larger graph will run proportionally longer.

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
numbers; the actual simulation runs (SUMO / MATSim) are separate
jobs. Always set `--time` to ≥ 1.5× the relevant row; the committed
`cluster/jobs/gen_nyc_500k.sbatch` uses `--time=08:00:00` for the
`stress_test` tier (≈ 2× the measured 3 h 52 m runtime).

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
module load python/3.12 openjdk/21.0.3_9

python -m execution.run_benchmark runspecs/benchmark_small.yaml
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --markdown
python -m evaluation.generate_plots    runs/benchmark_small/benchmark_results_benchmark_small.json
```

### DTALite on Pitzer (CPU)

DTALite (the third primary engine in Version_5) is bundled inside the
[`path4gmns`](https://github.com/jdlph/Path4GMNS) Python package and
ships in `requirements.lock`. After `uv pip install -r requirements.lock`
in the Pitzer venv, DTALite is ready — no separate build step. The
bundled binary on Linux x86_64 (`DTALiteMM.so` inside path4gmns/bin/)
links against standard `libgomp` only and works against Pitzer's
`module load openjdk/21.0.3_9` toolchain (no CUDA, no Apptainer needed).

> **Historical note.** Versions 1–4 reserved this slot for LPSim
> (GPU mesoscopic). After exhaustive Pitzer debugging, LPSim was
> abandoned in Version_5 — the bundled `LivingCity` binary crashed on
> networks larger than a few-K nodes, and an in-container source rebuild
> against the V100's sm_70 arch SIGSEGV'd at first kernel launch. The
> full integration narrative (12+ commits across two debugging sessions,
> with Boost 1.59 sed-patches, CUDA toolchain reconciliation, and CUDA
> arch overrides) is in [`doc/engines/LPSIM_RETROSPECTIVE.md`](engines/LPSIM_RETROSPECTIVE.md).
> The `cluster/jobs/build_lpsim.sbatch`, `smoke_lpsim.sbatch`, and
> `diag_lpsim.sbatch` jobs were removed in Version_5; the GPU partition
> (`--partition=gpu --gres=gpu:v100:1`) is no longer required for any
> SimForge engine and the benchmark sbatches now request `--partition=cpu`.

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

# Failure autopsy (exit code + wall-clock — correlate with the .out file for
# progress, .err for tracebacks)
sacct -j 47060176 --format=JobID,State,ExitCode,Elapsed,DerivedExitCode
```

### Watch logs

The four entry-point modules (`generate.py`, `execution/run_benchmark.py`,
`pipeline/network/warmup.py`, `evaluation/compare_modes.py`) configure the
root logger with `stream=sys.stdout, force=True`, so all
`INFO`/`WARNING`/`ERROR` lines land in the SLURM **`.out`** file. The `.err`
file only catches uncaught Python tracebacks and external-tool stderr (SUMO,
MATSim, etc.).

```bash
# Primary live stream — generation progress, per-step timings
tail -f ~/SimForge/logs/simforge_nyc_500k_47063986.out

# Real errors only — usually empty on a healthy run
tail -f ~/SimForge/logs/simforge_nyc_500k_47063986.err

# Grep across all recent logs (check both — uncaught tracebacks still land in .err)
grep -E "(Error|Traceback|FAILED)" ~/SimForge/logs/*.{out,err}
```

### Cancel

```bash
scancel 47060176                    # one job
scancel --user=$USER                # all your jobs (be careful!)
```

---

## 9. Benchmark matrix on Pitzer

The thesis numbers come from running `runspecs/benchmark_small.yaml` on Pitzer
with all three engines. After a successful benchmark job you should have:

```
runs/benchmark_small/
├── benchmark_results_benchmark_small.json
├── chicago_1k_car/
│   ├── sumo/     {seed_42,seed_43,seed_44,seed_45,seed_46}/tripinfo.xml
│   ├── matsim/   {seed_42..seed_46}/output_trips.csv.gz
│   └── dtalite/  {seed_42..seed_46}/agent.csv + link_performance.csv  (UE assignment)
└── plots/
    └── fig_5_{1..10}.{png,pdf}
```

Copy the plots and `benchmark_results_*.json` back to your local machine for
inclusion in the thesis:

```bash
# From your local machine
rsync -avh pitzer:SimForge/runs/benchmark_small/ ./runs/stress_test_pitzer/
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
| `MATSim ClassNotFoundException`                        | `module load openjdk/21.0.3_9` (must be in the sbatch, not just your login shell — and Pitzer's lmod requires an explicit version) and verify `lib/matsim-15.0/matsim-15.0.jar` exists. |
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
module load python/3.12 openjdk/21.0.3_9

# Submit / watch
sbatch ~/jobs/gen_nyc_500k.sbatch
squeue --user=$USER
tail -f ~/SimForge/logs/simforge_nyc_500k_*.out

# Postmortem
sacct --user=$USER --starttime=now-1day -o JobID,JobName,State,Elapsed,MaxRSS

# Transfer results home
rsync -avh pitzer:SimForge/runs/ ~/Projects/SimForge/runs-pitzer/
```
