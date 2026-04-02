"""Unit tests for MotherDuck platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
from unittest.mock import Mock, patch

import pytest

from benchbox.core.config_inheritance import resolve_dialect_for_query_translation
from benchbox.core.platform_registry import PlatformRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestMotherDuckRegistration:
    """Test MotherDuck platform is properly registered."""

    def test_platform_registered_in_registry(self):
        """MotherDuck should be registered in PlatformRegistry."""
        caps = PlatformRegistry.get_platform_capabilities("motherduck")
        assert caps is not None
        assert caps.supports_sql is True

    def test_inherits_from_duckdb(self):
        """MotherDuck should inherit from DuckDB."""
        caps = PlatformRegistry.get_platform_capabilities("motherduck")
        assert caps.inherits_from == "duckdb"
        assert caps.platform_family == "duckdb"

    def test_dialect_resolves_to_duckdb(self):
        """Query translation should use DuckDB dialect."""
        dialect = resolve_dialect_for_query_translation("motherduck")
        assert dialect == "duckdb"

    def test_deployment_mode_is_managed(self):
        """MotherDuck should have managed deployment mode."""
        caps = PlatformRegistry.get_platform_capabilities("motherduck")
        assert "managed" in caps.deployment_modes
        assert caps.default_deployment == "managed"

    def test_requires_credentials(self):
        """MotherDuck managed mode should require credentials."""
        caps = PlatformRegistry.get_platform_capabilities("motherduck")
        managed_cap = caps.deployment_modes["managed"]
        assert managed_cap.requires_credentials is True
        assert managed_cap.requires_network is True
        assert "token" in managed_cap.auth_methods


class TestMotherDuckAdapter:
    """Test MotherDuck adapter initialization and configuration."""

    def test_requires_token(self):
        """Adapter should raise error when no token provided."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        # Clear environment variable if set
        with patch.dict(os.environ, {}, clear=True):
            # Remove MOTHERDUCK_TOKEN if present
            os.environ.pop("MOTHERDUCK_TOKEN", None)

            with pytest.raises(ValueError) as exc_info:
                MotherDuckAdapter()

            assert "authentication token" in str(exc_info.value).lower()
            assert "MOTHERDUCK_TOKEN" in str(exc_info.value)

    def test_token_from_config(self):
        """Adapter should accept token from config."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MOTHERDUCK_TOKEN", None)

            # Token provided via config - should not raise
            # Note: We can't actually test connection without a real token
            adapter = MotherDuckAdapter(token="test-token-12345")
            assert adapter.token == "test-token-12345"

    def test_token_from_environment(self):
        """Adapter should accept token from environment variable."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        with patch.dict(os.environ, {"MOTHERDUCK_TOKEN": "env-token-67890"}):
            adapter = MotherDuckAdapter()
            assert adapter.token == "env-token-67890"

    def test_default_database(self):
        """Default database should be 'benchbox'."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token")
        assert adapter.database == "benchbox"

    def test_custom_database(self):
        """Custom database should be configurable."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token", database="my_custom_db")
        assert adapter.database == "my_custom_db"

    def test_platform_name(self):
        """Platform name should be 'MotherDuck'."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token")
        assert adapter.platform_name == "MotherDuck"

    def test_dialect_is_duckdb(self):
        """Dialect should be 'duckdb'."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token")
        assert adapter._dialect == "duckdb"

    def test_get_target_dialect(self):
        """get_target_dialect should return duckdb via inheritance."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token")
        # get_target_dialect uses config inheritance
        dialect = adapter.get_target_dialect()
        assert dialect == "duckdb"

    def test_get_platform_metadata(self):
        """Platform metadata should include MotherDuck-specific fields."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token", database="test_db")
        metadata = adapter.get_platform_metadata()

        assert metadata["platform_type"] == "motherduck"
        assert metadata["platform_name"] == "MotherDuck"
        assert metadata["dialect"] == "duckdb"
        assert metadata["database"] == "test_db"
        assert metadata["inherits_from"] == "duckdb"

    def test_create_external_tables_uses_duckdb_view_registration(self, tmp_path):
        """MotherDuck should reuse DuckDB external-view registration logic."""
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="test-token")
        parquet_path = tmp_path / "customer.parquet"
        parquet_path.touch()

        benchmark = Mock()
        benchmark.tables = {"customer": parquet_path}
        benchmark.get_table_loading_order.return_value = ["customer"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (3,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, per_table_timings = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert adapter.supports_external_tables is True
        assert table_stats == {"customer": 3}
        assert per_table_timings is None
        assert any("CREATE VIEW customer AS SELECT * FROM read_parquet(" in sql for sql in executed_sql)


class TestMotherDuckAdapterFactory:
    """Test adapter factory integration with MotherDuck."""

    def test_factory_can_resolve_motherduck(self):
        """Adapter factory should resolve motherduck platform."""
        from benchbox.platforms.adapter_factory import _normalize_platform_name, get_available_deployments

        name, df_mode, deployment = _normalize_platform_name("motherduck")
        assert name == "motherduck"
        assert df_mode is False
        assert deployment is None

        deployments = get_available_deployments("motherduck")
        assert "managed" in deployments

    def test_case_insensitive_name(self):
        """Platform name should be case-insensitive."""
        from benchbox.platforms.adapter_factory import _normalize_platform_name

        name1, _, _ = _normalize_platform_name("MotherDuck")
        name2, _, _ = _normalize_platform_name("MOTHERDUCK")
        name3, _, _ = _normalize_platform_name("motherduck")

        assert name1 == name2 == name3 == "motherduck"


class TestMotherDuckFromConfig:
    """Test from_config classmethod."""

    def test_from_config_sets_database(self):
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter.from_config(
            {
                "motherduck_database": "test_db",
                "motherduck_token": "tok123",
            }
        )
        assert adapter.database == "test_db"
        assert adapter.token == "tok123"

    def test_from_config_with_memory_limit(self):
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter.from_config(
            {
                "motherduck_token": "tok123",
                "memory_limit": "8GB",
            }
        )
        assert adapter.memory_limit == "8GB"


class TestMotherDuckCreateConnection:
    """Test create_connection with a mocked duckdb.connect."""

    def test_create_connection_uses_md_scheme(self):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="mytoken", database="mydb")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)

        with patch("benchbox.platforms.motherduck.duckdb") as mock_duckdb:
            mock_duckdb.connect.return_value = mock_conn
            conn = adapter.create_connection()

        call_args = mock_duckdb.connect.call_args[0][0]
        assert "md:mydb" in call_args
        assert "mytoken" in call_args
        assert conn is mock_conn
        assert adapter.connection is mock_conn

    def test_create_connection_cached(self):
        """Second call should return the same connection without reconnecting."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="mytoken")
        mock_conn = MagicMock()
        adapter.connection = mock_conn

        with patch("benchbox.platforms.motherduck.duckdb") as mock_duckdb:
            conn = adapter.create_connection()

        mock_duckdb.connect.assert_not_called()
        assert conn is mock_conn


class TestMotherDuckAddCliArguments:
    """Test add_cli_arguments registers expected flags."""

    def test_motherduck_database_arg_added(self):
        import argparse

        from benchbox.platforms.motherduck import MotherDuckAdapter

        parser = argparse.ArgumentParser()
        MotherDuckAdapter.add_cli_arguments(parser)
        args = parser.parse_args(["--motherduck-database", "mydb"])
        assert args.motherduck_database == "mydb"

    def test_motherduck_token_arg_added(self):
        import argparse

        from benchbox.platforms.motherduck import MotherDuckAdapter

        parser = argparse.ArgumentParser()
        MotherDuckAdapter.add_cli_arguments(parser)
        args = parser.parse_args(["--motherduck-token", "tok"])
        assert args.motherduck_token == "tok"


class TestMotherDuckGetPlatformInfo:
    """Test get_platform_info returns expected keys."""

    def test_get_platform_info_has_name_and_version(self):
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token="tok")
        info = adapter.get_platform_info()
        assert info["platform_name"] == "MotherDuck"
        assert "platform_version" in info
