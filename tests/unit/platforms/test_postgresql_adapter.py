"""Tests for PostgreSQL platform adapter.

Tests the PostgreSQLAdapter for PostgreSQL database support.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.base.data_loading import DataSource
from benchbox.platforms.postgresql import POSTGRES_DIALECT, PostgreSQLAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def postgres_stubs(monkeypatch):
    """Patch psycopg objects so tests don't require the real driver."""
    mock_psycopg = Mock()
    mock_psycopg.__version__ = "3.1.0"

    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)

    return mock_psycopg


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

    @staticmethod
    def _install_copy_context(mock_cursor):
        """Attach a context-manager mock to cursor.copy() (psycopg3 API)."""
        copy_cm = MagicMock()
        copy_cm.__enter__.return_value = copy_cm
        copy_cm.__exit__.return_value = False
        mock_cursor.copy.return_value = copy_cm
        return copy_cm

    def test_load_data_with_csv(self, postgres_stubs, tmp_path):
        """Should use COPY for CSV data loading."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (3,)  # Row count
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

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
        assert mock_cursor.copy.called

    def test_load_data_with_tbl(self, postgres_stubs, tmp_path):
        """Should handle .tbl files with trailing pipe delimiter."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (2,)  # Row count
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        # Create test .tbl file with trailing pipe
        tbl_file = tmp_path / "orders.tbl"
        tbl_file.write_text("1|alice|\n2|bob|\n")

        class Benchmark:
            tables = {"orders": tbl_file}

        adapter = PostgreSQLAdapter(schema="public")

        stats, load_time, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["orders"] == 2
        assert mock_cursor.copy.called

    def test_load_data_preserves_dat_trailing_empty_fields(self, postgres_stubs, tmp_path):
        """.dat files can encode trailing NULL columns with trailing delimiters."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        copy_cm = self._install_copy_context(mock_cursor)

        dat_file = tmp_path / "catalog_page.dat"
        dat_file.write_text("160|AAAAAAAAAKAAAAAA|2450997|||||\n")

        class Benchmark:
            tables = {"catalog_page": dat_file}

        adapter = PostgreSQLAdapter(schema="public")

        stats, _, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["catalog_page"] == 1
        assert any(call.args[0].endswith("|||||\n") for call in copy_cm.write.call_args_list)

    def test_load_data_accepts_list_of_chunks(self, postgres_stubs, tmp_path):
        """Multi-chunk tables (list[Path]) must load every chunk without a TypeError."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (6,)
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        chunk_a = tmp_path / "lineitem_0.csv"
        chunk_b = tmp_path / "lineitem_1.csv"
        chunk_a.write_text("1,alice\n2,bob\n3,charlie\n")
        chunk_b.write_text("4,dave\n5,eve\n6,frank\n")

        class Benchmark:
            tables = {"lineitem": [chunk_a, chunk_b]}

        adapter = PostgreSQLAdapter(schema="public")
        stats, _, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["lineitem"] == 6
        assert mock_cursor.copy.call_count == 2

    def test_load_data_skips_invalid_identifier(self, postgres_stubs, tmp_path):
        """Should skip tables with invalid identifiers."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        # Create test file
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("1,test\n")

        class Benchmark:
            tables = {"invalid table; DROP TABLE": csv_file}

        adapter = PostgreSQLAdapter()

        stats, _, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        # Invalid identifier should be skipped with 0 rows
        assert list(stats.values())[0] == 0
        assert not mock_cursor.copy.called

    def test_copy_sql_tbl_uses_format_text_with_null(self, postgres_stubs, tmp_path):
        """csv_null_marker='' in manifest metadata → FORMAT text, NULL '' in COPY SQL.

        Proves the table_metadata → resolve_csv_dialect → COPY SQL pipeline end-to-end.
        TPC-style files use FORMAT text to avoid quote-parsing issues with pipe delimiter.
        """
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        tbl_file = tmp_path / "lineitem.tbl"
        tbl_file.write_text("1|foo|bar|\n")

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"lineitem": tbl_file},
            table_metadata={"lineitem": {"csv_delimiter": "|", "csv_null_marker": ""}},
        )

        adapter = PostgreSQLAdapter(schema="public")
        with patch("benchbox.platforms.postgresql.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = fake_ds
            adapter.load_data(Mock(), mock_conn, tmp_path)

        assert mock_cursor.copy.called, "cursor.copy() was not called"
        copy_sql = mock_cursor.copy.call_args.args[0]
        assert "FORMAT text" in copy_sql
        assert "NULL ''" in copy_sql
        assert "FORMAT csv" not in copy_sql

    def test_copy_sql_csv_with_header_uses_header_true(self, postgres_stubs, tmp_path):
        """csv_has_header=True in manifest metadata → HEADER true in COPY SQL.

        Proves the table_metadata → resolve_csv_dialect → COPY SQL pipeline end-to-end.
        """
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (2,)
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        csv_file = tmp_path / "trips.csv"
        csv_file.write_text("time,lat,lon\n2026-01-01,1.0,2.0\n2026-01-02,3.0,4.0\n")

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"trips": csv_file},
            table_metadata={"trips": {"csv_has_header": True, "csv_delimiter": ","}},
        )

        adapter = PostgreSQLAdapter(schema="public")
        with patch("benchbox.platforms.postgresql.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = fake_ds
            adapter.load_data(Mock(), mock_conn, tmp_path)

        assert mock_cursor.copy.called, "cursor.copy() was not called"
        copy_sql = mock_cursor.copy.call_args.args[0]
        assert "FORMAT csv" in copy_sql
        assert "HEADER true" in copy_sql

    def test_copy_sql_csv_with_empty_null_marker_stays_csv(self, postgres_stubs, tmp_path):
        """Comma CSV with empty=NULL must still use CSV mode so headers and quoting work."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        csv_file = tmp_path / "flights.csv"
        csv_file.write_text("flight_id,carrier_delay\n1,\n")

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"flights": csv_file},
            table_metadata={"flights": {"csv_has_header": True, "csv_delimiter": ",", "csv_null_marker": ""}},
        )

        adapter = PostgreSQLAdapter(schema="public")
        with patch("benchbox.platforms.postgresql.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = fake_ds
            adapter.load_data(Mock(), mock_conn, tmp_path)

        assert mock_cursor.copy.called, "cursor.copy() was not called"
        copy_sql = mock_cursor.copy.call_args.args[0]
        assert "FORMAT csv" in copy_sql
        assert "HEADER true" in copy_sql
        assert "NULL ''" in copy_sql

    def test_copy_sql_csv_no_header_preserves_empty_strings(self, postgres_stubs, tmp_path):
        """csv_null_marker=None in manifest metadata → COPY uses a non-empty NULL sentinel.

        Proves the table_metadata → resolve_csv_dialect → COPY SQL pipeline end-to-end.
        PostgreSQL CSV COPY defaults NULL to an empty unquoted field; BenchBox's
        null_marker=None contract means empty fields must remain empty strings.
        """
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        self._install_copy_context(mock_cursor)

        csv_file = tmp_path / "hits.csv"
        csv_file.write_text("1,,bar\n")

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"hits": csv_file},
            table_metadata={"hits": {"csv_has_header": False, "csv_delimiter": ",", "csv_null_marker": None}},
        )

        adapter = PostgreSQLAdapter(schema="public")
        with patch("benchbox.platforms.postgresql.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = fake_ds
            adapter.load_data(Mock(), mock_conn, tmp_path)

        assert mock_cursor.copy.called, "cursor.copy() was not called"
        copy_sql = mock_cursor.copy.call_args.args[0]
        assert "FORMAT csv" in copy_sql
        assert "HEADER" not in copy_sql
        assert "NULL '__BENCHBOX_NO_NULL__'" in copy_sql

    def test_load_data_converts_parquet_to_csv_copy(self, postgres_stubs, tmp_path):
        """Parquet-backed benchmarks are converted to CSV before PostgreSQL COPY."""
        mock_conn = Mock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (2,)
        mock_conn.cursor.return_value = mock_cursor
        copy_cm = self._install_copy_context(mock_cursor)

        parquet_file = tmp_path / "title.parquet"
        table = pa.table({"id": [1, 2], "name": ["", None]})
        pq.write_table(table, parquet_file)

        class Benchmark:
            tables = {"title": parquet_file}

        adapter = PostgreSQLAdapter(schema="public")
        stats, _, _ = adapter.load_data(Benchmark(), mock_conn, tmp_path)

        assert stats["title"] == 2
        copy_sql = mock_cursor.copy.call_args.args[0]
        assert "FORMAT csv" in copy_sql
        assert "HEADER true" in copy_sql
        assert "NULL ''" in copy_sql
        written = b"".join(call.args[0] for call in copy_cm.write.call_args_list).decode()
        assert '"id","name"' in written
        assert '"1",""' in written


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
        """create_schema retries CREATE TABLE after stripping FOREIGN KEY constraints."""
        mock_conn = Mock()
        mock_cursor = Mock()
        # First attempt (with FK) fails; retry (without FK) succeeds
        mock_cursor.execute.side_effect = [Exception("syntax error"), None]
        mock_conn.cursor.return_value = mock_cursor

        class MockBenchmark:
            pass

        adapter = PostgreSQLAdapter()

        fk_stmt = "CREATE TABLE foo (id INT, FOREIGN KEY (id) REFERENCES bar(id))"
        with patch.object(adapter, "_create_schema_with_tuning", return_value=fk_stmt):
            duration = adapter.create_schema(MockBenchmark(), mock_conn)

        # Should complete without raising: FK stripped and retry succeeded
        assert isinstance(duration, float)
        mock_conn.commit.assert_called()


class TestPostgreSQLValidatePlatformCapabilities:
    """Tests for validate_platform_capabilities."""

    def test_valid_capabilities_with_psycopg(self, postgres_stubs):
        """Should return valid result when psycopg is available."""
        postgres_stubs.__version__ = "3.1.0"

        adapter = PostgreSQLAdapter(work_mem="256MB")
        result = adapter.validate_platform_capabilities("tpch")

        assert result is not None
        assert result.is_valid is True
        assert result.details["psycopg_available"] is True
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
        """Should populate defaults when no credentials are saved and options are empty."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm = MagicMock()
            mock_cm.get_platform_credentials.return_value = {}
            mock_cm_cls.return_value = mock_cm

            result = _build_postgresql_config("postgresql", {}, {}, None)

        assert result.host == "localhost"
        assert result.port == 5432
        assert result.username == "postgres"
        assert result.sslmode == "prefer"
        assert result.options.get("work_mem") == "256MB" or result.options.get("work_mem") is None

    def test_platform_options_override_defaults(self, postgres_stubs):
        """Explicit --platform-option flags should override saved credentials."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        explicit = {"host": "pg.example.com", "port": 5433, "work_mem": "1GB"}
        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm = MagicMock()
            mock_cm.get_platform_credentials.return_value = {"host": "saved-host", "username": "saved_user"}
            mock_cm_cls.return_value = mock_cm

            result = _build_postgresql_config(
                "postgresql",
                explicit,
                {"_explicit_platform_options": explicit},
                None,
            )

        assert result.host == "pg.example.com"
        assert result.port == 5433

    def test_benchmark_config_merged(self, postgres_stubs):
        """Benchmark config values should be merged into result via overrides."""
        from benchbox.platforms.postgresql import _build_postgresql_config

        result = _build_postgresql_config("postgresql", {}, {"scale_factor": 10.0, "benchmark": "tpch"}, None)

        assert result.scale_factor == 10.0
        assert result.benchmark == "tpch"
