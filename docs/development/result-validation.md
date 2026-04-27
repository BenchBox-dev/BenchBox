# Cross-Platform Result Validation

BenchBox's product is trustworthy benchmark results. The cross-platform
comparator lives at `benchbox/core/validation/cross_platform.py` and lets
tests assert that two platforms return equivalent rows for the same query.

## When to use it

Any time you want to confirm that a platform's query output matches a
reference platform's output - e.g., verifying a new adapter against DuckDB
at SF=0.01.

The comparator is a Python API for now; pytest is the canonical execution
surface. A `benchbox validate` CLI may follow once the semantics stabilize.

## Tolerance model

Default: **exact match on every cell, rows in order**.

Loosening requires a spec rule, not convenience:

| Loosening            | Spec anchor                                 |
|----------------------|---------------------------------------------|
| `ordering_required=False` | TPC-H §2.6.3 - no ORDER BY means any order |
| `epsilon > 0`        | TPC-H §2.6.4 - floating-point aggregate tolerance |
| NULL == NULL         | Matches SQL `IS NOT DISTINCT FROM`          |

`Tolerance` rejects a loose configuration without a `rationale` string.
Put the spec citation there.

## Using the comparator

```python
from benchbox.core.validation.cross_platform import (
    STRICT,
    Tolerance,
    compare_query_results,
    register_query_tolerance,
    tolerance_for,
)

# Strict by default.
report = compare_query_results(
    query_id="Q1",
    reference_platform="duckdb",
    comparison_platform="clickhouse",
    reference_rows=duckdb_rows,
    comparison_rows=clickhouse_rows,
)
assert report.matched, report.summary()

# Loosen per-query with a spec-anchored rationale.
register_query_tolerance(
    "tpch",
    "Q1",
    Tolerance(
        epsilon=1e-6,
        rationale="TPC-H §2.6.4 floating-point aggregate epsilon",
    ),
)
tol = tolerance_for("tpch", "Q1")
```

`ComparisonReport.summary()` prints up to five sample divergences with
row/column locators; the rest are counted.

## Running locally

```
uv run -- python -m pytest tests/unit/core/test_cross_platform_validation.py -q
```

The integration matrix (DuckDB × ClickHouse-local / DataFusion / Polars-DF)
and the nightly GitHub Actions workflow are tracked in a follow-up TODO:
`quality-cross-platform-validation-integration-matrix`.

## Adding a new platform

1. Add a pytest case that executes the benchmark on DuckDB (reference) and
   the new platform, then calls `compare_query_results`.
2. If a query legitimately needs a loosened tolerance, register it with a
   spec citation - do not raise the default.
3. Keep the unit tests in `tests/unit/core/test_cross_platform_validation.py`
   - they pin the comparator contract, not platform behavior.
