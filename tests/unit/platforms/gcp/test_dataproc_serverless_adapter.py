"""Tests for GCP Dataproc Serverless platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDataprocServerlessAdapterInitialization:
    """Test DataprocServerlessAdapter initialization."""

    def test_missing_project_id_raises_error(self):
        """Test error when project_id is not provided."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
        ):
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            with pytest.raises(ConfigurationError, match="project_id"):
                DataprocServerlessAdapter(
                    gcs_staging_dir="gs://my-bucket/benchbox-data",
                )

    def test_missing_gcs_staging_dir_raises_error(self):
        """Test error when gcs_staging_dir is not provided."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
        ):
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            with pytest.raises(ConfigurationError, match="gcs_staging_dir"):
                DataprocServerlessAdapter(
                    project_id="my-project",
                )

    def test_invalid_gcs_path_raises_error(self):
        """Test error when gcs_staging_dir has invalid format."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
        ):
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            with pytest.raises(ConfigurationError, match="Invalid GCS"):
                DataprocServerlessAdapter(
                    project_id="my-project",
                    gcs_staging_dir="/local/path",
                )

    def test_valid_configuration(self):
        """Test valid configuration initializes correctly."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                region="us-west1",
                gcs_staging_dir="gs://my-bucket/benchbox-data",
                database="my_benchmark_db",
            )

            assert adapter.gcs_bucket == "my-bucket"
            assert adapter.gcs_prefix == "benchbox-data"
            assert adapter.project_id == "my-project"
            assert adapter.region == "us-west1"
            assert adapter.database == "my_benchmark_db"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
            )

            assert adapter.region == "us-central1"
            assert adapter.database == "benchbox"
            assert adapter.runtime_version == "2.1"
            assert adapter.timeout_minutes == 60
            assert adapter.service_account is None
            assert adapter.network_uri is None
            assert adapter.subnetwork_uri is None

    def test_optional_network_configuration(self):
        """Test optional network configuration."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
                service_account="my-sa@my-project.iam.gserviceaccount.com",
                network_uri="projects/my-project/global/networks/my-vpc",
                subnetwork_uri="projects/my-project/regions/us-central1/subnetworks/my-subnet",
            )

            assert adapter.service_account == "my-sa@my-project.iam.gserviceaccount.com"
            assert adapter.network_uri == "projects/my-project/global/networks/my-vpc"
            assert adapter.subnetwork_uri == "projects/my-project/regions/us-central1/subnetworks/my-subnet"


class TestDataprocServerlessTableFormat:
    """Test table_format parameter configuration."""

    def test_table_format_default_parquet(self):
        """Test table_format defaults to parquet."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="proj",
                gcs_staging_dir="gs://bucket/data",
            )
            assert adapter.table_format == "parquet"

    def test_table_format_delta(self):
        """Test table_format can be set to delta."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="proj",
                gcs_staging_dir="gs://bucket/data",
                table_format="delta",
            )
            assert adapter.table_format == "delta"

    def test_table_format_from_config(self):
        """Test table_format is passed through from_config."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter.from_config(
                {
                    "project_id": "proj",
                    "gcs_staging_dir": "gs://bucket/data",
                    "table_format": "hudi",
                }
            )
            assert adapter.table_format == "hudi"


class TestDataprocServerlessAdapterPlatformInfo:
    """Test platform info methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct metadata."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                region="europe-west1",
                gcs_staging_dir="gs://my-bucket/data",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "dataproc-serverless"
            assert info["display_name"] == "Google Cloud Dataproc Serverless"
            assert info["vendor"] == "Google Cloud"
            assert info["type"] == "serverless_spark"
            assert info["project_id"] == "my-project"
            assert info["region"] == "europe-west1"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True
            assert info["cluster_management"] is False

    def test_get_dialect(self):
        """Test get_target_dialect returns spark."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
            )

            assert adapter.get_target_dialect() == "spark"


class TestDataprocServerlessAdapterConnection:
    """Test connection functionality."""

    def test_create_connection_success(self):
        """Test successful connection verification."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1") as mock_dataproc,
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock batch client
            mock_batch_client = MagicMock()
            mock_batch_client.list_batches.return_value = []
            mock_dataproc.BatchControllerClient.return_value = mock_batch_client
            mock_dataproc.ListBatchesRequest = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                region="us-central1",
                gcs_staging_dir="gs://my-bucket/data",
            )

            result = adapter.create_connection()

            assert result["status"] == "connected"
            assert result["project_id"] == "my-project"
            assert result["region"] == "us-central1"

    def test_create_connection_failure(self):
        """Test connection failure handling."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1") as mock_dataproc,
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock batch client to raise an error
            mock_batch_client = MagicMock()
            mock_batch_client.list_batches.side_effect = Exception("Permission denied")
            mock_dataproc.BatchControllerClient.return_value = mock_batch_client
            mock_dataproc.ListBatchesRequest = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
            )

            with pytest.raises(ConfigurationError, match="Failed to connect"):
                adapter.create_connection()


class TestDataprocServerlessAdapterDataLoading:
    """Test data loading functionality."""

    def test_load_data_existing_tables(self, tmp_path):
        """Test load_data skips upload when tables exist."""
        # Create actual source directory to pass validation
        source_dir = tmp_path / "test_data"
        source_dir.mkdir()

        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging_instance = MagicMock()
            mock_staging_instance.tables_exist.return_value = True
            mock_staging_instance.get_table_uri.side_effect = lambda t: f"gs://bucket/tables/{t}"
            mock_staging.from_uri.return_value = mock_staging_instance

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            mock_benchmark = SimpleNamespace(tables=["lineitem", "orders"])
            result_dict, _, _ = adapter.load_data(mock_benchmark, None, source_dir)

            assert "lineitem" in result_dict
            assert "orders" in result_dict
            mock_staging_instance.upload_tables.assert_not_called()


class TestDataprocBatchState:
    """Test batch state constants."""

    def test_batch_state_values(self):
        """Test DataprocBatchState constants are correct."""
        from benchbox.platforms.gcp.dataproc_serverless_adapter import DataprocBatchState

        assert DataprocBatchState.PENDING == "PENDING"
        assert DataprocBatchState.RUNNING == "RUNNING"
        assert DataprocBatchState.SUCCEEDED == "SUCCEEDED"
        assert DataprocBatchState.FAILED == "FAILED"
        assert DataprocBatchState.CANCELLED == "CANCELLED"

    def test_terminal_states(self):
        """Test terminal states are correctly defined."""
        from benchbox.platforms.gcp.dataproc_serverless_adapter import DataprocBatchState

        assert DataprocBatchState.SUCCEEDED in DataprocBatchState.TERMINAL_STATES
        assert DataprocBatchState.FAILED in DataprocBatchState.TERMINAL_STATES
        assert DataprocBatchState.CANCELLED in DataprocBatchState.TERMINAL_STATES
        assert DataprocBatchState.RUNNING not in DataprocBatchState.TERMINAL_STATES


class TestDataprocServerlessAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_metadata_exists(self):
        """Test Dataproc Serverless metadata exists in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "dataproc-serverless" in all_metadata

    def test_platform_metadata_content(self):
        """Test Dataproc Serverless metadata content is correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "dataproc-serverless" in all_metadata
        serverless_meta = all_metadata["dataproc-serverless"]

        assert serverless_meta["display_name"] == "Google Cloud Dataproc Serverless"
        assert serverless_meta["category"] == "cloud"
        assert serverless_meta["capabilities"]["supports_sql"] is True
        assert serverless_meta["capabilities"]["supports_dataframe"] is True
        assert "serverless" in serverless_meta["supports"]


class TestDataprocServerlessAdapterTuning:
    """Test tuning interface implementation."""

    def test_apply_platform_optimizations(self):
        """Test apply_platform_optimizations returns empty list."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            result = adapter.apply_platform_optimizations(MagicMock())
            assert result == []

    def test_apply_primary_keys(self):
        """Test apply_primary_keys returns empty list."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            config = MagicMock()
            config.enabled = True
            result = adapter.apply_primary_keys(config)
            assert result == []

    def test_configure_for_benchmark(self):
        """Test configure_for_benchmark sets benchmark type."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
            # SparkConfigOptimizer is now used from the mixin module
            patch("benchbox.platforms.base.cloud_spark.mixins.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_config = MagicMock()
            mock_config.to_dict.return_value = {"spark.sql.shuffle.partitions": "200"}
            mock_optimizer.for_tpch.return_value = mock_config

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            adapter.configure_for_benchmark(None, "tpch")

            assert adapter._benchmark_type == "tpch"
            mock_optimizer.for_tpch.assert_called_once()


class TestDataprocServerlessAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test add_cli_arguments adds expected arguments."""
        from benchbox.platforms.gcp import DataprocServerlessAdapter

        parser = MagicMock()
        parser.add_argument_group.return_value = MagicMock()

        DataprocServerlessAdapter.add_cli_arguments(parser)

        parser.add_argument_group.assert_called_once_with("Dataproc Serverless Options")


class TestDataprocServerlessAdapterFromConfig:
    """Test from_config factory method."""

    def test_from_config_basic(self):
        """Test from_config creates adapter with basic config."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            config = {
                "project_id": "test-project",
                "region": "asia-east1",
                "gcs_staging_dir": "gs://test-bucket/data",
                "database": "test_db",
                "runtime_version": "2.2",
            }

            adapter = DataprocServerlessAdapter.from_config(config)

            assert adapter.project_id == "test-project"
            assert adapter.region == "asia-east1"
            assert adapter.database == "test_db"
            assert adapter.runtime_version == "2.2"


class TestDataprocServerlessAdapterClose:
    """Test cleanup functionality."""

    def test_close_logs_metrics(self):
        """Test close logs execution metrics."""
        with (
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()),
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.gcp.dataproc_serverless_adapter.logger") as mock_logger,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocServerlessAdapter

            adapter = DataprocServerlessAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )
            adapter._query_count = 5
            adapter._total_batch_time_seconds = 120.5

            adapter.close()

            # Verify logging was called
            mock_logger.info.assert_called()
