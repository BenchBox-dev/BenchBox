"""Tests for pg_mooncake platform adapter.

Tests the PgMooncakeAdapter for columnstore PostgreSQL support.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import inspect
from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.pg_mooncake as pg_mooncake_module
import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.pg_mooncake import PgMooncakeAdapter
from benchbox.platforms.postgresql import POSTGRES_DIALECT

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def pg_mooncake_stubs(monkeypatch):
    """Patch psycopg objects so tests don't require the real driver.

    Must patch both pg_mooncake and postgresql modules since PgMooncakeAdapter
    inherits from PostgreSQLAdapter which checks for psycopg in its __init__.
    """
    mock_psycopg = Mock()
    mock_psycopg.__version__ = "3.1.0"

    # Patch both modules - parent checks in postgresql module
    monkeypatch.setattr(pg_mooncake_module, "psycopg", mock_psycopg)
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)

    return mock_psycopg


class TestPgMooncakeAdapter:
    """Unit tests for pg_mooncake adapter wiring and SQL handling."""

    def test_initialization_defaults(self, pg_mooncake_stubs):
        """Adapter should initialize with pg_mooncake defaults when stubs are present."""
        adapter = PgMooncakeAdapter()

        assert adapter.platform_name == "pg_mooncake"
        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.host == "localhost"
        assert adapter.port == 5432
        assert adapter.database == "benchbox"
        assert adapter.username == "postgres"
        assert adapter.schema == "public"
        # pg_mooncake-specific defaults
        assert adapter.storage_mode == "local"
        assert adapter.mooncake_bucket is None

    def test_initialization_with_config(self, pg_mooncake_stubs):
        """Adapter should accept custom pg_mooncake configuration."""
        adapter = PgMooncakeAdapter(
            host="mooncake.example.com",
            port=5433,
            database="analytics_db",
            username="custom_user",
            password="secret",
            schema="analytics",
            storage_mode="local",
        )

        assert adapter.host == "mooncake.example.com"
        assert adapter.port == 5433
        assert adapter.database == "analytics_db"
        assert adapter.username == "custom_user"
        assert adapter.password == "secret"
        assert adapter.schema == "analytics"
        assert adapter.storage_mode == "local"

    def test_dialect_is_postgres(self, pg_mooncake_stubs):
        """pg_mooncake should use PostgreSQL dialect (compatible)."""
        adapter = PgMooncakeAdapter()

        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.get_target_dialect() == "postgres"

    def test_from_config_basic(self, pg_mooncake_stubs):
        """from_config should create adapter with correct settings."""
        config = {
            "host": "mooncake.local",
            "port": 5433,
            "database": "test_analytics",
            "storage_mode": "local",
        }

        adapter = PgMooncakeAdapter.from_config(config)

        assert adapter.host == "mooncake.local"
        assert adapter.port == 5433
        assert adapter.database == "test_analytics"
        assert adapter.storage_mode == "local"

    def test_from_config_generates_database_name(self, pg_mooncake_stubs):
        """from_config should generate database name from benchmark config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = PgMooncakeAdapter.from_config(config)

        assert "benchbox" in adapter.database

    def test_from_config_uses_provided_database(self, pg_mooncake_stubs):
        """from_config should prefer explicit database name over generated one."""
        config = {
            "database": "explicit_db",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = PgMooncakeAdapter.from_config(config)

        assert adapter.database == "explicit_db"

    def test_inherits_postgresql_connection_params(self, pg_mooncake_stubs):
        """pg_mooncake adapter should inherit PostgreSQL connection parameter handling."""
        adapter = PgMooncakeAdapter(
            host="mooncake.example.com",
            port=5433,
            database="testdb",
            username="testuser",
            password="testpass",
            sslmode="require",
            connect_timeout=15,
        )

        params = adapter._get_connection_params()

        assert params["host"] == "mooncake.example.com"
        assert params["port"] == 5433
        assert params["dbname"] == "testdb"
        assert params["user"] == "testuser"
        assert params["password"] == "testpass"
        assert params["sslmode"] == "require"
        assert params["connect_timeout"] == 15

    def test_supports_tuning_type(self, pg_mooncake_stubs):
        """pg_mooncake columnstore tables should not support most PostgreSQL tuning."""
        adapter = PgMooncakeAdapter()

        from benchbox.core.tuning.interface import TuningType

        # Columnstore tables don't support PostgreSQL tuning
        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is False
        assert adapter.supports_tuning_type(TuningType.SORTING) is False
        assert adapter.supports_tuning_type(TuningType.DISTRIBUTION) is False
        assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is False
        assert adapter.supports_tuning_type(TuningType.FOREIGN_KEYS) is False

    def test_get_platform_info_basic(self, pg_mooncake_stubs):
        """Platform info should show pg_mooncake details."""
        adapter = PgMooncakeAdapter(storage_mode="local")

        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "pg_mooncake"
        assert info["platform_name"] == "pg_mooncake"
        assert info["configuration"]["storage_mode"] == "local"


class TestPgMooncakeColumnstoreDDL:
    """Tests for columnstore DDL generation."""

    def test_add_columnstore_basic(self, pg_mooncake_stubs):
        """_add_columnstore_access_method should add USING mooncake."""
        adapter = PgMooncakeAdapter()

        result = adapter._add_columnstore_access_method("CREATE TABLE foo (id INT, name TEXT);")

        assert "USING mooncake" in result
        assert result.endswith(";")

    def test_add_columnstore_no_semicolon(self, pg_mooncake_stubs):
        """Should handle DDL without trailing semicolon."""
        adapter = PgMooncakeAdapter()

        result = adapter._add_columnstore_access_method("CREATE TABLE foo (id INT)")

        assert "USING mooncake" in result

    def test_add_columnstore_already_present(self, pg_mooncake_stubs):
        """Should not double-add USING mooncake."""
        adapter = PgMooncakeAdapter()

        ddl = "CREATE TABLE foo (id INT) USING mooncake;"
        result = adapter._add_columnstore_access_method(ddl)

        assert result.count("USING mooncake") == 1

    def test_add_columnstore_skips_non_create_table(self, pg_mooncake_stubs):
        """Should not modify non-CREATE TABLE statements."""
        adapter = PgMooncakeAdapter()

        # ALTER TABLE should be unchanged
        alter = "ALTER TABLE foo ADD COLUMN bar TEXT;"
        assert adapter._add_columnstore_access_method(alter) == alter

        # CREATE INDEX should be unchanged
        index = "CREATE INDEX idx ON foo (id);"
        assert adapter._add_columnstore_access_method(index) == index

    def test_create_schema_adds_columnstore(self, pg_mooncake_stubs):
        """create_schema should keep heap tables for the COPY load phase."""
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        schema_sql = (
            "CREATE TABLE foo (id INT, name TEXT);"
            "CREATE INDEX idx_foo ON foo (id);"
            "CREATE TABLE bar (x BIGINT, y DECIMAL(10,2));"
        )

        with patch.object(adapter, "_create_schema_with_tuning", return_value=schema_sql):
            adapter.create_schema(Mock(), conn)

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        assert executed[0] == "CREATE TABLE foo (id INT, name TEXT)"
        assert executed[1] == "CREATE INDEX idx_foo ON foo (id)"
        assert executed[2] == "CREATE TABLE bar (x BIGINT, y DECIMAL(10,2))"
        conn.commit.assert_called_once()
        cursor.close.assert_called_once()

    def test_create_schema_signature_matches_postgresql_parent(self, pg_mooncake_stubs):
        """create_schema must keep the PostgreSQLAdapter public contract."""
        assert inspect.signature(PgMooncakeAdapter.create_schema) == inspect.signature(
            postgresql_module.PostgreSQLAdapter.create_schema
        )

    def test_create_schema_fk_strip_retry_preserves_heap_table(self, pg_mooncake_stubs):
        """When the initial CREATE TABLE fails and FK-strip retry runs, the retry
        statement should remain loadable by PostgreSQL COPY before mirror promotion.
        """
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = [
            Exception("FK violation"),
            None,
        ]
        schema_sql = "CREATE TABLE foo (id INT, ref_id INT, FOREIGN KEY (ref_id) REFERENCES bar(id));"

        with patch.object(adapter, "_create_schema_with_tuning", return_value=schema_sql):
            adapter.create_schema(Mock(), conn)

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        assert len(executed) == 2
        assert "USING mooncake" not in executed[0]
        assert "FOREIGN KEY" in executed[0]
        assert "USING mooncake" not in executed[1]
        assert "FOREIGN KEY" not in executed[1]
        conn.rollback.assert_called_once()


class TestPgMooncakeExtensionVerification:
    """Tests for pg_mooncake extension verification in create_connection."""

    def test_create_connection_verifies_extension(self, pg_mooncake_stubs):
        """create_connection should verify pg_mooncake extension is available."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("0.5.0",),  # extension exists
            (1,),
        ]

        pg_mooncake_stubs.connect.return_value = mock_conn

        adapter = PgMooncakeAdapter()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        extension_check = any("pg_mooncake" in call.lower() for call in calls)
        assert extension_check

    def test_create_connection_raises_when_extension_missing(self, pg_mooncake_stubs):
        """create_connection should raise when pg_mooncake is not available."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            None,  # extension not found
            None,  # still not found after CREATE
            (1,),
        ]

        pg_mooncake_stubs.connect.return_value = mock_conn

        adapter = PgMooncakeAdapter()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
            pytest.raises(RuntimeError, match="pg_mooncake extension is not available"),
        ):
            adapter.create_connection()

    def test_create_connection_uses_cascade_when_creating_extension(self, pg_mooncake_stubs):
        """pg_mooncake requires dependent extensions to be created as needed."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (1,),  # parent PostgreSQL connection verification
            None,  # extension not found
            ("0.5.0",),  # extension exists after CREATE EXTENSION CASCADE
        ]

        pg_mooncake_stubs.connect.return_value = mock_conn

        adapter = PgMooncakeAdapter()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("CREATE EXTENSION IF NOT EXISTS pg_mooncake CASCADE" in call for call in calls)


class TestPgMooncakeLoadPromotion:
    """Tests for heap-load to mooncake-mirror promotion."""

    def test_load_data_promotes_loaded_tables_to_mooncake_mirrors(self, pg_mooncake_stubs, tmp_path):
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        cursor.fetchone.side_effect = [(2,), (3,)]
        conn.cursor.return_value = cursor

        with patch.object(
            postgresql_module.PostgreSQLAdapter,
            "load_data",
            return_value=({"orders": 2, "lineitem": 3, "empty": 0}, 1.25, None),
        ) as parent_load:
            stats, load_time, extra = adapter.load_data(Mock(), conn, tmp_path)

        parent_load.assert_called_once()
        assert load_time == 1.25
        assert extra is None
        assert stats == {"orders": 2, "lineitem": 3, "empty": 0}

        executed = [call.args for call in cursor.execute.call_args_list]
        assert ('ALTER TABLE "orders" RENAME TO "__bb_moon_src_orders"',) in executed
        assert ("CALL mooncake.create_table(%s, %s)", ("orders", "__bb_moon_src_orders")) in executed
        assert ('SELECT COUNT(*) FROM "orders"',) in executed
        assert ('ALTER TABLE "lineitem" RENAME TO "__bb_moon_src_lineitem"',) in executed
        assert ("CALL mooncake.create_table(%s, %s)", ("lineitem", "__bb_moon_src_lineitem")) in executed
        assert ('SELECT COUNT(*) FROM "lineitem"',) in executed
        assert all("empty" not in str(args) for args in executed)
        assert conn.commit.call_count == 3
        cursor.close.assert_called_once()

    def test_load_data_rolls_back_on_promotion_failure(self, pg_mooncake_stubs, tmp_path):
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        cursor.execute.side_effect = RuntimeError("promotion failed")
        conn.cursor.return_value = cursor

        with (
            patch.object(
                postgresql_module.PostgreSQLAdapter,
                "load_data",
                return_value=({"orders": 2}, 1.25, None),
            ),
            pytest.raises(RuntimeError, match="promotion failed"),
        ):
            adapter.load_data(Mock(), conn, tmp_path)

        conn.rollback.assert_called_once()
        cursor.close.assert_called_once()

    def test_load_data_rejects_invalid_schema_identifier(self, pg_mooncake_stubs, tmp_path):
        adapter = PgMooncakeAdapter(schema='public";drop')
        conn = Mock()

        with (
            patch.object(
                postgresql_module.PostgreSQLAdapter,
                "load_data",
                return_value=({"orders": 2}, 1.25, None),
            ),
            pytest.raises(ValueError, match="Invalid pg_mooncake schema identifier"),
        ):
            adapter.load_data(Mock(), conn, tmp_path)

        conn.cursor.assert_not_called()


class TestPgMooncakeValidationCatalog:
    """Tests for pg_mooncake catalog reads used by validation."""

    def test_get_existing_tables_commits_catalog_transaction(self, pg_mooncake_stubs):
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = [("Customer",), ("__bb_moon_src_customer",)]
        conn.cursor.return_value = cursor

        tables = adapter._get_existing_tables(conn)

        assert tables == ["customer", "__bb_moon_src_customer"]
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        cursor.close.assert_called_once()

    def test_get_existing_tables_rolls_back_catalog_failure(self, pg_mooncake_stubs):
        adapter = PgMooncakeAdapter()
        conn = Mock()
        cursor = Mock()
        cursor.execute.side_effect = RuntimeError("catalog failed")
        conn.cursor.return_value = cursor

        tables = adapter._get_existing_tables(conn)

        assert tables == []
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        cursor.close.assert_called_once()


class TestPgMooncakeStorageConfig:
    """Tests for storage mode configuration."""

    def test_s3_mode_requires_bucket(self, pg_mooncake_stubs, monkeypatch):
        """S3 mode should require bucket configuration."""
        monkeypatch.delenv("MOONCAKE_S3_BUCKET", raising=False)

        with pytest.raises(ValueError, match="S3 storage mode requires bucket configuration"):
            PgMooncakeAdapter(storage_mode="s3")

    def test_s3_mode_accepts_config_bucket(self, pg_mooncake_stubs, monkeypatch):
        """S3 mode should accept bucket from config."""
        monkeypatch.delenv("MOONCAKE_S3_BUCKET", raising=False)

        adapter = PgMooncakeAdapter(
            storage_mode="s3",
            mooncake_bucket="s3://my-bucket/mooncake-data",
        )

        assert adapter.storage_mode == "s3"
        assert adapter.mooncake_bucket == "s3://my-bucket/mooncake-data"

    def test_s3_mode_accepts_env_bucket(self, pg_mooncake_stubs, monkeypatch):
        """S3 mode should accept bucket from environment variable."""
        monkeypatch.setenv("MOONCAKE_S3_BUCKET", "s3://env-bucket/data")

        adapter = PgMooncakeAdapter(storage_mode="s3")

        assert adapter.storage_mode == "s3"
        assert adapter.mooncake_bucket == "s3://env-bucket/data"

    def test_invalid_storage_mode_raises(self, pg_mooncake_stubs):
        """Invalid storage mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid pg_mooncake storage mode"):
            PgMooncakeAdapter(storage_mode="gcs")

    def test_create_connection_sets_bucket(self, pg_mooncake_stubs, monkeypatch):
        """create_connection should set mooncake.default_bucket in S3 mode."""
        monkeypatch.delenv("MOONCAKE_S3_BUCKET", raising=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("0.5.0",),  # extension exists
            (1,),
        ]

        pg_mooncake_stubs.connect.return_value = mock_conn

        adapter = PgMooncakeAdapter(
            storage_mode="s3",
            mooncake_bucket="s3://test-bucket/data",
        )

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        bucket_set = any("default_bucket" in call for call in calls)
        assert bucket_set

    def test_create_connection_bucket_set_uses_sql_literal(self, pg_mooncake_stubs, monkeypatch):
        """SET mooncake.default_bucket should use psycopg.sql.Literal, not f-string."""
        monkeypatch.delenv("MOONCAKE_S3_BUCKET", raising=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("0.5.0",),
            (1,),
        ]

        pg_mooncake_stubs.connect.return_value = mock_conn

        adapter = PgMooncakeAdapter(
            storage_mode="s3",
            mooncake_bucket="s3://test-bucket/data",
        )

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        # Verify execute was called with a psycopg.sql.Composed object (not an f-string)
        from psycopg import sql as psycopg_sql

        set_calls = [
            call
            for call in mock_cursor.execute.call_args_list
            if isinstance(call[0][0], (psycopg_sql.Composed, psycopg_sql.SQL))
        ]
        assert len(set_calls) >= 1, "Expected at least one psycopg.sql.Composed execute call for bucket SET"


class TestPgMooncakeRegistration:
    """Tests for pg_mooncake platform registration."""

    def test_pg_mooncake_in_platform_registry(self, pg_mooncake_stubs):
        """pg_mooncake should be registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry, auto_register_platforms

        auto_register_platforms()

        assert "pg-mooncake" in PlatformRegistry._adapters
        assert PlatformRegistry._adapters["pg-mooncake"] == PgMooncakeAdapter

    def test_pg_mooncake_metadata(self, pg_mooncake_stubs):
        """pg_mooncake should have correct metadata in registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        metadata = PlatformRegistry._build_platform_metadata()

        assert "pg-mooncake" in metadata
        assert metadata["pg-mooncake"]["display_name"] == "pg_mooncake"
        assert metadata["pg-mooncake"]["category"] == "olap"
        assert "columnstore" in metadata["pg-mooncake"]["supports"]


class TestPgMooncakeConfigBuilder:
    """Tests for pg_mooncake configuration builder function."""

    def test_config_builder_basic(self, pg_mooncake_stubs):
        """Config builder should produce correct configuration."""
        from benchbox.platforms.pg_mooncake import _build_pg_mooncake_config

        options = {
            "host": "localhost",
            "port": 5432,
            "storage_mode": "local",
        }
        overrides = {"scale_factor": 1.0}

        config = _build_pg_mooncake_config("pg-mooncake", options, overrides, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.storage_mode == "local"
        assert config.scale_factor == 1.0

    def test_config_builder_defaults(self, pg_mooncake_stubs):
        """Config builder should apply defaults for missing options."""
        from benchbox.platforms.pg_mooncake import _build_pg_mooncake_config

        config = _build_pg_mooncake_config("pg-mooncake", {}, {}, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.username == "postgres"
        assert config.admin_database == "postgres"
        assert config.sslmode == "prefer"
        assert config.work_mem == "256MB"
        assert config.maintenance_work_mem == "512MB"
        assert config.effective_cache_size == "1GB"
        assert config.max_parallel_workers_per_gather == 2
        assert config.storage_mode == "local"
        assert config.mooncake_bucket is None
        assert config.options["schema"] == "public"


class TestPgMooncakeMigrationPhase:
    """Tests for run_migration_phase() heap-to-columnstore migration."""

    def _make_mock_conn(self, table_names: list[str], storage_before: int = 8192, storage_after: int = 4096):
        """Build a mock psycopg connection that satisfies run_migration_phase queries."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Responses: heap-table discovery, then (before, after) per table
        fetchall_response = [(t,) for t in table_names]
        fetchone_responses = []
        for _ in table_names:
            fetchone_responses.append((storage_before,))  # before
            fetchone_responses.append((storage_after,))  # after

        mock_cursor.fetchall.return_value = fetchall_response
        mock_cursor.fetchone.side_effect = fetchone_responses
        return mock_conn, mock_cursor

    def test_returns_none_when_no_tables(self, pg_mooncake_stubs):
        """run_migration_phase should return None when table_names is empty."""
        adapter = PgMooncakeAdapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        result = adapter.run_migration_phase(mock_conn, table_names=[])

        assert result is None

    def test_returns_none_when_auto_discovery_finds_nothing(self, pg_mooncake_stubs):
        """run_migration_phase should return None when schema has no heap tables."""
        adapter = PgMooncakeAdapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        result = adapter.run_migration_phase(mock_conn, table_names=None)

        assert result is None

    def test_migrates_provided_tables(self, pg_mooncake_stubs):
        """run_migration_phase should ALTER TABLE for each provided table."""
        from benchbox.core.results.models import MigrationPhase

        adapter = PgMooncakeAdapter()
        mock_conn, mock_cursor = self._make_mock_conn(["lineitem", "orders"])

        result = adapter.run_migration_phase(mock_conn, table_names=["lineitem", "orders"])

        assert isinstance(result, MigrationPhase)
        assert result.tables_migrated == 2
        assert result.tables_failed == 0
        assert result.status == "completed"
        assert "lineitem" in result.per_table_stats
        assert "orders" in result.per_table_stats

    def test_storage_delta_computed_correctly(self, pg_mooncake_stubs):
        """Migration phase should record correct storage before/after/delta."""
        adapter = PgMooncakeAdapter()
        mock_conn, mock_cursor = self._make_mock_conn(["lineitem"], storage_before=8192, storage_after=4096)

        result = adapter.run_migration_phase(mock_conn, table_names=["lineitem"])

        assert result.storage_before_bytes == 8192
        assert result.storage_after_bytes == 4096
        assert result.storage_delta_bytes == -4096
        tbl = result.per_table_stats["lineitem"]
        assert tbl.storage_before_bytes == 8192
        assert tbl.storage_after_bytes == 4096
        assert tbl.storage_delta_bytes == -4096

    def test_failed_table_recorded_as_partial(self, pg_mooncake_stubs):
        """When one table fails, status should be 'partial' not 'completed'."""
        from benchbox.core.results.models import MigrationPhase

        adapter = PgMooncakeAdapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # lineitem succeeds, orders raises
        mock_cursor.fetchone.side_effect = [
            (8192,),  # lineitem before
            (4096,),  # lineitem after
            (8192,),  # orders before - fetched before the ALTER fails
        ]

        call_count = [0]

        def execute_side_effect(sql, *args):
            if "SET ACCESS METHOD" in str(sql) and "orders" in str(sql):
                raise Exception("columnstore not available")
            call_count[0] += 1

        mock_cursor.execute.side_effect = execute_side_effect

        result = adapter.run_migration_phase(mock_conn, table_names=["lineitem", "orders"])

        assert isinstance(result, MigrationPhase)
        assert result.tables_migrated == 1
        assert result.tables_failed == 1
        assert result.status == "partial"
        assert result.per_table_stats["orders"].status == "failed"
        assert result.per_table_stats["orders"].error_message is not None

    def test_all_failed_status_is_failed(self, pg_mooncake_stubs):
        """When all tables fail, status should be 'failed'."""
        adapter = PgMooncakeAdapter()
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        # Storage size query succeeds; ALTER TABLE fails
        mock_cursor.fetchone.return_value = (8192,)

        def execute_side_effect(sql, *args):
            if "SET ACCESS METHOD" in str(sql):
                raise Exception("columnar error")

        mock_cursor.execute.side_effect = execute_side_effect

        result = adapter.run_migration_phase(mock_conn, table_names=["lineitem"])

        assert result.status == "failed"
        assert result.tables_migrated == 0
        assert result.tables_failed == 1
