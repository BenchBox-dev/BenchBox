"""Warn-only pylint duplicate-code (R0801) gate for pre-commit.

Runs `pylint --disable=all --enable=duplicate-code` against `benchbox/` at
the 15-line similarity threshold, reports new clusters above a baseline
count, and ALWAYS exits 0 (warn-only). The baseline is intentionally loose
- this hook exists to surface drift, not to block commits. Promote to
hard-fail in a follow-up TODO once the deferred refactors documented in
docs/development/duplication-residuals.md (R-06, R-07, R-08, R-09) land
and the cluster count drops materially below current.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Keep this in sync with docs/development/duplication-residuals.md.
# Bump only when refactors land and the new floor sticks for >=1 week.
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
            f"pylint duplicate-code: {cluster_count} cluster pairs "
            f"(baseline {BASELINE_CLUSTER_PAIRS}).",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
