from __future__ import annotations

import re
import subprocess
import sys

BASELINE_CLUSTER_PAIRS = 102


def main() -> int:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "pylint",
            "--with",
            "pandas",
            "--with",
            "polars",
            "--",
            "python",
            "-m",
            "pylint",
            "--disable=all",
            "--enable=duplicate-code",
            "--min-similarity-lines=15",
            "benchbox/",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    cluster_count = len(re.findall(r"R0801: Similar lines", output))

    if cluster_count > BASELINE_CLUSTER_PAIRS:
        delta = cluster_count - BASELINE_CLUSTER_PAIRS
        print(
            f"::warning:: pylint duplicate-code: {cluster_count} cluster pairs "
            f"(+{delta} above baseline {BASELINE_CLUSTER_PAIRS}). "
            f"See docs/development/duplication-residuals.md.",
            file=sys.stderr,
        )
    else:
        print(
            f"pylint duplicate-code: {cluster_count} cluster pairs (baseline {BASELINE_CLUSTER_PAIRS}).",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
