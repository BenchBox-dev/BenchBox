"""Tests for CedarDB platform adapter.

Tests the CedarDBAdapter for PostgreSQL-compatible OLAP/OLTP support.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.cedardb import CedarDBAdapter
from benchbox.platforms.postgresql import POSTGRES_DIALECT

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def cedardb_stubs(monkeypatch):
    """Patch psycopg objects so tests don't require the real driver.

    Must patch both cedardb and postgresql modules since CedarDBAdapter
    inherits from PostgreSQLAdapter which checks for psycopg in its __init__.
    """
    mock_psycopg = Mock()
    mock_psycopg.__version__ = "3.1.0"

    # Patch postgresql module - parent checks for psycopg in its __init__
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)

    # Prevent saved local credentials from bleeding into unit tests
    with patch("benchbox.security.credentials.CredentialManager.get_platform_credentials", return_value={}):
        yield mock_psycopg


class TestCedarDBAdapter:
    """Unit tests for CedarDB adapter wiring and properties."""

    def test_initialization_defaults(self, cedardb_stubs):
        """Adapter should initialize with CedarDB defaults."""
        adapter = CedarDBAdapter()

        assert adapter.platform_name == "CedarDB"
        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.host == "localhost"
        assert adapter.port == 5432
        assert adapter.database == "benchbox"
        assert adapter.username == "postgres"
        assert adapter.schema == "public"

    def test_initialization_with_config(self, cedardb_stubs):
        """Adapter should accept custom configuration."""
        adapter = CedarDBAdapter(
            host="cedardb.example.com",
            port=5433,
            database="analytics_db",
            username="cedar_user",
            password="secret",
            schema="analytics",
        )

        assert adapter.host == "cedardb.example.com"
        assert adapter.port == 5433
        assert adapter.database == "analytics_db"
        assert adapter.username == "cedar_user"
        assert adapter.password == "secret"
        assert adapter.schema == "analytics"

    def test_dialect_is_postgres(self, cedardb_stubs):
        """CedarDB should use PostgreSQL dialect (wire-protocol compatible)."""
        adapter = CedarDBAdapter()

        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.get_target_dialect() == "postgres"

    def test_from_config_basic(self, cedardb_stubs):
        """from_config should create adapter with correct settings."""
        config = {
            "host": "cedardb.local",
            "port": 5434,
            "database": "test_analytics",
        }

        adapter = CedarDBAdapter.from_config(config)

        assert adapter.host == "cedardb.local"
        assert adapter.port == 5434
        assert adapter.database == "test_analytics"

    def test_from_config_generates_database_name(self, cedardb_stubs):
        """from_config should generate database name from benchmark config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = CedarDBAdapter.from_config(config)

        assert adapter.database == "benchbox_tpch_sf1"

    def test_from_config_uses_provided_database(self, cedardb_stubs):
        """from_config should prefer explicit database name over generated one."""
        config = {
            "database": "explicit_db",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        adapter = CedarDBAdapter.from_config(config)

        assert adapter.database == "explicit_db"

    def test_inherits_postgresql_connection_params(self, cedardb_stubs):
        """CedarDB adapter should inherit PostgreSQL connection parameter handling."""
        adapter = CedarDBAdapter(
            host="cedardb.example.com",
            port=5434,
            database="testdb",
            username="testuser",
            password="testpass",
            sslmode="require",
            connect_timeout=15,
        )

        params = adapter._get_connection_params()

        assert params["host"] == "cedardb.example.com"
        assert params["port"] == 5434
        assert params["dbname"] == "testdb"
        assert params["user"] == "testuser"
        assert params["password"] == "testpass"
        assert params["sslmode"] == "require"
        assert params["connect_timeout"] == 15

    def test_get_platform_info_basic(self, cedardb_stubs):
        """Platform info should show CedarDB details."""
        adapter = CedarDBAdapter()

        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "cedardb"
        assert info["platform_name"] == "CedarDB"

    def test_get_platform_info_with_connection(self, cedardb_stubs):
        """Platform info should include version string when connection provided."""
        adapter = CedarDBAdapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("CedarDB 1.0 (formerly Umbra)",)

        info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_type"] == "cedardb"
        assert "cedardb_version_string" in info
        assert "CedarDB" in info["cedardb_version_string"]


class TestCedarDBTuningTypes:
    """Tests for CedarDB tuning type support."""

    def test_supports_tuning_type(self, cedardb_stubs):
        """CedarDB should support standard PostgreSQL tuning types (except distribution)."""
        adapter = CedarDBAdapter()

        from benchbox.core.tuning.interface import TuningType

        assert adapter.supports_tuning_type(TuningType.PARTITIONING) is False
        assert adapter.supports_tuning_type(TuningType.SORTING) is False
        assert adapter.supports_tuning_type(TuningType.DISTRIBUTION) is False
        assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False
        assert adapter.supports_tuning_type(TuningType.PRIMARY_KEYS) is True
        assert adapter.supports_tuning_type(TuningType.FOREIGN_KEYS) is True


class TestCedarDBRegistration:
    """Tests for CedarDB platform registration."""

    def test_cedardb_in_platform_registry(self, cedardb_stubs):
        """CedarDB should be registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry, auto_register_platforms

        auto_register_platforms()

        assert "cedardb" in PlatformRegistry._adapters
        assert PlatformRegistry._adapters["cedardb"] == CedarDBAdapter

    def test_cedardb_metadata(self, cedardb_stubs):
        """CedarDB should have correct metadata in registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        metadata = PlatformRegistry._build_platform_metadata()

        assert "cedardb" in metadata
        assert metadata["cedardb"]["display_name"] == "CedarDB"
        assert metadata["cedardb"]["category"] == "olap"


class TestCedarDBConfigBuilder:
    """Tests for CedarDB configuration builder function."""

    def test_config_builder_basic(self, cedardb_stubs):
        """Config builder should produce correct DatabaseConfig."""
        from benchbox.platforms.cedardb import _build_cedardb_config

        options = {"host": "localhost", "port": 5432}
        overrides = {"scale_factor": 1.0}

        config = _build_cedardb_config("cedardb", options, overrides, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.type == "cedardb"

    def test_config_builder_defaults(self, cedardb_stubs):
        """Config builder should apply defaults for missing options."""
        from benchbox.platforms.cedardb import _build_cedardb_config

        config = _build_cedardb_config("cedardb", {}, {}, None)

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.username == "postgres"
        assert config.sslmode == "prefer"

    def test_config_builder_merges_overrides(self, cedardb_stubs):
        """Config builder should apply overrides over options."""
        from benchbox.platforms.cedardb import _build_cedardb_config

        options = {"host": "cedardb.local"}
        overrides = {"database": "benchmark_db", "scale_factor": 10.0}

        config = _build_cedardb_config("cedardb", options, overrides, None)

        assert config.host == "cedardb.local"
        assert config.database == "benchmark_db"
        assert config.scale_factor == 10.0

    def test_config_builder_custom_port(self, cedardb_stubs):
        """Config builder should accept custom port."""
        from benchbox.platforms.cedardb import _build_cedardb_config

        config = _build_cedardb_config("cedardb", {"port": 5434}, {}, None)

        assert config.port == 5434

    def test_config_builder_returns_database_config(self, cedardb_stubs):
        """Config builder should return a DatabaseConfig instance."""
        from benchbox.core.schemas import DatabaseConfig
        from benchbox.platforms.cedardb import _build_cedardb_config

        config = _build_cedardb_config("cedardb", {}, {}, None)

        assert isinstance(config, DatabaseConfig)
        assert config.type == "cedardb"
        assert config.name == "CedarDB"
