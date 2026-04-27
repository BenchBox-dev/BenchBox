"""Tests for GCP Dataproc platform adapter.

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


class TestDataprocAdapterInitialization:
    """Test DataprocAdapter initialization."""

    def test_missing_project_id_raises_error(self):
        """Test error when project_id is not provided."""
        from benchbox.platforms.gcp import DataprocAdapter

        with pytest.raises(ConfigurationError, match="project_id"):
            DataprocAdapter(
                gcs_staging_dir="gs://my-bucket/benchbox-data",
            )

    def test_missing_gcs_staging_dir_raises_error(self):
        """Test error when gcs_staging_dir is not provided."""
        from benchbox.platforms.gcp import DataprocAdapter

        with pytest.raises(ConfigurationError, match="gcs_staging_dir"):
            DataprocAdapter(
                project_id="my-project",
            )

    def test_invalid_gcs_path_raises_error(self):
        """Test error when gcs_staging_dir has invalid format."""
        from benchbox.platforms.gcp import DataprocAdapter

        with pytest.raises(ConfigurationError, match="Invalid GCS"):
            DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="/local/path",
            )

    def test_valid_configuration(self):
        """Test valid configuration initializes correctly."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                region="us-west1",
                cluster_name="my-cluster",
                gcs_staging_dir="gs://my-bucket/benchbox-data",
                database="my_benchmark_db",
            )

            assert adapter.gcs_bucket == "my-bucket"
            assert adapter.gcs_prefix == "benchbox-data"
            assert adapter.project_id == "my-project"
            assert adapter.region == "us-west1"
            assert adapter.cluster_name == "my-cluster"
            assert adapter.database == "my_benchmark_db"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
            )

            assert adapter.region == "us-central1"
            assert adapter.database == "benchbox"
            assert adapter.master_machine_type == "n2-standard-4"
            assert adapter.worker_machine_type == "n2-standard-4"
            assert adapter.num_workers == 2
            assert adapter.use_preemptible_workers is False
            assert adapter.timeout_minutes == 60
            assert adapter.create_ephemeral_cluster is False


class TestDataprocTableFormat:
    """Test table_format parameter configuration."""

    def test_table_format_default_parquet(self):
        """Test table_format defaults to parquet."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="proj",
                gcs_staging_dir="gs://bucket/data",
            )
            assert adapter.table_format == "parquet"

    def test_table_format_delta(self):
        """Test table_format can be set to delta."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="proj",
                gcs_staging_dir="gs://bucket/data",
                table_format="delta",
            )
            assert adapter.table_format == "delta"

    def test_table_format_from_config(self):
        """Test table_format is passed through from_config."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter.from_config(
                {
                    "project_id": "proj",
                    "gcs_staging_dir": "gs://bucket/data",
                    "table_format": "iceberg",
                }
            )
            assert adapter.table_format == "iceberg"


class TestDataprocAdapterPlatformInfo:
    """Test platform info methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct metadata."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                region="europe-west1",
                cluster_name="test-cluster",
                gcs_staging_dir="gs://my-bucket/data",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "dataproc"
            assert info["display_name"] == "Google Cloud Dataproc"
            assert info["vendor"] == "Google Cloud"
            assert info["type"] == "managed_spark"
            assert info["project_id"] == "my-project"
            assert info["region"] == "europe-west1"
            assert info["cluster_name"] == "test-cluster"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True

    def test_get_dialect(self):
        """Test get_target_dialect returns spark."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://my-bucket/data",
            )

            assert adapter.get_target_dialect() == "spark"


class TestDataprocAdapterConnection:
    """Test connection functionality."""

    def test_create_connection_success(self):
        """Test successful connection to existing cluster."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.dataproc_v1") as mock_dataproc,
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock cluster client
            mock_cluster_client = MagicMock()
            mock_cluster = MagicMock()
            mock_cluster.status.state.name = "RUNNING"
            mock_cluster.config.worker_config.num_instances = 4
            mock_cluster_client.get_cluster.return_value = mock_cluster
            mock_dataproc.ClusterControllerClient.return_value = mock_cluster_client

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                cluster_name="my-cluster",
                gcs_staging_dir="gs://my-bucket/data",
            )

            result = adapter.create_connection()

            assert result["status"] == "connected"
            assert result["cluster_name"] == "my-cluster"
            assert result["cluster_state"] == "RUNNING"


class TestDataprocAdapterDataLoading:
    """Test data loading functionality."""

    def test_load_data_existing_tables(self, tmp_path):
        """Test load_data skips upload when tables exist."""
        # Create actual source directory to pass validation
        source_dir = tmp_path / "test_data"
        source_dir.mkdir()

        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging_instance = MagicMock()
            mock_staging_instance.tables_exist.return_value = True
            mock_staging_instance.get_table_uri.side_effect = lambda t: f"gs://bucket/tables/{t}"
            mock_staging.from_uri.return_value = mock_staging_instance

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            mock_benchmark = SimpleNamespace(tables=["lineitem", "orders"])
            with patch.object(adapter, "_ensure_cluster_exists"):
                result_dict, _, _ = adapter.load_data(mock_benchmark, None, source_dir)

            assert "lineitem" in result_dict
            assert "orders" in result_dict
            mock_staging_instance.upload_tables.assert_not_called()


class TestDataprocJobState:
    """Test job state constants."""

    def test_job_state_values(self):
        """Test DataprocJobState constants are correct."""
        from benchbox.platforms.gcp.dataproc_adapter import DataprocJobState

        assert DataprocJobState.PENDING == "PENDING"
        assert DataprocJobState.RUNNING == "RUNNING"
        assert DataprocJobState.DONE == "DONE"
        assert DataprocJobState.ERROR == "ERROR"
        assert DataprocJobState.CANCELLED == "CANCELLED"


class TestDataprocAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_metadata_exists(self):
        """Test Dataproc metadata exists in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        # Check that dataproc is in the platform metadata
        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "dataproc" in all_metadata

    def test_platform_metadata_content(self):
        """Test Dataproc metadata content is correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        # Access metadata through the public interface
        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "dataproc" in all_metadata
        dataproc_meta = all_metadata["dataproc"]

        assert dataproc_meta["display_name"] == "Google Cloud Dataproc"
        assert dataproc_meta["category"] == "cloud"
        assert dataproc_meta["capabilities"]["supports_sql"] is True
        assert dataproc_meta["capabilities"]["supports_dataframe"] is True


class TestDataprocAdapterTuning:
    """Test tuning interface implementation."""

    def test_apply_platform_optimizations(self):
        """Test apply_platform_optimizations returns empty list."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            result = adapter.apply_platform_optimizations(MagicMock())
            assert result == []

    def test_apply_primary_keys(self):
        """Test apply_primary_keys returns empty list."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
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
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
            # SparkConfigOptimizer is now used from the mixin module
            patch("benchbox.platforms.base.cloud_spark.mixins.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_config = MagicMock()
            mock_config.to_dict.return_value = {"spark.sql.shuffle.partitions": "200"}
            mock_optimizer.for_tpch.return_value = mock_config

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )

            adapter.configure_for_benchmark(None, "tpch")

            assert adapter._benchmark_type == "tpch"
            mock_optimizer.for_tpch.assert_called_once()


class TestDataprocAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test add_cli_arguments adds expected arguments."""
        from benchbox.platforms.gcp import DataprocAdapter

        parser = MagicMock()
        parser.add_argument_group.return_value = MagicMock()

        DataprocAdapter.add_cli_arguments(parser)

        parser.add_argument_group.assert_called_once_with("Dataproc Options")


class TestDataprocAdapterFromConfig:
    """Test from_config factory method."""

    def test_from_config_basic(self):
        """Test from_config creates adapter with basic config."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            config = {
                "project_id": "test-project",
                "region": "asia-east1",
                "cluster_name": "test-cluster",
                "gcs_staging_dir": "gs://test-bucket/data",
                "database": "test_db",
            }

            adapter = DataprocAdapter.from_config(config)

            assert adapter.project_id == "test-project"
            assert adapter.region == "asia-east1"
            assert adapter.cluster_name == "test-cluster"
            assert adapter.database == "test_db"

    def test_from_config_generates_cluster_name(self):
        """Test from_config generates cluster name if not provided."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            config = {
                "project_id": "test-project",
                "gcs_staging_dir": "gs://test-bucket/data",
                "benchmark": "tpch",
                "scale_factor": 10,
            }

            adapter = DataprocAdapter.from_config(config)

            assert adapter.cluster_name.startswith("benchbox-tpch-sf10-")


class TestDataprocAdapterClose:
    """Test cleanup functionality."""

    def test_close_logs_metrics(self):
        """Test close logs execution metrics."""
        with (
            patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.gcp.dataproc_adapter.logger") as mock_logger,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.gcp import DataprocAdapter

            adapter = DataprocAdapter(
                project_id="my-project",
                gcs_staging_dir="gs://bucket/data",
            )
            adapter._query_count = 5
            adapter._total_job_time_seconds = 120.5

            adapter.close()

            # Verify logging was called
            mock_logger.info.assert_called()
