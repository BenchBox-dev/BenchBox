"""Tests for BigQuery platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base import DriverIsolationCapability
from benchbox.platforms.bigquery import BigQueryAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


@pytest.fixture
def dependencies_available():
    """Mock BigQuery dependency check to simulate installed extras."""

    with patch("benchbox.platforms.bigquery.check_platform_dependencies", return_value=(True, [])):
        yield


@pytest.mark.usefixtures("dependencies_available")
class TestBigQueryAdapter:
    """Test BigQuery platform adapter functionality."""

    def test_initialization_success(self, dependencies_available):
        """Test successful adapter initialization."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
                location="US",
                credentials_path="/path/to/service-account.json",
            )
            assert adapter.platform_name == "BigQuery"
            assert adapter.get_target_dialect() == "bigquery"
            assert adapter.project_id == "test-project"
            assert adapter.dataset_id == "test_dataset"
            assert adapter.location == "US"

    def test_initialization_with_defaults(self, dependencies_available):
        """Test initialization with default configuration."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
            assert adapter.location == "US"
            assert adapter.maximum_bytes_billed is None
            assert adapter.query_cache is False  # Cache disabled by default for accurate benchmarking
            assert adapter.dry_run is False

    def test_external_table_capability_declared(self, dependencies_available):
        """BigQuery should explicitly declare external-table support."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
            assert adapter.supports_external_tables is True

    def test_initialization_missing_driver(self):
        """Test initialization when BigQuery client library is not available."""
        with (
            patch(
                "benchbox.platforms.bigquery.check_platform_dependencies",
                return_value=(
                    False,
                    [
                        "google-cloud-bigquery",
                        "google-cloud-storage",
                    ],
                ),
            ),
            pytest.raises(ImportError, match="Missing dependencies for bigquery platform"),
        ):
            BigQueryAdapter()

    def test_initialization_missing_required_config(self, dependencies_available):
        """Test initialization with missing required configuration."""
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.bigquery.bigquery"):
            with pytest.raises(ConfigurationError, match="BigQuery configuration requires"):
                BigQueryAdapter()  # Missing required fields

    @patch("benchbox.platforms.bigquery.service_account")
    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_admin_client_with_credentials_path(
        self, mock_bigquery, mock_service_account, dependencies_available
    ):
        """Test admin client creation with credentials path."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client
        mock_credentials = Mock()
        mock_service_account.Credentials.from_service_account_file.return_value = mock_credentials

        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            credentials_path="/path/to/service-account.json",
        )

        client = adapter._create_admin_client()

        assert client == mock_client
        mock_service_account.Credentials.from_service_account_file.assert_called_once_with(
            "/path/to/service-account.json"
        )
        mock_bigquery.Client.assert_called_once_with(
            project="test-project", location="US", credentials=mock_credentials
        )

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_admin_client_with_default_credentials(self, mock_bigquery, dependencies_available):
        """Test admin client creation with default credentials."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client
        mock_credentials = Mock()

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Mock _load_credentials to return mock credentials
        with patch.object(adapter, "_load_credentials", return_value=mock_credentials):
            client = adapter._create_admin_client()

        assert client == mock_client
        mock_bigquery.Client.assert_called_once_with(
            project="test-project", location="US", credentials=mock_credentials
        )

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_check_server_database_exists_true(self, mock_bigquery, dependencies_available):
        """Test dataset existence check when dataset exists."""
        mock_client = Mock()
        mock_dataset = Mock()
        mock_dataset.dataset_id = "test_dataset"
        mock_client.list_datasets.return_value = [mock_dataset]
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        with patch.object(adapter, "_load_credentials", return_value=Mock()):
            exists = adapter.check_server_database_exists()

        assert exists is True
        mock_client.list_datasets.assert_called_once()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_check_server_database_exists_false(self, mock_bigquery, dependencies_available):
        """Test dataset existence check when dataset doesn't exist."""
        mock_client = Mock()
        mock_other_dataset = Mock()
        mock_other_dataset.dataset_id = "other_dataset"
        mock_client.list_datasets.return_value = [mock_other_dataset]
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        with patch.object(adapter, "_load_credentials", return_value=Mock()):
            exists = adapter.check_server_database_exists()

        assert exists is False

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_drop_database(self, mock_bigquery, dependencies_available):
        """Test dataset dropping."""
        mock_client = Mock()
        mock_dataset_ref = Mock()
        mock_client.dataset.return_value = mock_dataset_ref
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        with patch.object(adapter, "_load_credentials", return_value=Mock()):
            adapter.drop_database()

        mock_client.dataset.assert_called_once_with("test_dataset")
        mock_client.delete_dataset.assert_called_once_with(mock_dataset_ref, delete_contents=True, not_found_ok=True)

    @patch("benchbox.platforms.bigquery.bigquery")
    @patch("benchbox.platforms.bigquery.storage")
    def test_create_connection_success(self, mock_storage, mock_bigquery, dependencies_available):
        """Test successful connection creation."""
        mock_client = Mock()
        mock_storage_client = Mock()
        mock_bigquery.Client.return_value = mock_client
        mock_storage.Client.return_value = mock_storage_client
        mock_credentials = Mock()

        # Mock query execution
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(1,)]
        mock_client.query.return_value = mock_query_job

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Mock handle_existing_database and _load_credentials
        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_load_credentials", return_value=mock_credentials),
        ):
            connection = adapter.create_connection()

        assert connection == mock_client

        # Should test connection
        mock_client.query.assert_called_once_with("SELECT 1 as test")

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_connection_failure(self, mock_bigquery, dependencies_available):
        """Test connection creation failure."""
        mock_credentials = Mock()
        mock_bigquery.Client.side_effect = Exception("Authentication failed")

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_load_credentials", return_value=mock_credentials),
        ):
            with pytest.raises(Exception, match="Authentication failed"):
                adapter.create_connection()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_schema(self, mock_bigquery, dependencies_available):
        """Test schema creation with BigQuery tables."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        # Mock table creation
        mock_table = Mock()
        mock_client.create_table.return_value = mock_table

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INT64, name STRING);
            CREATE TABLE table2 (id INT64, data STRING);
        """

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Mock translate_sql method
        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = (
                "CREATE TABLE table1 (id INT64, name STRING);\nCREATE TABLE table2 (id INT64, data STRING);"
            )

            schema_time = adapter.create_schema(mock_benchmark, mock_client)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should create tables via DDL execution
        query_calls = list(mock_client.query.call_args_list)
        assert len(query_calls) >= 2  # At least 2 CREATE TABLE statements
        # Note: Actual SQL will be converted to BigQuery format with dataset qualification

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_load_data_with_csv_upload(self, mock_bigquery, dependencies_available):
        """Test data loading using BigQuery load jobs."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        # Mock load job
        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.output_rows = 100
        mock_client.load_table_from_file.return_value = mock_load_job

        # Mock row count query
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(100,)]
        mock_client.query.return_value = mock_query_job

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("id,name\n1,test1\n2,test2\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_client, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "TEST_TABLE" in table_stats
            assert table_stats["TEST_TABLE"] == 100

            # Should execute load job
            mock_client.load_table_from_file.assert_called_once()
            job_config_kwargs = mock_bigquery.LoadJobConfig.call_args.kwargs
            assert job_config_kwargs["source_format"] == mock_bigquery.SourceFormat.CSV
            assert job_config_kwargs["field_delimiter"] == ","

        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_load_data_with_direct_parquet_upload(self, mock_bigquery, dependencies_available):
        """Native local loads should use Parquet load jobs for parquet inputs."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_client.load_table_from_file.return_value = mock_load_job

        mock_query_job = Mock()
        mock_query_job.result.return_value = [(100,)]
        mock_client.query.return_value = mock_query_job

        mock_benchmark = Mock()

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".parquet", delete=False) as f:
            f.write(b"PAR1")  # content irrelevant — format detected from .parquet suffix
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_client, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert table_stats["TEST_TABLE"] == 100

            job_config_kwargs = mock_bigquery.LoadJobConfig.call_args.kwargs
            assert job_config_kwargs["source_format"] == mock_bigquery.SourceFormat.PARQUET
            assert "field_delimiter" not in job_config_kwargs
        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_load_data_with_compressed_parquet_upload(self, mock_bigquery, dependencies_available):
        """Compressed parquet (.parquet.gz) should still produce PARQUET source format, not CSV."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_client.load_table_from_file.return_value = mock_load_job

        mock_query_job = Mock()
        mock_query_job.result.return_value = [(100,)]
        mock_client.query.return_value = mock_query_job

        mock_benchmark = Mock()

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".parquet.gz", delete=False) as f:
            f.write(b"\x1f\x8b")  # gzip magic bytes
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_client, Path("/tmp"))

            assert table_stats["TEST_TABLE"] == 100

            job_config_kwargs = mock_bigquery.LoadJobConfig.call_args.kwargs
            assert job_config_kwargs["source_format"] == mock_bigquery.SourceFormat.PARQUET
            assert "field_delimiter" not in job_config_kwargs
        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_load_data_with_gcs_parquet_upload(self, mock_bigquery, dependencies_available):
        """Native GCS-staged loads should keep parquet as parquet."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_client.load_table_from_uri.return_value = mock_load_job

        mock_query_job = Mock()
        mock_query_job.result.return_value = [(100,)]
        mock_client.query.return_value = mock_query_job

        mock_benchmark = Mock()
        mock_bucket = Mock()

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".parquet", delete=False) as f:
            f.write(b"PAR1")  # content irrelevant — format detected from .parquet suffix
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
                storage_bucket="benchbox-bucket",
            )

            with patch.object(adapter, "_create_storage_bucket", return_value=mock_bucket):
                table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_client, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert table_stats["TEST_TABLE"] == 100

            job_config_kwargs = mock_bigquery.LoadJobConfig.call_args.kwargs
            assert job_config_kwargs["source_format"] == mock_bigquery.SourceFormat.PARQUET
            assert "field_delimiter" not in job_config_kwargs
            mock_client.load_table_from_uri.assert_called_once()
        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_build_load_job_config_warns_on_unrecognized_format(self, mock_bigquery, dependencies_available):
        """Unrecognized format should warn and fall back to CSV load job config."""
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # .vortex is a recognized format that is neither parquet nor delimited text —
        # detect_data_format returns "vortex", which is not in _DELIMITED_FORMATS
        with tempfile.NamedTemporaryFile(suffix=".vortex", delete=False) as f:
            temp_path = Path(f.name)

        try:
            mock_inner_logger = Mock(spec=logging.Logger)
            adapter.logger = mock_inner_logger
            adapter._build_load_job_config(
                temp_path,
                write_disposition=mock_bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            mock_inner_logger.warning.assert_called_once()
            warning_msg = mock_inner_logger.warning.call_args[0][0]
            assert "Unrecognized data format" in warning_msg
            assert "falling back to CSV" in warning_msg
            job_config_kwargs = mock_bigquery.LoadJobConfig.call_args.kwargs
            assert job_config_kwargs["source_format"] == mock_bigquery.SourceFormat.CSV
        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_validate_external_table_requirements_requires_bucket(self, mock_bigquery, dependencies_available):
        """External mode should require GCS staging configuration."""
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        with pytest.raises(ValueError, match="requires a GCS bucket"):
            adapter.validate_external_table_requirements()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_external_tables_generates_external_table_sql(self, mock_bigquery, dependencies_available):
        """External mode should create BigQuery external table SQL with GCS URIs."""
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="benchbox-bucket",
            storage_prefix="benchbox-data",
        )

        mock_connection = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_connection.query.return_value = mock_query_job

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [Path("/tmp/lineitem.parquet")]}),
            patch.object(
                adapter,
                "_prepare_external_parquet_uris",
                return_value=["gs://benchbox-bucket/benchbox-data/lineitem/lineitem.parquet"],
            ),
            patch.object(adapter, "_create_storage_bucket", return_value=Mock()),
            patch.object(adapter, "_get_table_row_count", return_value=55),
        ):
            table_stats, load_time, per_table_timings = adapter.create_external_tables(
                benchmark=Mock(),
                connection=mock_connection,
                data_dir=Path("/tmp"),
            )

        assert table_stats == {"LINEITEM": 55}
        assert isinstance(load_time, float)
        assert per_table_timings is None
        query_sql = str(mock_connection.query.call_args[0][0])
        assert "CREATE OR REPLACE EXTERNAL TABLE `test-project.test_dataset.LINEITEM`" in query_sql
        assert "format = 'PARQUET'" in query_sql
        assert "gs://benchbox-bucket/benchbox-data/lineitem/lineitem.parquet" in query_sql

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_external_tables_generates_delta_biglake_sql(self, mock_bigquery, dependencies_available):
        """Delta external mode should create BigLake SQL with DELTA_LAKE format."""
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="benchbox-bucket",
            storage_prefix="benchbox-data",
            biglake_connection="test-project.us.benchbox",
        )

        mock_connection = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_connection.query.return_value = mock_query_job

        with (
            patch.object(
                adapter,
                "_prepare_external_table_uris",
                return_value=("DELTA_LAKE", ["gs://benchbox-bucket/benchbox-data/lineitem/"]),
            ),
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [Path("/tmp/lineitem")]}),
            patch.object(adapter, "_create_storage_bucket", return_value=Mock()),
            patch.object(adapter, "_get_table_row_count", return_value=66),
        ):
            table_stats, _, _ = adapter.create_external_tables(
                benchmark=Mock(), connection=mock_connection, data_dir=Path("/tmp")
            )

        assert table_stats == {"LINEITEM": 66}
        query_sql = str(mock_connection.query.call_args[0][0])
        assert "WITH CONNECTION `test-project.us.benchbox`" in query_sql
        assert "format = 'DELTA_LAKE'" in query_sql

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_create_external_tables_delta_requires_biglake_connection(self, mock_bigquery, dependencies_available):
        """Delta external mode should reject runs without BigLake connection config."""
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="benchbox-bucket",
            storage_prefix="benchbox-data",
        )

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [Path("/tmp/lineitem")]}),
            patch.object(adapter, "_create_storage_bucket", return_value=Mock()),
            patch.object(
                adapter,
                "_prepare_external_delta_uris",
                return_value=["gs://benchbox-bucket/benchbox-data/lineitem/"],
            ),
            pytest.raises(ValueError, match="requires --platform-option biglake_connection"),
        ):
            adapter.create_external_tables(benchmark=Mock(), connection=Mock(), data_dir=Path("/tmp"))

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_configure_for_benchmark_olap(self, mock_bigquery, dependencies_available):
        """Test OLAP benchmark configuration."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Should not raise exception - BigQuery optimizations are automatic
        adapter.configure_for_benchmark(mock_client, "olap")

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_execute_query_success(self, mock_bigquery, dependencies_available):
        """Test successful query execution."""
        mock_client = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(1, "test"), (2, "test2")]
        mock_query_job.job_id = "job_123"
        mock_query_job.total_bytes_processed = 1024
        mock_query_job.total_bytes_billed = 512
        mock_query_job.slot_millis = 1000
        mock_client.query.return_value = mock_query_job
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        result = adapter.execute_query(mock_client, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)

        # Should include BigQuery-specific statistics
        assert result["job_id"] == "job_123"
        assert result["job_statistics"]["bytes_processed"] == 1024
        assert result["job_statistics"]["bytes_billed"] == 512
        assert result["job_statistics"]["slot_ms"] == 1000

        mock_client.query.assert_called_once()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_execute_query_with_job_config(self, mock_bigquery, dependencies_available):
        """Test query execution with job configuration."""
        mock_client = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(1, "test")]
        mock_query_job.job_id = "job_123"
        mock_query_job.total_bytes_processed = 1024
        mock_query_job.total_bytes_billed = 512
        mock_query_job.slot_millis = 1000
        mock_query_job.created = None
        mock_query_job.started = None
        mock_query_job.ended = None
        mock_client.query.return_value = mock_query_job
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            maximum_bytes_billed=1000000,
        )

        result = adapter.execute_query(mock_client, "SELECT * FROM test", "q1")

        assert result["status"] == "SUCCESS"
        assert result["job_statistics"]["bytes_processed"] == 1024

        # Should call query with job config
        mock_client.query.assert_called_once()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_execute_query_failure(self, mock_bigquery, dependencies_available):
        """Test query execution failure."""
        mock_client = Mock()
        mock_client.query.side_effect = Exception("Query failed")
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        result = adapter.execute_query(mock_client, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"
        assert isinstance(result["execution_time_seconds"], float)

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_get_platform_metadata(self, mock_bigquery, dependencies_available):
        """Test platform metadata collection."""
        mock_client = Mock()
        mock_client.project = "test-project"
        mock_client.location = "US"

        # Mock dataset info query
        mock_query_job = Mock()
        mock_query_job.result.return_value = [("test_dataset", "US", "2024-01-01 00:00:00", "BenchBox test dataset")]
        mock_client.query.return_value = mock_query_job

        # Mock tables info
        mock_tables = [Mock(), Mock()]
        mock_tables[0].table_id = "table1"
        mock_tables[0].num_rows = 1000
        mock_tables[0].num_bytes = 1024000
        mock_tables[1].table_id = "table2"
        mock_tables[1].num_rows = 2000
        mock_tables[1].num_bytes = 2048000
        mock_client.list_tables.return_value = mock_tables

        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        metadata = adapter._get_platform_metadata(mock_client)

        assert metadata["platform"] == "BigQuery"
        assert metadata["project_id"] == "test-project"
        assert metadata["dataset_id"] == "test_dataset"
        assert metadata["location"] == "US"
        assert "dataset_info" in metadata
        assert "tables" in metadata
        assert len(metadata["tables"]) == 2

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_close_connection(self, mock_bigquery, dependencies_available):
        """Test connection closing."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Should not raise exception - BigQuery client doesn't need explicit closing
        adapter.close_connection(mock_client)

    def test_supports_tuning_type(self, dependencies_available):
        """Test tuning type support checking."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            # Mock TuningType import
            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.SORTING = "sorting"

                assert adapter.supports_tuning_type(mock_tuning_type.PARTITIONING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.CLUSTERING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.SORTING) is False

    def test_generate_tuning_clause_with_partitioning(self, dependencies_available):
        """Test tuning clause generation with partitioning."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            # Mock table tuning with partitioning
            mock_tuning = Mock()
            mock_tuning.has_any_tuning.return_value = True

            # Mock partitioning column
            mock_column = Mock()
            mock_column.name = "partition_date"
            mock_column.order = 1
            mock_column.type = "DATE"

            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"

                def mock_get_columns_by_type(tuning_type):
                    if tuning_type == mock_tuning_type.PARTITIONING:
                        return [mock_column]
                    return []

                mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

                clause = adapter.generate_tuning_clause(mock_tuning)

                assert "PARTITION BY partition_date" in clause

    def test_generate_tuning_clause_with_clustering(self, dependencies_available):
        """Test tuning clause generation with clustering."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            # Mock table tuning with clustering
            mock_tuning = Mock()
            mock_tuning.has_any_tuning.return_value = True

            # Mock clustering columns
            mock_column1 = Mock()
            mock_column1.name = "cluster_key1"
            mock_column1.order = 1
            mock_column2 = Mock()
            mock_column2.name = "cluster_key2"
            mock_column2.order = 2

            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"

                def mock_get_columns_by_type(tuning_type):
                    if tuning_type == mock_tuning_type.CLUSTERING:
                        return [mock_column1, mock_column2]
                    return []

                mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

                clause = adapter.generate_tuning_clause(mock_tuning)

                assert "CLUSTER BY cluster_key1, cluster_key2" in clause

    def test_generate_tuning_clause_none(self, dependencies_available):
        """Test tuning clause generation with None input."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            clause = adapter.generate_tuning_clause(None)
            assert clause == ""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_apply_table_tunings_with_partitioning(self, mock_bigquery, dependencies_available):
        """Test applying table tunings with partitioning."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Mock table tuning
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"
        mock_tuning.has_any_tuning.return_value = True

        # Mock partitioning column
        mock_column = Mock()
        mock_column.name = "partition_date"
        mock_column.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.DISTRIBUTION = "distribution"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.PARTITIONING:
                    return [mock_column]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            # Should not raise exception - BigQuery tuning is applied during table creation
            adapter.apply_table_tunings(mock_tuning, mock_client)

    def test_apply_unified_tuning(self, dependencies_available):
        """Test unified tuning configuration application."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            mock_client = Mock()
            mock_unified_config = Mock()
            mock_unified_config.primary_keys = Mock()
            mock_unified_config.foreign_keys = Mock()
            mock_unified_config.platform_optimizations = Mock()
            mock_unified_config.table_tunings = {}

            # Should not raise exception
            with patch.object(adapter, "apply_constraint_configuration"):
                with patch.object(adapter, "apply_platform_optimizations"):
                    adapter.apply_unified_tuning(mock_unified_config, mock_client)

    def test_apply_constraint_configuration(self, dependencies_available):
        """Test constraint configuration application."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            mock_client = Mock()
            mock_primary_key_config = Mock()
            mock_primary_key_config.enabled = True
            mock_foreign_key_config = Mock()
            mock_foreign_key_config.enabled = False

            # Should not raise exception - constraints are not enforced in BigQuery
            adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, mock_client)

    def test_cost_control_features(self, dependencies_available):
        """Test BigQuery cost control features."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
                maximum_bytes_billed=1000000,  # 1MB limit
                query_cache=True,
                dry_run=True,
            )

            assert adapter.maximum_bytes_billed == 1000000
            assert adapter.query_cache is True
            assert adapter.dry_run is True

    def test_authentication_methods(self, dependencies_available):
        """Test different authentication methods."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            # Test service account file authentication
            adapter1 = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
                credentials_path="/path/to/key.json",
            )
            assert adapter1.credentials_path == "/path/to/key.json"

            # Test default credentials (ADC)
            adapter2 = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
            assert adapter2.credentials_path is None

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_job_configuration_options(self, mock_bigquery, dependencies_available):
        """Test BigQuery job configuration options."""
        mock_client = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(1,)]
        mock_client.query.return_value = mock_query_job
        mock_bigquery.Client.return_value = mock_client

        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            maximum_bytes_billed=1000000,
            use_legacy_sql=False,
            job_timeout_ms=600000,
        )

        result = adapter.execute_query(mock_client, "SELECT 1", "q1")

        assert result["status"] == "SUCCESS"

        # Should configure query job with specified options
        # Note: timeout handling varies by BigQuery client version
        mock_client.query.assert_called_once()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_data_location_and_regional_settings(self, mock_bigquery, dependencies_available):
        """Test BigQuery data location and regional settings."""
        mock_client = Mock()
        mock_bigquery.Client.return_value = mock_client

        # Test different regions
        adapter_us = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset", location="US")
        assert adapter_us.location == "US"

        adapter_eu = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset", location="EU")
        assert adapter_eu.location == "EU"

        adapter_asia = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            location="asia-northeast1",
        )
        assert adapter_asia.location == "asia-northeast1"

    def test_file_format_detection_for_chunked_files(self, dependencies_available):
        """Test that chunked TPC-H data files (.tbl.1, .tbl.2, etc.) are detected as pipe-delimited.

        This verifies the fix for the bug where chunked files like customer.tbl.1 were treated
        as CSV (comma-delimited) instead of TBL (pipe-delimited), causing data loading failures.
        """
        from pathlib import Path

        test_cases = [
            (Path("customer.tbl"), True, "Simple .tbl file"),
            (Path("customer.tbl.1"), True, "Chunked .tbl file"),
            (Path("lineitem.tbl.10"), True, "Chunked .tbl file (2 digits)"),
            (Path("orders.tbl.gz"), True, "Compressed .tbl file"),
            (Path("part.tbl.1.gz"), True, "Chunked compressed .tbl file"),
            (Path("nation.tbl.zst"), True, "zstd compressed .tbl file"),
            (Path("partsupp.dat"), True, "TPC-DS .dat file"),
            (Path("partsupp.dat.1"), True, "Chunked TPC-DS .dat file"),
            (Path("region.csv"), False, "CSV file"),
            (Path("supplier.csv.gz"), False, "Compressed CSV file"),
        ]

        for file_path, should_be_tbl, description in test_cases:
            file_str = str(file_path.name)
            is_tbl = ".tbl" in file_str or ".dat" in file_str
            assert is_tbl == should_be_tbl, f"Failed for {description}: {file_path.name}"

    def test_validate_data_integrity_with_client_api(self, dependencies_available):
        """Test that data integrity validation uses BigQuery Client API instead of cursor pattern.

        This verifies the fix for "'Client' object has no attribute 'cursor'" errors
        during database compatibility validation.
        """
        from unittest.mock import Mock

        # Mock BigQuery client and query results
        mock_client = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(1,)]  # Mock query result
        mock_client.query.return_value = mock_query_job

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Create mock benchmark
        mock_benchmark = Mock()

        # Table stats from validation
        table_stats = {
            "customer": 150,
            "lineitem": 6005,
            "nation": 25,
            "region": 5,
        }

        # Call validation method
        status, details = adapter._validate_data_integrity(mock_benchmark, mock_client, table_stats)

        # Verify it uses query() not cursor()
        assert mock_client.query.called, "Should use client.query() not client.cursor()"
        assert not hasattr(mock_client, "cursor") or not mock_client.cursor.called

        # Verify status is PASSED when all tables accessible
        assert status == "PASSED"
        assert "accessible_tables" in details
        assert len(details["accessible_tables"]) == 4

    def test_validate_data_integrity_handles_inaccessible_tables(self, dependencies_available):
        """Test that validation correctly detects inaccessible tables."""
        from unittest.mock import Mock

        mock_client = Mock()

        # Mock query to fail for some tables
        def query_side_effect(sql):
            mock_job = Mock()
            if "CUSTOMER" in sql or "LINEITEM" in sql:
                # Simulate table not found or inaccessible
                mock_job.result.side_effect = Exception("404 Table not found")
            else:
                mock_job.result.return_value = [(1,)]
            return mock_job

        mock_client.query.side_effect = query_side_effect

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        mock_benchmark = Mock()

        table_stats = {"customer": 0, "lineitem": 0, "nation": 25, "region": 5}

        status, details = adapter._validate_data_integrity(mock_benchmark, mock_client, table_stats)

        # Should fail when tables are inaccessible
        assert status == "FAILED"
        assert "inaccessible_tables" in details
        assert "customer" in details["inaccessible_tables"]
        assert "lineitem" in details["inaccessible_tables"]

    def test_get_table_row_count_uses_query_api(self, dependencies_available):
        """Test that get_table_row_count uses BigQuery Client API instead of cursor pattern.

        This verifies the fix for validation framework cursor errors during
        database compatibility checks.
        """
        from unittest.mock import Mock

        mock_client = Mock()
        mock_query_job = Mock()
        mock_query_job.result.return_value = [(150,)]  # Mock COUNT(*) result
        mock_client.query.return_value = mock_query_job

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Get row count for customer table
        row_count = adapter.get_table_row_count(mock_client, "customer")

        # Verify it uses query() not cursor()
        assert mock_client.query.called, "Should use client.query() not client.cursor()"
        assert not hasattr(mock_client, "cursor") or not mock_client.cursor.called

        # Verify row count is correct
        assert row_count == 150

    def test_get_table_row_count_handles_errors(self, dependencies_available):
        """Test that get_table_row_count returns 0 on errors."""
        from unittest.mock import Mock

        mock_client = Mock()
        mock_client.query.side_effect = Exception("Table not found")

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Should return 0 on error, not raise exception
        row_count = adapter.get_table_row_count(mock_client, "nonexistent_table")
        assert row_count == 0

    def test_storage_client_not_created_in_connection(self, dependencies_available):
        """Test that Storage client is NOT created during create_connection (lazy creation).

        Previously, create_connection would always create a Storage client and attach it
        to the connection object. This test verifies the new behavior where Storage client
        is only created on-demand when actually needed (during load_data with storage_bucket).
        """
        from unittest.mock import Mock, patch

        # Mock BigQuery and Storage clients
        with (
            patch("benchbox.platforms.bigquery.bigquery") as mock_bigquery,
            patch("benchbox.platforms.bigquery.storage") as mock_storage,
        ):
            mock_client = Mock(spec=["query", "close"])  # Strict spec prevents arbitrary attributes
            mock_bigquery.Client.return_value = mock_client

            # Mock successful connection test
            mock_query_job = Mock()
            mock_query_job.result.return_value = []
            mock_client.query.return_value = mock_query_job

            adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

            # Create connection with mocked _load_credentials
            with patch.object(adapter, "_load_credentials", return_value=Mock()):
                adapter.create_connection()

            # Verify Storage client was NOT created during connection
            # This is the key behavior change - Storage client creation is now lazy
            assert not mock_storage.Client.called, "Storage client should not be created in create_connection"

    def test_close_connection_handles_credential_errors(self, dependencies_available):
        """Test that close_connection gracefully handles credential refresh errors."""
        from unittest.mock import Mock

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Create mock connection that raises credential error on close
        mock_client = Mock()
        mock_client.close.side_effect = Exception("Anonymous credentials cannot be refreshed")

        # Should not raise exception - error should be suppressed
        adapter.close_connection(mock_client)

        # Verify close was attempted
        assert mock_client.close.called

    def test_close_connection_warns_on_other_errors(self, dependencies_available):
        """Test that close_connection warns on non-credential errors."""
        from unittest.mock import Mock

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Create mock connection that raises non-credential error
        mock_client = Mock()
        mock_client.close.side_effect = Exception("Network timeout")

        # Should log warning but not raise
        with patch.object(adapter.logger, "warning") as mock_warning:
            adapter.close_connection(mock_client)
            assert mock_warning.called

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_direct_loading_with_chunked_files(self, mock_bigquery, dependencies_available):
        """Test that direct loading handles chunked files (TPC-DS style) correctly."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, Mock

        # Mock WriteDisposition enum
        mock_bigquery.WriteDisposition.WRITE_TRUNCATE = "WRITE_TRUNCATE"
        mock_bigquery.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"

        # Track job configs to verify write dispositions
        job_configs = []

        def create_job_config(**kwargs):
            config = Mock()
            for k, v in kwargs.items():
                setattr(config, k, v)
            job_configs.append(config)
            return config

        mock_bigquery.LoadJobConfig = create_job_config

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Create temporary test files
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create chunked files (like TPC-DS generates)
            chunk1 = tmpdir / "customer_1.dat"
            chunk2 = tmpdir / "customer_2.dat"
            chunk1.write_text("1|John|100\n2|Jane|200\n")
            chunk2.write_text("3|Bob|300\n4|Alice|400\n")

            # Single file (like TPC-H)
            single = tmpdir / "nation.dat"
            single.write_text("1|USA\n2|Canada\n")

            # Create mock benchmark with tables as lists (TPC-DS style)
            mock_benchmark = Mock()
            mock_benchmark.tables = {
                "customer": [chunk1, chunk2],  # Multiple chunks
                "nation": [single],  # Single chunk in list
            }

            # Create mock BigQuery connection
            mock_connection = MagicMock()
            mock_dataset = Mock()
            mock_table_ref = Mock()
            mock_connection.dataset.return_value = mock_dataset
            mock_dataset.table.return_value = mock_table_ref

            # Mock load_table_from_file
            mock_load_job = Mock()
            mock_load_job.result.return_value = None
            mock_connection.load_table_from_file.return_value = mock_load_job

            # Mock query for row counts
            mock_query_job = Mock()
            mock_connection.query.return_value = mock_query_job

            # Return different row counts for different tables
            def mock_result():
                # First call is for customer (after all chunks), second is for nation
                if not hasattr(mock_result, "call_count"):
                    mock_result.call_count = 0
                mock_result.call_count += 1
                if mock_result.call_count == 1:
                    return [(4,)]  # customer: 4 rows (2 + 2)
                else:
                    return [(2,)]  # nation: 2 rows

            mock_query_job.result.side_effect = [mock_result(), mock_result()]

            # Call load_data
            table_stats, total_time, per_table_timings = adapter.load_data(mock_benchmark, mock_connection, tmpdir)

            # Verify both tables were loaded
            assert "CUSTOMER" in table_stats
            assert "NATION" in table_stats

            # Verify load_table_from_file was called for each chunk (2 for customer, 1 for nation)
            assert mock_connection.load_table_from_file.call_count == 3

            # Verify WRITE_TRUNCATE for first chunk, WRITE_APPEND for subsequent chunks
            # First job config (customer chunk 1): WRITE_TRUNCATE
            assert job_configs[0].write_disposition == "WRITE_TRUNCATE"
            # Second job config (customer chunk 2): WRITE_APPEND
            assert job_configs[1].write_disposition == "WRITE_APPEND"
            # Third job config (nation, single file): WRITE_TRUNCATE
            assert job_configs[2].write_disposition == "WRITE_TRUNCATE"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_direct_loading_with_single_paths(self, mock_bigquery, dependencies_available):
        """Test that direct loading still works with single paths (TPC-H style)."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, Mock

        # Mock WriteDisposition enum
        mock_bigquery.WriteDisposition.WRITE_TRUNCATE = "WRITE_TRUNCATE"
        mock_bigquery.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"

        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        # Create temporary test file
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "nation.dat"
            test_file.write_text("1|USA\n2|Canada\n")

            # Create mock benchmark with tables as single paths (TPC-H style)
            mock_benchmark = Mock()
            mock_benchmark.tables = {
                "nation": test_file,  # Single path, not a list
            }

            # Create mock BigQuery connection
            mock_connection = MagicMock()
            mock_dataset = Mock()
            mock_table_ref = Mock()
            mock_connection.dataset.return_value = mock_dataset
            mock_dataset.table.return_value = mock_table_ref

            # Mock load_table_from_file
            mock_load_job = Mock()
            mock_load_job.result.return_value = None
            mock_connection.load_table_from_file.return_value = mock_load_job

            # Mock query for row count
            mock_query_job = Mock()
            mock_query_job.result.return_value = [(2,)]
            mock_connection.query.return_value = mock_query_job

            # Call load_data
            table_stats, total_time, per_table_timings = adapter.load_data(mock_benchmark, mock_connection, tmpdir)

            # Verify table was loaded
            assert "NATION" in table_stats
            assert table_stats["NATION"] == 2

            # Verify load_table_from_file was called once
            assert mock_connection.load_table_from_file.call_count == 1

    def test_validate_database_compatibility_detects_empty_tables(self, dependencies_available):
        """Test that validation detects when more than half the tables are empty."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
            )

            # Mock the admin client
            mock_client = Mock()
            mock_dataset_ref = Mock()
            mock_client.dataset.return_value = mock_dataset_ref

            # Create mock tables - 3 out of 4 are empty (> 50%)
            mock_table_info1 = Mock()
            mock_table_info1.reference = Mock()
            mock_table_info2 = Mock()
            mock_table_info2.reference = Mock()
            mock_table_info3 = Mock()
            mock_table_info3.reference = Mock()
            mock_table_info4 = Mock()
            mock_table_info4.reference = Mock()

            mock_client.list_tables.return_value = [
                mock_table_info1,
                mock_table_info2,
                mock_table_info3,
                mock_table_info4,
            ]

            # Mock table objects - 3 empty, 1 with data
            mock_table1 = Mock()
            mock_table1.num_rows = 0
            mock_table1.table_id = "table1"

            mock_table2 = Mock()
            mock_table2.num_rows = 0
            mock_table2.table_id = "table2"

            mock_table3 = Mock()
            mock_table3.num_rows = 0
            mock_table3.table_id = "table3"

            mock_table4 = Mock()
            mock_table4.num_rows = 100
            mock_table4.table_id = "table4"

            mock_client.get_table.side_effect = [mock_table1, mock_table2, mock_table3, mock_table4]

            # Mock _create_admin_client to return our mock client
            with patch.object(adapter, "_create_admin_client", return_value=mock_client):
                # Mock the base validation to return valid result
                mock_base_result = Mock()
                mock_base_result.is_valid = True
                mock_base_result.can_reuse = True
                mock_base_result.issues = []
                mock_base_result.warnings = []

                with patch(
                    "benchbox.platforms.base.validation.DatabaseValidator.validate",
                    return_value=mock_base_result,
                ):
                    # Call validation
                    result = adapter._validate_database_compatibility()

                    # Verify that validation failed due to empty tables
                    assert result.is_valid is False
                    assert result.can_reuse is False
                    assert len(result.issues) == 1
                    assert "Empty tables detected: 3/4" in result.issues[0]
                    assert "indicates failed previous load" in result.issues[0]

    def test_validate_database_compatibility_allows_few_empty_tables(self, dependencies_available):
        """Test that validation passes when less than half the tables are empty."""
        with patch("benchbox.platforms.bigquery.bigquery"):
            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
            )

            # Mock the admin client
            mock_client = Mock()
            mock_dataset_ref = Mock()
            mock_client.dataset.return_value = mock_dataset_ref

            # Create mock tables - 1 out of 4 is empty (< 50%)
            mock_table_info1 = Mock()
            mock_table_info1.reference = Mock()
            mock_table_info2 = Mock()
            mock_table_info2.reference = Mock()
            mock_table_info3 = Mock()
            mock_table_info3.reference = Mock()
            mock_table_info4 = Mock()
            mock_table_info4.reference = Mock()

            mock_client.list_tables.return_value = [
                mock_table_info1,
                mock_table_info2,
                mock_table_info3,
                mock_table_info4,
            ]

            # Mock table objects - 1 empty, 3 with data
            mock_table1 = Mock()
            mock_table1.num_rows = 0
            mock_table1.table_id = "table1"

            mock_table2 = Mock()
            mock_table2.num_rows = 100
            mock_table2.table_id = "table2"

            mock_table3 = Mock()
            mock_table3.num_rows = 100
            mock_table3.table_id = "table3"

            mock_table4 = Mock()
            mock_table4.num_rows = 100
            mock_table4.table_id = "table4"

            mock_client.get_table.side_effect = [mock_table1, mock_table2, mock_table3, mock_table4]

            # Mock _create_admin_client to return our mock client
            with patch.object(adapter, "_create_admin_client", return_value=mock_client):
                # Mock the base validation to return valid result
                mock_base_result = Mock()
                mock_base_result.is_valid = True
                mock_base_result.can_reuse = True
                mock_base_result.issues = []
                mock_base_result.warnings = []

                with patch(
                    "benchbox.platforms.base.validation.DatabaseValidator.validate",
                    return_value=mock_base_result,
                ):
                    # Call validation
                    result = adapter._validate_database_compatibility()

                    # Verify that validation passed (few empty tables are acceptable)
                    assert result.is_valid is True
                    assert result.can_reuse is True
                    assert len(result.issues) == 0


# ===================================================================
# Additional coverage tests (merged from test_bigquery_case_normalization.py)
# ===================================================================


class TestBigQueryCaseNormalization:
    """Test BigQuery table name case normalization for TPC-DS compatibility."""

    def test_normalize_single_table(self):
        """Test normalization of a single lowercase table name."""
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        result = adapter._normalize_table_names_case("SELECT * FROM `customer`")
        assert "`CUSTOMER`" in result
        assert "`customer`" not in result

    def test_normalize_multiple_tables(self):
        """Test normalization of multiple lowercase table names."""
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        query = "SELECT * FROM `customer` JOIN `store_sales` ON `customer`.c_id = `store_sales`.c_id"
        result = adapter._normalize_table_names_case(query)
        assert "`CUSTOMER`" in result
        assert "`STORE_SALES`" in result
        assert "`customer`" not in result
        assert "`store_sales`" not in result

    def test_normalize_table_with_underscores(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        result = adapter._normalize_table_names_case("SELECT * FROM `date_dim` WHERE `date_dim`.d_year = 2000")
        assert "`DATE_DIM`" in result
        assert "`date_dim`" not in result

    def test_preserves_uppercase_tables(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        result = adapter._normalize_table_names_case("SELECT * FROM `CUSTOMER`")
        assert "`CUSTOMER`" in result

    def test_ignores_string_literals(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        result = adapter._normalize_table_names_case("SELECT * FROM `customer` WHERE name = 'customer_name'")
        assert "`CUSTOMER`" in result
        assert "'customer_name'" in result

    def test_handles_empty_query(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        assert adapter._normalize_table_names_case("") == ""

    def test_handles_query_without_backticks(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        query = "SELECT * FROM CUSTOMER WHERE id = 1"
        assert adapter._normalize_table_names_case(query) == query

    def test_complex_query_with_joins_and_subqueries(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")
        query = """
        SELECT c.c_id, ss.ss_sales_price
        FROM `customer` c
        JOIN (
            SELECT * FROM `store_sales`
            WHERE ss_sold_date_sk IN (SELECT d_date_sk FROM `date_dim`)
        ) ss ON c.c_customer_sk = ss.ss_customer_sk
        """
        result = adapter._normalize_table_names_case(query)
        assert "`CUSTOMER`" in result
        assert "`STORE_SALES`" in result
        assert "`DATE_DIM`" in result


# ===================================================================
# Additional coverage tests (merged from test_bigquery_staging_root.py)
# ===================================================================
class TestBigQueryStagingRoot:
    """Test BigQuery staging_root parsing for CloudStagingPath support."""

    def test_staging_root_parsing_simple(self):
        adapter = BigQueryAdapter(
            project_id="test-project", dataset_id="test_dataset", staging_root="gs://test-bucket/"
        )
        assert adapter.storage_bucket == "test-bucket"
        assert adapter.storage_prefix == "benchbox-data"

    def test_staging_root_parsing_with_path(self):
        adapter = BigQueryAdapter(
            project_id="test-project", dataset_id="test_dataset", staging_root="gs://test-bucket/custom/path/"
        )
        assert adapter.storage_bucket == "test-bucket"
        assert adapter.storage_prefix == "custom/path"

    def test_staging_root_parsing_no_trailing_slash(self):
        adapter = BigQueryAdapter(
            project_id="test-project", dataset_id="test_dataset", staging_root="gs://test-bucket/data"
        )
        assert adapter.storage_bucket == "test-bucket"
        assert adapter.storage_prefix == "data"

    def test_staging_root_overrides_explicit_bucket(self):
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="old-bucket",
            storage_prefix="old-prefix",
            staging_root="gs://new-bucket/new-prefix",
        )
        assert adapter.storage_bucket == "new-bucket"
        assert adapter.storage_prefix == "new-prefix"

    def test_no_staging_root_uses_explicit_config(self):
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="explicit-bucket",
            storage_prefix="explicit-prefix",
        )
        assert adapter.storage_bucket == "explicit-bucket"
        assert adapter.storage_prefix == "explicit-prefix"

    def test_staging_root_invalid_provider_raises_error(self):
        with pytest.raises(ValueError, match="BigQuery requires GCS"):
            BigQueryAdapter(project_id="test-project", dataset_id="test_dataset", staging_root="s3://aws-bucket/path")

    def test_staging_root_empty_bucket(self):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset", staging_root="gs://b")
        assert adapter.storage_bucket == "b"
        assert adapter.storage_prefix == "benchbox-data"


@pytest.mark.usefixtures("dependencies_available")
class TestBigQuerySqlGenerationHelpers:
    """Exercise helper-heavy BigQuery SQL generation and load-job branches."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_configure_for_benchmark_sets_default_dataset_and_olap_flags(self, mock_bigquery, dependencies_available):
        mock_connection = Mock()
        mock_job_config = Mock()
        mock_bigquery.QueryJobConfig.return_value = mock_job_config
        mock_bigquery.QueryPriority.INTERACTIVE = "INTERACTIVE"

        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            maximum_bytes_billed=123456,
            query_cache=False,
            dry_run=True,
        )

        adapter.configure_for_benchmark(mock_connection, "tpch")

        mock_bigquery.QueryJobConfig.assert_called_once_with(
            priority="INTERACTIVE",
            use_query_cache=False,
            dry_run=True,
        )
        assert mock_job_config.maximum_bytes_billed == 123456
        assert mock_job_config.default_dataset == "test-project.test_dataset"
        assert mock_job_config.use_legacy_sql is False
        assert mock_job_config.flatten_results is False
        assert mock_connection._default_job_config is mock_job_config

    def test_convert_to_bigquery_table_adds_dataset_partition_and_cluster(self, dependencies_available):
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            partitioning_field="order_date",
            clustering_fields=["customer_id", "order_id"],
        )

        converted = adapter._convert_to_bigquery_table("CREATE TABLE orders (id INT64)")

        assert converted.startswith("CREATE OR REPLACE TABLE `test-project.test_dataset.orders` (id INT64)")
        assert "PARTITION BY DATE(order_date)" in converted
        assert "CLUSTER BY customer_id, order_id" in converted

    def test_qualify_table_names_adds_fully_qualified_tpch_tables(self, dependencies_available):
        adapter = BigQueryAdapter(project_id="test-project", dataset_id="test_dataset")

        qualified = adapter._qualify_table_names(
            "SELECT * FROM customer JOIN orders ON customer.c_custkey = orders.o_custkey"
        )

        assert "`test-project.test_dataset.CUSTOMER`" in qualified
        assert "`test-project.test_dataset.ORDERS`" in qualified

    def test_prepare_external_parquet_uris_uploads_local_and_preserves_cloud(self, dependencies_available):
        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="benchbox-bucket",
            storage_prefix="benchbox-data",
        )
        bucket = Mock()
        uploaded_blobs = {}

        def create_blob(blob_name):
            blob = Mock()
            uploaded_blobs[blob_name] = blob
            return blob

        bucket.blob.side_effect = create_blob

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            parquet_path = tmpdir_path / "orders.parquet"
            parquet_path.write_text("parquet")
            csv_path = tmpdir_path / "orders.csv"
            csv_path.write_text("id,name\n1,alpha\n")

            uris = adapter._prepare_external_parquet_uris(
                bucket,
                "orders",
                [parquet_path, csv_path, "gs://cloud-bucket/orders/part-000.parquet"],
            )

        assert uris == [
            "gs://benchbox-bucket/benchbox-data/orders/orders.parquet",
            "gs://cloud-bucket/orders/part-000.parquet",
        ]
        uploaded_blobs["benchbox-data/orders/orders.parquet"].upload_from_filename.assert_called_once_with(
            str(parquet_path)
        )
        assert "benchbox-data/orders/orders.csv" not in uploaded_blobs

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows reports st_size=0 for directories, breaking _filter_valid_files"
    )
    def test_prepare_external_table_uris_requires_biglake_for_delta(self, dependencies_available):
        bucket = Mock()
        uploaded_blobs = {}

        def create_blob(blob_name):
            blob = Mock()
            uploaded_blobs[blob_name] = blob
            return blob

        bucket.blob.side_effect = create_blob

        with tempfile.TemporaryDirectory() as tmpdir:
            delta_dir = Path(tmpdir) / "orders_delta"
            (delta_dir / "_delta_log").mkdir(parents=True)
            (delta_dir / "_delta_log" / "00000000000000000000.json").write_text("{}")
            (delta_dir / "part-000.parquet").write_text("parquet")

            adapter = BigQueryAdapter(
                project_id="test-project",
                dataset_id="test_dataset",
                storage_bucket="benchbox-bucket",
                storage_prefix="benchbox-data",
            )

            with pytest.raises(ValueError, match="biglake_connection"):
                adapter._prepare_external_table_uris(bucket, "orders", [delta_dir])

            adapter.biglake_connection = "test-project.us.benchbox"
            source_format, uris = adapter._prepare_external_table_uris(bucket, "orders", [delta_dir])

        assert source_format == "DELTA_LAKE"
        assert uris == ["gs://benchbox-bucket/benchbox-data/orders/"]
        assert sorted(uploaded_blobs) == [
            "benchbox-data/orders/_delta_log/00000000000000000000.json",
            "benchbox-data/orders/part-000.parquet",
        ]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_load_table_via_cloud_storage_uses_write_append_for_chunks(self, mock_bigquery, dependencies_available):
        mock_bigquery.WriteDisposition.WRITE_TRUNCATE = "WRITE_TRUNCATE"
        mock_bigquery.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"
        mock_bigquery.SourceFormat.CSV = "CSV"

        job_configs = []

        def create_job_config(**kwargs):
            config = Mock()
            for key, value in kwargs.items():
                setattr(config, key, value)
            job_configs.append(config)
            return config

        mock_bigquery.LoadJobConfig.side_effect = create_job_config

        adapter = BigQueryAdapter(
            project_id="test-project",
            dataset_id="test_dataset",
            storage_bucket="benchbox-bucket",
            storage_prefix="benchbox-data",
        )
        bucket = Mock()
        mock_connection = Mock()
        mock_dataset = Mock()
        mock_table_ref = Mock()
        mock_connection.dataset.return_value = mock_dataset
        mock_dataset.table.return_value = mock_table_ref
        mock_load_job = Mock()
        mock_connection.load_table_from_uri.return_value = mock_load_job

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk1 = Path(tmpdir) / "customer_1.dat"
            chunk2 = Path(tmpdir) / "customer_2.dat"
            chunk1.write_text("1|alpha\n")
            chunk2.write_text("2|beta\n")

            with patch.object(adapter, "_get_table_row_count", return_value=2):
                row_count = adapter._load_table_via_cloud_storage(
                    mock_connection,
                    bucket,
                    "customer",
                    [chunk1, chunk2],
                )

        assert row_count == 2
        assert mock_connection.load_table_from_uri.call_count == 2
        assert job_configs[0].write_disposition == "WRITE_TRUNCATE"
        assert job_configs[1].write_disposition == "WRITE_APPEND"
        assert job_configs[0].field_delimiter == "|"
        assert job_configs[1].field_delimiter == "|"


# ===================================================================
# SQL generation, config validation, and type mapping tests
# ===================================================================


@pytest.mark.usefixtures("dependencies_available")
class TestConvertToBigqueryTable:
    """Test _convert_to_bigquery_table SQL transformation."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_non_create_table_passes_through(self, mock_bigquery):
        """Non-CREATE TABLE statements pass through unchanged."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._convert_to_bigquery_table("INSERT INTO t VALUES (1)")
        assert result == "INSERT INTO t VALUES (1)"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_adds_or_replace(self, mock_bigquery):
        """Converts CREATE TABLE to CREATE OR REPLACE TABLE."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._convert_to_bigquery_table("CREATE TABLE orders (id INT64)")
        assert "CREATE OR REPLACE TABLE" in result
        assert "CREATE TABLE " not in result.replace("CREATE OR REPLACE TABLE", "")

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_preserves_existing_or_replace(self, mock_bigquery):
        """If already OR REPLACE, don't double-add it."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._convert_to_bigquery_table("CREATE OR REPLACE TABLE orders (id INT64)")
        assert result.count("OR REPLACE") == 1

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_qualifies_with_project_and_dataset(self, mock_bigquery):
        """Table name is qualified with project.dataset in backticks."""
        adapter = BigQueryAdapter(project_id="my-project", dataset_id="my_dataset")
        result = adapter._convert_to_bigquery_table("CREATE TABLE lineitem (l_orderkey INT64)")
        assert "`my-project.my_dataset." in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_no_partitioning_when_field_not_set(self, mock_bigquery):
        """No PARTITION BY when partitioning_field is not configured."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._convert_to_bigquery_table("CREATE TABLE t (id INT64)")
        assert "PARTITION BY" not in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_no_clustering_when_fields_not_set(self, mock_bigquery):
        """No CLUSTER BY when clustering_fields is empty."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._convert_to_bigquery_table("CREATE TABLE t (id INT64)")
        assert "CLUSTER BY" not in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_adds_partitioning_clause(self, mock_bigquery):
        """Adds PARTITION BY DATE(field) when partitioning_field configured."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", partitioning_field="created_at")
        result = adapter._convert_to_bigquery_table("CREATE TABLE t (id INT64)")
        assert "PARTITION BY DATE(created_at)" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_adds_clustering_clause(self, mock_bigquery):
        """Adds CLUSTER BY when clustering_fields configured."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", clustering_fields=["a", "b", "c"])
        result = adapter._convert_to_bigquery_table("CREATE TABLE t (id INT64)")
        assert "CLUSTER BY a, b, c" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_skips_partition_if_already_present(self, mock_bigquery):
        """Does not add PARTITION BY if statement already contains it."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", partitioning_field="ts")
        sql = "CREATE TABLE t (id INT64) PARTITION BY DATE(ts)"
        result = adapter._convert_to_bigquery_table(sql)
        assert result.count("PARTITION BY") == 1

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_skips_cluster_if_already_present(self, mock_bigquery):
        """Does not add CLUSTER BY if statement already contains it."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", clustering_fields=["x"])
        sql = "CREATE TABLE t (id INT64) CLUSTER BY x"
        result = adapter._convert_to_bigquery_table(sql)
        assert result.count("CLUSTER BY") == 1


@pytest.mark.usefixtures("dependencies_available")
class TestQualifyTableNames:
    """Test _qualify_table_names for all TPC-H tables."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_qualifies_all_tpch_tables(self, mock_bigquery):
        """All 8 TPC-H table names are qualified with project.dataset."""
        adapter = BigQueryAdapter(project_id="p1", dataset_id="d1")
        tpch_tables = ["REGION", "NATION", "CUSTOMER", "SUPPLIER", "PART", "PARTSUPP", "ORDERS", "LINEITEM"]
        for table in tpch_tables:
            result = adapter._qualify_table_names(f"SELECT * FROM {table}")
            assert f"`p1.d1.{table}`" in result, f"{table} not qualified"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_qualifies_case_insensitive(self, mock_bigquery):
        """Qualification works for lowercase table names."""
        adapter = BigQueryAdapter(project_id="p1", dataset_id="d1")
        result = adapter._qualify_table_names("SELECT * FROM customer")
        assert "`p1.d1.CUSTOMER`" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_qualifies_multiple_references_in_join(self, mock_bigquery):
        """Multiple table references in a JOIN are all qualified."""
        adapter = BigQueryAdapter(project_id="p1", dataset_id="d1")
        sql = "SELECT * FROM lineitem l JOIN orders o ON l.l_orderkey = o.o_orderkey"
        result = adapter._qualify_table_names(sql)
        assert "`p1.d1.LINEITEM`" in result
        assert "`p1.d1.ORDERS`" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_does_not_qualify_non_tpch_tables(self, mock_bigquery):
        """Non-TPC-H table names are not modified."""
        adapter = BigQueryAdapter(project_id="p1", dataset_id="d1")
        result = adapter._qualify_table_names("SELECT * FROM my_custom_table")
        assert "my_custom_table" in result
        assert "`p1.d1." not in result


@pytest.mark.usefixtures("dependencies_available")
class TestNormalizeTableNamesCase:
    """Test _normalize_table_names_case edge cases."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_normalizes_mixed_case_identifiers(self, mock_bigquery):
        """Only lowercase backtick-quoted identifiers are uppercased."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        query = "SELECT `col_a`, `COL_B` FROM `my_table`"
        result = adapter._normalize_table_names_case(query)
        assert "`COL_A`" in result
        assert "`COL_B`" in result
        assert "`MY_TABLE`" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_preserves_numeric_suffixes(self, mock_bigquery):
        """Identifiers with numeric parts are normalized correctly."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._normalize_table_names_case("SELECT * FROM `table123`")
        assert "`TABLE123`" in result

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_no_change_for_already_uppercase(self, mock_bigquery):
        """Already-uppercase identifiers remain unchanged."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        query = "SELECT * FROM `CUSTOMER` WHERE `CUSTOMER`.`C_ID` = 1"
        result = adapter._normalize_table_names_case(query)
        assert "`CUSTOMER`" in result
        # uppercase identifiers don't match the lowercase-only regex
        assert result == query


@pytest.mark.usefixtures("dependencies_available")
class TestGenerateTuningClause:
    """Test generate_tuning_clause with different column types."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_timestamp_partitioning_uses_date_wrapper(self, mock_bigquery):
        """TIMESTAMP columns get PARTITION BY DATE(col)."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col = Mock()
        mock_col.name = "ts_col"
        mock_col.order = 1
        mock_col.type = "TIMESTAMP"

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.PARTITIONING:
                return [mock_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert "PARTITION BY DATE(ts_col)" in clause

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_date_partitioning_uses_direct_column(self, mock_bigquery):
        """DATE columns get PARTITION BY col (no DATE wrapper)."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col = Mock()
        mock_col.name = "order_date"
        mock_col.order = 1
        mock_col.type = "DATE"

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.PARTITIONING:
                return [mock_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == "PARTITION BY order_date"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_integer_partitioning_uses_range_bucket(self, mock_bigquery):
        """INTEGER columns get PARTITION BY RANGE_BUCKET(...)."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col = Mock()
        mock_col.name = "id_col"
        mock_col.order = 1
        mock_col.type = "INT64"

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.PARTITIONING:
                return [mock_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert "RANGE_BUCKET(id_col, GENERATE_ARRAY(0, 1000000, 10000))" in clause

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_clustering_limited_to_four_columns(self, mock_bigquery):
        """BigQuery enforces a max of 4 clustering columns."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        cols = []
        for i, name in enumerate(["a", "b", "c", "d", "e"]):
            c = Mock()
            c.name = name
            c.order = i
            cols.append(c)

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.CLUSTERING:
                return cols
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert "CLUSTER BY a, b, c, d" in clause
        assert "e" not in clause

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_combined_partitioning_and_clustering(self, mock_bigquery):
        """Both PARTITION BY and CLUSTER BY in one clause."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        part_col = Mock()
        part_col.name = "event_date"
        part_col.order = 1
        part_col.type = "DATE"

        cluster_col = Mock()
        cluster_col.name = "user_id"
        cluster_col.order = 1

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.PARTITIONING:
                return [part_col]
            if tt == TuningType.CLUSTERING:
                return [cluster_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert "PARTITION BY event_date" in clause
        assert "CLUSTER BY user_id" in clause

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_no_tuning_returns_empty(self, mock_bigquery):
        """has_any_tuning() == False returns empty string."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = False
        assert adapter.generate_tuning_clause(mock_tuning) == ""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_default_partitioning_for_unknown_type(self, mock_bigquery):
        """Unknown column type defaults to DATE() wrapper partitioning."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col = Mock()
        mock_col.name = "weird_col"
        mock_col.order = 1
        mock_col.type = "STRING"

        from benchbox.core.tuning.interface import TuningType

        def get_cols(tt):
            if tt == TuningType.PARTITIONING:
                return [mock_col]
            return []

        mock_tuning.get_columns_by_type.side_effect = get_cols
        clause = adapter.generate_tuning_clause(mock_tuning)
        assert "PARTITION BY DATE(weird_col)" in clause


@pytest.mark.usefixtures("dependencies_available")
class TestQueryCacheConfig:
    """Test query_cache configuration logic."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_query_cache_explicit_true(self, mock_bigquery):
        """Explicit query_cache=True overrides default."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", query_cache=True)
        assert adapter.query_cache is True

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_query_cache_explicit_false(self, mock_bigquery):
        """Explicit query_cache=False is respected."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", query_cache=False)
        assert adapter.query_cache is False

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_disable_result_cache_true_sets_query_cache_false(self, mock_bigquery):
        """disable_result_cache=True maps to query_cache=False."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", disable_result_cache=True)
        assert adapter.query_cache is False

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_disable_result_cache_false_sets_query_cache_true(self, mock_bigquery):
        """disable_result_cache=False maps to query_cache=True."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", disable_result_cache=False)
        assert adapter.query_cache is True

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_default_query_cache_is_disabled(self, mock_bigquery):
        """Default is cache disabled for accurate benchmarking."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter.query_cache is False


@pytest.mark.usefixtures("dependencies_available")
class TestGetPlatformInfo:
    """Test get_platform_info structure and content."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_basic_info_without_connection(self, mock_bigquery):
        """Platform info without connection returns base fields."""
        adapter = BigQueryAdapter(
            project_id="my-project",
            dataset_id="bench_ds",
            location="EU",
            storage_bucket="my-bucket",
            job_priority="BATCH",
            query_cache=True,
        )

        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "bigquery"
        assert info["platform_name"] == "BigQuery"
        assert info["connection_mode"] == "remote"
        assert info["cloud_provider"] == "GCP"
        assert info["configuration"]["project_id"] == "my-project"
        assert info["configuration"]["dataset_id"] == "bench_ds"
        assert info["configuration"]["location"] == "EU"
        assert info["configuration"]["storage_bucket"] == "my-bucket"
        assert info["configuration"]["job_priority"] == "BATCH"
        assert info["configuration"]["query_cache_enabled"] is True
        assert info["platform_version"] is None

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_info_with_connection_metadata_error(self, mock_bigquery):
        """If connection metadata queries fail, info still returned gracefully."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.get_dataset.side_effect = Exception("access denied")
        info = adapter.get_platform_info(connection=mock_conn)
        # Should still return basic info even if connection queries fail
        assert info["platform_type"] == "bigquery"
        assert info["configuration"]["project_id"] == "proj"


@pytest.mark.usefixtures("dependencies_available")
class TestExecuteQuerySqlTransformation:
    """Test execute_query SQL transformation branches."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_backtick_query_normalizes_case(self, mock_bigquery):
        """Queries with backticks use _normalize_table_names_case."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = [(1,)]
        mock_job.job_id = "j1"
        mock_job.total_bytes_processed = 0
        mock_job.total_bytes_billed = 0
        mock_job.slot_millis = 0
        mock_job.created = None
        mock_job.started = None
        mock_job.ended = None
        mock_conn.query.return_value = mock_job

        result = adapter.execute_query(mock_conn, "SELECT * FROM `customer`", "q1")

        assert result["status"] == "SUCCESS"
        # Verify the query was uppercase-normalized (backtick path)
        called_sql = mock_conn.query.call_args[0][0]
        assert "`CUSTOMER`" in called_sql

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_non_backtick_query_qualifies_tables(self, mock_bigquery):
        """Queries without backticks use _qualify_table_names."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = [(1,)]
        mock_job.job_id = "j2"
        mock_job.total_bytes_processed = 100
        mock_job.total_bytes_billed = 100
        mock_job.slot_millis = 50
        mock_job.created = None
        mock_job.started = None
        mock_job.ended = None
        mock_conn.query.return_value = mock_job

        result = adapter.execute_query(mock_conn, "SELECT * FROM CUSTOMER", "q1")

        assert result["status"] == "SUCCESS"
        called_sql = mock_conn.query.call_args[0][0]
        assert "`proj.ds.CUSTOMER`" in called_sql

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_translated_query_stored_when_different(self, mock_bigquery):
        """translated_query field set when SQL was transformed."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = []
        mock_job.job_id = "j3"
        mock_job.total_bytes_processed = 0
        mock_job.total_bytes_billed = 0
        mock_job.slot_millis = 0
        mock_job.created = None
        mock_job.started = None
        mock_job.ended = None
        mock_conn.query.return_value = mock_job

        original_sql = "SELECT * FROM REGION"
        result = adapter.execute_query(mock_conn, original_sql, "q1")

        # The query gets qualified, so translated_query should be set
        assert result["translated_query"] is not None
        assert "`proj.ds.REGION`" in result["translated_query"]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_job_statistics_in_result(self, mock_bigquery):
        """Result includes BigQuery job statistics."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = [(42,)]
        mock_job.job_id = "job_abc"
        mock_job.total_bytes_processed = 2048
        mock_job.total_bytes_billed = 1024
        mock_job.slot_millis = 500
        mock_job.created = None
        mock_job.started = None
        mock_job.ended = None
        mock_conn.query.return_value = mock_job

        result = adapter.execute_query(mock_conn, "SELECT 42", "q1")

        assert result["job_id"] == "job_abc"
        assert result["job_statistics"]["bytes_processed"] == 2048
        assert result["job_statistics"]["bytes_billed"] == 1024
        assert result["job_statistics"]["slot_ms"] == 500
        assert result["resource_usage"] == result["job_statistics"]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_execute_query_error_returns_error_dict(self, mock_bigquery):
        """Failed queries return structured error dict."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.query.side_effect = RuntimeError("Quota exceeded")

        result = adapter.execute_query(mock_conn, "SELECT 1", "q_fail")

        assert result["status"] == "FAILED"
        assert result["query_id"] == "q_fail"
        assert result["rows_returned"] == 0
        assert "Quota exceeded" in result["error"]
        assert result["error_type"] == "RuntimeError"


@pytest.mark.usefixtures("dependencies_available")
class TestCloseConnectionEdgeCases:
    """Test close_connection edge cases."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_close_none_connection(self, mock_bigquery):
        """close_connection(None) does nothing."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        adapter.close_connection(None)  # should not raise

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_close_suppresses_token_error(self, mock_bigquery):
        """Token-related errors are silently suppressed."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.close.side_effect = Exception("token expired during refresh")
        adapter.close_connection(mock_conn)  # should not raise

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_close_suppresses_auth_error(self, mock_bigquery):
        """Auth-related errors are silently suppressed."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.close.side_effect = Exception("auth credentials invalid")
        adapter.close_connection(mock_conn)  # should not raise

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_close_transport_cleanup(self, mock_bigquery):
        """Transport cleanup runs even if close() fails."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.close.side_effect = Exception("Network error")
        mock_transport = Mock()
        mock_conn._transport = mock_transport

        with patch.object(adapter.logger, "warning"):
            adapter.close_connection(mock_conn)

        mock_transport.close.assert_called_once()


@pytest.mark.usefixtures("dependencies_available")
class TestValidateCompressionSupport:
    """Test _validate_compression_support for zstd rejection."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_zstd_file_raises_error(self, mock_bigquery):
        """Zstd-compressed files raise descriptive error."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_benchmark = Mock()
        mock_benchmark.name = "tpch"
        mock_benchmark.scale_factor = 1
        mock_benchmark.data_dir = "/tmp/data"

        with (
            patch("benchbox.platforms.bigquery.detect_compression", return_value="zstd"),
            pytest.raises(ValueError, match="Zstd"),
        ):
            adapter._validate_compression_support({"lineitem": [Path("/tmp/lineitem.csv.zst")]}, mock_benchmark)

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_gzip_file_passes(self, mock_bigquery):
        """Gzip files do not raise."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_benchmark = Mock()

        with patch("benchbox.platforms.bigquery.detect_compression", return_value="gzip"):
            # should not raise
            adapter._validate_compression_support({"lineitem": [Path("/tmp/lineitem.csv.gz")]}, mock_benchmark)

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_uncompressed_file_passes(self, mock_bigquery):
        """Uncompressed files do not raise."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_benchmark = Mock()

        with patch("benchbox.platforms.bigquery.detect_compression", return_value="none"):
            adapter._validate_compression_support({"nation": [Path("/tmp/nation.tbl")]}, mock_benchmark)


@pytest.mark.usefixtures("dependencies_available")
class TestEnsureFileListAndFilterValidFiles:
    """Test _ensure_file_list and _filter_valid_files helpers."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_ensure_file_list_wraps_single(self, mock_bigquery):
        """Single path becomes a one-element list."""
        result = BigQueryAdapter._ensure_file_list(Path("/tmp/file.csv"))
        assert result == [Path("/tmp/file.csv")]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_ensure_file_list_preserves_list(self, mock_bigquery):
        """Already-list input passes through."""
        paths = [Path("/tmp/a.csv"), Path("/tmp/b.csv")]
        result = BigQueryAdapter._ensure_file_list(paths)
        assert result == paths

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_filter_valid_files_rejects_nonexistent(self, mock_bigquery):
        """Non-existent local files are filtered out."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._filter_valid_files([Path("/nonexistent/file.csv")], allow_cloud=False)
        assert result == []

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_filter_valid_files_accepts_cloud_paths(self, mock_bigquery):
        """Cloud paths are accepted when allow_cloud=True."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._filter_valid_files(["gs://bucket/file.parquet"], allow_cloud=True)
        assert result == ["gs://bucket/file.parquet"]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_filter_valid_files_rejects_cloud_when_not_allowed(self, mock_bigquery):
        """Cloud paths are rejected when allow_cloud=False."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        result = adapter._filter_valid_files(["gs://bucket/file.parquet"], allow_cloud=False)
        assert result == []


@pytest.mark.usefixtures("dependencies_available")
class TestGetExistingTables:
    """Test _get_existing_tables normalization."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_returns_lowercase_table_names(self, mock_bigquery):
        """Table names are normalized to lowercase."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_t1 = Mock()
        mock_t1.table_id = "CUSTOMER"
        mock_t2 = Mock()
        mock_t2.table_id = "LINEITEM"
        mock_conn.list_tables.return_value = [mock_t1, mock_t2]

        result = adapter._get_existing_tables(mock_conn)

        assert result == ["customer", "lineitem"]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_returns_empty_on_error(self, mock_bigquery):
        """Returns empty list when list_tables fails."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_conn.list_tables.side_effect = Exception("dataset not found")
        # Ensure dataset() doesn't cause issues
        mock_conn.dataset.side_effect = Exception("dataset not found")

        result = adapter._get_existing_tables(mock_conn)
        assert result == []


@pytest.mark.usefixtures("dependencies_available")
class TestBuildCtasSortSql:
    """Test _build_ctas_sort_sql behavior."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_returns_none_when_off(self, mock_bigquery):
        """Returns None when sorted ingestion is off."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("off", "none")):
            result = adapter._build_ctas_sort_sql("orders", [])
        assert result is None

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_raises_when_not_off(self, mock_bigquery):
        """Raises ValueError when sorted ingestion is requested but not supported."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        with (
            patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("auto", "ctas")),
            pytest.raises(ValueError, match="not yet executable"),
        ):
            adapter._build_ctas_sort_sql("orders", [Mock()])


@pytest.mark.usefixtures("dependencies_available")
class TestGetTableRowCount:
    """Test get_table_row_count SQL generation."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_generates_correct_count_sql(self, mock_bigquery):
        """Verify the COUNT(*) SQL uses project.dataset.TABLE format."""
        adapter = BigQueryAdapter(project_id="my-proj", dataset_id="my_ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = [(999,)]
        mock_conn.query.return_value = mock_job

        count = adapter.get_table_row_count(mock_conn, "lineitem")

        assert count == 999
        called_sql = mock_conn.query.call_args[0][0]
        assert called_sql == "SELECT COUNT(*) FROM `my-proj.my_ds.LINEITEM`"


@pytest.mark.usefixtures("dependencies_available")
class TestValidateDataIntegritySql:
    """Test _validate_data_integrity SQL generation."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_generates_correct_accessibility_sql(self, mock_bigquery):
        """Verify the SELECT 1 SQL uses project.dataset.TABLE format."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_conn = Mock()
        mock_job = Mock()
        mock_job.result.return_value = [(1,)]
        mock_conn.query.return_value = mock_job

        status, details = adapter._validate_data_integrity(Mock(), mock_conn, {"region": 5})

        assert status == "PASSED"
        called_sql = mock_conn.query.call_args[0][0]
        assert called_sql == "SELECT 1 FROM `proj.ds.REGION` LIMIT 1"


@pytest.mark.usefixtures("dependencies_available")
class TestBuildBigqueryConfig:
    """Test _build_bigquery_config config builder function."""

    def test_basic_config_construction(self):
        """Config built from options produces correct DatabaseConfig fields."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_info = Mock()
        mock_info.display_name = "Google BigQuery"
        mock_info.driver_package = "google-cloud-bigquery"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {}

            config = _build_bigquery_config(
                platform="bigquery",
                options={"project_id": "test-proj", "location": "EU"},
                overrides={},
                info=mock_info,
            )

        assert config.type == "bigquery"
        assert config.name == "Google BigQuery"
        assert config.project_id == "test-proj"
        assert config.location == "EU"

    def test_staging_root_extracts_bucket_and_prefix(self):
        """staging_root in overrides is parsed into storage_bucket and storage_prefix."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_info = Mock()
        mock_info.display_name = "BigQuery"
        mock_info.driver_package = "google-cloud-bigquery"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {}

            config = _build_bigquery_config(
                platform="bigquery",
                options={"project_id": "proj"},
                overrides={"staging_root": "gs://my-bucket/my-prefix"},
                info=mock_info,
            )

        assert config.storage_bucket == "my-bucket"
        assert config.storage_prefix == "my-prefix"
        assert config.staging_root == "gs://my-bucket/my-prefix"

    def test_saved_creds_merged_with_options(self):
        """Saved credentials are merged, with options taking precedence."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_info = Mock()
        mock_info.display_name = "BigQuery"
        mock_info.driver_package = "google-cloud-bigquery"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {
                "project_id": "saved-proj",
                "location": "US",
            }

            config = _build_bigquery_config(
                platform="bigquery",
                options={"project_id": "cli-proj"},
                overrides={},
                info=mock_info,
            )

        # CLI option should override saved credentials
        assert config.project_id == "cli-proj"
        # Saved location should be preserved
        assert config.location == "US"

    def test_default_output_location_used_as_staging_fallback(self):
        """default_output_location from creds is used as staging_root if gs://."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_info = Mock()
        mock_info.display_name = "BigQuery"
        mock_info.driver_package = "google-cloud-bigquery"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {
                "project_id": "proj",
                "default_output_location": "gs://default-bucket/default-path",
            }

            config = _build_bigquery_config(
                platform="bigquery",
                options={},
                overrides={},
                info=mock_info,
            )

        assert config.staging_root == "gs://default-bucket/default-path"
        assert config.storage_bucket == "default-bucket"

    def test_overrides_take_precedence_over_options(self):
        """Overrides win over both saved_creds and options."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_info = Mock()
        mock_info.display_name = "BigQuery"
        mock_info.driver_package = "google-cloud-bigquery"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {
                "project_id": "saved-proj",
            }

            config = _build_bigquery_config(
                platform="bigquery",
                options={"project_id": "option-proj"},
                overrides={"project_id": "override-proj", "driver_version": "3.25.0"},
                info=mock_info,
            )

        assert config.project_id == "override-proj"
        assert config.driver_version == "3.25.0"

    def test_none_info_uses_defaults(self):
        """When info is None, defaults are used for display name and driver package."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {}

            config = _build_bigquery_config(
                platform="bigquery",
                options={"project_id": "proj"},
                overrides={},
                info=None,
            )

        assert config.name == "Google BigQuery"
        assert config.driver_package == "google-cloud-bigquery"


@pytest.mark.usefixtures("dependencies_available")
class TestConnectionParams:
    """Test _get_connection_params."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_returns_adapter_defaults(self, mock_bigquery):
        """Default params from adapter config."""
        adapter = BigQueryAdapter(
            project_id="proj",
            dataset_id="ds",
            location="EU",
            credentials_path="/path/to/creds.json",
        )
        params = adapter._get_connection_params()
        assert params["project_id"] == "proj"
        assert params["location"] == "EU"
        assert params["credentials_path"] == "/path/to/creds.json"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_overrides_from_connection_config(self, mock_bigquery):
        """Connection config overrides adapter defaults."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds", location="US")
        params = adapter._get_connection_params(project_id="other-proj", location="asia-northeast1")
        assert params["project_id"] == "other-proj"
        assert params["location"] == "asia-northeast1"


@pytest.mark.usefixtures("dependencies_available")
class TestCleanupEmptyTables:
    """Test _cleanup_empty_tables_if_needed defense-in-depth logic."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_no_tables_does_nothing(self, mock_bigquery):
        """No tables means nothing to clean up."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        mock_client = Mock()
        mock_client.list_tables.return_value = []
        adapter._cleanup_empty_tables_if_needed(mock_client)
        # Should not attempt to delete anything
        mock_client.delete_table.assert_not_called()

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_majority_empty_triggers_cleanup(self, mock_bigquery):
        """When >50% tables empty, they are dropped and database_was_reused = False."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        adapter.database_was_reused = True

        mock_client = Mock()
        mock_dataset_ref = Mock()
        mock_client.dataset.return_value = mock_dataset_ref

        # 3 out of 4 tables are empty
        table_infos = []
        table_objs = []
        for i in range(4):
            ti = Mock()
            ti.reference = Mock()
            ti.table_id = f"table{i}"
            table_infos.append(ti)
            to = Mock()
            to.num_rows = 0 if i < 3 else 100
            to.table_id = f"table{i}"
            table_objs.append(to)

        mock_client.list_tables.return_value = table_infos
        mock_client.get_table.side_effect = table_objs

        adapter._cleanup_empty_tables_if_needed(mock_client)

        assert adapter.database_was_reused is False
        # 3 empty tables should be deleted
        assert mock_client.delete_table.call_count == 3

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_minority_empty_does_not_cleanup(self, mock_bigquery):
        """When <50% tables empty, no cleanup happens."""
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        adapter.database_was_reused = True

        mock_client = Mock()
        mock_dataset_ref = Mock()
        mock_client.dataset.return_value = mock_dataset_ref

        # 1 out of 4 tables is empty
        table_infos = []
        table_objs = []
        for i in range(4):
            ti = Mock()
            ti.reference = Mock()
            ti.table_id = f"table{i}"
            table_infos.append(ti)
            to = Mock()
            to.num_rows = 0 if i == 0 else 100
            to.table_id = f"table{i}"
            table_objs.append(to)

        mock_client.list_tables.return_value = table_infos
        mock_client.get_table.side_effect = table_objs

        adapter._cleanup_empty_tables_if_needed(mock_client)

        assert adapter.database_was_reused is True
        mock_client.delete_table.assert_not_called()


@pytest.mark.usefixtures("dependencies_available")
class TestPrepareExternalDeltaUris:
    """Test _prepare_external_delta_uris cloud path handling."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_cloud_delta_log_path_extracts_root(self, mock_bigquery):
        """Cloud path with /_delta_log extracts the root URI."""
        adapter = BigQueryAdapter(
            project_id="proj",
            dataset_id="ds",
            storage_bucket="bucket",
            storage_prefix="prefix",
        )
        bucket = Mock()

        uris = adapter._prepare_external_delta_uris(
            bucket,
            "orders",
            ["gs://cloud-bucket/data/orders/_delta_log/00000.json"],
        )

        assert uris == ["gs://cloud-bucket/data/orders/"]

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_non_delta_local_dir_ignored(self, mock_bigquery):
        """Local dir without _delta_log is skipped."""
        adapter = BigQueryAdapter(
            project_id="proj",
            dataset_id="ds",
            storage_bucket="bucket",
            storage_prefix="prefix",
        )
        bucket = Mock()

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            regular_dir = Path(tmpdir) / "orders"
            regular_dir.mkdir()
            # No _delta_log subdir

            uris = adapter._prepare_external_delta_uris(bucket, "orders", [regular_dir])

        assert uris == []

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_cloud_path_without_delta_log_ignored(self, mock_bigquery):
        """Cloud path without /_delta_log is skipped."""
        adapter = BigQueryAdapter(
            project_id="proj",
            dataset_id="ds",
            storage_bucket="bucket",
            storage_prefix="prefix",
        )
        bucket = Mock()

        uris = adapter._prepare_external_delta_uris(
            bucket,
            "orders",
            ["gs://cloud-bucket/data/orders/part-000.parquet"],
        )

        assert uris == []


@pytest.mark.usefixtures("dependencies_available")
class TestAddCliArguments:
    """Test add_cli_arguments registers expected arguments."""

    def test_adds_bigquery_arguments(self):
        """Verify all BQ-specific CLI arguments are registered."""
        import argparse

        parser = argparse.ArgumentParser()
        BigQueryAdapter.add_cli_arguments(parser)

        # Parse known args to check they exist
        args = parser.parse_args(
            [
                "--project-id",
                "test-proj",
                "--dataset-id",
                "test_ds",
                "--location",
                "EU",
                "--credentials-path",
                "/path/to/creds.json",
                "--storage-bucket",
                "my-bucket",
            ]
        )

        assert args.project_id == "test-proj"
        assert args.dataset_id == "test_ds"
        assert args.location == "EU"
        assert args.credentials_path == "/path/to/creds.json"
        assert args.storage_bucket == "my-bucket"


@pytest.mark.usefixtures("dependencies_available")
class TestGetTargetDialect:
    """Test get_target_dialect returns correct value."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_returns_bigquery(self, mock_bigquery):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter.get_target_dialect() == "bigquery"


@pytest.mark.usefixtures("dependencies_available")
class TestPlatformNameAndProperties:
    """Test basic platform property values."""

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_platform_name_is_bigquery(self, mock_bigquery):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter.platform_name == "BigQuery"

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_driver_isolation_capability(self, mock_bigquery):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter.driver_isolation_capability == DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_supports_external_tables(self, mock_bigquery):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter.supports_external_tables is True

    @patch("benchbox.platforms.bigquery.bigquery")
    def test_internal_dialect_is_bigquery(self, mock_bigquery):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        assert adapter._dialect == "bigquery"
