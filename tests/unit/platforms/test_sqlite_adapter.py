"""Tests for SQLite platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.sqlite import SQLiteAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSQLiteAdapter:
    """Test SQLite platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        adapter = SQLiteAdapter(database_path=":memory:", timeout=30.0, check_same_thread=False)
        assert adapter.platform_name == "SQLite"
        assert adapter.get_target_dialect() == "sqlite"
        assert adapter.database_path == ":memory:"
        assert adapter.timeout == 30.0
        assert adapter.check_same_thread is False

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        adapter = SQLiteAdapter()
        assert adapter.platform_name == "SQLite"
        assert adapter.database_path == ":memory:"
        assert adapter.timeout == 30.0
        assert adapter.check_same_thread is False

    def test_initialization_missing_driver(self):
        """Test initialization when SQLite driver is not available."""
        with patch("benchbox.platforms.sqlite.sqlite3", None):
            with pytest.raises(ImportError, match="SQLite not available"):
                SQLiteAdapter()

    def test_get_database_path(self):
        """Test database path configuration."""
        adapter = SQLiteAdapter(database_path="/tmp/test.db")

        # Test with override
        path = adapter.get_database_path(database_path="/tmp/override.db")
        assert path == "/tmp/override.db"

        # Test with default
        path = adapter.get_database_path()
        assert path == "/tmp/test.db"

        # Test memory database
        adapter = SQLiteAdapter()
        path = adapter.get_database_path()
        assert path == ":memory:"

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_connection_memory_database(self, mock_sqlite3):
        """Test connection creation with memory database."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter(database_path=":memory:")
        connection = adapter.create_connection()

        assert connection == mock_connection
        mock_sqlite3.connect.assert_called_once_with(":memory:", timeout=30.0, check_same_thread=False)

        # Check PRAGMA statements were executed
        expected_pragmas = [
            "PRAGMA foreign_keys = ON",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = 10000",
            "PRAGMA temp_store = MEMORY",
        ]

        for pragma in expected_pragmas:
            mock_connection.execute.assert_any_call(pragma)

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_connection_file_database(self, mock_sqlite3):
        """Test connection creation with file database."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter(database_path="/tmp/test.db")
        connection = adapter.create_connection()

        assert connection == mock_connection
        mock_sqlite3.connect.assert_called_once_with("/tmp/test.db", timeout=30.0, check_same_thread=False)

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_connection_with_overrides(self, mock_sqlite3):
        """Test connection creation with configuration overrides."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection(database_path="/tmp/override.db", timeout=60.0)

        assert connection == mock_connection
        # Should use override path but adapter's timeout (overrides not fully applied)
        mock_sqlite3.connect.assert_called_once()

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_connection_failure(self, mock_sqlite3):
        """Test connection creation failure."""
        mock_sqlite3.connect.side_effect = Exception("Connection failed")

        adapter = SQLiteAdapter()

        with pytest.raises(Exception, match="Connection failed"):
            adapter.create_connection()

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_schema_with_constraints(self, mock_sqlite3):
        """Test schema creation with constraints enabled."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE table2 (id INTEGER, fk_id INTEGER, FOREIGN KEY(fk_id) REFERENCES table1(id));
        """

        # Mock the signature to indicate the benchmark supports constraint parameters

        mock_sig = Mock()
        mock_sig.parameters = {
            "enable_primary_keys": Mock(),
            "enable_foreign_keys": Mock(),
        }

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        # Mock the effective tuning configuration to return constraint settings
        mock_config = Mock()
        mock_config.primary_keys.enabled = True
        mock_config.foreign_keys.enabled = True

        with (
            patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config),
            patch("inspect.signature", return_value=mock_sig),
        ):
            schema_time = adapter.create_schema(mock_benchmark, connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should call get_create_tables_sql with standardized signature
        mock_benchmark.get_create_tables_sql.assert_called_once_with(dialect="sqlite", tuning_config=mock_config)

        # Should execute schema and commit
        mock_connection.executescript.assert_called_once()
        mock_connection.commit.assert_called_once()

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_create_schema_without_constraints(self, mock_sqlite3):
        """Test schema creation with constraints disabled."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = "CREATE TABLE table1 (id INTEGER, name TEXT);"

        # Mock the signature to indicate the benchmark supports constraint parameters

        mock_sig = Mock()
        mock_sig.parameters = {
            "enable_primary_keys": Mock(),
            "enable_foreign_keys": Mock(),
        }

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        # Mock the effective tuning configuration to return constraint settings
        mock_config = Mock()
        mock_config.primary_keys.enabled = False
        mock_config.foreign_keys.enabled = False

        with (
            patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config),
            patch("inspect.signature", return_value=mock_sig),
        ):
            schema_time = adapter.create_schema(mock_benchmark, connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should call get_create_tables_sql with standardized signature
        mock_benchmark.get_create_tables_sql.assert_called_once_with(dialect="sqlite", tuning_config=mock_config)

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_configure_for_benchmark_olap(self, mock_sqlite3):
        """Test OLAP benchmark configuration."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        adapter.configure_for_benchmark(connection, "olap")

        # Should execute OLAP-specific pragmas
        mock_connection.execute.assert_any_call("PRAGMA query_only = false")
        mock_connection.execute.assert_any_call("PRAGMA read_uncommitted = true")

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_configure_for_benchmark_oltp(self, mock_sqlite3):
        """Test OLTP benchmark configuration."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        adapter.configure_for_benchmark(connection, "oltp")

        # Should execute OLTP-specific pragmas
        mock_connection.execute.assert_any_call("PRAGMA synchronous = FULL")

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_execute_query_success(self, mock_sqlite3):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        result = adapter.execute_query(connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["results"] == [(1, "test"), (2, "test2")]
        assert isinstance(result["execution_time_seconds"], float)

        mock_cursor.execute.assert_called_once_with("SELECT * FROM test")
        mock_cursor.fetchall.assert_called_once()

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_execute_query_failure(self, mock_sqlite3):
        """Test query execution failure."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SQL syntax error")
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        result = adapter.execute_query(connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "SQL syntax error"
        assert isinstance(result["execution_time_seconds"], float)

    def test_apply_table_tunings(self):
        """Test table tuning application (limited support in SQLite)."""
        adapter = SQLiteAdapter()
        mock_connection = Mock()
        mock_table_tuning = Mock()

        # Should not raise exception - SQLite has limited tuning support
        adapter.apply_table_tunings(mock_table_tuning, mock_connection)

    def test_generate_tuning_clause(self):
        """Test tuning clause generation (none supported in SQLite)."""
        adapter = SQLiteAdapter()
        mock_table_tuning = Mock()

        clause = adapter.generate_tuning_clause(mock_table_tuning)
        assert clause == ""

    def test_apply_unified_tuning(self):
        """Test unified tuning application (limited support in SQLite)."""
        adapter = SQLiteAdapter()
        mock_connection = Mock()
        mock_unified_config = Mock()

        # Should not raise exception - SQLite has limited tuning support
        adapter.apply_unified_tuning(mock_unified_config, mock_connection)

    def test_apply_platform_optimizations(self):
        """Test platform optimizations (limited in SQLite)."""
        adapter = SQLiteAdapter()
        mock_connection = Mock()
        mock_platform_config = Mock()

        # Should not raise exception - optimizations applied in create_connection
        adapter.apply_platform_optimizations(mock_platform_config, mock_connection)

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_apply_constraint_configuration_enable_foreign_keys(self, mock_sqlite3):
        """Test constraint configuration with foreign keys enabled."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        # Mock foreign key config
        mock_foreign_key_config = Mock()
        mock_foreign_key_config.enabled = True

        mock_primary_key_config = Mock()

        adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, connection)

        mock_connection.execute.assert_any_call("PRAGMA foreign_keys = ON")

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_apply_constraint_configuration_disable_foreign_keys(self, mock_sqlite3):
        """Test constraint configuration with foreign keys disabled."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        connection = adapter.create_connection()

        # Mock foreign key config
        mock_foreign_key_config = Mock()
        mock_foreign_key_config.enabled = False

        mock_primary_key_config = Mock()

        adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, connection)

        mock_connection.execute.assert_any_call("PRAGMA foreign_keys = OFF")

    def test_run_power_test_not_implemented(self):
        """Test power test raises NotImplementedError."""
        adapter = SQLiteAdapter()
        mock_benchmark = Mock()

        with pytest.raises(NotImplementedError, match="Power test not implemented for SQLite adapter"):
            adapter.run_power_test(mock_benchmark)

    def test_run_throughput_test_not_implemented(self):
        """Test throughput test raises NotImplementedError."""
        adapter = SQLiteAdapter()
        mock_benchmark = Mock()

        with pytest.raises(
            NotImplementedError,
            match="Throughput test not implemented for SQLite adapter",
        ):
            adapter.run_throughput_test(mock_benchmark)

    def test_run_maintenance_test_not_implemented(self):
        """Test maintenance test raises NotImplementedError."""
        adapter = SQLiteAdapter()
        mock_benchmark = Mock()

        with pytest.raises(
            NotImplementedError,
            match="Maintenance test not implemented for SQLite adapter",
        ):
            adapter.run_maintenance_test(mock_benchmark)

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_handle_existing_database_memory(self, mock_sqlite3):
        """Test existing database handling with memory database."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter(database_path=":memory:")

        # Should not raise exception for memory database
        connection = adapter.create_connection()
        assert connection == mock_connection

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_configuration_validation(self, mock_sqlite3):
        """Test configuration parameter validation."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        # Test various configuration combinations
        adapter = SQLiteAdapter(database_path="/tmp/test.db", timeout=60.0, check_same_thread=True)

        assert adapter.database_path == "/tmp/test.db"
        assert adapter.timeout == 60.0
        assert adapter.check_same_thread is True

        connection = adapter.create_connection()
        assert connection == mock_connection

    @patch("benchbox.platforms.sqlite.sqlite3")
    def test_connection_optimization_pragmas(self, mock_sqlite3):
        """Test that connection optimization pragmas are properly applied."""
        mock_connection = Mock()
        mock_sqlite3.connect.return_value = mock_connection

        adapter = SQLiteAdapter()
        adapter.create_connection()

        # Verify all optimization pragmas were executed
        expected_pragmas = [
            "PRAGMA foreign_keys = ON",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = 10000",
            "PRAGMA temp_store = MEMORY",
        ]

        for pragma in expected_pragmas:
            mock_connection.execute.assert_any_call(pragma)

        assert mock_connection.execute.call_count >= len(expected_pragmas)

    def test_from_config_with_connection_string(self):
        """Test from_config() with connection_string parameter."""
        config = {
            "connection_string": "/tmp/test_from_config.db",
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }

        adapter = SQLiteAdapter.from_config(config)

        assert adapter.database_path == "/tmp/test_from_config.db"
        assert adapter.timeout == 30.0
        assert adapter.check_same_thread is False

    def test_from_config_with_database_path(self):
        """Test from_config() with database_path parameter (takes priority)."""
        config = {
            "database_path": "/tmp/explicit_path.db",
            "connection_string": "/tmp/ignored.db",
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }

        adapter = SQLiteAdapter.from_config(config)

        assert adapter.database_path == "/tmp/explicit_path.db"

    def test_from_config_with_auto_generation(self):
        """Test from_config() with automatic path generation."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }

        adapter = SQLiteAdapter.from_config(config)

        # Should generate path based on benchmark and scale
        assert adapter.database_path is not None
        assert "tpch" in adapter.database_path.lower()
        # SQLite uses .sqlite extension (changed from .db to avoid collision)
        assert ".sqlite" in adapter.database_path

    def test_from_config_with_output_dir(self, tmp_path):
        """Test from_config() with custom output_dir."""
        custom_output = tmp_path / "custom_output"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(custom_output),
        }

        adapter = SQLiteAdapter.from_config(config)

        # Should generate path in custom output directory (cross-platform)
        assert str(custom_output) in adapter.database_path
        assert "tpch" in adapter.database_path.lower()

    def test_from_config_raises_on_missing_path(self):
        """Test from_config() raises ConfigurationError when no path can be determined."""
        from benchbox.core.exceptions import ConfigurationError

        config = {}

        with pytest.raises(ConfigurationError) as excinfo:
            SQLiteAdapter.from_config(config)

        assert "database_path" in str(excinfo.value)
        assert "--benchmark" in str(excinfo.value)

    def test_from_config_with_optional_params(self):
        """Test from_config() with optional timeout and check_same_thread."""
        config = {
            "connection_string": "/tmp/test.db",
            "timeout": 60.0,
            "check_same_thread": True,
        }

        adapter = SQLiteAdapter.from_config(config)

        assert adapter.database_path == "/tmp/test.db"
        assert adapter.timeout == 60.0
        assert adapter.check_same_thread is True

    def test_from_config_rejects_nested_connection_dict(self):
        """Nested connection dict is no longer accepted."""
        from benchbox.core.exceptions import ConfigurationError

        config = {
            "connection": {
                "database_path": "/tmp/legacy_path.db",
            },
        }

        with pytest.raises(ConfigurationError):
            SQLiteAdapter.from_config(config)

    def test_get_database_path_with_none_override(self):
        """Test get_database_path() when connection_config has None value."""
        adapter = SQLiteAdapter(database_path="/tmp/instance_path.db")

        # When connection_config has database_path=None, should use instance path
        path = adapter.get_database_path(database_path=None)
        assert path == "/tmp/instance_path.db"

    def test_get_database_path_with_explicit_override(self):
        """Test get_database_path() with explicit override value."""
        adapter = SQLiteAdapter(database_path="/tmp/instance_path.db")

        # When connection_config has explicit path, should use that
        path = adapter.get_database_path(database_path="/tmp/override.db")
        assert path == "/tmp/override.db"
