"""Tests for Amazon Athena for Apache Spark platform adapter.

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


class TestAthenaSparkAdapterInitialization:
    """Test AthenaSparkAdapter initialization."""

    def test_missing_workgroup_raises_error(self):
        """Test error when workgroup is not provided."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
        ):
            from benchbox.platforms.aws import AthenaSparkAdapter

            with pytest.raises(ConfigurationError, match="workgroup"):
                AthenaSparkAdapter(
                    s3_staging_dir="s3://my-bucket/benchbox-data",
                )

    def test_missing_s3_staging_dir_raises_error(self):
        """Test error when s3_staging_dir is not provided."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
        ):
            from benchbox.platforms.aws import AthenaSparkAdapter

            with pytest.raises(ConfigurationError, match="s3_staging_dir"):
                AthenaSparkAdapter(
                    workgroup="spark-workgroup",
                )

    def test_invalid_s3_path_raises_error(self):
        """Test error when s3_staging_dir has invalid format."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
        ):
            from benchbox.platforms.aws import AthenaSparkAdapter

            with pytest.raises(ConfigurationError, match="Invalid S3"):
                AthenaSparkAdapter(
                    workgroup="spark-workgroup",
                    s3_staging_dir="/local/path",
                )

    def test_valid_configuration(self):
        """Test valid configuration initializes correctly."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/benchbox-data",
                region="us-west-2",
                database="my_benchmark_db",
            )

            assert adapter.workgroup == "spark-workgroup"
            assert adapter.s3_bucket == "my-bucket"
            assert adapter.s3_prefix == "benchbox-data"
            assert adapter.region == "us-west-2"
            assert adapter.database == "my_benchmark_db"

    def test_default_values(self):
        """Test default configuration values."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            assert adapter.region == "us-east-1"
            assert adapter.database == "benchbox"
            assert adapter.session_idle_timeout_minutes == 15
            assert adapter.coordinator_dpu_size == 1
            assert adapter.max_concurrent_dpus == 20
            assert adapter.default_executor_dpu_size == 1
            assert adapter.timeout_minutes == 60

    def test_optional_session_configuration(self):
        """Test optional session configuration."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
                coordinator_dpu_size=2,
                max_concurrent_dpus=40,
                session_idle_timeout_minutes=30,
            )

            assert adapter.coordinator_dpu_size == 2
            assert adapter.max_concurrent_dpus == 40
            assert adapter.session_idle_timeout_minutes == 30


class TestAthenaSparkTableFormat:
    """Test table_format parameter configuration."""

    def test_table_format_default_parquet(self):
        """Test table_format defaults to parquet."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-wg",
                s3_staging_dir="s3://bucket/data",
            )
            assert adapter.table_format == "parquet"

    def test_table_format_delta(self):
        """Test table_format can be set to delta."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-wg",
                s3_staging_dir="s3://bucket/data",
                table_format="delta",
            )
            assert adapter.table_format == "delta"

    def test_table_format_from_config(self):
        """Test table_format is passed through from_config."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter.from_config(
                {
                    "workgroup": "spark-wg",
                    "s3_staging_dir": "s3://bucket/data",
                    "table_format": "iceberg",
                }
            )
            assert adapter.table_format == "iceberg"


class TestAthenaSparkAdapterPlatformInfo:
    """Test platform info methods."""

    def test_get_platform_info(self):
        """Test get_platform_info returns correct metadata."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
                region="eu-west-1",
            )

            info = adapter.get_platform_info()

            assert info["platform"] == "athena-spark"
            assert info["display_name"] == "Amazon Athena for Apache Spark"
            assert info["vendor"] == "AWS"
            assert info["type"] == "interactive_spark"
            assert info["region"] == "eu-west-1"
            assert info["workgroup"] == "spark-workgroup"
            assert info["supports_sql"] is True
            assert info["supports_dataframe"] is True
            assert info["billing_model"] == "DPU-hour"

    def test_get_dialect(self):
        """Test get_target_dialect returns spark."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            assert adapter.get_target_dialect() == "spark"


class TestAthenaSparkAdapterConnection:
    """Test connection functionality."""

    def test_create_connection_starts_session(self):
        """Test create_connection starts a new Spark session."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3") as mock_boto3,
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock Athena client
            mock_athena_client = MagicMock()
            mock_athena_client.start_session.return_value = {
                "SessionId": "session-123",
                "State": "CREATING",
            }
            mock_athena_client.get_session_status.return_value = {"Status": {"State": "IDLE"}}
            mock_boto3.client.return_value = mock_athena_client

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            result = adapter.create_connection()

            assert result["status"] == "connected"
            assert result["session_id"] == "session-123"
            mock_athena_client.start_session.assert_called_once()

    def test_create_connection_handles_error(self):
        """Test create_connection handles session creation errors."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3") as mock_boto3,
            patch("benchbox.platforms.aws.athena_spark_adapter.ClientError", Exception),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            # Setup mock to raise error
            mock_athena_client = MagicMock()
            error_response = {"Error": {"Code": "InvalidRequestException", "Message": "Not a Spark workgroup"}}
            mock_athena_client.start_session.side_effect = Exception("Invalid workgroup")
            mock_athena_client.start_session.side_effect.response = error_response
            mock_boto3.client.return_value = mock_athena_client

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="not-spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            with pytest.raises(Exception):
                adapter.create_connection()


class TestAthenaSparkSessionState:
    """Test session state constants."""

    def test_session_state_values(self):
        """Test AthenaSparkSessionState constants are correct."""
        from benchbox.platforms.aws.athena_spark_adapter import AthenaSparkSessionState

        assert AthenaSparkSessionState.CREATING == "CREATING"
        assert AthenaSparkSessionState.IDLE == "IDLE"
        assert AthenaSparkSessionState.BUSY == "BUSY"
        assert AthenaSparkSessionState.TERMINATED == "TERMINATED"
        assert AthenaSparkSessionState.FAILED == "FAILED"

    def test_ready_states(self):
        """Test ready states are correctly defined."""
        from benchbox.platforms.aws.athena_spark_adapter import AthenaSparkSessionState

        assert AthenaSparkSessionState.IDLE in AthenaSparkSessionState.READY_STATES
        assert AthenaSparkSessionState.CREATED in AthenaSparkSessionState.READY_STATES
        assert AthenaSparkSessionState.BUSY not in AthenaSparkSessionState.READY_STATES

    def test_terminal_states(self):
        """Test terminal states are correctly defined."""
        from benchbox.platforms.aws.athena_spark_adapter import AthenaSparkSessionState

        assert AthenaSparkSessionState.TERMINATED in AthenaSparkSessionState.TERMINAL_STATES
        assert AthenaSparkSessionState.FAILED in AthenaSparkSessionState.TERMINAL_STATES
        assert AthenaSparkSessionState.IDLE not in AthenaSparkSessionState.TERMINAL_STATES


class TestAthenaSparkCalculationState:
    """Test calculation state constants."""

    def test_calculation_state_values(self):
        """Test AthenaSparkCalculationState constants are correct."""
        from benchbox.platforms.aws.athena_spark_adapter import AthenaSparkCalculationState

        assert AthenaSparkCalculationState.CREATING == "CREATING"
        assert AthenaSparkCalculationState.RUNNING == "RUNNING"
        assert AthenaSparkCalculationState.COMPLETED == "COMPLETED"
        assert AthenaSparkCalculationState.FAILED == "FAILED"
        assert AthenaSparkCalculationState.CANCELED == "CANCELED"

    def test_terminal_states(self):
        """Test terminal states are correctly defined."""
        from benchbox.platforms.aws.athena_spark_adapter import AthenaSparkCalculationState

        assert AthenaSparkCalculationState.COMPLETED in AthenaSparkCalculationState.TERMINAL_STATES
        assert AthenaSparkCalculationState.FAILED in AthenaSparkCalculationState.TERMINAL_STATES
        assert AthenaSparkCalculationState.CANCELED in AthenaSparkCalculationState.TERMINAL_STATES
        assert AthenaSparkCalculationState.RUNNING not in AthenaSparkCalculationState.TERMINAL_STATES


class TestAthenaSparkAdapterRegistry:
    """Test platform registry integration."""

    def test_platform_metadata_exists(self):
        """Test Athena Spark metadata exists in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "athena-spark" in all_metadata

    def test_platform_metadata_content(self):
        """Test Athena Spark metadata content is correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()
        assert "athena-spark" in all_metadata
        spark_meta = all_metadata["athena-spark"]

        assert spark_meta["display_name"] == "Amazon Athena for Apache Spark"
        assert spark_meta["category"] == "cloud"
        assert spark_meta["capabilities"]["supports_sql"] is True
        assert spark_meta["capabilities"]["supports_dataframe"] is True
        assert "interactive" in spark_meta["supports"]


class TestAthenaSparkAdapterTuning:
    """Test tuning interface implementation."""

    def test_apply_platform_optimizations(self):
        """Test apply_platform_optimizations returns empty list."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            result = adapter.apply_platform_optimizations(MagicMock())
            assert result == []

    def test_apply_primary_keys(self):
        """Test apply_primary_keys returns empty list."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            config = MagicMock()
            config.enabled = True
            result = adapter.apply_primary_keys(config)
            assert result == []

    def test_configure_for_benchmark(self):
        """Test configure_for_benchmark sets benchmark type."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
            # SparkConfigOptimizer is now used from the mixin module
            patch("benchbox.platforms.base.cloud_spark.mixins.SparkConfigOptimizer") as mock_optimizer,
        ):
            mock_staging.from_uri.return_value = MagicMock()
            mock_config = MagicMock()
            mock_config.to_dict.return_value = {"spark.sql.shuffle.partitions": "200"}
            mock_optimizer.for_tpch.return_value = mock_config

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )

            adapter.configure_for_benchmark(None, "tpch")

            assert adapter._benchmark_type == "tpch"
            mock_optimizer.for_tpch.assert_called_once()


class TestAthenaSparkAdapterCLI:
    """Test CLI argument handling."""

    def test_add_cli_arguments(self):
        """Test add_cli_arguments adds expected arguments."""
        from benchbox.platforms.aws import AthenaSparkAdapter

        parser = MagicMock()
        parser.add_argument_group.return_value = MagicMock()

        AthenaSparkAdapter.add_cli_arguments(parser)

        parser.add_argument_group.assert_called_once_with("Athena Spark Options")


class TestAthenaSparkAdapterFromConfig:
    """Test from_config factory method."""

    def test_from_config_basic(self):
        """Test from_config creates adapter with basic config."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()),
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            from benchbox.platforms.aws import AthenaSparkAdapter

            config = {
                "workgroup": "test-spark-workgroup",
                "s3_staging_dir": "s3://test-bucket/data",
                "region": "ap-southeast-1",
                "database": "test_db",
                "coordinator_dpu_size": 2,
            }

            adapter = AthenaSparkAdapter.from_config(config)

            assert adapter.workgroup == "test-spark-workgroup"
            assert adapter.region == "ap-southeast-1"
            assert adapter.database == "test_db"
            assert adapter.coordinator_dpu_size == 2


class TestAthenaSparkAdapterClose:
    """Test cleanup functionality."""

    def test_close_terminates_session(self):
        """Test close terminates the active session."""
        with (
            patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True),
            patch("benchbox.platforms.aws.athena_spark_adapter.boto3") as mock_boto3,
            patch("benchbox.platforms.aws.athena_spark_adapter.CloudSparkStaging") as mock_staging,
        ):
            mock_staging.from_uri.return_value = MagicMock()

            mock_athena_client = MagicMock()
            mock_boto3.client.return_value = mock_athena_client

            from benchbox.platforms.aws import AthenaSparkAdapter

            adapter = AthenaSparkAdapter(
                workgroup="spark-workgroup",
                s3_staging_dir="s3://my-bucket/data",
            )
            adapter._session_id = "session-456"
            adapter._query_count = 5
            adapter._total_execution_time_seconds = 120.5

            adapter.close()

            mock_athena_client.terminate_session.assert_called_once_with(SessionId="session-456")
            assert adapter._session_id is None
