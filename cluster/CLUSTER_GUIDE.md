# SimForge on HPC — Complete Guide

> Setup, execution, and analysis on **OSC Pitzer** (primary) and **RedHawk** (legacy).

---

## Cluster Comparison

| Feature            | OSC Pitzer (Primary)              | RedHawk (Legacy)           |
| ------------------ | --------------------------------- | -------------------------- |
| Account / Project  | `PMIU0110`                        | `akulap`                   |
| Python             | `python/3.12` (module)            | `anaconda-python3.10`      |
| SUMO               | `pip install eclipse-sumo`        | Not available              |
| Internet on nodes  | **Yes** (OSM download works)      | **No** (jobs hang)         |
| Max wall time      | 7 days                            | 20 days                    |
| CPUs/node          | 40-48                             | 24+                        |
| RAM/node           | 178-744 GB                        | 93-708 GB                  |
| GPUs               | V100 (2-4 per node, GRES works)   | CUDA available             |
| SSH                | `ssh pitzer`                      | `ssh redhawk`              |

---

# Part 1 — OSC Pitzer (Recommended)

---

---

## Table of Contents

### OSC Pitzer
1. [Connect to Pitzer](#p1-connect-to-pitzer)
2. [First-Time Setup (Pitzer)](#p2-first-time-setup-pitzer)
3. [Transfer Model Files (Pitzer)](#p3-transfer-model-files-pitzer)
4. [Generate Scenarios (Pitzer)](#p4-generate-scenarios-pitzer)
5. [Run Simulations (Pitzer)](#p5-run-simulations-pitzer)
6. [Evaluate Results (Pitzer)](#p6-evaluate-results-pitzer)
7. [Retrieve Results (Pitzer)](#p7-retrieve-results-pitzer)
8. [Pitzer Quick Reference](#p8-pitzer-quick-reference)

### RedHawk (Legacy)
9. [Connect to RedHawk](#9-connect-to-redhawk)
10. [First-Time Setup (RedHawk)](#10-first-time-setup-redhawk)
11. [Transfer Model Files (RedHawk)](#11-transfer-model-files-redhawk)
12. [Job Management](#12-job-management)
13. [Troubleshooting](#13-troubleshooting)

---

## P1. Connect to Pitzer

### From Terminal

```bash
ssh phanidharakula@pitzer.osc.edu
```

- Uses OSC credentials (not Miami password)
- No VPN required

### SSH Shortcut (already configured)

File: `~/.ssh/config`

```
Host pitzer
    HostName pitzer.osc.edu
    User phanidharakula
    ForwardAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Then:

```bash
ssh pitzer
```

---

## P2. First-Time Setup (Pitzer)

> Run these commands **on the cluster** after SSH-ing in.

### Clone the Repository

```bash
git config --global credential.helper store

git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git ~/SimForge
```

- **Username**: `PhanidharAkula`
- **Password**: your GitHub Personal Access Token (`ghp_...`)

### Run Setup Script

```bash
bash ~/SimForge/cluster/setup_pitzer.sh
```

This will:

1. Pull latest code
2. Load `python/3.12` module
3. Create Python venv
4. Install pip dependencies + `eclipse-sumo`
5. Check for modelgen data files

### Verify Setup

```bash
cd ~/SimForge
module load python/3.12
source .venv/bin/activate

python --version           # Should be 3.12.x
sumo --version             # Should show SUMO version
python -m pytest tests/ -v # Should pass all tests
python run.py --list       # Shows available scenarios
```

---

## P3. Transfer Model Files (Pitzer)

> Run these commands **on your LOCAL Mac**.

### Transfer Chicago Only (needed for 200K script)

```bash
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/chicago_model.txt" phanidharakula@pitzer.osc.edu:~/SimForge/modelgen/
```

### Transfer All Three Cities

```bash
# Chicago (~279MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/chicago_model.txt" phanidharakula@pitzer.osc.edu:~/SimForge/modelgen/

# LA (~310MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/la_model.txt" phanidharakula@pitzer.osc.edu:~/SimForge/modelgen/

# NYC (~608MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/nyc_model.txt" phanidharakula@pitzer.osc.edu:~/SimForge/modelgen/
```

### Verify on Cluster

```bash
ls -lh ~/SimForge/modelgen/
```

---

## P4. Generate Scenarios (Pitzer)

### Submit Slurm Jobs (Recommended)

```bash
cd ~/SimForge

# 200K Chicago — car+transit, 24-hour
sbatch cluster/job_pitzer_200k.sh

# 500K NYC — car, 6-10AM
sbatch cluster/job_pitzer_500k.sh
```

**Note**: Unlike RedHawk, Pitzer compute nodes have internet access, so OSM downloads work in batch jobs.

### Interactive Generation (Small Scenarios)

```bash
cd ~/SimForge
module load python/3.12
source .venv/bin/activate

python scripts/01_quick_test.py        # 1K Chicago
python scripts/02_small_commute.py     # 10K NYC
python scripts/03_medium_multimodal.py # 50K LA
```

### Verify Generated Scenarios

```bash
ls scenarios/
for d in scenarios/*/; do
    python -m pipeline.validation.validate_bundle "$d"
done
```

---

## P5. Run Simulations (Pitzer)

### Quick Test (Interactive)

```bash
cd ~/SimForge
module load python/3.12
source .venv/bin/activate

# SUMO is installed via pip in the venv
python run.py --scenario chicago_1k_car --engine sumo --mode meso --repeats 1
```

### Full Benchmark (Slurm Job — Recommended)

```bash
sbatch cluster/job_pitzer_benchmark.sh
```

Runs: **all scenarios × SUMO × all modes × 3 repeats**.

### Custom Runs

```bash
python run.py --scenario chicago_1k_car,chicago_200k_car_transit --engine sumo --mode meso --repeats 3
python run.py --engine sumo --mode meso --repeats 5
```

---

## P6. Evaluate Results (Pitzer)

### Submit Evaluation Job

```bash
sbatch cluster/job_pitzer_evaluate.sh
```

### Interactive Evaluation

```bash
cd ~/SimForge
module load python/3.12
source .venv/bin/activate

python -m evaluation.analyze_benchmark runs/benchmark_*/benchmark_results.json
python -m evaluation.generate_plots runs/benchmark_*/benchmark_results.json --output doc/figures
python -m evaluation.compare_modes scenarios/chicago_5k --seed 42
```

---

## P7. Retrieve Results (Pitzer)

> Run on your **LOCAL Mac**.

```bash
# Benchmark results
scp phanidharakula@pitzer.osc.edu:~/SimForge/runs/benchmark_*/benchmark_results.json ~/Desktop/

# Generated figures
scp -r phanidharakula@pitzer.osc.edu:~/SimForge/doc/figures/ ~/Desktop/simforge_figures/

# Generated scenario (e.g., 200K)
scp -r phanidharakula@pitzer.osc.edu:~/SimForge/scenarios/chicago_200k_car_transit/ "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/scenarios/"

# Job logs
scp phanidharakula@pitzer.osc.edu:~/SimForge/cluster/logs/*.out ~/Desktop/simforge_logs/
```

---

## P8. Pitzer Quick Reference

```bash
# ============ CONNECT ============
ssh pitzer

# ============ SETUP (once) ============
bash ~/SimForge/cluster/setup_pitzer.sh

# ============ ENVIRONMENT ============
cd ~/SimForge
module load python/3.12
source .venv/bin/activate

# ============ GENERATE ============
sbatch cluster/job_pitzer_200k.sh       # 200K Chicago
sbatch cluster/job_pitzer_500k.sh       # 500K NYC

# ============ SIMULATE ============
sbatch cluster/job_pitzer_benchmark.sh  # Full benchmark

# ============ EVALUATE ============
sbatch cluster/job_pitzer_evaluate.sh   # Analysis + plots

# ============ MONITOR ============
squeue -u $USER                         # Check jobs
tail -f cluster/logs/job_*_<ID>.out     # Watch output
sacct -u $USER                          # Job history
```

### Available Pitzer Jobs

| Script                           | Purpose                        | Resources  | Est. Time |
| -------------------------------- | ------------------------------ | ---------- | --------- |
| `cluster/job_pitzer_200k.sh`     | Generate 200K Chicago scenario | 8 CPU, 32G | 25-45 min |
| `cluster/job_pitzer_500k.sh`     | Generate 500K NYC scenario     | 8 CPU, 64G | 1-2 hrs   |
| `cluster/job_pitzer_benchmark.sh`| Run all simulations            | 8 CPU, 32G | 2-4 hrs   |
| `cluster/job_pitzer_evaluate.sh` | Analyze results + plots        | 4 CPU, 8G  | 5-15 min  |

### End-to-End Pipeline (Pitzer)

```
Step 1: Setup       →  bash cluster/setup_pitzer.sh
Step 2: Transfer    →  scp modelgen files from Mac
Step 3: Generate    →  sbatch cluster/job_pitzer_200k.sh     (wait)
Step 4: Simulate    →  sbatch cluster/job_pitzer_benchmark.sh (wait)
Step 5: Evaluate    →  sbatch cluster/job_pitzer_evaluate.sh  (wait)
Step 6: Download    →  scp results to local Mac
```

---
---

# Part 2 — RedHawk (Legacy)

> Miami University RedHawk cluster. Use Pitzer instead when possible.

---

## 9. Connect to RedHawk

### From Terminal

```bash
ssh akulap@redhawk.hpc.miamioh.edu
```

- Enter Miami password, then Duo push (option 1)
- If off-campus, connect GlobalProtect VPN to `vpn.miamioh.edu` first

### SSH Shortcut (already configured)

File: `~/.ssh/config`

```
Host redhawk
    HostName redhawk.hpc.miamioh.edu
    User akulap
    ForwardAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Then just:

```bash
ssh redhawk
```

### Open a Second Terminal (for file transfers)

Keep one terminal SSH'd into RedHawk, use a second local terminal for `scp`.

---

## 10. First-Time Setup (RedHawk)

> Run these commands **on the cluster** after SSH-ing in.

### 3.1 Clone the Repository

```bash
# Store GitHub credentials so you don't re-enter every time
git config --global credential.helper store

# Clone
git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git ~/SimForge
```

- **Username**: `PhanidharAkula`
- **Password**: your GitHub Personal Access Token (`ghp_...`), NOT your GitHub password

### 3.2 Run Setup Script

```bash
bash ~/SimForge/cluster/setup_redhawk.sh
```

This will:

1. Pull latest code
2. Load `anaconda-python3.10` module
3. Create Python venv with `--system-site-packages`
4. Install pip dependencies
5. Check for modelgen data files

### 3.3 Verify Setup

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

python --version          # Should be 3.10.9
python -m pytest tests/ -v  # Should pass all tests
python run.py --list       # Shows available scenarios
python help.py             # Shows help topics
```

---

## 11. Transfer Model Files (RedHawk)

> Run these commands **on your LOCAL Mac** (not on the cluster).

The modelgen data files (~1.2GB total) are gitignored. Transfer manually:

### Transfer Chicago Only (needed for 200K script)

```bash
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/chicago_model.txt" akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/
```

### Transfer All Three Cities

```bash
# Chicago (~279MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/chicago_model.txt" akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/

# LA (~310MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/la_model.txt" akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/

# NYC (~608MB)
scp "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/modelgen/nyc_model.txt" akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/
```

### Verify on Cluster

```bash
ls -lh ~/SimForge/modelgen/
# chicago_model.txt  281M
# la_model.txt       310M
# nyc_model.txt      608M
```

**Important**: Use `/home/akulap/SimForge/modelgen/` (full path), NOT `~/SimForge/modelgen/` (tilde doesn't expand in scp destination).

---

## 12. Generate Scenarios (RedHawk)

### Option A: Submit Slurm Jobs (Recommended)

Generate large scenarios that can't run on a laptop:

```bash
cd ~/SimForge

# 200K Chicago — car+transit, 24-hour (needs chicago_model.txt)
sbatch cluster/job_200k.sh

# 500K NYC — car, 6-10AM (needs nyc_model.txt)
sbatch cluster/job_500k.sh
```

### Option B: Interactive Generation (Small Scenarios)

For small scenarios, can run directly on login node:

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# Quick 1K test
python scripts/01_quick_test.py

# Or use generate.py directly
python generate.py --city chicago --trips 5000 --modes car
```

### Option C: Generate All Scenarios Interactively

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# Small (runs in seconds)
python scripts/01_quick_test.py        # 1K Chicago car
python scripts/02_small_commute.py     # 10K NYC car
python scripts/03_medium_multimodal.py # 50K LA multi-mode

# Large (submit as jobs)
sbatch cluster/job_200k.sh             # 200K Chicago car+transit
sbatch cluster/job_500k.sh             # 500K NYC car
```

### Verify Generated Scenarios

```bash
# List all scenarios
ls scenarios/

# Validate a specific scenario
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
python -m pipeline.validation.validate_bundle scenarios/chicago_200k_car_transit

# Validate all
for d in scenarios/*/; do
    python -m pipeline.validation.validate_bundle "$d"
done
```

---

## 13. Run Simulations (RedHawk)

### 6.1 Check Available Engines

```bash
module avail sumo 2>&1 | grep sumo
module avail java 2>&1 | grep java
```

Load engines:

```bash
module load sumo         # If available
module load java/17      # If available (for MATSim)
```

### 6.2 Quick Test (Interactive)

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# Single scenario, single engine
python run.py --scenario chicago_1k_car --engine sumo --mode meso --repeats 1

# List what's available
python run.py --list

# Validate only (no simulation)
python run.py --validate-only
```

### 6.3 Full Benchmark (Slurm Job — Recommended)

```bash
# Submit the benchmark job
sbatch cluster/job_benchmark.sh
```

This runs: **all scenarios × all installed engines × all modes × 3 repeats**.

### 6.4 Custom Benchmark Runs

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# Specific scenarios
python run.py --scenario chicago_1k_car,chicago_200k_car_transit --engine sumo --mode meso --repeats 3

# All scenarios with SUMO mesoscopic
python run.py --engine sumo --mode meso --repeats 5

# Using runspec file
python -m execution.run_benchmark runspecs/benchmark_small.yaml
python -m execution.run_benchmark runspecs/benchmark_large.yaml
python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run
```

### 6.5 Individual Adapter CLIs

```bash
# Convert to SUMO format and run
python -m adapters.sumo.cli scenarios/chicago_1k_car runs/chicago_sumo

# Convert to MATSim format
python -m adapters.matsim.cli scenarios/chicago_1k_car runs/chicago_matsim
```

---

## 14. Evaluate Results (RedHawk)

### 7.1 Submit Evaluation Job

```bash
sbatch cluster/job_evaluate.sh
```

This:

1. Analyzes benchmark results (stats, tables)
2. Generates plots in `doc/figures/`
3. Compares simulation modes

### 7.2 Interactive Evaluation

```bash
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# Analyze benchmark results
python -m evaluation.analyze_benchmark runs/benchmark_*/benchmark_results.json

# Generate plots
python -m evaluation.generate_plots runs/benchmark_*/benchmark_results.json --output doc/figures

# Compare micro vs meso modes
python -m evaluation.compare_modes scenarios/chicago_1k_car --seed 42
```

### 7.3 Individual Metrics

```bash
# These are library modules, used by the benchmark harness:
# evaluation/metrics/fidelity.py       — micro vs meso accuracy
# evaluation/metrics/reproducibility.py — cross-run consistency
# evaluation/metrics/scalability.py     — performance scaling
# evaluation/metrics/travel_time.py     — trip-level analysis
```

---

## 15. Retrieve Results (RedHawk)

> Run on your **LOCAL Mac**.

### Download Everything

```bash
# Results JSON
scp akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/runs/benchmark_*/benchmark_results.json ~/Desktop/

# Generated figures
scp -r akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/doc/figures/ ~/Desktop/simforge_figures/

# Generated scenario (e.g., the 200K)
scp -r akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/scenarios/chicago_200k_car_transit/ "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge/scenarios/"
```

### Download Job Logs

```bash
scp akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/cluster/logs/*.out ~/Desktop/simforge_logs/
```

---

## 16. Job Management

### Monitor Jobs

```bash
# Check your jobs
squeue -u $USER

# Detailed job info
scontrol show job <JOBID>

# Watch output in real-time
tail -f ~/SimForge/cluster/logs/job_200k_<JOBID>.out

# Check job history
sacct -u $USER --format=JobID,JobName,State,Elapsed,MaxRSS -j <JOBID>
```

### Cancel Jobs

```bash
# Cancel a specific job
scancel <JOBID>

# Cancel all your jobs
scancel -u $USER
```

### Job Status Codes

| Code | Meaning       |
| ---- | ------------- |
| PD   | Pending       |
| R    | Running       |
| CG   | Completing    |
| CD   | Completed     |
| F    | Failed        |
| TO   | Timeout       |
| OOM  | Out of Memory |

### Resource Limits

The default partition (`batch`) limits:

- Max wall time: check with `sinfo -p batch`
- 200K script: `--mem=32G --time=02:00:00` (safe)
- 500K script: `--mem=64G --time=04:00:00` (safe)
- Benchmark: `--mem=16G --time=04:00:00` (safe)

---

## 17. Troubleshooting

### "Authentication failed" on git pull

GitHub requires a Personal Access Token (PAT), not your password.

1. Go to https://github.com/settings/tokens
2. Generate a new classic token with `repo` scope
3. Use the token as the password

Cache it: `git config --global credential.helper store`

### "No module named 'dataclasses'"

Wrong Python version. Make sure to load the module first:

```bash
module load anaconda-python3.10
source ~/SimForge/.venv/bin/activate
python --version  # Must be 3.10+
```

### "SSL module is not available"

Using `python-3.10.0` instead of `anaconda-python3.10`. Fix:

```bash
module purge
module load anaconda-python3.10
```

### scp "~ not found" or "Failure"

Use full path in destination, not `~`:

```bash
# WRONG:
scp file.txt akulap@redhawk:~/SimForge/modelgen/

# CORRECT:
scp file.txt akulap@redhawk.hpc.miamioh.edu:/home/akulap/SimForge/modelgen/
```

### Job fails with ExitCode 1

Check the logs:

```bash
cat ~/SimForge/cluster/logs/job_<NAME>_<JOBID>.out
cat ~/SimForge/cluster/logs/job_<NAME>_<JOBID>.err
```

### Job killed (OOM)

Increase memory in the job script:

```bash
#SBATCH --mem=64G   # or higher
```

### Updating Code on Cluster

```bash
# On LOCAL Mac: push changes
cd "/Users/phanidharakula/Library/Mobile Documents/com~apple~CloudDocs/Projects/SimForge"
git add -A && git commit -m "description" && git push origin modelgen

# On CLUSTER: pull changes
cd ~/SimForge
git pull origin modelgen
```

---

## 18. RedHawk Quick Reference

### Cheat Sheet

```bash
# ============ CONNECT ============
ssh akulap@redhawk.hpc.miamioh.edu

# ============ SETUP (once) ============
cd ~/SimForge
module load anaconda-python3.10
source .venv/bin/activate

# ============ GENERATE ============
sbatch cluster/job_200k.sh          # 200K Chicago
sbatch cluster/job_500k.sh          # 500K NYC

# ============ SIMULATE ============
sbatch cluster/job_benchmark.sh     # Full benchmark

# ============ EVALUATE ============
sbatch cluster/job_evaluate.sh      # Analysis + plots

# ============ MONITOR ============
squeue -u $USER                     # Check jobs
tail -f cluster/logs/job_*_<ID>.out # Watch output
sacct -u $USER                      # Job history

# ============ RESULTS ============
ls runs/benchmark_*/                # Benchmark results
ls doc/figures/                     # Generated plots
```

### Available Slurm Jobs

| Script                     | Purpose                        | Resources  | Est. Time |
| -------------------------- | ------------------------------ | ---------- | --------- |
| `cluster/job_200k.sh`      | Generate 200K Chicago scenario | 8 CPU, 32G | 25-45 min |
| `cluster/job_500k.sh`      | Generate 500K NYC scenario     | 8 CPU, 64G | 1-2 hrs   |
| `cluster/job_benchmark.sh` | Run all simulations            | 8 CPU, 16G | 1-3 hrs   |
| `cluster/job_evaluate.sh`  | Analyze results + plots        | 4 CPU, 8G  | 5-15 min  |

### End-to-End Pipeline

```
Step 1: Generate    →  sbatch cluster/job_200k.sh     (wait for completion)
Step 2: Simulate    →  sbatch cluster/job_benchmark.sh (wait for completion)
Step 3: Evaluate    →  sbatch cluster/job_evaluate.sh  (wait for completion)
Step 4: Download    →  scp results to local Mac
```

### File Locations

| What              | Local Mac                                  | RedHawk Cluster  |
| ----------------- | ------------------------------------------ | ---------------- |
| Project root      | `~/Library/Mobile Documents/.../SimForge/` | `~/SimForge/`    |
| Modelgen data     | `modelgen/*.txt`                           | `modelgen/*.txt` |
| Scenarios         | `scenarios/*/`                             | `scenarios/*/`   |
| Simulation output | `runs/`                                    | `runs/`          |
| Figures           | `doc/figures/`                             | `doc/figures/`   |
| Job logs          | —                                          | `cluster/logs/`  |
| Cluster scripts   | `cluster/*.sh`                             | `cluster/*.sh`   |
