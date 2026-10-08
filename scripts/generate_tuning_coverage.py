from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchbox.core.tuning.coverage import build_tuning_coverage_rows, write_tuning_coverage_tsv
from tests.uat.matrix import PLATFORM_GROUPS, load_benchmarks, resolve_benchmarks


def main() -> None:
    platforms = list(PLATFORM_GROUPS["all"])
    benchmarks = resolve_benchmarks(groups=["all"], benchmarks=load_benchmarks())
    rows = build_tuning_coverage_rows(platforms, benchmarks)
    target = REPO_ROOT / "tests" / "uat" / "data" / "tuning_coverage.tsv"
    write_tuning_coverage_tsv(rows, target)
    print(f"wrote {len(rows)} rows to {target}")


if __name__ == "__main__":
    main()
