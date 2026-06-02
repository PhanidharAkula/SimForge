"""
The runspec schema for benchmark execution.

A runspec says which scenarios to run, on which engines, and how many
repeats to do for the reproducibility analysis. It's loaded from YAML.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SimulationMode(str, Enum):
    """Simulation fidelity mode."""
    MICROSCOPIC = "microscopic"  # Full car-following, lane-changing (accurate, slow)
    MESOSCOPIC = "mesoscopic"    # Queue-based, edge-travel-time (fast, ~100x speedup)
    
    @classmethod
    def from_string(cls, s: str) -> "SimulationMode":
        """Parse mode from string (case-insensitive)."""
        s_lower = s.lower().strip()
        if s_lower in ("micro", "microscopic"):
            return cls.MICROSCOPIC
        elif s_lower in ("meso", "mesoscopic"):
            return cls.MESOSCOPIC
        else:
            raise ValueError(f"Unknown simulation mode: {s}. Use 'microscopic' or 'mesoscopic'")


@dataclass
class RunConfig:
    """Configuration for a single benchmark run."""
    scenario_id: str
    scenario_path: str
    engine: str  # sumo, matsim, dtalite
    environment: str = "local_cpu"  # local_cpu, local_gpu, hpc
    repeats: int = 1
    seed: int = 42
    seed_increment: bool = True  # If True, seed += 1 for each repeat
    timeout_s: int = 3600  # Max runtime per run
    output_dir: Optional[str] = None
    engine_options: dict = field(default_factory=dict)
    # Simulation mode (applies to SUMO; other engines may interpret differently)
    mode: SimulationMode = SimulationMode.MICROSCOPIC
    # Legacy field - use 'mode' instead
    mesoscopic: bool = False  # Deprecated: use mode=mesoscopic
    
    def __post_init__(self):
        if self.repeats < 1:
            raise ValueError(f"repeats must be >= 1, got {self.repeats}")
        if self.timeout_s < 1:
            raise ValueError(f"timeout_s must be >= 1, got {self.timeout_s}")
        # Sync mode and mesoscopic fields (mode takes precedence)
        if self.mode == SimulationMode.MESOSCOPIC:
            self.mesoscopic = True
        elif self.mesoscopic:  # Legacy: mesoscopic=True but mode not set
            self.mode = SimulationMode.MESOSCOPIC
    
    @property
    def is_mesoscopic(self) -> bool:
        """Check if using mesoscopic mode."""
        return self.mode == SimulationMode.MESOSCOPIC
    
    def get_seeds(self) -> list[int]:
        """Generate list of seeds for all repeats."""
        if self.seed_increment:
            return [self.seed + i for i in range(self.repeats)]
        return [self.seed] * self.repeats


@dataclass
class RunSpec:
    """
    A run specification containing multiple run configurations.
    
    Typically loaded from a YAML or JSON file.
    """
    name: str
    description: str = ""
    runs: list[RunConfig] = field(default_factory=list)
    global_output_dir: str = "runs"
    
    @classmethod
    def from_yaml(cls, path: Path) -> "RunSpec":
        """Load runspec from YAML file."""
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("PyYAML required: pip install pyyaml") from exc
        
        if not path.is_file():
            raise FileNotFoundError(
                f"Runspec file not found: {path}\n"
                f"  See runspecs/ directory for example YAML files."
            )
        with open(path, encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(
                    f"Failed to parse YAML runspec at {path}: {e}\n"
                    f"  Check for indentation errors or invalid YAML syntax."
                ) from e
        if not isinstance(data, dict):
            raise ValueError(
                f"Runspec YAML must be a mapping (dict), got {type(data).__name__} in {path}"
            )
        return cls._from_dict(data, path)
    
    KNOWN_ENGINES = {"sumo", "matsim", "dtalite"}

    @classmethod
    def _from_dict(cls, data: dict, source_path: Path) -> "RunSpec":
        """Parse runspec from dictionary."""
        runs = []
        if "runs" not in data or not data["runs"]:
            raise ValueError(
                f"Runspec at {source_path} has no 'runs' list.\n"
                f"  Add a 'runs:' section with at least one run configuration."
            )
        for i, run_data in enumerate(data.get("runs", [])):
            # Parse mode field (supports both 'mode' and legacy 'mesoscopic')
            mode = SimulationMode.MICROSCOPIC
            if "mode" in run_data:
                mode = SimulationMode.from_string(run_data["mode"])
            elif run_data.get("mesoscopic", False):
                mode = SimulationMode.MESOSCOPIC
            
            # Validate required keys
            for key in ("scenario_id", "scenario_path", "engine"):
                if key not in run_data:
                    raise ValueError(
                        f"Run #{i+1} in {source_path} is missing required key '{key}'.\n"
                        f"  Each run must have: scenario_id, scenario_path, engine"
                    )
            engine = run_data["engine"]
            if engine not in cls.KNOWN_ENGINES:
                raise ValueError(
                    f"Unknown engine '{engine}' in run #{i+1} of {source_path}.\n"
                    f"  Supported engines: {', '.join(sorted(cls.KNOWN_ENGINES))}"
                )
            runs.append(RunConfig(
                scenario_id=run_data["scenario_id"],
                scenario_path=run_data["scenario_path"],
                engine=engine,
                environment=run_data.get("environment", "local_cpu"),
                repeats=run_data.get("repeats", 1),
                seed=run_data.get("seed", 42),
                seed_increment=run_data.get("seed_increment", True),
                timeout_s=run_data.get("timeout_s", 3600),
                output_dir=run_data.get("output_dir"),
                engine_options=run_data.get("engine_options", {}),
                mode=mode,
                mesoscopic=(mode == SimulationMode.MESOSCOPIC)
            ))
        
        return cls(
            name=data.get("name", source_path.stem),
            description=data.get("description", ""),
            runs=runs,
            global_output_dir=data.get("output_dir", "runs")
        )
    
    @classmethod
    def from_file(cls, path: Path) -> "RunSpec":
        """Load a runspec from a file (YAML only)."""
        path = Path(path)
        if path.suffix in (".yaml", ".yml"):
            return cls.from_yaml(path)
        else:
            raise ValueError(f"Unknown runspec format: {path.suffix}")
