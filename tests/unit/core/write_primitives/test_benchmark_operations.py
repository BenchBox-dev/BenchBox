"""Tests for WritePrimitivesBenchmark operation execution internals.

Covers rows_affected extraction, validation query checking, cleanup SQL
execution, load_data verification, reset flow, population SQL generation,
and staging table lifecycle operations not covered by test_benchmark_execution.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from benchbox.core.write_primitives.benchmark import OperationResult, WritePrimitivesBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def wp(tmp_path: Path) -> WritePrimitivesBenchmark:
    return WritePrimitivesBenchmark(output_dir=tmp_path)


# ---------------------------------------------------------------------------
# _extract_rows_affected
# ---------------------------------------------------------------------------
class TestExtractRowsAffected:
    def test_normal_rowcount(self, wp: WritePrimitivesBenchmark):
        result = SimpleNamespace(rowcount=42)
        assert wp._extract_rows_affected(result, "OP_1") == 42

    def test_rowcount_none_returns_sentinel(self, wp: WritePrimitivesBenchmark):
        result = SimpleNamespace()  # no rowcount attribute
        assert wp._extract_rows_affected(result, "OP_1") == -1

    def test_rowcount_minus_one_passthrough(self, wp: WritePrimitivesBenchmark):
        result = SimpleNamespace(rowcount=-1)
        assert wp._extract_rows_affected(result, "OP_1") == -1

    def test_rowcount_zero(self, wp: WritePrimitivesBenchmark):
        result = SimpleNamespace(rowcount=0)
        assert wp._extract_rows_affected(result, "OP_1") == 0


# ---------------------------------------------------------------------------
# _run_operation_validation
# ---------------------------------------------------------------------------
class TestRunOperationValidation:
    def test_passes_when_no_validation_queries(self, wp: WritePrimitivesBenchmark):
        operation = SimpleNamespace(validation_queries=[])
        conn = MagicMock()
        passed, results, duration_ms = wp._run_operation_validation(operation, conn, "OP_1")
        assert passed is True
        assert results == []
        assert duration_ms >= 0

    def test_passes_with_matching_row_count(self, wp: WritePrimitivesBenchmark):
        val_query = SimpleNamespace(
            id="V1",
            sql="SELECT COUNT(*) FROM t",
            expected_rows=3,
            expected_rows_min=None,
            expected_rows_max=None,
            expected_values=None,
            check_expression=None,
            platform_overrides={},
        )
        operation = SimpleNamespace(validation_queries=[val_query])
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [(1,), (2,), (3,)]
        passed, results, _ = wp._run_operation_validation(operation, conn, "OP_1")
        assert passed is True
        assert results[0]["actual_rows"] == 3
        assert results[0]["passed"] is True

    def test_fails_with_wrong_row_count(self, wp: WritePrimitivesBenchmark):
        val_query = SimpleNamespace(
            id="V1",
            sql="SELECT * FROM t",
            expected_rows=10,
            expected_rows_min=None,
            expected_rows_max=None,
            expected_values=None,
            check_expression=None,
            platform_overrides={},
        )
        operation = SimpleNamespace(validation_queries=[val_query])
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [(1,)]
        passed, results, _ = wp._run_operation_validation(operation, conn, "OP_1")
        assert passed is False
        assert results[0]["passed"] is False


# ---------------------------------------------------------------------------
# _run_operation_cleanup
# ---------------------------------------------------------------------------
class TestRunOperationCleanup:
    def test_no_cleanup_sql_succeeds(self, wp: WritePrimitivesBenchmark):
        operation = SimpleNamespace(cleanup_sql=None)
        conn = MagicMock()
        success, warning, duration_ms = wp._run_operation_cleanup(operation, conn, "OP_1")
        assert success is True
        assert warning is None
        conn.execute.assert_not_called()

    def test_cleanup_sql_executes(self, wp: WritePrimitivesBenchmark):
        operation = SimpleNamespace(cleanup_sql="DELETE FROM t WHERE 1=1")
        conn = MagicMock()
        success, warning, _ = wp._run_operation_cleanup(operation, conn, "OP_1")
        assert success is True
        assert warning is None
        conn.execute.assert_called_once_with("DELETE FROM t WHERE 1=1")

    def test_cleanup_failure_returns_warning(self, wp: WritePrimitivesBenchmark):
        operation = SimpleNamespace(cleanup_sql="DROP TABLE missing")
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("table not found")
        success, warning, _ = wp._run_operation_cleanup(operation, conn, "OP_1")
        assert success is False
        assert "cleanup failed" in warning
        assert "table not found" in warning


# ---------------------------------------------------------------------------
# _get_population_sql
# ---------------------------------------------------------------------------
class TestGetPopulationSql:
    def test_returns_string(self, wp: WritePrimitivesBenchmark):
        sql = wp._get_population_sql("orders_stage", "orders")
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_contains_table_names(self, wp: WritePrimitivesBenchmark):
        sql = wp._get_population_sql("orders_stage", "orders")
        assert "orders_stage" in sql.lower() or "orders" in sql.lower()


# ---------------------------------------------------------------------------
# load_data
# ---------------------------------------------------------------------------
class TestLoadData:
    def test_returns_dict(self, wp: WritePrimitivesBenchmark):
        conn = MagicMock()
        # Mock table_exists to return True for all tables
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "benchbox.core.write_primitives.benchmark.table_exists",
                lambda conn, name, *args, **kwargs: True,
            )
            conn.execute.return_value.fetchone.return_value = (100,)
            result = wp.load_data(conn)
            assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# OperationResult edge cases
# ---------------------------------------------------------------------------
class TestOperationResultEdgeCases:
    def test_skipped_status(self):
        result = OperationResult(
            operation_id="SKIP_1",
            success=True,
            write_duration_ms=0.0,
            rows_affected=0,
            validation_duration_ms=0.0,
            validation_passed=True,
            validation_results=[],
            cleanup_duration_ms=0.0,
            cleanup_success=True,
            status="SKIPPED",
        )
        assert result.status == "SKIPPED"

    def test_with_cleanup_warning(self):
        result = OperationResult(
            operation_id="WARN_1",
            success=True,
            write_duration_ms=10.0,
            rows_affected=5,
            validation_duration_ms=2.0,
            validation_passed=True,
            validation_results=[],
            cleanup_duration_ms=1.0,
            cleanup_success=False,
            cleanup_warning="Cleanup SQL failed",
        )
        assert result.cleanup_warning == "Cleanup SQL failed"
        assert result.cleanup_success is False


# ---------------------------------------------------------------------------
# Operation management edge cases
# ---------------------------------------------------------------------------
class TestOperationManagement:
    def test_get_operations_by_category_returns_subset(self, wp: WritePrimitivesBenchmark):
        categories = wp.get_operation_categories()
        if categories:
            ops = wp.get_operations_by_category(categories[0])
            assert isinstance(ops, dict)
            for op in ops.values():
                assert op.category == categories[0]

    def test_get_operations_by_unknown_category(self, wp: WritePrimitivesBenchmark):
        ops = wp.get_operations_by_category("nonexistent_category")
        assert ops == {}

    def test_supports_dataframe_mode(self, wp: WritePrimitivesBenchmark):
        assert wp.supports_dataframe_mode() is True

    def test_skip_dataframe_data_loading(self, wp: WritePrimitivesBenchmark):
        assert wp.skip_dataframe_data_loading() is True

    def test_get_data_source_benchmark_returns_tpch(self, wp: WritePrimitivesBenchmark):
        assert wp.get_data_source_benchmark() == "tpch"
