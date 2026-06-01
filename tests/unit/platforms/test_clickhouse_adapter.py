"""Tests for ClickHouse platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.clickhouse import ClickHouseAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Check for optional dependencies
try:
    import importlib.util

    CHDB_AVAILABLE = importlib.util.find_spec("chdb") is not None
except ImportError:
    CHDB_AVAILABLE = False


@pytest.fixture(autouse=True)
def clickhouse_dependencies():
    """Mock ClickHouse dependency check to simulate installed extras."""

    with patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])):
        yield


class TestClickHouseAdapter:
    """Test ClickHouse platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization in server mode."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            adapter = ClickHouseAdapter(
                deployment_mode="server",  # Explicitly request server mode
                host="localhost",
                port=9000,
                database="test",
                username="test",
                password="test",
            )
            assert adapter.platform_name == "ClickHouse (Server)"
            assert adapter.dialect == "clickhouse"
            assert adapter.host == "localhost"
            assert adapter.port == 9000
            assert adapter.deployment_mode == "server"

    def test_initialization_missing_driver(self):
        """Test initialization when ClickHouse driver dependencies are missing (server mode)."""
        with (
            patch(
                "benchbox.platforms.clickhouse.adapter.check_platform_dependencies",
                return_value=(False, ["clickhouse-driver"]),
            ),
            pytest.raises(ImportError) as excinfo,
        ):
            ClickHouseAdapter(deployment_mode="server")  # Server mode requires driver

        assert "Missing dependencies for clickhouse platform" in str(excinfo.value)

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_create_connection_success(self, mock_client_class):
        """Test successful connection creation."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Mock database check to return empty list (database doesn't exist)
        mock_client.execute.side_effect = [
            [],
            None,
            None,
        ]  # SHOW DATABASES returns [], CREATE DATABASE succeeds, SELECT 1 returns None

        adapter = ClickHouseAdapter(deployment_mode="server", host="localhost", port=9000)
        connection = adapter.create_connection()

        assert connection == mock_client
        # Should be called three times: db check, db create, main client
        assert mock_client_class.call_count == 3
        # Should execute SHOW DATABASES, CREATE DATABASE, and SELECT 1
        assert mock_client.execute.call_count == 3

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_create_connection_bootstraps_database_before_scoped_client(self, mock_client_class):
        """Server connections create the target database before selecting it."""
        check_client = Mock()
        create_client = Mock()
        main_client = Mock()
        check_client.execute.return_value = []
        mock_client_class.side_effect = [check_client, create_client, main_client]

        adapter = ClickHouseAdapter(
            deployment_mode="server",
            host="localhost",
            port=9000,
            database="benchbox_run",
            username="default",
            password="benchbox",
        )

        assert adapter.create_connection() == main_client

        create_client.execute.assert_called_once_with("CREATE DATABASE IF NOT EXISTS `benchbox_run`")
        assert "database" not in mock_client_class.call_args_list[1].kwargs
        assert mock_client_class.call_args_list[2].kwargs["database"] == "benchbox_run"

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_create_connection_rejects_unsafe_database_identifier(self, mock_client_class):
        """Database bootstrap does not interpolate unsafe identifiers into SQL."""
        check_client = Mock()
        check_client.execute.return_value = []
        mock_client_class.return_value = check_client

        adapter = ClickHouseAdapter(deployment_mode="server", database="bad-name")

        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter.create_connection()

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_create_connection_failure(self, mock_client_class):
        """Test connection creation failure."""
        mock_client_class.side_effect = Exception("Connection failed")

        adapter = ClickHouseAdapter(deployment_mode="server")

        with pytest.raises(Exception, match="Connection failed"):
            adapter.create_connection()

    def test_sql_translation(self):
        """Test SQL dialect translation."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            adapter = ClickHouseAdapter(deployment_mode="server")

            # Test with sqlglot available
            with patch("sqlglot.transpile") as mock_transpile:
                mock_transpile.return_value = ['SELECT * FROM "table"']

                result = adapter.translate_sql("SELECT * FROM table", "duckdb")
                # translate_sql adds semicolon at the end
                assert result == 'SELECT * FROM "table";'
                # identify=False for clickhouse (excluded from quoting policy)
                mock_transpile.assert_called_once_with(
                    "SELECT * FROM table", read="duckdb", write="clickhouse", identify=False
                )

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_create_schema(self, mock_client_class):
        """Test schema creation."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = (
            "CREATE TABLE test (id INT); CREATE TABLE test2 (name STRING);"
        )

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        schema_time = adapter.create_schema(mock_benchmark, connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0
        # Should execute multiple statements
        assert mock_client.execute.call_count >= 2

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_load_data_with_tables(self, mock_client_class):
        """Test data loading with table files."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Mock database check to return empty list (database doesn't exist)
        # Mock database creation and SELECT 1 to return None for connection setup
        # Mock COUNT(*) query to return the row count
        # Mock: database check, database create, connection test,
        # COUNT(*) before, INSERT statement, COUNT(*) after
        mock_client.execute.side_effect = [[], None, None, [[0]], None, [[100]]]

        # Create temporary test file first
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,test\n2,test2\n")
            temp_path = Path(f.name)

        try:
            # Create mock benchmark with proper dict attribute (not a Mock)
            mock_benchmark = Mock(spec=["tables", "get_schema"])  # Only allow specific attributes
            tables_dict = {"test_table": str(temp_path)}
            mock_benchmark.tables = tables_dict
            mock_benchmark.get_schema.return_value = {}  # Return empty schema

            adapter = ClickHouseAdapter(deployment_mode="server")
            connection = adapter.create_connection()

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "test_table" in table_stats  # Table names are lowercase per TPC spec
            assert table_stats["test_table"] == 2

        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_execute_query_success(self, mock_client_class):
        """Test successful query execution."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.execute.return_value = [[1, "test"], [2, "test2"]]

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        result = adapter.execute_query(connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == [1, "test"]
        assert isinstance(result["execution_time_seconds"], float)

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_execute_query_failure(self, mock_client_class):
        """Test query execution failure."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Mock successful connection setup, then query failure
        mock_client.execute.side_effect = [
            [],
            None,
            None,
            Exception("Query failed"),
        ]  # db check, database create, connection test, then query failure

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        result = adapter.execute_query(connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert isinstance(result["execution_time_seconds"], float)

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_configure_for_benchmark_tuning_disabled(self, mock_client_class):
        """Test benchmark optimization when tuning is disabled."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Use server mode to avoid chdb initialization in unit tests
        adapter = ClickHouseAdapter(deployment_mode="server", strict_validation=False)
        adapter.tuning_enabled = False  # Explicitly disable tuning
        connection = adapter.create_connection()

        # Should apply OLAP optimizations for OLAP benchmark types
        adapter.configure_for_benchmark(connection, "olap")

        # Should execute multiple optimization statements (basic + OLAP)
        assert mock_client.execute.call_count > 5  # basic settings + OLAP settings

        # Reset mock for next test
        mock_client.reset_mock()

        # Should only apply basic optimizations for non-OLAP benchmark types
        adapter.configure_for_benchmark(connection, "read_primitives")

        # Should execute fewer statements (basic settings + cache control + validation = 10)
        assert mock_client.execute.call_count == 10  # basic (6) + cache (3) + validation (1)

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_configure_for_benchmark_tuning_enabled(self, mock_client_class):
        """Test benchmark optimization when tuning is enabled."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Mock database check to return empty list
        mock_client.execute.side_effect = [[], None, None]

        # Use server mode to avoid chdb initialization in unit tests
        adapter = ClickHouseAdapter(deployment_mode="server", strict_validation=False)
        adapter.tuning_enabled = True  # Enable tuning
        connection = adapter.create_connection()

        # Reset mock to clear the connection setup calls
        mock_client.reset_mock()

        # Should only apply basic settings when tuning is enabled
        adapter.configure_for_benchmark(connection, "olap")

        # Should execute only basic optimization statements (no OLAP-specific ones)
        # Basic settings (6) + cache control settings (3) + validation query (1) = 10
        assert mock_client.execute.call_count == 10  # basic + cache + validation

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_configure_for_benchmark_join_memory_uses_50_pct_multiplier(self, mock_client_class):
        """max_bytes_in_join must be 50% of max_memory_usage - SF1 Q5 needs 2.72 GiB."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        adapter = ClickHouseAdapter(deployment_mode="server", strict_validation=False)
        adapter.tuning_enabled = False  # trigger OLAP settings path

        connection = adapter.create_connection()
        mock_client.reset_mock()
        adapter.configure_for_benchmark(connection, "tpch")

        executed_statements = [call[0][0] for call in mock_client.execute.call_args_list]
        join_stmt = next((s for s in executed_statements if "max_bytes_in_join" in s), None)
        assert join_stmt is not None, "max_bytes_in_join setting was not applied"

        # Extract the numeric value from "SET max_bytes_in_join = <N>"
        import re

        m = re.search(r"max_bytes_in_join\s*=\s*(\d+)", join_stmt)
        assert m is not None, f"Could not parse max_bytes_in_join value from: {join_stmt}"
        join_limit = int(m.group(1))

        memory_bytes = adapter._parse_memory_setting(adapter.max_memory_usage)
        expected_50pct = int(memory_bytes * 0.5)
        assert join_limit == expected_50pct, (
            f"max_bytes_in_join should be 50% of max_memory_usage ({expected_50pct}), got {join_limit}"
        )

        # Verify grace_hash is applied for server mode
        grace_stmt = next((s for s in executed_statements if "grace_hash" in s), None)
        assert grace_stmt is not None, "join_algorithm = grace_hash setting was not applied"

    @pytest.mark.skipif(not CHDB_AVAILABLE, reason="chDB not installed (required for embedded mode test)")
    def test_configure_for_benchmark_embedded_mode(self):
        """Test benchmark optimization in embedded mode skips problematic settings."""
        # Skip if chdb is not available - this test specifically tests embedded mode behavior
        # which requires actual chdb to be installed
        mock_connection = Mock()

        # Create adapter in local mode (embedded is now an alias for local)
        # Use a unique database path to avoid conflicts with other tests
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ClickHouseAdapter(
                deployment_mode="local",
                strict_validation=False,
                data_path=tmpdir,
            )
            adapter.tuning_enabled = False  # Disable tuning to test OLAP optimizations

            # Should apply OLAP optimizations but skip embedded-incompatible settings
            adapter.configure_for_benchmark(mock_connection, "olap")

            # Check that problematic settings were not applied
            executed_statements = [call[0][0] for call in mock_connection.execute.call_args_list]
            executed_sql = " ".join(executed_statements)

            # These settings should not be present in local/embedded mode
            assert "join_algorithm" not in executed_sql
            assert "enable_multiple_joins_emulation" not in executed_sql

            # But other settings should still be applied
            assert "max_memory_usage" in executed_sql
            assert "max_threads" in executed_sql

    def test_get_database_path_server_mode(self):
        """Test database path generation in server mode returns None."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            adapter = ClickHouseAdapter(deployment_mode="server")

            result = adapter.get_database_path(database_path="some/path.duckdb")
            assert result is None

    @pytest.mark.skipif(not CHDB_AVAILABLE, reason="chDB not installed (required for embedded mode)")
    def test_apply_setting_with_validation_embedded_mode(self):
        """Test setting validation in embedded mode."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            mock_connection = Mock()

            adapter = ClickHouseAdapter(deployment_mode="local")

            # Test that known problematic settings are skipped in embedded mode
            result = adapter._apply_setting_with_validation(mock_connection, "join_algorithm", "hash")
            assert result is False
            mock_connection.execute.assert_not_called()

            mock_connection.reset_mock()

            result = adapter._apply_setting_with_validation(mock_connection, "enable_multiple_joins_emulation", 1)
            assert result is False
            mock_connection.execute.assert_not_called()

            # Test that safe settings are still applied
            mock_connection.reset_mock()
            result = adapter._apply_setting_with_validation(mock_connection, "max_threads", 4)
            assert result is True
            mock_connection.execute.assert_called_once_with("SET max_threads = 4")

    def test_apply_setting_with_validation_server_mode(self):
        """Test setting validation in server mode."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            mock_connection = Mock()

            adapter = ClickHouseAdapter(deployment_mode="server")

            # Test that problematic settings are attempted in server mode
            result = adapter._apply_setting_with_validation(mock_connection, "join_algorithm", "hash")
            assert result is True
            mock_connection.execute.assert_called_once_with("SET join_algorithm = 'hash'")

            # Test error handling
            mock_connection.reset_mock()
            mock_connection.execute.side_effect = Exception("Setting not supported")

            result = adapter._apply_setting_with_validation(mock_connection, "some_setting", "value")
            assert result is False
            mock_connection.execute.assert_called_once_with("SET some_setting = 'value'")

    def test_memory_setting_parsing(self):
        """Test memory setting parsing."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            adapter = ClickHouseAdapter(deployment_mode="server")

            assert adapter._parse_memory_setting("8GB") == 8 * 1024 * 1024 * 1024
            assert adapter._parse_memory_setting("512MB") == 512 * 1024 * 1024
            assert adapter._parse_memory_setting("1024KB") == 1024 * 1024
            assert adapter._parse_memory_setting(1024) == 1024

    def test_table_optimization(self):
        """Test table definition optimization."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"):
            adapter = ClickHouseAdapter(deployment_mode="server")

            # Test adding MergeTree engine
            original = "CREATE TABLE test (id INT, name STRING)"
            optimized = adapter._optimize_table_definition(original)
            expected = "CREATE TABLE test (id INT, name STRING) ENGINE = MergeTree() ORDER BY tuple()"
            assert optimized == expected

            # Test with existing engine
            with_engine = "CREATE TABLE test (id INT) ENGINE = ReplacingMergeTree()"
            optimized_with_engine = adapter._optimize_table_definition(with_engine)
            expected_with_engine = "CREATE TABLE test (id INT) ENGINE = ReplacingMergeTree() ORDER BY tuple()"
            assert optimized_with_engine == expected_with_engine

            # DuckDB-style fixed-size float arrays must be rewritten to
            # Array(Float32/Float64) — ClickHouse rejects `FLOAT[N]` syntax.
            duckdb_array = "CREATE TABLE vectors (id BIGINT, embedding FLOAT[128])"
            assert "Array(Float32)" in adapter._optimize_table_definition(duckdb_array)
            assert "FLOAT[" not in adapter._optimize_table_definition(duckdb_array)

            duckdb_double_array = "CREATE TABLE vectors (id BIGINT, embedding DOUBLE[256])"
            assert "Array(Float64)" in adapter._optimize_table_definition(duckdb_double_array)

            # \b word boundary must protect identifiers that merely contain the
            # FLOAT/DOUBLE substring; the rewrite is for type tokens only. The
            # mixed case asserts both: the real FLOAT[N] type token IS rewritten
            # while the column name `my_float_col` survives untouched.
            mixed = "CREATE TABLE t (vec FLOAT[10], my_float_col INT)"
            mixed_out = adapter._optimize_table_definition(mixed)
            assert "vec Array(Float32)" in mixed_out
            assert "my_float_col INT" in mixed_out
            assert "FLOAT[" not in mixed_out

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_get_platform_metadata(self, mock_client_class):
        """Test platform metadata collection."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock version query
        mock_client.execute.return_value = [["21.8.0"]]

        adapter = ClickHouseAdapter(deployment_mode="server", host="test", port=9000, database="test")
        connection = adapter.create_connection()

        metadata = adapter._get_platform_metadata(connection)

        assert metadata["platform"] == "ClickHouse (Server)"
        assert metadata["host"] == "test"
        assert metadata["port"] == 9000
        assert metadata["database"] == "test"
        assert "clickhouse_version" in metadata

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_get_table_info(self, mock_client_class):
        """Test table information retrieval."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock connection setup, then schema and stats queries
        mock_client.execute.side_effect = [
            [],  # database check
            None,  # database create
            None,  # connection test
            [("id", "Int32"), ("name", "String")],  # schema query
            [(1000, 1024000, 512000)],  # stats query
        ]

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        info = adapter.get_table_info(connection, "test_table")

        assert info["columns"] == [("id", "Int32"), ("name", "String")]
        assert info["row_count"] == 1000
        assert info["bytes_on_disk"] == 1024000
        assert info["compressed_size"] == 512000

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_optimize_table(self, mock_client_class):
        """Test table optimization."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        adapter.optimize_table(connection, "test_table")

        mock_client.execute.assert_called_with("OPTIMIZE TABLE test_table FINAL")

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_close_connection(self, mock_client_class):
        """Test connection closing."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        adapter.close_connection(connection)

        mock_client.disconnect.assert_called_once()

    def test_test_connection(self):
        """Test connection testing."""
        with patch("benchbox.platforms.clickhouse.setup.ClickHouseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            adapter = ClickHouseAdapter(deployment_mode="server")

            # Test successful connection
            assert adapter.test_connection() is True

            # Test failed connection
            mock_client_class.side_effect = Exception("Connection failed")
            assert adapter.test_connection() is False

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_apply_table_tunings_with_sorting(self, mock_client_class):
        """Test applying table tunings with sorting configuration."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock table tuning object
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"

        # Mock sorting column
        mock_sort_col = Mock()
        mock_sort_col.name = "id"
        mock_sort_col.order = 1

        # Mock the get_columns_by_type method
        def mock_get_columns_by_type(tuning_type):
            # Import here to avoid circular imports in test
            from benchbox.core.tuning.interface import TuningType

            if str(tuning_type) == str(TuningType.SORTING):
                return [mock_sort_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

        mock_tuning.sorting = [mock_sort_col]  # Has sorting configuration
        mock_tuning.clustering = None
        mock_tuning.partitioning = None
        mock_tuning.distribution = None

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        # Should not raise exception
        adapter.apply_table_tunings(mock_tuning, connection)

        # Should call optimize_table (which calls OPTIMIZE TABLE)
        expected_calls = [call for call in mock_client.execute.call_args_list if "OPTIMIZE" in str(call)]
        assert len(expected_calls) > 0

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_apply_table_tunings_with_clustering(self, mock_client_class):
        """Test applying table tunings with clustering configuration."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock table tuning object
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"

        # Mock clustering column
        mock_cluster_col = Mock()
        mock_cluster_col.name = "cluster_key"
        mock_cluster_col.order = 1

        # Mock the get_columns_by_type method
        def mock_get_columns_by_type(tuning_type):
            # Import here to avoid circular imports in test
            from benchbox.core.tuning.interface import TuningType

            if str(tuning_type) == str(TuningType.CLUSTERING):
                return [mock_cluster_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

        mock_tuning.sorting = None
        mock_tuning.clustering = [mock_cluster_col]  # Has clustering configuration
        mock_tuning.partitioning = None
        mock_tuning.distribution = None

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        # Should not raise exception
        adapter.apply_table_tunings(mock_tuning, connection)

        # Should call OPTIMIZE TABLE FINAL for clustering
        optimize_final_calls = [
            call for call in mock_client.execute.call_args_list if "OPTIMIZE TABLE test_table FINAL" in str(call)
        ]
        assert len(optimize_final_calls) > 0

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_apply_table_tunings_none(self, mock_client_class):
        """Test applying table tunings with None input."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        adapter = ClickHouseAdapter(deployment_mode="server")
        connection = adapter.create_connection()

        # Should not raise exception with None tuning
        adapter.apply_table_tunings(None, connection)

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_generate_tuning_clause_with_partitioning(self, mock_client_class):
        """Test generating tuning clause with partitioning."""
        mock_client_class.return_value = Mock()

        # Mock TuningType and columns
        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"

            # Mock table tuning object
            mock_tuning = Mock()
            mock_tuning.table_name = "test_table"
            mock_tuning.partitioning = [Mock()]  # Has partitioning configuration
            mock_tuning.clustering = None
            mock_tuning.sorting = None
            mock_tuning.distribution = None

            # Mock column object
            mock_column = Mock()
            mock_column.name = "date_col"
            mock_column.order = 1

            mock_tuning.get_columns_by_type.return_value = [mock_column]

            adapter = ClickHouseAdapter(deployment_mode="server")

            clause = adapter.generate_tuning_clause(mock_tuning)

            assert "PARTITION BY" in clause
            assert "date_col" in clause

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_generate_tuning_clause_with_sorting(self, mock_client_class):
        """Test generating tuning clause with sorting."""
        mock_client_class.return_value = Mock()

        # Mock TuningType and columns
        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"

            # Mock table tuning object
            mock_tuning = Mock()
            mock_tuning.table_name = "test_table"
            mock_tuning.partitioning = None
            mock_tuning.clustering = None
            mock_tuning.sorting = [Mock()]  # Has sorting configuration
            mock_tuning.distribution = None

            # Mock column object
            mock_column = Mock()
            mock_column.name = "sort_col"
            mock_column.order = 1

            mock_tuning.get_columns_by_type.return_value = [mock_column]

            adapter = ClickHouseAdapter(deployment_mode="server")

            clause = adapter.generate_tuning_clause(mock_tuning)

            assert "ORDER BY" in clause
            assert "sort_col" in clause

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_generate_tuning_clause_none(self, mock_client_class):
        """Test generating tuning clause with None input."""
        mock_client_class.return_value = Mock()

        adapter = ClickHouseAdapter(deployment_mode="server")

        clause = adapter.generate_tuning_clause(None)
        assert clause == ""

    @patch("benchbox.platforms.clickhouse.setup.ClickHouseClient")
    def test_generate_tuning_clause_empty(self, mock_client_class):
        """Test generating tuning clause with empty configuration."""
        mock_client_class.return_value = Mock()

        # Mock table tuning object with no tuning configurations
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"
        mock_tuning.partitioning = None
        mock_tuning.clustering = None
        mock_tuning.sorting = None
        mock_tuning.distribution = None

        adapter = ClickHouseAdapter(deployment_mode="server")

        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == ""


class TestClickHouseNativeHandlerBulk:
    """Tests for ClickHouseNativeHandler.load_table_bulk() glob-pattern loading."""

    def _make_handler(self, dry_run: bool = False, server_mode: bool = False):
        from benchbox.platforms.base.data_loading import ClickHouseNativeHandler

        adapter = Mock(spec=[])  # no dry_run_mode unless set
        if server_mode:
            adapter.deployment_mode = "server"
        if dry_run:
            adapter.dry_run_mode = True
            adapter.capture_sql = Mock()
        benchmark = Mock(spec=[])
        return ClickHouseNativeHandler("|", adapter, benchmark)

    def _make_bulk_connection(self, before: int, after: int) -> Mock:
        """Mock for a single bulk load: [COUNT_before, INSERT, COUNT_after]."""
        connection = Mock()
        connection.execute.side_effect = [[[before]], None, [[after]]]
        return connection

    def test_bulk_load_same_dir_uses_glob_sql(self, tmp_path):
        """4 shards in same dir must produce a single INSERT with file(glob) SQL."""
        shards = [tmp_path / f"lineitem.tbl.{i}" for i in range(1, 5)]
        for s in shards:
            s.touch()

        handler = self._make_handler()
        connection = self._make_bulk_connection(before=0, after=4000)

        result = handler.load_table_bulk("lineitem", shards, connection, Mock(), Mock())

        assert result == 4000
        # Single bulk INSERT: [COUNT_before, INSERT, COUNT_after]
        assert connection.execute.call_count == 3
        insert_sql = connection.execute.call_args_list[1][0][0]
        assert "INSERT INTO lineitem" in insert_sql
        # Glob must reference the common prefix
        assert "lineitem.tbl.*" in insert_sql
        assert "file(" in insert_sql
        # Pipe delimiter setting
        assert "format_csv_delimiter" in insert_sql

    def test_bulk_load_different_dirs_falls_back(self, tmp_path):
        """Shards in different directories must fall back to per-shard loop."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        shards = [dir_a / "orders.tbl.1", dir_b / "orders.tbl.2"]
        for s in shards:
            s.touch()

        handler = self._make_handler()

        # Each load_table() call needs: [COUNT_before, INSERT, COUNT_after]
        connection = Mock()
        connection.execute.side_effect = [
            [[0]],  # shard 1 COUNT before
            None,  # shard 1 INSERT
            [[500]],  # shard 1 COUNT after
            [[500]],  # shard 2 COUNT before
            None,  # shard 2 INSERT
            [[1000]],  # shard 2 COUNT after
        ]

        result = handler.load_table_bulk("orders", shards, connection, Mock(), Mock())

        # Fallback: 2 load_table() calls → 3 executes each = 6 total
        assert connection.execute.call_count == 6
        assert result == 1000  # 500 + 500

    def test_bulk_load_single_shard_delegates_to_load_table(self, tmp_path):
        """Single-element list must produce same result as load_table()."""
        shard = tmp_path / "region.tbl"
        shard.touch()

        handler = self._make_handler()
        connection = self._make_bulk_connection(before=0, after=5)

        result = handler.load_table_bulk("region", [shard], connection, Mock(), Mock())

        assert result == 5

    def test_load_table_parquet_zst_uses_parquet_sql(self, tmp_path):
        """Compressed parquet files should still use ClickHouse's Parquet reader."""
        parquet_file = tmp_path / "lineitem.parquet.zst"
        parquet_file.touch()

        handler = self._make_handler()
        connection = self._make_bulk_connection(before=0, after=6000)

        result = handler.load_table("lineitem", parquet_file, connection, Mock(), Mock())

        assert result == 6000
        insert_sql = connection.execute.call_args_list[1][0][0]
        assert "file(" in insert_sql
        assert "'Parquet'" in insert_sql
        assert "format_csv_delimiter" not in insert_sql

    def test_bulk_load_parquet_shards_use_parquet_sql(self, tmp_path):
        """Sharded parquet names should preserve Parquet detection for glob loading."""
        shards = [tmp_path / f"lineitem.parquet.{i}.zst" for i in range(1, 3)]
        for shard in shards:
            shard.touch()

        handler = self._make_handler()
        connection = self._make_bulk_connection(before=0, after=6000)

        result = handler.load_table_bulk("lineitem", shards, connection, Mock(), Mock())

        assert result == 6000
        insert_sql = connection.execute.call_args_list[1][0][0]
        assert "lineitem.parquet.*" in insert_sql
        assert "'Parquet'" in insert_sql
        assert "format_csv_delimiter" not in insert_sql

    def test_bulk_load_dry_run_returns_placeholder(self, tmp_path):
        """Dry-run mode must return 1000*N without executing INSERT."""
        shards = [tmp_path / f"customer.tbl.{i}" for i in range(1, 5)]
        for s in shards:
            s.touch()

        handler = self._make_handler(dry_run=True)
        connection = Mock()

        result = handler.load_table_bulk("customer", shards, connection, Mock(), Mock())

        assert result == 4000
        assert not connection.execute.called
        handler.adapter.capture_sql.assert_called_once()

    def test_server_mode_loads_host_files_with_client_batches(self, tmp_path):
        """ClickHouse server mode cannot use file() for host-local Docker paths."""
        shard = tmp_path / "region.tbl"
        shard.write_text("1|AFRICA\n2|AMERICA\n", encoding="utf-8")

        handler = self._make_handler(server_mode=True)
        connection = Mock()
        benchmark = Mock()
        benchmark.get_schema.return_value = {
            "region": {
                "columns": [
                    {"name": "r_regionkey", "type": "INTEGER"},
                    {"name": "r_name", "type": "CHAR(25)"},
                ]
            }
        }

        result = handler.load_table_bulk("region", [shard], connection, benchmark, Mock())

        assert result == 2
        connection.execute.assert_called_once_with(
            "INSERT INTO region VALUES",
            [(1, "AFRICA"), (2, "AMERICA")],
        )
        assert "file(" not in connection.execute.call_args[0][0]


# ===================================================================
# Additional coverage tests (merged from test_clickhouse_metadata_coverage.py)
# ===================================================================

from benchbox.platforms.clickhouse.metadata import ClickHouseMetadataMixin  # noqa: E402


class _DummyClickHouseMetadata(ClickHouseMetadataMixin):
    def __init__(self, deployment_mode="local"):
        self.deployment_mode = deployment_mode
        self.data_path = "/tmp/ch"
        self.host = "localhost"
        self.port = 9000
        self.database = "bench"
        self.disable_result_cache = False
        self.logger = SimpleNamespace(debug=lambda *a, **k: None)


class TestClickHouseMetadataCoverage:
    def test_platform_name_and_target_dialect(self):
        assert _DummyClickHouseMetadata(deployment_mode="local").platform_name == "ClickHouse (Local)"
        assert _DummyClickHouseMetadata(deployment_mode="server").get_target_dialect() == "clickhouse"

    def test_get_database_path_variants(self, tmp_path):
        adapter = _DummyClickHouseMetadata(deployment_mode="local")

        duckdb_path = adapter.get_database_path(database_path="/tmp/db.duckdb")
        bare_path = adapter.get_database_path(database_path="/tmp/db")
        assert duckdb_path is not None
        assert bare_path is not None
        assert duckdb_path.endswith(".chdb")
        assert bare_path.endswith(".chdb")

        assert adapter.get_database_path(database_name="bench_local") is None

        server_adapter = _DummyClickHouseMetadata(deployment_mode="server")
        assert server_adapter.get_database_path(database_path="/tmp/db.duckdb") is None

    def test_get_platform_info_local_no_connection(self):
        adapter = _DummyClickHouseMetadata(deployment_mode="local")
        info = adapter.get_platform_info(connection=None)
        assert info["platform_type"] == "clickhouse"
        assert info["platform_version"] is None
        assert info["configuration"]["deployment_mode"] == "local"

    def test_get_platform_info_local_connection(self):
        adapter = _DummyClickHouseMetadata(deployment_mode="local")

        class LocalConn:
            def query(self, _sql):
                return "24.10.1.1234\n"

        info = adapter.get_platform_info(connection=LocalConn())
        assert info["platform_version"] == "24.10.1.1234"

    def test_get_platform_info_server_connection(self):
        adapter = _DummyClickHouseMetadata(deployment_mode="server")

        class Cursor:
            def __init__(self):
                self.calls = 0

            def execute(self, _sql):
                self.calls += 1

            def fetchone(self):
                return ("24.9",)

            def fetchall(self):
                if self.calls == 2:
                    return [("max_threads", "8")]
                if self.calls == 3:
                    return [("BUILD_TYPE", "Release")]
                return []

            def close(self):
                return None

        class Conn:
            def cursor(self):
                return Cursor()

        info = adapter.get_platform_info(connection=Conn())
        assert info["platform_version"] == "24.9"
        assert info["compute_configuration"]["system_settings"]["max_threads"] == "8"
        assert info["compute_configuration"]["build_options"]["BUILD_TYPE"] == "Release"


class TestClickHouseWorkloadCoverage:
    """Additional coverage-focused tests for workload helpers."""

    @staticmethod
    def _adapter(deployment_mode: str = "server") -> ClickHouseAdapter:
        adapter = ClickHouseAdapter.__new__(ClickHouseAdapter)
        adapter.deployment_mode = deployment_mode
        logger = logging.getLogger(f"benchbox.tests.clickhouse.{deployment_mode}")
        logger.debug = Mock()
        adapter.logger = logger
        adapter.verbose_enabled = False
        adapter.very_verbose = False
        adapter.log_verbose = Mock()
        adapter.log_very_verbose = Mock()
        return adapter

    def test_extract_primary_key_columns_handles_inline_and_composite_keys(self):
        adapter = self._adapter()

        columns = adapter._extract_primary_key_columns(
            "CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT, PRIMARY KEY (customer_id, order_id))"
        )

        assert "id" in columns
        assert "customer_id" in columns
        assert "order_id" in columns

    def test_get_existing_tables_handles_local_server_and_errors(self):
        local_adapter = self._adapter(deployment_mode="local")
        local_connection = Mock()
        local_connection.execute.return_value = [("Orders",), "LineItem"]
        assert local_adapter._get_existing_tables(local_connection) == ["orders", "lineitem"]

        server_adapter = self._adapter()
        server_connection = Mock()
        server_connection.execute.return_value = [("Orders",), ("LineItem",)]
        assert server_adapter._get_existing_tables(server_connection) == ["orders", "lineitem"]

        failing_connection = Mock()
        failing_connection.execute.side_effect = RuntimeError("boom")
        assert server_adapter._get_existing_tables(failing_connection) == []

    def test_get_table_row_count_uses_execute_not_cursor(self):
        # Regression: local/cloud clients have no cursor(); must use execute()
        adapter = self._adapter(deployment_mode="local")

        conn = Mock()
        conn.execute.return_value = [(42,)]
        assert adapter.get_table_row_count(conn, "orders") == 42
        conn.execute.assert_called_once_with("SELECT COUNT(*) FROM orders")

        # Verify execute() is used (not cursor) even when cursor attribute is absent
        conn2 = Mock(spec=[])  # no cursor attribute
        conn2.execute = Mock(return_value=[(99,)])
        assert adapter.get_table_row_count(conn2, "orders") == 99

        # Silent failure on query error
        conn3 = Mock()
        conn3.execute.side_effect = RuntimeError("boom")
        assert adapter.get_table_row_count(conn3, "orders") == 0

    def test_get_constraint_configuration_uses_effective_config(self):
        adapter = self._adapter()
        adapter.get_effective_tuning_configuration = Mock(
            return_value=SimpleNamespace(foreign_keys=SimpleNamespace(enabled=True))
        )

        assert adapter._get_constraint_configuration() == (True, True)

    def test_validate_data_integrity_covers_success_failure_and_missing_execute(self):
        adapter = self._adapter()

        healthy_connection = Mock()
        healthy_connection.execute.return_value = None
        status, details = adapter._validate_data_integrity(None, healthy_connection, {"orders": 1})
        assert status == "PASSED"
        assert details["accessible_tables"] == ["orders"]
        assert details["constraints_enabled"] is True

        def _execute(sql):
            if "lineitem" in sql:
                raise RuntimeError("missing")
            return None

        flaky_connection = SimpleNamespace(execute=_execute)
        status, details = adapter._validate_data_integrity(None, flaky_connection, {"orders": 1, "lineitem": 2})
        assert status == "FAILED"
        assert details["inaccessible_tables"] == ["lineitem"]
        assert details["constraints_enabled"] is False

        status, details = adapter._validate_data_integrity(None, SimpleNamespace(execute=None), {"orders": 1})
        assert status == "FAILED"
        assert "execute() method" in details["integrity_error"]

    def test_execute_query_adds_row_count_validation_metadata(self):
        adapter = self._adapter()
        adapter.verbose_enabled = True
        adapter.very_verbose = True
        connection = Mock()
        connection.execute.return_value = [(1,)]

        transformer = Mock()
        transformer.transform.return_value = "SELECT 1"
        transformer.add_query_settings.return_value = "SELECT 1 SETTINGS joined_subquery_requires_alias = 0"
        transformer.get_transformations_applied.return_value = ["expanded_final"]
        validation_result = SimpleNamespace(
            is_valid=True,
            warning_message="expected row count unavailable",
            error_message=None,
            expected_row_count=None,
        )

        with (
            patch("benchbox.platforms.clickhouse.workload.ClickHouseQueryTransformer", return_value=transformer),
            patch("benchbox.core.validation.query_validation.QueryValidator") as validator_cls,
        ):
            validator_cls.return_value.validate_query_result.return_value = validation_result
            result = adapter.execute_query(
                connection,
                "SELECT * FROM table",
                "Q1",
                benchmark_type="tpch",
                scale_factor=1.0,
            )

        assert result["status"] == "SUCCESS"
        assert result["row_count_validation"]["status"] == "PASSED"
        assert result["row_count_validation"]["warning"] == "expected row count unavailable"
        adapter.log_verbose.assert_any_call("Query Q1: Applied transformations: expanded_final")

    def test_execute_query_turns_validation_failures_into_failed_results(self):
        adapter = self._adapter()
        connection = Mock()
        connection.execute.return_value = [(1,), (2,)]

        transformer = Mock()
        transformer.transform.return_value = "SELECT 1"
        transformer.add_query_settings.return_value = "SELECT 1 SETTINGS joined_subquery_requires_alias = 0"
        transformer.get_transformations_applied.return_value = []
        validation_result = SimpleNamespace(
            is_valid=False,
            warning_message=None,
            error_message="row count mismatch",
            expected_row_count=5,
        )

        with (
            patch("benchbox.platforms.clickhouse.workload.ClickHouseQueryTransformer", return_value=transformer),
            patch("benchbox.core.validation.query_validation.QueryValidator") as validator_cls,
        ):
            validator_cls.return_value.validate_query_result.return_value = validation_result
            result = adapter.execute_query(connection, "SELECT * FROM table", "Q2", benchmark_type="tpch")

        assert result["status"] == "FAILED"
        assert result["row_count_validation"]["status"] == "FAILED"
        assert result["row_count_validation"]["error"] == "row count mismatch"
        assert result["error"] == "row count mismatch"

    def test_execute_query_returns_failure_payload_on_exceptions(self):
        adapter = self._adapter()
        connection = Mock()
        connection.execute.side_effect = RuntimeError("boom")

        transformer = Mock()
        transformer.transform.return_value = "SELECT 1"
        transformer.add_query_settings.return_value = "SELECT 1 SETTINGS joined_subquery_requires_alias = 0"
        transformer.get_transformations_applied.return_value = []

        with patch("benchbox.platforms.clickhouse.workload.ClickHouseQueryTransformer", return_value=transformer):
            result = adapter.execute_query(connection, "SELECT * FROM table", "Q3")

        assert result["status"] == "FAILED"
        assert result["error"] == "boom"
        assert result["error_type"] == "RuntimeError"

    def test_execute_query_error_message_capture_preserves_exception_text(self):
        """Full driver-style error text (Code/DB::Exception) must flow into result.error."""
        adapter = self._adapter()
        connection = Mock()
        driver_error = (
            "ClickHouse local query failed: Code: 47. DB::Exception: "
            "Unknown expression identifier `foo_invalid`. (UNKNOWN_IDENTIFIER)"
        )
        connection.execute.side_effect = RuntimeError(driver_error)

        transformer = Mock()
        transformer.transform.return_value = "SELECT foo_invalid"
        transformer.add_query_settings.return_value = "SELECT foo_invalid"
        transformer.get_transformations_applied.return_value = []

        with patch("benchbox.platforms.clickhouse.workload.ClickHouseQueryTransformer", return_value=transformer):
            result = adapter.execute_query(connection, "SELECT foo_invalid", "Q_err")

        assert result["status"] == "FAILED"
        assert result["error"] == driver_error
        assert "UNKNOWN_IDENTIFIER" in result["error"]
        assert result["error_type"] == "RuntimeError"

    def test_execute_query_error_capture_falls_back_when_str_is_empty(self):
        """Bare exceptions (no message) must still yield a non-empty `error` field."""
        adapter = self._adapter()
        connection = Mock()
        # RuntimeError() with no args -> str(e) == "" - must not produce empty error.
        connection.execute.side_effect = RuntimeError()

        transformer = Mock()
        transformer.transform.return_value = "SELECT 1"
        transformer.add_query_settings.return_value = "SELECT 1"
        transformer.get_transformations_applied.return_value = []

        with patch("benchbox.platforms.clickhouse.workload.ClickHouseQueryTransformer", return_value=transformer):
            result = adapter.execute_query(connection, "SELECT 1", "Q_empty")

        assert result["status"] == "FAILED"
        assert result["error"]  # non-empty - bug G guard
        assert result["error_type"] == "RuntimeError"


class TestClickHouseQueryTransformerDecimalLiterals:
    """Regression tests for fix_type_casts decimal literal handling.

    The patterns (0\\.0*)\\b in fix_type_casts used to backtrack-match "0." from
    non-zero decimals like 0.06, producing malformed SQL such as
    "CAST(0 AS Decimal(15,2))6". These tests guard against that regression.
    """

    def _transformer(self):
        from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

        return ClickHouseQueryTransformer()

    def test_arithmetic_non_zero_decimal_not_corrupted(self):
        """col + 0.06 must not become col + CAST(...)6."""
        t = self._transformer()
        for expr in ("col + 0.06", "col - 0.01", "col * 0.05", "col / 0.07"):
            result = t.fix_type_casts(expr)
            assert result == expr, f"fix_type_casts corrupted {expr!r} -> {result!r}"

    def test_arithmetic_pure_zero_decimal_is_cast(self):
        """col + 0.0 and col - 0.00 are pure-zero floats and should be CAST."""
        t = self._transformer()
        for expr in ("col + 0.0", "col - 0.00"):
            result = t.fix_type_casts(expr)
            assert "CAST(0 AS Decimal" in result, f"fix_type_casts should cast pure-zero in {expr!r}"
            assert result.count("CAST") == 1, f"Unexpected extra CASTs in {result!r}"

    def test_then_non_zero_decimal_not_corrupted(self):
        """THEN 0.06 must not produce THEN CAST(...)6."""
        t = self._transformer()
        for expr in ("THEN 0.06", "THEN 0.05", "THEN 0.07"):
            result = t.fix_type_casts(expr)
            assert result == expr, f"fix_type_casts corrupted {expr!r} -> {result!r}"

    def test_else_non_zero_decimal_not_corrupted(self):
        """ELSE 0.07 must not produce ELSE CAST(...)7."""
        t = self._transformer()
        for expr in ("ELSE 0.06", "ELSE 0.07", "ELSE 0.01"):
            result = t.fix_type_casts(expr)
            assert result == expr, f"fix_type_casts corrupted {expr!r} -> {result!r}"

    def test_tpchavoc_q6_between_clause_preserved(self):
        """l_discount between 0.06 - 0.01 and 0.06 + 0.01 must pass through unchanged."""
        t = self._transformer()
        sql = "WHERE l_discount between 0.06 - 0.01 and 0.06 + 0.01"
        result = t.fix_type_casts(sql)
        assert result == sql, f"fix_type_casts corrupted Q6 BETWEEN clause: {result!r}"

    def test_full_transform_preserves_q6_decimal_literals(self):
        """Full transformer pipeline must not strip leading zeros from Q6-like SQL."""
        t = self._transformer()
        sql = (
            "SELECT SUM(l_extendedprice * l_discount) AS revenue "
            "FROM lineitem "
            "WHERE l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01"
        )
        result = t.transform(sql)
        assert "0.06" in result, f"0.06 was stripped from SQL: {result!r}"
        assert "0.01" in result, f"0.01 was stripped from SQL: {result!r}"
        # Ensure no dangling digits after CAST
        import re

        assert not re.search(r"Decimal\(15,2\)\)\d", result), f"Dangling digit after CAST: {result!r}"


class TestClickHouseQueryTransformerSettings:
    """Tests for add_query_settings() under the new-analyzer-by-default architecture."""

    def _transformer(self):
        from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

        return ClickHouseQueryTransformer()

    def test_settings_not_appended_to_non_select(self):
        """DDL statements must pass through unchanged."""
        t = self._transformer()
        ddl = "CREATE TABLE foo (id Int32) ENGINE = MergeTree() ORDER BY id"
        assert t.add_query_settings(ddl) == ddl

    def test_settings_include_joined_subquery_alias(self):
        """Every SELECT/WITH query must include joined_subquery_requires_alias = 0."""
        t = self._transformer()
        result = t.add_query_settings("SELECT 1")
        assert "joined_subquery_requires_alias = 0" in result

    def test_enable_analyzer_not_added_for_plain_select(self):
        """Simple queries must NOT get enable_analyzer = 0 (uses new analyzer by default)."""
        t = self._transformer()
        result = t.add_query_settings("SELECT count(*) FROM store_sales")
        assert "enable_analyzer" not in result

    def test_enable_analyzer_not_added_for_avg_sum_window_pattern(self):
        """Q47/Q57-like SQL must rely on benchmark-local rewrites, not generic analyzer opt-outs."""
        t = self._transformer()
        q47_like = (
            "WITH v1 AS (SELECT d_year, SUM(ss_sales_price) AS sum_sales, "
            "AVG(SUM(ss_sales_price)) OVER (PARTITION BY i_category, d_year) AS avg_sales "
            "FROM store_sales GROUP BY d_year, i_category) SELECT * FROM v1"
        )
        result = t.add_query_settings(q47_like)
        assert "enable_analyzer" not in result

    def test_enable_analyzer_not_added_for_q66_alias_aggregate_pattern(self):
        """Q66-like SQL must be rewritten in TPC-DS, not downgraded generically here."""
        t = self._transformer()
        q66_like = (
            "SELECT w_warehouse_name, sum(jan_sales) as jan_sales "
            "FROM (SELECT w_warehouse_name, sum(CASE WHEN d_moy=1 THEN ws_ext_list_price ELSE 0 END) as jan_sales "
            "FROM web_sales JOIN date_dim ON ws_sold_date_sk = d_date_sk "
            "UNION ALL SELECT w_warehouse_name, sum(CASE WHEN d_moy=1 THEN cs_ext_list_price ELSE 0 END) as jan_sales "
            "FROM catalog_sales JOIN date_dim ON cs_sold_date_sk = d_date_sk) "
            "GROUP BY w_warehouse_name"
        )
        result = t.add_query_settings(q66_like)
        assert "enable_analyzer" not in result


class TestClickHouseQueryTransformerDecimalDivision:
    """Tests for fix_decimal_division_by_zero() - wraps Nullable(Decimal) divisors with NULLIF."""

    def _transformer(self):
        from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

        return ClickHouseQueryTransformer()

    def test_nullable_decimal_divisor_is_wrapped(self):
        """/ CAST(col AS Nullable(Decimal(15,4))) must become / NULLIF(CAST(...), 0)."""
        t = self._transformer()
        sql = "SELECT a / CAST(b AS Nullable(Decimal(15, 4))) FROM t"
        result = t.fix_decimal_division_by_zero(sql)
        assert "NULLIF(CAST(b AS Nullable(Decimal(15, 4))), 0)" in result

    def test_non_nullable_decimal_not_wrapped(self):
        """/ CAST(col AS Decimal(15,4)) (non-Nullable) must pass through unchanged."""
        t = self._transformer()
        sql = "SELECT a / CAST(b AS Decimal(15, 4)) FROM t"
        result = t.fix_decimal_division_by_zero(sql)
        assert "NULLIF" not in result
        assert result == sql

    def test_transformation_recorded(self):
        """Transformation name must be recorded when the pattern is found."""
        t = self._transformer()
        sql = "SELECT x / CAST(y AS Nullable(Decimal(18, 2))) FROM t"
        t.fix_decimal_division_by_zero(sql)
        assert "decimal_division_fix" in t.transformations_applied

    def test_no_transformation_when_pattern_absent(self):
        """No transformation must be recorded when there is no Nullable(Decimal) divisor."""
        t = self._transformer()
        sql = "SELECT a / b FROM t"
        t.fix_decimal_division_by_zero(sql)
        assert "decimal_division_fix" not in t.transformations_applied


class TestClickHouseQueryTransformerSafeDivision:
    """Focused tests for parenthesized divisor handling in safe_division()."""

    def _transformer(self):
        from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

        return ClickHouseQueryTransformer()

    def test_parenthesized_divisor_is_wrapped_as_a_whole(self):
        """Nested parenthesized divisors must be wrapped with one outer NULLIF."""
        t = self._transformer()
        sql = "SELECT revenue / ((store_sales + web_sales) / 2) FROM metrics"
        result = t.safe_division(sql)
        assert "revenue / NULLIF(((store_sales + web_sales) / 2), 0)" in result

    def test_numeric_literal_divisor_stays_untouched(self):
        """Literal divisors are already safe and must not gain NULLIF wrappers."""
        t = self._transformer()
        sql = "SELECT total_sales / 12 FROM metrics"
        result = t.safe_division(sql)
        assert result == sql

    def test_function_call_divisor_is_wrapped(self):
        """Function-call divisors like COUNT(*) must be wrapped with NULLIF."""
        t = self._transformer()
        sql = "SELECT total / COUNT(*) FROM t"
        result = t.safe_division(sql)
        assert "total / NULLIF(COUNT(*), 0)" in result

    def test_sum_function_divisor_is_wrapped(self):
        """SUM(col) divisors must be wrapped with NULLIF."""
        t = self._transformer()
        sql = "SELECT revenue / SUM(quantity) FROM t"
        result = t.safe_division(sql)
        assert "revenue / NULLIF(SUM(quantity), 0)" in result

    def test_already_nullif_wrapped_divisor_stays_untouched(self):
        """Divisors already wrapped in NULLIF must not be double-wrapped."""
        t = self._transformer()
        sql = "SELECT a / NULLIF(b, 0) FROM t"
        result = t.safe_division(sql)
        assert "a / NULLIF(b, 0)" in result
        assert "NULLIF(NULLIF" not in result

    def test_multiple_divisions_in_one_query(self):
        """All divisions in a query must be independently wrapped."""
        t = self._transformer()
        sql = "SELECT a / b, c / d FROM t"
        result = t.safe_division(sql)
        assert "a / NULLIF(b, 0)" in result
        assert "c / NULLIF(d, 0)" in result

    def test_division_inside_string_literal_not_transformed(self):
        """Division operators inside string literals must not be modified."""
        t = self._transformer()
        sql = "SELECT 'a/b' AS label, x / y FROM t"
        result = t.safe_division(sql)
        assert "'a/b'" in result
        assert "x / NULLIF(y, 0)" in result
