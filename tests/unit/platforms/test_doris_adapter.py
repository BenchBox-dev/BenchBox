"""Tests for Apache Doris platform adapter.

Tests the DorisAdapter for self-hosted Apache Doris deployments using
MySQL protocol (PyMySQL) and Stream Load HTTP API.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import gzip
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base.data_loading import CsvDialect, DataSource
from benchbox.platforms.doris import DorisAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDorisIdentifierValidation:
    """Tests for SQL injection prevention via identifier validation."""

    def test_init_rejects_invalid_database(self):
        """DorisAdapter should reject invalid database names at init time."""
        with pytest.raises(ValueError, match="Invalid database identifier"):
            DorisAdapter(database="DROP TABLE; --")

    def test_init_accepts_valid_database(self):
        """DorisAdapter should accept valid alphanumeric database names."""
        adapter = DorisAdapter(database="benchbox_tpch")
        assert adapter.database == "benchbox_tpch"


class TestDorisAdapterInitialization:
    """Test Doris adapter initialization and configuration."""

    def test_initialization_default_config(self):
        """Test initialization with default configuration."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.host == "localhost"
        assert adapter.port == 9030
        assert adapter.http_port == 8030
        assert adapter.username == "root"
        assert adapter.database == "benchbox"
        assert adapter.platform_name == "Apache Doris"
        assert adapter.get_target_dialect() == "doris"

    def test_initialization_custom_config(self):
        """Test initialization with custom configuration."""
        try:
            adapter = DorisAdapter(
                host="doris-fe.example.com",
                port=9031,
                http_port=8031,
                username="admin",
                password="secret",
                database="my_benchmark",
            )
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.host == "doris-fe.example.com"
        assert adapter.port == 9031
        assert adapter.http_port == 8031
        assert adapter.username == "admin"
        assert adapter.password == "secret"
        assert adapter.database == "my_benchmark"

    def test_init_uses_simple_defaults_not_env_vars(self):
        """Test that __init__ uses simple defaults; env var resolution is the builder's job."""
        try:
            with patch.dict(
                "os.environ",
                {
                    "DORIS_HOST": "env-host",
                    "DORIS_PORT": "9032",
                    "DORIS_HTTP_PORT": "8032",
                    "DORIS_USER": "env-user",
                    "DORIS_PASSWORD": "env-pass",
                },
            ):
                # Direct construction bypasses the builder; __init__ uses Python defaults.
                adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.host == "localhost"
        assert adapter.port == 9030
        assert adapter.http_port == 8030
        assert adapter.username == "root"
        assert adapter.password == ""

    def test_builder_resolves_env_vars(self):
        """Test that the config builder (_build_doris_config) resolves env vars."""
        from benchbox.platforms.doris import _build_doris_config

        with patch.dict(
            "os.environ",
            {
                "DORIS_HOST": "env-host",
                "DORIS_PORT": "9032",
                "DORIS_HTTP_PORT": "8032",
                "DORIS_USER": "env-user",
                "DORIS_PASSWORD": "env-pass",
            },
        ):
            config = _build_doris_config("doris", {}, {}, None)

        assert config.host == "env-host"
        assert config.port == 9032
        assert config.http_port == 8032
        assert config.username == "env-user"
        assert config.password == "env-pass"

    def test_dialect_is_doris(self):
        """Test that Doris uses the 'doris' SQLGlot dialect."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.get_target_dialect() == "doris"
        assert adapter._dialect == "doris"


class TestDorisFromConfig:
    """Test from_config() factory method."""

    def test_from_config_basic(self):
        """Test from_config() with basic options."""
        config = {
            "host": "my-doris-host",
            "port": 9030,
            "database": "test_db",
            "username": "root",
            "password": "pass",
        }

        try:
            adapter = DorisAdapter.from_config(config)
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.host == "my-doris-host"
        assert adapter.port == 9030
        assert adapter.database == "test_db"

    def test_from_config_generates_database_name(self):
        """Test from_config() generates database name from benchmark config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }

        try:
            adapter = DorisAdapter.from_config(config)
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.database is not None
        assert "benchbox" in adapter.database.lower()
        assert "tpch" in adapter.database.lower()

    def test_from_config_default_database(self):
        """Test from_config() uses 'benchbox' as default database."""
        config = {}

        try:
            adapter = DorisAdapter.from_config(config)
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter.database == "benchbox"


class TestDorisConnection:
    """Test connection creation and management."""

    def test_create_connection(self):
        """Test connection creation via MySQL protocol."""
        try:
            adapter = DorisAdapter(
                host="localhost",
                port=9030,
                database="test_db",
                username="root",
                password="",
            )
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch("benchbox.platforms.doris.pymysql") as mock_pymysql,
        ):
            mock_pymysql.connect.return_value = mock_connection
            connection = adapter.create_connection()

        from benchbox.platforms.doris import _DorisConnectionWrapper

        assert isinstance(connection, _DorisConnectionWrapper)
        assert connection._conn == mock_connection
        mock_pymysql.connect.assert_called_once()
        call_kwargs = mock_pymysql.connect.call_args.kwargs
        assert call_kwargs["host"] == "localhost"
        assert call_kwargs["port"] == 9030
        assert call_kwargs["database"] == "test_db"
        assert call_kwargs["user"] == "root"
        mock_cursor.execute.assert_called_with("SELECT 1")
        mock_cursor.fetchone.assert_called_once()
        mock_cursor.close.assert_called_once()

    def test_create_connection_creates_database_if_missing(self):
        """Test that create_connection creates database if it doesn't exist."""
        try:
            adapter = DorisAdapter(database="new_db")
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=False),
            patch.object(adapter, "_create_database") as mock_create_db,
            patch("benchbox.platforms.doris.pymysql") as mock_pymysql,
        ):
            mock_pymysql.connect.return_value = mock_connection
            adapter.create_connection()

        mock_create_db.assert_called_once()

    def test_close_connection(self):
        """Test connection closing."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        adapter.close_connection(mock_connection)
        mock_connection.close.assert_called_once()

    def test_close_connection_none(self):
        """Test closing None connection doesn't raise."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        # Should not raise
        adapter.close_connection(None)

    def test_test_connection_success(self):
        """Test successful connection test."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.return_value = mock_connection
            result = adapter.test_connection()

        assert result is True
        mock_cursor.execute.assert_called_with("SELECT 1")
        mock_cursor.close.assert_called_once()
        mock_connection.close.assert_called_once()

    def test_test_connection_failure(self):
        """Test failed connection test."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.side_effect = Exception("Connection refused")
            result = adapter.test_connection()

        assert result is False


class TestDorisDatabaseOperations:
    """Test database existence checking and management."""

    def test_check_server_database_exists_true(self):
        """Test database existence check when database exists."""
        try:
            adapter = DorisAdapter(database="test_db")
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("information_schema",), ("test_db",), ("other_db",)]

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.return_value = mock_connection
            result = adapter.check_server_database_exists()

        assert result is True
        mock_cursor.execute.assert_called_with("SHOW DATABASES")

    def test_check_server_database_exists_false(self):
        """Test database existence check when database doesn't exist."""
        try:
            adapter = DorisAdapter(database="nonexistent_db")
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("information_schema",), ("other_db",)]

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.return_value = mock_connection
            result = adapter.check_server_database_exists()

        assert result is False

    def test_check_server_database_exists_connection_error(self):
        """Test database check returns False on connection error."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.side_effect = Exception("Connection refused")
            result = adapter.check_server_database_exists()

        assert result is False

    def test_drop_database(self):
        """Test database dropping."""
        try:
            adapter = DorisAdapter(database="drop_me")
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.return_value = mock_connection
            adapter.drop_database()

        mock_cursor.execute.assert_called_with("DROP DATABASE IF EXISTS `drop_me`")

    def test_drop_database_invalid_identifier(self):
        """Test drop database rejects invalid identifiers."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter.drop_database(database="invalid; DROP TABLE")

    def test_create_database(self):
        """Test database creation."""
        try:
            adapter = DorisAdapter(database="new_db")
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("benchbox.platforms.doris.pymysql") as mock_pymysql:
            mock_pymysql.connect.return_value = mock_connection
            adapter._create_database()

        mock_cursor.execute.assert_called_with("CREATE DATABASE IF NOT EXISTS `new_db`")

    def test_get_existing_tables(self):
        """Test getting list of existing tables."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("CUSTOMER",), ("orders",), ("LineItem",)]

        tables = adapter._get_existing_tables(mock_connection)

        assert tables == ["customer", "orders", "lineitem"]
        mock_cursor.execute.assert_called_with("SHOW TABLES")


class TestDorisSchemaOperations:
    """Test schema creation."""

    def test_create_schema(self):
        """Test schema creation with Doris table definitions."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER, name VARCHAR(100));
            CREATE TABLE table2 (id INTEGER, data VARCHAR(255));
        """

        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = (
                "CREATE TABLE table1 (id INT, name VARCHAR(100));\nCREATE TABLE table2 (id INT, data VARCHAR(255));"
            )
            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0
        assert mock_cursor.execute.call_count >= 2
        mock_cursor.close.assert_called_once()

    def test_create_schema_raises_on_create_table_failure(self):
        """create_schema should raise RuntimeError when CREATE TABLE statements fail."""
        adapter = DorisAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Syntax error")

        mock_benchmark = Mock()

        with (
            patch.object(adapter, "_create_schema_with_tuning", return_value="CREATE TABLE lineitem (id INT)"),
            pytest.raises(RuntimeError, match="critical CREATE TABLE"),
        ):
            adapter.create_schema(mock_benchmark, mock_connection)

    def test_create_schema_continues_on_non_critical_failure(self):
        """create_schema should not raise when non-CREATE TABLE statements fail."""
        adapter = DorisAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # Only the ALTER TABLE fails, CREATE TABLE succeeds
        mock_cursor.execute.side_effect = [None, Exception("Index error")]

        mock_benchmark = Mock()

        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE t1 (id INT); ALTER TABLE t1 ADD INDEX idx (id)",
        ):
            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)


class TestDorisDataLoading:
    """Test data loading functionality."""

    def test_load_data_stream_load(self):
        """Test loading data via Stream Load HTTP API."""
        try:
            adapter = DorisAdapter(
                host="localhost",
                http_port=8030,
                username="root",
                password="",
                database="test_db",
            )
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test1\n2,test2\n3,test3\n")
            temp_path = Path(f.name)

        try:
            fake_ds = DataSource(
                source_type="benchmark_tables",
                tables={"test_table": [temp_path]},
                table_metadata={"test_table": {"csv_delimiter": ","}},
            )

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "Status": "Success",
                "NumberLoadedRows": 3,
            }

            with (
                patch("benchbox.platforms.doris.DataSourceResolver") as mock_resolver_cls,
                patch("benchbox.platforms.doris._requests") as mock_requests,
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                mock_requests.put.return_value = mock_response
                mock_requests.__bool__ = Mock(return_value=True)
                table_stats, load_time, per_table = adapter.load_data(mock_benchmark, Mock(), Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert "test_table" in table_stats
            assert table_stats["test_table"] == 3

        finally:
            temp_path.unlink()

    def test_load_data_insert_fallback(self):
        """Test loading data via INSERT when requests is not available."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test1\n2,test2\n")
            temp_path = Path(f.name)

        try:
            fake_ds = DataSource(
                source_type="benchmark_tables",
                tables={"test_table": [temp_path]},
                table_metadata={"test_table": {"csv_delimiter": ","}},
            )

            with (
                patch("benchbox.platforms.doris.DataSourceResolver") as mock_resolver_cls,
                patch("benchbox.platforms.doris._requests", None),
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                table_stats, load_time, per_table = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert "test_table" in table_stats
            assert table_stats["test_table"] == 2
            assert mock_cursor.executemany.called

        finally:
            temp_path.unlink()

    def test_load_data_tbl_files_insert_fallback(self):
        """Test loading pipe-delimited .tbl files via INSERT fallback."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()

        # Create temporary test file with pipe delimiter
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", encoding="utf-8", delete=False) as f:
            f.write("1|test1|\n2|test2|\n")
            temp_path = Path(f.name)

        try:
            fake_ds = DataSource(
                source_type="benchmark_tables",
                tables={"customer": [temp_path]},
                table_metadata={"customer": {"csv_delimiter": "|", "csv_null_marker": ""}},
            )

            with (
                patch("benchbox.platforms.doris.DataSourceResolver") as mock_resolver_cls,
                patch("benchbox.platforms.doris._requests", None),
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert "customer" in table_stats
            assert table_stats["customer"] == 2

            # Check the INSERT batch was called
            assert mock_cursor.executemany.called
            insert_sql, rows = mock_cursor.executemany.call_args[0]
            assert "INSERT INTO `customer`" in insert_sql
            # TPC format trailing pipe should be stripped
            assert rows == [["1", "test1"], ["2", "test2"]]

        finally:
            temp_path.unlink()

    def test_load_data_missing_file(self):
        """Test loading nonexistent data file is handled gracefully."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_benchmark = Mock()
        fake_ds = DataSource(
            source_type="benchmark_tables",
            tables={"missing_table": [Path("/nonexistent/path/data.csv")]},
            table_metadata={},
        )

        with (
            patch("benchbox.platforms.doris.DataSourceResolver") as mock_resolver_cls,
            patch("benchbox.platforms.doris._requests", None),
        ):
            mock_resolver_cls.return_value.resolve.return_value = fake_ds
            table_stats, load_time, _ = adapter.load_data(mock_benchmark, Mock(), Path("/tmp"))

        assert table_stats["missing_table"] == 0

    def test_stream_load_failure_status(self):
        """Test Stream Load handles failure response."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Status": "Fail",
            "Message": "Table not found",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test1\n")
            temp_path = Path(f.name)

        try:
            csv_dialect = CsvDialect(
                delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None
            )
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response

                with pytest.raises(RuntimeError, match="Stream Load failed"):
                    adapter._stream_load_file("test_table", temp_path, csv_dialect)
        finally:
            temp_path.unlink()

    def test_stream_load_http_error(self):
        """Test Stream Load handles HTTP error status."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test1\n")
            temp_path = Path(f.name)

        try:
            csv_dialect = CsvDialect(
                delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None
            )
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response

                with pytest.raises(RuntimeError, match="status 503"):
                    adapter._stream_load_file("test_table", temp_path, csv_dialect)
        finally:
            temp_path.unlink()


class TestDorisQueryExecution:
    """Test query execution functionality."""

    def test_execute_query_success(self):
        """Test successful query execution."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

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
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

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

    def test_execute_query_empty_result(self):
        """Test query execution with empty result."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        result = adapter.execute_query(mock_connection, "SELECT * FROM empty_table", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 0
        assert result["first_row"] is None

    def test_get_query_plan(self):
        """Test query plan retrieval."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("OlapScanNode",),
            ("  TABLE: customer",),
            ("  PREDICATES: c_custkey > 100",),
        ]

        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM customer WHERE c_custkey > 100")

        assert "OlapScanNode" in plan
        assert "customer" in plan
        mock_cursor.execute.assert_called_once()
        mock_cursor.close.assert_called_once()

    def test_get_query_plan_verbose(self):
        """Test verbose query plan retrieval."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("VERBOSE PLAN",)]

        adapter.get_query_plan(mock_connection, "SELECT 1", explain_options={"verbose": True})

        call_args = mock_cursor.execute.call_args[0][0]
        assert call_args.startswith("EXPLAIN VERBOSE")

    def test_get_query_plan_failure(self):
        """Test query plan retrieval failure."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("EXPLAIN not supported")

        plan = adapter.get_query_plan(mock_connection, "SELECT 1")

        assert "Failed to get query plan" in plan


class TestDorisPlatformInfo:
    """Test platform information retrieval."""

    def test_get_platform_info_with_connection(self):
        """Test platform info with active connection."""
        try:
            adapter = DorisAdapter(
                host="doris-host",
                port=9030,
                http_port=8030,
                database="test_db",
            )
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            ("5.7.99",),  # SELECT version() MySQL compatibility string
            ("doris version doris-4.0.3-rc03-e9096296b8b",),  # SELECT @@version_comment
            ("test_db",),  # SELECT database()
        ]

        platform_info = adapter.get_platform_info(mock_connection)

        assert platform_info["platform_type"] == "doris"
        assert platform_info["platform_name"] == "Apache Doris"
        assert platform_info["host"] == "doris-host"
        assert platform_info["port"] == 9030
        assert platform_info["dialect"] == "doris"
        assert platform_info["platform_version"] == "4.0.3-rc03"
        assert platform_info["configuration"]["database"] == "test_db"
        assert platform_info["configuration"]["http_port"] == 8030
        assert platform_info["configuration"]["mysql_protocol_version"] == "5.7.99"
        assert platform_info["configuration"]["version_comment"] == "doris version doris-4.0.3-rc03-e9096296b8b"

    def test_get_platform_info_no_connection(self):
        """Test platform info without connection."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        platform_info = adapter.get_platform_info(None)

        assert platform_info["platform_type"] == "doris"
        assert platform_info["platform_name"] == "Apache Doris"
        assert "platform_version" not in platform_info


class TestDorisTuning:
    """Test tuning and optimization functionality."""

    def test_configure_for_benchmark_olap(self):
        """Test OLAP benchmark configuration."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Should attempt to set exec_mem_limit for OLAP
        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("exec_mem_limit" in c for c in calls)

    def test_configure_for_benchmark_uses_session_level_set(self):
        """Test that configure_for_benchmark uses session-level SET, not SET global."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_connection, "olap")

        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        for call in calls:
            assert "global" not in call.lower(), f"SET global found in: {call}"

        # Verify session-level SET statements are issued
        assert any("enable_sql_cache" in c for c in calls)
        assert any("parallel_fragment_exec_instance_num" in c for c in calls)

    def test_configure_for_benchmark_generic(self):
        """Test generic benchmark configuration."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Should not raise
        adapter.configure_for_benchmark(mock_connection, "generic")

    def test_supports_tuning_type(self):
        """Test tuning type support checking."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        from benchbox.core.tuning.interface import TuningType

        assert adapter.supports_tuning_type(TuningType.DISTRIBUTION) is True
        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
        assert adapter.supports_tuning_type(TuningType.SORTING) is True
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is True
        assert adapter.supports_tuning_type(TuningType.FOREIGN_KEYS) is False
        assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False

    def test_generate_tuning_clause_none(self):
        """Test tuning clause generation with None input."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        clause = adapter.generate_tuning_clause(None)
        assert clause == ""

    def test_apply_constraint_configuration(self):
        """Test constraint configuration (no enforcement in Doris)."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_pk_config = Mock()
        mock_pk_config.enabled = True
        mock_fk_config = Mock()
        mock_fk_config.enabled = True

        # Should not raise - constraints are not enforced in Doris
        adapter.apply_constraint_configuration(mock_pk_config, mock_fk_config, mock_connection)


class TestDorisAnalyze:
    """Test table analysis functionality."""

    def test_analyze_table(self):
        """Test ANALYZE TABLE execution."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_connection, "customer")

        mock_cursor.execute.assert_called_with("ANALYZE TABLE `customer`")

    def test_analyze_table_invalid_name(self):
        """Test ANALYZE TABLE with invalid table name is skipped."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_connection, "invalid; DROP TABLE")

        # Should not execute anything for invalid identifier
        mock_cursor.execute.assert_not_called()


class TestDorisIdentifierValidation:
    """Test SQL identifier validation."""

    def test_valid_identifiers(self):
        """Test valid SQL identifiers are accepted."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter._validate_identifier("customer") is True
        assert adapter._validate_identifier("order_items") is True
        assert adapter._validate_identifier("TPC_H_lineitem") is True
        assert adapter._validate_identifier("_private") is True

    def test_invalid_identifiers(self):
        """Test invalid SQL identifiers are rejected."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        assert adapter._validate_identifier("") is False
        assert adapter._validate_identifier("123abc") is False
        assert adapter._validate_identifier("drop; table") is False
        assert adapter._validate_identifier("name with spaces") is False
        assert adapter._validate_identifier(None) is False


class TestDorisValidation:
    """Test platform validation methods."""

    def test_validate_platform_capabilities(self):
        """Test platform capabilities validation."""
        try:
            import pymysql  # noqa: F401
        except ImportError:
            pytest.skip("pymysql not installed")

        adapter = DorisAdapter()
        result = adapter.validate_platform_capabilities("tpch")

        assert result is not None
        assert result.is_valid is True
        assert result.details["platform"] == "Apache Doris"
        assert result.details["pymysql_available"] is True

    def test_validate_connection_health(self):
        """Test connection health validation."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (1,),  # SELECT 1
            ("5.7.99",),  # SELECT version() MySQL compatibility string
            ("doris version doris-4.0.3-rc03-e9096296b8b",),  # SELECT @@version_comment
            ("test_db",),  # SELECT database()
        ]

        result = adapter.validate_connection_health(mock_connection)

        assert result is not None
        assert result.is_valid is True
        assert result.details["basic_query_test"] == "passed"
        assert result.details["server_version"] == "4.0.3-rc03"
        assert result.details["mysql_protocol_version"] == "5.7.99"
        assert result.details["version_comment"] == "doris version doris-4.0.3-rc03-e9096296b8b"

    def test_validate_connection_health_failure(self):
        """Test connection health validation on failure."""
        try:
            adapter = DorisAdapter()
        except ImportError:
            pytest.skip("pymysql not installed")

        mock_connection = Mock()
        mock_connection.cursor.side_effect = Exception("Connection lost")

        result = adapter.validate_connection_health(mock_connection)

        assert result is not None
        assert result.is_valid is False
        assert len(result.errors) > 0


class TestDorisBuildConfig:
    """Test the _build_doris_config helper function."""

    def test_build_config_from_options(self):
        """Test building config from platform options."""
        from benchbox.platforms.doris import _build_doris_config

        options = {
            "host": "my-doris",
            "port": 9030,
            "http_port": 8030,
            "username": "admin",
            "password": "secret",
            "database": "my_db",
        }

        config = _build_doris_config("doris", options, {}, None)

        assert config.host == "my-doris"
        assert config.port == 9030
        assert config.http_port == 8030
        assert config.username == "admin"
        assert config.password == "secret"
        assert config.database == "my_db"
        assert config.type == "doris"

    def test_build_config_defaults(self):
        """Test building config with defaults."""
        from benchbox.platforms.doris import _build_doris_config

        config = _build_doris_config("doris", {}, {}, None)

        assert config.host == "localhost"
        assert config.port == 9030
        assert config.http_port == 8030
        assert config.username == "root"

    def test_build_config_returns_database_config(self):
        """Test that config builder returns a DatabaseConfig instance."""
        from benchbox.core.schemas import DatabaseConfig
        from benchbox.platforms.doris import _build_doris_config

        config = _build_doris_config("doris", {}, {}, None)

        assert isinstance(config, DatabaseConfig)
        assert config.type == "doris"
        assert config.name == "Apache Doris"


class TestDorisTlsUrls:
    """Tests for TLS/HTTPS URL construction in Doris Stream Load."""

    def test_stream_load_url_defaults_to_http(self):
        """Stream Load URL uses HTTP and targets FE http_port by default."""
        adapter = DorisAdapter(host="myhost", http_port=8030, be_http_port=8040, database="test_db")
        assert adapter.use_tls is False

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f,
        ):
            f.write("1,test\n")
            temp_path = f.name

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
                url = mock_requests.put.call_args[0][0]
                assert url.startswith("http://")
                assert "myhost:8030" in url
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_stream_load_url_uses_https_when_tls_enabled(self):
        """Stream Load URL uses HTTPS and FE http_port when use_tls=True."""
        adapter = DorisAdapter(host="myhost", http_port=8030, be_http_port=8040, database="test_db", use_tls=True)
        assert adapter.use_tls is True

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f,
        ):
            f.write("1,test\n")
            temp_path = f.name

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
                url = mock_requests.put.call_args[0][0]
                assert url.startswith("https://")
                assert "myhost:8030" in url
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_from_config_passes_use_tls(self):
        """from_config propagates use_tls to adapter instance."""
        config = {
            "host": "localhost",
            "use_tls": True,
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }
        adapter = DorisAdapter.from_config(config)
        assert adapter.use_tls is True


class TestDorisChunkedLoading:
    """Tests for w8: Chunked loading for large files."""

    def test_small_file_uses_single_load(self):
        """Files smaller than chunk size use single Stream Load request."""
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=1024)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 3}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,a\n2,b\n3,c\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                rows = adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))

            assert rows == 3
            # Single request (not chunked)
            assert mock_requests.put.call_count == 1
        finally:
            temp_path.unlink()

    def test_large_file_uses_chunked_load(self):
        """Files larger than chunk size use chunked Stream Load."""
        # Use a very small chunk size to trigger chunking
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=20)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 2}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            # Write enough data to exceed 20 bytes
            f.write("1,aaaaaaa\n2,bbbbbbb\n3,ccccccc\n4,ddddddd\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                rows = adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))

            # Should have made multiple requests
            assert mock_requests.put.call_count > 1
            # Total rows = 2 per chunk * number of chunks
            assert rows == 2 * mock_requests.put.call_count
        finally:
            temp_path.unlink()

    def test_chunked_load_tpc_format_preserves_trailing_separator(self):
        """Chunked loading preserves trailing field separator in TPC format.

        TPC .tbl rows like '1|val1|' end with '|' because it is the field
        separator before an empty last column, not a spurious trailing delimiter.
        Stripping it reduces the column count and causes stream load to reject rows.
        """
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=15)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", encoding="utf-8", delete=False) as f:
            f.write("1|val1|\n2|val2|\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect("|", False, "", False, None))

            # Verify the payload is sent verbatim - compare byte-exact content.
            # _requests.put is always called with data as a keyword argument.
            sent = b"".join(call.kwargs["data"] for call in mock_requests.put.call_args_list)
            lines = sent.decode("utf-8").split("\n")
            assert lines == ["1|val1|", "2|val2|"], f"Rows were modified before sending - got: {lines}"
        finally:
            temp_path.unlink()

    def test_chunked_load_preserves_rows_without_trailing_separator(self):
        """Rows without a trailing | (non-NULL last column) are also sent as-is.

        The no-strip fix must not accidentally insert or remove separators for
        rows that genuinely don't end with the field delimiter.
        """
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=50)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", encoding="utf-8", delete=False) as f:
            # Row 1: NULL last column (trailing |). Row 2: non-NULL last column (no trailing |).
            f.write("1|val1|\n2|val2\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect("|", False, "", False, None))

            sent = b"".join(call.kwargs["data"] for call in mock_requests.put.call_args_list)
            lines = sent.decode("utf-8").split("\n")
            assert "1|val1|" in lines, "Trailing | stripped from NULL-last-column row"
            assert "2|val2" in lines, "Non-trailing-| row was modified"
        finally:
            temp_path.unlink()

    def test_chunked_load_handles_failure(self):
        """Chunked loading raises on Stream Load failure."""
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=10)

        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,aaaaaaa\n2,bbbbbbb\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                with pytest.raises(RuntimeError, match="chunk.*failed"):
                    adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
        finally:
            temp_path.unlink()

    def test_stream_load_chunk_size_config(self):
        """stream_load_chunk_size is configurable via init."""
        adapter = DorisAdapter(stream_load_chunk_size=50 * 1024 * 1024)
        assert adapter.stream_load_chunk_size == 50 * 1024 * 1024

    def test_stream_load_chunk_size_default(self):
        """Default chunk size is 10MB (reduced from 100MB to avoid Docker timeout on large tables)."""
        adapter = DorisAdapter()
        assert adapter.stream_load_chunk_size == 10 * 1024 * 1024

    def test_from_config_passes_chunk_size(self):
        """from_config propagates stream_load_chunk_size."""
        config = {"stream_load_chunk_size": 200 * 1024 * 1024}
        adapter = DorisAdapter.from_config(config)
        assert adapter.stream_load_chunk_size == 200 * 1024 * 1024


class TestDorisTableModel:
    """Tests for w11: Duplicate/Aggregate/Unique Key table models."""

    def test_default_table_model_is_duplicate(self):
        """Default table model is 'duplicate'."""
        adapter = DorisAdapter()
        assert adapter.table_model == "duplicate"

    def test_table_model_aggregate(self):
        """Can set table model to 'aggregate'."""
        adapter = DorisAdapter(table_model="aggregate")
        assert adapter.table_model == "aggregate"

    def test_table_model_unique(self):
        """Can set table model to 'unique'."""
        adapter = DorisAdapter(table_model="unique")
        assert adapter.table_model == "unique"

    def test_table_model_case_insensitive(self):
        """Table model is case insensitive."""
        adapter = DorisAdapter(table_model="DUPLICATE")
        assert adapter.table_model == "duplicate"

    def test_invalid_table_model_raises(self):
        """Invalid table model raises ValueError."""
        with pytest.raises(ValueError, match="Invalid table_model"):
            DorisAdapter(table_model="invalid")

    def test_get_table_model_clause_duplicate_lineitem(self):
        """DUPLICATE KEY clause for lineitem uses correct columns."""
        adapter = DorisAdapter(table_model="duplicate")
        clause = adapter.get_table_model_clause("lineitem")
        assert clause == "DUPLICATE KEY(l_orderkey, l_linenumber)"

    def test_get_table_model_clause_aggregate_orders(self):
        """AGGREGATE KEY clause for orders."""
        adapter = DorisAdapter(table_model="aggregate")
        clause = adapter.get_table_model_clause("orders")
        assert clause == "AGGREGATE KEY(o_orderkey)"

    def test_get_table_model_clause_unique_customer(self):
        """UNIQUE KEY clause for customer."""
        adapter = DorisAdapter(table_model="unique")
        clause = adapter.get_table_model_clause("customer")
        assert clause == "UNIQUE KEY(c_custkey)"

    def test_get_table_model_clause_all_tpch_tables(self):
        """All TPC-H tables have defined key columns."""
        adapter = DorisAdapter()
        tpch_tables = [
            "lineitem",
            "orders",
            "customer",
            "part",
            "supplier",
            "partsupp",
            "nation",
            "region",
        ]
        for table in tpch_tables:
            clause = adapter.get_table_model_clause(table)
            assert clause.startswith("DUPLICATE KEY("), f"Missing key for {table}"

    def test_get_table_model_clause_unknown_table(self):
        """Unknown table returns empty string."""
        adapter = DorisAdapter()
        clause = adapter.get_table_model_clause("unknown_table")
        assert clause == ""

    def test_from_config_passes_table_model(self):
        """from_config propagates table_model."""
        config = {"table_model": "unique"}
        adapter = DorisAdapter.from_config(config)
        assert adapter.table_model == "unique"


class TestDorisDistribution:
    """Tests for w12: DISTRIBUTED BY HASH clause generation."""

    def test_default_buckets(self):
        """Default bucket count is 10."""
        adapter = DorisAdapter()
        assert adapter.default_buckets == 10

    def test_custom_buckets(self):
        """Custom bucket count via config."""
        adapter = DorisAdapter(default_buckets=32)
        assert adapter.default_buckets == 32

    def test_distribution_clause_lineitem(self):
        """Distribution clause for lineitem uses l_orderkey."""
        adapter = DorisAdapter()
        clause = adapter.get_distribution_clause("lineitem")
        assert "DISTRIBUTED BY HASH(l_orderkey)" in clause
        assert "BUCKETS" in clause

    def test_distribution_clause_customer(self):
        """Distribution clause for customer uses c_custkey."""
        adapter = DorisAdapter()
        clause = adapter.get_distribution_clause("customer")
        assert "DISTRIBUTED BY HASH(c_custkey)" in clause

    def test_distribution_clause_all_tpch_tables(self):
        """All TPC-H tables have distribution keys."""
        adapter = DorisAdapter()
        tpch_tables = [
            "lineitem",
            "orders",
            "customer",
            "part",
            "supplier",
            "partsupp",
            "nation",
            "region",
        ]
        for table in tpch_tables:
            clause = adapter.get_distribution_clause(table)
            assert "DISTRIBUTED BY HASH" in clause, f"Missing distribution for {table}"
            assert "BUCKETS" in clause

    def test_distribution_clause_unknown_table(self):
        """Unknown table uses table name as distribution key with default buckets."""
        adapter = DorisAdapter(default_buckets=8)
        clause = adapter.get_distribution_clause("unknown_table")
        assert "BUCKETS 8" in clause

    def test_bucket_count_scales_with_sf(self):
        """Bucket count increases with scale factor for large tables."""
        adapter = DorisAdapter(default_buckets=4)
        small_clause = adapter.get_distribution_clause("lineitem", scale_factor=0.01)
        large_clause = adapter.get_distribution_clause("lineitem", scale_factor=100)
        # Extract bucket numbers
        small_buckets = int(small_clause.split("BUCKETS ")[-1])
        large_buckets = int(large_clause.split("BUCKETS ")[-1])
        assert large_buckets > small_buckets

    def test_bucket_count_capped_at_128(self):
        """Bucket count is capped at 128."""
        adapter = DorisAdapter()
        clause = adapter.get_distribution_clause("lineitem", scale_factor=10000)
        buckets = int(clause.split("BUCKETS ")[-1])
        assert buckets <= 128

    def test_from_config_passes_default_buckets(self):
        """from_config propagates default_buckets."""
        config = {"default_buckets": 16}
        adapter = DorisAdapter.from_config(config)
        assert adapter.default_buckets == 16


class TestDorisPartitioning:
    """Tests for w13: PARTITION BY RANGE for large tables."""

    def test_partitioning_disabled_by_default(self):
        """Partitioning is disabled by default."""
        adapter = DorisAdapter()
        assert adapter.enable_partitioning is False

    def test_partition_clause_disabled(self):
        """No partition clause when disabled."""
        adapter = DorisAdapter(enable_partitioning=False)
        clause = adapter.get_partition_clause("lineitem")
        assert clause == ""

    def test_partition_clause_lineitem(self):
        """Partition clause for lineitem uses l_shipdate."""
        adapter = DorisAdapter(enable_partitioning=True)
        clause = adapter.get_partition_clause("lineitem")
        assert "PARTITION BY RANGE(l_shipdate)" in clause
        assert "p1992" in clause
        assert "p1998" in clause
        assert "VALUES LESS THAN" in clause

    def test_partition_clause_orders(self):
        """Partition clause for orders uses o_orderdate."""
        adapter = DorisAdapter(enable_partitioning=True)
        clause = adapter.get_partition_clause("orders")
        assert "PARTITION BY RANGE(o_orderdate)" in clause

    def test_partition_clause_small_table(self):
        """No partition clause for small tables (nation, region, etc)."""
        adapter = DorisAdapter(enable_partitioning=True)
        assert adapter.get_partition_clause("customer") == ""
        assert adapter.get_partition_clause("nation") == ""
        assert adapter.get_partition_clause("region") == ""

    def test_partition_clause_unknown_table(self):
        """No partition clause for unknown tables."""
        adapter = DorisAdapter(enable_partitioning=True)
        assert adapter.get_partition_clause("unknown") == ""

    def test_from_config_passes_enable_partitioning(self):
        """from_config propagates enable_partitioning."""
        config = {"enable_partitioning": True}
        adapter = DorisAdapter.from_config(config)
        assert adapter.enable_partitioning is True


class TestDorisCacheValidation:
    """Tests for w18: Cache disable validation."""

    def test_cache_validation_passes(self):
        """configure_for_benchmark validates cache is disabled."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # SHOW VARIABLES returns ('enable_sql_cache', 'false')
        mock_cursor.fetchone.return_value = ("enable_sql_cache", "false")

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Verify SHOW VARIABLES was called for validation
        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("SHOW VARIABLES" in c for c in calls)

    def test_cache_validation_warns_on_failure(self, caplog):
        """configure_for_benchmark warns if cache is still enabled."""
        import logging

        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # SHOW VARIABLES returns cache still enabled
        mock_cursor.fetchone.return_value = ("enable_sql_cache", "true")

        with caplog.at_level(logging.WARNING):
            adapter.configure_for_benchmark(mock_connection, "generic")
            assert any("Cache disable validation failed" in msg for msg in caplog.messages)

    def test_cache_validation_no_global_set(self):
        """Cache validation does not use SET global."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("enable_sql_cache", "false")

        adapter.configure_for_benchmark(mock_connection, "olap")

        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        for call in calls:
            assert "global" not in call.lower(), f"SET global found: {call}"


class TestDorisBloomFilterIndex:
    """Tests for w20: Bloom filter index support."""

    def test_create_bloom_filter_indexes(self):
        """Creates Bloom filter indexes on high-cardinality columns."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bloom_filter_indexes(mock_connection)

        assert len(stmts) > 0
        for stmt in stmts:
            assert "USING BLOOM_FILTER" in stmt
            assert "CREATE INDEX" in stmt

    def test_bloom_filter_on_specific_tables(self):
        """Creates Bloom filter indexes only on specified tables."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bloom_filter_indexes(mock_connection, tables=["lineitem"])

        assert len(stmts) > 0
        for stmt in stmts:
            assert "lineitem" in stmt

    def test_bloom_filter_index_names(self):
        """Bloom filter indexes have proper naming convention."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bloom_filter_indexes(mock_connection, tables=["lineitem"])

        for stmt in stmts:
            assert "idx_bloom_" in stmt

    def test_bloom_filter_handles_execute_failure(self):
        """Bloom filter creation handles SQL execution failures gracefully."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Index already exists")

        # Should not raise
        stmts = adapter.create_bloom_filter_indexes(mock_connection, tables=["lineitem"])
        assert len(stmts) == 0  # None succeeded


class TestDorisBitmapIndex:
    """Tests for w21: Bitmap index support."""

    def test_create_bitmap_indexes(self):
        """Creates Bitmap indexes on low-cardinality columns."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bitmap_indexes(mock_connection)

        assert len(stmts) > 0
        for stmt in stmts:
            assert "USING BITMAP" in stmt
            assert "CREATE INDEX" in stmt

    def test_bitmap_on_specific_tables(self):
        """Creates Bitmap indexes only on specified tables."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bitmap_indexes(mock_connection, tables=["orders"])

        assert len(stmts) > 0
        for stmt in stmts:
            assert "orders" in stmt

    def test_bitmap_index_names(self):
        """Bitmap indexes have proper naming convention."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bitmap_indexes(mock_connection, tables=["lineitem"])

        for stmt in stmts:
            assert "idx_bitmap_" in stmt

    def test_bitmap_correct_columns(self):
        """Bitmap indexes target low-cardinality columns."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bitmap_indexes(mock_connection, tables=["lineitem"])

        stmt_text = " ".join(stmts)
        assert "l_returnflag" in stmt_text
        assert "l_linestatus" in stmt_text

    def test_bitmap_handles_execute_failure(self):
        """Bitmap creation handles SQL execution failures gracefully."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Index already exists")

        stmts = adapter.create_bitmap_indexes(mock_connection, tables=["lineitem"])
        assert len(stmts) == 0

    def test_bitmap_no_columns_for_unknown_table(self):
        """Bitmap indexes return empty for unknown tables."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        stmts = adapter.create_bitmap_indexes(mock_connection, tables=["unknown_table"])
        assert len(stmts) == 0


class TestDorisPlatformInfoNewFields:
    """Test that platform info includes new configuration fields."""

    def test_platform_info_includes_table_model(self):
        """Platform info includes table_model config."""
        adapter = DorisAdapter(table_model="unique")
        info = adapter.get_platform_info()
        assert info["configuration"]["table_model"] == "unique"

    def test_platform_info_includes_default_buckets(self):
        """Platform info includes default_buckets config."""
        adapter = DorisAdapter(default_buckets=32)
        info = adapter.get_platform_info()
        assert info["configuration"]["default_buckets"] == 32

    def test_platform_info_includes_chunk_size(self):
        """Platform info includes stream_load_chunk_size config."""
        adapter = DorisAdapter(stream_load_chunk_size=50 * 1024 * 1024)
        info = adapter.get_platform_info()
        assert info["configuration"]["stream_load_chunk_size"] == 50 * 1024 * 1024

    def test_platform_info_includes_partitioning(self):
        """Platform info includes enable_partitioning config."""
        adapter = DorisAdapter(enable_partitioning=True)
        info = adapter.get_platform_info()
        assert info["configuration"]["enable_partitioning"] is True

    def test_platform_info_includes_index_configs(self):
        """Platform info includes bloom filter and bitmap config."""
        adapter = DorisAdapter(enable_bloom_filter=True, enable_bitmap_index=True)
        info = adapter.get_platform_info()
        assert info["configuration"]["enable_bloom_filter"] is True
        assert info["configuration"]["enable_bitmap_index"] is True

    def test_platform_info_includes_stream_load_max_filter_ratio(self):
        """Platform info includes stream_load_max_filter_ratio config."""
        adapter = DorisAdapter(stream_load_max_filter_ratio=0.001)
        info = adapter.get_platform_info()
        assert info["configuration"]["stream_load_max_filter_ratio"] == "0.001"


class TestDorisTlsCertValidation:
    """Tests for verify_ssl and ca_cert_path TLS certificate options."""

    def test_defaults_verify_ssl_true_no_ca_cert(self):
        """verify_ssl defaults to True, ca_cert_path defaults to None."""
        adapter = DorisAdapter()
        assert adapter.verify_ssl is True
        assert adapter.ca_cert_path is None

    def test_verify_ssl_false_disables_validation(self):
        """verify_ssl=False is stored and passed as verify=False to requests."""
        adapter = DorisAdapter(database="test_db", verify_ssl=False)
        assert adapter.verify_ssl is False

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test\n")
            temp_path = f.name

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
                _, kwargs = mock_requests.put.call_args
                assert kwargs["verify"] is False
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_ca_cert_path_passed_as_verify(self):
        """ca_cert_path is passed as verify= to requests, taking precedence over verify_ssl."""
        adapter = DorisAdapter(database="test_db", ca_cert_path="/etc/ssl/custom-ca.crt")
        assert adapter.ca_cert_path == "/etc/ssl/custom-ca.crt"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 1}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,test\n")
            temp_path = f.name

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
                _, kwargs = mock_requests.put.call_args
                assert kwargs["verify"] == "/etc/ssl/custom-ca.crt"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_chunked_load_passes_verify_ssl(self):
        """verify_ssl=False is also propagated to chunked stream load requests."""
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=10, verify_ssl=False)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 5}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            # Write enough data to trigger chunked loading (> 10 bytes chunk size)
            for i in range(20):
                f.write(f"{i},value_{i}\n")
            temp_path = f.name

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
                # All requests.put calls should have verify=False
                for call in mock_requests.put.call_args_list:
                    _, kwargs = call
                    assert kwargs["verify"] is False
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_from_config_passes_verify_ssl_and_ca_cert_path(self):
        """from_config propagates verify_ssl and ca_cert_path to the adapter."""
        config = {
            "host": "localhost",
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "verify_ssl": False,
            "ca_cert_path": "/etc/ssl/my-ca.crt",
        }
        adapter = DorisAdapter.from_config(config)
        assert adapter.verify_ssl is False
        assert adapter.ca_cert_path == "/etc/ssl/my-ca.crt"


class TestDorisStreamLoadFilterRatio:
    """Tests for filtered-row handling during Doris Stream Load."""

    def test_invalid_stream_load_max_filter_ratio_raises(self):
        """stream_load_max_filter_ratio must be between 0 and 1 inclusive."""
        with pytest.raises(
            ValueError,
            match="stream_load_max_filter_ratio must be between 0 and 1 inclusive",
        ):
            DorisAdapter(stream_load_max_filter_ratio=1.5)

    def test_from_config_passes_max_filter_ratio(self):
        """from_config propagates stream_load_max_filter_ratio."""
        adapter = DorisAdapter.from_config({"stream_load_max_filter_ratio": 0.001})
        assert adapter.stream_load_max_filter_ratio == "0.001"

    def test_filtered_rows_raise_by_default(self):
        """Successful Doris responses with filtered rows still fail by default."""
        adapter = DorisAdapter(database="test_db")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Status": "Success",
            "NumberLoadedRows": 2,
            "NumberFilteredRows": 1,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,a\n2,b\n3,c\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                with pytest.raises(RuntimeError, match="refusing silent partial load"):
                    adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))
        finally:
            temp_path.unlink()

    def test_filtered_rows_can_be_allowed_explicitly(self, caplog):
        """Nonzero max_filter_ratio allows filtered rows but emits a warning."""
        import logging

        adapter = DorisAdapter(database="test_db", stream_load_max_filter_ratio=0.001)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Status": "Success",
            "NumberLoadedRows": 2,
            "NumberFilteredRows": 1,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write("1,a\n2,b\n3,c\n")
            temp_path = Path(f.name)

        try:
            with patch("benchbox.platforms.doris._requests") as mock_requests:
                mock_requests.put.return_value = mock_response
                with caplog.at_level(logging.WARNING):
                    rows = adapter._stream_load_file("test_table", temp_path, CsvDialect(",", False, None, False, None))

            assert rows == 2
            assert "filtered 1 row(s)" in caplog.text
        finally:
            temp_path.unlink()


class TestDorisParquetStreamLoad:
    """Tests for Parquet-specific Doris Stream Load handling."""

    def test_parquet_uses_streaming_upload_with_parquet_format(self, tmp_path):
        """Parquet files must be uploaded as one streaming request with format=parquet."""
        adapter = DorisAdapter(database="test_db", stream_load_chunk_size=1)
        parquet_bytes = b"PAR1benchbox-parquetPAR1"
        data_file = tmp_path / "rows.parquet"
        data_file.write_bytes(parquet_bytes)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 7}

        captured: dict[str, object] = {}

        def _put(url, **kwargs):
            captured["url"] = url
            captured["headers"] = dict(kwargs["headers"])
            captured["payload"] = kwargs["data"].read()
            return mock_response

        with patch("benchbox.platforms.doris._requests") as mock_requests:
            mock_requests.put.side_effect = _put
            rows = adapter._stream_load_file("test_table", data_file, CsvDialect(",", False, None, False, None))

        assert rows == 7
        assert mock_requests.put.call_count == 1
        assert captured["url"] == "http://localhost:8030/api/test_db/test_table/_stream_load"
        assert captured["headers"] == {
            "Expect": "100-continue",
            "format": "parquet",
            "max_filter_ratio": "0",
        }
        assert captured["payload"] == parquet_bytes

    def test_gzipped_parquet_is_decompressed_before_upload(self, tmp_path):
        """Outer gzip compression is removed client-side before Parquet upload."""
        adapter = DorisAdapter(database="test_db")
        parquet_bytes = b"PAR1compressed-parquetPAR1"
        data_file = tmp_path / "rows.parquet.gz"
        data_file.write_bytes(gzip.compress(parquet_bytes))

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Status": "Success", "NumberLoadedRows": 5}

        captured: dict[str, object] = {}

        def _put(_url, **kwargs):
            captured["headers"] = dict(kwargs["headers"])
            captured["payload"] = kwargs["data"].read()
            return mock_response

        with patch("benchbox.platforms.doris._requests") as mock_requests:
            mock_requests.put.side_effect = _put
            rows = adapter._stream_load_file("test_table", data_file, CsvDialect(",", False, None, False, None))

        assert rows == 5
        assert mock_requests.put.call_count == 1
        assert captured["headers"]["format"] == "parquet"
        assert captured["payload"] == parquet_bytes


class TestDorisDdlAndIntegrityValidation:
    """Tests for Doris DDL rewrites and integrity validation overrides."""

    def test_inject_doris_ddl_clauses_strips_array_dimensions(self):
        """ARRAY<T>[N] should be rewritten to the Doris-supported unsized ARRAY<T> form."""
        adapter = DorisAdapter()
        ddl = """\
CREATE TABLE vectors (
    id BIGINT PRIMARY KEY,
    embedding ARRAY<FLOAT>[128] NOT NULL,
    tag VARCHAR(32)
);
"""

        rewritten = adapter._inject_doris_ddl_clauses(ddl)

        assert "ARRAY<FLOAT>[128]" not in rewritten
        assert "ARRAY<FLOAT>" in rewritten
        assert "VARCHAR(32)" in rewritten

    def test_inject_doris_ddl_clauses_strips_table_level_pk_with_leading_comma(self):
        """Table-level PRIMARY KEY (col) with leading comma is stripped."""
        adapter = DorisAdapter()
        ddl = "CREATE TABLE t (id BIGINT, name VARCHAR(32), PRIMARY KEY (id))"

        rewritten = adapter._inject_doris_ddl_clauses(ddl)

        assert "PRIMARY KEY" not in rewritten

    def test_inject_doris_ddl_clauses_strips_bare_table_level_pk(self):
        """Bare table-level PRIMARY KEY (no leading comma) is stripped."""
        adapter = DorisAdapter()
        ddl = "CREATE TABLE t (PRIMARY KEY (id), id BIGINT, name VARCHAR(32))"

        rewritten = adapter._inject_doris_ddl_clauses(ddl)

        assert "PRIMARY KEY" not in rewritten
        # Trailing artefacts cleaned: no leading "(," in column block
        assert "(," not in rewritten

    def test_inject_doris_ddl_clauses_strips_column_level_pk(self):
        """Column-level "col TYPE PRIMARY KEY" form is stripped."""
        adapter = DorisAdapter()
        ddl = "CREATE TABLE t (id BIGINT PRIMARY KEY, name VARCHAR(32))"

        rewritten = adapter._inject_doris_ddl_clauses(ddl)

        assert "PRIMARY KEY" not in rewritten

    def test_validate_data_integrity_quotes_mixed_case_table_names(self):
        """Integrity validation should quote mixed-case table names such as DimCustomer."""
        adapter = DorisAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        status, details = adapter._validate_data_integrity(
            None,
            mock_connection,
            {"DimCustomer": 3},
        )

        assert status == "PASSED"
        assert details["accessible_tables"] == ["DimCustomer"]
        mock_cursor.execute.assert_called_once_with("SELECT 1 FROM `DimCustomer` LIMIT 1")
        mock_cursor.close.assert_called_once()
