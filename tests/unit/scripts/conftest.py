import sys
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
