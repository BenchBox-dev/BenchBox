"""Tests for PostgreSQL platform adapter.

Tests the PostgreSQLAdapter for PostgreSQL database support.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import argparse
from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.postgresql import POSTGRES_DIALECT, PostgreSQLAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def postgres_stubs(monkeypatch):
    """Patch psycopg2 objects so tests don't require the real driver."""
    mock_psycopg2 = Mock()
    mock_psycopg2.__version__ = "2.9.9"
    mock_psycopg2.extras = Mock()

    monkeypatch.setattr(postgresql_module, "psycopg2", mock_psycopg2)

    return mock_psycopg2


class TestPostgreSQLAdapter:
    """Unit tests for PostgreSQL adapter wiring and SQL handling."""

    def test_initialization_defaults(self, postgres_stubs):
        """Adapter should initialize with PostgreSQL defaults when stubs are present."""
        adapter = PostgreSQLAdapter()

        assert adapter.platform_name == "PostgreSQL"
        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.host == "localhost"
        assert adapter.port == 5432
        assert adapter.database == "benchbox"
        assert adapter.username == "postgres"
        assert adapter.schema == "public"
        assert adapter.sslmode == "prefer"

    def test_initialization_with_config(self, postgres_stubs):
        """Adapter should accept custom configuration."""
        adapter = PostgreSQLAdapter(
            host="pg.example.com",
            port=5433,
            database="custom_db",
            username="custom_user",
            password="secret",
            schema="analytics",
            work_mem="512MB",
        )

        assert adapter.host == "pg.example.com"
        assert adapter.port == 5433
        assert adapter.database == "custom_db"
        assert adapter.username == "custom_user"
        assert adapter.password == "secret"
        assert adapter.schema == "analytics"
        assert adapter.work_mem == "512MB"

    def test_get_connection_params(self, postgres_stubs):
        """Connection parameters should include all required fields."""
        adapter = PostgreSQLAdapter(
            host="pg.example.com",
            port=5433,
            database="testdb",
            username="testuser",
            password="testpass",
            sslmode="require",
            connect_timeout=15,
        )

        params = adapter._get_connection_params()

        assert params["host"] == "pg.example.com"
        assert params["port"] == 5433
        assert params["dbname"] == "testdb"
        assert params["user"] == "testuser"
        assert params["password"] == "testpass"
        assert params["sslmode"] == "require"
        assert params["connect_timeout"] == 15

    def test_get_connection_params_custom_database(self, postgres_stubs):
        """Connection parameters should allow custom database override."""
        adapter = PostgreSQLAdapter(database="default_db")

        params = adapter._get_connection_params(database="override_db")

        assert params["dbname"] == "override_db"

    def test_add_cli_arguments_registers_postgres_compatible_flags(self, postgres_stubs):
        """CLI parser should expose shared PostgreSQL-compatible arguments."""
        parser = argparse.ArgumentParser()

        PostgreSQLAdapter.add_cli_arguments(parser)
        parsed = parser.parse_args(
            [
                "--postgres-host",
                "pg.local",
                "--postgres-port",
                "5544",
                "--postgres-database",
                "benchbox_db",
                "--postgres-username",
                "benchbox",
                "--postgres-password",
                "secret",
                "--postgres-schema",
                "analytics",
                "--postgres-work-mem",
                "768MB",
                "--postgres-maintenance-work-mem",
                "1GB",
                "--postgres-enable-timescale",
            ]
        )

        assert parsed.host == "pg.local"
        assert parsed.port == 5544
        assert parsed.database == "benchbox_db"
        assert parsed.username == "benchbox"
        assert parsed.password == "secret"
        assert parsed.schema == "analytics"
        assert parsed.work_mem == "768MB"
        assert parsed.maintenance_work_mem == "1GB"
        assert parsed.enable_timescale is True

    def test_check_server_database_exists_true(self, postgres_stubs):
        """Database existence check returns True when database is found."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="testdb")

        assert adapter.check_server_database_exists() is True
        postgres_stubs.connect.assert_called()

    def test_check_server_database_exists_false(self, postgres_stubs):
        """Database existence check returns False when database not found."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="nonexistent")

        assert adapter.check_server_database_exists() is False

    def test_check_server_database_exists_connection_error(self, postgres_stubs):
        """Database existence check returns False on connection error."""
        postgres_stubs.connect.side_effect = Exception("Connection refused")

        adapter = PostgreSQLAdapter()

        assert adapter.check_server_database_exists() is False

    def test_drop_database_success(self, postgres_stubs):
        """Drop database should terminate connections and drop."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="to_drop")

        adapter.drop_database(database="to_drop")

        executed = " ".join(str(call) for call in mock_cursor.execute.call_args_list)
        assert "pg_terminate_backend" in executed
        assert "DROP DATABASE" in executed

    def test_drop_database_rejects_invalid_identifier(self, postgres_stubs):
        """Drop database should reject SQL injection attempts."""
        adapter = PostgreSQLAdapter()

        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter.drop_database(database="test; DROP TABLE users")

    def test_validate_identifier_valid(self, postgres_stubs):
        """Valid identifiers should pass validation."""
        adapter = PostgreSQLAdapter()

        assert adapter._validate_identifier("my_database") is True
        assert adapter._validate_identifier("TestDB") is True
        assert adapter._validate_identifier("_private") is True
        assert adapter._validate_identifier("db123") is True

    def test_validate_identifier_invalid(self, postgres_stubs):
        """Invalid identifiers should fail validation."""
        adapter = PostgreSQLAdapter()

        assert adapter._validate_identifier("") is False
        assert adapter._validate_identifier(None) is False
        assert adapter._validate_identifier("123abc") is False  # Starts with number
        assert adapter._validate_identifier("db-name") is False  # Contains hyphen
        assert adapter._validate_identifier("a" * 64) is False  # Too long
        assert adapter._validate_identifier("db.schema") is False  # Contains dot

    def test_create_connection_applies_settings(self, postgres_stubs):
        """Connection should apply session settings."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [(1,), (1,)]  # Database exists, SELECT 1
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(
            database="testdb",
            work_mem="512MB",
            maintenance_work_mem="1GB",
        )

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
        ):
            connection = adapter.create_connection()

        assert connection is mock_conn

        # Verify settings were applied
        executed = " ".join(str(call) for call in mock_cursor.execute.call_args_list)
        assert "work_mem" in executed
        assert "maintenance_work_mem" in executed

    def test_create_connection_creates_database(self, postgres_stubs):
        """Connection should create database if it doesn't exist."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [None, (1,)]  # DB doesn't exist, then SELECT 1
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="newdb")

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_create_database") as mock_create,
            patch.object(adapter, "check_server_database_exists", side_effect=[False, True]),
        ):
            adapter.create_connection()

        mock_create.assert_called_once()

    def test_get_platform_info(self, postgres_stubs):
        """Platform info should include PostgreSQL version and settings."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            ("PostgreSQL 15.2 on x86_64",),  # version()
            None,  # TimescaleDB check
            ("100 MB",),  # database size
        ]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter(
            host="pg.example.com",
            port=5432,
            database="testdb",
            schema="analytics",
            work_mem="256MB",
        )

        info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_type"] == "postgresql"
        assert info["platform_name"] == "PostgreSQL"
        assert info["host"] == "pg.example.com"
        assert info["port"] == 5432
        assert info["dialect"] == POSTGRES_DIALECT
        assert info["configuration"]["database"] == "testdb"
        assert info["configuration"]["schema"] == "analytics"
        assert info["configuration"]["work_mem"] == "256MB"

    def test_execute_query_success(self, postgres_stubs):
        """Query execution should return correct result structure."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()

        result = adapter.execute_query(mock_conn, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)

    def test_execute_query_failure(self, postgres_stubs):
        """Query execution failure should return error info."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.side_effect = Exception("Query failed")
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()

        result = adapter.execute_query(mock_conn, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"

    def test_get_query_plan(self, postgres_stubs):
        """Query plan should use EXPLAIN ANALYZE."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [
            ("Seq Scan on test  (cost=0.00..10.00 rows=100 width=36)",),
            ("  Filter: (id > 5)",),
        ]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()

        plan = adapter.get_query_plan(mock_conn, "SELECT * FROM test WHERE id > 5")

        assert "Seq Scan" in plan
        assert "Filter" in plan

    def test_configure_for_benchmark_olap(self, postgres_stubs):
        """OLAP configuration should set appropriate settings."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()

        adapter.configure_for_benchmark(mock_conn, "olap")

        executed = " ".join(str(call) for call in mock_cursor.execute.call_args_list)
        assert "enable_hashjoin" in executed
        assert "random_page_cost" in executed

    def test_configure_for_benchmark_oltp(self, postgres_stubs):
        """OLTP configuration should set appropriate settings."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()

        adapter.configure_for_benchmark(mock_conn, "oltp")

        executed = " ".join(str(call) for call in mock_cursor.execute.call_args_list)
        assert "synchronous_commit" in executed

    def test_analyze_table(self, postgres_stubs):
        """Analyze should run ANALYZE on the table."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter(schema="public")

        adapter.analyze_table(mock_conn, "test_table")

        mock_cursor.execute.assert_called()
        executed = str(mock_cursor.execute.call_args)
        assert "ANALYZE" in executed

    def test_get_existing_tables(self, postgres_stubs):
        """Should query information_schema for tables."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("table1",), ("TABLE2",)]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter(schema="public")

        tables = adapter._get_existing_tables(mock_conn)

        assert tables == ["table1", "table2"]

    def test_test_connection_success(self, postgres_stubs):
        """Connection test should return True on success."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter()

        assert adapter.test_connection() is True

    def test_test_connection_failure(self, postgres_stubs):
        """Connection test should return False on failure."""
        postgres_stubs.connect.side_effect = Exception("Connection refused")

        adapter = PostgreSQLAdapter()

        assert adapter.test_connection() is False

    def test_from_config_generates_database_name(self, postgres_stubs):
        """from_config should generate database name from benchmark config."""
        config = {
            "host": "pg.example.com",
            "benchmark": "tpch",
            "scale_factor": 10.0,
        }

        adapter = PostgreSQLAdapter.from_config(config)

        assert "tpch" in adapter.database.lower()
        assert adapter.host == "pg.example.com"

    def test_from_config_uses_provided_database(self, postgres_stubs):
        """from_config should use explicitly provided database name."""
        config = {
            "host": "pg.example.com",
            "database": "my_custom_db",
            "benchmark": "tpch",
            "scale_factor": 10.0,
        }

        adapter = PostgreSQLAdapter.from_config(config)

        assert adapter.database == "my_custom_db"

    def test_supports_tuning_type(self, postgres_stubs):
        """Should report correct tuning type support."""
        adapter = PostgreSQLAdapter()

        from benchbox.core.tuning.interface import TuningType

        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
        assert adapter.supports_tuning_type(TuningType.SORTING) is False
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is True
        assert adapter.supports_tuning_type(TuningType.FOREIGN_KEYS) is True
        assert adapter.supports_tuning_type(TuningType.CLUSTERING) is True

    def test_close_connection(self, postgres_stubs):
        """Close connection should call close on the connection."""
        mock_conn = Mock()

        adapter = PostgreSQLAdapter()

        adapter.close_connection(mock_conn)

        mock_conn.close.assert_called_once()

    def test_dialect_is_postgres(self, postgres_stubs):
        """Dialect should be 'postgres' for SQLGlot compatibility."""
        adapter = PostgreSQLAdapter()

        assert adapter.get_target_dialect() == "postgres"
        assert adapter._dialect == "postgres"


class TestPostgreSQLDataLoading:
    """Tests for PostgreSQL COPY-based data loading."""

    def test_load_data_with_csv(self, postgres_stubs, tmp_path):
        """Should use COPY for CSV data loading."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (3,)  # Row count
        mock_conn.cursor.return_value = mock_cursor

        # Create test CSV file
        csv_file = tmp_path / "test_table.csv"
        csv_file.write_text("1,alice\n2,bob\n3,charlie\n")

        class Benchmark:
            tables = {"test_table": csv_file}

        adapter = PostgreSQLAdapter(schema="public")

        stats, load_time, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["test_table"] == 3
        assert load_time >= 0

        # Verify COPY was used
        assert mock_cursor.copy_expert.called

    def test_load_data_with_tbl(self, postgres_stubs, tmp_path):
        """Should handle .tbl files with trailing pipe delimiter."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (2,)  # Row count
        mock_conn.cursor.return_value = mock_cursor

        # Create test .tbl file with trailing pipe
        tbl_file = tmp_path / "orders.tbl"
        tbl_file.write_text("1|alice|\n2|bob|\n")

        class Benchmark:
            tables = {"orders": tbl_file}

        adapter = PostgreSQLAdapter(schema="public")

        stats, load_time, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["orders"] == 2
        assert mock_cursor.copy_expert.called

    def test_load_data_skips_invalid_identifier(self, postgres_stubs, tmp_path):
        """Should skip tables with invalid identifiers."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Create test file
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("1,test\n")

        class Benchmark:
            tables = {"invalid table; DROP TABLE": csv_file}

        adapter = PostgreSQLAdapter()

        stats, _, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        # Invalid identifier should be skipped with 0 rows
        assert list(stats.values())[0] == 0
        assert not mock_cursor.copy_expert.called


class TestPostgreSQLCreateDatabase:
    """Tests for _create_database helper."""

    def test_create_database_calls_create_if_not_exists(self, postgres_stubs):
        """_create_database should execute CREATE DATABASE when db doesn't exist."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = None  # DB does not exist
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="newdb")
        adapter._create_database()

        executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "CREATE DATABASE" in executed
        assert "newdb" in executed

    def test_create_database_skips_if_already_exists(self, postgres_stubs):
        """_create_database should skip when DB already exists."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (1,)  # DB already exists
        mock_conn.cursor.return_value = mock_cursor
        postgres_stubs.connect.return_value = mock_conn

        adapter = PostgreSQLAdapter(database="existingdb")
        adapter._create_database()

        executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "CREATE DATABASE" not in executed

    def test_create_database_rejects_invalid_identifier(self, postgres_stubs):
        """_create_database should raise ValueError for invalid database names."""
        adapter = PostgreSQLAdapter(database="valid_db")
        adapter.database = "invalid; DROP TABLE users"

        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter._create_database()


class TestPostgreSQLCreateSchema:
    """Tests for create_schema method."""

    def test_create_schema_executes_statements(self, postgres_stubs):
        """create_schema should execute all SQL statements from benchmark schema."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        class MockBenchmark:
            def get_schema_sql(self):
                return "CREATE TABLE foo (id INT); CREATE TABLE bar (id INT)"

        adapter = PostgreSQLAdapter()

        with patch.object(
            adapter, "_create_schema_with_tuning", return_value="CREATE TABLE foo (id INT); CREATE TABLE bar (id INT)"
        ):
            duration = adapter.create_schema(MockBenchmark(), mock_conn)

        assert isinstance(duration, float)
        assert duration >= 0
        mock_conn.commit.assert_called()

    def test_create_schema_continues_on_statement_failure(self, postgres_stubs):
        """create_schema should continue executing remaining statements if one fails."""
        mock_conn = Mock()
        mock_cursor = Mock()
        # First statement fails, second succeeds
        mock_cursor.execute.side_effect = [Exception("syntax error"), None]
        mock_conn.cursor.return_value = mock_cursor

        class MockBenchmark:
            pass

        adapter = PostgreSQLAdapter()

        with patch.object(adapter, "_create_schema_with_tuning", return_value="INVALID SQL; CREATE TABLE bar (id INT)"):
            duration = adapter.create_schema(MockBenchmark(), mock_conn)

        # Should complete without raising despite first statement error
        assert isinstance(duration, float)
        mock_conn.commit.assert_called()


class TestPostgreSQLValidatePlatformCapabilities:
    """Tests for validate_platform_capabilities."""

    def test_valid_capabilities_with_psycopg2(self, postgres_stubs):
        """Should return valid result when psycopg2 is available."""
        postgres_stubs.__version__ = "2.9.9"

        adapter = PostgreSQLAdapter(work_mem="256MB")
        result = adapter.validate_platform_capabilities("tpch")

        assert result is not None
        assert result.is_valid is True
        assert result.details["psycopg2_available"] is True
        assert result.details["benchmark_type"] == "tpch"

    def test_warns_on_low_work_mem(self, postgres_stubs):
        """Should warn when work_mem is below 64MB."""
        adapter = PostgreSQLAdapter(work_mem="32MB")
        result = adapter.validate_platform_capabilities("tpch")

        assert result is not None
        warning_messages = " ".join(result.warnings)
        assert "work_mem" in warning_messages

    def test_warns_on_gb_work_mem_not_low(self, postgres_stubs):
        """Should not warn when work_mem is in GB."""
        adapter = PostgreSQLAdapter(work_mem="1GB")
        result = adapter.validate_platform_capabilities("tpch")

        assert result is not None
        # 1GB = 1024MB, well above 64MB threshold
        work_mem_warnings = [w for w in result.warnings if "work_mem" in w.lower()]
        assert len(work_mem_warnings) == 0


class TestPostgreSQLValidateConnectionHealth:
    """Tests for validate_connection_health."""

    def test_healthy_connection(self, postgres_stubs):
        """Should return valid result for a working connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            (1,),  # SELECT 1
            ("PostgreSQL 15.2 on x86_64-pc-linux-gnu",),  # SELECT version()
            ("256MB",),  # SHOW work_mem
            None,  # timescaledb check
        ]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()
        result = adapter.validate_connection_health(mock_conn)

        assert result is not None
        assert result.is_valid is True
        assert result.details["basic_query_test"] == "passed"
        assert "PostgreSQL" in result.details["server_version"]

    def test_warns_on_old_postgres_version(self, postgres_stubs):
        """Should warn when PostgreSQL version is older than 12."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            (1,),
            ("PostgreSQL 11.19 on x86_64",),
            ("256MB",),
            None,
        ]
        mock_conn.cursor.return_value = mock_cursor

        adapter = PostgreSQLAdapter()
        result = adapter.validate_connection_health(mock_conn)

        assert result is not None
        warning_messages = " ".join(result.warnings)
        assert "11" in warning_messages or "older" in warning_messages

    def test_failed_connection_returns_invalid_result(self, postgres_stubs):
        """Should return invalid result when connection health check fails."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Connection lost")

        adapter = PostgreSQLAdapter()
        result = adapter.validate_connection_health(mock_conn)

        assert result is not None
        assert result.is_valid is False
        assert len(result.errors) > 0


class TestBuildPostgreSQLConfig:
    """Tests for _build_postgresql_config module-level function."""

    def test_default_values(self, postgres_stubs):
        """Should populate defaults when options are empty."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        result = _build_postgresql_config({}, {})

        assert result["host"] == "localhost"
        assert result["port"] == 5432
        assert result["username"] == "postgres"
        assert result["schema"] == "public"
        assert result["work_mem"] == "256MB"
        assert result["maintenance_work_mem"] == "512MB"
        assert result["enable_timescale"] is False

    def test_platform_options_override_defaults(self, postgres_stubs):
        """Platform options should override defaults."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        result = _build_postgresql_config(
            {},
            {
                "host": "pg.example.com",
                "port": 5433,
                "work_mem": "1GB",
            },
        )

        assert result["host"] == "pg.example.com"
        assert result["port"] == 5433
        assert result["work_mem"] == "1GB"

    def test_benchmark_config_merged(self, postgres_stubs):
        """Benchmark config values should be merged into result."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        result = _build_postgresql_config({"scale_factor": 10.0, "benchmark": "tpch"}, {})

        assert result["scale_factor"] == 10.0
        assert result["benchmark"] == "tpch"
