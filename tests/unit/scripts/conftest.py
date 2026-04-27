"""conftest for tests/unit/scripts/ - adds the project scripts/ dir to sys.path."""

import sys
from pathlib import Path

# Make scripts/ importable so test modules can use plain imports.
_scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
