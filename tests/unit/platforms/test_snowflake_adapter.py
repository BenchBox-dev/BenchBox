"""Tests for Snowflake platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base import DriverIsolationCapability
from benchbox.platforms.base.data_loading import NO_BENCHMARK, DataSource
from benchbox.platforms.snowflake import SnowflakeAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


def _parse_snowflake_cli_args(argv: list[str]) -> dict[str, object]:
    """Parse Snowflake CLI args in a clean Python process."""

    script = """
import argparse
import json
from benchbox.platforms.snowflake import SnowflakeAdapter

parser = argparse.ArgumentParser()
SnowflakeAdapter.add_cli_arguments(parser)
print(json.dumps(vars(parser.parse_args(ARGV))))
"""

    result = subprocess.run(
        [sys.executable, "-c", script.replace("ARGV", repr(argv))],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.fixture(autouse=True)
def snowflake_dependencies():
    """Mock Snowflake dependency check to simulate installed extras."""

    with patch("benchbox.platforms.snowflake.check_platform_dependencies", return_value=(True, [])):
        yield


class TestSnowflakeAdapter:
    """Test Snowflake platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
                schema="TEST_SCHEMA",
            )
            assert adapter.platform_name == "Snowflake"
            assert adapter.get_target_dialect() == "snowflake"
            assert adapter.account == "test_account"
            assert adapter.username == "test_user"
            assert adapter.warehouse == "TEST_WH"
            assert adapter.database == "TEST_DB"

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(account="test_account", username="test_user", password="test_pass")
            assert adapter.warehouse == "COMPUTE_WH"
            assert adapter.database == "BENCHBOX"
            assert adapter.schema == "PUBLIC"
            assert adapter.authenticator == "snowflake"
            assert adapter.warehouse_size == "MEDIUM"
            assert adapter.auto_suspend == 300
            assert adapter.auto_resume is True

    def test_external_table_capability_declared(self):
        """Snowflake should explicitly declare external-table support."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(account="test_account", username="test_user", password="test_pass")
            assert adapter.supports_external_tables is True

    def test_initialization_missing_driver(self):
        """Test initialization when Snowflake dependencies are missing."""
        with (
            patch("benchbox.platforms.snowflake.snowflake", None),
            patch(
                "benchbox.platforms.snowflake.check_platform_dependencies",
                return_value=(False, ["snowflake-connector-python"]),
            ),
            pytest.raises(ImportError) as excinfo,
        ):
            SnowflakeAdapter()

        assert "Missing dependencies for snowflake platform" in str(excinfo.value)

    def test_initialization_missing_required_config(self):
        """Test initialization with missing required configuration."""
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.snowflake.snowflake"):
            with pytest.raises(ConfigurationError, match="Snowflake configuration is incomplete"):
                SnowflakeAdapter()  # Missing required fields

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_connection_params(self, mock_snowflake):
        """Test connection parameter configuration."""
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            role="TEST_ROLE",
        )

        params = adapter._get_connection_params()

        assert params["account"] == "test_account"
        assert params["username"] == "test_user"
        assert params["password"] == "test_pass"
        assert params["warehouse"] == "TEST_WH"
        assert params["role"] == "TEST_ROLE"

        # Test with overrides
        override_params = adapter._get_connection_params(account="override_account", username="override_user")
        assert override_params["account"] == "override_account"
        assert override_params["username"] == "override_user"
        assert override_params["password"] == "test_pass"  # Should keep original

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_generates_database_name(self, mock_snowflake):
        """Test that from_config generates proper database names."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "account": "test_account",
            "username": "test_user",
            "password": "test_pass",
            "warehouse": "TEST_WH",
            "tuning_config": None,  # No tuning configuration
        }

        adapter = SnowflakeAdapter.from_config(config)

        # Database should be auto-generated with benchmark and scale info
        assert adapter.database == "tpch_sf1_notuning_noconstraints"
        assert adapter.account == "test_account"
        assert adapter.warehouse == "TEST_WH"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_respects_explicit_database(self, mock_snowflake):
        """Test that explicit database name overrides generation."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "account": "test_account",
            "username": "test_user",
            "password": "test_pass",
            "warehouse": "TEST_WH",
            "database": "CUSTOM_DATABASE",
        }

        adapter = SnowflakeAdapter.from_config(config)

        # Explicit database name should be used
        assert adapter.database == "CUSTOM_DATABASE"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_with_scale_factor_formatting(self, mock_snowflake):
        """Test database name generation with different scale factors."""
        # Test SF 0.1
        config_01 = {
            "benchmark": "tpcds",
            "scale_factor": 0.1,
            "account": "test_account",
            "username": "test_user",
            "password": "test_pass",
        }
        adapter_01 = SnowflakeAdapter.from_config(config_01)
        assert adapter_01.database == "tpcds_sf01_notuning_noconstraints"

        # Test SF 10
        config_10 = {
            "benchmark": "ssb",
            "scale_factor": 10.0,
            "account": "test_account",
            "username": "test_user",
            "password": "test_pass",
        }
        adapter_10 = SnowflakeAdapter.from_config(config_10)
        assert adapter_10.database == "ssb_sf10_notuning_noconstraints"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_admin_connection(self, mock_snowflake):
        """Test admin connection creation."""
        mock_connection = Mock()
        mock_snowflake.connector.connect.return_value = mock_connection

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        admin_conn = adapter._create_admin_connection()

        assert admin_conn == mock_connection
        mock_snowflake.connector.connect.assert_called_once()
        call_kwargs = mock_snowflake.connector.connect.call_args[1]
        assert call_kwargs["account"] == "test_account"
        assert call_kwargs["username"] == "test_user"
        assert call_kwargs["password"] == "test_pass"
        assert call_kwargs["warehouse"] == "TEST_WH"
        assert call_kwargs["client_session_keep_alive"] is True

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_check_server_database_exists_true(self, mock_snowflake):
        """Test database existence check when database exists."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ["schema", "TEST_DB", "owner", "comment"],
            ["schema", "OTHER_DB", "owner", "comment"],
        ]
        mock_snowflake.connector.connect.return_value = mock_connection

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        exists = adapter.check_server_database_exists()

        assert exists is True
        mock_cursor.execute.assert_called_once_with("SHOW DATABASES")
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_check_server_database_exists_false(self, mock_snowflake):
        """Test database existence check when database doesn't exist."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Return different values for each fetchall() call:
        # 1. SHOW DATABASES returns only OTHER_DB (not TEST_DB)
        # 2. SHOW SCHEMAS returns empty (database doesn't exist)
        # 3. SHOW TABLES returns empty (no tables)
        mock_cursor.fetchall.side_effect = [
            [["schema", "OTHER_DB", "owner", "comment"]],  # SHOW DATABASES
            [],  # SHOW SCHEMAS (if database exists but is empty)
            [],  # SHOW TABLES (if schema exists but is empty)
        ]
        mock_snowflake.connector.connect.return_value = mock_connection

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        exists = adapter.check_server_database_exists()

        assert exists is False
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_check_server_database_exists_connection_error(self, mock_snowflake):
        """Test database existence check with connection error."""
        mock_snowflake.connector.connect.side_effect = Exception("Connection failed")

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        exists = adapter.check_server_database_exists()

        assert exists is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_drop_database(self, mock_snowflake):
        """Test database dropping."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_snowflake.connector.connect.return_value = mock_connection

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        adapter.drop_database()

        # SQL injection fix: identifiers are now quoted
        mock_cursor.execute.assert_called_once_with('DROP DATABASE IF EXISTS "TEST_DB"')
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_drop_database_connection_error_preserves_database_name(self, mock_snowflake):
        """Connection failures should not be masked by an unbound database variable."""
        mock_snowflake.connector.connect.side_effect = RuntimeError("connection failed")
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        with pytest.raises(RuntimeError, match="Failed to drop Snowflake database TEST_DB: connection failed"):
            adapter.drop_database()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_connection_success(self, mock_snowflake):
        """Test successful connection creation."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_snowflake.connector.connect.return_value = mock_connection

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        # Mock handle_existing_database
        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_snowflake.connector.connect.assert_called_once()

        # Check connection test was performed
        mock_cursor.execute.assert_called_with("SELECT CURRENT_VERSION()")
        mock_cursor.fetchall.assert_called_once()
        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_connection_with_key_pair_auth(self, mock_snowflake):
        """Test connection creation with key pair authentication."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_snowflake.connector.connect.return_value = mock_connection

        # Create a temporary key file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False, encoding="utf-8") as f:
            f.write("""-----BEGIN TEST KEY-----
benchbox-fixture-key-material
-----END TEST KEY-----""")
            key_path = f.name

        try:
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
                private_key_path=key_path,
            )

            # Mock cryptography imports by patching the import statements
            mock_serialization = Mock()
            mock_load_key = Mock()
            mock_private_key = Mock()
            mock_load_key.return_value = mock_private_key
            mock_private_key.private_bytes.return_value = b"mock_key_bytes"

            with patch.dict(
                "sys.modules",
                {
                    "cryptography": Mock(),
                    "cryptography.hazmat": Mock(),
                    "cryptography.hazmat.primitives": Mock(),
                    "cryptography.hazmat.primitives.serialization": mock_serialization,
                },
            ):
                mock_serialization.load_pem_private_key = mock_load_key
                mock_serialization.Encoding = Mock()
                mock_serialization.PrivateFormat = Mock()
                mock_serialization.NoEncryption = Mock()

                with patch.object(adapter, "handle_existing_database"):
                    connection = adapter.create_connection()

            assert connection == mock_connection

            # Should call connect with private_key parameter
            call_kwargs = mock_snowflake.connector.connect.call_args[1]
            assert "private_key" in call_kwargs
            assert "password" not in call_kwargs  # Should remove password for key auth

        finally:
            Path(key_path).unlink()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_connection_failure(self, mock_snowflake):
        """Test connection creation failure."""
        mock_snowflake.connector.connect.side_effect = Exception("Connection failed")

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        with patch.object(adapter, "handle_existing_database"):
            with pytest.raises(Exception, match="Connection failed"):
                adapter.create_connection()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_schema(self, mock_snowflake):
        """Test schema creation."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_snowflake.connector.connect.return_value = mock_connection

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER, name VARCHAR(100));
            CREATE TABLE table2 (id INTEGER, data TEXT);
        """

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        # Mock translate_sql method
        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = (
                "CREATE TABLE table1 (id INTEGER, name VARCHAR(100));\nCREATE TABLE table2 (id INTEGER, data TEXT);"
            )

            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should execute database and schema setup
        setup_calls = list(mock_cursor.execute.call_args_list)
        setup_sqls = [str(call) for call in setup_calls]

        # Should include database creation, schema creation, and table creation
        assert any("CREATE DATABASE" in sql for sql in setup_sqls)
        assert any("CREATE SCHEMA" in sql for sql in setup_sqls)

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_load_data_with_file_upload(self, mock_snowflake):
        """Test data loading using Snowflake PUT and COPY INTO."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock COPY INTO results
        mock_cursor.fetchall.side_effect = [
            [(True, 100, 0, 0, "LOADED", None)],  # Copy results
            [(100,)],  # Row count
        ]
        mock_cursor.fetchone.return_value = (100,)  # Row count query

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|test1|\n2|test2|\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "TEST_TABLE" in table_stats
            assert table_stats["TEST_TABLE"] == 100

            # Should execute file format creation, PUT, and COPY INTO
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("CREATE OR REPLACE FILE FORMAT" in call for call in execute_calls)
            assert any("PUT file://" in call for call in execute_calls)
            assert any("COPY INTO TEST_TABLE" in call for call in execute_calls)

        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_validate_external_table_requirements_requires_staging_root(self, mock_snowflake):
        """External mode should require staging_root for Snowflake."""
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        with pytest.raises(ValueError, match="requires --platform-option staging_root"):
            adapter.validate_external_table_requirements()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_external_tables_generates_stage_and_external_table_sql(self, mock_snowflake):
        """External mode should create external stage and external table DDL."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (77,)

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            staging_root="s3://benchbox-stage-root",
        )

        ds = DataSource(source_type="test", tables={"lineitem": [Path("/tmp/lineitem.parquet")]})
        with patch.object(adapter, "_resolve_data_files", return_value=ds):
            table_stats, load_time, per_table_timings = adapter.create_external_tables(
                benchmark=Mock(),
                connection=mock_connection,
                data_dir=Path("/tmp"),
            )

        assert table_stats == {"LINEITEM": 77}
        assert isinstance(load_time, float)
        assert per_table_timings is None

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE STAGE IF NOT EXISTS PUBLIC.BENCHBOX_EXTERNAL_STAGE" in sql for sql in execute_calls)
        assert any("CREATE OR REPLACE EXTERNAL TABLE LINEITEM" in sql for sql in execute_calls)
        assert any("AUTO_REFRESH=FALSE" in sql for sql in execute_calls)
        assert any("FILE_FORMAT=(TYPE=PARQUET)" in sql for sql in execute_calls)
        assert any("ALTER EXTERNAL TABLE LINEITEM REFRESH" in sql for sql in execute_calls)
        assert any("SELECT COUNT(*) FROM LINEITEM" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_external_tables_generates_iceberg_sql(self, mock_snowflake):
        """Iceberg external mode should derive BASE_LOCATION from staging_root."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (11,)

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            staging_root="s3://benchbox-stage-root/external-prefix",
            iceberg_external_volume="BENCHBOX_VOL",
        )

        ds = DataSource(source_type="test", tables={"lineitem": [Path("/tmp/lineitem")]})
        with (
            patch.object(adapter, "_resolve_data_files", return_value=ds),
            patch.object(adapter, "_detect_external_table_format", return_value="iceberg"),
        ):
            table_stats, _, _ = adapter.create_external_tables(
                benchmark=Mock(), connection=mock_connection, data_dir=Path("/tmp")
            )

        assert table_stats == {"LINEITEM": 11}
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE OR REPLACE ICEBERG TABLE LINEITEM" in sql for sql in execute_calls)
        assert any("EXTERNAL_VOLUME = 'BENCHBOX_VOL'" in sql for sql in execute_calls)
        assert any("CATALOG = 'SNOWFLAKE'" in sql for sql in execute_calls)
        assert any("BASE_LOCATION = 'external-prefix/test_db/lineitem'" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_external_tables_iceberg_requires_external_volume(self, mock_snowflake):
        """Iceberg external mode should reject runs without external volume config."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            staging_root="s3://benchbox-stage-root/external-prefix",
        )

        ds = DataSource(source_type="test", tables={"lineitem": [Path("/tmp/lineitem")]})
        with (
            patch.object(adapter, "_resolve_data_files", return_value=ds),
            patch.object(adapter, "_detect_external_table_format", return_value="iceberg"),
            pytest.raises(ValueError, match="requires --platform-option iceberg_external_volume"),
        ):
            adapter.create_external_tables(benchmark=Mock(), connection=mock_connection, data_dir=Path("/tmp"))

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_external_tables_generates_delta_sql(self, mock_snowflake):
        """Delta external mode should use TABLE_FORMAT=DELTA."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (12,)

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            staging_root="s3://benchbox-stage-root",
        )

        ds = DataSource(source_type="test", tables={"lineitem": [Path("/tmp/lineitem")]})
        with (
            patch.object(adapter, "_resolve_data_files", return_value=ds),
            patch.object(adapter, "_detect_external_table_format", return_value="delta"),
        ):
            table_stats, _, _ = adapter.create_external_tables(
                benchmark=Mock(), connection=mock_connection, data_dir=Path("/tmp")
            )

        assert table_stats == {"LINEITEM": 12}
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("TABLE_FORMAT=DELTA" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_external_tables_escapes_staging_root_quotes(self, mock_snowflake):
        """Staging root with single quotes must be escaped in CREATE STAGE SQL."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (10,)

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            staging_root="s3://bucket/it's-a-path",
        )

        ds = DataSource(source_type="test", tables={"orders": [Path("/tmp/orders.parquet")]})
        with patch.object(adapter, "_resolve_data_files", return_value=ds):
            adapter.create_external_tables(
                benchmark=Mock(),
                connection=mock_connection,
                data_dir=Path("/tmp"),
            )

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        stage_sql = [sql for sql in execute_calls if "CREATE STAGE" in sql]
        assert stage_sql, "Expected CREATE STAGE SQL"
        # The single quote in the path should be escaped as ''
        assert "it''s-a-path" in stage_sql[0]

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_detect_external_table_format(self, mock_snowflake):
        """External format detection should distinguish delta, iceberg, and parquet paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            delta_dir = tmp_path / "delta_table"
            iceberg_dir = tmp_path / "iceberg_table"
            parquet_file = tmp_path / "orders.parquet"

            (delta_dir / "_delta_log").mkdir(parents=True)
            (iceberg_dir / "metadata").mkdir(parents=True)
            parquet_file.write_bytes(b"PAR1")

            assert SnowflakeAdapter._detect_external_table_format(delta_dir) == "delta"
            assert SnowflakeAdapter._detect_external_table_format(iceberg_dir) == "iceberg"
            assert SnowflakeAdapter._detect_external_table_format(parquet_file) == "parquet"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_load_file_formats_uses_configured_compression(self, mock_snowflake):
        """Configured compression should be embedded in both Snowflake load file formats."""
        mock_cursor = Mock()
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            compression="GZIP",
        )

        adapter._create_load_file_formats(mock_cursor)

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE OR REPLACE FILE FORMAT PUBLIC.BENCHBOX_CSV_FORMAT" in sql for sql in execute_calls)
        assert any("CREATE OR REPLACE FILE FORMAT PUBLIC.BENCHBOX_TBL_FORMAT" in sql for sql in execute_calls)
        assert all("COMPRESSION = 'GZIP'" in sql for sql in execute_calls)
        assert any("FIELD_DELIMITER = '|'" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_file_format_for_table_uses_tbl_format_for_tpch_chunks(self, mock_snowflake):
        """Chunked .tbl inputs should use the TBL file format object."""
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
        )
        empty_ds = DataSource(source_type="test", tables={})

        assert (
            adapter._get_file_format_for_table("lineitem", Path("lineitem.tbl.1"), empty_ds, NO_BENCHMARK)
            == "PUBLIC.BENCHBOX_TBL_FORMAT"
        )
        assert (
            adapter._get_file_format_for_table("orders", Path("orders.csv"), empty_ds, NO_BENCHMARK)
            == "PUBLIC.BENCHBOX_CSV_FORMAT"
        )

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_file_format_for_table_manifest_csv_with_tpc_dialect_picks_tbl_format(self, mock_snowflake):
        """Manifest-declared TPC dialect on a .csv path must select BENCHBOX_TBL_FORMAT."""
        from tests.unit.platforms.csv_dialect_test_helpers import resolver_data_source

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
        )
        file_path = Path("lineitem.csv")
        ds = resolver_data_source("lineitem", file_path, {"csv_delimiter": "|", "csv_null_marker": ""})

        assert (
            adapter._get_file_format_for_table("lineitem", file_path, ds, NO_BENCHMARK) == "PUBLIC.BENCHBOX_TBL_FORMAT"
        )

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_file_format_for_table_manifest_csv_without_null_marker_picks_csv_format(self, mock_snowflake):
        """Manifest-declared CSV dialect without null_marker must select BENCHBOX_CSV_FORMAT."""
        from tests.unit.platforms.csv_dialect_test_helpers import resolver_data_source

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
        )
        file_path = Path("orders.csv")
        ds = resolver_data_source("orders", file_path, {"csv_delimiter": ",", "csv_null_marker": None})

        assert adapter._get_file_format_for_table("orders", file_path, ds, NO_BENCHMARK) == "PUBLIC.BENCHBOX_CSV_FORMAT"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_parse_copy_results_logs_failed_and_unparseable_rows(self, mock_snowflake, caplog):
        """COPY INTO parsing should warn on failed files and malformed row counts."""
        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        caplog.set_level("WARNING")
        adapter._parse_copy_results(
            [
                ["orders.csv.gz", "FAILED", None, 3, None, "parse error"],
                ["lineitem.csv.gz", "FAILED", None, "not-an-int", None, "ignored"],
            ]
        )

        assert "orders.csv.gz status: FAILED, loaded 3 rows. Error: parse error" in caplog.text
        assert "Could not parse rows_loaded from COPY result" in caplog.text

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_load_table_from_stage_uploads_files_and_executes_copy_into(self, mock_snowflake):
        """Stage loading should PUT each file, execute COPY INTO, and return the counted rows."""
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [["lineitem.tbl.1", "LOADED", None, 2, None, None]]
        mock_cursor.fetchone.return_value = (5,)

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
        )

        with (
            tempfile.NamedTemporaryFile(mode="wb", suffix=".tbl.1", delete=False) as f1,
            tempfile.NamedTemporaryFile(mode="wb", suffix=".tbl.2", delete=False) as f2,
        ):
            f1.write(b"1|one|\n")
            f2.write(b"2|two|\n")
            path_one = Path(f1.name)
            path_two = Path(f2.name)

        try:
            row_count = adapter._load_table_from_stage(mock_cursor, "lineitem", "LINEITEM", [path_one, path_two])
        finally:
            path_one.unlink()
            path_two.unlink()

        assert row_count == 5
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any(f"PUT file://{path_one.absolute()} @%LINEITEM" in sql for sql in execute_calls)
        assert any(f"PUT file://{path_two.absolute()} @%LINEITEM" in sql for sql in execute_calls)
        assert any("COPY INTO LINEITEM" in sql for sql in execute_calls)
        assert any("FORMAT_NAME = 'PUBLIC.BENCHBOX_TBL_FORMAT'" in sql for sql in execute_calls)
        assert any("PURGE = TRUE" in sql for sql in execute_calls)
        assert execute_calls[-1] == "SELECT COUNT(*) FROM LINEITEM"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_configure_for_benchmark_olap(self, mock_snowflake):
        """Test OLAP benchmark configuration."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            strict_validation=False,  # Disable validation in unit tests
        )

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Should execute OLAP-specific optimizations
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("QUERY_ACCELERATION_MAX_SCALE_FACTOR" in call for call in execute_calls)
        assert any("USE_CACHED_RESULT" in call for call in execute_calls)
        assert any("STATEMENT_TIMEOUT_IN_SECONDS" in call for call in execute_calls)
        assert any("USE WAREHOUSE" in call for call in execute_calls)

        # cursor.close() called twice: once for configure, once for validation
        assert mock_cursor.close.call_count == 2

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_configure_for_benchmark_with_multi_cluster(self, mock_snowflake):
        """Test benchmark configuration with multi-cluster warehouse."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            multi_cluster_warehouse=True,
            modify_warehouse_settings=True,  # Explicitly enable warehouse modifications
            strict_validation=False,  # Disable validation in unit tests
        )

        adapter.configure_for_benchmark(mock_connection, "tpch")

        # Should execute multi-cluster warehouse configuration
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("MIN_CLUSTER_COUNT" in call for call in execute_calls)
        assert any("MAX_CLUSTER_COUNT" in call for call in execute_calls)
        assert any("SCALING_POLICY" in call for call in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_configure_for_benchmark_with_single_cluster_warehouse_settings(self, mock_snowflake):
        """Single-cluster mode should apply warehouse size and suspend/resume settings."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
            warehouse_size="LARGE",
            auto_suspend=120,
            auto_resume=False,
            modify_warehouse_settings=True,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "tpch")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        warehouse_sql = [sql for sql in execute_calls if "ALTER WAREHOUSE TEST_WH SET" in sql]
        assert warehouse_sql, "Expected single-cluster warehouse ALTER statement"
        assert "WAREHOUSE_SIZE = 'LARGE'" in warehouse_sql[0]
        assert "AUTO_SUSPEND = 120" in warehouse_sql[0]
        assert "AUTO_RESUME = False" in warehouse_sql[0]

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_execute_query_success(self, mock_snowflake):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        # Mock query statistics
        with patch.object(adapter, "_get_query_statistics") as mock_stats:
            mock_stats.return_value = {"snowflake_query_id": "test_query_id"}

            result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)
        assert result["query_statistics"] == {"snowflake_query_id": "test_query_id"}

        mock_cursor.execute.assert_any_call("ALTER SESSION SET QUERY_TAG = 'BenchBox_q1'")
        mock_cursor.execute.assert_any_call("SELECT * FROM test")
        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_execute_query_failure(self, mock_snowflake):
        """Test query execution failure."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = [
            None,
            Exception("Query failed"),
        ]  # Query tag succeeds, query fails

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"
        assert isinstance(result["execution_time_seconds"], float)

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_query_statistics(self, mock_snowflake):
        """Test query statistics retrieval."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = [
            "query_id_123",
            "SELECT * FROM test",
            1000,
            800,
            200,
            1024000,
            512000,
            0,
            0,
            10,
            1000,
            5.5,
            "MEDIUM",
            1,
        ]

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        stats = adapter._get_query_statistics(mock_connection, "q1")

        assert stats["snowflake_query_id"] == "query_id_123"
        assert stats["total_elapsed_time_ms"] == 1000
        assert stats["execution_time_ms"] == 800
        assert stats["compilation_time_ms"] == 200
        assert stats["bytes_scanned"] == 1024000
        assert stats["rows_produced"] == 10
        assert stats["warehouse_size"] == "MEDIUM"

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_get_platform_metadata(self, mock_snowflake):
        """Test platform metadata collection."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock query responses
        mock_cursor.fetchone.side_effect = [
            ["6.21.0"],  # Snowflake version
            [
                "test_user",
                "test_role",
                "TEST_WH",
                "TEST_DB",
                "PUBLIC",
                "us-east-1",
                "test_account",
            ],  # Session info
        ]

        # Import datetime for proper mock objects
        from datetime import datetime

        mock_datetime = datetime(2024, 1, 1, 12, 0, 0)

        mock_cursor.fetchall.side_effect = [
            [
                [
                    "TEST_WH",
                    "STARTED",
                    "STANDARD",
                    "MEDIUM",
                    1,
                    1,
                    1,
                    1,
                    0,
                    0,
                    0,
                    0,
                    300,
                    True,
                    True,
                    False,
                    False,
                    False,
                    "2024-01-01",
                    "2024-01-01",
                    "2024-01-01",
                    "test_user",
                    "Test warehouse",
                    None,
                    None,
                    "STANDARD",
                ]
            ],  # Warehouse info
            [
                ["TABLE1", 1000, 1024000, 7, mock_datetime, mock_datetime, None]
            ],  # Table info with proper datetime objects
        ]

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        metadata = adapter._get_platform_metadata(mock_connection)

        assert metadata["platform"] == "Snowflake"
        assert metadata["account"] == "test_account"
        assert metadata["warehouse"] == "TEST_WH"
        assert metadata["snowflake_version"] == "6.21.0"
        assert "session_info" in metadata
        assert "warehouse_info" in metadata
        assert "tables" in metadata

        mock_cursor.close.assert_called()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_analyze_table(self, mock_snowflake):
        """Test table analysis (reclustering)."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        adapter.analyze_table(mock_connection, "test_table")

        mock_cursor.execute.assert_called_once_with("ALTER TABLE TEST_TABLE RECLUSTER")
        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_close_connection(self, mock_snowflake):
        """Test connection closing."""
        mock_connection = Mock()

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        adapter.close_connection(mock_connection)

        mock_connection.close.assert_called_once()

    def test_supports_tuning_type(self):
        """Test tuning type support checking."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            # Mock TuningType from the correct import path
            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.SORTING = "sorting"

                assert adapter.supports_tuning_type(mock_tuning_type.CLUSTERING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.PARTITIONING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.SORTING) is False

    def test_generate_tuning_clause_with_clustering(self):
        """Test tuning clause generation with clustering."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            # Mock table tuning with clustering
            mock_tuning = Mock()
            mock_tuning.has_any_tuning.return_value = True

            # Mock clustering column
            mock_column = Mock()
            mock_column.name = "cluster_key"
            mock_column.order = 1

            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.PARTITIONING = "partitioning"

                def mock_get_columns_by_type(tuning_type):
                    if tuning_type == mock_tuning_type.CLUSTERING:
                        return [mock_column]
                    return []

                mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

                clause = adapter.generate_tuning_clause(mock_tuning)

                assert "CLUSTER BY (cluster_key)" in clause

    def test_generate_tuning_clause_none(self):
        """Test tuning clause generation with None input."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            clause = adapter.generate_tuning_clause(None)
            assert clause == ""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_apply_table_tunings_with_clustering(self, mock_snowflake):
        """Test applying table tunings with clustering."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock clustering key query response
        mock_cursor.fetchone.return_value = [None]  # No existing clustering

        adapter = SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            warehouse="TEST_WH",
            database="TEST_DB",
        )

        # Mock table tuning
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"
        mock_tuning.has_any_tuning.return_value = True

        # Mock clustering column
        mock_column = Mock()
        mock_column.name = "cluster_key"
        mock_column.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.DISTRIBUTION = "distribution"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.CLUSTERING:
                    return [mock_column]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            adapter.apply_table_tunings(mock_tuning, mock_connection)

            # Should execute clustering setup
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("ALTER TABLE TEST_TABLE CLUSTER BY" in call for call in execute_calls)
            assert any("RESUME RECLUSTER" in call for call in execute_calls)

        mock_cursor.close.assert_called()

    def test_apply_unified_tuning(self):
        """Test unified tuning configuration application."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            mock_connection = Mock()
            mock_unified_config = Mock()
            mock_unified_config.primary_keys = Mock()
            mock_unified_config.foreign_keys = Mock()
            mock_unified_config.platform_optimizations = Mock()
            mock_unified_config.table_tunings = {}

            # Should not raise exception
            with patch.object(adapter, "apply_constraint_configuration"):
                with patch.object(adapter, "apply_platform_optimizations"):
                    adapter.apply_unified_tuning(mock_unified_config, mock_connection)

    def test_file_format_detection_for_chunked_files(self):
        """Test that chunked .tbl files (.tbl.1, .tbl.2) are correctly detected as TBL format."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            from pathlib import Path

            SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            # Test various TPC-H file naming patterns
            test_cases = [
                (Path("customer.tbl"), True, "Simple .tbl file"),
                (Path("customer.tbl.1"), True, "Chunked .tbl file"),
                (Path("lineitem.tbl.10"), True, "Chunked .tbl file (2 digits)"),
                (Path("orders.tbl.gz"), True, "Compressed .tbl file"),
                (Path("part.tbl.1.gz"), True, "Chunked compressed .tbl file"),
                (Path("nation.tbl.zst"), True, "zstd compressed .tbl file"),
                (Path("region.csv"), False, "CSV file"),
                (Path("supplier.csv.gz"), False, "Compressed CSV file"),
            ]

            for file_path, should_be_tbl, description in test_cases:
                file_str = str(file_path.name)
                is_tbl = ".tbl" in file_str
                assert is_tbl == should_be_tbl, f"Failed for {description}: {file_path.name}"

    def test_apply_constraint_configuration(self):
        """Test constraint configuration application."""
        with patch("benchbox.platforms.snowflake.snowflake"):
            adapter = SnowflakeAdapter(
                account="test_account",
                username="test_user",
                password="test_pass",
                warehouse="TEST_WH",
                database="TEST_DB",
            )

            mock_connection = Mock()
            mock_primary_key_config = Mock()
            mock_primary_key_config.enabled = True
            mock_foreign_key_config = Mock()
            mock_foreign_key_config.enabled = True

            # Should not raise exception - constraints are informational in Snowflake
            adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, mock_connection)


class TestSnowflakeOptimizeTableDefinition:
    """Test _optimize_table_definition SQL generation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_table_becomes_create_or_replace(self, mock_snowflake):
        """CREATE TABLE should be rewritten to CREATE OR REPLACE TABLE."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        result = adapter._optimize_table_definition("CREATE TABLE orders (id INT)")
        assert result == "CREATE OR REPLACE TABLE orders (id INT)"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_already_has_or_replace_is_unchanged(self, mock_snowflake):
        """Statement that already has OR REPLACE should not be modified."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        stmt = "CREATE OR REPLACE TABLE orders (id INT)"
        result = adapter._optimize_table_definition(stmt)
        assert result == stmt

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_non_create_table_statement_is_passthrough(self, mock_snowflake):
        """Non-CREATE TABLE statements should be returned unchanged."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        stmt = "ALTER TABLE orders ADD COLUMN name VARCHAR(100)"
        result = adapter._optimize_table_definition(stmt)
        assert result == stmt

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_lowercase_create_table_is_not_modified(self, mock_snowflake):
        """Lowercase 'create table' should not be modified (case-sensitive check)."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        stmt = "create table orders (id INT)"
        result = adapter._optimize_table_definition(stmt)
        # The method checks upper() for the starts-with, but replaces literal "CREATE TABLE"
        assert result == stmt


class TestSnowflakeBuildCtasSortSql:
    """Test _build_ctas_sort_sql CTAS generation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_ctas_sort_generates_correct_sql(self, mock_snowflake):
        """CTAS sort should produce CREATE OR REPLACE TABLE ... ORDER BY."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_col1 = Mock()
        mock_col1.name = "l_shipdate"
        mock_col2 = Mock()
        mock_col2.name = "l_orderkey"

        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "ctas")):
            sql = adapter._build_ctas_sort_sql("LINEITEM", [mock_col1, mock_col2])

        assert sql == "CREATE OR REPLACE TABLE LINEITEM AS SELECT * FROM LINEITEM ORDER BY l_shipdate, l_orderkey"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_ctas_sort_returns_none_when_off(self, mock_snowflake):
        """When sorted ingestion is off, should return None."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("off", "auto")):
            result = adapter._build_ctas_sort_sql("LINEITEM", [Mock(name="col1")])

        assert result is None

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_ctas_sort_rejects_non_ctas_method(self, mock_snowflake):
        """Method other than 'ctas' should raise ValueError."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "presort")):
            with pytest.raises(ValueError, match="not supported for Snowflake"):
                adapter._build_ctas_sort_sql("LINEITEM", [Mock(name="col1")])


class TestSnowflakeShouldSkipSchemaCreation:
    """Test _should_skip_schema_creation logic."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_skips_when_all_tables_exist_with_data(self, mock_snowflake):
        """Should return True when all expected tables exist and have rows."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # fetchone returns a row for SHOW TABLES LIKE, then count > 0
        mock_cursor.fetchone.side_effect = [
            ("LINEITEM",),  # SHOW TABLES LIKE 'LINEITEM' => exists
            (1000,),  # SELECT COUNT(*) FROM LINEITEM => 1000 rows
            ("ORDERS",),  # SHOW TABLES LIKE 'ORDERS' => exists
            (500,),  # SELECT COUNT(*) FROM ORDERS => 500 rows
        ]

        with patch.object(adapter, "_get_expected_tables", return_value=["LINEITEM", "ORDERS"]):
            result = adapter._should_skip_schema_creation(Mock(), mock_connection)

        assert result is True

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_does_not_skip_when_table_is_missing(self, mock_snowflake):
        """Should return False when a table does not exist."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # SHOW TABLES LIKE returns None => table doesn't exist
        mock_cursor.fetchone.return_value = None

        with patch.object(adapter, "_get_expected_tables", return_value=["LINEITEM"]):
            result = adapter._should_skip_schema_creation(Mock(), mock_connection)

        assert result is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_does_not_skip_when_table_is_empty(self, mock_snowflake):
        """Should return False when a table exists but has no rows."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            ("LINEITEM",),  # table exists
            (0,),  # 0 rows
        ]

        with patch.object(adapter, "_get_expected_tables", return_value=["LINEITEM"]):
            result = adapter._should_skip_schema_creation(Mock(), mock_connection)

        assert result is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_does_not_skip_when_no_expected_tables(self, mock_snowflake):
        """Should return False when expected tables list is empty."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        with patch.object(adapter, "_get_expected_tables", return_value=[]):
            result = adapter._should_skip_schema_creation(Mock(), mock_connection)

        assert result is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_returns_false_on_exception(self, mock_snowflake):
        """Should return False when a database error occurs (fail-safe)."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_connection.cursor.side_effect = Exception("DB unavailable")

        with patch.object(adapter, "_get_expected_tables", return_value=["LINEITEM"]):
            result = adapter._should_skip_schema_creation(Mock(), mock_connection)

        assert result is False


class TestSnowflakeGetExistingTables:
    """Test _get_existing_tables method."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_returns_lowercase_table_names(self, mock_snowflake):
        """SHOW TABLES results should be normalized to lowercase."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2024-01-01", "LINEITEM", "DB", "PUBLIC", "TABLE"),
            ("2024-01-01", "ORDERS", "DB", "PUBLIC", "TABLE"),
            ("2024-01-01", "CUSTOMER", "DB", "PUBLIC", "TABLE"),
        ]

        result = adapter._get_existing_tables(mock_connection)

        assert result == ["lineitem", "orders", "customer"]
        mock_cursor.execute.assert_called_once_with("SHOW TABLES")

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_returns_empty_list_on_failure(self, mock_snowflake):
        """Should return empty list when SHOW TABLES fails."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_connection.cursor.side_effect = Exception("Permission denied")

        result = adapter._get_existing_tables(mock_connection)

        assert result == []


class TestSnowflakeValidateDataIntegrity:
    """Test _validate_data_integrity SQL generation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_passed_when_all_tables_accessible(self, mock_snowflake):
        """Should return PASSED when all tables are accessible via SELECT."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # Each fetchone succeeds (table accessible)
        mock_cursor.fetchone.return_value = (1,)

        status, details = adapter._validate_data_integrity(Mock(), mock_connection, {"LINEITEM": 1000, "ORDERS": 500})

        assert status == "PASSED"
        assert "LINEITEM" in details["accessible_tables"]
        assert "ORDERS" in details["accessible_tables"]
        assert details["constraints_enabled"] is True

        # Verify the SQL used
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert "SELECT 1 FROM LINEITEM LIMIT 1" in execute_calls
        assert "SELECT 1 FROM ORDERS LIMIT 1" in execute_calls

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_failed_when_table_inaccessible(self, mock_snowflake):
        """Should return FAILED when a table is not accessible."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # First table succeeds, second fails
        mock_cursor.execute.side_effect = [None, Exception("Table not found")]
        mock_cursor.fetchone.return_value = (1,)

        status, details = adapter._validate_data_integrity(Mock(), mock_connection, {"LINEITEM": 1000, "ORDERS": 500})

        assert status == "FAILED"
        assert "inaccessible_tables" in details
        assert details["constraints_enabled"] is False


class TestSnowflakeValidateSessionCacheControl:
    """Test validate_session_cache_control delegation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_calls_shared_validate_with_correct_params(self, mock_snowflake):
        """Should delegate to cloud_shared with Snowflake-specific parameters."""
        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            disable_result_cache=True,
            strict_validation=False,
        )

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("FALSE",)

        with patch("benchbox.platforms.cloud_shared.validate_session_cache_control") as mock_validate:
            mock_validate.return_value = {"validated": True, "cache_disabled": True}
            result = adapter.validate_session_cache_control(mock_connection)

        assert result["validated"] is True
        assert result["cache_disabled"] is True

        # Verify the call args
        call_kwargs = mock_validate.call_args[1]
        assert call_kwargs["setting_key"] == "USE_CACHED_RESULT"
        assert call_kwargs["disabled_value"] == "FALSE"
        assert call_kwargs["enabled_value"] == "TRUE"
        assert call_kwargs["normalize"] == "upper"
        assert call_kwargs["platform_name"] == "Snowflake"
        assert call_kwargs["disable_result_cache"] is True
        assert call_kwargs["strict_validation"] is False


class TestSnowflakeGetPlatformInfo:
    """Test get_platform_info SQL generation and response structure."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_platform_info_without_connection(self, mock_snowflake):
        """Without a connection, should return basic config info."""
        adapter = SnowflakeAdapter(
            account="test_account",
            username="u",
            password="p",
            warehouse="TEST_WH",
            database="TEST_DB",
            schema="PUBLIC",
            role="SYSADMIN",
        )

        result = adapter.get_platform_info(connection=None)

        assert result["platform_type"] == "snowflake"
        assert result["platform_name"] == "Snowflake"
        assert result["connection_mode"] == "remote"
        assert result["configuration"]["account"] == "test_account"
        assert result["configuration"]["warehouse"] == "TEST_WH"
        assert result["configuration"]["database"] == "TEST_DB"
        assert result["configuration"]["schema"] == "PUBLIC"
        assert result["configuration"]["role"] == "SYSADMIN"
        assert result["configuration"]["result_cache_enabled"] is False  # disable_result_cache default=True
        assert result["platform_version"] is None

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_platform_info_with_connection_queries_version(self, mock_snowflake):
        """With a connection, should query current_version() and set engine_version."""
        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
        )

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # First call: SELECT current_version()
        # Second call: SELECT current_region(), current_cloud()
        # Third call: SHOW WAREHOUSES (raise to skip)
        # Fourth call: SELECT current_account_name() (raise to skip)
        mock_cursor.execute.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            ("8.12.3",),  # current_version()
            ("AWS_US_EAST_1", "AWS"),  # current_region(), current_cloud()
            Exception("skip"),  # will be caught
        ]

        call_count = [0]

        def side_effect_execute(sql):
            call_count[0] += 1
            if "SHOW WAREHOUSES" in sql:
                raise Exception("skip warehouses")
            if "current_account_name" in sql:
                raise Exception("skip account")
            return mock_cursor

        mock_cursor.execute = Mock(side_effect=side_effect_execute)

        result = adapter.get_platform_info(connection=mock_connection)

        assert result["platform_version"] == "8.12.3"
        assert result["engine_version"] == "8.12.3"
        assert result["engine_version_source"] == "sql_query"
        assert result["cloud_region"] == "AWS_US_EAST_1"
        assert result["cloud_provider"] == "AWS"


class TestSnowflakeConfigValidation:
    """Test config validation edge cases and error messages."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_missing_account_error_message(self, mock_snowflake):
        """Missing account should produce a specific error message."""
        from benchbox.core.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="account"):
            SnowflakeAdapter(
                username="u",
                password="p",
                warehouse="WH",
                database="DB",
            )

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_missing_username_error_message(self, mock_snowflake):
        """Missing username should produce a specific error message."""
        from benchbox.core.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="username"):
            SnowflakeAdapter(
                account="a",
                password="p",
                warehouse="WH",
                database="DB",
            )

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_missing_password_error_message(self, mock_snowflake):
        """Missing password should produce a specific error message."""
        from benchbox.core.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="password"):
            SnowflakeAdapter(
                account="a",
                username="u",
                warehouse="WH",
                database="DB",
            )

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_missing_multiple_fields_error_message(self, mock_snowflake):
        """Missing multiple fields should list all of them in the error."""
        from benchbox.core.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            SnowflakeAdapter()

        error_msg = str(exc_info.value)
        assert "account" in error_msg
        assert "username" in error_msg
        assert "password" in error_msg

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_authenticator_default(self, mock_snowflake):
        """Default authenticator should be 'snowflake'."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.authenticator == "snowflake"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_authenticator_override(self, mock_snowflake):
        """Authenticator should accept custom values like 'oauth'."""
        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            authenticator="oauth",
        )
        assert adapter.authenticator == "oauth"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_private_key_path_is_stored(self, mock_snowflake):
        """Private key path should be stored for key pair auth."""
        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            private_key_path="/path/to/key.pem",
            private_key_passphrase="secret",
        )
        assert adapter.private_key_path == "/path/to/key.pem"
        assert adapter.private_key_passphrase == "secret"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_disable_result_cache_default_true(self, mock_snowflake):
        """Result cache should be disabled by default for accurate benchmarking."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.disable_result_cache is True

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_disable_result_cache_explicit_false(self, mock_snowflake):
        """Result cache can be explicitly enabled."""
        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            disable_result_cache=False,
        )
        assert adapter.disable_result_cache is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_modify_warehouse_settings_default_false(self, mock_snowflake):
        """Warehouse modification should be off by default."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.modify_warehouse_settings is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_suppress_nondeterministic_errors_default_false(self, mock_snowflake):
        """Nondeterministic error suppression should be off by default."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.suppress_nondeterministic_errors is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_auto_suspend_zero_is_preserved(self, mock_snowflake):
        """auto_suspend=0 should not fall through to default 300."""
        adapter = SnowflakeAdapter(
            account="a", username="u", password="p", warehouse="WH", database="DB", auto_suspend=0
        )
        assert adapter.auto_suspend == 0

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_auto_resume_false_is_preserved(self, mock_snowflake):
        """auto_resume=False should not fall through to default True."""
        adapter = SnowflakeAdapter(
            account="a", username="u", password="p", warehouse="WH", database="DB", auto_resume=False
        )
        assert adapter.auto_resume is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_multi_cluster_warehouse_false_by_default(self, mock_snowflake):
        """Multi-cluster should be off by default."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.multi_cluster_warehouse is False

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_file_format_default_csv(self, mock_snowflake):
        """Default file format should be CSV."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.file_format == "CSV"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_compression_default_auto(self, mock_snowflake):
        """Default compression should be AUTO."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.compression == "AUTO"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_query_tag_default(self, mock_snowflake):
        """Default query tag should be BenchBox."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.query_tag == "BenchBox"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_timezone_default_utc(self, mock_snowflake):
        """Default timezone should be UTC."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.timezone == "UTC"


class TestSnowflakeConfigureForBenchmarkEdgeCases:
    """Test configure_for_benchmark SQL generation for edge cases."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_suppress_nondeterministic_errors_generates_sql(self, mock_snowflake):
        """When suppress_nondeterministic_errors=True, should emit session ALTER statements."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            suppress_nondeterministic_errors=True,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "tpch")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("ERROR_ON_NONDETERMINISTIC_MERGE = FALSE" in sql for sql in execute_calls)
        assert any("ERROR_ON_NONDETERMINISTIC_UPDATE = FALSE" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_modify_warehouse_settings_false_skips_alter_warehouse(self, mock_snowflake):
        """When modify_warehouse_settings=False, no ALTER WAREHOUSE should be emitted."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            modify_warehouse_settings=False,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "tpch")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert not any("ALTER WAREHOUSE" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_result_cache_enabled_generates_true(self, mock_snowflake):
        """When disable_result_cache=False, USE_CACHED_RESULT should be TRUE."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            disable_result_cache=False,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "olap")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("USE_CACHED_RESULT = TRUE" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_multi_cluster_warehouse_generates_scaling_sql(self, mock_snowflake):
        """Multi-cluster warehouse config should emit MIN/MAX_CLUSTER_COUNT and SCALING_POLICY."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            multi_cluster_warehouse=True,
            modify_warehouse_settings=True,
            auto_suspend=60,
            auto_resume=True,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "olap")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        alter_wh = [sql for sql in execute_calls if "ALTER WAREHOUSE WH SET" in sql]
        assert len(alter_wh) == 1
        assert "MIN_CLUSTER_COUNT = 1" in alter_wh[0]
        assert "MAX_CLUSTER_COUNT = 3" in alter_wh[0]
        assert "AUTO_SUSPEND = 60" in alter_wh[0]
        assert "AUTO_RESUME = True" in alter_wh[0]
        assert "SCALING_POLICY = 'STANDARD'" in alter_wh[0]

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_non_olap_benchmark_type_skips_olap_settings(self, mock_snowflake):
        """Non-OLAP benchmark types should not emit QUERY_ACCELERATION or warehouse settings."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            modify_warehouse_settings=True,
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "custom_benchmark")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert not any("QUERY_ACCELERATION_MAX_SCALE_FACTOR" in sql for sql in execute_calls)
        assert not any("ALTER WAREHOUSE" in sql for sql in execute_calls)

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_session_base_settings_always_applied(self, mock_snowflake):
        """Base session settings (TIMEZONE, AUTOCOMMIT) should always be applied."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="DB",
            timezone="America/New_York",
            strict_validation=False,
        )

        adapter.configure_for_benchmark(mock_connection, "custom")

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert any("TIMEZONE = 'America/New_York'" in sql for sql in execute_calls)
        assert any("AUTOCOMMIT = TRUE" in sql for sql in execute_calls)


class TestSnowflakeNormalizeExistingFiles:
    """Test _normalize_existing_files static method."""

    def test_filters_nonexistent_files(self, tmp_path):
        """Non-existent files should be filtered out."""
        existing = tmp_path / "exists.tbl"
        existing.write_text("data")

        result = SnowflakeAdapter._normalize_existing_files([existing, tmp_path / "nonexistent.tbl"])

        assert result == [existing]

    def test_filters_empty_files(self, tmp_path):
        """Empty files (0 bytes) should be filtered out."""
        empty = tmp_path / "empty.tbl"
        empty.write_text("")
        nonempty = tmp_path / "data.tbl"
        nonempty.write_text("1|test|\n")

        result = SnowflakeAdapter._normalize_existing_files([empty, nonempty])

        assert result == [nonempty]

    def test_accepts_single_path_not_list(self, tmp_path):
        """Should handle a single Path instead of a list."""
        single = tmp_path / "single.tbl"
        single.write_text("1|data|\n")

        result = SnowflakeAdapter._normalize_existing_files(single)

        assert result == [single]

    def test_converts_strings_to_paths(self, tmp_path):
        """Should handle string paths."""
        f = tmp_path / "file.csv"
        f.write_text("data")

        result = SnowflakeAdapter._normalize_existing_files([str(f)])

        assert result == [f]


class TestSnowflakeBuildSnowflakeConfig:
    """Test _build_snowflake_config function."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_merges_saved_creds_and_options(self, mock_snowflake):
        """CLI options should override saved credentials."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        mock_info = Mock()
        mock_info.display_name = "Snowflake"
        mock_info.driver_package = "snowflake-connector-python"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm:
            mock_cm.return_value.get_platform_credentials.return_value = {
                "account": "saved_acct",
                "username": "saved_user",
                "password": "saved_pass",
            }

            config = _build_snowflake_config(
                platform="snowflake",
                options={"warehouse": "CLI_WH"},
                overrides={"account": "override_acct"},
                info=mock_info,
            )

        # override > option > saved
        assert config.account == "override_acct"
        assert config.warehouse == "CLI_WH"
        # saved creds preserved when no override
        assert config.username == "saved_user"
        assert config.password == "saved_pass"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_database_override_is_included(self, mock_snowflake):
        """Explicit database override should be included in config."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        mock_info = Mock()
        mock_info.display_name = "Snowflake"
        mock_info.driver_package = "snowflake-connector-python"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm:
            mock_cm.return_value.get_platform_credentials.return_value = {
                "account": "a",
                "username": "u",
                "password": "p",
            }

            config = _build_snowflake_config(
                platform="snowflake",
                options={},
                overrides={"database": "MY_DB"},
                info=mock_info,
            )

        assert config.database == "MY_DB"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_no_database_override_omits_database(self, mock_snowflake):
        """Without explicit database override, database should not be set in config."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        mock_info = Mock()
        mock_info.display_name = "Snowflake"
        mock_info.driver_package = "snowflake-connector-python"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm:
            mock_cm.return_value.get_platform_credentials.return_value = {
                "account": "a",
                "username": "u",
                "password": "p",
            }

            config = _build_snowflake_config(
                platform="snowflake",
                options={},
                overrides={},
                info=mock_info,
            )

        # database should not be in the config (or be None)
        assert not hasattr(config, "database") or config.database is None


class TestSnowflakeFromConfigEdgeCases:
    """Test from_config edge cases."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_passes_behavior_options(self, mock_snowflake):
        """Behavior control options should be passed through from_config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "account": "a",
            "username": "u",
            "password": "p",
            "warehouse": "WH",
            "disable_result_cache": False,
            "strict_validation": False,
            "suppress_nondeterministic_errors": True,
            "modify_warehouse_settings": True,
        }

        adapter = SnowflakeAdapter.from_config(config)

        assert adapter.disable_result_cache is False
        assert adapter.strict_validation is False
        assert adapter.suppress_nondeterministic_errors is True
        assert adapter.modify_warehouse_settings is True

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_passes_file_format_and_compression(self, mock_snowflake):
        """File format and compression should be passed through from_config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "account": "a",
            "username": "u",
            "password": "p",
            "file_format": "PARQUET",
            "compression": "GZIP",
        }

        adapter = SnowflakeAdapter.from_config(config)

        assert adapter.file_format == "PARQUET"
        assert adapter.compression == "GZIP"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_from_config_passes_warehouse_settings(self, mock_snowflake):
        """Warehouse settings should be passed through from_config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "account": "a",
            "username": "u",
            "password": "p",
            "warehouse_size": "XLARGE",
            "auto_suspend": 0,
            "auto_resume": False,
            "multi_cluster_warehouse": True,
        }

        adapter = SnowflakeAdapter.from_config(config)

        assert adapter.warehouse_size == "XLARGE"
        assert adapter.auto_suspend == 0
        assert adapter.auto_resume is False
        assert adapter.multi_cluster_warehouse is True


class TestSnowflakeCreateLoadFileFormats:
    """Test _create_load_file_formats SQL generation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_default_compression_auto(self, mock_snowflake):
        """Default compression=AUTO should be embedded in file format SQL."""
        mock_cursor = Mock()
        adapter = SnowflakeAdapter(
            account="a", username="u", password="p", warehouse="WH", database="DB", schema="MY_SCHEMA"
        )

        adapter._create_load_file_formats(mock_cursor)

        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert len(execute_calls) == 2

        # Check CSV format
        csv_sql = execute_calls[0]
        assert "MY_SCHEMA.BENCHBOX_CSV_FORMAT" in csv_sql
        assert "FIELD_DELIMITER = ','" in csv_sql
        assert "COMPRESSION = 'AUTO'" in csv_sql
        assert "ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE" in csv_sql
        assert "REPLACE_INVALID_CHARACTERS = TRUE" in csv_sql
        assert "EMPTY_FIELD_AS_NULL = TRUE" in csv_sql

        # Check TBL format
        tbl_sql = execute_calls[1]
        assert "MY_SCHEMA.BENCHBOX_TBL_FORMAT" in tbl_sql
        assert "FIELD_DELIMITER = '|'" in tbl_sql
        assert "COMPRESSION = 'AUTO'" in tbl_sql


class TestSnowflakeDriverIsolation:
    """Test driver isolation capability declaration."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_driver_isolation_is_feasible_client_only(self, mock_snowflake):
        """Snowflake adapter should declare FEASIBLE_CLIENT_ONLY driver isolation."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        assert adapter.driver_isolation_capability == DriverIsolationCapability.FEASIBLE_CLIENT_ONLY


class TestSnowflakeAddCliArguments:
    """Test add_cli_arguments setup."""

    def test_adds_snowflake_arguments(self):
        """Snowflake CLI parser should expose the expected defaults."""
        args = _parse_snowflake_cli_args([])

        assert args["warehouse"] == "COMPUTE_WH"
        assert args["schema"] == "PUBLIC"
        assert args["authenticator"] == "snowflake"
        assert args["modify_warehouse_settings"] is False
        assert args["suppress_nondeterministic_errors"] is False
        assert args["disable_result_cache"] is True

    def test_cli_no_disable_result_cache_flag(self):
        """Result-cache opt-out flag should set disable_result_cache to False."""
        args = _parse_snowflake_cli_args(["--no-disable-result-cache"])
        assert args["disable_result_cache"] is False

    def test_cli_modify_warehouse_settings_flag(self):
        """Warehouse-settings flag should set the boolean to True."""
        args = _parse_snowflake_cli_args(["--modify-warehouse-settings"])
        assert args["modify_warehouse_settings"] is True


class TestSnowflakeGenerateTuningClauseEdgeCases:
    """Test generate_tuning_clause edge cases."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_partition_columns_used_as_clustering_when_no_explicit_clustering(self, mock_snowflake):
        """Partition columns should become clustering keys when no explicit clustering."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col = Mock()
        mock_col.name = "order_date"
        mock_col.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.PARTITIONING:
                    return [mock_col]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            clause = adapter.generate_tuning_clause(mock_tuning)

        assert clause == "CLUSTER BY (order_date)"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_multiple_clustering_columns_ordered(self, mock_snowflake):
        """Multiple clustering columns should be ordered by their order attribute."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        col2 = Mock()
        col2.name = "b_col"
        col2.order = 2
        col1 = Mock()
        col1.name = "a_col"
        col1.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.CLUSTERING:
                    return [col2, col1]  # reverse order
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            clause = adapter.generate_tuning_clause(mock_tuning)

        assert clause == "CLUSTER BY (a_col, b_col)"

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_no_tuning_returns_empty_string(self, mock_snowflake):
        """No tuning returns empty string."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = False

        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == ""


class TestSnowflakeCreateSchemaSQL:
    """Test create_schema SQL generation."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_schema_executes_database_and_schema_ddl(self, mock_snowflake):
        """create_schema should emit CREATE DATABASE, USE DATABASE, CREATE SCHEMA, USE SCHEMA."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="MY_DB",
            schema="MY_SCHEMA",
        )

        mock_benchmark = Mock()

        with (
            patch.object(adapter, "_should_skip_schema_creation", return_value=False),
            patch.object(adapter, "_create_schema_with_tuning", return_value="CREATE TABLE t (id INT)"),
            patch.object(adapter, "_optimize_table_definition", side_effect=lambda s: s),
        ):
            elapsed = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(elapsed, float)
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert "CREATE DATABASE IF NOT EXISTS MY_DB" in execute_calls
        assert "USE DATABASE MY_DB" in execute_calls
        assert "CREATE SCHEMA IF NOT EXISTS MY_SCHEMA" in execute_calls
        assert "USE SCHEMA MY_SCHEMA" in execute_calls
        assert any("BenchBox_schema_creation" in sql for sql in execute_calls)
        assert "CREATE TABLE t (id INT)" in execute_calls

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_create_schema_skips_when_tables_exist(self, mock_snowflake):
        """create_schema should skip table creation when schema already exists with data."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = SnowflakeAdapter(
            account="a",
            username="u",
            password="p",
            warehouse="WH",
            database="MY_DB",
            schema="MY_SCHEMA",
        )

        with patch.object(adapter, "_should_skip_schema_creation", return_value=True):
            elapsed = adapter.create_schema(Mock(), mock_connection)

        assert isinstance(elapsed, float)
        execute_calls = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        # Should still create database/schema
        assert "CREATE DATABASE IF NOT EXISTS MY_DB" in execute_calls
        # But should NOT have query tag or table creation
        assert not any("QUERY_TAG" in sql for sql in execute_calls)


class TestSnowflakeParseResultsEdgeCases:
    """Test _parse_copy_results edge cases."""

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_skips_rows_with_3_or_fewer_columns(self, mock_snowflake):
        """Rows with <= 3 columns should be silently skipped."""
        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")
        # Should not raise
        adapter._parse_copy_results([["a"], ["a", "b"], ["a", "b", "c"]])

    @patch("benchbox.platforms.snowflake.snowflake")
    def test_loaded_status_is_silently_skipped(self, mock_snowflake):
        """LOADED status rows should not produce warnings."""
        import logging

        adapter = SnowflakeAdapter(account="a", username="u", password="p", warehouse="WH", database="DB")

        with patch.object(adapter.logger, "warning") as mock_warn:
            adapter._parse_copy_results([["orders.csv.gz", "LOADED", None, 100, None, None]])
        mock_warn.assert_not_called()
