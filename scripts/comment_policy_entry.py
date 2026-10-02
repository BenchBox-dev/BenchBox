from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
runpy.run_path(str(Path(__file__).with_name("check_comment_policy.py")), run_name="__main__")
