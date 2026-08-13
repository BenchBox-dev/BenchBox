"""Shared fixtures for repository script tests."""

import sys
from pathlib import Path

# Make the repository's general scripts directory importable. Package-boundary
# tests load _project/scripts explicitly when they need the BenchBox adapter.
scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
