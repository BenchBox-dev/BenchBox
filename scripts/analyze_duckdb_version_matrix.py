#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import analyze_version_matrix
from scripts.version_matrix_specs import DUCKDB

CLI_DESCRIPTION = "Compute median DuckDB version-matrix metrics from a run manifest."


def main(argv: list[str] | None = None) -> int:
    return analyze_version_matrix.main(argv, spec=DUCKDB, description=CLI_DESCRIPTION)


if __name__ == "__main__":
    raise SystemExit(main())
