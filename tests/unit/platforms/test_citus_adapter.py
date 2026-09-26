"""Tests for Citus platform adapter.

Tests the CitusAdapter for citus extension support and opt-in table
distribution.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.citus as citus_module
import benchbox.platforms.postgresql as postgresql_module
from benchbox.platforms.citus import CITUS_EXTENSION, CitusAdapter
from benchbox.platforms.postgresql import POSTGRES_DIALECT, PostgreSQLAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def citus_stubs(monkeypatch):
    """Patch psycopg objects so tests don't require the real driver.

    Must patch both citus and postgresql modules since CitusAdapter
    inherits from PostgreSQLAdapter which checks for psycopg in its __init__.
    """
    mock_psycopg = Mock()
    mock_psycopg.__version__ = "3.1.0"

    # Patch both modules - parent checks in postgresql module
    monkeypatch.setattr(citus_module, "psycopg", mock_psycopg)
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)

    return mock_psycopg


class TestCitusAdapter:
    """Unit tests for Citus adapter wiring and SQL handling."""

    def test_initialization_defaults(self, citus_stubs):
        """Adapter should initialize with Citus defaults when stubs are present."""
        adapter = CitusAdapter()

        assert adapter.platform_name == "citus"
        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.host == "localhost"
        assert adapter.port == 5432
        assert adapter.database == "benchbox"
        assert adapter.username == "postgres"
        assert adapter.schema == "public"
        assert adapter.distribution_column is None

    def test_initialization_with_distribution_column(self, citus_stubs):
        """Adapter should accept a distribution column."""
        adapter = CitusAdapter(distribution_column="l_orderkey")

        assert adapter.distribution_column == "l_orderkey"

    def test_dialect_is_postgres(self, citus_stubs):
        """Citus should use PostgreSQL dialect (compatible)."""
        adapter = CitusAdapter()

        assert adapter.get_target_dialect() == POSTGRES_DIALECT
        assert adapter.get_target_dialect() == "postgres"

    def test_from_config_basic(self, citus_stubs):
        """from_config should create adapter with correct settings."""
        config = {
            "host": "citus.local",
            "port": 5433,
            "database": "test_analytics",
            "distribution_column": "l_orderkey",
        }

        adapter = CitusAdapter.from_config(config)

        assert adapter.host == "citus.local"
        assert adapter.port == 5433
        assert adapter.database == "test_analytics"
        assert adapter.distribution_column == "l_orderkey"

    def test_create_connection_verifies_extension(self, citus_stubs):
        """create_connection should verify citus is installed."""
        adapter = CitusAdapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("12.1",)
        mock_cursor.closed = False
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(PostgreSQLAdapter, "create_connection", return_value=mock_conn):
            result = adapter.create_connection()

        assert result is mock_conn
        executed = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert any(CITUS_EXTENSION in sql for sql in executed)

    def test_create_connection_raises_when_extension_unavailable(self, citus_stubs):
        """create_connection should raise when citus cannot be installed."""
        adapter = CitusAdapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.closed = False
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(PostgreSQLAdapter, "create_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="citus extension is not available"):
                adapter.create_connection()

    def test_create_schema_distributes_tables_when_configured(self, citus_stubs):
        """create_schema should distribute tables on the configured column."""
        adapter = CitusAdapter(distribution_column="l_orderkey")

        benchmark = Mock()
        benchmark._get_active_tables.return_value = ["lineitem", "orders"]

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.closed = False
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(PostgreSQLAdapter, "create_schema", return_value=1.0) as mock_super_schema:
            elapsed = adapter.create_schema(benchmark, mock_conn)

        assert elapsed == 1.0
        mock_super_schema.assert_called_once_with(benchmark, mock_conn)
        distributed = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert any("create_distributed_table" in sql and "lineitem" in sql for sql in distributed)
        assert any("create_distributed_table" in sql and "orders" in sql for sql in distributed)

    def test_create_schema_skips_distribution_by_default(self, citus_stubs):
        """Without a distribution column no distribution SQL is issued."""
        adapter = CitusAdapter()

        mock_conn = Mock()

        with (
            patch.object(PostgreSQLAdapter, "create_schema", return_value=1.0),
            patch.object(CitusAdapter, "_distribute_benchmark_tables") as mock_distribute,
        ):
            adapter.create_schema(Mock(), mock_conn)

        mock_distribute.assert_not_called()

    def test_distribution_column_must_be_a_plain_identifier(self, citus_stubs):
        """Reject injection-shaped distribution columns before executing SQL."""
        adapter = CitusAdapter(distribution_column="x'); DROP TABLE t; --")

        with pytest.raises(ValueError, match="plain SQL identifier"):
            adapter._distribute_benchmark_tables(Mock(), Mock())

    def test_tables_missing_column_stay_local(self, citus_stubs):
        """Tables that fail distribution warn instead of failing the run."""
        adapter = CitusAdapter(distribution_column="l_orderkey")

        benchmark = Mock()
        benchmark._get_active_tables.return_value = ["nation"]

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.closed = False
        mock_cursor.execute.side_effect = RuntimeError("column does not exist")
        mock_conn.cursor.return_value = mock_cursor

        adapter._distribute_benchmark_tables(benchmark, mock_conn)

        mock_conn.rollback.assert_called()
        mock_conn.commit.assert_called_once_with()

    def test_platform_info_reports_version_and_column(self, citus_stubs):
        """get_platform_info should include the citus version and column."""
        adapter = CitusAdapter(distribution_column="l_orderkey")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("12.1",)
        mock_conn.cursor.return_value = mock_cursor

        info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_type"] == "citus"
        assert info["citus_version"] == "12.1"
        assert info["configuration"]["distribution_column"] == "l_orderkey"

    def test_no_extension_conflicts_declared(self):
        """Citus bundles no shared native libs: no conflicts_with entries."""
        from benchbox.core.platform_registry import PlatformRegistry

        assert PlatformRegistry.get_platform_conflicts("citus") == []
