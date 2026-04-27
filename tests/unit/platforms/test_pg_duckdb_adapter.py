"""Tests for pg_duckdb platform adapter.

Tests the PgDuckDBAdapter for DuckDB-accelerated PostgreSQL support.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.pg_duckdb as pg_duckdb_module
import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.pg_duckdb import PgDuckDBAdapter
from benchbox.platforms.postgresql import POSTGRES_DIALECT

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def pg_duckdb_stubs(monkeypatch):
    """Patch psycopg objects so tests don't require the real driver.

    Must patch both pg_duckdb and postgresql modules since PgDuckDBAdapter
    inherits from PostgreSQLAdapter which checks for psycopg in its __init__.
    """
    mock_psycopg = Mock()
    mock_psycopg.__version__ = "3.1.0"

    # Patch both modules - parent checks in postgresql module
    monkeypatch.setattr(pg_duckdb_module, "psycopg", mock_psycopg)
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)

    return mock_psycopg


class TestPgDuckDBAdapter:
    """Unit tests for pg_duckdb adapter wiring and SQL handling."""

    def test_initialization_defaults(self, pg_duckdb_stubs):
        """Adapter should initialize with pg_duckdb defaults when stubs are present."""
        adapter = PgDuckDBAdapter()

        assert adapter.platform_name == "pg_duckdb"
        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.host == "localhost"
        assert adapter.port == 5432
        assert adapter.database == "benchbox"
        assert adapter.username == "postgres"
        assert adapter.schema == "public"
        # pg_duckdb-specific defaults
        assert adapter.force_execution is True
        assert adapter.postgres_scan_threads == 0
        assert adapter.deployment_mode == "self-hosted"

    def test_initialization_with_config(self, pg_duckdb_stubs):
        """Adapter should accept custom pg_duckdb configuration."""
        adapter = PgDuckDBAdapter(
            host="pgduckdb.example.com",
            port=5433,
            database="analytics_db",
            username="custom_user",
            password="secret",
            schema="analytics",
            force_execution=False,
            postgres_scan_threads=4,
        )

        assert adapter.host == "pgduckdb.example.com"
        assert adapter.port == 5433
        assert adapter.database == "analytics_db"
        assert adapter.username == "custom_user"
        assert adapter.password == "secret"
        assert adapter.schema == "analytics"
        assert adapter.force_execution is False
        assert adapter.postgres_scan_threads == 4

    def test_dialect_is_postgres(self, pg_duckdb_stubs):
        """pg_duckdb should use PostgreSQL dialect (compatible)."""
        adapter = PgDuckDBAdapter()

        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.get_target_dialect() == "postgres"

    def test_from_config_basic(self, pg_duckdb_stubs):
        """from_config should create adapter with correct settings."""
        config = {
            "host": "pgduckdb.local",
            "port": 5433,
            "database": "test_analytics",
            "force_execution": True,
            "postgres_scan_threads": 8,
        }

        adapter = PgDuckDBAdapter.from_config(config)

        assert adapter.host == "pgduckdb.local"
        assert adapter.port == 5433
        assert adapter.database == "test_analytics"
        assert adapter.force_execution is True
        assert adapter.postgres_scan_threads == 8

    def test_from_config_generates_database_name(self, pg_duckdb_stubs):
        """from_config should generate database name from benchmark config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = PgDuckDBAdapter.from_config(config)

        assert "benchbox" in adapter.database

    def test_from_config_uses_provided_database(self, pg_duckdb_stubs):
        """from_config should prefer explicit database name over generated one."""
        config = {
            "database": "explicit_db",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = PgDuckDBAdapter.from_config(config)

        assert adapter.database == "explicit_db"

    def test_inherits_postgresql_connection_params(self, pg_duckdb_stubs):
        """pg_duckdb adapter should inherit PostgreSQL connection parameter handling."""
        adapter = PgDuckDBAdapter(
            host="pgduckdb.example.com",
            port=5433,
            database="testdb",
            username="testuser",
            password="testpass",
            sslmode="require",
            connect_timeout=15,
        )

        params = adapter._get_connection_params()

        assert params["host"] == "pgduckdb.example.com"
        assert params["port"] == 5433
        assert params["dbname"] == "testdb"
        assert params["user"] == "testuser"
        assert params["password"] == "testpass"
        assert params["sslmode"] == "require"
        assert params["connect_timeout"] == 15

    def test_supports_tuning_type(self, pg_duckdb_stubs):
        """pg_duckdb should support same tuning types as PostgreSQL."""
        adapter = PgDuckDBAdapter()

        from benchbox.core.tuning.interface import TuningType

        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
        assert adapter.supports_tuning_type(TuningType.CLUSTERING) is True
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is True
        assert adapter.supports_tuning_type(TuningType.FOREIGN_KEYS) is True
        # pg_duckdb does not support distribution/sorting
        assert adapter.supports_tuning_type(TuningType.DISTRIBUTION) is False
        assert adapter.supports_tuning_type(TuningType.SORTING) is False

    def test_get_platform_info_basic(self, pg_duckdb_stubs):
        """Platform info should show pg_duckdb details."""
        adapter = PgDuckDBAdapter(
            force_execution=True,
            postgres_scan_threads=4,
        )

        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "pg_duckdb"
        assert info["platform_name"] == "pg_duckdb"
        assert info["configuration"]["force_execution"] is True
        assert info["configuration"]["postgres_scan_threads"] == 4
        assert info["configuration"]["deployment_mode"] == "self-hosted"


class TestPgDuckDBExtensionVerification:
    """Tests for pg_duckdb extension verification in create_connection."""

    def test_create_connection_verifies_extension(self, pg_duckdb_stubs):
        """create_connection should verify pg_duckdb extension is available."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Extension exists
        mock_cursor.fetchone.side_effect = [
            None,  # check_server_database_exists
            None,  # check again in _create_database
            ("1.1.0",),  # extension version check
            (1,),  # verify connection
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        # Should have checked for extension
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        extension_check = any("pg_duckdb" in call.lower() for call in calls)
        assert extension_check

    def test_create_connection_sets_force_execution(self, pg_duckdb_stubs):
        """create_connection should set duckdb.force_execution GUC."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,  # check_server_database_exists
            None,  # check again
            ("1.0.0",),  # extension exists
            (1,),  # verify connection
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter(force_execution=True)

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        force_exec_set = any("force_execution" in call for call in calls)
        assert force_exec_set

    def test_create_connection_sets_thread_count(self, pg_duckdb_stubs):
        """create_connection should set thread count when configured."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("1.0.0",),
            (1,),
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter(postgres_scan_threads=8)

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        threads_set = any("threads_for_postgres_scan" in call for call in calls)
        assert threads_set

    def test_create_connection_raises_when_extension_missing(self, pg_duckdb_stubs):
        """create_connection should raise when pg_duckdb extension is not available."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Extension not found, CREATE EXTENSION fails, still not found
        mock_cursor.fetchone.side_effect = [
            None,  # check_server_database_exists
            None,  # check again
            None,  # extension not found
            None,  # still not found after CREATE
            (1,),  # verify connection
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
            pytest.raises(RuntimeError, match="pg_duckdb extension is not available"),
        ):
            adapter.create_connection()


class TestPgDuckDBMotherDuckMode:
    """Tests for MotherDuck deployment mode."""

    def test_motherduck_mode_requires_token(self, pg_duckdb_stubs, monkeypatch):
        """MotherDuck mode should require MOTHERDUCK_TOKEN."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

        with pytest.raises(ValueError, match="MotherDuck deployment mode requires authentication token"):
            PgDuckDBAdapter(deployment_mode="motherduck")

    def test_motherduck_mode_accepts_config_token(self, pg_duckdb_stubs, monkeypatch):
        """MotherDuck mode should accept token from config."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

        adapter = PgDuckDBAdapter(
            deployment_mode="motherduck",
            motherduck_token="test_token_123",
        )

        assert adapter.deployment_mode == "motherduck"
        assert adapter.motherduck_token == "test_token_123"

    def test_motherduck_mode_accepts_env_token(self, pg_duckdb_stubs, monkeypatch):
        """MotherDuck mode should accept token from environment variable."""
        monkeypatch.setenv("MOTHERDUCK_TOKEN", "env_token_456")

        adapter = PgDuckDBAdapter(deployment_mode="motherduck")

        assert adapter.deployment_mode == "motherduck"
        assert adapter.motherduck_token == "env_token_456"

    def test_invalid_deployment_mode_raises(self, pg_duckdb_stubs):
        """Invalid deployment mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid pg_duckdb deployment mode"):
            PgDuckDBAdapter(deployment_mode="invalid")

    def test_create_connection_sets_motherduck_token(self, pg_duckdb_stubs, monkeypatch):
        """create_connection should set duckdb.motherduck_token in motherduck mode."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("1.0.0",),  # extension exists
            (1,),
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter(
            deployment_mode="motherduck",
            motherduck_token="md_token_789",
        )

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "handle_existing_database"),
        ):
            adapter.create_connection()

        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        token_set = any("motherduck_token" in call for call in calls)
        assert token_set

    def test_create_connection_token_set_uses_sql_literal(self, pg_duckdb_stubs, monkeypatch):
        """SET duckdb.motherduck_token should use psycopg.sql.Literal, not f-string."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,
            None,
            ("1.0.0",),
            (1,),
        ]

        pg_duckdb_stubs.connect.return_value = mock_conn

        adapter = PgDuckDBAdapter(
            deployment_mode="motherduck",
            motherduck_token="md_token_789",
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
        assert len(set_calls) >= 1, "Expected at least one psycopg.sql.Composed execute call for token SET"


class TestPgDuckDBRegistration:
    """Tests for pg_duckdb platform registration."""

    def test_pg_duckdb_in_platform_registry(self, pg_duckdb_stubs):
        """pg_duckdb should be registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry, auto_register_platforms

        auto_register_platforms()

        assert "pg-duckdb" in PlatformRegistry._adapters
        assert PlatformRegistry._adapters["pg-duckdb"] == PgDuckDBAdapter

    def test_pg_duckdb_metadata(self, pg_duckdb_stubs):
        """pg_duckdb should have correct metadata in registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        metadata = PlatformRegistry._build_platform_metadata()

        assert "pg-duckdb" in metadata
        assert metadata["pg-duckdb"]["display_name"] == "pg_duckdb"
        assert metadata["pg-duckdb"]["category"] == "olap"
        assert "olap" in metadata["pg-duckdb"]["supports"]
        assert "analytics" in metadata["pg-duckdb"]["supports"]


class TestPgDuckDBConfigBuilder:
    """Tests for pg_duckdb configuration builder function."""

    def test_config_builder_basic(self, pg_duckdb_stubs):
        """Config builder should produce correct configuration."""
        from benchbox.platforms.pg_duckdb import _build_pg_duckdb_config

        options = {
            "host": "localhost",
            "port": 5432,
            "force_execution": True,
            "postgres_scan_threads": 4,
        }
        overrides = {"scale_factor": 1.0}

        config = _build_pg_duckdb_config("pg-duckdb", options, overrides, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.force_execution is True
        assert config.postgres_scan_threads == 4
        assert config.scale_factor == 1.0

    def test_config_builder_defaults(self, pg_duckdb_stubs):
        """Config builder should apply defaults for missing options."""
        from benchbox.platforms.pg_duckdb import _build_pg_duckdb_config

        config = _build_pg_duckdb_config("pg-duckdb", {}, {}, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.username == "postgres"
        assert config.admin_database == "postgres"
        assert config.sslmode == "prefer"
        assert config.work_mem == "256MB"
        assert config.maintenance_work_mem == "512MB"
        assert config.effective_cache_size == "1GB"
        assert config.max_parallel_workers_per_gather == 2
        assert config.force_execution is True
        assert config.postgres_scan_threads == 0
        assert config.compare_native is False
        assert config.options["schema"] == "public"


class TestPgDuckDBFromConfigPassthrough:
    """Test from_config passes through deployment_mode and motherduck_token."""

    def test_from_config_passes_deployment_mode(self, pg_duckdb_stubs):
        """Test that from_config passes deployment_mode to adapter."""
        from benchbox.platforms.pg_duckdb import PgDuckDBAdapter

        config = {"deployment_mode": "motherduck", "motherduck_token": "test_token_123"}
        adapter = PgDuckDBAdapter.from_config(config)

        assert adapter.deployment_mode == "motherduck"
        assert adapter.motherduck_token == "test_token_123"

    def test_from_config_default_deployment_mode(self, pg_duckdb_stubs):
        """Test that from_config defaults to self-hosted deployment mode."""
        from benchbox.platforms.pg_duckdb import PgDuckDBAdapter

        adapter = PgDuckDBAdapter.from_config({})

        assert adapter.deployment_mode == "self-hosted"


class TestPgDuckDBCreateConnectionReraise:
    """Test that create_connection re-raises on extension configuration failure."""

    def test_create_connection_reraises_on_guc_failure(self, pg_duckdb_stubs):
        """Test that GUC configuration failures are re-raised, not swallowed."""
        from benchbox.platforms.pg_duckdb import PgDuckDBAdapter

        adapter = PgDuckDBAdapter(host="localhost", database="test")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        # Extension check succeeds, but GUC SET fails
        mock_cursor.fetchone.return_value = ("0.1.0",)
        mock_cursor.execute.side_effect = [
            None,  # SELECT extversion
            Exception("GUC not available"),  # SET duckdb.force_execution
        ]

        # Mock the parent create_connection to return our mock connection
        with patch.object(type(adapter).__bases__[0], "create_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="pg_duckdb configuration failed"):
                adapter.create_connection()


class TestPgDuckDBNativeComparison:
    """Tests for run_native_comparison() pg_duckdb vs native DuckDB comparison."""

    def test_returns_none_when_compare_native_false(self, pg_duckdb_stubs):
        """run_native_comparison should return None when compare_native is False."""
        adapter = PgDuckDBAdapter()
        assert adapter.compare_native is False

        result = adapter.run_native_comparison([], {}, scale_factor=1.0)

        assert result is None

    def test_compare_native_flag_from_string_true(self, pg_duckdb_stubs):
        """compare_native should be True when passed as string 'true' via platform-option."""
        adapter = PgDuckDBAdapter.from_config({"compare_native": "true"})

        assert adapter.compare_native is True

    def test_compare_native_flag_from_string_false(self, pg_duckdb_stubs):
        """compare_native should be False when passed as string 'false'."""
        adapter = PgDuckDBAdapter.from_config({"compare_native": "false"})

        assert adapter.compare_native is False

    def test_duckdb_db_path_stored(self, pg_duckdb_stubs):
        """duckdb_db_path should be stored from config."""
        adapter = PgDuckDBAdapter.from_config({"duckdb_db_path": "/tmp/test.duckdb"})

        assert adapter.duckdb_db_path == "/tmp/test.duckdb"

    def test_returns_none_when_no_matching_query_results(self, pg_duckdb_stubs):
        """run_native_comparison should return None when no results match query_sql_map."""
        adapter = PgDuckDBAdapter(compare_native=True)

        # query_results has entries but none match the query_sql_map keys
        query_results = [{"query_id": "Q99", "ms": 100.0, "run_type": "measurement"}]
        query_sql_map = {"Q1": "SELECT 1"}

        # Import duckdb stub to avoid the ImportError path
        mock_duckdb = Mock()
        mock_conn = Mock()
        mock_duckdb.connect.return_value = mock_conn

        with patch.dict("sys.modules", {"duckdb": mock_duckdb}):
            result = adapter.run_native_comparison(query_results, query_sql_map, scale_factor=1.0)

        assert result is None

    def test_config_builder_passes_compare_native(self, pg_duckdb_stubs):
        """Config builder should pass compare_native and duckdb_db_path through."""
        from benchbox.platforms.pg_duckdb import _build_pg_duckdb_config

        config = _build_pg_duckdb_config(
            "pg-duckdb",
            {"compare_native": "true", "duckdb_db_path": "/data/tpch.duckdb"},
            {},
            None,
        )

        assert config.compare_native == "true"
        assert config.duckdb_db_path == "/data/tpch.duckdb"

    def test_native_comparison_with_duckdb(self, pg_duckdb_stubs):
        """run_native_comparison should produce NativeComparison when duckdb is available."""
        from benchbox.core.results.models import NativeComparison

        adapter = PgDuckDBAdapter(compare_native=True)

        query_results = [
            {"query_id": "Q1", "ms": 100.0, "run_type": "measurement"},
            {"query_id": "Q6", "ms": 50.0, "run_type": "measurement"},
        ]
        query_sql_map = {"Q1": "SELECT 1", "Q6": "SELECT 2+2"}

        mock_duckdb = Mock()
        mock_conn = Mock()
        mock_duckdb.connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch.dict("sys.modules", {"duckdb": mock_duckdb}):
            result = adapter.run_native_comparison(query_results, query_sql_map, scale_factor=1.0)

        assert isinstance(result, NativeComparison)
        assert result.total_queries == 2
        assert result.scale_factor == 1.0
        assert len(result.entries) == 2
        entry_ids = {e.query_id for e in result.entries}
        assert entry_ids == {"Q1", "Q6"}

    def test_warmup_rows_excluded_from_comparison(self, pg_duckdb_stubs):
        """Warmup query_results rows should be excluded from the comparison."""
        adapter = PgDuckDBAdapter(compare_native=True)

        query_results = [
            {"query_id": "Q1", "ms": 200.0, "run_type": "warmup"},
            {"query_id": "Q1", "ms": 100.0, "run_type": "measurement"},
        ]
        query_sql_map = {"Q1": "SELECT 1"}

        mock_duckdb = Mock()
        mock_conn = Mock()
        mock_duckdb.connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch.dict("sys.modules", {"duckdb": mock_duckdb}):
            result = adapter.run_native_comparison(query_results, query_sql_map, scale_factor=0.1)

        # Only one entry (warmup excluded); pg_duckdb_ms should be 100.0 not 150.0
        assert result is not None
        assert result.entries[0].pg_duckdb_ms == 100.0

    def test_returns_none_when_duckdb_not_importable(self, pg_duckdb_stubs):
        """run_native_comparison should return None gracefully when duckdb is missing."""
        adapter = PgDuckDBAdapter(compare_native=True)
        query_results = [{"query_id": "Q1", "ms": 100.0, "run_type": "measurement"}]
        query_sql_map = {"Q1": "SELECT 1"}

        with patch.dict("sys.modules", {"duckdb": None}):
            result = adapter.run_native_comparison(query_results, query_sql_map, scale_factor=1.0)

        assert result is None
