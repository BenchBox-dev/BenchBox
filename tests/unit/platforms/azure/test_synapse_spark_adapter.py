"""Tests for Azure Synapse Spark platform adapter.

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


class TestSynapseSparkAdapterInitialization:
    """Test SynapseSparkAdapter initialization."""

    def test_missing_workspace_name_raises_error(self):
        """Test error when workspace_name is not provided."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import SynapseSparkAdapter

            with pytest.raises(ConfigurationError, match="workspace_name"):
                SynapseSparkAdapter(
                    spark_pool_name="sparkpool1",
                    storage_account="mystorageaccount",
                    storage_container="benchbox",
                )

    def test_missing_spark_pool_raises_error(self):
        """Test error when spark_pool_name is not provided."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import SynapseSparkAdapter

            with pytest.raises(ConfigurationError, match="spark_pool_name"):
                SynapseSparkAdapter(
                    workspace_name="my-synapse-workspace",
                    storage_account="mystorageaccount",
                    storage_container="benchbox",
                )

    def test_missing_storage_account_raises_error(self):
        """Test error when storage_account is not provided."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import SynapseSparkAdapter

            with pytest.raises(ConfigurationError, match="storage_account"):
                SynapseSparkAdapter(
                    workspace_name="my-synapse-workspace",
                    spark_pool_name="sparkpool1",
                    storage_container="benchbox",
                )

    def test_missing_storage_container_raises_error(self):
        """Test error when storage_container is not provided."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
        ):
            from benchbox.platforms.azure import SynapseSparkAdapter

            with pytest.raises(ConfigurationError, match="storage_container"):
                SynapseSparkAdapter(
                    workspace_name="my-synapse-workspace",
                    spark_pool_name="sparkpool1",
                    storage_account="mystorageaccount",
                )

    def test_valid_configuration(self):
        """Test valid configuration with all required parameters."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="my-synapse-workspace",
                spark_pool_name="sparkpool1",
                storage_account="mystorageaccount",
                storage_container="benchbox",
                tenant_id="tenant-123",
            )

            assert adapter.workspace_name == "my-synapse-workspace"
            assert adapter.spark_pool_name == "sparkpool1"
            assert adapter.storage_account == "mystorageaccount"
            assert adapter.storage_container == "benchbox"
            assert adapter.tenant_id == "tenant-123"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="my-synapse-workspace",
                spark_pool_name="sparkpool1",
                storage_account="mystorageaccount",
                storage_container="benchbox",
            )

            assert adapter.timeout_minutes == 60
            assert adapter.storage_path == "benchbox"
            assert adapter.tenant_id is None

    def test_derived_livy_endpoint(self):
        """Test Livy endpoint is derived from workspace and pool names."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="my-workspace",
                spark_pool_name="my-pool",
                storage_account="mystorageaccount",
                storage_container="benchbox",
            )

            assert "my-workspace" in adapter.livy_endpoint
            assert "my-pool" in adapter.livy_endpoint
            assert "dev.azuresynapse.net" in adapter.livy_endpoint

    def test_adls_uri_format(self):
        """Test ADLS Gen2 URI is correctly formatted."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="my-workspace",
                spark_pool_name="my-pool",
                storage_account="mystorageaccount",
                storage_container="mycontainer",
                storage_path="data/benchbox",
            )

            assert adapter.adls_uri == "abfss://mycontainer@mystorageaccount.dfs.core.windows.net/data/benchbox"


class TestSynapseSparkAdapterPlatformInfo:
    """Test platform info methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct metadata."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="test-workspace",
                spark_pool_name="test-pool",
                storage_account="teststorage",
                storage_container="testcontainer",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "synapse-spark"
            assert info["display_name"] == "Azure Synapse Analytics Spark"
            assert info["vendor"] == "Microsoft"
            assert info["type"] == "managed_spark"
            assert info["workspace_name"] == "test-workspace"
            assert info["spark_pool"] == "test-pool"
            assert info["storage_account"] == "teststorage"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True
            assert info["storage"] == "ADLS Gen2"

    def test_get_dialect(self):
        """Test get_target_dialect returns spark."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="test-workspace",
                spark_pool_name="test-pool",
                storage_account="teststorage",
                storage_container="testcontainer",
            )

            assert adapter.get_target_dialect() == "spark"


class TestSynapseSparkAdapterConnection:
    """Test connection and authentication."""

    def test_create_connection_success(self):
        """Test successful Spark pool connection."""
        import requests as real_requests

        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock credential
            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            with patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests:
                mock_requests.exceptions = real_requests.exceptions

                # Setup mock response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "sparkVersion": "3.3",
                    "nodeSize": "Medium",
                    "nodeCount": 5,
                }
                mock_requests.get.return_value = mock_response

                from benchbox.platforms.azure import SynapseSparkAdapter

                adapter = SynapseSparkAdapter(
                    workspace_name="test-workspace",
                    spark_pool_name="test-pool",
                    storage_account="teststorage",
                    storage_container="testcontainer",
                )

                result = adapter.create_connection()

                assert result["status"] == "connected"
                assert result["workspace_name"] == "test-workspace"
                assert result["spark_pool"] == "test-pool"
                assert result["spark_version"] == "3.3"

    def test_create_connection_auth_failure(self):
        """Test authentication failure handling."""
        import requests as real_requests

        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            with patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests:
                mock_requests.exceptions = real_requests.exceptions

                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_requests.get.return_value = mock_response

                from benchbox.platforms.azure import SynapseSparkAdapter

                adapter = SynapseSparkAdapter(
                    workspace_name="test-workspace",
                    spark_pool_name="test-pool",
                    storage_account="teststorage",
                    storage_container="testcontainer",
                )

                with pytest.raises(ConfigurationError, match="Authentication failed"):
                    adapter.create_connection()

    def test_create_connection_pool_not_found(self):
        """Test Spark pool not found handling."""
        import requests as real_requests

        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential") as mock_cred_class,
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            mock_credential = MagicMock()
            mock_token = MagicMock()
            mock_token.token = "test-token"
            mock_token.expires_on = 9999999999
            mock_credential.get_token.return_value = mock_token
            mock_cred_class.return_value = mock_credential

            with patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests:
                mock_requests.exceptions = real_requests.exceptions

                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_requests.get.return_value = mock_response

                from benchbox.platforms.azure import SynapseSparkAdapter

                adapter = SynapseSparkAdapter(
                    workspace_name="test-workspace",
                    spark_pool_name="nonexistent-pool",
                    storage_account="teststorage",
                    storage_container="testcontainer",
                )

                with pytest.raises(ConfigurationError, match="not found"):
                    adapter.create_connection()


class TestSynapseSparkAdapterTuning:
    """Test benchmark tuning configuration."""

    def test_configure_for_tpch(self):
        """Test TPC-H benchmark configuration."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.synapse_spark_adapter.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            mock_config = MagicMock()
            mock_config.to_dict.return_value = {"spark.sql.adaptive.enabled": "true"}
            mock_optimizer.for_tpch.return_value = mock_config

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="test-workspace",
                spark_pool_name="test-pool",
                storage_account="teststorage",
                storage_container="testcontainer",
            )

            adapter.configure_for_benchmark("tpch", scale_factor=10.0)

            assert adapter._benchmark_type == "tpch"
            assert adapter._scale_factor == 10.0
            mock_optimizer.for_tpch.assert_called_once()

    def test_configure_for_tpcds(self):
        """Test TPC-DS benchmark configuration."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.synapse_spark_adapter.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            mock_config = MagicMock()
            mock_config.to_dict.return_value = {}
            mock_optimizer.for_tpcds.return_value = mock_config

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="test-workspace",
                spark_pool_name="test-pool",
                storage_account="teststorage",
                storage_container="testcontainer",
            )

            adapter.configure_for_benchmark("tpcds", scale_factor=100.0)

            assert adapter._benchmark_type == "tpcds"
            assert adapter._scale_factor == 100.0
            mock_optimizer.for_tpcds.assert_called_once()


class TestSynapseSparkAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test CLI arguments are added correctly."""
        from argparse import ArgumentParser

        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
        ):
            from benchbox.platforms.azure import SynapseSparkAdapter

            parser = ArgumentParser()
            SynapseSparkAdapter.add_cli_arguments(parser)

            args = parser.parse_args(
                [
                    "--workspace-name",
                    "test-workspace",
                    "--spark-pool",
                    "test-pool",
                    "--storage-account",
                    "teststorage",
                    "--storage-container",
                    "testcontainer",
                    "--storage-path",
                    "data/benchbox",
                    "--tenant-id",
                    "test-tenant",
                    "--timeout",
                    "120",
                ]
            )

            assert args.workspace_name == "test-workspace"
            assert args.spark_pool_name == "test-pool"
            assert args.storage_account == "teststorage"
            assert args.storage_container == "testcontainer"
            assert args.storage_path == "data/benchbox"
            assert args.tenant_id == "test-tenant"
            assert args.timeout_minutes == 120

    def test_from_config(self):
        """Test adapter creation from config dictionary."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.azure import SynapseSparkAdapter

            config = {
                "workspace_name": "config-workspace",
                "spark_pool_name": "config-pool",
                "storage_account": "configstorage",
                "storage_container": "configcontainer",
                "storage_path": "config/path",
                "tenant_id": "config-tenant",
                "timeout_minutes": 90,
            }

            adapter = SynapseSparkAdapter.from_config(config)

            assert adapter.workspace_name == "config-workspace"
            assert adapter.spark_pool_name == "config-pool"
            assert adapter.storage_account == "configstorage"
            assert adapter.storage_container == "configcontainer"
            assert adapter.storage_path == "config/path"
            assert adapter.tenant_id == "config-tenant"
            assert adapter.timeout_minutes == 90


class TestSynapseSparkAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_registered_in_registry(self):
        """Test that synapse-spark is registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()

        assert "synapse-spark" in all_metadata
        metadata = all_metadata["synapse-spark"]

        assert metadata["display_name"] == "Azure Synapse Analytics Spark"
        assert metadata["category"] == "cloud"
        assert "azure-identity" in str(metadata.get("libraries", []))

    def test_platform_capabilities(self):
        """Test that synapse-spark capabilities are correctly defined."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        metadata = all_metadata["synapse-spark"]

        capabilities = metadata.get("capabilities", {})
        assert capabilities.get("supports_sql") is True
        assert capabilities.get("supports_dataframe") is True


class TestSynapseLivyStateConstants:
    """Test Livy session state constants."""

    def test_synapse_livy_session_states(self):
        """Test SynapseLivySessionState constants are defined."""
        from benchbox.platforms.azure.synapse_spark_adapter import SynapseLivySessionState

        assert SynapseLivySessionState.NOT_STARTED == "not_started"
        assert SynapseLivySessionState.STARTING == "starting"
        assert SynapseLivySessionState.IDLE == "idle"
        assert SynapseLivySessionState.BUSY == "busy"
        assert SynapseLivySessionState.ERROR == "error"
        assert SynapseLivySessionState.DEAD == "dead"

    def test_table_format_default_parquet(self):
        """Test table_format defaults to parquet."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="ws",
                spark_pool_name="pool",
                storage_account="sa",
                storage_container="c",
            )
            assert adapter.table_format == "parquet"

    def test_table_format_delta(self):
        """Test table_format can be set to delta."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="ws",
                spark_pool_name="pool",
                storage_account="sa",
                storage_container="c",
                table_format="delta",
            )
            assert adapter.table_format == "delta"

    def test_table_format_from_config(self):
        """Test table_format is passed through from_config."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter.from_config(
                {
                    "workspace_name": "ws",
                    "spark_pool_name": "pool",
                    "storage_account": "sa",
                    "storage_container": "c",
                    "table_format": "iceberg",
                }
            )
            assert adapter.table_format == "iceberg"

    def test_session_config_delta_extensions(self):
        """Test Delta Lake extensions are added to session config."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": 1}
            mock_requests.post.return_value = mock_response

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="ws",
                spark_pool_name="pool",
                storage_account="sa",
                storage_container="c",
                table_format="delta",
            )
            adapter._wait_for_session_state = MagicMock()
            adapter._create_session()

            call_kwargs = mock_requests.post.call_args
            session_conf = call_kwargs.kwargs["json"]["conf"]
            assert "io.delta.sql.DeltaSparkSessionExtension" in session_conf["spark.sql.extensions"]
            assert "DeltaCatalog" in session_conf["spark.sql.catalog.spark_catalog"]

    def test_session_config_iceberg_extensions(self):
        """Test Iceberg extensions are added to session config."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": 1}
            mock_requests.post.return_value = mock_response

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="ws",
                spark_pool_name="pool",
                storage_account="sa",
                storage_container="c",
                table_format="iceberg",
            )
            adapter._wait_for_session_state = MagicMock()
            adapter._create_session()

            call_kwargs = mock_requests.post.call_args
            session_conf = call_kwargs.kwargs["json"]["conf"]
            assert "IcebergSparkSessionExtensions" in session_conf["spark.sql.extensions"]
            assert "SparkSessionCatalog" in session_conf["spark.sql.catalog.spark_catalog"]
            assert session_conf["spark.sql.catalog.spark_catalog.type"] == "hive"

    def test_session_config_parquet_no_extensions(self):
        """Test parquet (default) does not add format extensions."""
        with (
            patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
            patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
            patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.azure.synapse_spark_adapter.requests") as mock_requests,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": 1}
            mock_requests.post.return_value = mock_response

            from benchbox.platforms.azure import SynapseSparkAdapter

            adapter = SynapseSparkAdapter(
                workspace_name="ws",
                spark_pool_name="pool",
                storage_account="sa",
                storage_container="c",
            )
            adapter._wait_for_session_state = MagicMock()
            adapter._create_session()

            call_kwargs = mock_requests.post.call_args
            session_conf = call_kwargs.kwargs["json"]["conf"]
            assert "spark.sql.extensions" not in session_conf

    def test_synapse_livy_statement_states(self):
        """Test LivyStatementState constants are defined (shared across Azure Spark adapters)."""
        from benchbox.platforms.azure.spark_execution_utils import LivyStatementState

        assert LivyStatementState.WAITING == "waiting"
        assert LivyStatementState.RUNNING == "running"
        assert LivyStatementState.AVAILABLE == "available"
        assert LivyStatementState.ERROR == "error"
        assert LivyStatementState.CANCELLED == "cancelled"
