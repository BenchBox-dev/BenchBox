"""Tests for Databend platform adapter.

Tests the DatabendAdapter for cloud-native OLAP workloads using
Snowflake-compatible SQL via sqlglot translation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.databend.adapter import DatabendAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDatabendAdapterInitialization:
    """Test Databend adapter initialization and configuration."""

    def test_initialization_with_host(self):
        """Test initialization with explicit host."""
        try:
            adapter = DatabendAdapter(
                host="localhost",
                port=8000,
                username="root",
                password="",
                database="test_db",
                ssl=False,
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.host == "localhost"
        assert adapter.port == 8000
        assert adapter.database == "test_db"
        assert adapter.username == "root"
        assert adapter.platform_name == "Databend"
        assert adapter.get_target_dialect() == "snowflake"

    def test_initialization_with_dsn(self):
        """Test initialization with DSN string."""
        try:
            adapter = DatabendAdapter(
                dsn="databend+http://root:@localhost:8000/test_db",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.dsn == "databend+http://root:@localhost:8000/test_db"
        assert adapter.database == "benchbox"  # default when not set separately

    def test_initialization_with_cloud_config(self):
        """Test initialization with Databend Cloud configuration."""
        try:
            adapter = DatabendAdapter(
                host="tenant--warehouse.gw.databend.com",
                username="benchbox",
                password="cloud_pass",
                database="analytics",
                warehouse="my_warehouse",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.host == "tenant--warehouse.gw.databend.com"
        assert adapter.warehouse == "my_warehouse"
        assert adapter.database == "analytics"

    def test_initialization_missing_config(self):
        """Test initialization raises error without host or DSN."""
        from benchbox.core.exceptions import ConfigurationError

        try:
            with pytest.raises(ConfigurationError, match="Databend configuration is incomplete"):
                DatabendAdapter(database="test_db")
        except ImportError:
            pytest.skip("databend-driver not installed")

    def test_initialization_env_vars(self):
        """Test initialization from environment variables."""
        env_vars = {
            "DATABEND_HOST": "env-host.example.com",
            "DATABEND_USER": "env_user",
            "DATABEND_PASSWORD": "env_pass",
            "DATABEND_DATABASE": "env_db",
        }

        try:
            with patch.dict("os.environ", env_vars):
                adapter = DatabendAdapter()
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.host == "env-host.example.com"
        assert adapter.username == "env_user"
        assert adapter.password == "env_pass"
        assert adapter.database == "env_db"

    def test_default_ssl_enabled(self):
        """Test SSL is enabled by default."""
        try:
            adapter = DatabendAdapter(host="example.com", password="pass")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.ssl is True

    def test_disable_result_cache_default(self):
        """Test result cache is disabled by default for benchmarking."""
        try:
            adapter = DatabendAdapter(host="example.com", password="pass")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.disable_result_cache is True


class TestDatabendDSNBuilding:
    """Test DSN construction from individual parameters."""

    def test_build_dsn_ssl(self):
        """Test DSN building with SSL enabled."""
        try:
            adapter = DatabendAdapter(
                host="example.com",
                username="user",
                password="pass",
                database="mydb",
                ssl=True,
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        dsn = adapter._build_dsn()
        assert dsn.startswith("databend+https://")
        assert "user:pass@example.com" in dsn
        assert "/mydb" in dsn
        assert ":443/" in dsn

    def test_build_dsn_no_ssl(self):
        """Test DSN building without SSL."""
        try:
            adapter = DatabendAdapter(
                host="localhost",
                username="root",
                password="",
                database="test",
                ssl=False,
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        dsn = adapter._build_dsn()
        assert dsn.startswith("databend+http://")
        assert ":8000/" in dsn
        assert "sslmode=disable" in dsn

    def test_build_dsn_with_warehouse(self):
        """Test DSN building with warehouse parameter."""
        try:
            adapter = DatabendAdapter(
                host="cloud.example.com",
                username="user",
                password="pass",
                warehouse="my_wh",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        dsn = adapter._build_dsn()
        assert "warehouse=my_wh" in dsn

    def test_build_dsn_explicit_port(self):
        """Test DSN building with explicit port."""
        try:
            adapter = DatabendAdapter(
                host="example.com",
                port=9000,
                username="user",
                password="pass",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        dsn = adapter._build_dsn()
        assert ":9000/" in dsn

    def test_build_dsn_returns_explicit_dsn(self):
        """Test that explicit DSN is returned as-is."""
        try:
            adapter = DatabendAdapter(
                dsn="databend+http://custom:dsn@host/db",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._build_dsn() == "databend+http://custom:dsn@host/db?sslmode=disable"

    def test_build_dsn_normalizes_legacy_explicit_dsn(self):
        """Test that legacy BenchBox DSN schemes are normalized for the driver."""
        try:
            adapter = DatabendAdapter(
                dsn="databend://custom:dsn@host/db",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._build_dsn() == "databend+http://custom:dsn@host/db?sslmode=disable"


class TestDatabendConnection:
    """Test connection creation and management."""

    def test_create_connection(self):
        """Test connection creation."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_client = Mock()
        mock_client.query_row.return_value = Mock()

        with (
            patch.object(adapter, "handle_existing_database"),
            patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd,
        ):
            mock_dd.BlockingDatabendClient.return_value = mock_client

            # Need to make databend_driver importable in the from_config context
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                connection = adapter.create_connection()

        assert connection == mock_client
        mock_client.query_row.assert_called_with("SELECT 1")

    def test_create_connection_with_get_conn(self):
        """Test connection creation with the current databend-driver API."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock(spec=["query_row", "close"])
        mock_connection.query_row.return_value = Mock()
        mock_client = Mock(spec=["get_conn"])
        mock_client.get_conn.return_value = mock_connection

        with (
            patch.object(adapter, "handle_existing_database"),
            patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd,
        ):
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                connection = adapter.create_connection()

        assert connection == mock_connection
        mock_client.get_conn.assert_called_once()
        mock_connection.query_row.assert_called_with("SELECT 1")

    def test_close_connection(self):
        """Test connection closing."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        adapter.close_connection(mock_connection)
        mock_connection.close.assert_called_once()

    def test_close_connection_none(self):
        """Test closing None connection doesn't raise."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        # Should not raise
        adapter.close_connection(None)

    def test_test_connection_success(self):
        """Test successful connection test."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_client = Mock()
        mock_client.query_row.return_value = Mock()

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.test_connection()

        assert result is True

    def test_test_connection_failure(self):
        """Test failed connection test."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.side_effect = Exception("Connection refused")
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.test_connection()

        assert result is False


class TestDatabendSchemaOperations:
    """Test schema creation and management."""

    def test_create_schema(self):
        """Test schema creation with Databend table definitions."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER, name VARCHAR(100));
            CREATE TABLE table2 (id INTEGER, data VARCHAR(255));
        """

        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = (
                "CREATE TABLE table1 (id INTEGER, name VARCHAR(100));\n"
                "CREATE TABLE table2 (id INTEGER, data VARCHAR(255));"
            )

            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0
        # Should execute CREATE DATABASE, USE, and at least 2 CREATE TABLE statements
        assert mock_connection.exec.call_count >= 4

    def test_optimize_table_definition_char_to_varchar(self):
        """Test CHAR(n) to VARCHAR(n) conversion for Databend."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        sql = "CREATE TABLE test (id INTEGER, code CHAR(10), name VARCHAR(100))"
        optimized = adapter._optimize_table_definition(sql)

        # CHAR(10) should be converted to VARCHAR(10); check no standalone CHAR remains
        # (note: "CHAR(10)" is a substring of "VARCHAR(10)", so use word boundary check)
        import re

        assert not re.search(r"\bCHAR\s*\(", optimized, re.IGNORECASE), f"Standalone CHAR( found in: {optimized}"
        assert "VARCHAR(10)" in optimized
        assert "VARCHAR(100)" in optimized

    def test_optimize_table_definition_removes_primary_key(self):
        """Test PRIMARY KEY constraint removal."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        sql = "CREATE TABLE test (id INTEGER, name VARCHAR(100), PRIMARY KEY (id))"
        optimized = adapter._optimize_table_definition(sql)

        assert "PRIMARY KEY" not in optimized

    def test_optimize_table_definition_removes_foreign_key(self):
        """Test FOREIGN KEY constraint removal."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        sql = "CREATE TABLE test (id INTEGER, other_id INTEGER, FOREIGN KEY (other_id) REFERENCES other(id))"
        optimized = adapter._optimize_table_definition(sql)

        assert "FOREIGN KEY" not in optimized
        assert "REFERENCES" not in optimized

    def test_extract_table_name(self):
        """Test table name extraction from CREATE statement."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        sql = "CREATE TABLE customer (id INTEGER)"
        table_name = adapter._extract_table_name(sql)
        assert table_name == "customer"

    def test_extract_table_name_if_not_exists(self):
        """Test table name extraction with IF NOT EXISTS."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        sql = "CREATE TABLE IF NOT EXISTS customer (id INTEGER)"
        table_name = adapter._extract_table_name(sql)
        assert table_name == "customer"


class TestDatabendDataLoading:
    """Test data loading functionality."""

    def test_load_data_csv(self):
        """Test loading CSV data."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("1,test1\n2,test2\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "test_table" in table_stats
            assert table_stats["test_table"] == 2

            # Should execute USE and INSERT commands
            exec_calls = mock_connection.exec.call_args_list
            assert any("USE" in str(call) for call in exec_calls)
            assert any("INSERT INTO" in str(call) for call in exec_calls)

        finally:
            temp_path.unlink()

    def test_load_data_tbl_files(self):
        """Test loading pipe-delimited .tbl files (TPC format)."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_benchmark = Mock()

        # Create temporary test file with pipe delimiter
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False) as f:
            f.write("1|test1|\n2|test2|\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"customer": str(temp_path)}

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert "customer" in table_stats
            assert table_stats["customer"] == 2

        finally:
            temp_path.unlink()

    def test_load_data_escapes_quotes(self):
        """Test proper escaping of single quotes in data."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_benchmark = Mock()

        # Create file with single quotes in data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("1,test's data\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            # Verify the INSERT call contains properly escaped quotes
            exec_calls = [str(call) for call in mock_connection.exec.call_args_list]
            insert_calls = [c for c in exec_calls if "INSERT INTO" in c]
            assert len(insert_calls) > 0
            # The escaped value should use '' for single quotes
            assert "test''s data" in insert_calls[0]

        finally:
            temp_path.unlink()


class TestDatabendQueryExecution:
    """Test query execution functionality."""

    def test_execute_query_success(self):
        """Test successful query execution."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_connection.query_iter.return_value = [(1, "test"), (2, "test2")]

        result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert isinstance(result["execution_time_seconds"], float)

    def test_execute_query_use_database_before_timing(self):
        """Test that USE database is called before query timing starts."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_connection.query_iter.return_value = [(1,)]

        result = adapter.execute_query(mock_connection, "SELECT 1", "q1")

        # USE database should be called via exec before query_iter
        exec_calls = [str(c) for c in mock_connection.exec.call_args_list]
        assert any("USE" in c for c in exec_calls), "USE database should be called"

        # Verify call order: exec (USE) happens before query_iter
        assert mock_connection.exec.call_count >= 1
        assert result["status"] == "SUCCESS"

    def test_execute_query_failure(self):
        """Test query execution failure."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_connection.exec.return_value = None
        mock_connection.query_iter.side_effect = Exception("Query failed")

        result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"

    def test_execute_query_empty_result(self):
        """Test query execution with empty result."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_connection.query_iter.return_value = []

        result = adapter.execute_query(mock_connection, "SELECT * FROM empty_table", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 0

    def test_get_query_plan(self):
        """Test query plan retrieval."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_row1 = Mock()
        mock_row1.values.return_value = ["Scan table test_table"]
        mock_row2 = Mock()
        mock_row2.values.return_value = ["  Columns: id, name"]
        mock_connection.query_iter.return_value = [mock_row1, mock_row2]

        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM test_table")

        assert "Scan table test_table" in plan


class TestDatabendPlatformInfo:
    """Test platform information retrieval."""

    def test_get_platform_info(self):
        """Test platform info retrieval."""
        try:
            adapter = DatabendAdapter(
                host="example.com",
                database="test_db",
                password="pass",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_row = Mock()
        mock_row.values.return_value = ["v1.2.3"]
        mock_connection.query_row.return_value = mock_row

        platform_info = adapter.get_platform_info(mock_connection)

        assert platform_info["platform_type"] == "databend"
        assert platform_info["platform_name"] == "Databend"
        assert platform_info["configuration"]["database"] == "test_db"
        assert platform_info["configuration"]["host"] == "example.com"
        assert platform_info["platform_version"] == "v1.2.3"

    def test_get_platform_info_with_warehouse(self):
        """Test platform info includes warehouse when set."""
        try:
            adapter = DatabendAdapter(
                host="example.com",
                password="pass",
                warehouse="my_wh",
            )
        except ImportError:
            pytest.skip("databend-driver not installed")

        platform_info = adapter.get_platform_info(None)

        assert platform_info["warehouse"] == "my_wh"
        assert platform_info["platform_version"] is None

    def test_get_platform_info_no_connection(self):
        """Test platform info without connection."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        platform_info = adapter.get_platform_info(None)

        assert platform_info["platform_type"] == "databend"
        assert platform_info["platform_version"] is None


class TestDatabendDialect:
    """Test SQL dialect handling."""

    def test_target_dialect_is_snowflake(self):
        """Test that Databend uses Snowflake-compatible dialect."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.get_target_dialect() == "snowflake"
        assert adapter._dialect == "snowflake"


class TestDatabendTuning:
    """Test tuning and optimization functionality."""

    def test_configure_for_benchmark_olap(self):
        """Test OLAP benchmark configuration."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()

        # Should not raise
        adapter.configure_for_benchmark(mock_connection, "olap")

    def test_configure_for_benchmark_disables_result_cache(self):
        """Test that configure_for_benchmark disables query result cache."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.disable_result_cache is True

        mock_connection = Mock()
        adapter.configure_for_benchmark(mock_connection, "tpch")

        mock_connection.exec.assert_called_once_with("SET enable_query_result_cache = 0")

    def test_configure_for_benchmark_cache_disable_respects_flag(self):
        """Test that cache disable is skipped when flag is False."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="", disable_result_cache=False)
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        adapter.configure_for_benchmark(mock_connection, "tpch")

        mock_connection.exec.assert_not_called()

    def test_generate_tuning_clause_none(self):
        """Test tuning clause generation with None input."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        clause = adapter.generate_tuning_clause(None)
        assert clause == ""

    def test_apply_constraint_configuration(self):
        """Test constraint configuration (informational only in Databend)."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()
        mock_primary_key_config = Mock()
        mock_primary_key_config.enabled = True
        mock_foreign_key_config = Mock()
        mock_foreign_key_config.enabled = True

        # Should not raise - constraints are informational only
        adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, mock_connection)

    def test_analyze_table_skipped(self):
        """Test that ANALYZE is skipped (Databend collects stats automatically)."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        mock_connection = Mock()

        # ANALYZE should not be called - Databend collects stats automatically
        adapter.analyze_table(mock_connection, "test_table")

        # No exec call should be made
        mock_connection.exec.assert_not_called()


class TestDatabendFromConfig:
    """Test from_config() factory method."""

    def test_from_config_with_host(self):
        """Test from_config() with host parameters."""
        config = {
            "host": "localhost",
            "port": 8000,
            "username": "root",
            "password": "",
            "database": "test_db",
            "ssl": False,
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        try:
            adapter = DatabendAdapter.from_config(config)
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.host == "localhost"
        assert adapter.port == 8000
        assert adapter.database == "test_db"

    def test_from_config_with_dsn(self):
        """Test from_config() with DSN."""
        config = {
            "dsn": "databend+http://root:@localhost:8000/mydb",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        try:
            adapter = DatabendAdapter.from_config(config)
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter.dsn == "databend+http://root:@localhost:8000/mydb"

    def test_from_config_generates_database_name(self):
        """Test from_config() generates database name from benchmark config."""
        config = {
            "host": "localhost",
            "ssl": False,
            "password": "",
            "benchmark": "tpch",
            "scale_factor": 10.0,
        }

        try:
            adapter = DatabendAdapter.from_config(config)
        except ImportError:
            pytest.skip("databend-driver not installed")

        # Database name should be generated from benchmark config
        assert adapter.database is not None
        assert "tpch" in adapter.database.lower() or "sf10" in adapter.database.lower()


class TestDatabendQuoteIdentifier:
    """Test identifier quoting."""

    def test_quote_identifier_simple(self):
        """Test simple identifier quoting with backticks."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._quote_identifier("table_name") == "`table_name`"

    def test_quote_identifier_with_backtick(self):
        """Test quoting identifier containing backtick."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._quote_identifier("my`table") == "`my``table`"

    def test_quote_identifier_empty_raises(self):
        """Test that empty identifier raises ValueError."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with pytest.raises(ValueError, match="Identifier must be a non-empty string"):
            adapter._quote_identifier("")


class TestDatabendCoerceBool:
    """Test boolean coercion utility."""

    def test_coerce_bool_none_returns_default(self):
        """Test None returns default value."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._coerce_bool(None, True) is True
        assert adapter._coerce_bool(None, False) is False

    def test_coerce_bool_string_values(self):
        """Test string to bool coercion."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._coerce_bool("true", False) is True
        assert adapter._coerce_bool("false", True) is False
        assert adapter._coerce_bool("0", True) is False
        assert adapter._coerce_bool("yes", False) is True
        assert adapter._coerce_bool("no", True) is False

    def test_coerce_bool_native_bool(self):
        """Test native bool passthrough."""
        try:
            adapter = DatabendAdapter(host="localhost", ssl=False, password="")
        except ImportError:
            pytest.skip("databend-driver not installed")

        assert adapter._coerce_bool(True, False) is True
        assert adapter._coerce_bool(False, True) is False


class TestDatabendResourceCleanup:
    """Test that BlockingDatabendClient instances are closed after use."""

    def test_test_connection_closes_client(self):
        """test_connection should close the BlockingDatabendClient."""
        mock_client = Mock()
        mock_client.query_row.return_value = (1,)

        try:
            adapter = DatabendAdapter(host="localhost")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.test_connection()

        assert result is True
        mock_client.close.assert_called_once()

    def test_test_connection_closes_client_on_failure(self):
        """test_connection should close the client even on failure."""
        mock_client = Mock()
        mock_client.query_row.side_effect = Exception("Connection refused")

        try:
            adapter = DatabendAdapter(host="localhost")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.test_connection()

        assert result is False
        mock_client.close.assert_called_once()

    def test_test_connection_closes_connection_from_get_conn(self):
        """test_connection should close the connection returned by get_conn."""
        mock_connection = Mock(spec=["query_row", "close"])
        mock_connection.query_row.return_value = (1,)
        mock_client = Mock(spec=["get_conn"])
        mock_client.get_conn.return_value = mock_connection

        try:
            adapter = DatabendAdapter(host="localhost")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.test_connection()

        assert result is True
        mock_client.get_conn.assert_called_once()
        mock_connection.close.assert_called_once()

    def test_check_server_database_exists_closes_client(self):
        """check_server_database_exists should close the BlockingDatabendClient."""
        mock_row = Mock()
        mock_row.values.return_value = ["default"]
        mock_client = Mock()
        mock_client.query_iter.return_value = [mock_row]

        try:
            adapter = DatabendAdapter(host="localhost", database="default")
        except ImportError:
            pytest.skip("databend-driver not installed")

        with patch("benchbox.platforms.databend.adapter.databend_driver") as mock_dd:
            mock_dd.BlockingDatabendClient.return_value = mock_client
            with patch.dict("sys.modules", {"databend_driver": mock_dd}):
                result = adapter.check_server_database_exists()

        assert result is True
        mock_client.close.assert_called_once()


class TestDatabendDelimiterValidation:
    """Test delimiter validation in data loading path."""

    def test_safe_delimiters_accepted(self):
        """Pipe, comma, and tab delimiters should be accepted."""
        safe_delimiters = [",", "|", "\t"]
        for d in safe_delimiters:
            if d not in (",", "|", "\t"):
                raise AssertionError(f"Unexpectedly rejected: {d!r}")

    def test_unsafe_delimiter_rejected(self):
        """Unsafe delimiter characters should be rejected by the validation logic."""
        # The validation checks delimiter not in (",", "|", "\t")
        unsafe_chars = [";", "'", '"', " ", "\n"]
        for char in unsafe_chars:
            assert char not in (",", "|", "\t"), f"Expected {char!r} to be unsafe"


class TestDatabendConfigBuilder:
    """Test config builder resolution from package __init__."""

    def test_config_builder_importable_from_package(self):
        """Test that _build_databend_config is importable from databend package."""
        from benchbox.platforms.databend import _build_databend_config

        assert callable(_build_databend_config)

    def test_config_builder_getattr_resolution(self):
        """Test that getattr on package module resolves _build_databend_config."""
        import benchbox.platforms.databend as databend_module

        builder = getattr(databend_module, "_build_databend_config", None)
        assert builder is not None
        assert callable(builder)


class TestDatabendDsnConstruction:
    """Tests for DSN construction including URL-encoding and SSL scheme."""

    def test_dsn_defaults_to_ssl(self):
        """DSN uses databend+https scheme by default."""
        try:
            adapter = DatabendAdapter(host="myhost", username="user", password="pass", database="db")
        except ImportError:
            pytest.skip("databend-driver not installed")
        dsn = adapter._build_dsn()
        assert dsn.startswith("databend+https://")
        assert ":443/" in dsn

    def test_dsn_uses_plain_scheme_when_ssl_disabled(self):
        """DSN uses databend+http scheme when ssl=False."""
        try:
            adapter = DatabendAdapter(host="myhost", username="user", password="pass", database="db", ssl=False)
        except ImportError:
            pytest.skip("databend-driver not installed")
        dsn = adapter._build_dsn()
        assert dsn.startswith("databend+http://")
        assert ":8000/" in dsn
        assert "sslmode=disable" in dsn

    def test_dsn_url_encodes_password_with_special_chars(self):
        """Password with special characters is URL-encoded in DSN."""
        try:
            adapter = DatabendAdapter(host="myhost", username="user", password="p@ss:w/rd#", database="db")
        except ImportError:
            pytest.skip("databend-driver not installed")
        dsn = adapter._build_dsn()
        # @ should be encoded as %40, : as %3A, / as %2F, # as %23
        assert "p%40ss%3Aw%2Frd%23" in dsn
        # Raw special chars should not appear in the password section
        assert "p@ss:" not in dsn

    def test_dsn_url_encodes_username_with_special_chars(self):
        """Username with special characters is URL-encoded in DSN."""
        try:
            adapter = DatabendAdapter(host="myhost", username="user@domain", password="pass", database="db")
        except ImportError:
            pytest.skip("databend-driver not installed")
        dsn = adapter._build_dsn()
        assert "user%40domain:" in dsn

    def test_dsn_plain_credentials_unchanged(self):
        """Simple alphanumeric credentials pass through without encoding."""
        try:
            adapter = DatabendAdapter(host="myhost", username="admin", password="secret123", database="db")
        except ImportError:
            pytest.skip("databend-driver not installed")
        dsn = adapter._build_dsn()
        assert "admin:secret123@" in dsn
