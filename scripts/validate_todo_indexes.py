from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKS = ("timing_policy_check.py", "fast_lane_ceiling_check.py")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    status = 0
    for script in CHECKS:
        cmd = [sys.executable, str(repo_root / "_project" / "scripts" / script), "--strict"]
        status = subprocess.call(cmd, cwd=repo_root) or status
    return status


if __name__ == "__main__":
    raise SystemExit(main())
