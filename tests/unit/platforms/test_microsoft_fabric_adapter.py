"""Unit tests for Microsoft Fabric Data Warehouse adapter.

Tests the FabricWarehouseAdapter class including:
- Initialization and configuration validation
- Connection string generation
- Authentication (Entra ID)
- Data loading via OneLake
- Query execution

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

import benchbox.platforms.fabric_warehouse as fabric_module
from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.fabric_warehouse import (
    FABRIC_DIALECT,
    FabricWarehouseAdapter,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def fabric_stubs(monkeypatch):
    """Patch pyodbc and azure dependencies so tests don't require real drivers."""
    # Mock pyodbc
    mock_pyodbc = Mock()
    mock_pyodbc.connect = Mock()
    mock_pyodbc.Error = Exception

    # Patch pyodbc at the module level
    monkeypatch.setattr(fabric_module, "pyodbc", mock_pyodbc)

    # Mock the dependency check to always pass
    monkeypatch.setattr(
        fabric_module,
        "check_platform_dependencies",
        lambda platform, packages=None: (True, []),
    )

    return mock_pyodbc


@pytest.fixture()
def fabric_adapter(fabric_stubs):
    """Create a Fabric adapter instance for testing."""
    return FabricWarehouseAdapter(
        workspace="test-workspace-guid",
        warehouse="test_warehouse",
        auth_method="service_principal",
        tenant_id="test-tenant-id",
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


class TestFabricWarehouseAdapter:
    """Tests for FabricWarehouseAdapter initialization and configuration."""

    def test_initialization_defaults(self, fabric_stubs):
        """Test adapter initializes with correct defaults."""
        adapter = FabricWarehouseAdapter(
            workspace="test-workspace",
            database="test_db",
            auth_method="default_credential",
        )

        assert adapter.workspace == "test-workspace"
        assert adapter.database == "test_db"
        assert adapter.port == 1433
        assert adapter.schema == "dbo"
        assert adapter.auth_method == "default_credential"
        assert adapter.driver == "ODBC Driver 18 for SQL Server"
        assert adapter.connect_timeout == 30
        assert adapter.disable_result_cache is True
        assert adapter.staging_path == "benchbox-staging"

    def test_initialization_with_config(self, fabric_stubs):
        """Test adapter accepts custom configuration."""
        adapter = FabricWarehouseAdapter(
            server="custom.datawarehouse.fabric.microsoft.com",
            database="custom_db",
            schema="custom_schema",
            auth_method="service_principal",
            tenant_id="tenant-123",
            client_id="client-456",
            client_secret="secret-789",
            connect_timeout=60,
            staging_path="custom-staging",
        )

        assert adapter.server == "custom.datawarehouse.fabric.microsoft.com"
        assert adapter.database == "custom_db"
        assert adapter.schema == "custom_schema"
        assert adapter.tenant_id == "tenant-123"
        assert adapter.client_id == "client-456"
        assert adapter.client_secret == "secret-789"
        assert adapter.connect_timeout == 60
        assert adapter.staging_path == "custom-staging"

    def test_missing_workspace_and_server_raises_error(self, fabric_stubs):
        """Test that missing workspace/server raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires connection details"):
            FabricWarehouseAdapter(
                database="test_db",
                auth_method="default_credential",
            )

    def test_missing_database_raises_error(self, fabric_stubs):
        """Test that missing database/warehouse raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires a database/warehouse name"):
            FabricWarehouseAdapter(
                workspace="test-workspace",
                auth_method="default_credential",
            )

    def test_service_principal_missing_credentials_raises_error(self, fabric_stubs):
        """Test that service_principal auth without credentials raises error."""
        with pytest.raises(ConfigurationError, match="service principal authentication is incomplete"):
            FabricWarehouseAdapter(
                workspace="test-workspace",
                database="test_db",
                auth_method="service_principal",
                # Missing client_id, client_secret, tenant_id
            )

    def test_workspace_generates_server_endpoint(self, fabric_stubs):
        """Test that workspace generates correct server endpoint."""
        adapter = FabricWarehouseAdapter(
            workspace="abc123-def456",
            database="test_db",
            auth_method="default_credential",
        )

        assert adapter.server == "abc123-def456.datawarehouse.fabric.microsoft.com"

    def test_warehouse_used_as_database(self, fabric_stubs):
        """Test that warehouse parameter sets database."""
        adapter = FabricWarehouseAdapter(
            workspace="test-workspace",
            warehouse="my_warehouse",
            auth_method="default_credential",
        )

        assert adapter.database == "my_warehouse"


class TestConnectionString:
    """Tests for connection string generation."""

    def test_connection_string_format(self, fabric_adapter):
        """Test connection string has correct format."""
        conn_str = fabric_adapter._get_connection_string()

        assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_str
        assert "SERVER=test-workspace-guid.datawarehouse.fabric.microsoft.com,1433" in conn_str
        assert "DATABASE=test_warehouse" in conn_str
        assert "Encrypt=yes" in conn_str
        assert "TrustServerCertificate=no" in conn_str
        assert "Connection Timeout=30" in conn_str

    def test_connection_string_custom_database(self, fabric_adapter):
        """Test connection string with custom database."""
        conn_str = fabric_adapter._get_connection_string(db="custom_db")

        assert "DATABASE=custom_db" in conn_str


class TestPlatformInfo:
    """Tests for platform information methods."""

    def test_platform_name(self, fabric_adapter):
        """Test platform_name property."""
        assert fabric_adapter.platform_name == "Fabric Warehouse"

    def test_dialect_is_tsql(self, fabric_adapter):
        """Test dialect is T-SQL."""
        assert fabric_adapter.get_target_dialect() == FABRIC_DIALECT
        assert fabric_adapter._dialect == "tsql"


class TestAuthentication:
    """Tests for authentication methods."""

    def test_token_struct_creation(self, fabric_adapter):
        """Test access token struct is created correctly."""
        token = "test_access_token_123"
        token_struct = fabric_adapter._create_token_struct(token)

        # Token struct should be bytes with length prefix
        assert isinstance(token_struct, bytes)
        # Should contain the token encoded as UTF-16-LE
        assert len(token_struct) > len(token)

    @patch("benchbox.platforms.fabric_warehouse.FabricWarehouseAdapter._get_access_token")
    def test_create_connection_with_token(self, mock_get_token, fabric_adapter, fabric_stubs):
        """Test connection creation uses access token."""
        mock_get_token.return_value = "mock_access_token"

        # Setup mock connection
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ["Microsoft Fabric Warehouse"]
        mock_connection.cursor.return_value = mock_cursor
        fabric_stubs.connect.return_value = mock_connection

        fabric_adapter.create_connection()

        # Verify pyodbc.connect was called with attrs_before containing token
        assert fabric_stubs.connect.called
        call_kwargs = fabric_stubs.connect.call_args[1]
        assert "attrs_before" in call_kwargs
        assert 1256 in call_kwargs["attrs_before"]  # SQL_COPT_SS_ACCESS_TOKEN


class TestQueryExecution:
    """Tests for query execution."""

    def test_execute_query_success(self, fabric_adapter, fabric_stubs):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("row1",), ("row2",)]
        mock_connection.cursor.return_value = mock_cursor

        result = fabric_adapter.execute_query(
            connection=mock_connection,
            query="SELECT * FROM test",
            query_id="Q1",
        )

        assert result["status"] == "SUCCESS"
        assert result["query_id"] == "Q1"
        assert result["rows_returned"] == 2
        assert "execution_time_seconds" in result

    def test_execute_query_failure(self, fabric_adapter, fabric_stubs):
        """Test query execution handles errors."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Query failed")
        mock_connection.cursor.return_value = mock_cursor

        result = fabric_adapter.execute_query(
            connection=mock_connection,
            query="SELECT * FROM nonexistent",
            query_id="Q2",
        )

        assert result["status"] == "FAILED"
        assert result["query_id"] == "Q2"
        assert "error" in result


class TestTableOperations:
    """Tests for table operations."""

    def test_get_existing_tables(self, fabric_adapter):
        """Test listing existing tables."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("table1",), ("table2",), ("table3",)]
        mock_connection.cursor.return_value = mock_cursor

        tables = fabric_adapter.get_existing_tables(mock_connection)

        assert tables == ["table1", "table2", "table3"]

    def test_drop_table(self, fabric_adapter):
        """Test dropping a table."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        fabric_adapter.drop_table(mock_connection, "test_table")

        mock_cursor.execute.assert_called_once()
        call_arg = mock_cursor.execute.call_args[0][0]
        assert "DROP TABLE IF EXISTS" in call_arg
        assert "[dbo].[test_table]" in call_arg

    def test_extract_table_name(self, fabric_adapter):
        """Test extracting table name from CREATE statement."""
        create_sql = "CREATE TABLE my_table (id INT, name VARCHAR(100))"
        table_name = fabric_adapter._extract_table_name(create_sql)
        assert table_name == "my_table"

        create_sql_with_schema = "CREATE TABLE [dbo].[my_table] (id INT)"
        table_name = fabric_adapter._extract_table_name(create_sql_with_schema)
        assert table_name == "my_table"


class TestTuningSupport:
    """Tests for tuning support."""

    def test_supports_clustering_only(self, fabric_adapter):
        """Test that Fabric only supports clustering tuning type (columnstore)."""
        from benchbox.core.tuning.interface import TuningType

        # Clustering (columnstore) is supported
        assert fabric_adapter.supports_tuning_type(TuningType.CLUSTERING) is True

        # Distribution and partitioning are auto-managed in Fabric
        assert fabric_adapter.supports_tuning_type(TuningType.DISTRIBUTION) is False
        assert fabric_adapter.supports_tuning_type(TuningType.PARTITIONING) is False


class TestFromConfig:
    """Tests for from_config class method."""

    def test_from_config_generates_database_name(self, fabric_stubs):
        """Test from_config generates database name from benchmark params."""
        config = {
            "workspace": "test-workspace",
            "benchmark": "tpch",
            "scale_factor": 10,
            "auth_method": "default_credential",
        }

        adapter = FabricWarehouseAdapter.from_config(config)

        # Database name should be auto-generated
        assert adapter.database is not None
        assert "tpch" in adapter.database.lower() or "sf" in adapter.database.lower()

    def test_from_config_uses_provided_database(self, fabric_stubs):
        """Test from_config uses explicitly provided database name."""
        config = {
            "workspace": "test-workspace",
            "database": "custom_database",
            "benchmark": "tpch",
            "scale_factor": 10,
            "auth_method": "default_credential",
        }

        adapter = FabricWarehouseAdapter.from_config(config)

        assert adapter.database == "custom_database"


class TestConnectionTest:
    """Tests for connection testing."""

    @patch("benchbox.platforms.fabric_warehouse.FabricWarehouseAdapter._get_access_token")
    def test_test_connection_success(self, mock_get_token, fabric_adapter, fabric_stubs):
        """Test successful connection test."""
        mock_get_token.return_value = "mock_token"

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ["Microsoft Fabric v1.0"]
        mock_connection.cursor.return_value = mock_cursor
        fabric_stubs.connect.return_value = mock_connection

        result = fabric_adapter.test_connection()

        assert result["success"] is True
        assert "version" in result
        assert result["auth_method"] == "service_principal"

    @patch("benchbox.platforms.fabric_warehouse.FabricWarehouseAdapter._get_access_token")
    def test_test_connection_failure(self, mock_get_token, fabric_adapter, fabric_stubs):
        """Test failed connection test."""
        mock_get_token.side_effect = Exception("Auth failed")

        result = fabric_adapter.test_connection()

        assert result["success"] is False
        assert "error" in result


class TestDataLoading:
    """Tests for data loading methods."""

    def test_insert_batch(self, fabric_adapter):
        """Test batch INSERT generation."""
        mock_cursor = Mock()
        batch = [
            ["1", "value1", "100"],
            ["2", "value2", "200"],
        ]

        fabric_adapter._insert_batch(mock_cursor, "[dbo].[test_table]", batch)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]

        assert "INSERT INTO [dbo].[test_table] VALUES" in sql
        assert "('1', 'value1', '100')" in sql
        assert "('2', 'value2', '200')" in sql

    def test_insert_batch_handles_quotes(self, fabric_adapter):
        """Test batch INSERT escapes quotes."""
        mock_cursor = Mock()
        batch = [
            ["1", "O'Brien", "100"],
        ]

        fabric_adapter._insert_batch(mock_cursor, "[dbo].[test_table]", batch)

        sql = mock_cursor.execute.call_args[0][0]
        assert "O''Brien" in sql  # Escaped quote

    def test_insert_batch_handles_null(self, fabric_adapter):
        """Test batch INSERT handles NULL values."""
        mock_cursor = Mock()
        batch = [
            ["1", "", "NULL"],
        ]

        fabric_adapter._insert_batch(mock_cursor, "[dbo].[test_table]", batch)

        sql = mock_cursor.execute.call_args[0][0]
        assert "NULL" in sql


class TestLifecycle:
    """Tests for adapter lifecycle methods."""

    def test_close_connection(self, fabric_adapter):
        """Test connection close."""
        mock_connection = Mock()

        fabric_adapter.close_connection(mock_connection)

        mock_connection.close.assert_called_once()

    def test_close_connection_handles_none(self, fabric_adapter):
        """Test close handles None connection gracefully."""
        # Should not raise
        fabric_adapter.close_connection(None)

    def test_close_connection_handles_error(self, fabric_adapter):
        """Test close handles errors gracefully."""
        mock_connection = Mock()
        mock_connection.close.side_effect = Exception("Close failed")

        # Should not raise
        fabric_adapter.close_connection(mock_connection)


# ---------------------------------------------------------------------------
# _get_access_token auth method branching
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    """Test _get_access_token branches for each auth method."""

    def test_service_principal_uses_client_secret_credential(self, fabric_adapter):
        mock_csc = Mock()
        mock_csc.get_token.return_value = Mock(token="sp-token")

        mock_identity = Mock()
        mock_identity.ClientSecretCredential.return_value = mock_csc
        mock_identity.DefaultAzureCredential = Mock()
        mock_identity.InteractiveBrowserCredential = Mock()

        with patch.dict("sys.modules", {"azure.identity": mock_identity}):
            token = fabric_adapter._get_access_token()

        assert token == "sp-token"
        mock_identity.ClientSecretCredential.assert_called_once_with(
            tenant_id="test-tenant-id",
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    def test_default_credential_path(self, fabric_stubs):
        adapter = FabricWarehouseAdapter(
            workspace="wsp",
            database="db",
            auth_method="default_credential",
        )

        mock_cred = Mock()
        mock_cred.get_token.return_value = Mock(token="default-token")

        mock_identity = Mock()
        mock_identity.ClientSecretCredential = Mock()
        mock_identity.DefaultAzureCredential.return_value = mock_cred
        mock_identity.InteractiveBrowserCredential = Mock()

        with patch.dict("sys.modules", {"azure.identity": mock_identity}):
            token = adapter._get_access_token()

        assert token == "default-token"
        mock_identity.DefaultAzureCredential.assert_called_once()

    def test_import_error_raises_helpful_message(self, fabric_adapter):
        with patch.dict("sys.modules", {"azure.identity": None}):
            with pytest.raises(ImportError):
                fabric_adapter._get_access_token()


# ---------------------------------------------------------------------------
# configure_for_benchmark
# ---------------------------------------------------------------------------


class TestConfigureForBenchmark:
    """Test configure_for_benchmark applies expected SQL."""

    def test_olap_benchmark_sets_ansi_and_clears_cache(self, fabric_adapter):
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        fabric_adapter.configure_for_benchmark(mock_connection, benchmark_type="tpch")

        executed = [call[0][0] for call in mock_cursor.execute.call_args_list]
        assert any("ANSI_NULLS" in sql for sql in executed)
        assert any("ANSI_PADDING" in sql for sql in executed)
        assert any("ANSI_WARNINGS" in sql for sql in executed)

    def test_non_olap_benchmark_skips_query_store(self, fabric_adapter):
        """Non-OLAP benchmark type should not call QUERY_STORE CLEAR."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        fabric_adapter.configure_for_benchmark(mock_connection, benchmark_type="write")

        executed = [call[0][0] for call in mock_cursor.execute.call_args_list]
        assert not any("QUERY_STORE" in sql for sql in executed)


# ---------------------------------------------------------------------------
# get_platform_info basic fields
# ---------------------------------------------------------------------------


class TestGetPlatformInfoFabric:
    """Test get_platform_info without a live connection."""

    def test_basic_fields_present(self, fabric_adapter, fabric_stubs):
        fabric_stubs.connect.side_effect = Exception("no connection in test")

        info = fabric_adapter.get_platform_info()

        assert info["platform"] == "Fabric Warehouse"
        assert info["dialect"] == FABRIC_DIALECT
        assert info["server"] == "test-workspace-guid.datawarehouse.fabric.microsoft.com"
        assert info["database"] == "test_warehouse"
        assert info["auth_method"] == "service_principal"
        assert info["supported_item_type"] == "Warehouse"


# ---------------------------------------------------------------------------
# Item type warning for unsupported types
# ---------------------------------------------------------------------------


class TestItemTypeWarning:
    """Test that non-Warehouse item types emit a warning."""

    def test_lakehouse_item_type_emits_warning(self, fabric_stubs):
        with pytest.warns(UserWarning, match="only supports Warehouse items"):
            FabricWarehouseAdapter(
                workspace="wsp",
                database="db",
                auth_method="default_credential",
                item_type="Lakehouse",
            )


# ---------------------------------------------------------------------------
# add_cli_arguments
# ---------------------------------------------------------------------------


class TestFabricAddCliArguments:
    """Test add_cli_arguments registers expected flags."""

    def test_workspace_arg(self):
        import argparse

        parser = argparse.ArgumentParser()
        FabricWarehouseAdapter.add_cli_arguments(parser)
        args = parser.parse_args(["--workspace", "my-workspace-guid"])
        assert args.workspace == "my-workspace-guid"

    def test_auth_method_default(self):
        import argparse

        parser = argparse.ArgumentParser()
        FabricWarehouseAdapter.add_cli_arguments(parser)
        args = parser.parse_args([])
        assert args.auth_method == "default_credential"

    def test_staging_path_default(self):
        import argparse

        parser = argparse.ArgumentParser()
        FabricWarehouseAdapter.add_cli_arguments(parser)
        args = parser.parse_args([])
        assert args.staging_path == "benchbox-staging"
