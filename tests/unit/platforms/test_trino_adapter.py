"""Tests for Trino platform adapter.

Tests the TrinoAdapter for Trino distributed SQL query engine support.

Note: This adapter supports Trino only, NOT PrestoDB (Meta's Presto fork).
For AWS managed Presto/Trino workloads, use the AthenaAdapter.
For Starburst Enterprise, this adapter is fully compatible.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.trino import TrinoAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTrinoAdapter:
    """Test Trino platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                port=8080,
                catalog="hive",
                schema="default",
                username="trino",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.platform_name == "Trino"
        assert adapter.get_target_dialect() == "trino"
        assert adapter.host == "trino-coordinator.example.com"
        assert adapter.port == 8080
        assert adapter.catalog == "hive"
        assert adapter.schema == "default"
        assert adapter.username == "trino"

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        try:
            adapter = TrinoAdapter(catalog="hive")  # catalog is required
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.host == "localhost"
        assert adapter.port == 8080
        assert adapter.catalog == "hive"
        assert adapter.schema == "default"
        assert adapter.username == "trino"
        assert adapter.http_scheme == "http"
        assert adapter.table_format == "memory"

    def test_initialization_without_catalog(self):
        """Test initialization without catalog (validation happens on connection)."""
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.catalog is None
        assert adapter.host == "localhost"
        assert adapter.port == 8080

    def test_initialization_with_password_enables_https(self):
        """Test that providing a password auto-enables HTTPS."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                username="user",
                password="secret",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.http_scheme == "https"

    def test_initialization_explicit_http_scheme(self):
        """Test explicit HTTP scheme configuration."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                username="user",
                password="secret",
                http_scheme="http",  # Override auto-detection
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.http_scheme == "http"

    def test_get_connection_params(self):
        """Test connection parameter configuration."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                port=8443,
                catalog="iceberg",
                schema="benchmark",
                username="test_user",
                password="test_pass",
                http_scheme="https",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        params = adapter._get_connection_params()

        assert params["host"] == "trino-coordinator.example.com"
        assert params["port"] == 8443
        assert params["catalog"] == "iceberg"
        assert params["schema"] == "benchmark"
        assert params["user"] == "test_user"
        assert params["http_scheme"] == "https"
        # Password should be used for auth object, not passed directly
        assert "auth" in params

    def test_get_connection_params_no_auth(self):
        """Test connection parameters without authentication."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                username="user",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        params = adapter._get_connection_params()

        assert params["user"] == "user"
        assert "auth" not in params

    def test_check_server_database_exists_true(self):
        """Test schema existence check when schema exists."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Mock the connection and cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("default",)

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
            result = adapter.check_server_database_exists(schema="default", catalog="memory")

        assert result is True

    def test_check_server_database_exists_false(self):
        """Test schema existence check when schema doesn't exist."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Mock the connection and cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
            result = adapter.check_server_database_exists(schema="nonexistent", catalog="memory")

        assert result is False

    def test_check_server_database_exists_connection_error(self):
        """Test schema existence check with connection error."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="hive",  # catalog is required
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", side_effect=Exception("Connection failed")):
            result = adapter.check_server_database_exists(schema="default", catalog="hive")

        # When connection fails, method should return False
        assert result is False

    def test_validate_catalog_raises_when_server_unreachable(self):
        """Catalog validation should raise ConfigurationError when server unreachable and no catalog."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )  # No catalog provided
        except ImportError:
            pytest.skip("Trino drivers not installed")

        from benchbox.core.exceptions import ConfigurationError

        # Mock _get_available_catalogs to return empty list (server query fails)
        with patch.object(adapter, "_get_available_catalogs", return_value=[]):
            with pytest.raises(ConfigurationError) as excinfo:
                adapter._validate_catalog_exists(None)

        assert "server is unreachable" in str(excinfo.value)

    def test_auto_select_catalog_prefers_hive(self):
        """Auto-selection should prefer hive over other catalogs."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch.object(adapter, "_get_available_catalogs", return_value=["memory", "hive", "system"]):
            selected = adapter._auto_select_catalog()

        assert selected == "hive"

    def test_auto_select_catalog_fallback_to_memory(self):
        """Auto-selection should fall back to memory when hive not available."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch.object(adapter, "_get_available_catalogs", return_value=["memory", "system"]):
            selected = adapter._auto_select_catalog()

        assert selected == "memory"

    def test_auto_select_catalog_uses_first_available(self):
        """Auto-selection should use first usable catalog when no preferred catalogs."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # system is filtered out, custom_catalog is used
        with patch.object(adapter, "_get_available_catalogs", return_value=["custom_catalog", "system"]):
            selected = adapter._auto_select_catalog()

        assert selected == "custom_catalog"

    def test_auto_select_catalog_only_system_catalogs(self):
        """Auto-selection should return None when only system catalogs exist."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Only jmx and system - both are system-only and unusable
        with patch.object(adapter, "_get_available_catalogs", return_value=["jmx", "system"]):
            selected = adapter._auto_select_catalog()

        assert selected is None

    def test_auto_select_catalog_server_unreachable(self):
        """Auto-selection should return None when server unreachable."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch.object(adapter, "_get_available_catalogs", return_value=[]):
            selected = adapter._auto_select_catalog()

        assert selected is None

    def test_validation_auto_selects_when_none(self):
        """Validation should auto-select catalog when None provided."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch.object(adapter, "_get_available_catalogs", return_value=["hive", "memory", "system"]):
            validated = adapter._validate_catalog_exists(None)

        assert validated == "hive"
        assert adapter._catalog_was_auto_selected is True

    def test_validation_raises_when_server_unreachable(self):
        """Validation should raise ConfigurationError when server unreachable and no catalog."""
        from benchbox.core.exceptions import ConfigurationError

        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch.object(adapter, "_get_available_catalogs", return_value=[]):
            with pytest.raises(ConfigurationError) as exc_info:
                adapter._validate_catalog_exists(None)

        assert "server is unreachable" in str(exc_info.value)

    def test_validation_raises_when_only_system_catalogs(self):
        """Validation should raise ConfigurationError when only system catalogs exist."""
        from benchbox.core.exceptions import ConfigurationError

        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Only jmx and system catalogs exist
        with patch.object(adapter, "_get_available_catalogs", return_value=["jmx", "system"]):
            with pytest.raises(ConfigurationError) as exc_info:
                adapter._validate_catalog_exists(None)

        assert "No usable data catalogs found" in str(exc_info.value)
        assert "jmx, system" in str(exc_info.value)

    def test_drop_database(self):
        """Test schema dropping."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="test_schema",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Mock the connection and cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # First call checks if schema exists
        mock_cursor.fetchone.return_value = ("test_schema",)

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
            adapter.drop_database(schema="test_schema", catalog="memory")

        # Verify DROP SCHEMA was executed
        drop_calls = [call for call in mock_cursor.execute.call_args_list if "DROP SCHEMA" in str(call)]
        assert len(drop_calls) > 0, "DROP SCHEMA should have been executed"

    def test_create_connection_success(self):
        """Test successful connection creation."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
        ):
            import benchbox.platforms.trino as trino_module

            with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
                connection = adapter.create_connection()

        assert connection == mock_connection
        mock_cursor.execute.assert_called_with("SELECT 1")
        mock_cursor.fetchone.assert_called_once()
        mock_cursor.close.assert_called_once()

    def test_create_connection_local_refused_raises_friendly_error(self):
        """A local connection failure should surface a helpful error message."""
        try:
            adapter = TrinoAdapter(host="localhost", port=8080)
        except ImportError:
            pytest.skip("Trino drivers not installed")

        import benchbox.platforms.trino as trino_module

        connection_error = Exception(
            "HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /v1/statement "
            "(Caused by NewConnectionError: Failed to establish a new connection: [Errno 61] Connection refused)"
        )

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(trino_module.trino.dbapi, "connect", side_effect=connection_error),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                adapter.create_connection()

        assert "Trino is not running on localhost:8080" in str(excinfo.value)

    def test_create_connection_remote_refused_re_raises_original_error(self):
        """Remote host failures should not be replaced with local-only guidance."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com", port=8080)
        except ImportError:
            pytest.skip("Trino drivers not installed")

        import benchbox.platforms.trino as trino_module

        connection_error = Exception(
            "HTTPConnectionPool(host='trino-coordinator.example.com', port=8080): Max retries exceeded with url: /v1/statement "
            "(Caused by NewConnectionError: Failed to establish a new connection: [Errno 61] Connection refused)"
        )

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(trino_module.trino.dbapi, "connect", side_effect=connection_error),
        ):
            with pytest.raises(Exception) as excinfo:
                adapter.create_connection()

        assert "trino-coordinator.example.com" in str(excinfo.value)

    def test_create_connection_creates_schema(self):
        """Test connection creation with schema creation."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="new_schema",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            # First call returns False (schema doesn't exist), second returns True (just created)
            patch.object(adapter, "check_server_database_exists", side_effect=[False, True]),
        ):
            import benchbox.platforms.trino as trino_module

            with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
                adapter.create_connection()

        # Verify CREATE SCHEMA was executed
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE SCHEMA" in call for call in execute_calls)

    def test_create_connection_keeps_session_properties_on_final_connection_after_auto_select(self, monkeypatch):
        """Bootstrap connections should not receive catalog-scoped session properties."""
        import benchbox.platforms.trino as trino_module

        mock_dbapi = Mock()
        monkeypatch.setattr(trino_module, "trino", SimpleNamespace(dbapi=mock_dbapi))

        catalog_connection = Mock()
        catalog_cursor = Mock()
        catalog_cursor.fetchall.return_value = [("memory",), ("system",)]
        catalog_connection.cursor.return_value = catalog_cursor

        validation_catalog_connection = Mock()
        validation_catalog_cursor = Mock()
        validation_catalog_cursor.fetchall.return_value = [("memory",), ("system",)]
        validation_catalog_connection.cursor.return_value = validation_catalog_cursor

        schema_check_connection = Mock()
        schema_check_cursor = Mock()
        schema_check_cursor.fetchone.return_value = None
        schema_check_connection.cursor.return_value = schema_check_cursor

        schema_create_connection = Mock()
        schema_create_cursor = Mock()
        schema_create_connection.cursor.return_value = schema_create_cursor

        final_connection = Mock()
        final_cursor = Mock()
        final_cursor.fetchone.return_value = (1,)
        final_connection.cursor.return_value = final_cursor

        mock_dbapi.connect.side_effect = [
            catalog_connection,
            validation_catalog_connection,
            schema_check_connection,
            schema_create_connection,
            final_connection,
        ]

        session_properties = {"memory.query_partition_filter_required": "false"}
        adapter = TrinoAdapter(schema="new_schema", session_properties=session_properties)

        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection is final_connection
        assert adapter.catalog == "memory"

        connect_kwargs = [call.kwargs for call in mock_dbapi.connect.call_args_list]
        assert len(connect_kwargs) == 5
        assert all("session_properties" not in kwargs for kwargs in connect_kwargs[:4])
        assert connect_kwargs[2]["catalog"] == "memory"
        assert connect_kwargs[3]["catalog"] == "memory"
        assert connect_kwargs[4]["catalog"] == "memory"
        assert connect_kwargs[4]["session_properties"] == session_properties
        schema_create_cursor.execute.assert_called_once_with("CREATE SCHEMA IF NOT EXISTS memory.new_schema")

    def test_create_schema(self):
        """Test schema creation with Trino table definitions."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
                table_format="memory",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER, name VARCHAR(100));
            CREATE TABLE table2 (id INTEGER, data VARCHAR(255));
        """

        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = "CREATE TABLE table1 (id INTEGER, name VARCHAR(100));\nCREATE TABLE table2 (id INTEGER, data VARCHAR(255));"

            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0
        assert mock_cursor.execute.call_count >= 2
        mock_cursor.close.assert_called_once()

    def test_load_data_with_insert(self):
        """Test data loading using INSERT statements."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,test1\n2,test2\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "test_table" in table_stats
            assert table_stats["test_table"] == 2  # 2 rows in test data

            # Should execute qualified INSERT commands (catalog.schema.table)
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("INSERT INTO" in call and "test_table" in call for call in execute_calls)

        finally:
            temp_path.unlink()

    def test_load_data_with_tbl_files(self):
        """Test data loading with pipe-delimited .tbl files."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()

        # Create temporary test file with pipe delimiter
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|test1|\n2|test2|\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"customer": str(temp_path)}

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert "customer" in table_stats
            assert table_stats["customer"] == 2

        finally:
            temp_path.unlink()

    def test_external_table_mode_requires_staging_root(self):
        """External mode should require staging_root configuration."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com", catalog="hive", schema="analytics")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with pytest.raises(ValueError, match="requires --platform-option staging_root"):
            adapter.validate_external_table_requirements()

    def test_create_external_tables_generates_location_sql(self):
        """External mode should create tables with external_location and parquet format."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="hive",
                schema="analytics",
                staging_root="s3://benchbox/staging",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (9,)

        benchmark = Mock()
        benchmark.tables = {"orders": [Path("/tmp/orders.parquet")]}
        benchmark.get_schema.return_value = {
            "orders": {
                "columns": [
                    {"name": "o_orderkey", "type": "BIGINT"},
                    {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
                ]
            }
        }

        stats, _, _ = adapter.create_external_tables(benchmark, mock_connection, Path("/tmp"))

        assert stats["orders"] == 9
        executed_sql = " ".join(call.args[0] for call in mock_cursor.execute.call_args_list)
        assert "CREATE TABLE hive.analytics.orders" in executed_sql
        assert "external_location = 's3://benchbox/staging/orders/'" in executed_sql
        assert "format = 'PARQUET'" in executed_sql

    def test_load_data_does_not_invoke_external_registration(self):
        """Native load_data path should remain independent from external registration."""
        try:
            adapter = TrinoAdapter(host="trino-coordinator.example.com", catalog="memory", schema="default")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,test\n")
            temp_path = Path(f.name)

        mock_benchmark = Mock()
        mock_benchmark.tables = {"orders": str(temp_path)}

        try:
            with patch.object(
                adapter,
                "create_external_tables",
                side_effect=AssertionError("native load_data should not call create_external_tables"),
            ):
                stats, _, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))
            assert stats["orders"] == 1
        finally:
            temp_path.unlink()

    def test_configure_for_benchmark_olap(self):
        """Test OLAP benchmark configuration with Trino optimizations."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Should execute Trino OLAP optimizations
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("SET SESSION" in call for call in execute_calls)
        mock_cursor.close.assert_called_once()

    def test_execute_query_success(self):
        """Test successful query execution."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]

        result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)

        mock_cursor.execute.assert_called_with("SELECT * FROM test")
        mock_cursor.close.assert_called_once()

    def test_execute_query_failure(self):
        """Test query execution failure."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Query failed")

        result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"

        mock_cursor.close.assert_called_once()

    def test_get_query_plan(self):
        """Test query plan retrieval."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("Fragment 0 [SINGLE]",),
            ("    Output partitioning: SINGLE []",),
            ("    TableScan[memory:test_table]",),
        ]

        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM test_table")

        assert "Fragment 0 [SINGLE]" in plan
        assert "TableScan" in plan
        mock_cursor.close.assert_called_once()

    def test_close_connection(self):
        """Test connection closing."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()

        adapter.close_connection(mock_connection)

        mock_connection.close.assert_called_once()

    def test_get_platform_info(self):
        """Test platform information retrieval."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                port=8080,
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock query responses
        mock_cursor.fetchone.side_effect = [
            ("478",),  # Trino version
            (3,),  # Node count
        ]
        mock_cursor.fetchall.return_value = [
            ("memory",),
            ("system",),
        ]

        platform_info = adapter.get_platform_info(mock_connection)

        assert platform_info["platform_type"] == "trino"
        assert platform_info["platform_name"] == "Trino"
        assert platform_info["host"] == "trino-coordinator.example.com"
        assert platform_info["port"] == 8080
        assert platform_info["configuration"]["catalog"] == "memory"

    def test_supports_tuning_type(self):
        """Test tuning type support checking."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.DISTRIBUTION = "distribution"

            assert adapter.supports_tuning_type(mock_tuning_type.PARTITIONING) is True
            assert adapter.supports_tuning_type(mock_tuning_type.SORTING) is True
            # Trino doesn't support distribution keys like Redshift
            assert adapter.supports_tuning_type(mock_tuning_type.DISTRIBUTION) is False

    def test_generate_tuning_clause_iceberg(self):
        """Test tuning clause generation for Iceberg tables."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                table_format="iceberg",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        # Mock partition column
        mock_partition_col = Mock()
        mock_partition_col.name = "event_date"
        mock_partition_col.order = 1

        # Mock sort column
        mock_sort_col = Mock()
        mock_sort_col.name = "event_time"
        mock_sort_col.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.SORTING = "sorting"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.PARTITIONING:
                    return [mock_partition_col]
                elif tuning_type == mock_tuning_type.SORTING:
                    return [mock_sort_col]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            clause = adapter.generate_tuning_clause(mock_tuning)

            assert "WITH" in clause
            assert "partitioning" in clause
            assert "event_date" in clause
            assert "sorted_by" in clause
            assert "event_time" in clause

    def test_generate_tuning_clause_none(self):
        """Test tuning clause generation with None input."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        clause = adapter.generate_tuning_clause(None)
        assert clause == ""

    def test_apply_constraint_configuration(self):
        """Test constraint configuration application."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_primary_key_config = Mock()
        mock_primary_key_config.enabled = True
        mock_foreign_key_config = Mock()
        mock_foreign_key_config.enabled = True

        # Should not raise exception - constraints are informational in Trino
        adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, mock_connection)

    def test_from_config(self):
        """Test from_config() properly passes through all configuration parameters."""
        config = {
            "host": "trino-coordinator.example.com",
            "port": 8443,
            "catalog": "iceberg",
            "username": "test_user",
            "password": "test_pass",
            "http_scheme": "https",
            "table_format": "iceberg",
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "verify_ssl": True,
            "session_properties": {"query_max_memory": "1GB"},
        }

        try:
            adapter = TrinoAdapter.from_config(config)
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.host == "trino-coordinator.example.com"
        assert adapter.port == 8443
        assert adapter.catalog == "iceberg"
        assert adapter.username == "test_user"
        assert adapter.password == "test_pass"
        assert adapter.http_scheme == "https"
        assert adapter.table_format == "iceberg"
        assert adapter.verify_ssl is True
        assert adapter.session_properties == {"query_max_memory": "1GB"}

    def test_from_config_generates_schema_name(self):
        """Test from_config() generates schema name from benchmark config."""
        config = {
            "host": "trino-coordinator.example.com",
            "catalog": "memory",
            "benchmark": "tpch",
            "scale_factor": 10.0,
        }

        try:
            adapter = TrinoAdapter.from_config(config)
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Schema should be generated from benchmark config
        assert adapter.schema is not None
        assert "tpch" in adapter.schema.lower() or "sf10" in adapter.schema.lower()

    def test_normalize_table_name_in_sql(self):
        """Test table name normalization in SQL."""
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        sql = 'CREATE TABLE "CUSTOMER" (id INTEGER, name VARCHAR(100))'
        normalized = adapter._normalize_table_name_in_sql(sql)

        assert "CREATE TABLE customer" in normalized

    def test_optimize_table_definition_memory(self):
        """Test table definition optimization for memory catalog."""
        try:
            adapter = TrinoAdapter(table_format="memory")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        sql = "CREATE TABLE test (id INTEGER) WITH (format='PARQUET')"
        optimized = adapter._optimize_table_definition(sql)

        # Memory catalog should strip WITH clause
        assert "WITH" not in optimized

    def test_optimize_table_definition_iceberg(self):
        """Test table definition optimization for Iceberg tables."""
        try:
            adapter = TrinoAdapter(table_format="iceberg")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        sql = "CREATE TABLE test (id INTEGER, name VARCHAR(100))"
        optimized = adapter._optimize_table_definition(sql)

        # Iceberg should add format specification
        assert "WITH" in optimized
        assert "PARQUET" in optimized

    def test_get_existing_tables(self):
        """Test getting list of existing tables."""
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("table1",), ("table2",), ("TABLE3",)]

        tables = adapter._get_existing_tables(mock_connection)

        assert tables == ["table1", "table2", "table3"]  # All lowercase
        mock_cursor.execute.assert_called_with("SHOW TABLES")

    def test_analyze_table_memory_skipped(self):
        """Test that ANALYZE is skipped for memory catalog."""
        try:
            adapter = TrinoAdapter(table_format="memory")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_connection, "test_table")

        # ANALYZE should not be called for memory catalog
        mock_cursor.execute.assert_not_called()

    def test_analyze_table_iceberg(self):
        """Test that ANALYZE is called for Iceberg catalog."""
        try:
            adapter = TrinoAdapter(table_format="iceberg")
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_connection, "test_table")

        mock_cursor.execute.assert_called_once_with("ANALYZE test_table")

    def test_session_properties_configuration(self):
        """Test session properties configuration."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                session_properties={
                    "query_max_memory": "2GB",
                    "join_reordering_strategy": "AUTOMATIC",
                },
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        assert adapter.session_properties["query_max_memory"] == "2GB"
        assert adapter.session_properties["join_reordering_strategy"] == "AUTOMATIC"

    def test_timezone_configuration(self):
        """Test timezone configuration."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                timezone="America/New_York",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        params = adapter._get_connection_params()
        assert params["timezone"] == "America/New_York"

    def test_encoding_configuration(self):
        """Test spooling protocol encoding configuration."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                encoding="json+zstd",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        params = adapter._get_connection_params()
        assert params["encoding"] == "json+zstd"

    def test_validate_identifier_valid(self):
        """Test valid SQL identifier validation."""
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Valid identifiers
        assert adapter._validate_identifier("my_schema") is True
        assert adapter._validate_identifier("catalog123") is True
        assert adapter._validate_identifier("_private") is True
        assert adapter._validate_identifier("test-schema") is True
        assert adapter._validate_identifier("MySchema") is True

    def test_validate_identifier_invalid(self):
        """Test invalid SQL identifier validation (prevents SQL injection)."""
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Invalid identifiers - potential SQL injection attempts
        assert adapter._validate_identifier("") is False
        assert adapter._validate_identifier(None) is False
        assert adapter._validate_identifier("schema; DROP TABLE users") is False
        assert adapter._validate_identifier("schema'--") is False
        assert adapter._validate_identifier("123schema") is False  # Can't start with number
        assert adapter._validate_identifier("a" * 129) is False  # Too long
        assert adapter._validate_identifier("schema.table") is False  # Dots not allowed
        assert adapter._validate_identifier('schema"quote') is False  # Quotes not allowed

    def test_drop_database_rejects_invalid_identifier(self):
        """Test that drop_database rejects SQL injection attempts."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
                catalog="memory",
                schema="default",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Attempting SQL injection should raise ValueError
        with pytest.raises(ValueError, match="Invalid catalog or schema identifier"):
            adapter.drop_database(schema="test; DROP TABLE users", catalog="memory")

        with pytest.raises(ValueError, match="Invalid catalog or schema identifier"):
            adapter.drop_database(schema="test", catalog="memory'--")

    def test_test_connection_success(self):
        """Test successful connection test."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", return_value=mock_connection):
            result = adapter.test_connection()

        assert result is True
        mock_cursor.execute.assert_called_with("SELECT 1")
        mock_cursor.close.assert_called_once()
        mock_connection.close.assert_called_once()

    def test_test_connection_failure(self):
        """Test failed connection test."""
        try:
            adapter = TrinoAdapter(
                host="trino-coordinator.example.com",
            )
        except ImportError:
            pytest.skip("Trino drivers not installed")

        import benchbox.platforms.trino as trino_module

        with patch.object(trino_module.trino.dbapi, "connect", side_effect=Exception("Connection refused")):
            result = adapter.test_connection()

        assert result is False

    def test_trino_only_not_presto(self):
        """Verify this adapter is explicitly for Trino, NOT PrestoDB.

        The TrinoAdapter uses the 'trino' Python package and 'trino' SQL dialect,
        which are incompatible with PrestoDB (Meta's Presto fork).

        Key differences that prevent PrestoDB compatibility:
        - Driver: Uses 'trino' package, PrestoDB needs 'presto-python-client'
        - Dialect: Uses SQLGlot 'trino' dialect, not 'presto'
        - Headers: Trino uses X-Trino-* headers, Presto uses X-Presto-*
        - System tables: Different metadata schemas between forks

        For AWS managed Presto/Trino, use AthenaAdapter instead.
        """
        try:
            adapter = TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

        # Verify dialect is explicitly 'trino', not 'presto'
        assert adapter.get_target_dialect() == "trino"
        assert adapter._dialect == "trino"

        # Verify platform name is 'Trino', not 'Presto'
        assert adapter.platform_name == "Trino"
        assert "Presto" not in adapter.platform_name


class TestTrinoLocalHostDetection:
    """Tests for _is_local_host helper."""

    def _adapter(self):
        try:
            return TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_localhost_string(self):
        adapter = self._adapter()
        assert adapter._is_local_host("localhost") is True

    def test_ipv4_loopback(self):
        adapter = self._adapter()
        assert adapter._is_local_host("127.0.0.1") is True

    def test_ipv6_loopback(self):
        adapter = self._adapter()
        assert adapter._is_local_host("::1") is True

    def test_dot_local_hostname(self):
        adapter = self._adapter()
        assert adapter._is_local_host("my-machine.local") is True

    def test_external_host_is_not_local(self):
        adapter = self._adapter()
        assert adapter._is_local_host("trino.example.com") is False

    def test_none_is_not_local(self):
        adapter = self._adapter()
        assert adapter._is_local_host(None) is False

    def test_empty_string_is_not_local(self):
        adapter = self._adapter()
        assert adapter._is_local_host("") is False


class TestTrinoConnectionErrorDetection:
    """Tests for _error_indicates_connection_refused and _build_friendly_connection_error."""

    def _adapter(self, **kwargs):
        try:
            return TrinoAdapter(**kwargs)
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_connection_refused_message_detected(self):
        adapter = self._adapter()
        exc = Exception("connection refused: port 8080")
        assert adapter._error_indicates_connection_refused(exc) is True

    def test_max_retries_message_detected(self):
        adapter = self._adapter()
        exc = Exception("Max retries exceeded with url")
        assert adapter._error_indicates_connection_refused(exc) is True

    def test_other_error_not_detected(self):
        adapter = self._adapter()
        exc = Exception("Authentication failed: invalid credentials")
        assert adapter._error_indicates_connection_refused(exc) is False

    def test_friendly_error_for_local_refused(self):
        adapter = self._adapter(host="localhost", port=8080)
        exc = Exception("connection refused")
        msg = adapter._build_friendly_connection_error(exc)
        assert msg is not None
        assert "localhost" in msg
        assert "8080" in msg

    def test_no_friendly_error_for_remote_host(self):
        adapter = self._adapter(host="trino.example.com")
        exc = Exception("connection refused")
        msg = adapter._build_friendly_connection_error(exc)
        assert msg is None

    def test_no_friendly_error_for_non_refused_local(self):
        adapter = self._adapter(host="localhost")
        exc = Exception("Authentication failed")
        msg = adapter._build_friendly_connection_error(exc)
        assert msg is None


class TestTrinoValueFormatting:
    """Tests for the shared presto_trino_utils value-formatting helpers."""

    def test_is_date_value_valid_date(self):
        from benchbox.platforms.presto_trino_utils import is_date_value

        assert is_date_value("1998-12-31") is True

    def test_is_date_value_regex_only_checks_format(self):
        from benchbox.platforms.presto_trino_utils import is_date_value

        assert is_date_value("12/31/1998") is False
        assert is_date_value("1998-13-99") is True  # YYYY-MM-DD pattern matches; no semantic validation
        assert is_date_value("not-a-date") is False

    def test_escape_empty_string_becomes_null(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("") == "NULL"

    def test_escape_null_string_becomes_null(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("null") == "NULL"
        assert escape_insert_value("NULL") == "NULL"

    def test_escape_date_value(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("1998-01-15") == "DATE '1998-01-15'"

    def test_escape_numeric_value_unquoted(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("42") == "42"
        assert escape_insert_value("3.14") == "3.14"

    def test_escape_string_value_quoted(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("hello world") == "'hello world'"

    def test_escape_string_with_single_quote(self):
        from benchbox.platforms.presto_trino_utils import escape_insert_value

        assert escape_insert_value("O'Brien") == "'O''Brien'"


class TestTrinoTableDefinitionOptimization:
    """Tests for _optimize_table_definition."""

    def _adapter(self, table_format="memory"):
        try:
            return TrinoAdapter(table_format=table_format)
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_non_create_table_statement_unchanged(self):
        adapter = self._adapter()
        sql = "INSERT INTO foo VALUES (1)"
        assert adapter._optimize_table_definition(sql) == sql

    def test_memory_format_removes_with_clause(self):
        adapter = self._adapter(table_format="memory")
        sql = "CREATE TABLE orders (id BIGINT) WITH (format = 'ORC')"
        result = adapter._optimize_table_definition(sql)
        assert "WITH" not in result
        assert "CREATE TABLE orders" in result

    def test_iceberg_format_adds_parquet_when_no_with(self):
        adapter = self._adapter(table_format="iceberg")
        sql = "CREATE TABLE orders (id BIGINT)"
        result = adapter._optimize_table_definition(sql)
        assert "WITH (format = 'PARQUET')" in result

    def test_iceberg_format_preserves_existing_with(self):
        adapter = self._adapter(table_format="iceberg")
        sql = "CREATE TABLE orders (id BIGINT) WITH (format = 'ORC')"
        result = adapter._optimize_table_definition(sql)
        # Already has WITH, should not add another
        assert result.count("WITH") == 1

    def test_hive_format_adds_parquet_when_no_with(self):
        adapter = self._adapter(table_format="hive")
        sql = "CREATE TABLE orders (id BIGINT)"
        result = adapter._optimize_table_definition(sql)
        assert "WITH (format = 'PARQUET')" in result

    @pytest.mark.parametrize(
        ("table_format", "adds_format"),
        [("memory", False), ("hive", True), ("iceberg", True), ("delta", False)],
    )
    def test_strips_inline_primary_key_metadata(self, table_format, adds_format):
        adapter = self._adapter(table_format=table_format)
        sql = "CREATE TABLE kind_type (id INTEGER PRIMARY KEY, kind VARCHAR(15) NOT NULL)"
        result = adapter._optimize_table_definition(sql)
        result_upper = result.upper()

        assert "PRIMARY KEY" not in result_upper
        assert "id INTEGER" in result
        if table_format == "memory":
            assert "NOT NULL" not in result_upper
        else:
            assert "NOT NULL" in result_upper
        if adds_format:
            assert "WITH (format = 'PARQUET')" in result
        else:
            assert "WITH" not in result_upper

    @pytest.mark.parametrize(
        ("table_format", "adds_format"),
        [("memory", False), ("hive", True), ("iceberg", True), ("delta", False)],
    )
    def test_strips_table_level_primary_key_metadata_with_nested_expression(self, table_format, adds_format):
        adapter = self._adapter(table_format=table_format)
        sql = "CREATE TABLE edge_case (id BIGINT, other_id BIGINT, PRIMARY KEY (id, coalesce(other_id, 0)))"
        result = adapter._optimize_table_definition(sql)
        result_upper = result.upper()

        assert "PRIMARY KEY" not in result_upper
        assert "coalesce" not in result
        assert "id BIGINT" in result
        assert "other_id BIGINT" in result
        if adds_format:
            assert "WITH (format = 'PARQUET')" in result
        else:
            assert "WITH" not in result_upper


class TestTrinoConfigureForBenchmark:
    """Tests for configure_for_benchmark."""

    def _adapter(self):
        try:
            return TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_olap_type_executes_session_settings(self):
        adapter = self._adapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "olap")

        executed_sql = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "optimizer_hash_generation_enabled" in executed_sql
        assert "join_reordering_strategy" in executed_sql
        mock_cursor.close.assert_called_once()

    def test_tpch_type_executes_session_settings(self):
        adapter = self._adapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "tpch")

        assert mock_cursor.execute.call_count >= 1

    def test_oltp_type_no_session_settings(self):
        adapter = self._adapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "oltp")

        mock_cursor.execute.assert_not_called()
        mock_cursor.close.assert_called_once()


class TestTrinoAutoSelectCatalog:
    """Tests for _auto_select_catalog catalog selection logic."""

    def _adapter(self):
        try:
            return TrinoAdapter()
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_returns_none_when_no_catalogs(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=[]):
            assert adapter._auto_select_catalog() is None

    def test_returns_none_when_only_system_catalogs(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=["jmx", "system"]):
            assert adapter._auto_select_catalog() is None

    def test_prefers_hive_over_memory(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=["memory", "hive", "system"]):
            assert adapter._auto_select_catalog() == "hive"

    def test_prefers_iceberg_over_memory(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=["memory", "iceberg"]):
            assert adapter._auto_select_catalog() == "iceberg"

    def test_falls_back_to_memory_when_no_preferred(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=["memory", "system"]):
            assert adapter._auto_select_catalog() == "memory"

    def test_falls_back_to_first_usable_catalog(self):
        adapter = self._adapter()
        with patch.object(adapter, "_get_available_catalogs", return_value=["custom_catalog", "another"]):
            assert adapter._auto_select_catalog() == "custom_catalog"


class TestTrinoTuningSupport:
    """Tests for supports_tuning_type and generate_tuning_clause."""

    def _adapter(self, **kwargs):
        try:
            return TrinoAdapter(**kwargs)
        except ImportError:
            pytest.skip("Trino drivers not installed")

    def test_supports_partitioning_and_sorting(self):
        from benchbox.core.tuning.interface import TuningType

        adapter = self._adapter()
        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
        assert adapter.supports_tuning_type(TuningType.SORTING) is True

    def test_does_not_support_primary_keys(self):
        from benchbox.core.tuning.interface import TuningType

        adapter = self._adapter()
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is False

    def test_generate_tuning_clause_returns_empty_for_none(self):
        adapter = self._adapter()
        assert adapter.generate_tuning_clause(None) == ""

    def test_generate_tuning_clause_returns_empty_for_no_tuning(self):
        from unittest.mock import Mock

        adapter = self._adapter()
        table_tuning = Mock()
        table_tuning.has_any_tuning.return_value = False
        assert adapter.generate_tuning_clause(table_tuning) == ""

    def test_generate_tuning_clause_hive_partitioning(self):
        from unittest.mock import Mock

        from benchbox.core.tuning.interface import TuningType

        adapter = self._adapter(table_format="hive")
        col1 = Mock()
        col1.name = "l_shipdate"
        col1.order = 1
        table_tuning = Mock()
        table_tuning.has_any_tuning.return_value = True
        table_tuning.get_columns_by_type.side_effect = lambda t: ([col1] if t == TuningType.PARTITIONING else [])

        result = adapter.generate_tuning_clause(table_tuning)
        assert "PARTITIONED BY" in result
        assert "l_shipdate" in result

    def test_generate_tuning_clause_iceberg_partitioning(self):
        from unittest.mock import Mock

        from benchbox.core.tuning.interface import TuningType

        adapter = self._adapter(table_format="iceberg")
        col1 = Mock()
        col1.name = "l_shipdate"
        col1.order = 1
        table_tuning = Mock()
        table_tuning.has_any_tuning.return_value = True
        table_tuning.get_columns_by_type.side_effect = lambda t: ([col1] if t == TuningType.PARTITIONING else [])

        result = adapter.generate_tuning_clause(table_tuning)
        assert "WITH" in result
        assert "partitioning" in result
        assert "l_shipdate" in result
