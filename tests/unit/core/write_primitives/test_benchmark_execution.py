"""Unit tests for Write Primitives benchmark execution.

Tests for:
- WritePrimitivesBenchmark initialization
- OperationResult dataclass
- SQL identifier quoting and placeholder replacement
- Operation management methods
- Benchmark information retrieval

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.core.write_primitives.benchmark import OperationResult, WritePrimitivesBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestOperationResult:
    """Tests for OperationResult dataclass."""

    def test_operation_result_creation(self):
        """Test creating an OperationResult instance."""
        result = OperationResult(
            operation_id="INSERT_001",
            success=True,
            write_duration_ms=50.5,
            rows_affected=100,
            validation_duration_ms=10.2,
            validation_passed=True,
            validation_results=[{"query_id": "V1", "passed": True}],
            cleanup_duration_ms=5.0,
            cleanup_success=True,
        )

        assert result.operation_id == "INSERT_001"
        assert result.success is True
        assert result.write_duration_ms == 50.5
        assert result.rows_affected == 100
        assert result.validation_passed is True
        assert result.cleanup_success is True
        assert result.error is None
        assert result.cleanup_warning is None

    def test_operation_result_with_error(self):
        """Test creating an OperationResult with error."""
        result = OperationResult(
            operation_id="FAILED_OP",
            success=False,
            write_duration_ms=0.0,
            rows_affected=0,
            validation_duration_ms=0.0,
            validation_passed=False,
            validation_results=[],
            cleanup_duration_ms=0.0,
            cleanup_success=False,
            error="Database error: connection lost",
            cleanup_warning="Cleanup failed",
        )

        assert result.success is False
        assert result.error == "Database error: connection lost"
        assert result.cleanup_warning == "Cleanup failed"


class TestWritePrimitivesBenchmarkInit:
    """Tests for WritePrimitivesBenchmark initialization."""

    def test_default_initialization(self, tmp_path):
        """Test benchmark initializes with defaults."""
        with patch("benchbox.core.write_primitives.benchmark.get_benchmark_runs_datagen_path") as mock_path:
            mock_path.return_value = tmp_path
            wp_benchmark = WritePrimitivesBenchmark()

            assert wp_benchmark._name == "Write Primitives Benchmark"
            assert wp_benchmark._version == "1.0"
            assert wp_benchmark.scale_factor == 1.0
            assert wp_benchmark.tables == {}

    def test_custom_scale_factor(self, tmp_path):
        """Test benchmark with custom scale factor."""
        with patch("benchbox.core.write_primitives.benchmark.get_benchmark_runs_datagen_path") as mock_path:
            mock_path.return_value = tmp_path
            wp_benchmark = WritePrimitivesBenchmark(scale_factor=0.1)

            assert wp_benchmark.scale_factor == 0.1

    def test_custom_output_dir(self, tmp_path):
        """Test benchmark with custom output directory."""
        wp_benchmark = WritePrimitivesBenchmark(output_dir=tmp_path)

        # output_dir property should return a path-like object
        assert str(wp_benchmark.output_dir) == str(tmp_path)

    def test_data_source_benchmark(self, tmp_path):
        """Test get_data_source_benchmark returns tpch."""
        wp_benchmark = WritePrimitivesBenchmark(output_dir=tmp_path)
        assert wp_benchmark.get_data_source_benchmark() == "tpch"


class TestQuoteIdentifier:
    """Tests for SQL identifier quoting."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_valid_identifier(self, wp_benchmark):
        """Test quoting valid identifiers."""
        assert wp_benchmark._quote_identifier("table_name") == '"table_name"'
        assert wp_benchmark._quote_identifier("Orders") == '"Orders"'
        assert wp_benchmark._quote_identifier("_private") == '"_private"'

    def test_identifier_with_numbers(self, wp_benchmark):
        """Test quoting identifiers with numbers."""
        assert wp_benchmark._quote_identifier("table123") == '"table123"'
        assert wp_benchmark._quote_identifier("t1") == '"t1"'

    def test_invalid_identifier_with_spaces(self, wp_benchmark):
        """Test that identifiers with spaces raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            wp_benchmark._quote_identifier("table name")

    def test_invalid_identifier_with_semicolon(self, wp_benchmark):
        """Test that identifiers with semicolons raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            wp_benchmark._quote_identifier("table;DROP TABLE users")

    def test_invalid_identifier_starting_with_number(self, wp_benchmark):
        """Test that identifiers starting with numbers raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            wp_benchmark._quote_identifier("123table")

    def test_invalid_identifier_with_special_chars(self, wp_benchmark):
        """Test that identifiers with special characters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            wp_benchmark._quote_identifier("table-name")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            wp_benchmark._quote_identifier("table.name")


class TestReplacePlaceholders:
    """Tests for placeholder replacement in SQL."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_file_path_placeholder(self, wp_benchmark):
        """Test replacing {file_path} placeholder."""
        sql = "COPY table FROM '{file_path}/data.csv'"
        result = wp_benchmark._replace_placeholders(sql)

        assert "{file_path}" not in result
        assert "write_primitives_auxiliary" in result

    def test_no_placeholder(self, wp_benchmark):
        """Test SQL without placeholders passes through unchanged."""
        sql = "SELECT * FROM orders"
        result = wp_benchmark._replace_placeholders(sql)
        assert result == sql


class TestTableExists:
    """Tests for table existence checking."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_table_exists_success(self, wp_benchmark):
        """Test that existing table returns True."""
        mock_conn = Mock()
        mock_conn.execute.return_value = None  # Query succeeds

        result = wp_benchmark._table_exists(mock_conn, "orders")
        assert result is True

    def test_table_does_not_exist(self, wp_benchmark):
        """Test that nonexistent table returns False."""
        mock_conn = Mock()
        mock_conn.execute.side_effect = Exception("Table 'test' does not exist")

        result = wp_benchmark._table_exists(mock_conn, "test")
        assert result is False

    def test_table_exists_invalid_name(self, wp_benchmark):
        """Test that invalid table name returns False."""
        mock_conn = Mock()

        result = wp_benchmark._table_exists(mock_conn, "invalid;DROP TABLE")
        assert result is False
        mock_conn.execute.assert_not_called()

    def test_table_exists_unexpected_error(self, wp_benchmark):
        """Test that unexpected errors return False."""
        mock_conn = Mock()
        mock_conn.execute.side_effect = Exception("Connection timeout")

        result = wp_benchmark._table_exists(mock_conn, "orders")
        assert result is False


class TestOperationManagement:
    """Tests for operation management methods."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_get_operation_categories(self, wp_benchmark):
        """Test getting operation categories."""
        categories = wp_benchmark.get_operation_categories()

        assert isinstance(categories, list)
        assert len(categories) > 0
        # Common categories
        assert "insert" in categories or "INSERT" in [c.upper() for c in categories]

    def test_get_all_operations(self, wp_benchmark):
        """Test getting all operations."""
        operations = wp_benchmark.get_all_operations()

        assert isinstance(operations, dict)
        assert len(operations) > 0

    def test_get_operation(self, wp_benchmark):
        """Test getting a specific operation."""
        operations = wp_benchmark.get_all_operations()
        if operations:
            first_op_id = next(iter(operations.keys()))
            operation = wp_benchmark.get_operation(first_op_id)
            assert operation is not None
            assert hasattr(operation, "write_sql")

    def test_get_operation_invalid_id(self, wp_benchmark):
        """Test getting operation with invalid ID raises error."""
        with pytest.raises((ValueError, KeyError)):
            wp_benchmark.get_operation("NONEXISTENT_OPERATION_12345")

    def test_get_queries(self, wp_benchmark):
        """Test getting all queries."""
        queries = wp_benchmark.get_queries()

        assert isinstance(queries, dict)
        # Each value should be SQL string
        for sql in queries.values():
            assert isinstance(sql, str)

    def test_get_queries_by_category(self, wp_benchmark):
        """Test getting queries by category."""
        categories = wp_benchmark.get_operation_categories()
        if categories:
            category = categories[0]
            queries = wp_benchmark.get_queries_by_category(category)
            assert isinstance(queries, dict)


class TestBenchmarkInfo:
    """Tests for benchmark information methods."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_get_benchmark_info(self, wp_benchmark):
        """Test getting benchmark information."""
        info = wp_benchmark.get_benchmark_info()

        assert isinstance(info, dict)
        assert "name" in info
        assert "version" in info
        assert "scale_factor" in info
        assert "total_operations" in info
        assert "categories" in info
        assert "data_source" in info
        assert info["data_source"] == "tpch"

    def test_get_schema(self, wp_benchmark):
        """Test getting schema definitions."""
        schema = wp_benchmark.get_schema()

        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_get_create_tables_sql(self, wp_benchmark):
        """Test getting CREATE TABLE SQL."""
        sql = wp_benchmark.get_create_tables_sql()

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql
        # Should include both TPC-H and staging tables
        assert "Write Primitives Staging Tables" in sql

    def test_get_create_tables_sql_with_tuning(self, wp_benchmark):
        """Test getting CREATE TABLE SQL with tuning config."""
        mock_tuning = Mock()
        mock_tuning.primary_keys = Mock(enabled=True)
        mock_tuning.foreign_keys = Mock(enabled=False)

        sql = wp_benchmark.get_create_tables_sql(tuning_config=mock_tuning)

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

    def test_get_query(self, wp_benchmark):
        """Test getting a single query."""
        operations = wp_benchmark.get_all_operations()
        if operations:
            first_op_id = next(iter(operations.keys()))
            query = wp_benchmark.get_query(first_op_id)
            assert isinstance(query, str)


class TestExecuteOperation:
    """Tests for execute_operation method."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_execute_operation_no_connection(self, wp_benchmark):
        """Test that None connection raises ValueError."""
        with pytest.raises(ValueError, match="Connection is None"):
            wp_benchmark.execute_operation("INSERT_001", None)

    def test_execute_operation_invalid_connection(self, wp_benchmark):
        """Test that invalid connection type raises ValueError."""
        invalid_conn = "not a connection"
        with pytest.raises(ValueError, match="Invalid connection type"):
            wp_benchmark.execute_operation("INSERT_001", invalid_conn)

    def test_execute_operation_skips_unsupported_datafusion_category(self, wp_benchmark, monkeypatch):
        """DataFusion should mark unsupported operation categories as SKIPPED via platform_overrides."""
        mock_conn = Mock()
        mock_conn.execute = Mock()

        monkeypatch.setattr(wp_benchmark, "is_setup", lambda conn: True)
        result = wp_benchmark.execute_operation("update_single_row_pk", mock_conn, platform_key="datafusion")

        assert result.status == "SKIPPED"
        assert result.success is True
        assert result.validation_passed is True
        mock_conn.execute.assert_not_called()

    def test_execute_operation_uses_platform_override_when_available(self, wp_benchmark, monkeypatch):
        """Platform override SQL should be used instead of base write_sql."""
        operation = wp_benchmark.get_operation("insert_on_conflict_ignore")

        # DuckDB override is present in catalog for this operation.
        assert operation.platform_overrides.get("duckdb")

        class _Result:
            rowcount = 1

            def fetchall(self):
                return [(1,)]

        sql_calls: list[str] = []

        def _execute(sql):
            sql_calls.append(sql)
            return _Result()

        mock_conn = Mock()
        mock_conn.execute = _execute
        monkeypatch.setattr(wp_benchmark, "is_setup", lambda conn: True)

        result = wp_benchmark.execute_operation("insert_on_conflict_ignore", mock_conn, platform_key="duckdb")

        assert result.status == "SUCCESS"
        assert any("INSERT OR IGNORE" in sql for sql in sql_calls)


class TestRunBenchmark:
    """Tests for run_benchmark method."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_run_benchmark_with_mock(self, wp_benchmark):
        """Test run_benchmark with mocked execute_operation."""
        mock_conn = Mock()
        mock_conn.execute.return_value = Mock(rowcount=10)

        # Get a real operation ID from the benchmark
        operations = wp_benchmark.get_all_operations()
        real_op_id = next(iter(operations.keys()))

        # Mock the staging tables as already set up
        with patch.object(wp_benchmark, "is_setup", return_value=True):
            with patch.object(wp_benchmark, "execute_operation") as mock_execute:
                # Create a successful result
                mock_execute.return_value = OperationResult(
                    operation_id=real_op_id,
                    success=True,
                    write_duration_ms=10.0,
                    rows_affected=10,
                    validation_duration_ms=5.0,
                    validation_passed=True,
                    validation_results=[],
                    cleanup_duration_ms=2.0,
                    cleanup_success=True,
                )

                results = wp_benchmark.run_benchmark(mock_conn, operation_ids=[real_op_id])

                assert len(results) == 1
                assert results[0].success is True

    def test_run_benchmark_by_category(self, wp_benchmark):
        """Test run_benchmark filtered by category."""
        mock_conn = Mock()
        mock_conn.execute.return_value = Mock(rowcount=10)

        with patch.object(wp_benchmark, "is_setup", return_value=True):
            with patch.object(wp_benchmark, "execute_operation") as mock_execute:
                mock_execute.return_value = OperationResult(
                    operation_id="cat_op",
                    success=True,
                    write_duration_ms=10.0,
                    rows_affected=10,
                    validation_duration_ms=5.0,
                    validation_passed=True,
                    validation_results=[],
                    cleanup_duration_ms=2.0,
                    cleanup_success=True,
                )

                categories = wp_benchmark.get_operation_categories()
                if categories:
                    results = wp_benchmark.run_benchmark(mock_conn, categories=[categories[0]])
                    assert isinstance(results, list)


class TestSetupAndTeardown:
    """Tests for setup and teardown methods."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance for testing."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_teardown_drops_tables(self, wp_benchmark):
        """Test that teardown drops staging tables."""
        mock_conn = Mock()

        wp_benchmark.teardown(mock_conn)

        # Should have called execute for each staging table
        assert mock_conn.execute.call_count > 0
        # Check some DROP TABLE calls were made
        drop_calls = [call for call in mock_conn.execute.call_args_list if "DROP TABLE" in str(call)]
        assert len(drop_calls) > 0

    def test_is_setup_false_when_tables_missing(self, wp_benchmark):
        """Test is_setup returns False when tables are missing."""
        mock_conn = Mock()
        mock_conn.execute.side_effect = Exception("Table not found")

        result = wp_benchmark.is_setup(mock_conn)
        assert result is False

    def test_is_setup_false_when_tables_empty(self, wp_benchmark):
        """Test is_setup returns False when tables are empty."""
        mock_conn = Mock()
        # Return 0 rows
        mock_conn.execute.return_value.fetchone.return_value = (0,)

        result = wp_benchmark.is_setup(mock_conn)
        assert result is False

    def test_acquire_setup_lock_skips_lock_table_for_datafusion(self, wp_benchmark):
        """DataFusion setup lock should bypass SQL lock-table DDL/PK usage."""
        mock_conn = Mock()

        assert wp_benchmark._acquire_setup_lock(mock_conn, dialect="datafusion") is True
        mock_conn.execute.assert_not_called()

    def test_setup_uses_datafusion_dialect_for_staging_tables(self, wp_benchmark, monkeypatch):
        """setup() should request DataFusion dialect staging DDL when dialect='datafusion'."""

        class _Result:
            def __init__(self, row=(1,)):
                self._row = row

            def fetchone(self):
                return self._row

        mock_conn = Mock()
        mock_conn.execute.return_value = _Result((1,))
        monkeypatch.setattr(wp_benchmark, "_table_exists", lambda conn, table_name: False)

        requested_dialects: list[str] = []

        def _fake_create_sql(table_name, dialect="standard", if_not_exists=False):
            requested_dialects.append(dialect)
            if_not_exists_clause = " IF NOT EXISTS" if if_not_exists else ""
            return f"CREATE TABLE{if_not_exists_clause} {table_name} (id INTEGER)"

        monkeypatch.setattr("benchbox.core.write_primitives.benchmark.get_create_table_sql", _fake_create_sql)

        result = wp_benchmark.setup(mock_conn, force=False, dialect="datafusion")

        assert result["success"] is True
        assert requested_dialects
        assert set(requested_dialects) == {"datafusion"}


class TestCleanupAuxiliaryFiles:
    """Tests for auxiliary file cleanup."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create a benchmark instance with a real output dir."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_cleanup_removes_directory(self, wp_benchmark, tmp_path):
        """Test that cleanup_auxiliary_files removes the directory."""
        # Create the auxiliary directory
        aux_dir = tmp_path / "write_primitives_auxiliary"
        aux_dir.mkdir()
        (aux_dir / "test.csv").write_text("data")

        # Set up data generator's files_dir
        wp_benchmark.data_generator.files_dir = aux_dir

        wp_benchmark.cleanup_auxiliary_files()

        assert not aux_dir.exists()

    def test_cleanup_handles_nonexistent_dir(self, wp_benchmark, tmp_path):
        """Test that cleanup handles nonexistent directory gracefully."""
        aux_dir = tmp_path / "nonexistent"
        wp_benchmark.data_generator.files_dir = aux_dir

        # Should not raise an error
        wp_benchmark.cleanup_auxiliary_files()


class TestDataFrameSqlParity:
    """Tests for DataFrame/SQL parity behavior in Write Primitives execution."""

    @pytest.fixture
    def wp_benchmark(self, tmp_path):
        """Create benchmark instance for parity tests."""
        return WritePrimitivesBenchmark(output_dir=tmp_path)

    def test_dataframe_workload_matches_sql_status_mapping_for_same_operations(self, wp_benchmark, monkeypatch):
        """DataFrame workload should map operation outcomes identically to SQL runner semantics."""
        operation_ids = ["insert_single_row", "update_single_row_pk", "ddl_create_table_simple"]

        monkeypatch.setattr(
            wp_benchmark,
            "_select_dataframe_operation_ids",
            lambda query_filter=None: operation_ids,  # noqa: ARG005
        )

        # Avoid touching real DuckDB/data loading in this unit test.
        monkeypatch.setattr("benchbox.platforms.duckdb.DuckDBAdapter.create_connection", lambda self, **_: object())
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.create_schema",
            lambda self, benchmark, connection: 0.0,  # noqa: ARG005
        )
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.load_data",
            lambda self, benchmark, connection, data_dir: ({}, 0.0, None),  # noqa: ARG005
        )
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.close_connection",
            lambda self, connection: None,  # noqa: ARG005
        )

        results_by_id = {
            "insert_single_row": OperationResult(
                operation_id="insert_single_row",
                success=True,
                write_duration_ms=1.0,
                rows_affected=1,
                validation_duration_ms=0.1,
                validation_passed=True,
                validation_results=[],
                cleanup_duration_ms=0.1,
                cleanup_success=True,
            ),
            "update_single_row_pk": OperationResult(
                operation_id="update_single_row_pk",
                success=False,
                write_duration_ms=2.0,
                rows_affected=0,
                validation_duration_ms=0.1,
                validation_passed=False,
                validation_results=[],
                cleanup_duration_ms=0.0,
                cleanup_success=False,
                error="forced update failure",
            ),
            "ddl_create_table_simple": OperationResult(
                operation_id="ddl_create_table_simple",
                success=True,
                write_duration_ms=0.5,
                rows_affected=-1,
                validation_duration_ms=0.1,
                validation_passed=False,
                validation_results=[],
                cleanup_duration_ms=0.0,
                cleanup_success=True,
            ),
        }

        monkeypatch.setattr(
            wp_benchmark,
            "execute_operation",
            lambda op_id, connection: results_by_id[op_id],  # noqa: ARG005
        )

        sql_results = wp_benchmark.run_benchmark(connection=object(), operation_ids=operation_ids)
        expected_status = {
            result.operation_id: ("SUCCESS" if result.success and result.validation_passed else "FAILED")
            for result in sql_results
        }

        class DummyAdapter:
            platform_name = "polars-df"

        dataframe_rows = wp_benchmark.execute_dataframe_workload(
            ctx=None,
            adapter=DummyAdapter(),
            benchmark_config=SimpleNamespace(options={}),
            query_filter=None,
            monitor=None,
            run_options=None,
        )

        # Default parity shape: 1 warmup + 3 measurements for each operation ID.
        assert len(dataframe_rows) == len(operation_ids) * 4

        seen_status: dict[str, set[str]] = {op_id: set() for op_id in operation_ids}
        for row in dataframe_rows:
            query_id = row["query_id"]
            assert query_id in expected_status
            seen_status[query_id].add(row["status"])
            assert row["run_type"] in {"warmup", "measurement"}
            assert row["iteration"] in {0, 1, 2, 3}

        for op_id in operation_ids:
            assert seen_status[op_id] == {expected_status[op_id]}

    def test_dataframe_workload_query_filter_keeps_sql_subset(self, wp_benchmark, monkeypatch):
        """Query filter should constrain DataFrame parity execution to SQL-equivalent subset."""
        monkeypatch.setattr("benchbox.platforms.duckdb.DuckDBAdapter.create_connection", lambda self, **_: object())
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.create_schema",
            lambda self, benchmark, connection: 0.0,  # noqa: ARG005
        )
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.load_data",
            lambda self, benchmark, connection, data_dir: ({}, 0.0, None),  # noqa: ARG005
        )
        monkeypatch.setattr(
            "benchbox.platforms.duckdb.DuckDBAdapter.close_connection",
            lambda self, connection: None,  # noqa: ARG005
        )

        monkeypatch.setattr(
            wp_benchmark,
            "execute_operation",
            lambda op_id, connection: OperationResult(  # noqa: ARG005
                operation_id=op_id,
                success=True,
                write_duration_ms=1.0,
                rows_affected=1,
                validation_duration_ms=0.1,
                validation_passed=True,
                validation_results=[],
                cleanup_duration_ms=0.1,
                cleanup_success=True,
            ),
        )

        class DummyAdapter:
            platform_name = "polars-df"

        rows = wp_benchmark.execute_dataframe_workload(
            ctx=None,
            adapter=DummyAdapter(),
            benchmark_config=SimpleNamespace(options={}),
            query_filter={"INSERT_SINGLE_ROW"},
            monitor=None,
            run_options=None,
        )

        assert rows
        assert {row["query_id"] for row in rows} == {"insert_single_row"}


# ---------------------------------------------------------------------------
# _check_validation_query tests (fast - no I/O, pure logic)
# ---------------------------------------------------------------------------


class TestCheckValidationQuery:
    """Tests for _check_validation_query helper."""

    pytestmark = [pytest.mark.unit, pytest.mark.fast]

    def _make_query(
        self,
        expected_rows=None,
        expected_rows_min=None,
        expected_rows_max=None,
        expected_value_min=None,
        expected_value_max=None,
    ):
        return SimpleNamespace(
            expected_rows=expected_rows,
            expected_rows_min=expected_rows_min,
            expected_rows_max=expected_rows_max,
            expected_value_min=expected_value_min,
            expected_value_max=expected_value_max,
        )

    def test_exact_match_passes(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        assert _check_validation_query(self._make_query(expected_rows=500), actual_rows=500) is True

    def test_exact_mismatch_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        assert _check_validation_query(self._make_query(expected_rows=500), actual_rows=499) is False

    def test_min_max_within_range_passes(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_rows_min=10, expected_rows_max=20)
        assert _check_validation_query(q, actual_rows=15) is True

    def test_min_max_below_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_rows_min=10, expected_rows_max=20)
        assert _check_validation_query(q, actual_rows=9) is False

    def test_min_max_above_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_rows_min=10, expected_rows_max=20)
        assert _check_validation_query(q, actual_rows=21) is False

    def test_only_min_no_max_passes_above_min(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_rows_min=5)
        assert _check_validation_query(q, actual_rows=100) is True

    def test_only_max_no_min_passes_below_max(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_rows_max=100)
        assert _check_validation_query(q, actual_rows=50) is True

    def test_no_constraints_always_passes(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query()
        assert _check_validation_query(q, actual_rows=999) is True

    def test_value_bounds_within_range_passes(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=14000, expected_value_max=16000)
        assert _check_validation_query(q, actual_rows=1, val_result=[(14836.89,)]) is True

    def test_value_bounds_below_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=14000, expected_value_max=16000)
        assert _check_validation_query(q, actual_rows=1, val_result=[(0.0,)]) is False

    def test_value_bounds_above_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=14000, expected_value_max=16000)
        assert _check_validation_query(q, actual_rows=1, val_result=[(50000.0,)]) is False

    def test_value_bounds_no_rows_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=14000, expected_value_max=16000)
        assert _check_validation_query(q, actual_rows=0, val_result=[]) is False

    def test_value_bounds_non_numeric_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=14000, expected_value_max=16000)
        assert _check_validation_query(q, actual_rows=1, val_result=[("not a number",)]) is False

    def test_value_bounds_integer_scalar_passes(self):
        """Integer scalars (e.g. topk frequent_count = 7) coerce to float for the range check."""
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=6, expected_value_max=8)
        assert _check_validation_query(q, actual_rows=1, val_result=[(7,)]) is True

    # w4 regression: every row of expected_value_* must be in range, not just [0][0].

    def test_value_bounds_multi_row_all_in_range_passes(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=3, val_result=[(11,), (15,), (19,)]) is True

    def test_value_bounds_multi_row_first_out_of_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=3, val_result=[(0,), (15,), (19,)]) is False

    def test_value_bounds_multi_row_middle_out_of_range_fails(self):
        """Pre-w4 behavior would have passed because only [0][0] was inspected;
        post-w4 we walk every row and fail on the first out-of-range value."""
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=3, val_result=[(11,), (999,), (19,)]) is False

    def test_value_bounds_multi_row_last_out_of_range_fails(self):
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=3, val_result=[(11,), (15,), (0,)]) is False

    def test_value_bounds_empty_result_fails(self):
        """Empty result (after the bounds branch is taken) must fail rather than
        silently pass — there's nothing to validate."""
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=0, val_result=None) is False

    def test_value_bounds_empty_row_fails(self):
        """A row with no columns can't be coerced to a scalar; treat as failure."""
        from benchbox.core.write_primitives.benchmark import _check_validation_query

        q = self._make_query(expected_value_min=10, expected_value_max=20)
        assert _check_validation_query(q, actual_rows=2, val_result=[(15,), ()]) is False


# ============================================================================
# Fast-lane coverage tests (pytest.mark.fast)
# ============================================================================


pytestmark_fast = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture()
def fast_bench(tmp_path):
    """WritePrimitivesBenchmark with mocked data generator."""
    with patch("benchbox.core.write_primitives.benchmark.WritePrimitivesDataGenerator"):
        bench = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
    return bench


@pytest.fixture()
def fast_conn():
    """Mock database connection."""
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    conn.execute.return_value.fetchone.return_value = (100,)
    return conn


# ---------------------------------------------------------------------------
# generate_data (lines 192-199)
# ---------------------------------------------------------------------------


def test_generate_data_calls_generator_and_returns_list(fast_bench):
    fast_bench.data_generator.generate.return_value = {
        "orders": Path("/tmp/orders.parquet"),
        "lineitem": Path("/tmp/lineitem.parquet"),
    }
    result = fast_bench.generate_data()
    fast_bench.data_generator.generate.assert_called_once()
    assert len(result) == 2


# ---------------------------------------------------------------------------
# setup() success path (lines 553-627)
# ---------------------------------------------------------------------------


def test_setup_success_creates_and_populates_tables(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "_acquire_setup_lock", return_value=True),
        patch.object(fast_bench, "_release_setup_lock"),
        patch.object(fast_bench, "_table_exists", return_value=False),
        patch.object(fast_bench, "_populate_staging_tables", return_value={}),
    ):
        result = fast_bench.setup(fast_conn)

    assert result["success"] is True
    assert "tables_created" in result


def test_setup_lock_timeout_raises_runtime_error(fast_bench, fast_conn):
    with patch.object(fast_bench, "_acquire_setup_lock", return_value=False):
        with pytest.raises(RuntimeError, match="Could not acquire setup lock"):
            fast_bench.setup(fast_conn)


def test_setup_force_drops_existing_tables(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "_acquire_setup_lock", return_value=True),
        patch.object(fast_bench, "_release_setup_lock"),
        patch.object(fast_bench, "_table_exists", return_value=True),
        patch.object(fast_bench, "_populate_staging_tables", return_value={}),
    ):
        result = fast_bench.setup(fast_conn, force=True)

    assert result["success"] is True
    # DROP TABLE IF EXISTS calls should have been made
    drop_calls = [str(c) for c in fast_conn.execute.call_args_list if "DROP" in str(c)]
    assert len(drop_calls) > 0


def test_setup_missing_required_table_raises(fast_bench):
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("table not found")
    with pytest.raises(RuntimeError, match="Required TPC-H table"):
        fast_bench.setup(conn)


def test_setup_datafusion_dialect_skips_lock(fast_bench, fast_conn):
    """DataFusion dialect bypasses lock (returns True immediately)."""
    with (
        patch.object(fast_bench, "_table_exists", return_value=True),
        patch.object(fast_bench, "_populate_staging_tables", return_value={}),
    ):
        result = fast_bench.setup(fast_conn, dialect="datafusion")

    assert result["success"] is True


# ---------------------------------------------------------------------------
# teardown() (lines 637-647)
# ---------------------------------------------------------------------------


def test_teardown_drops_all_tables(fast_bench, fast_conn):
    fast_bench.teardown(fast_conn)
    drop_calls = [str(c) for c in fast_conn.execute.call_args_list if "DROP" in str(c)]
    assert len(drop_calls) > 0


def test_teardown_ignores_drop_errors(fast_bench):
    conn = MagicMock()
    conn.execute.side_effect = Exception("table does not exist")
    fast_bench.teardown(conn)  # should not raise


# ---------------------------------------------------------------------------
# reset_staging_tables() (lines 658-666)
# ---------------------------------------------------------------------------


def test_reset_staging_tables_truncates_and_repopulates(fast_bench, fast_conn):
    with patch.object(fast_bench, "_populate_staging_tables") as mock_pop:
        fast_bench.reset(fast_conn)
    mock_pop.assert_called_once()
    truncate_calls = [str(c) for c in fast_conn.execute.call_args_list if "TRUNCATE" in str(c)]
    assert len(truncate_calls) > 0


# ---------------------------------------------------------------------------
# execute_operation() (lines 968-1048)
# ---------------------------------------------------------------------------


def test_execute_operation_success_path(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "is_setup", return_value=True),
        patch.object(fast_bench, "_get_effective_write_sql", return_value=("SELECT 1", None)),
        patch.object(fast_bench, "_replace_placeholders", side_effect=lambda s: s),
        patch.object(fast_bench, "_extract_rows_affected", return_value=3),
        patch.object(fast_bench, "_run_operation_validation", return_value=(True, [], 0.0)),
        patch.object(fast_bench, "_run_operation_cleanup", return_value=(True, None, 0.0)),
    ):
        result = fast_bench.execute_operation("insert_single_row", fast_conn)

    assert result.success is True
    assert result.status == "SUCCESS"
    assert result.rows_affected == 3


def test_execute_operation_skipped_when_skip_reason(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "is_setup", return_value=True),
        patch.object(fast_bench, "_get_effective_write_sql", return_value=(None, "platform not supported")),
    ):
        result = fast_bench.execute_operation("insert_single_row", fast_conn)

    assert result.success is True
    assert result.status == "SKIPPED"


def test_execute_operation_error_returns_failed(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "is_setup", return_value=True),
        patch.object(fast_bench, "_get_effective_write_sql", return_value=("SELECT 1", None)),
        patch.object(fast_bench, "_replace_placeholders", side_effect=RuntimeError("db error")),
    ):
        result = fast_bench.execute_operation("insert_single_row", fast_conn)

    assert result.success is False
    assert "db error" in (result.error or "")


def test_execute_operation_invalid_connection_raises(fast_bench):
    with pytest.raises(ValueError, match="Invalid connection type"):
        fast_bench.execute_operation("insert_single_row", object())


def test_execute_operation_none_connection_raises(fast_bench):
    with pytest.raises(ValueError, match="Connection is None"):
        fast_bench.execute_operation("insert_single_row", None)


def test_execute_operation_auto_setup_when_not_initialized(fast_bench, fast_conn):
    """When requires_setup=True and is_setup=False, calls setup() automatically."""
    with (
        patch.object(fast_bench, "is_setup", return_value=False),
        patch.object(fast_bench, "setup") as mock_setup,
        patch.object(fast_bench, "_get_effective_write_sql", return_value=("SELECT 1", None)),
        patch.object(fast_bench, "_replace_placeholders", side_effect=lambda s: s),
        patch.object(fast_bench, "_extract_rows_affected", return_value=0),
        patch.object(fast_bench, "_run_operation_validation", return_value=(True, [], 0.0)),
        patch.object(fast_bench, "_run_operation_cleanup", return_value=(True, None, 0.0)),
    ):
        fast_bench.execute_operation("insert_single_row", fast_conn)

    mock_setup.assert_called_once()


# ---------------------------------------------------------------------------
# run_benchmark() (lines 1147-1171)
# ---------------------------------------------------------------------------


def test_run_benchmark_by_operation_ids(fast_bench, fast_conn):
    mock_result = OperationResult(
        operation_id="insert_single_row",
        success=True,
        write_duration_ms=10.0,
        rows_affected=1,
        validation_duration_ms=5.0,
        validation_passed=True,
        validation_results=[],
        cleanup_duration_ms=0.0,
        cleanup_success=True,
    )
    with patch.object(fast_bench, "execute_operation", return_value=mock_result):
        results = fast_bench.run_benchmark(fast_conn, operation_ids=["insert_single_row"])

    assert len(results) == 1
    assert results[0].success is True


def test_run_benchmark_by_category(fast_bench, fast_conn):
    mock_result = OperationResult(
        operation_id="op1",
        success=True,
        write_duration_ms=1.0,
        rows_affected=0,
        validation_duration_ms=0.0,
        validation_passed=True,
        validation_results=[],
        cleanup_duration_ms=0.0,
        cleanup_success=True,
    )
    with patch.object(fast_bench, "execute_operation", return_value=mock_result):
        results = fast_bench.run_benchmark(fast_conn, categories=["insert"])

    assert len(results) > 0


def test_run_benchmark_all_operations(fast_bench, fast_conn):
    mock_result = OperationResult(
        operation_id="op1",
        success=False,
        write_duration_ms=0.0,
        rows_affected=0,
        validation_duration_ms=0.0,
        validation_passed=False,
        validation_results=[],
        cleanup_duration_ms=0.0,
        cleanup_success=False,
        error="test error",
    )
    with patch.object(fast_bench, "execute_operation", return_value=mock_result):
        results = fast_bench.run_benchmark(fast_conn)

    assert len(results) > 0


# ---------------------------------------------------------------------------
# _populate_staging_tables() (lines 475-519)
# ---------------------------------------------------------------------------


def test_populate_staging_tables_already_populated(fast_bench):
    """Table with existing rows is skipped (not repopulated)."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (500,)  # current_count > 0

    reset_map = {"update_ops_orders": "orders"}
    result = fast_bench._populate_staging_tables(conn, reset_map)

    assert result["update_ops_orders"] == 500


def test_populate_staging_tables_empty_populates(fast_bench):
    """Empty table is populated from source."""
    fetch_results = [
        (0,),  # current_count = 0 → needs population
        (1000,),  # source_count = 1000 → has data
        (1000,),  # after population count
    ]
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = fetch_results

    with patch.object(fast_bench, "_get_population_sql", return_value="INSERT INTO ..."):
        result = fast_bench._populate_staging_tables(conn, {"update_ops_orders": "orders"})

    assert result["update_ops_orders"] == 1000


def test_populate_staging_tables_optional_missing_source(fast_bench):
    """Optional delete_ops_supplier skips when source doesn't exist."""
    conn = MagicMock()

    def execute_side(sql):
        result = MagicMock()
        if "delete_ops_supplier" in sql and "COUNT" in sql:
            result.fetchone.return_value = (0,)
        elif "COUNT" in sql:
            raise RuntimeError("table not found")  # source check fails
        else:
            result.fetchone.return_value = (0,)
        return result

    conn.execute.side_effect = execute_side

    result = fast_bench._populate_staging_tables(conn, {"delete_ops_supplier": "supplier"})
    assert result["delete_ops_supplier"] == 0


def test_populate_staging_tables_required_empty_source_raises(fast_bench):
    """Required table with empty source raises RuntimeError."""
    fetch_results = [
        (0,),  # current_count = 0
        (0,),  # source_count = 0 → empty!
    ]
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = fetch_results

    with pytest.raises(RuntimeError, match="Source table .* is empty"):
        fast_bench._populate_staging_tables(conn, {"update_ops_orders": "orders"})


# ---------------------------------------------------------------------------
# reset() exception in TRUNCATE handler (lines 711-712)
# ---------------------------------------------------------------------------


def test_reset_truncate_exception_is_silenced(fast_bench):
    conn = MagicMock()
    conn.execute.side_effect = Exception("TRUNCATE not supported")

    with patch.object(fast_bench, "_populate_staging_tables"):
        fast_bench.reset(conn)  # should not raise


# ---------------------------------------------------------------------------
# is_setup() (lines 727-747)
# ---------------------------------------------------------------------------


def test_is_setup_returns_true_when_all_tables_populated(fast_bench):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (100,)

    assert fast_bench.is_setup(conn) is True


def test_is_setup_returns_false_when_table_empty(fast_bench):
    conn = MagicMock()
    # First call returns 0 rows → table empty
    conn.execute.return_value.fetchone.return_value = (0,)

    assert fast_bench.is_setup(conn) is False


def test_is_setup_returns_false_on_exception(fast_bench):
    conn = MagicMock()
    conn.execute.side_effect = Exception("table not found")

    assert fast_bench.is_setup(conn) is False


# ---------------------------------------------------------------------------
# _replace_placeholders() with {file_path} (lines 768-783)
# ---------------------------------------------------------------------------


def test_replace_placeholders_substitutes_file_path(fast_bench, tmp_path):
    sql = "COPY INTO table FROM '{file_path}/data.parquet'"
    result = fast_bench._replace_placeholders(sql)
    assert "{file_path}" not in result
    assert "write_primitives_auxiliary" in result


def test_replace_placeholders_no_placeholder_unchanged(fast_bench):
    sql = "SELECT 1"
    result = fast_bench._replace_placeholders(sql)
    assert result == sql


def test_replace_placeholders_no_output_dir_uses_empty(fast_bench):
    fast_bench._output_dir = None
    sql = "COPY INTO t FROM '{file_path}/x'"
    result = fast_bench._replace_placeholders(sql)
    assert "{file_path}" not in result


# ---------------------------------------------------------------------------
# get_schema() (lines 836-863)
# ---------------------------------------------------------------------------


def test_get_schema_returns_normalized_dict(fast_bench):
    schema = fast_bench.get_schema()
    assert isinstance(schema, dict)
    assert len(schema) > 0
    # Staging tables should be present
    for table_name, table_def in schema.items():
        assert "columns" in table_def or isinstance(table_def, dict)


# ---------------------------------------------------------------------------
# get_benchmark_info() (line 878 etc.)
# ---------------------------------------------------------------------------


def test_get_benchmark_info_returns_metadata(fast_bench):
    info = fast_bench.get_benchmark_info()
    assert info["name"] == "Write Primitives Benchmark"
    assert "scale_factor" in info


# ---------------------------------------------------------------------------
# get_query() / get_queries() / get_queries_by_category() (lines 915-940)
# ---------------------------------------------------------------------------


def test_get_query_returns_sql_string(fast_bench):
    result = fast_bench.get_query("insert_single_row")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_queries_returns_all(fast_bench):
    queries = fast_bench.get_queries()
    assert isinstance(queries, dict)
    assert len(queries) > 0


def test_get_queries_by_category_returns_subset(fast_bench):
    queries = fast_bench.get_queries_by_category("insert")
    assert isinstance(queries, dict)
    assert len(queries) > 0


# ---------------------------------------------------------------------------
# execute_operation() auto-setup failure (lines 986-987)
# ---------------------------------------------------------------------------


def test_execute_operation_auto_setup_failure_raises_runtime(fast_bench, fast_conn):
    with (
        patch.object(fast_bench, "is_setup", return_value=False),
        patch.object(fast_bench, "setup", side_effect=RuntimeError("setup failed")),
    ):
        with pytest.raises(RuntimeError, match="Failed to initialize staging tables"):
            fast_bench.execute_operation("insert_single_row", fast_conn)


# ---------------------------------------------------------------------------
# _extract_rows_affected() (lines 1063-1072)
# ---------------------------------------------------------------------------


def test_extract_rows_affected_from_rowcount(fast_bench):
    result = MagicMock()
    result.rowcount = 10
    assert fast_bench._extract_rows_affected(result, "test_op") == 10


def test_extract_rows_affected_no_rowcount_returns_minus_one(fast_bench):
    result = MagicMock(spec=[])  # no rowcount attribute
    assert fast_bench._extract_rows_affected(result, "test_op") == -1


def test_extract_rows_affected_minus_one_passthrough(fast_bench):
    result = MagicMock()
    result.rowcount = -1
    assert fast_bench._extract_rows_affected(result, "test_op") == -1


# ---------------------------------------------------------------------------
# _run_operation_validation() (lines 1073-1101)
# ---------------------------------------------------------------------------


def test_run_operation_validation_passes(fast_bench, fast_conn):
    from benchbox.core.write_primitives.catalog.loader import ValidationQuery

    val_q = ValidationQuery(id="v1", sql="SELECT 1", expected_rows=1)
    operation = SimpleNamespace(validation_queries=[val_q])
    fast_conn.execute.return_value.fetchall.return_value = [("1",)]

    passed, results, duration_ms = fast_bench._run_operation_validation(operation, fast_conn, "test_op")

    assert passed is True
    assert len(results) == 1
    assert results[0]["query_id"] == "v1"


def test_run_operation_validation_fails_wrong_count(fast_bench, fast_conn):
    from benchbox.core.write_primitives.catalog.loader import ValidationQuery

    val_q = ValidationQuery(id="v1", sql="SELECT 1", expected_rows=5)
    operation = SimpleNamespace(validation_queries=[val_q])
    fast_conn.execute.return_value.fetchall.return_value = [("1",)]  # only 1 row

    passed, results, _ = fast_bench._run_operation_validation(operation, fast_conn, "test_op")

    assert passed is False


def test_run_operation_validation_no_queries(fast_bench, fast_conn):
    operation = SimpleNamespace(validation_queries=[])

    passed, results, _ = fast_bench._run_operation_validation(operation, fast_conn, "test_op")

    assert passed is True
    assert results == []


# ---------------------------------------------------------------------------
# _run_operation_cleanup() (lines 1103-1129)
# ---------------------------------------------------------------------------


def test_run_operation_cleanup_executes_sql(fast_bench, fast_conn):
    operation = SimpleNamespace(cleanup_sql="DELETE FROM t WHERE 1=0")

    success, warning, _ = fast_bench._run_operation_cleanup(operation, fast_conn, "test_op")

    assert success is True
    assert warning is None
    fast_conn.execute.assert_called_with("DELETE FROM t WHERE 1=0")


def test_run_operation_cleanup_no_sql(fast_bench, fast_conn):
    operation = SimpleNamespace(cleanup_sql=None)

    success, warning, _ = fast_bench._run_operation_cleanup(operation, fast_conn, "test_op")

    assert success is True
    assert warning is None


def test_run_operation_cleanup_error_sets_warning(fast_bench):
    conn = MagicMock()
    conn.execute.side_effect = Exception("cleanup failed")
    operation = SimpleNamespace(cleanup_sql="DELETE FROM t")

    success, warning, _ = fast_bench._run_operation_cleanup(operation, conn, "test_op")

    assert success is False
    assert warning is not None
    assert "cleanup failed" in warning


# ---------------------------------------------------------------------------
# _get_effective_write_sql() (lines 379-390)
# ---------------------------------------------------------------------------


def test_get_effective_write_sql_uses_sql_override(fast_bench):
    operation = SimpleNamespace(write_sql="SELECT 1", platform_overrides={}, id="op1")
    sql, skip = fast_bench._get_effective_write_sql(operation, sql_override="OVERRIDE SQL")
    assert sql == "OVERRIDE SQL"
    assert skip is None


def test_get_effective_write_sql_platform_override_none_skips(fast_bench):
    operation = SimpleNamespace(write_sql="SELECT 1", platform_overrides={"duckdb": None}, id="op1")
    sql, skip = fast_bench._get_effective_write_sql(operation, platform_key="duckdb")
    assert sql is None
    assert skip is not None
    assert "unsupported" in skip.lower()


def test_get_effective_write_sql_platform_override_sql(fast_bench):
    operation = SimpleNamespace(write_sql="SELECT 1", platform_overrides={"duckdb": "DUCKDB SQL"}, id="op1")
    sql, skip = fast_bench._get_effective_write_sql(operation, platform_key="duckdb")
    assert sql == "DUCKDB SQL"
    assert skip is None


def test_get_effective_write_sql_no_overrides(fast_bench):
    operation = SimpleNamespace(write_sql="INSERT INTO t VALUES (1)", platform_overrides={}, id="op1")
    sql, skip = fast_bench._get_effective_write_sql(operation)
    assert sql == "INSERT INTO t VALUES (1)"
    assert skip is None


# ---------------------------------------------------------------------------
# _get_population_sql() for different table names (lines 433, 439, 445, 451)
# ---------------------------------------------------------------------------


def test_get_population_sql_merge_ops_target(fast_bench):
    sql = fast_bench._get_population_sql("merge_ops_target", "orders")
    assert "0.5" in sql or "50%" in sql or "CAST" in sql
    assert "merge_ops_target" in sql or '"merge_ops_target"' in sql


def test_get_population_sql_merge_ops_source(fast_bench):
    sql = fast_bench._get_population_sql("merge_ops_source", "orders")
    assert "orders" in sql or '"orders"' in sql


def test_get_population_sql_merge_ops_lineitem_target(fast_bench):
    sql = fast_bench._get_population_sql("merge_ops_lineitem_target", "lineitem")
    assert "lineitem" in sql or '"lineitem"' in sql


def test_get_population_sql_ddl_truncate_target(fast_bench):
    sql = fast_bench._get_population_sql("ddl_truncate_target", "orders")
    assert "o_orderkey" in sql


def test_get_population_sql_default_full_copy(fast_bench):
    sql = fast_bench._get_population_sql("update_ops_orders", "orders")
    assert "SELECT *" in sql


# ---------------------------------------------------------------------------
# get_create_tables_sql() (line 878)
# ---------------------------------------------------------------------------


def test_get_create_tables_sql_returns_sql_string(fast_bench):
    sql = fast_bench.get_create_tables_sql()
    assert isinstance(sql, str)
    assert "CREATE TABLE" in sql.upper()
    assert "CREATE TABLE orders_stage" in sql
    assert "CREATE TABLE lineitem_stage" in sql


# ---------------------------------------------------------------------------
# ensure_auxiliary_data_files() (lines 210-235)
# ---------------------------------------------------------------------------


def test_ensure_auxiliary_data_files_bulk_files_exist(fast_bench):
    fast_bench.data_generator.check_bulk_load_files_exist.return_value = True
    fast_bench.ensure_auxiliary_data_files()  # should not raise
    fast_bench.data_generator.generate_bulk_load_files.assert_not_called()


def test_ensure_auxiliary_data_files_acquires_lock_and_generates(fast_bench):
    fast_bench.data_generator.check_bulk_load_files_exist.return_value = False
    fast_bench.data_generator._acquire_bulk_load_lock.return_value = True
    fast_bench.data_generator.generate_bulk_load_files.return_value = ["/tmp/f1.parquet"]

    fast_bench.ensure_auxiliary_data_files()

    fast_bench.data_generator.generate_bulk_load_files.assert_called_once()


def test_ensure_auxiliary_data_files_lock_timeout_silenced(fast_bench):
    fast_bench.data_generator.check_bulk_load_files_exist.return_value = False
    fast_bench.data_generator._acquire_bulk_load_lock.return_value = False

    fast_bench.ensure_auxiliary_data_files()  # should not raise


def test_ensure_auxiliary_data_files_already_generated_during_lock(fast_bench):
    """After acquiring lock, another process may have generated files."""
    call_count = [0]

    def check_side_effect():
        call_count[0] += 1
        return call_count[0] > 1  # False first, True on second call

    fast_bench.data_generator.check_bulk_load_files_exist.side_effect = check_side_effect
    fast_bench.data_generator._acquire_bulk_load_lock.return_value = True
    fast_bench.data_generator._release_bulk_load_lock = MagicMock()

    fast_bench.ensure_auxiliary_data_files()  # should not raise


# ---------------------------------------------------------------------------
# cleanup_auxiliary_files() (lines 658-666)
# ---------------------------------------------------------------------------


def test_cleanup_auxiliary_files_removes_directory(fast_bench, tmp_path):
    aux_dir = tmp_path / "write_primitives_auxiliary"
    aux_dir.mkdir()
    fast_bench.data_generator.files_dir = aux_dir

    fast_bench.cleanup_auxiliary_files()

    assert not aux_dir.exists()


def test_cleanup_auxiliary_files_missing_dir_is_noop(fast_bench, tmp_path):
    fast_bench.data_generator.files_dir = tmp_path / "nonexistent_dir"
    fast_bench.cleanup_auxiliary_files()  # should not raise


# ---------------------------------------------------------------------------
# _replace_placeholders() unusual chars warning (line 781)
# ---------------------------------------------------------------------------


def test_replace_placeholders_unusual_chars_in_path(fast_bench, tmp_path):
    """Unusual characters in path trigger a warning log (line 781)."""
    fast_bench._output_dir = Path("/tmp/test<path>")
    sql = "COPY INTO t FROM '{file_path}/data'"
    result = fast_bench._replace_placeholders(sql)
    # Should not raise - just log warning
    assert "{file_path}" not in result


# ---------------------------------------------------------------------------
# execute_operation() effective_sql=None case (line 1012)
# ---------------------------------------------------------------------------


def test_execute_operation_none_sql_raises_via_exception_handler(fast_bench, fast_conn):
    """When effective_sql is None and skip_reason is None, RuntimeError is raised."""
    with (
        patch.object(fast_bench, "is_setup", return_value=True),
        patch.object(fast_bench, "_get_effective_write_sql", return_value=(None, None)),
    ):
        result = fast_bench.execute_operation("insert_single_row", fast_conn)

    # The RuntimeError is caught by except Exception, returns FAILED
    assert result.success is False


# ---------------------------------------------------------------------------
# _populate_staging_tables() direct line coverage (475-476)
# ---------------------------------------------------------------------------


def test_populate_staging_tables_count_exception_treats_as_zero(fast_bench):
    """Exception in COUNT query → current_count=0 → triggers population."""
    call_count = [0]

    def execute_side(sql):
        result = MagicMock()
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: COUNT for staging table → raise exception
            raise Exception("table not found")
        elif call_count[0] == 2:
            # Second call: COUNT for source (orders)
            result.fetchone.return_value = (1000,)
        else:
            result.fetchone.return_value = (1000,)
        return result

    conn = MagicMock()
    conn.execute.side_effect = execute_side

    with patch.object(fast_bench, "_get_population_sql", return_value="INSERT INTO ..."):
        result = fast_bench._populate_staging_tables(conn, {"update_ops_orders": "orders"})

    assert result.get("update_ops_orders", 0) >= 0
