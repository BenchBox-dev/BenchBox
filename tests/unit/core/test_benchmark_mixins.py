"""Tests for benchmark mixin contracts and MRO safety.

Verifies that CursorValidationQueryExecutionMixin enforces its method
contract at class definition time and that required methods resolve to
PlatformAdapter (not stubs) in the standard inheritance chain.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from benchbox.core.benchmark_mixins import (
    CursorValidationQueryExecutionMixin,
    DataGenerationMixin,
    OperationCategoryFacadeMixin,
    QueryCategoryFacadeMixin,
    QueryFacadeMixin,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _FakeParent:
    """Minimal stand-in providing the methods CursorValidationQueryExecutionMixin requires."""

    def log_verbose(self, msg: str) -> None:
        pass

    def log_very_verbose(self, msg: str) -> None:
        pass

    def _build_query_result_with_validation(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS", **kwargs}


class _DataGenerationBenchmark(DataGenerationMixin):
    """Concrete DataGenerationMixin wrapper for unit coverage."""

    def __init__(self, *, batch_size: int | None = None) -> None:
        self._batch_size = batch_size
        self.tables: dict[str, Any] = {}
        self.data_generator = Mock()
        self._schema = {
            "customer": {"columns": [{"name": "id"}, {"name": "name"}]},
            "orders": {"columns": [{"name": "id"}, {"name": "amount"}]},
        }

    def _get_table_schema(self) -> dict[str, Any]:
        return self._schema

    def _get_data_loading_batch_size(self) -> int | None:
        return self._batch_size

    def get_create_tables_sql(self) -> str:
        return "CREATE TABLE customer (id INT, name TEXT);CREATE TABLE orders (id INT, amount INT);"


class _FacadeBenchmark(
    QueryCategoryFacadeMixin,
    OperationCategoryFacadeMixin,
    QueryFacadeMixin,
):
    def __init__(self) -> None:
        self._impl = Mock()


# ---------------------------------------------------------------------------
# MRO resolution tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCursorValidationMixinMRO:
    """Guard against MRO-shadowing regressions (see commit f2ca27e5)."""

    def test_required_methods_resolve_to_parent_not_mixin(self):
        """Verify log_verbose and friends resolve past the mixin to the parent."""

        class ConcreteAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            pass

        adapter = ConcreteAdapter()
        # These must NOT raise NotImplementedError - they should reach _FakeParent.
        adapter.log_verbose("test")
        adapter.log_very_verbose("test")
        result = adapter._build_query_result_with_validation(query_id="q1")
        assert result["status"] == "SUCCESS"

    def test_mixin_does_not_define_required_methods(self):
        """Ensure the mixin itself has no stub implementations that could shadow."""
        mixin_own_methods = set(CursorValidationQueryExecutionMixin.__dict__.keys())
        for method_name in CursorValidationQueryExecutionMixin._REQUIRED_METHODS:
            assert method_name not in mixin_own_methods, (
                f"{method_name} must NOT be defined on CursorValidationQueryExecutionMixin "
                f"- it would shadow the real implementation via MRO"
            )

    def test_real_adapters_resolve_methods_correctly(self):
        """Spot-check that Trino/Firebolt/Presto resolve methods to PlatformAdapter."""
        from benchbox.platforms.base.adapter import PlatformAdapter

        for adapter_name in ("trino", "firebolt", "presto"):
            module = __import__(f"benchbox.platforms.{adapter_name}", fromlist=["_"])
            adapter_cls = next(v for k, v in vars(module).items() if k.endswith("Adapter") and k[0].isupper())
            mro = adapter_cls.__mro__
            for method_name in CursorValidationQueryExecutionMixin._REQUIRED_METHODS:
                # Find the first class in MRO that defines the method
                provider = next(c for c in mro if method_name in c.__dict__)
                assert provider is not CursorValidationQueryExecutionMixin, (
                    f"{adapter_cls.__name__}.{method_name} resolves to the mixin - "
                    f"expected PlatformAdapter or a concrete parent"
                )


# ---------------------------------------------------------------------------
# __init_subclass__ enforcement tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCursorValidationMixinSubclassEnforcement:
    """Verify __init_subclass__ catches missing method providers."""

    def test_subclass_without_provider_raises_type_error(self):
        """A concrete class using the mixin without a parent that provides methods must fail."""
        with pytest.raises(TypeError, match="does not inherit a concrete implementation"):

            class BrokenAdapter(CursorValidationQueryExecutionMixin):
                pass

    def test_intermediate_mixin_skips_enforcement(self):
        """Classes with 'Mixin' or 'Base' suffix are not checked (they're not concrete)."""

        class IntermediateMixin(CursorValidationQueryExecutionMixin):
            pass  # Should NOT raise

    def test_valid_subclass_passes_enforcement(self):
        """A concrete adapter with a proper parent passes the check."""

        class ValidAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            pass  # Should NOT raise


# ---------------------------------------------------------------------------
# execute_query integration test
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCursorValidationExecuteQuery:
    """Test execute_query flow through the mixin."""

    def test_execute_query_returns_success_with_valid_parent(self):
        """End-to-end: mixin execute_query should succeed when parent provides methods."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            pass

        adapter = TestAdapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, "row")]

        result = adapter.execute_query(mock_conn, "SELECT 1", "q1")
        assert result["status"] == "SUCCESS"
        assert result["query_id"] == "q1"

    def test_build_query_stats_and_attach_query_stats_share_payload(self):
        """Helper methods should use a shared stats payload."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            pass

        adapter = TestAdapter()
        stats = adapter._build_query_stats(1.25)
        result = {"query_id": "q1"}

        adapter._attach_query_stats(result, stats)

        assert stats == {"execution_time_seconds": 1.25}
        assert result["query_statistics"] is stats
        assert result["resource_usage"] is stats

    def test_execute_query_logs_row_count_warning(self):
        """Validation warnings should be logged through log_verbose."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            def __init__(self) -> None:
                self.verbose_messages: list[str] = []

            def log_verbose(self, msg: str) -> None:
                self.verbose_messages.append(msg)

        adapter = TestAdapter()
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [(1,)]

        with patch(
            "benchbox.core.validation.query_validation.QueryValidator.validate_query_result",
            return_value=SimpleNamespace(
                warning_message="row count differs",
                is_valid=True,
                error_message=None,
                expected_row_count=1,
            ),
        ):
            result = adapter.execute_query(connection, "SELECT 1", "q1", benchmark_type="tpch", scale_factor=0.01)

        assert result["status"] == "SUCCESS"
        assert adapter.verbose_messages == ["Row count validation: row count differs"]
        cursor.close.assert_called_once()

    def test_execute_query_logs_validation_failure(self):
        """Validation failures should be logged through log_verbose."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            def __init__(self) -> None:
                self.verbose_messages: list[str] = []

            def log_verbose(self, msg: str) -> None:
                self.verbose_messages.append(msg)

        adapter = TestAdapter()
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [(1,)]

        with patch(
            "benchbox.core.validation.query_validation.QueryValidator.validate_query_result",
            return_value=SimpleNamespace(
                warning_message=None,
                is_valid=False,
                error_message="wrong row count",
                expected_row_count=2,
            ),
        ):
            adapter.execute_query(connection, "SELECT 1", "q1", benchmark_type="tpch")

        assert adapter.verbose_messages == ["Row count validation FAILED: wrong row count"]

    def test_execute_query_logs_validation_success(self):
        """Successful validation should route to log_very_verbose."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            def __init__(self) -> None:
                self.very_verbose_messages: list[str] = []

            def log_very_verbose(self, msg: str) -> None:
                self.very_verbose_messages.append(msg)

        adapter = TestAdapter()
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [(1,), (2,)]

        with patch(
            "benchbox.core.validation.query_validation.QueryValidator.validate_query_result",
            return_value=SimpleNamespace(
                warning_message=None,
                is_valid=True,
                error_message=None,
                expected_row_count=2,
            ),
        ):
            adapter.execute_query(connection, "SELECT 1", "q1", benchmark_type="tpch")

        assert adapter.very_verbose_messages == ["Row count validation PASSED: 2 rows (expected: 2)"]

    def test_execute_query_returns_failed_result_on_exception(self):
        """Execution failures should return a failed payload and close the cursor."""

        class TestAdapter(CursorValidationQueryExecutionMixin, _FakeParent):
            pass

        adapter = TestAdapter()
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor
        cursor.execute.side_effect = RuntimeError("boom")

        with patch("benchbox.core.benchmark_mixins.elapsed_seconds", return_value=0.5):
            result = adapter.execute_query(connection, "SELECT 1", "q1")

        assert result == {
            "query_id": "q1",
            "status": "FAILED",
            "execution_time_seconds": 0.5,
            "rows_returned": 0,
            "error": "boom",
            "error_type": "RuntimeError",
        }
        cursor.close.assert_called_once()


class TestDataGenerationMixin:
    """Test CSV generation and load helpers."""

    def test_generate_data_defaults_to_all_tables(self):
        benchmark = _DataGenerationBenchmark()
        expected = {"customer": Path("customer.csv")}
        benchmark.data_generator.generate_data.return_value = expected

        result = benchmark.generate_data()

        assert result is expected
        benchmark.data_generator.generate_data.assert_called_once_with(["customer", "orders"])

    def test_generate_data_rejects_invalid_output_format(self):
        benchmark = _DataGenerationBenchmark()

        with pytest.raises(ValueError, match="Unsupported output format"):
            benchmark.generate_data(output_format="parquet")

    def test_generate_data_rejects_unknown_tables(self):
        benchmark = _DataGenerationBenchmark()

        with pytest.raises(ValueError, match="Invalid table names"):
            benchmark.generate_data(tables=["missing"])

    def test_load_data_to_database_requires_generated_tables(self):
        benchmark = _DataGenerationBenchmark()

        with pytest.raises(ValueError, match="No data generated"):
            benchmark.load_data_to_database(Mock())

    def test_load_data_to_database_uses_executescript_and_executemany(self, tmp_path: Path):
        benchmark = _DataGenerationBenchmark()
        customer_csv = tmp_path / "customer.csv"
        customer_csv.write_text("1|alice\n2|bob\n")
        benchmark.tables = {"customer": customer_csv}

        connection = Mock(spec=["executescript", "executemany", "commit"])

        benchmark.load_data_to_database(connection)

        connection.executescript.assert_called_once()
        connection.executemany.assert_called_once_with(
            "INSERT INTO customer VALUES (?,?)",
            [["1", "alice"], ["2", "bob"]],
        )
        connection.commit.assert_called_once()

    def test_load_data_to_database_batches_rows_when_batch_size_is_set(self, tmp_path: Path):
        benchmark = _DataGenerationBenchmark(batch_size=2)
        orders_csv = tmp_path / "orders.csv"
        orders_csv.write_text("1|10\n2|20\n3|30\n")
        benchmark.tables = {"orders": orders_csv}

        connection = Mock(spec=["executescript", "executemany", "commit"])

        benchmark.load_data_to_database(connection)

        assert connection.executemany.call_args_list == [
            (("INSERT INTO orders VALUES (?,?)", [["1", "10"], ["2", "20"]]),),
            (("INSERT INTO orders VALUES (?,?)", [["3", "30"]]),),
        ]

    def test_load_data_to_database_uses_cursor_fallbacks(self, tmp_path: Path):
        benchmark = _DataGenerationBenchmark()
        customer_csv = tmp_path / "customer.csv"
        customer_csv.write_text("1|alice\n")
        benchmark.tables = {"customer": customer_csv}
        cursor = Mock()

        class CursorOnlyConnection:
            def __init__(self, inner_cursor: Mock) -> None:
                self._cursor = inner_cursor
                self.committed = False

            def cursor(self) -> Mock:
                return self._cursor

            def commit(self) -> None:
                self.committed = True

        connection = CursorOnlyConnection(cursor)

        benchmark.load_data_to_database(connection)

        assert cursor.execute.call_args_list == [
            (("CREATE TABLE customer (id INT, name TEXT)",),),
            (("CREATE TABLE orders (id INT, amount INT)",),),
            (("INSERT INTO customer VALUES (?,?)", ["1", "alice"]),),
        ]
        assert connection.committed is True


class TestFacadeMixins:
    """Test simple delegation mixins."""

    def test_category_and_query_facades_delegate_to_impl(self):
        benchmark = _FacadeBenchmark()
        benchmark._impl.get_queries_by_category.return_value = {"Q1": "select 1"}
        benchmark._impl.get_query_categories.return_value = ["power"]
        benchmark._impl.get_operations_by_category.return_value = {"op1": {"kind": "write"}}
        benchmark._impl.get_operation_categories.return_value = ["writes"]
        benchmark._impl.get_queries.return_value = {"Q1": "select 1"}
        benchmark._impl.get_query.return_value = "select 1"

        assert benchmark.get_queries_by_category("power") == {"Q1": "select 1"}
        assert benchmark.get_query_categories() == ["power"]
        assert benchmark.get_operations_by_category("writes") == {"op1": {"kind": "write"}}
        assert benchmark.get_operation_categories() == ["writes"]
        assert benchmark.get_queries(dialect="duckdb") == {"Q1": "select 1"}
        assert benchmark.get_query("Q1", params={"x": 1}, dialect="duckdb") == "select 1"

        benchmark._impl.get_queries_by_category.assert_called_once_with("power")
        benchmark._impl.get_query_categories.assert_called_once_with()
        benchmark._impl.get_operations_by_category.assert_called_once_with("writes")
        benchmark._impl.get_operation_categories.assert_called_once_with()
        benchmark._impl.get_queries.assert_called_once_with(dialect="duckdb")
        benchmark._impl.get_query.assert_called_once_with("Q1", params={"x": 1}, dialect="duckdb")

    def test_query_facade_omits_params_when_none(self):
        benchmark = _FacadeBenchmark()
        benchmark._impl.get_query.return_value = "select 2"

        assert benchmark.get_query("Q2", dialect="sqlite") == "select 2"
        benchmark._impl.get_query.assert_called_once_with("Q2", dialect="sqlite")
