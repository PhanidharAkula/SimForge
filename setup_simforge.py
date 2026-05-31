#!/usr/bin/env python3
"""
SimForge Setup Script

One-command bootstrap for new users. Checks prerequisites, creates a
virtual environment, installs Python dependencies, downloads external
tools (MATSim JAR), and validates the installation.

Usage:
    python setup_simforge.py
"""

import sys
import shutil
import subprocess
import platform
import urllib.request
import zipfile
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_DEV = PROJECT_ROOT / "requirements-dev.txt"
MATSIM_DIR = PROJECT_ROOT / "lib" / "matsim-15.0"
MATSIM_JAR = MATSIM_DIR / "matsim-15.0.jar"
MATSIM_ZIP_URL = "https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip"
MIN_PYTHON = (3, 10)
MIN_JAVA = 17

# ── Helpers ──────────────────────────────────────────────────────────

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _print_step(n: int, total: int, msg: str):
    print(f"\n{CYAN}{BOLD}[{n}/{total}]{RESET} {msg}")


def _ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _fail(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


# ── Step functions ───────────────────────────────────────────────────

def check_python() -> bool:
    """Verify Python version meets minimum requirement."""
    v = sys.version_info
    if (v.major, v.minor) >= MIN_PYTHON:
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    _fail(f"Python {v.major}.{v.minor} found, need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
    return False


def check_java() -> bool:
    """Check for Java (needed by MATSim)."""
    java = shutil.which("java")
    if not java:
        _warn("Java not found, MATSim will not work")
        _warn("Install with: brew install openjdk@17  (macOS)")
        _warn("              apt install openjdk-17-jre  (Linux)")
        return False
    result = _run([java, "-version"])
    version_line = (result.stderr or result.stdout).split("\n")[0]
    _ok(f"Java found: {version_line.strip()}")
    return True


def check_sumo() -> bool:
    """Check for SUMO traffic simulator."""
    sumo = shutil.which("sumo")
    if not sumo:
        _warn("SUMO not found, SUMO engine will not work")
        _warn("Install with: uv pip install -r requirements.lock  (canonical, bundles eclipse-sumo)")
        _warn("       or:    pip install eclipse-sumo             (ad-hoc, same wheel)")
        return False
    result = _run([sumo, "--version"])
    first_line = result.stdout.strip().split("\n")[0]
    _ok(f"SUMO found: {first_line}")
    return True


def check_libomp_macos() -> bool:
    """On macOS the bundled DTALite binary inside path4gmns dynamically
    links against libomp (OpenMP runtime). It is NOT shipped by default
    and must be installed separately via Homebrew. We check for the
    standard Homebrew install path; if missing, the dtalite engine will
    fail at run-time with `dlopen: libomp.dylib not found`."""
    if platform.system() != "Darwin":
        return True  # not relevant outside macOS
    libomp_path = Path("/opt/homebrew/opt/libomp/lib/libomp.dylib")
    libomp_intel = Path("/usr/local/opt/libomp/lib/libomp.dylib")  # Intel Macs
    if libomp_path.exists() or libomp_intel.exists():
        _ok("libomp (OpenMP runtime for DTALite) found")
        return True
    _warn("libomp NOT found, DTALite engine will fail at run-time")
    _warn("Install with: brew install libomp")
    return False


def create_venv() -> Path:
    """Create virtual environment if it doesn't exist."""
    if VENV_DIR.exists():
        _ok(f"Virtual environment already exists: {VENV_DIR.name}/")
        return VENV_DIR

    print(f"  Creating virtual environment in {VENV_DIR.name}/ ...")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    _ok("Virtual environment created")
    return VENV_DIR


def get_venv_python() -> str:
    """Get path to python inside the venv."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def install_dependencies():
    """Install Python packages from requirements.txt + requirements-dev.txt."""
    pip_python = get_venv_python()
    subprocess.run(
        [pip_python, "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True, text=True, check=False,
    )
    print(f"  Installing from {REQUIREMENTS.name} ...")
    result = subprocess.run(
        [pip_python, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        _fail("pip install failed:")
        print(result.stderr[-500:] if result.stderr else result.stdout[-500:])
        return False
    _ok("Runtime dependencies installed")

    # Dev deps (coverage, mutation testing, parallel pytest) are required for
    # the documented `pytest -n auto` and `mutmut run` flows to work.
    if REQUIREMENTS_DEV.exists():
        print(f"  Installing from {REQUIREMENTS_DEV.name} ...")
        dev_result = subprocess.run(
            [pip_python, "-m", "pip", "install", "-r", str(REQUIREMENTS_DEV)],
            capture_output=True, text=True, check=False,
        )
        if dev_result.returncode != 0:
            _warn(f"{REQUIREMENTS_DEV.name} install failed, "
                  "coverage / mutation tools will be unavailable.")
            print(dev_result.stderr[-500:] if dev_result.stderr else dev_result.stdout[-500:])
        else:
            _ok("Dev dependencies installed (pytest-cov, pytest-xdist, mutmut)")
    return True


def download_matsim() -> bool:
    """Download MATSim 15.0 JAR if not already present."""
    if MATSIM_JAR.exists():
        _ok(f"MATSim JAR already present: {MATSIM_JAR.relative_to(PROJECT_ROOT)}")
        return True

    print("  Downloading MATSim 15.0 (~65 MB) ...")
    zip_path = PROJECT_ROOT / "lib" / "matsim-15.0.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlretrieve(MATSIM_ZIP_URL, str(zip_path))
    except (OSError, urllib.error.URLError) as e:
        _warn(f"Download failed: {e}")
        _warn("You can manually download from:")
        _warn(f"  {MATSIM_ZIP_URL}")
        _warn(f"  Extract to: {MATSIM_DIR}")
        return False

    print("  Extracting ...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(str(zip_path.parent))

    zip_path.unlink()

    if MATSIM_JAR.exists():
        _ok(f"MATSim 15.0 installed to {MATSIM_DIR.relative_to(PROJECT_ROOT)}/")
        return True

    _warn("Extraction succeeded but JAR not found at expected path")
    return False


def verify_installation() -> dict:
    """Run quick checks to verify everything works."""
    pip_python = get_venv_python()

    checks = {}

    # Core import check
    result = _run([pip_python, "-c", "import lxml, yaml, osmnx, networkx, matplotlib; print('ok')"])
    if result.returncode == 0 and "ok" in result.stdout:
        _ok("Core imports: lxml, yaml, osmnx, networkx, matplotlib")
        checks["imports"] = True
    else:
        _fail(f"Import check failed: {result.stderr.strip()}")
        checks["imports"] = False

    # DTALite (path4gmns) import check, bundled binary inside the wheel,
    # so successful import means the engine should run (modulo the libomp
    # runtime dependency on macOS, checked separately above).
    result = _run([pip_python, "-c",
                   "from adapters.dtalite import is_dtalite_available; "
                   "print('available' if is_dtalite_available() else 'missing')"])
    if result.returncode == 0 and "available" in result.stdout:
        _ok("DTALite (path4gmns) ready")
        checks["dtalite"] = True
    else:
        _warn("DTALite not available, `uv pip install path4gmns` (Mac: also brew install libomp)")
        checks["dtalite"] = False

    # Engine check
    result = _run([pip_python, str(PROJECT_ROOT / "run.py"), "--list"])
    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            line = line.strip()
            if "✅" in line or "❌" in line:
                print(f"    {line}")
        checks["engines"] = True
    else:
        _warn("Could not verify engines")
        checks["engines"] = False

    # Scenario check
    scenarios = list((PROJECT_ROOT / "scenarios").iterdir()) if (PROJECT_ROOT / "scenarios").exists() else []
    scenario_dirs = [s for s in scenarios if s.is_dir()]
    if scenario_dirs:
        _ok(f"{len(scenario_dirs)} scenario(s) found: {', '.join(s.name for s in scenario_dirs[:5])}")
    else:
        _warn("No scenarios found, generate one to get started")
    checks["scenarios"] = len(scenario_dirs)

    return checks


def print_next_steps(has_java: bool, has_sumo: bool, has_libomp: bool = True):
    """Print getting-started instructions."""
    activate = "source .venv/bin/activate" if platform.system() != "Windows" else r".venv\Scripts\activate"

    print(f"""
{BOLD}{'=' * 60}
  SimForge setup complete!
{'=' * 60}{RESET}

{CYAN}Activate the environment:{RESET}
  {activate}

{CYAN}Get help:{RESET}
  python help.py                 # Full help overview
  python help.py tests           # Test suite reference
  python help.py cities          # Census data limits

{CYAN}Generate a scenario:{RESET}
  python generate.py --city chicago --trips 5000

{CYAN}Validate:{RESET}
  python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car

{CYAN}Run simulation (all 3 engines):{RESET}
  python run.py --scenario chicago_1k_car --engine sumo,matsim,dtalite --mode meso --repeats 3

{CYAN}Run the canonical benchmark (Phase 12+, per-scenario JSONs land at runs/<runspec>/<scenario>/):{RESET}
  python -m execution.run_benchmark runspecs/benchmark_small.yaml

{CYAN}Analyze results (canonical 3-step post-benchmark pipeline):{RESET}
  python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json
  python -m evaluation.audit_fairness    runs/benchmark_small
  python -m evaluation.generate_plots    runs/benchmark_small/benchmark_results_benchmark_small.json

{CYAN}Run tests:{RESET}
  python -m pytest tests/ -v --tb=short
""")

    missing = []
    if not has_java:
        missing.append("  • Java 17+: brew install openjdk@17  (needed for MATSim)")
    if not has_sumo:
        missing.append("  • SUMO:     uv pip install -r requirements.lock  (bundles eclipse-sumo)")
    if not has_libomp:
        missing.append("  • libomp:   brew install libomp  (needed for DTALite on macOS)")
    if missing:
        print(f"{YELLOW}Missing external tools:{RESET}")
        for m in missing:
            print(m)
        print()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    total_steps = 6
    print(f"\n{BOLD}SimForge Setup{RESET}")
    print(f"Project root: {PROJECT_ROOT}\n")

    # 1. Python version
    _print_step(1, total_steps, "Checking Python version")
    if not check_python():
        print(f"\n{RED}Setup aborted: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required.{RESET}")
        return 1

    # 2. External tools
    _print_step(2, total_steps, "Checking external tools")
    has_java = check_java()
    has_sumo = check_sumo()
    has_libomp = check_libomp_macos()

    # 3. Virtual environment
    _print_step(3, total_steps, "Setting up virtual environment")
    create_venv()

    # 4. Python dependencies
    _print_step(4, total_steps, "Installing Python dependencies")
    if not install_dependencies():
        print(f"\n{RED}Setup failed: could not install dependencies.{RESET}")
        return 1

    # 5. MATSim
    _print_step(5, total_steps, "Setting up MATSim")
    if has_java:
        download_matsim()
    else:
        _warn("Skipping MATSim download (Java not found)")

    # 6. Verify
    _print_step(6, total_steps, "Verifying installation")
    verify_installation()

    # Done
    print_next_steps(has_java, has_sumo, has_libomp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
