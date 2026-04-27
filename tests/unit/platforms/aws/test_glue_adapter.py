"""Tests for AWS Glue platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestAWSGlueAdapterInitialization:
    """Test AWSGlueAdapter initialization."""

    def test_missing_s3_staging_dir_raises_error(self):
        """Test error when s3_staging_dir is not provided."""
        from benchbox.platforms.aws import AWSGlueAdapter

        with pytest.raises(ConfigurationError, match="s3_staging_dir"):
            AWSGlueAdapter(
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

    def test_missing_job_role_raises_error(self):
        """Test error when job_role is not provided."""
        from benchbox.platforms.aws import AWSGlueAdapter

        with pytest.raises(ConfigurationError, match="job_role"):
            AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/benchbox-data",
            )

    def test_invalid_s3_path_raises_error(self):
        """Test error when s3_staging_dir has invalid format."""
        from benchbox.platforms.aws import AWSGlueAdapter

        with pytest.raises(ConfigurationError, match="Invalid S3"):
            AWSGlueAdapter(
                s3_staging_dir="/local/path",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

    def test_valid_configuration(self):
        """Test valid configuration initializes correctly."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/benchbox-data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
                region="us-west-2",
                database="my_benchmark_db",
            )

            assert adapter.s3_bucket == "my-bucket"
            assert adapter.s3_prefix == "benchbox-data"
            assert adapter.region == "us-west-2"
            assert adapter.database == "my_benchmark_db"
            assert adapter.job_role == "arn:aws:iam::123456789012:role/GlueRole"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            assert adapter.region == "us-east-1"
            assert adapter.database == "benchbox"
            assert adapter.worker_type == "G.1X"
            assert adapter.number_of_workers == 2
            assert adapter.glue_version == "4.0"
            assert adapter.job_timeout == 60


class TestAWSGlueAdapterPlatformInfo:
    """Test platform information methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct information."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
                region="eu-west-1",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "aws_glue"
            assert info["display_name"] == "AWS Glue"
            assert info["dialect"] == "spark"
            assert info["region"] == "eu-west-1"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True

    def test_get_dialect(self):
        """Test get_dialect returns spark."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            assert adapter.get_dialect() == "spark"


class TestAWSGlueAdapterConnection:
    """Test connection management."""

    def test_create_connection_success(self):
        """Test successful connection creation."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.aws.glue_adapter.boto3") as mock_boto3,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_session = MagicMock()
            mock_glue_client = MagicMock()
            mock_glue_client.get_databases.return_value = {"DatabaseList": []}
            mock_session.client.return_value = mock_glue_client
            mock_boto3.Session.return_value = mock_session

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            client = adapter.create_connection()

            assert client == mock_glue_client
            mock_glue_client.get_databases.assert_called_once()


class TestAWSGlueAdapterSchema:
    """Test schema creation."""

    def test_create_schema_new_database(self):
        """Test creating a new Glue database."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.aws.glue_adapter.boto3") as mock_boto3,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_session = MagicMock()
            mock_glue_client = MagicMock()

            # Create a mock exception class that matches ClientError behavior
            class MockClientError(Exception):
                def __init__(self, error_response, operation_name):
                    self.response = error_response
                    self.operation_name = operation_name
                    super().__init__(f"{operation_name}: {error_response}")

            # Patch ClientError with the mock class
            with patch("benchbox.platforms.aws.glue_adapter.ClientError", MockClientError):
                # Simulate database not found
                error_response = {"Error": {"Code": "EntityNotFoundException"}}
                mock_glue_client.get_database.side_effect = MockClientError(error_response, "GetDatabase")
                mock_session.client.return_value = mock_glue_client
                mock_boto3.Session.return_value = mock_session

                from benchbox.platforms.aws import AWSGlueAdapter

                adapter = AWSGlueAdapter(
                    s3_staging_dir="s3://my-bucket/data",
                    job_role="arn:aws:iam::123456789012:role/GlueRole",
                    database="tpch_sf1",
                )

                adapter.create_schema(None, None)

                mock_glue_client.create_database.assert_called_once()
                call_args = mock_glue_client.create_database.call_args
                assert call_args[1]["DatabaseInput"]["Name"] == "tpch_sf1"

    def test_create_schema_existing_database(self):
        """Test creating schema when database already exists."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.aws.glue_adapter.boto3") as mock_boto3,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_session = MagicMock()
            mock_glue_client = MagicMock()
            mock_glue_client.get_database.return_value = {"Database": {"Name": "existing_db"}}
            mock_session.client.return_value = mock_glue_client
            mock_boto3.Session.return_value = mock_session

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            adapter.create_schema(None, None)

            # Should not try to create database
            mock_glue_client.create_database.assert_not_called()


class TestAWSGlueAdapterDataLoading:
    """Test data loading functionality."""

    def test_load_data_existing_tables(self):
        """Test load_data skips upload when tables exist."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging_instance = MagicMock()
            mock_staging_instance.tables_exist.return_value = True
            mock_staging_instance.get_table_uri.side_effect = lambda t: f"s3://bucket/{t}/"
            mock_staging.from_uri.return_value = mock_staging_instance

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            mock_benchmark = SimpleNamespace(tables=["lineitem", "orders"])
            with tempfile.TemporaryDirectory() as tmpdir:
                result_dict, _, _ = adapter.load_data(mock_benchmark, None, tmpdir)

            assert "lineitem" in result_dict
            assert "orders" in result_dict
            mock_staging_instance.upload_tables.assert_not_called()

    def test_load_data_new_tables(self):
        """Test load_data uploads tables when they don't exist."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.aws.glue_adapter.boto3") as mock_boto3,
        ):
            mock_staging_instance = MagicMock()
            mock_staging_instance.tables_exist.return_value = False
            mock_staging_instance.upload_tables.return_value = {
                "lineitem": "s3://bucket/lineitem/",
                "orders": "s3://bucket/orders/",
            }
            mock_staging.from_uri.return_value = mock_staging_instance

            mock_session = MagicMock()
            mock_glue_client = MagicMock()
            mock_session.client.return_value = mock_glue_client
            mock_boto3.Session.return_value = mock_session

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            mock_benchmark = SimpleNamespace(tables=["lineitem", "orders"])
            with tempfile.TemporaryDirectory() as tmpdir:
                source_dir = Path(tmpdir)
                (source_dir / "lineitem.parquet").write_text("data")
                (source_dir / "orders.parquet").write_text("data")

                result_dict, _, _ = adapter.load_data(mock_benchmark, None, source_dir)

            assert "lineitem" in result_dict
            assert "orders" in result_dict
            mock_staging_instance.upload_tables.assert_called_once()


class TestAWSGlueAdapterJobStatus:
    """Test Glue job status constants."""

    def test_job_status_values(self):
        """Test all job status values are defined."""
        from benchbox.platforms.aws.glue_adapter import GlueJobStatus

        assert GlueJobStatus.STARTING == "STARTING"
        assert GlueJobStatus.RUNNING == "RUNNING"
        assert GlueJobStatus.SUCCEEDED == "SUCCEEDED"
        assert GlueJobStatus.FAILED == "FAILED"
        assert GlueJobStatus.TIMEOUT == "TIMEOUT"
        assert GlueJobStatus.STOPPED == "STOPPED"


class TestAWSGlueAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_metadata_exists(self):
        """Test AWS Glue metadata exists in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        # Check that glue is in the platform metadata
        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "glue" in all_metadata

    def test_platform_metadata_content(self):
        """Test AWS Glue metadata content is correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        # Access metadata through the public interface
        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "glue" in all_metadata
        glue_meta = all_metadata["glue"]

        assert glue_meta["display_name"] == "AWS Glue"
        assert glue_meta["category"] == "cloud"
        assert glue_meta["capabilities"]["supports_sql"] is True
        assert glue_meta["capabilities"]["supports_dataframe"] is True


class TestAWSGlueAdapterTuning:
    """Test tuning interface implementation."""

    def test_apply_platform_optimizations(self):
        """Test apply_platform_optimizations returns empty list."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            result = adapter.apply_platform_optimizations(MagicMock())

            assert result == []

    def test_apply_primary_keys(self):
        """Test apply_primary_keys returns empty list (not supported)."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            result = adapter.apply_primary_keys(MagicMock())

            assert result == []

    def test_configure_for_benchmark(self):
        """Test configure_for_benchmark doesn't raise."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )

            # Should not raise
            adapter.configure_for_benchmark(None, "tpch")


class TestAWSGlueAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test add_cli_arguments adds expected arguments."""
        from argparse import ArgumentParser

        from benchbox.platforms.aws import AWSGlueAdapter

        parser = ArgumentParser()
        AWSGlueAdapter.add_cli_arguments(parser)

        # Parse with defaults
        args = parser.parse_args([])

        assert args.region == "us-east-1"
        assert args.database == "benchbox"
        assert args.worker_type == "G.1X"
        assert args.number_of_workers == 2
        assert args.glue_version == "4.0"


class TestAWSGlueAdapterFromConfig:
    """Test from_config factory method."""

    def test_from_config_basic(self):
        """Test from_config creates adapter with basic config."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            config = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "s3_staging_dir": "s3://my-bucket/data",
                "job_role": "arn:aws:iam::123456789012:role/GlueRole",
                "region": "eu-central-1",
            }

            adapter = AWSGlueAdapter.from_config(config)

            assert adapter.region == "eu-central-1"
            assert adapter.s3_staging_dir == "s3://my-bucket/data"

    def test_from_config_generates_database_name(self):
        """Test from_config generates database name when not provided."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            config = {
                "benchmark": "tpch",
                "scale_factor": 0.01,
                "s3_staging_dir": "s3://my-bucket/data",
                "job_role": "arn:aws:iam::123456789012:role/GlueRole",
            }

            adapter = AWSGlueAdapter.from_config(config)

            # Should have generated a database name
            assert adapter.database is not None
            assert "tpch" in adapter.database.lower() or adapter.database == "benchbox"


class TestAWSGlueAdapterClose:
    """Test cleanup functionality."""

    def test_close_logs_dpu_hours(self):
        """Test close method logs DPU usage."""
        with (
            patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
            patch("benchbox.platforms.aws.glue_adapter.logger") as mock_logger,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AWSGlueAdapter

            adapter = AWSGlueAdapter(
                s3_staging_dir="s3://my-bucket/data",
                job_role="arn:aws:iam::123456789012:role/GlueRole",
            )
            adapter._total_dpu_hours = 1.5

            adapter.close()

            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            assert "DPU-hours" in call_args
