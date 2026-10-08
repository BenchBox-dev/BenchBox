# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from benchbox.core.tpch.schema import TABLES
from benchbox.core.tpchavoc.validation import ResultValidator, ValidationError

MATRIX_MODULE = "tests/integration/test_local_platform_benchmark_matrix.py"

SQLITE_VALUE_PARITY_NODE = f"{MATRIX_MODULE}::test_sqlite_tpch_fixed_seed_value_parity"

REQUIRED_LOCAL_CASES: tuple[str, ...] = (
    f"{MATRIX_MODULE}::test_local_platform_benchmark_matrix[tpch-duckdb]",
    f"{MATRIX_MODULE}::test_local_platform_benchmark_matrix[tpcds-duckdb]",
    f"{MATRIX_MODULE}::test_local_platform_benchmark_matrix[tpch-datafusion]",
    f"{MATRIX_MODULE}::test_local_dataframe_platform_benchmark_matrix[tpch-polars-df]",
    SQLITE_VALUE_PARITY_NODE,
)

SQLITE_CASE_SCALE_FACTOR = 0.01
SQLITE_CASE_SEED = 42
SQLITE_CASE_QUERY_IDS: tuple[str, ...] = ("1", "6", "14")
SQLITE_CASE_ITERATIONS = 3
VALUE_TOLERANCE = 1e-10

TPCH_TABLE_NAMES: tuple[str, ...] = tuple(table.name for table in TABLES)


class RequiredCaseError(AssertionError):
    pass


def check_inventory(node_ids: Iterable[str]) -> None:
    observed = Counter(node_ids)
    expected = Counter(REQUIRED_LOCAL_CASES)
    duplicates = sorted(node for node, count in observed.items() if count > 1)
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if duplicates or missing or extra:
        raise RequiredCaseError(
            f"required local-case inventory mismatch: missing={missing}, extra={extra}, duplicates={duplicates}"
        )


def check_collected(collected: Iterable[str]) -> None:
    present = set(collected)
    missing = sorted(node for node in REQUIRED_LOCAL_CASES if node not in present)
    if missing:
        raise RequiredCaseError(f"required local cases are not collected by pytest: {missing}")


def expected_measurement_multiset(
    query_ids: Sequence[str] = SQLITE_CASE_QUERY_IDS,
    iterations: int = SQLITE_CASE_ITERATIONS,
) -> Counter[str]:
    return Counter({str(query_id): iterations for query_id in query_ids})


def check_measurement_multiset(queries: Iterable[Mapping[str, Any]], expected: Counter[str]) -> None:
    measured = [q for q in queries if q.get("run_type") == "measurement"]
    failed = [str(q.get("id")) for q in measured if q.get("status") != "SUCCESS"]
    if failed:
        raise RequiredCaseError(f"non-successful measurement rows: {sorted(failed)}")
    observed = Counter(str(q.get("id")) for q in measured)
    if observed != expected:
        raise RequiredCaseError(
            f"measurement-ID multiset mismatch: expected={dict(sorted(expected.items()))}, "
            f"observed={dict(sorted(observed.items()))}"
        )


def check_tables_populated(row_counts: Mapping[str, int], tables: Sequence[str] = TPCH_TABLE_NAMES) -> None:
    missing = sorted(set(tables) - set(row_counts))
    empty = sorted(name for name in tables if name in row_counts and int(row_counts[name]) <= 0)
    if missing or empty:
        raise RequiredCaseError(f"table population failed: missing={missing}, empty={empty}")


def check_rows_match(
    reference_rows: Sequence[tuple[Any, ...]],
    actual_rows: Sequence[tuple[Any, ...]],
    query_id: str,
    tolerance: float = VALUE_TOLERANCE,
) -> None:
    if not reference_rows:
        raise RequiredCaseError(f"Q{query_id}: reference result is empty; value proof is vacuous")
    validator = ResultValidator(tolerance=tolerance)
    try:
        validator.validate_results_exact(
            [tuple(row) for row in reference_rows],
            [tuple(row) for row in actual_rows],
            query_id=int(query_id),
            variant_id=0,
        )
    except ValidationError as exc:
        raise RequiredCaseError(f"Q{query_id}: SQLite rows differ from reference: {exc}") from exc
