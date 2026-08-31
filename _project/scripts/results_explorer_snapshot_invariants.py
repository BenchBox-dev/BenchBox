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
        "logical_query_count",
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
        "logical_query_count",
        "valid_query_count",
        "comparison_exclusion_reason",
        "ranking_exclusion_reason",
        "power_score",
        "display_geomean_ms",
    },
    "cohort_metadata": {
        "cohort_key",
        "platform_id",
        "result_id",
        "platform_count",
        "cohort_ranked_count",
        "cohort_ranking_exclusion_reason",
        "rank",
        "metric_value",
        "has_display_timing",
        "display_exclusion_reason",
        "comparison_exclusion_reason",
        "ranking_exclusion_reason",
    },
    "result_basis_availability": {
        "result_id",
        "has_warmup",
        "measurement_pass_count",
        "warmup_status",
        "available_bases",
    },
    "result_environment": {
        "result_id",
        "os",
        "arch",
        "cpu_count",
        "memory_gb",
        "python",
        "cpu_model",
        "cpu_family",
        "cpu_identity_provenance",
    },
}

# These are the same required non-empty scans used by the browser during
# snapshot initialisation. Keeping the list here makes an empty or partially
# populated candidate fail before it can replace the last known-good output.
REQUIRED_NONEMPTY_SCANS: tuple[tuple[str, str], ...] = (
    ("results", "SELECT COUNT(*) FROM results"),
    ("platform_index_rows", "SELECT COUNT(*) FROM platform_index_rows"),
    ("benchmark_rankings", "SELECT COUNT(*) FROM benchmark_rankings"),
    ("benchmark_matrix_cells", "SELECT COUNT(*) FROM benchmark_matrix_cells"),
    ("result_detail_metrics", "SELECT COUNT(*) FROM result_detail_metrics"),
    ("result_basis_availability", "SELECT COUNT(*) FROM result_basis_availability"),
)


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


def _required_nonempty_scan_errors(con: Any) -> list[str]:
    errors: list[str] = []
    for label, sql in REQUIRED_NONEMPTY_SCANS:
        count = _count(con, sql)
        if count < 1:
            errors.append(f"required browser scan {label} must be non-empty: {count} row(s)")
    return errors


def check_snapshot(db_path: Path) -> list[str]:
    try:
        import duckdb
    except ImportError as exc:
        raise SystemExit("duckdb is required to validate Results Explorer snapshot invariants") from exc

    errors: list[str] = []
    wal_path = db_path.with_name(db_path.name + ".wal")
    if wal_path.exists():
        errors.append(f"snapshot is not self-contained: WAL sidecar exists at {wal_path.name}")
        return errors
    with duckdb.connect(str(db_path), read_only=True) as con:
        errors.extend(_required_column_errors(con))
        if errors:
            return errors
        errors.extend(_required_nonempty_scan_errors(con))

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
                    OR (logical_query_count > 0 AND valid_query_count * 2 < logical_query_count)
                  )
                """,
            ),
            (
                "public snapshot must expose at least one compare-eligible display row",
                """
                SELECT CASE
                    WHEN COUNT(*) = 0
                    THEN 1
                    ELSE 0
                END
                FROM results
                WHERE has_display_timing = TRUE
                  AND comparison_exclusion_reason IS NULL
                """,
            ),
            (
                "fully covered logical rows must not be excluded by raw sample count",
                """
                SELECT COUNT(*)
                FROM results
                WHERE comparison_exclusion_reason = 'insufficient_query_coverage'
                  AND logical_query_count > 0
                  AND valid_query_count >= logical_query_count
                  AND query_count > logical_query_count
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
            (
                "published unranked leaderboard evidence must expose an exclusion reason",
                """
                SELECT COUNT(*)
                FROM cohort_metadata
                WHERE platform_count >= 2
                  AND rank IS NULL
                  AND result_id IS NOT NULL
                  AND COALESCE(
                    ranking_exclusion_reason,
                    cohort_ranking_exclusion_reason,
                    display_exclusion_reason,
                    comparison_exclusion_reason
                  ) IS NULL
                """,
            ),
            (
                "ranked leaderboard evidence must not carry a ranking exclusion reason",
                """
                SELECT COUNT(*)
                FROM cohort_metadata
                WHERE platform_count >= 2
                  AND rank IS NOT NULL
                  AND ranking_exclusion_reason IS NOT NULL
                """,
            ),
            (
                "unranked leaderboard evidence with metrics must not be indistinguishable from missing evidence",
                """
                SELECT COUNT(*)
                FROM cohort_metadata
                WHERE platform_count >= 2
                  AND rank IS NULL
                  AND metric_value IS NOT NULL
                  AND COALESCE(ranking_exclusion_reason, cohort_ranking_exclusion_reason) IS NULL
                """,
            ),
            (
                "snapshots claiming warmup basis availability must have passing warmup executions in query_executions",
                """
                SELECT COUNT(*)
                FROM result_basis_availability rba
                WHERE rba.has_warmup = TRUE
                  AND NOT EXISTS (
                    SELECT 1 FROM query_executions qe
                    WHERE qe.result_id = rba.result_id
                      AND qe.run_type = 'warmup'
                      AND qe.status = 'pass'
                  )
                """,
            ),
            (
                "results with passing warmup executions must report warmup as available",
                """
                SELECT COUNT(*)
                FROM result_basis_availability rba
                WHERE rba.has_warmup = FALSE
                  AND EXISTS (
                    SELECT 1 FROM query_executions qe
                    WHERE qe.result_id = rba.result_id
                      AND qe.run_type = 'warmup'
                      AND qe.status = 'pass'
                  )
                """,
            ),
            (
                "results without warmup executions must report warmup as unavailable",
                """
                SELECT COUNT(*)
                FROM result_basis_availability rba
                WHERE rba.has_warmup = FALSE
                  AND rba.warmup_status = 'available'
                """,
            ),
            (
                "basis availability must cover every result in the snapshot",
                """
                SELECT COUNT(*)
                FROM results r
                LEFT JOIN result_basis_availability rba USING (result_id)
                WHERE rba.result_id IS NULL
                """,
            ),
            (
                "query_executions must only contain allowed execution run types",
                """
                SELECT COUNT(*)
                FROM query_executions
                WHERE run_type IS NOT NULL
                  AND run_type NOT IN ('measurement', 'warmup')
                """,
            ),
            (
                "result_environment cpu_family must belong to closed vocabulary or be NULL",
                """
                SELECT COUNT(*)
                FROM result_environment
                WHERE cpu_family IS NOT NULL
                  AND cpu_family NOT IN (
                    'apple_silicon', 'graviton', 'intel_xeon', 'intel_core',
                    'amd_epyc', 'amd_ryzen', 'ampere_altra', 'arm_neoverse', 'unknown'
                  )
                """,
            ),
            (
                "if cpu_model is present, cpu_family must be populated",
                """
                SELECT COUNT(*)
                FROM result_environment
                WHERE cpu_model IS NOT NULL
                  AND cpu_family IS NULL
                """,
            ),
            (
                "if cpu_model is NULL, cpu_family must be NULL",
                """
                SELECT COUNT(*)
                FROM result_environment
                WHERE cpu_model IS NULL
                  AND cpu_family IS NOT NULL
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
