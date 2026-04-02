"""Tests for Microsoft Fabric Spark platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestFabricSparkAdapterInitialization:
    """Test FabricSparkAdapter initialization."""

    def test_missing_workspace_id_raises_error(self):
        """Test error when workspace_id is not provided."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            with pytest.raises(ConfigurationError, match="workspace_id"):
                FabricSparkAdapter(
                    lakehouse_id="lakehouse-123",
                )

    def test_missing_lakehouse_id_raises_error(self):
        """Test error when lakehouse_id is not provided."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            with pytest.raises(ConfigurationError, match="lakehouse_id"):
                FabricSparkAdapter(
                    workspace_id="workspace-abc",
                )

    def test_valid_configuration(self):
        """Test valid configuration with workspace and lakehouse IDs."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc-123",
                lakehouse_id="lakehouse-xyz-456",
                tenant_id="tenant-789",
                spark_pool_name="my-pool",
            )

            assert adapter.workspace_id == "workspace-abc-123"
            assert adapter.lakehouse_id == "lakehouse-xyz-456"
            assert adapter.tenant_id == "tenant-789"
            assert adapter.spark_pool_name == "my-pool"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
            )

            assert adapter.timeout_minutes == 60
            assert adapter.tenant_id is None
            assert adapter.spark_pool_name is None

    def test_derived_livy_endpoint(self):
        """Test Livy endpoint is derived from workspace and lakehouse IDs."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="my-workspace",
                lakehouse_id="my-lakehouse",
            )

            assert "my-workspace" in adapter.livy_endpoint
            assert "my-lakehouse" in adapter.livy_endpoint
            assert "livyApi" in adapter.livy_endpoint

    def test_custom_livy_endpoint(self):
        """Test custom Livy endpoint overrides derived endpoint."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            custom_endpoint = "https://custom-livy.example.com/sessions"
            adapter = FabricSparkAdapter(
                workspace_id="my-workspace",
                lakehouse_id="my-lakehouse",
                livy_endpoint=custom_endpoint,
            )

            assert adapter.livy_endpoint == custom_endpoint


class TestFabricSparkAdapterPlatformInfo:
    """Test platform info methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct metadata."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
                spark_pool_name="my-pool",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "fabric-spark"
            assert info["display_name"] == "Microsoft Fabric Spark"
            assert info["vendor"] == "Microsoft"
            assert info["type"] == "managed_spark"
            assert info["workspace_id"] == "workspace-abc"
            assert info["lakehouse_id"] == "lakehouse-xyz"
            assert info["spark_pool"] == "my-pool"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True
            assert info["storage"] == "OneLake"

    def test_get_dialect(self):
        """Test get_target_dialect returns spark."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
            )

            assert adapter.get_target_dialect() == "spark"


class TestFabricSparkAdapterConnection:
    """Test connection and authentication."""

    def test_create_connection_success(self):
        """Test successful workspace connection."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests,
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock credential
            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999  # Far future
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            # Setup mock response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "displayName": "My Workspace",
            }
            mock_requests.get.return_value = mock_response

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
            )

            result = adapter.create_connection()

            assert result["status"] == "connected"
            assert result["workspace_id"] == "workspace-abc"
            assert result["workspace_name"] == "My Workspace"
            assert result["lakehouse_id"] == "lakehouse-xyz"

    def test_create_connection_auth_failure(self):
        """Test authentication failure handling."""
        import requests as real_requests

        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock credential
            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            # Mock requests.get but keep real exceptions
            with patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests:
                # Keep real exceptions accessible
                mock_requests.exceptions = real_requests.exceptions

                # Setup mock 401 response
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_requests.get.return_value = mock_response

                from benchbox.platforms.azure import FabricSparkAdapter

                adapter = FabricSparkAdapter(
                    workspace_id="workspace-abc",
                    lakehouse_id="lakehouse-xyz",
                )

                with pytest.raises(ConfigurationError, match="Authentication failed"):
                    adapter.create_connection()

    def test_create_connection_workspace_not_found(self):
        """Test workspace not found handling."""
        import requests as real_requests

        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock credential
            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            # Mock requests.get but keep real exceptions
            with patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests:
                # Keep real exceptions accessible
                mock_requests.exceptions = real_requests.exceptions

                # Setup mock 404 response
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_requests.get.return_value = mock_response

                from benchbox.platforms.azure import FabricSparkAdapter

                adapter = FabricSparkAdapter(
                    workspace_id="nonexistent-workspace",
                    lakehouse_id="lakehouse-xyz",
                )

                with pytest.raises(ConfigurationError, match="not found"):
                    adapter.create_connection()


class TestFabricSparkAdapterDataLoading:
    """Test data loading functionality."""

    def test_load_data_skips_when_exists(self):
        """Test that load_data skips upload when tables already exist."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests,
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            # Setup mock staging that says tables exist
            mock_staging_instance = MagicMock()
            mock_staging_instance.tables_exist.return_value = True
            mock_staging.from_uri.return_value = mock_staging_instance

            # Mock token and Livy API for execute_statement calls
            mock_cred = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_cred.get_token.return_value = mock_token

            # Mock statement execution
            mock_session_response = MagicMock()
            mock_session_response.status_code = 201
            mock_session_response.json.return_value = {"id": 1, "state": "idle"}

            mock_statement_response = MagicMock()
            mock_statement_response.status_code = 201
            mock_statement_response.json.return_value = {"id": 1, "state": "available", "output": {"status": "ok"}}

            mock_requests.post.return_value = mock_session_response
            mock_requests.get.return_value = mock_statement_response

            from benchbox.platforms.azure import FabricSparkAdapter

            with patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", return_value=mock_cred):
                adapter = FabricSparkAdapter(
                    workspace_id="workspace-abc",
                    lakehouse_id="lakehouse-xyz",
                )

                import tempfile

                mock_benchmark = MagicMock()
                mock_benchmark.tables = {"lineitem": None, "orders": None}

                with tempfile.TemporaryDirectory() as tmpdir:
                    from pathlib import Path

                    adapter.load_data(mock_benchmark, None, Path(tmpdir))

                    # Should not call upload_tables since tables exist
                    mock_staging_instance.upload_tables.assert_not_called()


class TestFabricSparkAdapterTuning:
    """Test benchmark tuning configuration."""

    def test_configure_for_tpch(self):
        """Test TPC-H benchmark configuration."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.fabric_spark_adapter.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Mock optimizer (class method pattern)
            mock_config = MagicMock()
            mock_config.to_dict.return_value = {"spark.sql.adaptive.enabled": "true"}
            mock_optimizer.for_tpch.return_value = mock_config

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
            )

            adapter.configure_for_benchmark(None, "tpch", scale_factor=10.0)

            assert adapter._benchmark_type == "tpch"
            assert adapter._scale_factor == 10.0
            mock_optimizer.for_tpch.assert_called_once()

    def test_configure_for_tpcds(self):
        """Test TPC-DS benchmark configuration."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.fabric_spark_adapter.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Mock optimizer (class method pattern)
            mock_config = MagicMock()
            mock_config.to_dict.return_value = {}
            mock_optimizer.for_tpcds.return_value = mock_config

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="workspace-abc",
                lakehouse_id="lakehouse-xyz",
            )

            adapter.configure_for_benchmark(None, "tpcds", scale_factor=100.0)

            assert adapter._benchmark_type == "tpcds"
            assert adapter._scale_factor == 100.0
            mock_optimizer.for_tpcds.assert_called_once()


class TestFabricSparkAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test CLI arguments are added correctly."""
        from argparse import ArgumentParser

        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            parser = ArgumentParser()
            FabricSparkAdapter.add_cli_arguments(parser)

            # Parse with test arguments
            args = parser.parse_args(
                [
                    "--workspace-id",
                    "test-workspace",
                    "--lakehouse-id",
                    "test-lakehouse",
                    "--tenant-id",
                    "test-tenant",
                    "--spark-pool",
                    "test-pool",
                    "--timeout",
                    "120",
                ]
            )

            assert args.workspace_id == "test-workspace"
            assert args.lakehouse_id == "test-lakehouse"
            assert args.tenant_id == "test-tenant"
            assert args.spark_pool_name == "test-pool"
            assert args.timeout_minutes == 120

    def test_from_config(self):
        """Test adapter creation from config dictionary."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import FabricSparkAdapter

            config = {
                "workspace_id": "config-workspace",
                "lakehouse_id": "config-lakehouse",
                "tenant_id": "config-tenant",
                "spark_pool_name": "config-pool",
                "timeout_minutes": 90,
            }

            adapter = FabricSparkAdapter.from_config(config)

            assert adapter.workspace_id == "config-workspace"
            assert adapter.lakehouse_id == "config-lakehouse"
            assert adapter.tenant_id == "config-tenant"
            assert adapter.spark_pool_name == "config-pool"
            assert adapter.timeout_minutes == 90


class TestFabricSparkAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_registered_in_registry(self):
        """Test that fabric-spark is registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        # Get all platform metadata
        all_metadata = PlatformRegistry.get_all_platform_metadata()

        assert "fabric-spark" in all_metadata
        metadata = all_metadata["fabric-spark"]

        assert metadata["display_name"] == "Microsoft Fabric Spark"
        assert metadata["category"] == "cloud"
        assert "azure-identity" in str(metadata.get("libraries", []))

    def test_platform_capabilities(self):
        """Test that fabric-spark capabilities are correctly defined."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        metadata = all_metadata["fabric-spark"]

        capabilities = metadata.get("capabilities", {})
        assert capabilities.get("supports_sql") is True
        assert capabilities.get("supports_dataframe") is True


class TestFabricSparkLivySessionConstants:
    """Test Livy session state constants."""

    def test_livy_session_states(self):
        """Test LivySessionState constants are defined."""
        from benchbox.platforms.azure.fabric_spark_adapter import LivySessionState

        assert LivySessionState.NOT_STARTED == "not_started"
        assert LivySessionState.STARTING == "starting"
        assert LivySessionState.IDLE == "idle"
        assert LivySessionState.BUSY == "busy"
        assert LivySessionState.ERROR == "error"
        assert LivySessionState.DEAD == "dead"

    def test_table_format_default_delta(self):
        """Test table_format defaults to delta on Fabric."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="ws-123",
                lakehouse_id="lh-456",
            )
            assert adapter.table_format == "delta"

    def test_table_format_iceberg(self):
        """Test table_format can be set to iceberg."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="ws-123",
                lakehouse_id="lh-456",
                table_format="iceberg",
            )
            assert adapter.table_format == "iceberg"

    def test_table_format_from_config(self):
        """Test table_format is passed through from_config."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter.from_config(
                {
                    "workspace_id": "ws-123",
                    "lakehouse_id": "lh-456",
                    "table_format": "parquet",
                }
            )
            assert adapter.table_format == "parquet"

    def test_session_config_iceberg_extensions(self):
        """Test Iceberg extensions are added to session config."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": 1}
            mock_requests.post.return_value = mock_response

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="ws-123",
                lakehouse_id="lh-456",
                table_format="iceberg",
            )
            adapter._wait_for_session_state = MagicMock()
            adapter._create_session()

            call_kwargs = mock_requests.post.call_args
            session_conf = call_kwargs.kwargs["json"]["conf"]
            assert "IcebergSparkSessionExtensions" in session_conf["spark.sql.extensions"]
            assert "SparkSessionCatalog" in session_conf["spark.sql.catalog.spark_catalog"]

    def test_session_config_delta_no_extensions(self):
        """Test delta (default on Fabric) does not add extra extensions since Delta is native."""
        with (
            patch("benchbox.platforms.azure.fabric_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.fabric_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.fabric_spark_adapter.requests") as mock_requests,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": 1}
            mock_requests.post.return_value = mock_response

            from benchbox.platforms.azure import FabricSparkAdapter

            adapter = FabricSparkAdapter(
                workspace_id="ws-123",
                lakehouse_id="lh-456",
            )
            adapter._wait_for_session_state = MagicMock()
            adapter._create_session()

            call_kwargs = mock_requests.post.call_args
            session_conf = call_kwargs.kwargs["json"]["conf"]
            assert "spark.sql.extensions" not in session_conf

    def test_livy_statement_states(self):
        """Test LivyStatementState constants are defined."""
        from benchbox.platforms.azure.spark_execution_utils import LivyStatementState

        assert LivyStatementState.WAITING == "waiting"
        assert LivyStatementState.RUNNING == "running"
        assert LivyStatementState.AVAILABLE == "available"
        assert LivyStatementState.ERROR == "error"
        assert LivyStatementState.CANCELLED == "cancelled"
