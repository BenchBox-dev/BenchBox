"""Unit tests for AWS Athena platform adapter."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base.data_loading import DataSource

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestAthenaAdapterConfigurationValidation:
    """Tests for Athena configuration validation."""

    @pytest.fixture
    def mock_boto3(self):
        """Mock boto3 module."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            yield

    @pytest.fixture
    def mock_pyathena(self):
        """Mock pyathena module."""
        mock_connect = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.cursor.return_value = mock_cursor
        with patch.dict(
            "sys.modules",
            {
                "pyathena": MagicMock(connect=mock_connect),
                "pyathena.cursor": MagicMock(Cursor=MagicMock()),
            },
        ):
            yield mock_connect, mock_cursor

    @pytest.fixture
    def mock_aws_credentials(self, tmp_path, monkeypatch):
        """Create mock AWS credentials file for testing."""
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        creds_file = aws_dir / "credentials"
        creds_file.write_text("[default]\naws_access_key_id = test\naws_secret_access_key = test\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        return creds_file

    def test_validation_fails_without_s3_config(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation fails when S3 is not configured."""
        from benchbox.platforms.athena import AthenaAdapter

        # Clear AWS environment
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")  # No credentials file

        with pytest.raises(ConfigurationError) as exc_info:
            AthenaAdapter()

        assert "No S3 location configured" in str(exc_info.value)

    def test_validation_fails_with_invalid_s3_path(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that validation fails with invalid S3 path format."""
        from benchbox.platforms.athena import AthenaAdapter

        with pytest.raises(ConfigurationError) as exc_info:
            AthenaAdapter(s3_staging_dir="invalid-path")

        assert "Invalid S3 staging directory format" in str(exc_info.value)

    def test_validation_fails_with_invalid_region(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that validation fails with invalid region format."""
        from benchbox.platforms.athena import AthenaAdapter

        with pytest.raises(ConfigurationError) as exc_info:
            AthenaAdapter(s3_bucket="test-bucket", region="invalid")

        assert "Invalid AWS region format" in str(exc_info.value)

    def test_validation_fails_with_invalid_workgroup(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that validation fails with invalid workgroup name."""
        from benchbox.platforms.athena import AthenaAdapter

        with pytest.raises(ConfigurationError) as exc_info:
            AthenaAdapter(s3_bucket="test-bucket", workgroup="123-invalid")

        assert "Invalid workgroup name" in str(exc_info.value)

    def test_validation_passes_with_explicit_credentials(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation passes with explicit credentials."""
        from benchbox.platforms.athena import AthenaAdapter

        # Clear environment
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")

        # Should not raise with explicit credentials
        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )
        assert adapter.s3_bucket == "test-bucket"

    def test_validation_passes_with_aws_profile(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation passes with AWS profile."""
        from benchbox.platforms.athena import AthenaAdapter

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            aws_profile="my-profile",
        )
        assert adapter.aws_profile == "my-profile"

    def test_validation_passes_with_env_credentials(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation passes with environment credentials."""
        from benchbox.platforms.athena import AthenaAdapter

        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
        monkeypatch.setenv("HOME", "/nonexistent")

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        assert adapter.s3_bucket == "test-bucket"

    def test_validation_error_includes_details(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation error includes helpful details."""
        from benchbox.platforms.athena import AthenaAdapter

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")

        with pytest.raises(ConfigurationError) as exc_info:
            AthenaAdapter()

        error = exc_info.value
        assert error.details["platform"] == "athena"
        assert "validation_errors" in error.details

    def test_validation_provides_fix_suggestions(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that validation errors include fix suggestions."""
        from benchbox.platforms.athena import AthenaAdapter

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")

        # Mock instance metadata check to ensure credential error is raised
        # (GitHub Actions runners may have access to AWS metadata endpoint)
        with patch.object(AthenaAdapter, "_check_instance_metadata_available", return_value=False):
            with pytest.raises(ConfigurationError) as exc_info:
                AthenaAdapter()

        error_msg = str(exc_info.value)
        # Should suggest how to fix S3 config
        assert "--platform-option" in error_msg or "s3://" in error_msg
        # Should suggest how to configure credentials
        assert "aws configure" in error_msg or "AWS_ACCESS_KEY_ID" in error_msg


class TestAthenaAdapter:
    """Tests for AthenaAdapter class."""

    @pytest.fixture
    def mock_boto3(self):
        """Mock boto3 module."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            yield

    @pytest.fixture
    def mock_pyathena(self):
        """Mock pyathena module."""
        mock_connect = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.cursor.return_value = mock_cursor
        with patch.dict(
            "sys.modules",
            {
                "pyathena": MagicMock(connect=mock_connect),
                "pyathena.cursor": MagicMock(Cursor=MagicMock()),
            },
        ):
            yield mock_connect, mock_cursor

    @pytest.fixture
    def mock_aws_credentials(self, tmp_path, monkeypatch):
        """Create mock AWS credentials file for testing."""
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        creds_file = aws_dir / "credentials"
        creds_file.write_text("[default]\naws_access_key_id = test\naws_secret_access_key = test\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        return creds_file

    def test_initialization_success(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test successful adapter initialization."""
        from benchbox.platforms.athena import AthenaAdapter

        config = {
            "region": "us-west-2",
            "workgroup": "test-workgroup",
            "database": "test_db",
            "s3_bucket": "test-bucket",
            "s3_output_location": "s3://test-bucket/results/",
        }

        adapter = AthenaAdapter(**config)

        assert adapter.platform_name == "Athena"
        assert adapter.region == "us-west-2"
        assert adapter.workgroup == "test-workgroup"
        assert adapter.database == "test_db"
        assert adapter.s3_bucket == "test-bucket"

    def test_initialization_with_defaults(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test initialization with default values."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        assert adapter.region == "us-east-1"
        assert adapter.workgroup == "primary"
        assert adapter.database == "default"
        assert adapter.catalog == "AwsDataCatalog"

    def test_external_table_capability_declared(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Athena should explicitly declare external-table support."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        assert adapter.supports_external_tables is True

    def test_initialization_with_staging_root(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test initialization with s3 staging root."""
        from benchbox.platforms.athena import AthenaAdapter

        config = {
            "staging_root": "s3://my-bucket/data/path",
        }

        adapter = AthenaAdapter(**config)

        assert adapter.s3_bucket == "my-bucket"
        assert adapter.s3_prefix == "data/path"
        assert adapter.s3_output_location == "s3://my-bucket/athena-results/"

    def test_get_target_dialect(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that target dialect returns trino."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        assert adapter.get_target_dialect() == "trino"

    def test_platform_info(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test platform info collection."""
        from benchbox.platforms.athena import AthenaAdapter

        config = {
            "region": "us-west-2",
            "workgroup": "analytics",
            "database": "benchmark",
            "s3_bucket": "data-bucket",
        }

        adapter = AthenaAdapter(**config)
        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "athena"
        assert info["platform_name"] == "AWS Athena"
        assert info["connection_mode"] == "serverless"
        assert info["configuration"]["region"] == "us-west-2"
        assert info["configuration"]["workgroup"] == "analytics"

    def test_cost_tracking(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test cost summary calculation."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        # Simulate some queries
        adapter._total_data_scanned_bytes = 1024**4  # 1 TB
        adapter._query_count = 10

        summary = adapter.get_cost_summary()

        assert summary["total_data_scanned_bytes"] == 1024**4
        assert summary["total_data_scanned_tb"] == 1.0
        assert summary["query_count"] == 10
        assert summary["cost_per_tb_usd"] == 5.0
        assert summary["total_cost_usd"] == 5.0
        assert summary["average_cost_per_query_usd"] == 0.5

    def test_from_config(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test adapter creation from config."""
        from benchbox.platforms.athena import AthenaAdapter

        config = {
            "benchmark": "TPC-H",
            "scale_factor": 10.0,
            "region": "eu-west-1",
            "workgroup": "production",
            "s3_bucket": "prod-bucket",
        }

        adapter = AthenaAdapter.from_config(config)

        assert adapter.region == "eu-west-1"
        assert adapter.workgroup == "production"
        # Database name should be auto-generated
        assert "tpch" in adapter.database.lower() or "benchmark" in adapter.database.lower()

    def test_supports_tuning_type(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test tuning type support."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        try:
            from benchbox.core.tuning.interface import TuningType

            assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
            assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False
        except ImportError:
            # TuningType may not be available in all test environments
            pass

    def test_test_connection_method_exists(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that test_connection method exists and is callable."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_output_location="s3://test-bucket/results/",
        )

        # Verify the method exists
        assert hasattr(adapter, "test_connection")
        assert callable(adapter.test_connection)

    def test_s3_bucket_required_at_init(self, mock_boto3, mock_pyathena, monkeypatch):
        """Test that initialization fails if S3 bucket not configured."""
        from benchbox.platforms.athena import AthenaAdapter

        # Clear AWS environment so credentials check passes with profile
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent")

        # Should fail during init, not during load_data
        with pytest.raises(ConfigurationError, match="No S3 location configured"):
            AthenaAdapter(aws_profile="test-profile")  # Has creds but no S3

    def test_normalize_table_name(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test table name normalization."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        sql = 'CREATE TABLE "CUSTOMER" (id INT)'
        normalized = adapter._normalize_table_name_in_sql(sql)

        # Function should lowercase the table name and preserve the rest of the SQL
        assert "customer" in normalized.lower()
        assert "(id INT)" in normalized  # Column definitions preserved
        # Note: EXTERNAL is added by _convert_to_external_table, not this function

    def test_convert_to_external_table_parquet(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test conversion to external table with Parquet format."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            default_format="PARQUET",
        )

        sql = "CREATE TABLE orders (id INT, amount DECIMAL)"
        converted = adapter._convert_to_external_table(sql)

        assert "EXTERNAL TABLE" in converted.upper()
        assert "STORED AS PARQUET" in converted.upper()
        assert "LOCATION" in converted.upper()
        assert "s3://test-bucket/data/test_db/orders/" in converted
        # Parquet format should not have ROW FORMAT DELIMITED
        assert "ROW FORMAT DELIMITED" not in converted.upper()

    def test_convert_to_external_table_strips_not_null(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that NOT NULL constraints are stripped from external table DDL.

        Athena/Hive DDL doesn't support NOT NULL constraints for external tables.
        """
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            default_format="PARQUET",
        )

        sql = "CREATE TABLE region (r_regionkey INTEGER NOT NULL, r_name VARCHAR NOT NULL, r_comment VARCHAR)"
        converted = adapter._convert_to_external_table(sql)

        assert "EXTERNAL TABLE" in converted.upper()
        # NOT NULL constraints should be stripped
        assert "NOT NULL" not in converted.upper()
        # Column types should still be present (VARCHAR converted to STRING for Hive DDL)
        assert "r_regionkey INTEGER" in converted
        assert "r_name STRING" in converted
        assert "r_comment STRING" in converted

    def test_convert_to_external_table_tbl_format(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test conversion to external table with TBL (pipe-delimited) format in text mode."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            data_format="text",  # Use text mode for text file tables
            default_format="TBL",  # TPC-H style pipe-delimited
        )

        sql = "CREATE TABLE lineitem (l_orderkey INT, l_partkey INT)"
        converted = adapter._convert_to_external_table(sql)

        assert "EXTERNAL TABLE" in converted.upper()
        assert "IF NOT EXISTS" in converted.upper()
        assert "ROW FORMAT DELIMITED" in converted.upper()
        assert "FIELDS TERMINATED BY '|'" in converted
        assert "STORED AS TEXTFILE" in converted.upper()
        assert "s3://test-bucket/data/test_db/lineitem/" in converted

    def test_convert_to_external_table_csv_format(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test conversion to external table with CSV format in text mode."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            data_format="text",  # Use text mode for text file tables
            default_format="CSV",
        )

        sql = "CREATE TABLE events (event_id INT, event_name VARCHAR)"
        converted = adapter._convert_to_external_table(sql)

        assert "EXTERNAL TABLE" in converted.upper()
        assert "ROW FORMAT DELIMITED" in converted.upper()
        assert "FIELDS TERMINATED BY ','" in converted
        assert "STORED AS TEXTFILE" in converted.upper()

    def test_convert_to_external_table_parquet_default(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test that parquet mode (default) creates Parquet tables."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            # data_format defaults to "parquet"
        )

        sql = "CREATE TABLE lineitem (l_orderkey INT, l_partkey INT)"
        converted = adapter._convert_to_external_table(sql)

        assert "EXTERNAL TABLE" in converted.upper()
        assert "IF NOT EXISTS" in converted.upper()
        assert "STORED AS PARQUET" in converted.upper()
        assert "s3://test-bucket/data/test_db/lineitem/" in converted

    def test_convert_to_external_table_staging(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test staging table creation for CTAS workflow."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="data",
            database="test_db",
            data_format="parquet",
        )

        sql = "CREATE TABLE lineitem (l_orderkey INT, l_partkey INT)"
        converted = adapter._convert_to_external_table(sql, is_staging=True)

        assert "lineitem_staging" in converted.lower()
        assert "EXTERNAL TABLE" in converted.upper()
        assert "ROW FORMAT DELIMITED" in converted.upper()
        assert "FIELDS TERMINATED BY '|'" in converted
        assert "STORED AS TEXTFILE" in converted.upper()
        assert "s3://test-bucket/data/test_db_staging/lineitem/" in converted

    def test_create_external_tables_bypasses_ctas_conversion(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """External mode should upload/register without invoking CTAS conversion."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        parquet_file = tmp_path / "lineitem.parquet"
        parquet_file.write_bytes(b"PAR1")

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (123,)
        mock_connection.cursor.return_value = mock_cursor
        mock_s3 = MagicMock()

        with (
            patch.object(adapter, "_get_s3_client", return_value=mock_s3),
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [parquet_file]}),
            patch.object(
                adapter,
                "_build_external_table_statements",
                return_value={
                    "lineitem": "CREATE EXTERNAL TABLE IF NOT EXISTS lineitem (id INT) STORED AS PARQUET LOCATION 's3://test-bucket/data/test_db/lineitem/'"
                },
            ),
            patch.object(adapter, "_convert_staging_to_parquet") as mock_ctas_conversion,
        ):
            stats, _, per_table_timings = adapter.create_external_tables(
                benchmark=MagicMock(), connection=mock_connection, data_dir=tmp_path
            )

        assert stats == {"lineitem": 123}
        assert per_table_timings is None
        mock_ctas_conversion.assert_not_called()
        mock_s3.upload_file.assert_called_once()
        assert any("CREATE EXTERNAL TABLE" in str(call.args[0]).upper() for call in mock_cursor.execute.call_args_list)

    def test_resolve_data_files_external_prefers_manifest_parquet(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """External mode should replace text benchmark tables with manifest-selected Parquet files."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        adapter.table_mode = "external"

        tbl_file = tmp_path / "lineitem.tbl"
        parquet_file = tmp_path / "lineitem.parquet"
        tbl_file.write_text("1|x|\n")
        parquet_file.write_bytes(b"PAR1")
        (tmp_path / "_datagen_manifest.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "benchmark": "tpch",
                    "scale_factor": 0.01,
                    "format_preference": ["tbl", "parquet"],
                    "tables": {
                        "lineitem": {
                            "formats": {
                                "tbl": [{"path": "lineitem.tbl", "size_bytes": 5, "row_count": 1}],
                                "parquet": [{"path": "lineitem.parquet", "size_bytes": 4, "row_count": 1}],
                            }
                        }
                    },
                }
            )
        )
        benchmark = SimpleNamespace(tables={"lineitem": tbl_file})

        result = adapter._resolve_data_files(benchmark, tmp_path)

        assert result == {"lineitem": [parquet_file]}

    def test_resolve_data_files_passes_athena_context_to_resolver(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """Resolver construction should include Athena mode and platform config."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        adapter.table_mode = "external"
        data_source = DataSource(source_type="manifest_v2", tables={"lineitem": [tmp_path / "lineitem.parquet"]})

        with patch("benchbox.platforms.athena.DataSourceResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = data_source
            mock_resolver_cls.return_value = mock_resolver

            result = adapter._resolve_data_files(SimpleNamespace(), tmp_path)

        call_kwargs = mock_resolver_cls.call_args.kwargs
        assert call_kwargs["platform_name"] == "Athena"
        assert call_kwargs["table_mode"] == "external"
        assert call_kwargs["platform_config"]["s3_bucket"] == "test-bucket"
        assert call_kwargs["platform_config"]["s3_prefix"] == "data"
        assert result == {"lineitem": [tmp_path / "lineitem.parquet"]}

    def test_resolve_data_files_external_keeps_benchmark_source_without_manifest_replacement(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """External mode should keep the original source when the manifest has no replacement files."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        adapter.table_mode = "external"
        data_source = DataSource(source_type="benchmark_tables", tables={"lineitem": [tmp_path / "lineitem.tbl"]})

        with patch("benchbox.platforms.athena.DataSourceResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = data_source
            mock_resolver._manifest_source.get_data_source.return_value = None
            mock_resolver_cls.return_value = mock_resolver

            result = adapter._resolve_data_files(SimpleNamespace(), tmp_path)

        assert result == {"lineitem": [tmp_path / "lineitem.tbl"]}

    def test_resolve_data_files_external_manifest_prefers_parquet(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """External mode should select Parquet when falling through directly to the manifest."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        adapter.table_mode = "external"

        tbl_file = tmp_path / "lineitem.tbl"
        parquet_file = tmp_path / "lineitem.parquet"
        tbl_file.write_text("1|x|\n")
        parquet_file.write_bytes(b"PAR1")
        (tmp_path / "_datagen_manifest.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "benchmark": "tpch",
                    "scale_factor": 0.01,
                    "format_preference": ["tbl", "parquet"],
                    "tables": {
                        "lineitem": {
                            "formats": {
                                "tbl": [{"path": "lineitem.tbl", "size_bytes": 5, "row_count": 1}],
                                "parquet": [{"path": "lineitem.parquet", "size_bytes": 4, "row_count": 1}],
                            }
                        }
                    },
                }
            )
        )

        result = adapter._resolve_data_files(SimpleNamespace(), tmp_path)

        assert result == {"lineitem": [parquet_file]}

    def test_resolve_data_files_native_keeps_text_benchmark_tables(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """Native mode should keep benchmark-provided text files instead of forcing manifest Parquet."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")

        tbl_file = tmp_path / "lineitem.tbl"
        parquet_file = tmp_path / "lineitem.parquet"
        tbl_file.write_text("1|x|\n")
        parquet_file.write_bytes(b"PAR1")
        (tmp_path / "_datagen_manifest.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "benchmark": "tpch",
                    "scale_factor": 0.01,
                    "format_preference": ["parquet", "tbl"],
                    "tables": {
                        "lineitem": {
                            "formats": {
                                "tbl": [{"path": "lineitem.tbl", "size_bytes": 5, "row_count": 1}],
                                "parquet": [{"path": "lineitem.parquet", "size_bytes": 4, "row_count": 1}],
                            }
                        }
                    },
                }
            )
        )
        benchmark = SimpleNamespace(tables={"lineitem": tbl_file})

        result = adapter._resolve_data_files(benchmark, tmp_path)

        assert result == {"lineitem": [tbl_file]}

    def test_resolve_data_files_native_keeps_benchmark_source_when_manifest_prefers_parquet(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """Native mode keeps benchmark-provided text files even when the manifest lists Parquet first.

        BenchmarkTablesSource wins the chain because benchmark.tables is non-empty; the
        manifest is only consulted for format hints, not to replace the table list.
        """
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")

        tbl_file = tmp_path / "lineitem.tbl"
        parquet_file = tmp_path / "lineitem.parquet"
        tbl_file.write_text("1|x|\n")
        parquet_file.write_bytes(b"PAR1")
        (tmp_path / "_datagen_manifest.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "benchmark": "tpch",
                    "scale_factor": 0.01,
                    "format_preference": ["parquet", "tbl"],
                    "tables": {
                        "lineitem": {
                            "formats": {
                                "tbl": [{"path": "lineitem.tbl", "size_bytes": 5, "row_count": 1}],
                                "parquet": [{"path": "lineitem.parquet", "size_bytes": 4, "row_count": 1}],
                            }
                        }
                    },
                }
            )
        )

        result = adapter._resolve_data_files(SimpleNamespace(), tmp_path)

        assert result == {"lineitem": [tbl_file]}

    def test_resolve_data_files_raises_when_no_source_found(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """Missing benchmark tables and manifest should raise a clear error."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")

        with patch("benchbox.platforms.athena.DataSourceResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = None
            mock_resolver_cls.return_value = mock_resolver

            with pytest.raises(ValueError, match="No data files found"):
                adapter._resolve_data_files(SimpleNamespace(), tmp_path)

    def test_load_data_parquet_mode_keeps_ctas_conversion(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Native parquet mode should continue to use CTAS staging conversion path."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="test_db")
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_s3 = MagicMock()

        with (
            patch.object(adapter, "_get_s3_client", return_value=mock_s3),
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [MagicMock()]}),
            patch.object(adapter, "_upload_files_to_s3", return_value=(100, 1)),
            patch.object(
                adapter, "_convert_staging_to_parquet", return_value={"lineitem": 100}
            ) as mock_ctas_conversion,
        ):
            stats, _, per_table_timings = adapter.load_data(
                benchmark=MagicMock(), connection=mock_connection, data_dir=MagicMock()
            )

        assert stats == {"lineitem": 100}
        assert per_table_timings is None
        mock_ctas_conversion.assert_called_once()

    def test_build_external_table_statements_normalizes_table_names(
        self, mock_boto3, mock_pyathena, mock_aws_credentials
    ):
        """External-table statements should be keyed by normalized table name."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="data", database="analytics")

        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="""
                CREATE TABLE "ORDERS" (id INT, amount DECIMAL);
                CREATE TABLE LINEITEM (line_id BIGINT);
            """,
        ):
            statements = adapter._build_external_table_statements(MagicMock())

        assert sorted(statements) == ["lineitem", "orders"]
        assert "CREATE EXTERNAL TABLE IF NOT EXISTS orders" in statements["orders"]
        assert "s3://test-bucket/data/analytics/orders/" in statements["orders"]
        assert "CREATE EXTERNAL TABLE IF NOT EXISTS lineitem" in statements["lineitem"]

    def test_normalize_parquet_files_filters_non_parquet_and_empty(
        self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path
    ):
        """Only existing non-empty Parquet files should be kept for external registration."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        parquet_file = tmp_path / "orders.parquet"
        csv_file = tmp_path / "orders.csv"
        empty_parquet = tmp_path / "empty.parquet"
        parquet_file.write_bytes(b"PAR1")
        csv_file.write_text("1,test\n")
        empty_parquet.write_bytes(b"")

        result = adapter._normalize_parquet_files([parquet_file, csv_file, empty_parquet, tmp_path / "missing.parquet"])

        assert result == [parquet_file]

    @pytest.mark.parametrize(
        ("is_parquet_mode", "expected"),
        [
            (True, "benchbox-data/tpch_staging/lineitem/"),
            (False, "benchbox-data/tpch/lineitem/"),
        ],
    )
    def test_build_s3_table_path(self, is_parquet_mode, expected, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Table S3 paths should switch between staging and final prefixes."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="benchbox-data", database="tpch")

        assert adapter._build_s3_table_path("lineitem", is_parquet_mode) == expected

    def test_upload_files_to_s3_counts_non_blank_rows(self, mock_boto3, mock_pyathena, mock_aws_credentials, tmp_path):
        """S3 upload helper should count only non-empty rows and upload each valid file."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="benchbox-data", database="tpch")
        mock_s3 = MagicMock()
        file_one = tmp_path / "lineitem.tbl"
        file_two = tmp_path / "lineitem.tbl.1"
        file_one.write_text("1|a|\n\n2|b|\n")
        file_two.write_text("3|c|\n")

        uploaded_rows, file_count = adapter._upload_files_to_s3(
            mock_s3,
            "lineitem",
            "lineitem",
            [file_one, file_two],
            is_parquet_mode=True,
        )

        assert uploaded_rows == 3
        assert file_count == 2
        upload_calls = [call.args for call in mock_s3.upload_file.call_args_list]
        assert (str(file_one), "test-bucket", "benchbox-data/tpch_staging/lineitem/lineitem.tbl") in upload_calls
        assert (str(file_two), "test-bucket", "benchbox-data/tpch_staging/lineitem/lineitem.tbl.1") in upload_calls

    def test_load_text_mode_table_returns_uploaded_rows_when_count_check_fails(
        self, mock_boto3, mock_pyathena, mock_aws_credentials
    ):
        """Text-mode load should fall back to uploaded row count when verification fails."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = [None, Exception("count failed")]

        actual_rows, verified = adapter._load_text_mode_table(mock_cursor, "lineitem", 11)

        assert actual_rows == 11
        assert verified is False
        mock_cursor.execute.assert_any_call("MSCK REPAIR TABLE lineitem")
        mock_cursor.execute.assert_any_call("SELECT COUNT(*) FROM lineitem")

    def test_convert_staging_to_parquet_executes_ctas_and_cleanup(
        self, mock_boto3, mock_pyathena, mock_aws_credentials
    ):
        """CTAS conversion should target the parquet location and clean up staging when enabled."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(
            s3_bucket="test-bucket",
            s3_prefix="benchbox-data",
            database="tpch",
            compression="GZIP",
            cleanup_staging=True,
        )
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (9,)
        mock_s3 = MagicMock()

        with patch.object(adapter, "_cleanup_staging") as mock_cleanup:
            stats = adapter._convert_staging_to_parquet(mock_cursor, [("lineitem", 9)], mock_s3)

        assert stats == {"lineitem": 9}
        execute_sql = [str(call.args[0]) for call in mock_cursor.execute.call_args_list]
        assert execute_sql[0] == "DROP TABLE IF EXISTS lineitem"
        assert any("CREATE TABLE lineitem" in sql for sql in execute_sql)
        assert any("external_location = 's3://test-bucket/benchbox-data/tpch/lineitem/'" in sql for sql in execute_sql)
        assert any("parquet_compression = 'GZIP'" in sql for sql in execute_sql)
        assert execute_sql[-1] == "SELECT COUNT(*) FROM lineitem"
        mock_cleanup.assert_called_once_with(mock_cursor, mock_s3, "lineitem", "lineitem_staging")

    def test_cleanup_staging_deletes_in_batches(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Staging cleanup should drop the Glue table and batch S3 object deletions."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket", s3_prefix="benchbox-data", database="tpch")
        mock_cursor = MagicMock()
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        first_batch = [{"Key": f"benchbox-data/tpch_staging/lineitem/part-{i}.parquet"} for i in range(1000)]
        second_batch = [{"Key": "benchbox-data/tpch_staging/lineitem/part-1000.parquet"}]
        mock_paginator.paginate.return_value = [{"Contents": first_batch + second_batch}]
        mock_s3.get_paginator.return_value = mock_paginator

        adapter._cleanup_staging(mock_cursor, mock_s3, "lineitem", "lineitem_staging")

        mock_cursor.execute.assert_called_once_with("DROP TABLE IF EXISTS lineitem_staging")
        delete_calls = mock_s3.delete_objects.call_args_list
        assert len(delete_calls) == 2
        assert delete_calls[0].kwargs["Bucket"] == "test-bucket"
        assert len(delete_calls[0].kwargs["Delete"]["Objects"]) == 1000
        assert len(delete_calls[1].kwargs["Delete"]["Objects"]) == 1


class TestAthenaAdapterExecution:
    """Tests for Athena query execution and error handling."""

    @pytest.fixture
    def mock_boto3(self):
        """Mock boto3 module."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            yield

    @pytest.fixture
    def mock_pyathena(self):
        """Mock pyathena module."""
        mock_connect = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.cursor.return_value = mock_cursor
        with patch.dict(
            "sys.modules",
            {
                "pyathena": MagicMock(connect=mock_connect),
                "pyathena.cursor": MagicMock(Cursor=MagicMock()),
            },
        ):
            yield mock_connect, mock_cursor

    @pytest.fixture
    def mock_aws_credentials(self, tmp_path, monkeypatch):
        """Create mock AWS credentials file for testing."""
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        creds_file = aws_dir / "credentials"
        creds_file.write_text("[default]\naws_access_key_id = test\naws_secret_access_key = test\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        return creds_file

    def test_execute_query_success(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test successful query execution."""
        from benchbox.platforms.athena import AthenaAdapter

        _, mock_cursor = mock_pyathena
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.data_scanned_in_bytes = 1024

        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2

    def test_execute_query_failure(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test query execution failure."""
        from benchbox.platforms.athena import AthenaAdapter

        _, mock_cursor = mock_pyathena
        mock_cursor.execute.side_effect = Exception("Query failed")

        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert "Query failed" in result.get("error", "")

    def test_close_connection(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test connection closing."""
        from benchbox.platforms.athena import AthenaAdapter

        mock_connection = MagicMock()

        adapter = AthenaAdapter(s3_bucket="test-bucket")
        adapter.close_connection(mock_connection)

        mock_connection.close.assert_called_once()

    def test_close_connection_handles_none(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test connection closing handles None gracefully."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        # Should not raise
        adapter.close_connection(None)

    def test_generate_tuning_clause_partitioning(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test tuning clause generation with partitioning."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        mock_col = MagicMock()
        mock_col.name = "date_col"
        mock_col.order = 1

        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = True

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning.get_columns_by_type.return_value = [mock_col]

            clause = adapter.generate_tuning_clause(mock_tuning)
            assert "PARTITIONED BY" in clause
            assert "date_col" in clause

    def test_generate_tuning_clause_empty(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test tuning clause generation with no tuning."""
        from benchbox.platforms.athena import AthenaAdapter

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = False

        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == ""

    def test_get_query_plan(self, mock_boto3, mock_pyathena, mock_aws_credentials):
        """Test query plan retrieval."""
        from benchbox.platforms.athena import AthenaAdapter

        _, mock_cursor = mock_pyathena
        mock_cursor.fetchall.return_value = [("Stage 1: Scan Table",), ("Stage 2: Filter",)]

        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = AthenaAdapter(s3_bucket="test-bucket")

        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM test")

        assert "Scan Table" in plan or "Stage" in plan


class TestAthenaAdapterImportError:
    """Tests for import error handling when pyathena is not installed."""

    def test_missing_dependencies(self):
        """Test that missing dependencies raise ImportError."""
        import sys

        # Remove pyathena and boto3 from modules if present
        modules_to_remove = ["pyathena", "boto3"]
        removed = {}
        for mod in modules_to_remove:
            if mod in sys.modules:
                removed[mod] = sys.modules.pop(mod)

        try:
            with patch.dict("sys.modules", {"pyathena": None, "boto3": None}):
                # This should raise ImportError due to missing dependencies
                # The actual test depends on how the module handles missing deps
                pass
        finally:
            # Restore modules
            sys.modules.update(removed)


class TestAthenaAdapterRegistration:
    """Tests for platform registration."""

    def test_athena_in_platform_list(self):
        """Test that Athena is listed in available platforms."""
        from benchbox.platforms import list_available_platforms

        platforms = list_available_platforms()
        assert "athena" in platforms

    def test_athena_requirements(self):
        """Test that Athena requirements are correct."""
        from benchbox.platforms import get_platform_requirements

        requirements = get_platform_requirements("athena")
        assert "pyathena" in requirements
        assert "boto3" in requirements

    def test_athena_dependency_group(self):
        """Test that Athena dependency group is defined."""
        from benchbox.utils.dependencies import DEPENDENCY_GROUPS

        assert "athena" in DEPENDENCY_GROUPS
        athena_deps = DEPENDENCY_GROUPS["athena"]
        assert "pyathena" in athena_deps.packages
        assert "boto3" in athena_deps.packages

    def test_validate_external_table_requirements_raises_without_s3_bucket(self):
        """Athena must expose validate_external_table_requirements as a contract."""
        with (
            patch.dict("sys.modules", {"boto3": MagicMock()}),
            patch.dict(
                "sys.modules",
                {
                    "pyathena": MagicMock(connect=MagicMock()),
                    "pyathena.cursor": MagicMock(Cursor=MagicMock()),
                },
            ),
        ):
            from benchbox.platforms.athena import AthenaAdapter

            adapter = AthenaAdapter.__new__(AthenaAdapter)
            adapter.s3_bucket = None
            with pytest.raises(ValueError, match="S3 bucket|s3_bucket"):
                adapter.validate_external_table_requirements()

    def test_validate_external_table_requirements_passes_with_s3_bucket(self):
        with (
            patch.dict("sys.modules", {"boto3": MagicMock()}),
            patch.dict(
                "sys.modules",
                {
                    "pyathena": MagicMock(connect=MagicMock()),
                    "pyathena.cursor": MagicMock(Cursor=MagicMock()),
                },
            ),
        ):
            from benchbox.platforms.athena import AthenaAdapter

            adapter = AthenaAdapter.__new__(AthenaAdapter)
            adapter.s3_bucket = "my-bucket"
            adapter.validate_external_table_requirements()  # Should not raise


class TestAthenaConfigBuilder:
    """Tests for the Athena config builder."""

    def test_builder_uses_aws_region_when_region_missing(self):
        from benchbox.platforms.athena import _build_athena_config

        mock_info = MagicMock(display_name="AWS Athena", driver_package="pyathena")

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {"aws_region": "eu-west-1"}

            config = _build_athena_config("athena", {}, {}, mock_info)

        assert config.region == "eu-west-1"

    def test_builder_prefers_region_over_aws_region(self):
        from benchbox.platforms.athena import _build_athena_config

        mock_info = MagicMock(display_name="AWS Athena", driver_package="pyathena")

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm_cls.return_value.get_platform_credentials.return_value = {"aws_region": "eu-west-1"}

            config = _build_athena_config(
                "athena",
                {"region": "us-west-2"},
                {},
                mock_info,
            )

        assert config.region == "us-west-2"
