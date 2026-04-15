"""
Run specification schema for benchmark execution.

A runspec defines which scenarios to run, with which engines,
and how many repetitions for reproducibility analysis.

Supported formats:
- YAML (recommended)
- JSON
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    engine: str  # sumo, matsim, qarsumo
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
        except ImportError:
            raise ImportError("PyYAML required: pip install pyyaml")
        
        with open(path) as f:
            data = yaml.safe_load(f)
        
        return cls._from_dict(data, path)
    
    @classmethod
    def from_json(cls, path: Path) -> "RunSpec":
        """Load runspec from JSON file."""
        with open(path) as f:
            data = json.load(f)
        
        return cls._from_dict(data, path)
    
    @classmethod
    def _from_dict(cls, data: dict, source_path: Path) -> "RunSpec":
        """Parse runspec from dictionary."""
        runs = []
        for run_data in data.get("runs", []):
            # Parse mode field (supports both 'mode' and legacy 'mesoscopic')
            mode = SimulationMode.MICROSCOPIC
            if "mode" in run_data:
                mode = SimulationMode.from_string(run_data["mode"])
            elif run_data.get("mesoscopic", False):
                mode = SimulationMode.MESOSCOPIC
            
            runs.append(RunConfig(
                scenario_id=run_data["scenario_id"],
                scenario_path=run_data["scenario_path"],
                engine=run_data["engine"],
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
        """Load runspec from file (auto-detect format)."""
        path = Path(path)
        if path.suffix in (".yaml", ".yml"):
            return cls.from_yaml(path)
        elif path.suffix == ".json":
            return cls.from_json(path)
        else:
            raise ValueError(f"Unknown runspec format: {path.suffix}")
    
    def to_yaml(self, path: Path) -> None:
        """Save runspec to YAML file."""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required: pip install pyyaml")
        
        data = self._to_dict()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    def to_json(self, path: Path) -> None:
        """Save runspec to JSON file."""
        data = self._to_dict()
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _to_dict(self) -> dict:
        """Convert runspec to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "output_dir": self.global_output_dir,
            "runs": [
                {
                    "scenario_id": r.scenario_id,
                    "scenario_path": r.scenario_path,
                    "engine": r.engine,
                    "environment": r.environment,
                    "mode": r.mode.value,  # microscopic or mesoscopic
                    "repeats": r.repeats,
                    "seed": r.seed,
                    "seed_increment": r.seed_increment,
                    "timeout_s": r.timeout_s,
                    "output_dir": r.output_dir,
                    "engine_options": r.engine_options
                }
                for r in self.runs
            ]
        }


def create_example_runspec(output_path: Path) -> RunSpec:
    """Create an example runspec for reference."""
    spec = RunSpec(
        name="example_benchmark",
        description="Example benchmark specification",
        global_output_dir="runs",
        runs=[
            RunConfig(
                scenario_id="chicago_1k_car",
                scenario_path="scenarios/chicago_1k_car",
                engine="sumo",
                environment="local_cpu",
                repeats=3,
                seed=42,
                mode=SimulationMode.MESOSCOPIC,
            ),
            RunConfig(
                scenario_id="nyc_10k_car",
                scenario_path="scenarios/nyc_10k_car",
                engine="sumo",
                environment="local_cpu",
                repeats=3,
                seed=42,
                mode=SimulationMode.MESOSCOPIC,
            ),
        ]
    )
    
    spec.to_yaml(output_path)
    logger.info(f"Created example runspec: {output_path}")
    return spec
