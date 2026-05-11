"""Validate Results Explorer DuckDB eligibility invariants.

This script is intentionally independent of the build pipeline so release
gates can run it against any generated ``results.duckdb`` snapshot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "results": {
        "result_id",
        "query_count",
        "has_display_timing",
        "valid_query_count",
        "missing_query_count",
        "zero_timing_count",
        "display_exclusion_reason",
        "comparison_exclusion_reason",
        "ranking_exclusion_reason",
    },
    "benchmark_rankings": {
        "result_id",
        "primary_metric",
        "rank",
        "total_in_cohort",
        "cohort_ranked_count",
        "cohort_ranking_exclusion_reason",
        "has_display_timing",
        "valid_query_count",
        "comparison_exclusion_reason",
        "ranking_exclusion_reason",
        "power_score",
        "display_geomean_ms",
    },
}


def _count(con: Any, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0] if row else 0)


def _required_column_errors(con: Any) -> list[str]:
    errors: list[str] = []
    for table, required in REQUIRED_COLUMNS.items():
        actual = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
        missing = sorted(required - actual)
        if missing:
            errors.append(f"{table} missing required eligibility columns: {', '.join(missing)}")
    return errors


def check_snapshot(db_path: Path) -> list[str]:
    try:
        import duckdb
    except ImportError as exc:
        raise SystemExit("duckdb is required to validate Results Explorer snapshot invariants") from exc

    errors: list[str] = []
    with duckdb.connect(str(db_path), read_only=True) as con:
        errors.extend(_required_column_errors(con))
        if errors:
            return errors

        checks = [
            (
                "compare-eligible rows must have enough valid timings",
                """
                SELECT COUNT(*)
                FROM results
                WHERE comparison_exclusion_reason IS NULL
                  AND (
                    has_display_timing = FALSE
                    OR valid_query_count < 2
                    OR (query_count > 0 AND valid_query_count * 2 < query_count)
                  )
                """,
            ),
            (
                "ranked rows must have a valid primary metric",
                """
                SELECT COUNT(*)
                FROM benchmark_rankings
                WHERE rank IS NOT NULL
                  AND (
                    ranking_exclusion_reason IS NOT NULL
                    OR CASE
                        WHEN primary_metric = 'power_score' THEN power_score
                        ELSE display_geomean_ms
                      END IS NULL
                    OR CASE
                        WHEN primary_metric = 'power_score' THEN power_score
                        ELSE display_geomean_ms
                      END <= 0
                  )
                """,
            ),
            (
                "all-unrankable cohorts must expose an explicit cohort reason",
                """
                SELECT COUNT(*)
                FROM benchmark_rankings
                WHERE cohort_ranked_count = 0
                  AND cohort_ranking_exclusion_reason IS NULL
                """,
            ),
            (
                "ranked cohorts must not expose an all-unrankable cohort reason",
                """
                SELECT COUNT(*)
                FROM benchmark_rankings
                WHERE cohort_ranked_count > 0
                  AND cohort_ranking_exclusion_reason IS NOT NULL
                """,
            ),
            (
                "no row can lack display timing and still be compare-eligible",
                """
                SELECT COUNT(*)
                FROM results
                WHERE has_display_timing = FALSE
                  AND comparison_exclusion_reason IS NULL
                """,
            ),
            (
                "query_count=0 results must not appear as ranked evidence",
                """
                SELECT COUNT(*)
                FROM benchmark_rankings br
                JOIN results r USING (result_id)
                WHERE r.query_count = 0
                  AND br.rank IS NOT NULL
                """,
            ),
            (
                "ranking totals must match explicit cohort ranked counts",
                """
                SELECT COUNT(*)
                FROM benchmark_rankings
                WHERE total_in_cohort != cohort_ranked_count
                """,
            ),
        ]
        for label, sql in checks:
            failures = _count(con, sql)
            if failures:
                errors.append(f"{label}: {failures} row(s)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("duckdb_path", type=Path)
    args = parser.parse_args(argv)

    db_path = args.duckdb_path
    if not db_path.is_file():
        print(f"snapshot not found: {db_path}", file=sys.stderr)
        return 2

    errors = check_snapshot(db_path)
    if errors:
        print("Results Explorer snapshot invariants FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Results Explorer snapshot invariants passed: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
