"""Internal CLI entry points for the `make uat-*` operator targets.

These are intentionally thin: argparse → call into framework module →
print structured output. Not exposed as a `benchbox` subcommand (UAT
is a project-developer concern; benchbox is a project-user concern;
see _project/specs/uat-framework.md Section 1.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cell_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-cell PLATFORM=X BENCHMARK=Y SCALE=Z`."""
    from tests.uat.runner import run_cell

    parser = argparse.ArgumentParser(prog="uat-cell")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--scale", required=True, type=float)
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--phases", default="load,power")
    parser.add_argument("--compression", default=None)
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args(argv)

    result = run_cell(
        platform=args.platform,
        benchmark=args.benchmark,
        scale=args.scale,
        timeout_s=args.timeout_s,
        phases=args.phases,
        compression=args.compression,
        log_dir=Path(args.log_dir) if args.log_dir else None,
    )
    print(
        json.dumps(
            {
                "platform": result.platform,
                "benchmark": result.benchmark,
                "scale": result.scale,
                "status": result.status,
                "exit_code": result.exit_code,
                "elapsed_s": round(result.elapsed_s, 2),
                "log_path": str(result.log_path),
                "result_path": str(result.result_path) if result.result_path else None,
            },
            indent=2,
        )
    )
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(cell_main())
