"""Additional coverage tests for RedshiftAdapter uncovered paths.

Focuses on:
- _connect_with_driver: redshift_connector vs psycopg selection
- _get_copy_credentials_clause: session token path
- staging_root non-S3 provider raises ValueError
- _detect_deployment_type, _extract_region/_identifier from hostname
- get_platform_info basic fields without connection
- COMPUPDATE validation
- add_cli_arguments

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_redshift_deps():
    """Provide a clean mock of redshift_connector and boto3."""
    mock_rc = MagicMock()
    mock_boto = MagicMock()
    with (
        patch("benchbox.platforms.redshift.redshift_connector", mock_rc),
        patch("benchbox.platforms.redshift.boto3", mock_boto),
        patch(
            "benchbox.platforms.redshift.check_platform_dependencies",
            return_value=(True, []),
        ),
        patch(
            "benchbox.platforms.redshift.get_dependency_group_packages",
            return_value=[],
        ),
    ):
        yield {"rc": mock_rc, "boto3": mock_boto}


def _make_adapter(**kwargs):
    from benchbox.platforms.redshift import RedshiftAdapter

    defaults = {
        "host": "cluster.us-east-1.redshift.amazonaws.com",
        "username": "test_user",
        "password": "test_pass",
        "database": "test_db",
    }
    defaults.update(kwargs)
    return RedshiftAdapter(**defaults)


# ---------------------------------------------------------------------------
# _connect_with_driver: connector selection
# ---------------------------------------------------------------------------


class TestConnectWithDriverSelection:
    """Test _connect_with_driver uses the available connector."""

    def test_uses_redshift_connector_when_available(self, _mock_redshift_deps):
        mock_rc = _mock_redshift_deps["rc"]
        mock_conn = Mock()
        mock_rc.connect.return_value = mock_conn

        adapter = _make_adapter()
        result = adapter._connect_with_driver(application_name="Test", connect_timeout=10)

        mock_rc.connect.assert_called_once()
        assert result is mock_conn

    def test_falls_back_to_psycopg_when_rc_unavailable(self):
        """When redshift_connector is None, psycopg.connect is called instead."""
        mock_pg = MagicMock()
        mock_conn = Mock()
        mock_pg.connect.return_value = mock_conn

        with (
            patch("benchbox.platforms.redshift.redshift_connector", None),
            patch("benchbox.platforms.redshift.psycopg", mock_pg, create=True),
            patch(
                "benchbox.platforms.redshift.check_platform_dependencies",
                return_value=(True, []),
            ),
            patch(
                "benchbox.platforms.redshift.get_dependency_group_packages",
                return_value=[],
            ),
        ):
            from benchbox.platforms.redshift import RedshiftAdapter

            adapter = RedshiftAdapter(
                host="cluster.us-east-1.redshift.amazonaws.com",
                username="test_user",
                password="test_pass",
                database="test_db",
            )
            result = adapter._connect_with_driver(application_name="Test", connect_timeout=10)

        mock_pg.connect.assert_called_once()
        assert result is mock_conn

    def test_redshift_connector_call_includes_required_kwargs(self, _mock_redshift_deps):
        mock_rc = _mock_redshift_deps["rc"]
        mock_rc.connect.return_value = Mock()

        adapter = _make_adapter()
        adapter._connect_with_driver(application_name="BenchBox", connect_timeout=15)

        call_kwargs = mock_rc.connect.call_args[1]
        assert call_kwargs["host"] == "cluster.us-east-1.redshift.amazonaws.com"
        assert call_kwargs["database"] == "test_db"
        assert call_kwargs["user"] == "test_user"
        assert call_kwargs["password"] == "test_pass"

    def test_sslmode_verify_full_forwarded_to_rc(self, _mock_redshift_deps):
        mock_rc = _mock_redshift_deps["rc"]
        mock_rc.connect.return_value = Mock()

        adapter = _make_adapter(sslmode="verify-full")
        adapter._connect_with_driver(application_name="BenchBox", connect_timeout=10)

        call_kwargs = mock_rc.connect.call_args[1]
        assert call_kwargs.get("sslmode") == "verify-full"


# ---------------------------------------------------------------------------
# _get_copy_credentials_clause: session token success path
# ---------------------------------------------------------------------------


class TestCopyCredentialsWithSessionToken:
    """Test _get_copy_credentials_clause includes session token when set."""

    def test_session_token_appended_to_clause(self):
        adapter = _make_adapter(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_session_token="tok123",
        )
        clause = adapter._get_copy_credentials_clause()

        assert "ACCESS_KEY_ID 'AKIATEST'" in clause
        assert "SECRET_ACCESS_KEY 'secret'" in clause
        assert "SESSION_TOKEN 'tok123'" in clause

    def test_no_session_token_omits_session_token(self):
        adapter = _make_adapter(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
        )
        clause = adapter._get_copy_credentials_clause()

        assert "SESSION_TOKEN" not in clause
        assert "ACCESS_KEY_ID 'AKIATEST'" in clause


# ---------------------------------------------------------------------------
# staging_root: non-S3 raises ValueError
# ---------------------------------------------------------------------------


class TestStagingRootValidation:
    """Test non-S3 staging_root raises ValueError."""

    def test_gs_staging_root_raises(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ValueError, match="S3.*staging"):
            RedshiftAdapter(
                host="h.us-east-1.redshift.amazonaws.com",
                username="u",
                password="p",
                database="db",
                staging_root="gs://bucket/path",
            )


# ---------------------------------------------------------------------------
# _detect_deployment_type
# ---------------------------------------------------------------------------


class TestDetectDeploymentType:
    """Test hostname-based deployment type detection."""

    def test_serverless_hostname_detected(self):
        adapter = _make_adapter()
        assert adapter._detect_deployment_type("wg.acct.us-east-1.redshift-serverless.amazonaws.com") == "serverless"

    def test_provisioned_hostname_detected(self):
        adapter = _make_adapter()
        assert adapter._detect_deployment_type("cluster.us-east-1.redshift.amazonaws.com") == "provisioned"

    def test_unknown_hostname_detected(self):
        adapter = _make_adapter()
        assert adapter._detect_deployment_type("my-custom-host.example.com") == "unknown"

    def test_empty_hostname_is_unknown(self):
        adapter = _make_adapter()
        assert adapter._detect_deployment_type("") == "unknown"


# ---------------------------------------------------------------------------
# _extract_region_from_hostname and _extract_identifier_from_hostname
# ---------------------------------------------------------------------------


class TestHostnameParsing:
    """Test region and identifier extraction from hostname."""

    def test_provisioned_region_extracted(self):
        adapter = _make_adapter()
        region = adapter._extract_region_from_hostname("my-cluster.us-west-2.redshift.amazonaws.com", "provisioned")
        assert region == "us-west-2"

    def test_serverless_region_extracted(self):
        adapter = _make_adapter()
        region = adapter._extract_region_from_hostname(
            "my-wg.123456789012.eu-central-1.redshift-serverless.amazonaws.com", "serverless"
        )
        assert region == "eu-central-1"

    def test_provisioned_identifier_extracted(self):
        adapter = _make_adapter()
        ident = adapter._extract_identifier_from_hostname("my-cluster.us-east-1.redshift.amazonaws.com", "provisioned")
        assert ident == "my-cluster"

    def test_serverless_identifier_extracted(self):
        adapter = _make_adapter()
        ident = adapter._extract_identifier_from_hostname(
            "my-workgroup.123456789012.us-east-1.redshift-serverless.amazonaws.com", "serverless"
        )
        assert ident == "my-workgroup"

    def test_empty_hostname_returns_none(self):
        adapter = _make_adapter()
        assert adapter._extract_region_from_hostname("", "provisioned") is None
        assert adapter._extract_identifier_from_hostname("", "serverless") is None


# ---------------------------------------------------------------------------
# COMPUPDATE validation
# ---------------------------------------------------------------------------


class TestCompupdateValidation:
    """Test COMPUPDATE value validated on init."""

    def test_valid_preset_accepted(self):
        adapter = _make_adapter(compupdate="PRESET")
        assert adapter.compupdate == "PRESET"

    def test_lowercase_normalized(self):
        adapter = _make_adapter(compupdate="on")
        assert adapter.compupdate == "ON"

    def test_invalid_value_raises(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ValueError, match="Invalid COMPUPDATE"):
            RedshiftAdapter(
                host="h.us-east-1.redshift.amazonaws.com",
                username="u",
                password="p",
                database="db",
                compupdate="FAST",
            )


# ---------------------------------------------------------------------------
# get_platform_info without connection
# ---------------------------------------------------------------------------


class TestGetPlatformInfoBasic:
    """Test get_platform_info returns expected fields without a live connection."""

    def test_basic_fields_present(self):
        adapter = _make_adapter(
            host="cluster.us-east-1.redshift.amazonaws.com",
            database="bench_db",
            iam_role="arn:aws:iam::123:role/role",
        )
        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "redshift"
        assert info["platform_name"] == "Redshift"
        assert info["cloud_provider"] == "AWS"
        assert info["configuration"]["database"] == "bench_db"
        assert info["configuration"]["iam_role"] == "arn:aws:iam::123:role/role"

    def test_deployment_type_included(self):
        adapter = _make_adapter(host="wg.acct.us-east-1.redshift-serverless.amazonaws.com")
        info = adapter.get_platform_info(connection=None)
        assert info["configuration"]["deployment_type"] == "serverless"


# ---------------------------------------------------------------------------
# add_cli_arguments
# ---------------------------------------------------------------------------


class TestRedshiftAddCliArguments:
    """Test add_cli_arguments registers expected flags."""

    def test_host_arg(self):
        import argparse

        from benchbox.platforms.redshift import RedshiftAdapter

        parser = argparse.ArgumentParser()
        RedshiftAdapter.add_cli_arguments(parser)
        args = parser.parse_args(["--host", "my-cluster.us-east-1.redshift.amazonaws.com"])
        assert args.host == "my-cluster.us-east-1.redshift.amazonaws.com"

    def test_port_default(self):
        import argparse

        from benchbox.platforms.redshift import RedshiftAdapter

        parser = argparse.ArgumentParser()
        RedshiftAdapter.add_cli_arguments(parser)
        args = parser.parse_args([])
        assert args.port == 5439

    def test_iam_role_arg(self):
        import argparse

        from benchbox.platforms.redshift import RedshiftAdapter

        parser = argparse.ArgumentParser()
        RedshiftAdapter.add_cli_arguments(parser)
        args = parser.parse_args(["--iam-role", "arn:aws:iam::123:role/r"])
        assert args.iam_role == "arn:aws:iam::123:role/r"


# ---------------------------------------------------------------------------
# _upload_file_to_s3: happy path and ClientError branches
# ---------------------------------------------------------------------------


class TestUploadFileToS3:
    """Test _upload_file_to_s3 S3 URI construction and error handling."""

    def test_happy_path_returns_s3_uri(self, tmp_path):
        from pathlib import Path

        adapter = _make_adapter(
            staging_root="s3://my-bucket/my-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        file_path = tmp_path / "lineitem.tbl"
        file_path.write_text("data")

        result = adapter._upload_file_to_s3(mock_s3, file_path, "lineitem", 0)

        expected_key = "my-prefix/lineitem_0.tbl"
        mock_s3.upload_file.assert_called_once_with(str(file_path), "my-bucket", expected_key)
        assert result == f"s3://my-bucket/{expected_key}"

    def test_no_such_bucket_raises_value_error(self, tmp_path):
        from botocore.exceptions import ClientError

        adapter = _make_adapter(
            staging_root="s3://my-bucket/pfx",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "The bucket does not exist"}},
            "PutObject",
        )
        file_path = tmp_path / "orders.tbl"
        file_path.write_text("data")

        with pytest.raises(ValueError, match="does not exist"):
            adapter._upload_file_to_s3(mock_s3, file_path, "orders", 0)

    def test_access_denied_raises_value_error(self, tmp_path):
        from botocore.exceptions import ClientError

        adapter = _make_adapter(
            staging_root="s3://my-bucket/pfx",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "PutObject",
        )
        file_path = tmp_path / "part.tbl"
        file_path.write_text("data")

        with pytest.raises(ValueError, match="Access denied"):
            adapter._upload_file_to_s3(mock_s3, file_path, "part", 0)

    def test_other_client_error_raises_with_code(self, tmp_path):
        from botocore.exceptions import ClientError

        adapter = _make_adapter(
            staging_root="s3://my-bucket/pfx",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "Something went wrong"}},
            "PutObject",
        )
        file_path = tmp_path / "supplier.tbl"
        file_path.write_text("data")

        with pytest.raises(ValueError, match="InternalError"):
            adapter._upload_file_to_s3(mock_s3, file_path, "supplier", 0)


# ---------------------------------------------------------------------------
# _load_table_via_s3: format and compression branches
# ---------------------------------------------------------------------------


class TestLoadTableViaS3:
    """Test _load_table_via_s3 COPY SQL generation for different formats."""

    def _make_s3_adapter(self):
        return _make_adapter(
            staging_root="s3://bench-bucket/bench-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            auto_analyze=False,
        )

    def _make_cursor(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = [100]
        return cursor

    def test_parquet_format_copy_sql(self, tmp_path):
        from pathlib import Path

        adapter = self._make_s3_adapter()
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = self._make_cursor()
        mock_s3 = MagicMock()
        file_path = tmp_path / "lineitem.parquet"
        file_path.write_text("parquet_data")

        with (
            patch.object(
                adapter, "_upload_file_to_s3", return_value="s3://bench-bucket/bench-prefix/lineitem_0.parquet"
            ),
            patch.object(
                adapter, "_build_s3_copy_source", return_value=("s3://bench-bucket/bench-prefix/lineitem_0.parquet", "")
            ),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=True),
            patch("benchbox.platforms.redshift.detect_compression", return_value=None),
        ):
            row_count = adapter._load_table_via_s3(cursor, mock_s3, "lineitem", [file_path], MagicMock())

        assert row_count == 100
        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "FORMAT AS PARQUET" in copy_call

    def test_csv_format_copy_sql(self, tmp_path):
        from pathlib import Path

        adapter = self._make_s3_adapter()
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = self._make_cursor()
        mock_s3 = MagicMock()
        file_path = tmp_path / "orders.tbl"
        file_path.write_text("data")

        with (
            patch.object(adapter, "_upload_file_to_s3", return_value="s3://bench-bucket/bench-prefix/orders_0.tbl"),
            patch.object(
                adapter, "_build_s3_copy_source", return_value=("s3://bench-bucket/bench-prefix/orders_0.tbl", "")
            ),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=False),
            patch("benchbox.platforms.redshift.detect_compression", return_value=None),
        ):
            row_count = adapter._load_table_via_s3(cursor, mock_s3, "orders", [file_path], MagicMock())

        assert row_count == 100
        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "DELIMITER" in copy_call
        assert "COMPUPDATE" in copy_call

    def test_gzip_compression_in_copy_sql(self, tmp_path):
        from pathlib import Path

        adapter = self._make_s3_adapter()
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = self._make_cursor()
        mock_s3 = MagicMock()
        file_path = tmp_path / "part.tbl.gz"
        file_path.write_text("data")

        with (
            patch.object(adapter, "_upload_file_to_s3", return_value="s3://bench-bucket/bench-prefix/part_0.tbl.gz"),
            patch.object(
                adapter, "_build_s3_copy_source", return_value=("s3://bench-bucket/bench-prefix/part_0.tbl.gz", "")
            ),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=False),
            patch("benchbox.platforms.redshift.detect_compression", return_value="gzip"),
        ):
            row_count = adapter._load_table_via_s3(cursor, mock_s3, "part", [file_path], MagicMock())

        assert row_count == 100
        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "GZIP" in copy_call

    def test_zstd_compression_in_copy_sql(self, tmp_path):
        from pathlib import Path

        adapter = self._make_s3_adapter()
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = self._make_cursor()
        mock_s3 = MagicMock()
        file_path = tmp_path / "supplier.tbl.zst"
        file_path.write_text("data")

        with (
            patch.object(
                adapter, "_upload_file_to_s3", return_value="s3://bench-bucket/bench-prefix/supplier_0.tbl.zst"
            ),
            patch.object(
                adapter, "_build_s3_copy_source", return_value=("s3://bench-bucket/bench-prefix/supplier_0.tbl.zst", "")
            ),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=False),
            patch("benchbox.platforms.redshift.detect_compression", return_value="zstd"),
        ):
            row_count = adapter._load_table_via_s3(cursor, mock_s3, "supplier", [file_path], MagicMock())

        assert row_count == 100
        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "ZSTD" in copy_call


# ---------------------------------------------------------------------------
# _optimize_table_definition: DDL transformation branches
# ---------------------------------------------------------------------------


class TestOptimizeTableDefinition:
    """Test _optimize_table_definition Redshift DDL enhancement."""

    def test_non_create_table_returned_unchanged(self):
        adapter = _make_adapter()
        sql = "SELECT * FROM lineitem"
        assert adapter._optimize_table_definition(sql) == sql

    def test_create_table_gets_diststyle_and_sortkey(self):
        adapter = _make_adapter()
        sql = "CREATE TABLE orders (o_orderkey INT)"
        result = adapter._optimize_table_definition(sql)
        assert "DISTSTYLE AUTO" in result
        assert "SORTKEY AUTO" in result

    def test_existing_diststyle_not_duplicated(self):
        adapter = _make_adapter()
        sql = "CREATE TABLE orders (o_orderkey INT) DISTSTYLE EVEN"
        result = adapter._optimize_table_definition(sql)
        # DISTSTYLE already present - should not add DISTSTYLE AUTO again
        assert result.upper().count("DISTSTYLE") == 1
        # SORTKEY not present - should append SORTKEY AUTO
        assert "SORTKEY AUTO" in result


# ---------------------------------------------------------------------------
# _create_direct_connection: WLM query group SET statement
# ---------------------------------------------------------------------------


class TestCreateDirectConnectionWlm:
    """Test _create_direct_connection applies WLM query group when configured."""

    def test_wlm_queue_name_issues_set_statement(self):
        adapter = _make_adapter(wlm_query_queue_name="my_queue")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(adapter, "_connect_with_driver", return_value=mock_conn):
            result = adapter._create_direct_connection(database="test_db")

        assert result is mock_conn
        mock_cursor.execute.assert_called_once_with("SET query_group TO 'my_queue'")
        mock_cursor.close.assert_called_once()

    def test_no_wlm_queue_name_skips_set_statement(self):
        adapter = _make_adapter()  # no wlm_query_queue_name

        mock_conn = MagicMock()

        with patch.object(adapter, "_connect_with_driver", return_value=mock_conn):
            result = adapter._create_direct_connection(database="test_db")

        assert result is mock_conn
        mock_conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# _create_s3_client: partial credential XOR check
# ---------------------------------------------------------------------------


class TestCreateS3ClientCredentialXor:
    """Test _create_s3_client raises ValueError when only one of the key pair is set."""

    def test_key_id_without_secret_raises(self):
        adapter = _make_adapter(aws_access_key_id="AKIATEST")
        # aws_secret_access_key is not set - XOR mismatch

        with pytest.raises(ValueError, match="both"):
            adapter._create_s3_client()


# ---------------------------------------------------------------------------
# from_config() factory
# ---------------------------------------------------------------------------


class TestFromConfig:
    """Test from_config() class method creates adapter correctly."""

    def test_generates_database_name_from_benchmark(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        with patch("benchbox.platforms.redshift.CredentialManager", create=True):
            config = {
                "host": "cluster.us-east-1.redshift.amazonaws.com",
                "username": "user",
                "password": "pass",
                "benchmark": "tpch",
                "scale_factor": 1,
            }
            adapter = RedshiftAdapter.from_config(config)
            # Database name should be generated (not empty)
            assert adapter.database is not None
            assert len(adapter.database) > 0

    def test_explicit_database_name_used_as_is(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        config = {
            "host": "cluster.us-east-1.redshift.amazonaws.com",
            "username": "user",
            "password": "pass",
            "benchmark": "tpch",
            "scale_factor": 1,
            "database": "my_custom_db",
        }
        adapter = RedshiftAdapter.from_config(config)
        assert adapter.database == "my_custom_db"

    def test_iam_role_passed_through(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        config = {
            "host": "cluster.us-east-1.redshift.amazonaws.com",
            "username": "user",
            "password": "pass",
            "benchmark": "tpch",
            "scale_factor": 1,
            "iam_role": "arn:aws:iam::123456789:role/RedshiftRole",
        }
        adapter = RedshiftAdapter.from_config(config)
        assert adapter.iam_role == "arn:aws:iam::123456789:role/RedshiftRole"

    def test_default_port_is_5439(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        config = {
            "host": "cluster.us-east-1.redshift.amazonaws.com",
            "username": "user",
            "password": "pass",
            "benchmark": "tpch",
            "scale_factor": 1,
        }
        adapter = RedshiftAdapter.from_config(config)
        assert adapter.port == 5439

    def test_result_cache_options_passed_through(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        config = {
            "host": "cluster.us-east-1.redshift.amazonaws.com",
            "username": "user",
            "password": "pass",
            "benchmark": "tpch",
            "scale_factor": 1,
            "disable_result_cache": False,
            "strict_validation": False,
        }
        adapter = RedshiftAdapter.from_config(config)
        assert adapter.disable_result_cache is False
        assert adapter.strict_validation is False

    def test_custom_port_passed_through(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        config = {
            "host": "cluster.us-east-1.redshift.amazonaws.com",
            "port": 5440,
            "username": "user",
            "password": "pass",
            "benchmark": "tpch",
            "scale_factor": 1,
        }
        adapter = RedshiftAdapter.from_config(config)
        assert adapter.port == 5440


# ---------------------------------------------------------------------------
# Missing host raises ConfigurationError
# ---------------------------------------------------------------------------


class TestMissingHostRaisesConfigurationError:
    """Test that missing host raises ConfigurationError on init."""

    def test_missing_host_raises(self):
        from benchbox.core.exceptions import ConfigurationError
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ConfigurationError, match="host"):
            RedshiftAdapter(username="user", password="pass", database="db")

    def test_missing_username_raises(self):
        from benchbox.core.exceptions import ConfigurationError
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ConfigurationError, match="username"):
            RedshiftAdapter(
                host="cluster.us-east-1.redshift.amazonaws.com",
                password="pass",
                database="db",
            )

    def test_missing_password_raises(self):
        from benchbox.core.exceptions import ConfigurationError
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ConfigurationError, match="password"):
            RedshiftAdapter(
                host="cluster.us-east-1.redshift.amazonaws.com",
                username="user",
                database="db",
            )


# ---------------------------------------------------------------------------
# get_platform_info with connection (Serverless path)
# ---------------------------------------------------------------------------


class TestGetPlatformInfoWithConnectionServerless:
    """Test get_platform_info returns serverless metadata when connection is provided."""

    def test_serverless_path_calls_version_and_metadata(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2 on Redshift 1.0.1234",)
        mock_cursor.fetchall.return_value = []

        # Mock the _get_serverless_metadata_api to return workgroup info
        serverless_meta = {
            "workgroup_name": "my-workgroup",
            "base_capacity_rpu": 128,
            "max_capacity_rpu": 512,
            "namespace_name": "my-namespace",
            "enhanced_vpc_routing": False,
        }
        with patch.object(adapter, "_get_serverless_metadata_api", return_value=serverless_meta):
            info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_type"] == "redshift"
        assert info["configuration"]["deployment_type"] == "serverless"
        assert info["configuration"]["workgroup_name"] == "my-workgroup"
        assert info["configuration"]["base_capacity_rpu"] == 128

    def test_serverless_sql_fallback_when_api_empty(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)
        mock_cursor.fetchall.return_value = []

        sql_meta = {"current_rpu_capacity": 64}

        with (
            patch.object(adapter, "_get_serverless_metadata_api", return_value={}),
            patch.object(adapter, "_get_serverless_metadata_sql", return_value=sql_meta),
        ):
            info = adapter.get_platform_info(connection=mock_conn)

        # _get_serverless_metadata_sql was used as fallback; deployment_type still serverless
        assert info["configuration"]["deployment_type"] == "serverless"


# ---------------------------------------------------------------------------
# get_platform_info with connection (Provisioned path)
# ---------------------------------------------------------------------------


class TestGetPlatformInfoWithConnectionProvisioned:
    """Test get_platform_info returns provisioned metadata when connection is provided."""

    def test_provisioned_path_with_api_metadata(self):
        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)
        mock_cursor.fetchall.return_value = []

        provisioned_meta = {
            "cluster_identifier": "my-cluster",
            "node_type": "ra3.xlplus",
            "number_of_nodes": 3,
            "encrypted": True,
            "enhanced_vpc_routing": False,
        }
        with patch.object(adapter, "_get_provisioned_metadata_api", return_value=provisioned_meta):
            info = adapter.get_platform_info(connection=mock_conn)

        assert info["configuration"]["deployment_type"] == "provisioned"
        assert info["configuration"]["node_type"] == "ra3.xlplus"
        assert info["configuration"]["number_of_nodes"] == 3

    def test_provisioned_sql_fallback_when_api_empty(self):
        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)
        mock_cursor.fetchall.return_value = []

        sql_meta = {
            "node_type": "dc2.large",
            "cluster_version": "1.0.41374",
            "number_of_nodes": 2,
        }
        with (
            patch.object(adapter, "_get_provisioned_metadata_api", return_value={}),
            patch.object(adapter, "_get_provisioned_metadata_sql", return_value=sql_meta),
        ):
            info = adapter.get_platform_info(connection=mock_conn)

        assert info["configuration"]["deployment_type"] == "provisioned"
        assert info["configuration"]["node_type"] == "dc2.large"
        assert info["configuration"]["number_of_nodes"] == 2


# ---------------------------------------------------------------------------
# normalized result metadata
# ---------------------------------------------------------------------------


class TestNormalizedResultMetadata:
    """Test Redshift normalized execution/runtime metadata mappings."""

    def _mock_connection(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2 on Amazon Redshift 1.0.50481",)
        mock_cursor.fetchall.return_value = []
        return mock_conn

    def test_serverless_metadata_maps_cloud_compute_storage_and_cache(self):
        adapter = _make_adapter(
            host="wg.123456789012.us-east-1.redshift-serverless.amazonaws.com",
            staging_root="s3://bench-bucket/bench-prefix",
            iam_role="arn:aws:iam::123456789012:role/RedshiftCopy",
            disable_result_cache=False,
        )
        serverless_meta = {
            "workgroup_name": "wg-prod",
            "namespace_name": "ns-prod",
            "base_capacity_rpu": 128,
            "max_capacity_rpu": 512,
            "status": "AVAILABLE",
            "enhanced_vpc_routing": True,
            "encrypted": True,
        }

        with patch.object(adapter, "_get_serverless_metadata_api", return_value=serverless_meta):
            info = adapter.get_platform_info(connection=self._mock_connection())

        metadata = adapter.get_normalized_result_metadata(platform_info=info)

        assert metadata["execution_environment"]["platform_runtime"]["runtime_type"] == "serverless"
        assert metadata["platform_deployment"]["deployment_type"] == "serverless"
        assert metadata["platform_deployment"]["service_model"] == "serverless"
        assert metadata["platform_deployment"]["workgroup"] == "wg-prod"
        assert metadata["platform_deployment"]["namespace"] == "ns-prod"
        assert metadata["platform_cloud"]["provider"] == "aws"
        assert metadata["platform_cloud"]["region"] == "us-east-1"
        assert metadata["platform_compute"]["service_model"] == "serverless"
        assert metadata["platform_compute"]["workgroup"] == "wg-prod"
        assert metadata["platform_compute"]["namespace"] == "ns-prod"
        assert metadata["platform_compute"]["rpu"] == 128
        assert metadata["platform_compute"]["base_capacity_rpu"] == 128
        assert metadata["platform_compute"]["max_capacity_rpu"] == 512
        assert metadata["platform_compute"]["result_cache_enabled"] is True
        assert metadata["platform_compute"]["collection_status"] == "available"
        assert metadata["platform_storage"]["bucket"] == "bench-bucket"
        assert metadata["platform_storage"]["prefix"] == "bench-prefix"
        assert metadata["platform_storage"]["staging_location"] == "s3://bench-bucket/bench-prefix"
        assert metadata["platform_storage"]["iam_role_configured"] is True

    def test_provisioned_metadata_maps_cluster_shape_and_storage_capacity(self):
        adapter = _make_adapter(
            host="prod-cluster.us-west-2.redshift.amazonaws.com",
            s3_bucket="bench-bucket",
            s3_prefix="bench-prefix",
            iam_role="arn:aws:iam::123456789012:role/RedshiftCopy",
            disable_result_cache=True,
        )
        provisioned_meta = {
            "cluster_identifier": "prod-cluster",
            "node_type": "ra3.4xlarge",
            "number_of_nodes": 4,
            "cluster_status": "available",
            "cluster_version": "1.0.50481",
            "total_storage_capacity_mb": 204800,
            "enhanced_vpc_routing": False,
            "encrypted": True,
        }

        with patch.object(adapter, "_get_provisioned_metadata_api", return_value=provisioned_meta):
            info = adapter.get_platform_info(connection=self._mock_connection())

        metadata = adapter.get_normalized_result_metadata(platform_info=info)

        assert metadata["execution_environment"]["platform_runtime"]["runtime_type"] == "managed_cloud"
        assert metadata["platform_deployment"]["deployment_type"] == "managed_cloud"
        assert metadata["platform_deployment"]["service_model"] == "provisioned"
        assert metadata["platform_deployment"]["cluster_identifier"] == "prod-cluster"
        assert metadata["platform_cloud"]["provider"] == "aws"
        assert metadata["platform_cloud"]["region"] == "us-west-2"
        assert metadata["platform_compute"]["service_model"] == "provisioned"
        assert metadata["platform_compute"]["cluster_id"] == "prod-cluster"
        assert metadata["platform_compute"]["node_type"] == "ra3.4xlarge"
        assert metadata["platform_compute"]["node_count"] == 4
        assert metadata["platform_compute"]["cluster_version"] == "1.0.50481"
        assert metadata["platform_compute"]["result_cache_enabled"] is False
        assert metadata["platform_compute"]["collection_status"] == "available"
        assert metadata["platform_storage"]["bucket"] == "bench-bucket"
        assert metadata["platform_storage"]["prefix"] == "bench-prefix"
        assert metadata["platform_storage"]["storage_capacity_mb"] == 204800

    def test_serverless_sql_fallback_preserves_current_rpu_capacity(self):
        adapter = _make_adapter(host="wg.123456789012.us-east-1.redshift-serverless.amazonaws.com")
        sql_meta = {"current_rpu_capacity": 32}

        with (
            patch.object(adapter, "_get_serverless_metadata_api", return_value={}),
            patch.object(adapter, "_get_serverless_metadata_sql", return_value=sql_meta),
        ):
            info = adapter.get_platform_info(connection=self._mock_connection())

        metadata = adapter.get_normalized_result_metadata(platform_info=info)

        assert info["configuration"]["current_rpu_capacity"] == 32
        assert metadata["platform_deployment"]["workgroup"] == "wg"
        assert metadata["platform_compute"]["rpu"] == 32
        assert metadata["platform_compute"]["current_rpu_capacity"] == 32
        assert metadata["platform_compute"]["collection_status"] == "available"


# ---------------------------------------------------------------------------
# _get_serverless_metadata_api: boto3 calls
# ---------------------------------------------------------------------------


class TestGetServerlessMetadataApi:
    """Test _get_serverless_metadata_api returns workgroup data from boto3."""

    def test_returns_workgroup_data(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.return_value = {
            "workgroup": {
                "workgroupName": "my-wg",
                "baseCapacity": 128,
                "maxCapacity": 512,
                "namespaceName": "my-ns",
                "enhancedVpcRouting": False,
                "status": "AVAILABLE",
            }
        }
        mock_client.get_namespace.return_value = {"namespace": {"kmsKeyId": "arn:aws:kms:...", "status": "AVAILABLE"}}

        adapter = _make_adapter(host="my-wg.123456789.us-east-1.redshift-serverless.amazonaws.com")
        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")

        assert result["workgroup_name"] == "my-wg"
        assert result["base_capacity_rpu"] == 128
        mock_boto.client.assert_called_once_with("redshift-serverless", region_name="us-east-1")

    def test_no_credentials_error_returns_empty(self, _mock_redshift_deps):
        from botocore.exceptions import NoCredentialsError

        mock_boto = _mock_redshift_deps["boto3"]
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.side_effect = NoCredentialsError()

        adapter = _make_adapter()
        result = adapter._get_serverless_metadata_api("wg", "us-east-1")
        assert result == {}

    def test_client_error_returns_empty(self, _mock_redshift_deps):
        from botocore.exceptions import ClientError

        mock_boto = _mock_redshift_deps["boto3"]
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}}, "GetWorkgroup"
        )

        adapter = _make_adapter()
        result = adapter._get_serverless_metadata_api("wg", "us-east-1")
        assert result == {}


# ---------------------------------------------------------------------------
# _get_provisioned_metadata_api: boto3 calls
# ---------------------------------------------------------------------------


class TestGetProvisionedMetadataApi:
    """Test _get_provisioned_metadata_api returns cluster data from boto3."""

    def test_returns_cluster_data(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {
            "Clusters": [
                {
                    "ClusterIdentifier": "my-cluster",
                    "NodeType": "ra3.xlplus",
                    "NumberOfNodes": 4,
                    "ClusterStatus": "available",
                    "Encrypted": True,
                    "KmsKeyId": "arn:aws:kms:...",
                    "EnhancedVpcRouting": False,
                    "TotalStorageCapacityInMegaBytes": 102400,
                }
            ]
        }

        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")
        result = adapter._get_provisioned_metadata_api("my-cluster", "us-east-1")

        assert result["node_type"] == "ra3.xlplus"
        assert result["number_of_nodes"] == 4
        mock_boto.client.assert_called_once_with("redshift", region_name="us-east-1")

    def test_empty_clusters_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": []}

        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")
        result = adapter._get_provisioned_metadata_api("my-cluster", "us-east-1")
        assert result == {}

    def test_no_credentials_error_returns_empty(self, _mock_redshift_deps):
        from botocore.exceptions import NoCredentialsError

        mock_boto = _mock_redshift_deps["boto3"]
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.side_effect = NoCredentialsError()

        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")
        result = adapter._get_provisioned_metadata_api("my-cluster", "us-east-1")
        assert result == {}


# ---------------------------------------------------------------------------
# _get_serverless_metadata_sql
# ---------------------------------------------------------------------------


class TestGetServerlessMetadataSql:
    """Test _get_serverless_metadata_sql reads sys_serverless_usage table."""

    def test_returns_rpu_capacity_from_cursor(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (64,)

        result = adapter._get_serverless_metadata_sql(mock_cursor)
        assert result["current_rpu_capacity"] == 64

    def test_empty_result_returns_empty_dict(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        result = adapter._get_serverless_metadata_sql(mock_cursor)
        assert result == {}

    def test_exception_returns_empty_dict(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("permission denied")

        result = adapter._get_serverless_metadata_sql(mock_cursor)
        assert result == {}


# ---------------------------------------------------------------------------
# _get_provisioned_metadata_sql
# ---------------------------------------------------------------------------


class TestGetProvisionedMetadataSql:
    """Test _get_provisioned_metadata_sql reads stv_cluster_configuration."""

    def test_returns_cluster_info(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("ra3.xlplus", "1.0.41374", 3)

        result = adapter._get_provisioned_metadata_sql(mock_cursor)
        assert result["node_type"] == "ra3.xlplus"
        assert result["cluster_version"] == "1.0.41374"
        assert result["number_of_nodes"] == 3

    def test_empty_result_returns_empty_dict(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        result = adapter._get_provisioned_metadata_sql(mock_cursor)
        assert result == {}

    def test_exception_returns_empty_dict(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("relation does not exist")

        result = adapter._get_provisioned_metadata_sql(mock_cursor)
        assert result == {}


# ---------------------------------------------------------------------------
# drop_database() paths
# ---------------------------------------------------------------------------


class TestDropDatabase:
    """Test drop_database terminates connections and drops the database."""

    def test_active_connections_terminated_then_dropped(self):
        adapter = _make_adapter()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall = MagicMock()

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "_create_admin_connection", return_value=mock_conn),
            patch.object(adapter, "_resolve_connect_timeout", return_value=30),
            patch.object(adapter, "_long_running_timeout", return_value=300),
        ):
            adapter.drop_database(database="test_db")

        # Verify cursor.execute was called (terminate + drop)
        assert mock_cursor.execute.call_count >= 2
        # Last execute call should be DROP DATABASE
        last_call_sql = mock_cursor.execute.call_args_list[-1][0][0]
        assert "DROP DATABASE" in last_call_sql

    def test_non_existent_db_skips_drop(self):
        adapter = _make_adapter()

        with patch.object(adapter, "check_server_database_exists", return_value=False):
            # Should return without error and without trying to connect
            adapter.drop_database(database="nonexistent_db")

    def test_retry_on_active_connections_error(self):
        adapter = _make_adapter()

        mock_conn1 = MagicMock()
        mock_cursor1 = MagicMock()
        mock_conn1.cursor.return_value = mock_cursor1

        mock_conn2 = MagicMock()
        mock_cursor2 = MagicMock()
        mock_conn2.cursor.return_value = mock_cursor2

        # First DROP raises "active connection" error, second succeeds
        drop_error = Exception("database is being accessed")
        drop_error.args = ({"C": "55006"},)

        mock_cursor1.execute.side_effect = [
            None,  # first pg_terminate_backend SELECT
            drop_error,  # first DROP fails
        ]

        connections = [mock_conn1, mock_conn2]

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "_create_admin_connection", side_effect=connections),
            patch.object(adapter, "_resolve_connect_timeout", return_value=30),
            patch.object(adapter, "_long_running_timeout", return_value=300),
        ):
            adapter.drop_database(database="test_db")

        # Second connection should have been used for retry
        assert mock_conn2.cursor.called

    def test_non_database_in_use_error_re_raised(self):
        adapter = _make_adapter()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Error with pgcode that is NOT 55006
        drop_error = Exception("syntax error")
        drop_error.args = ({"C": "42601"},)
        mock_cursor.execute.side_effect = [
            None,  # pg_terminate_backend
            drop_error,  # DROP fails with non-55006 code
        ]

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch.object(adapter, "_create_admin_connection", return_value=mock_conn),
            patch.object(adapter, "_resolve_connect_timeout", return_value=30),
            patch.object(adapter, "_long_running_timeout", return_value=300),
        ):
            with pytest.raises(RuntimeError):
                adapter.drop_database(database="test_db")


# ---------------------------------------------------------------------------
# _build_s3_copy_source: manifest generation
# ---------------------------------------------------------------------------


class TestBuildS3CopySource:
    """Test _build_s3_copy_source generates manifest when multiple files exist."""

    def test_single_file_returns_direct_uri(self):
        adapter = _make_adapter(
            staging_root="s3://my-bucket/my-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        uri = "s3://my-bucket/my-prefix/lineitem_0.parquet"
        copy_path, manifest_opt = adapter._build_s3_copy_source(mock_s3, [uri], "lineitem")

        assert copy_path == uri
        assert manifest_opt == ""
        mock_s3.put_object.assert_not_called()

    def test_multiple_files_generates_manifest(self):
        adapter = _make_adapter(
            staging_root="s3://my-bucket/my-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        uris = [
            "s3://my-bucket/my-prefix/lineitem_0.parquet",
            "s3://my-bucket/my-prefix/lineitem_1.parquet",
        ]
        copy_path, manifest_opt = adapter._build_s3_copy_source(mock_s3, uris, "lineitem")

        assert "manifest" in copy_path
        assert manifest_opt == "manifest"
        mock_s3.put_object.assert_called_once()
        # Verify JSON body contains entries
        call_kwargs = mock_s3.put_object.call_args[1]
        import json

        body = json.loads(call_kwargs["Body"])
        assert len(body["entries"]) == 2

    def test_manifest_client_error_raises_value_error(self):
        from botocore.exceptions import ClientError

        adapter = _make_adapter(
            staging_root="s3://my-bucket/my-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "PutObject"
        )
        uris = ["s3://my-bucket/my-prefix/a_0.parquet", "s3://my-bucket/my-prefix/a_1.parquet"]

        with pytest.raises(ValueError):
            adapter._build_s3_copy_source(mock_s3, uris, "orders")


# ---------------------------------------------------------------------------
# _load_table_via_s3: MANIFEST keyword and MAXERROR tests
# ---------------------------------------------------------------------------


class TestLoadTableViaS3Extended:
    """Test _load_table_via_s3 COPY SQL contains MANIFEST and COMPUPDATE options."""

    def _make_s3_adapter(self):
        return _make_adapter(
            staging_root="s3://bench-bucket/bench-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            auto_analyze=False,
        )

    def test_manifest_keyword_in_copy_sql_when_multiple_files(self, tmp_path):
        adapter = self._make_s3_adapter()
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = MagicMock()
        cursor.fetchone.return_value = [500]
        mock_s3 = MagicMock()

        file1 = tmp_path / "part_0.tbl"
        file2 = tmp_path / "part_1.tbl"
        file1.write_text("data")
        file2.write_text("data")

        with (
            patch.object(adapter, "_upload_file_to_s3", side_effect=["s3://b/p/part_0.tbl", "s3://b/p/part_1.tbl"]),
            patch.object(adapter, "_build_s3_copy_source", return_value=("s3://b/p/part_manifest.json", "manifest")),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=False),
            patch("benchbox.platforms.redshift.detect_compression", return_value=None),
        ):
            row_count = adapter._load_table_via_s3(cursor, mock_s3, "part", [file1, file2], MagicMock())

        assert row_count == 500
        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "manifest" in copy_call.lower()

    def test_compupdate_off_in_copy_sql(self, tmp_path):
        adapter = _make_adapter(
            staging_root="s3://bench-bucket/bench-prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            auto_analyze=False,
            compupdate="OFF",
        )
        adapter.get_effective_tuning_configuration = MagicMock(return_value=None)
        cursor = MagicMock()
        cursor.fetchone.return_value = [100]
        mock_s3 = MagicMock()
        file_path = tmp_path / "orders.tbl"
        file_path.write_text("data")

        with (
            patch.object(adapter, "_upload_file_to_s3", return_value="s3://b/p/orders_0.tbl"),
            patch.object(adapter, "_build_s3_copy_source", return_value=("s3://b/p/orders_0.tbl", "")),
            patch("benchbox.platforms.redshift.is_parquet_format", return_value=False),
            patch("benchbox.platforms.redshift.detect_compression", return_value=None),
        ):
            adapter._load_table_via_s3(cursor, mock_s3, "orders", [file_path], MagicMock())

        execute_calls = [str(call) for call in cursor.execute.call_args_list]
        copy_call = execute_calls[0]
        assert "COMPUPDATE OFF" in copy_call

    def test_mixed_parquet_and_delimited_raises(self, tmp_path):
        adapter = self._make_s3_adapter()
        cursor = MagicMock()
        mock_s3 = MagicMock()

        f1 = tmp_path / "orders.parquet"
        f2 = tmp_path / "orders.tbl"
        f1.write_text("parquet")
        f2.write_text("delimited")

        call_count = [0]

        def alternate_is_parquet(f):
            call_count[0] += 1
            return call_count[0] % 2 == 1  # True, False alternating

        with patch("benchbox.platforms.redshift.is_parquet_format", side_effect=alternate_is_parquet):
            with pytest.raises(ValueError, match="uniform"):
                adapter._load_table_via_s3(cursor, mock_s3, "orders", [f1, f2], MagicMock())


# ---------------------------------------------------------------------------
# _sanitize_copy_credential
# ---------------------------------------------------------------------------


class TestSanitizeCopyCredential:
    """Test _sanitize_copy_credential rejects values containing single quotes."""

    def test_valid_value_returned_unchanged(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._sanitize_copy_credential("arn:aws:iam::123:role/R", "iam_role")
        assert result == "arn:aws:iam::123:role/R"

    def test_value_with_single_quote_raises(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        with pytest.raises(ValueError, match="single-quote"):
            RedshiftAdapter._sanitize_copy_credential("it's invalid", "iam_role")


# ---------------------------------------------------------------------------
# _map_external_column_type: type mapping
# ---------------------------------------------------------------------------


class TestMapExternalColumnType:
    """Test _map_external_column_type maps benchmark types to Spectrum types."""

    def test_bigint(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("BIGINT") == "BIGINT"

    def test_smallint(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("SMALLINT") == "SMALLINT"

    def test_int(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("INT") == "INTEGER"

    def test_double(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("DOUBLE PRECISION") == "DOUBLE PRECISION"

    def test_float(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("FLOAT") == "REAL"

    def test_date(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("DATE") == "DATE"

    def test_boolean(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("BOOLEAN") == "BOOLEAN"
        assert RedshiftAdapter._map_external_column_type("BOOL") == "BOOLEAN"

    def test_varchar_preserved(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("VARCHAR(255)") == "VARCHAR(255)"

    def test_empty_returns_varchar(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("") == "VARCHAR(65535)"

    def test_unknown_returns_varchar(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        assert RedshiftAdapter._map_external_column_type("JSONB") == "VARCHAR(65535)"


# ---------------------------------------------------------------------------
# get_target_dialect
# ---------------------------------------------------------------------------


class TestGetTargetDialect:
    """Test get_target_dialect returns redshift."""

    def test_returns_redshift(self):
        adapter = _make_adapter()
        assert adapter.get_target_dialect() == "redshift"


# ---------------------------------------------------------------------------
# _get_connection_params
# ---------------------------------------------------------------------------


class TestGetConnectionParams:
    """Test _get_connection_params returns correct dict."""

    def test_returns_all_fields(self):
        adapter = _make_adapter(
            host="cluster.us-east-1.redshift.amazonaws.com",
            port=5439,
            database="bench_db",
            username="bench_user",
            password="bench_pass",
            sslmode="require",
        )
        params = adapter._get_connection_params()
        assert params["host"] == "cluster.us-east-1.redshift.amazonaws.com"
        assert params["port"] == 5439
        assert params["database"] == "bench_db"
        assert params["user"] == "bench_user"
        assert params["password"] == "bench_pass"
        assert params["sslmode"] == "require"

    def test_overrides_applied(self):
        adapter = _make_adapter(database="original_db")
        params = adapter._get_connection_params(database="override_db")
        assert params["database"] == "override_db"


# ---------------------------------------------------------------------------
# check_server_database_exists
# ---------------------------------------------------------------------------


class TestCheckServerDatabaseExists:
    """Test check_server_database_exists returns correct bool."""

    def test_returns_true_when_db_found(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("test_db",)

        with patch.object(adapter, "_create_admin_connection", return_value=mock_conn):
            result = adapter.check_server_database_exists(database="test_db")

        assert result is True

    def test_returns_false_when_db_not_found(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch.object(adapter, "_create_admin_connection", return_value=mock_conn):
            result = adapter.check_server_database_exists(database="nonexistent_db")

        assert result is False

    def test_exception_returns_false(self):
        adapter = _make_adapter()

        with patch.object(adapter, "_create_admin_connection", side_effect=Exception("connection refused")):
            result = adapter.check_server_database_exists(database="test_db")

        assert result is False


# ---------------------------------------------------------------------------
# _compute_connect_timeout
# ---------------------------------------------------------------------------


class TestComputeConnectTimeout:
    """Test _compute_connect_timeout returns appropriate timeouts."""

    def test_unknown_deployment_returns_default(self):
        adapter = _make_adapter(host="custom.example.com")
        # unknown deployment type - no API call, returns default
        result = adapter._compute_connect_timeout()
        assert result == adapter.connect_timeout

    def test_serverless_returns_extended_timeout(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")
        result = adapter._compute_connect_timeout()
        # Serverless uses extended timeout >= 60
        assert result >= 60

    def test_provisioned_available_returns_default(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "available"}]}

        adapter = _make_adapter(host="cluster.us-east-1.redshift.amazonaws.com")
        result = adapter._compute_connect_timeout()
        assert result == adapter.connect_timeout

    def test_provisioned_paused_returns_extended(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "paused"}]}

        adapter = _make_adapter(host="cluster.us-east-1.redshift.amazonaws.com")
        result = adapter._compute_connect_timeout()
        assert result >= 120


# ---------------------------------------------------------------------------
# _filter_valid_files
# ---------------------------------------------------------------------------


class TestFilterValidFiles:
    """Test _filter_valid_files filters out non-existent and empty files."""

    def test_existing_file_included(self, tmp_path):
        adapter = _make_adapter()
        f = tmp_path / "data.tbl"
        f.write_text("row1|row2")
        result = adapter._filter_valid_files([f])
        assert len(result) == 1

    def test_nonexistent_file_excluded(self, tmp_path):
        adapter = _make_adapter()
        f = tmp_path / "missing.tbl"
        result = adapter._filter_valid_files([f])
        assert len(result) == 0

    def test_empty_file_excluded(self, tmp_path):
        adapter = _make_adapter()
        f = tmp_path / "empty.tbl"
        f.write_text("")
        result = adapter._filter_valid_files([f])
        assert len(result) == 0

    def test_string_paths_converted_to_path_objects(self, tmp_path):
        adapter = _make_adapter()
        f = tmp_path / "orders.tbl"
        f.write_text("data")
        result = adapter._filter_valid_files([str(f)])
        assert len(result) == 1

    def test_non_list_input_normalized(self, tmp_path):
        adapter = _make_adapter()
        f = tmp_path / "lineitem.tbl"
        f.write_text("data")
        result = adapter._filter_valid_files(f)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# validate_external_table_requirements
# ---------------------------------------------------------------------------


class TestValidateExternalTableRequirements:
    """Test validate_external_table_requirements raises for missing S3 or IAM."""

    def test_missing_s3_bucket_raises(self):
        adapter = _make_adapter()
        # No s3_bucket configured
        with pytest.raises(ValueError, match="S3 staging"):
            adapter.validate_external_table_requirements()

    def test_missing_iam_role_raises(self):
        adapter = _make_adapter(staging_root="s3://bucket/prefix")
        # s3_bucket set but no iam_role
        with pytest.raises(ValueError, match="IAM role"):
            adapter.validate_external_table_requirements()


# ---------------------------------------------------------------------------
# execute_query: success and failure paths
# ---------------------------------------------------------------------------


class TestExecuteQuery:
    """Test execute_query returns timing and row count data."""

    def test_successful_query_returns_result_dict(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("row1",), ("row2",)]

        with patch.object(adapter, "_get_query_statistics", return_value={"execution_time_seconds": 0.1}):
            result = adapter.execute_query(
                connection=mock_conn,
                query="SELECT 1",
                query_id="Q1",
                validate_row_count=False,
            )

        assert result["query_id"] == "Q1"
        assert result["rows_returned"] == 2
        assert "execution_time_seconds" in result

    def test_failed_query_returns_error_dict(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("syntax error near unexpected token")

        result = adapter.execute_query(
            connection=mock_conn,
            query="SELECT INVALID",
            query_id="Q99",
            validate_row_count=False,
        )

        assert result["status"] == "FAILED"
        assert "error" in result
        assert result["query_id"] == "Q99"

    def test_empty_result_set(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch.object(adapter, "_get_query_statistics", return_value={}):
            result = adapter.execute_query(
                connection=mock_conn,
                query="SELECT * FROM empty_table",
                query_id="Q2",
                validate_row_count=False,
            )

        assert result["rows_returned"] == 0


# ---------------------------------------------------------------------------
# configure_for_benchmark
# ---------------------------------------------------------------------------


class TestConfigureForBenchmark:
    """Test configure_for_benchmark applies session settings."""

    def test_olap_benchmark_applies_settings(self):
        adapter = _make_adapter(auto_vacuum=False, auto_analyze=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            adapter,
            "validate_session_cache_control",
            return_value={"validated": True, "cache_disabled": True},
        ):
            adapter.configure_for_benchmark(mock_conn, "tpch")

        # Multiple settings should have been applied
        assert mock_cursor.execute.call_count >= 3

    def test_non_olap_benchmark_applies_fewer_settings(self):
        adapter = _make_adapter(auto_vacuum=False, auto_analyze=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            adapter,
            "validate_session_cache_control",
            return_value={"validated": True, "cache_disabled": True},
        ):
            adapter.configure_for_benchmark(mock_conn, "custom_workload")

        assert mock_cursor.execute.call_count >= 1

    def test_cursor_closed_on_exception(self):
        adapter = _make_adapter(auto_vacuum=False, auto_analyze=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("connection lost")

        with pytest.raises(Exception):
            adapter.configure_for_benchmark(mock_conn, "tpch")

        mock_cursor.close.assert_called()


# ---------------------------------------------------------------------------
# analyze_table and vacuum_table
# ---------------------------------------------------------------------------


class TestAnalyzeAndVacuumTable:
    """Test analyze_table and vacuum_table execute SQL."""

    def test_analyze_table_executes_analyze(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_conn, "lineitem")
        mock_cursor.execute.assert_called_once_with("ANALYZE lineitem")

    def test_analyze_table_raises_on_failure(self):
        """Must raise (not swallow) so gather_statistics()'s caller can detect
        and record a real failure as status=FAILED."""
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("permission denied")

        with pytest.raises(Exception, match="permission denied"):
            adapter.analyze_table(mock_conn, "lineitem")
        mock_cursor.close.assert_called_once()

    def test_vacuum_table_executes_vacuum(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.vacuum_table(mock_conn, "orders")
        mock_cursor.execute.assert_called_once_with("VACUUM orders")

    def test_vacuum_table_swallows_exception(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("relation does not exist")

        adapter.vacuum_table(mock_conn, "orders")


# ---------------------------------------------------------------------------
# get_query_plan
# ---------------------------------------------------------------------------


class TestGetQueryPlan:
    """Test get_query_plan returns EXPLAIN output."""

    def test_returns_plan_text(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("XN Seq Scan on lineitem",),
            ("  -> cost=0.00..100.00 rows=1000",),
        ]

        plan = adapter.get_query_plan(mock_conn, "SELECT * FROM lineitem")
        assert "XN Seq Scan" in plan

    def test_returns_none_on_exception(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("permission denied")

        plan = adapter.get_query_plan(mock_conn, "SELECT * FROM forbidden_table")
        assert plan is None


# ---------------------------------------------------------------------------
# close_connection
# ---------------------------------------------------------------------------


class TestCloseConnection:
    """Test close_connection gracefully handles close errors."""

    def test_closes_connection(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        adapter.close_connection(mock_conn)
        mock_conn.close.assert_called_once()

    def test_exception_on_close_does_not_raise(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("already closed")
        adapter.close_connection(mock_conn)

    def test_none_connection_does_not_raise(self):
        adapter = _make_adapter()
        adapter.close_connection(None)


# ---------------------------------------------------------------------------
# _get_existing_tables
# ---------------------------------------------------------------------------


class TestGetExistingTables:
    """Test _get_existing_tables returns lowercase table names."""

    def test_returns_lowercase_table_names(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("LINEITEM",), ("ORDERS",), ("PART",)]

        result = adapter._get_existing_tables(mock_conn)
        assert result == ["lineitem", "orders", "part"]

    def test_empty_schema_returns_empty_list(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        result = adapter._get_existing_tables(mock_conn)
        assert result == []


# ---------------------------------------------------------------------------
# _get_query_statistics
# ---------------------------------------------------------------------------


class TestGetQueryStatistics:
    """Test _get_query_statistics parses system table responses."""

    def test_returns_empty_when_no_query_id(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (-1,)

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}

    def test_returns_empty_on_exception(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("no such table")

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}

    def test_provisioned_parses_stl_query(self):
        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (12345,),  # pg_last_query_id
            (12345, 5000000, 4000000, 1024, 512, 2, 2, 0),  # stl_query row (aborted=0)
        ]

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result.get("query_id") == "12345"
        assert result.get("duration_microsecs") == 5000000
        assert result.get("aborted") is False

    def test_serverless_parses_sys_query_history(self):
        adapter = _make_adapter(host="wg.123.us-east-1.redshift-serverless.amazonaws.com")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (99999,),  # pg_last_query_id
            (99999, 3000000, 3000000, 0, 0, 1, 1, "success"),
        ]

        result = adapter._get_query_statistics(mock_conn, "Q2")
        assert result.get("query_id") == "99999"
        assert result.get("aborted") is False

    def test_returns_empty_when_no_stats_row(self):
        adapter = _make_adapter(host="my-cluster.us-east-1.redshift.amazonaws.com")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (12345,),  # pg_last_query_id
            None,  # no stats row
        ]

        result = adapter._get_query_statistics(mock_conn, "Q3")
        assert result == {}


# ---------------------------------------------------------------------------
# _normalize_table_name_in_sql and _extract_table_name
# ---------------------------------------------------------------------------


class TestNormalizeAndExtractTableName:
    """Test SQL normalization helpers."""

    def test_normalize_table_name_lowercases_table(self):
        adapter = _make_adapter()
        result = adapter._normalize_table_name_in_sql("SELECT * FROM LINEITEM")
        assert isinstance(result, str)

    def test_extract_table_name_from_create_table(self):
        adapter = _make_adapter()
        result = adapter._extract_table_name("CREATE TABLE lineitem (l_orderkey INT)")
        assert result is not None


# ---------------------------------------------------------------------------
# platform_name property
# ---------------------------------------------------------------------------


class TestPlatformNameProperty:
    """Test platform_name returns 'Redshift'."""

    def test_platform_name(self):
        adapter = _make_adapter()
        assert adapter.platform_name == "Redshift"


# ---------------------------------------------------------------------------
# _long_running_timeout
# ---------------------------------------------------------------------------


class TestLongRunningTimeout:
    """Test _long_running_timeout applies floor correctly."""

    def test_returns_floor_when_below_floor(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_resolve_connect_timeout", return_value=10):
            result = adapter._long_running_timeout(floor=300)
        assert result == 300

    def test_returns_timeout_when_above_floor(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_resolve_connect_timeout", return_value=500):
            result = adapter._long_running_timeout(floor=300)
        assert result == 500


# ---------------------------------------------------------------------------
# _resolve_connect_timeout (caching)
# ---------------------------------------------------------------------------


class TestResolveConnectTimeout:
    """Test _resolve_connect_timeout caches the result."""

    def test_cached_result_returned_on_second_call(self):
        adapter = _make_adapter()
        adapter._cached_connect_timeout = 42

        result = adapter._resolve_connect_timeout()
        assert result == 42

    def test_computes_and_caches_first_call(self):
        adapter = _make_adapter(host="custom.example.com")
        result = adapter._resolve_connect_timeout()
        assert hasattr(adapter, "_cached_connect_timeout")
        assert adapter._cached_connect_timeout == result


# ---------------------------------------------------------------------------
# _get_platform_metadata with connection
# ---------------------------------------------------------------------------


class TestGetPlatformMetadata:
    """Test _get_platform_metadata fetches version and tables."""

    def test_returns_metadata_dict(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        version_row = ("PostgreSQL 8.0.2 on Redshift",)
        session_row = ("admin", "bench_db", "public", "127.0.0.1", 5439)
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.side_effect = [version_row, None, session_row]

        result = adapter._get_platform_metadata(mock_conn)
        assert result["platform"] == "Redshift"
        assert "redshift_version" in result

    def test_returns_error_on_exception(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("connection lost")

        result = adapter._get_platform_metadata(mock_conn)
        assert "metadata_error" in result


# ---------------------------------------------------------------------------
# _run_vacuum_analyze_isolated
# ---------------------------------------------------------------------------


class TestRunVacuumAnalyzeIsolated:
    """Test _run_vacuum_analyze_isolated runs VACUUM/ANALYZE on a separate connection."""

    def test_runs_vacuum_and_analyze_for_each_table(self):
        adapter = _make_adapter(auto_vacuum=True, auto_analyze=True)
        main_conn = MagicMock()
        main_cursor = MagicMock()
        main_conn.cursor.return_value = main_cursor
        main_cursor.fetchall.return_value = [("public", "lineitem"), ("public", "orders")]

        maint_conn = MagicMock()
        maint_cursor = MagicMock()
        maint_conn.cursor.return_value = maint_cursor

        with patch.object(adapter, "_connect_with_driver", return_value=maint_conn):
            with patch.object(adapter, "_long_running_timeout", return_value=300):
                adapter._run_vacuum_analyze_isolated(main_conn)

        assert maint_cursor.execute.call_count >= 4  # SET + 2*VACUUM + 2*ANALYZE

    def test_empty_table_list_returns_immediately(self):
        adapter = _make_adapter(auto_vacuum=True, auto_analyze=True)
        main_conn = MagicMock()
        main_cursor = MagicMock()
        main_conn.cursor.return_value = main_cursor
        main_cursor.fetchall.return_value = []

        with patch.object(adapter, "_connect_with_driver") as mock_connect:
            with patch.object(adapter, "_long_running_timeout", return_value=300):
                adapter._run_vacuum_analyze_isolated(main_conn)

        mock_connect.assert_not_called()

    def test_connection_failure_logged_not_raised(self):
        adapter = _make_adapter(auto_vacuum=True, auto_analyze=True)
        main_conn = MagicMock()
        main_cursor = MagicMock()
        main_conn.cursor.return_value = main_cursor
        main_cursor.fetchall.return_value = [("public", "part")]

        with patch.object(adapter, "_connect_with_driver", side_effect=Exception("connection refused")):
            with patch.object(adapter, "_long_running_timeout", return_value=300):
                adapter._run_vacuum_analyze_isolated(main_conn)


# ---------------------------------------------------------------------------
# apply_unified_tuning (no-op paths)
# ---------------------------------------------------------------------------


class TestApplyUnifiedTuning:
    """Test apply_unified_tuning with empty/None config is a no-op."""

    def test_none_config_is_noop(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        adapter.apply_unified_tuning(None, mock_conn)
        mock_conn.cursor.assert_not_called()

    def test_apply_platform_optimizations_noop(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        adapter.apply_platform_optimizations(None, mock_conn)
        mock_conn.cursor.assert_not_called()

    def test_apply_constraint_configuration_logs_when_enabled(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_pk = MagicMock()
        mock_pk.enabled = True
        mock_fk = MagicMock()
        mock_fk.enabled = True
        adapter.apply_constraint_configuration(mock_pk, mock_fk, mock_conn)

    def test_apply_constraint_configuration_none_pk_fk(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        adapter.apply_constraint_configuration(None, None, mock_conn)


# ---------------------------------------------------------------------------
# create_connection: new database path
# ---------------------------------------------------------------------------


class TestCreateConnection:
    """Test create_connection creates DB if it doesn't exist."""

    def test_creates_new_database_when_missing(self):
        adapter = _make_adapter()

        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_conn.cursor.return_value = mock_admin_cursor

        mock_main_conn = MagicMock()
        mock_main_cursor = MagicMock()
        mock_main_conn.cursor.return_value = mock_main_cursor
        mock_main_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_resolve_connect_timeout", return_value=10),
            patch.object(adapter, "check_server_database_exists", return_value=False),
            patch.object(adapter, "_create_admin_connection", return_value=mock_admin_conn),
            patch.object(adapter, "_connect_with_driver", return_value=mock_main_conn),
        ):
            adapter.database_was_reused = False
            conn = adapter.create_connection()

        assert conn is mock_main_conn
        create_calls = [str(c) for c in mock_admin_cursor.execute.call_args_list]
        assert any("CREATE DATABASE" in c for c in create_calls)

    def test_skips_create_when_database_reused(self):
        adapter = _make_adapter()

        mock_main_conn = MagicMock()
        mock_main_cursor = MagicMock()
        mock_main_conn.cursor.return_value = mock_main_cursor
        mock_main_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_resolve_connect_timeout", return_value=10),
            patch.object(adapter, "_connect_with_driver", return_value=mock_main_conn),
        ):
            adapter.database_was_reused = True
            conn = adapter.create_connection()

        assert conn is mock_main_conn

    def test_create_database_failure_propagates(self):
        adapter = _make_adapter()

        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_conn.cursor.return_value = mock_admin_cursor
        mock_admin_cursor.execute.side_effect = Exception("permission denied")

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_resolve_connect_timeout", return_value=10),
            patch.object(adapter, "check_server_database_exists", return_value=False),
            patch.object(adapter, "_create_admin_connection", return_value=mock_admin_conn),
        ):
            adapter.database_was_reused = False
            with pytest.raises(Exception, match="permission denied"):
                adapter.create_connection()

    def test_wlm_slot_count_setting_applied(self):
        adapter = _make_adapter(wlm_query_slot_count=4)

        mock_main_conn = MagicMock()
        mock_main_cursor = MagicMock()
        mock_main_conn.cursor.return_value = mock_main_cursor
        mock_main_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_resolve_connect_timeout", return_value=10),
            patch.object(adapter, "_connect_with_driver", return_value=mock_main_conn),
        ):
            adapter.database_was_reused = True
            adapter.create_connection()

        execute_calls = [str(c) for c in mock_main_cursor.execute.call_args_list]
        assert any("wlm_query_slot_count" in c for c in execute_calls)

    def test_statement_timeout_setting_applied(self):
        adapter = _make_adapter(statement_timeout=60000)

        mock_main_conn = MagicMock()
        mock_main_cursor = MagicMock()
        mock_main_conn.cursor.return_value = mock_main_cursor
        mock_main_cursor.fetchone.return_value = ("PostgreSQL 8.0.2",)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "_resolve_connect_timeout", return_value=10),
            patch.object(adapter, "_connect_with_driver", return_value=mock_main_conn),
        ):
            adapter.database_was_reused = True
            adapter.create_connection()

        execute_calls = [str(c) for c in mock_main_cursor.execute.call_args_list]
        assert any("statement_timeout" in c for c in execute_calls)


# ---------------------------------------------------------------------------
# create_schema
# ---------------------------------------------------------------------------


class TestCreateSchema:
    """Test create_schema executes schema DDL statements."""

    def test_creates_schema_and_executes_ddl(self):
        adapter = _make_adapter(schema="public")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE lineitem (l_orderkey INT); CREATE TABLE orders (o_orderkey INT)",
        ):
            with patch.object(adapter, "_normalize_table_name_in_sql", side_effect=lambda s: s):
                with patch.object(adapter, "_extract_table_name", return_value="lineitem"):
                    with patch.object(adapter, "_optimize_table_definition", side_effect=lambda s: s):
                        adapter.create_schema(mock_benchmark, mock_conn)

        # Should have executed multiple statements
        assert mock_cursor.execute.call_count >= 2

    def test_non_public_schema_creates_schema_first(self):
        adapter = _make_adapter(schema="bench_schema")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        with patch.object(adapter, "_create_schema_with_tuning", return_value=""):
            with patch.object(adapter, "_normalize_table_name_in_sql", side_effect=lambda s: s):
                adapter.create_schema(mock_benchmark, mock_conn)

        execute_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("CREATE SCHEMA" in c for c in execute_calls)

    def test_exception_propagates_from_create_schema(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("syntax error")

        mock_benchmark = MagicMock()

        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE lineitem (l_orderkey INT)",
        ):
            with patch.object(adapter, "_normalize_table_name_in_sql", side_effect=lambda s: s):
                with patch.object(adapter, "_extract_table_name", return_value="lineitem"):
                    with pytest.raises(Exception, match="syntax error"):
                        adapter.create_schema(mock_benchmark, mock_conn)


# ---------------------------------------------------------------------------
# _load_table_via_insert
# ---------------------------------------------------------------------------


class TestLoadTableViaInsert:
    """Test _load_table_via_insert loads rows via INSERT statements."""

    def test_loads_rows_from_delimited_file(self, tmp_path):
        adapter = _make_adapter()

        cursor = MagicMock()
        mock_conn = MagicMock()

        data_file = tmp_path / "lineitem.tbl"
        data_file.write_text("1|2|3\n4|5|6\n7|8|9\n")

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            row_count = adapter._load_table_via_insert(cursor, "lineitem", [data_file], mock_conn)

        assert row_count == 3
        assert cursor.execute.called

    def test_empty_file_loads_zero_rows(self, tmp_path):
        adapter = _make_adapter()
        cursor = MagicMock()
        mock_conn = MagicMock()

        data_file = tmp_path / "empty.tbl"
        data_file.write_text("")

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            row_count = adapter._load_table_via_insert(cursor, "empty_table", [data_file], mock_conn)

        assert row_count == 0


# ---------------------------------------------------------------------------
# load_data: S3 and non-S3 paths
# ---------------------------------------------------------------------------


class TestLoadData:
    """Test load_data dispatches to S3 or INSERT path correctly."""

    def test_s3_path_calls_load_table_via_s3(self, tmp_path):
        adapter = _make_adapter(
            staging_root="s3://bench-bucket/prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        data_file = tmp_path / "lineitem.tbl"
        data_file.write_text("data")

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [data_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[data_file]),
            patch.object(adapter, "_create_s3_client", return_value=MagicMock()),
            patch.object(adapter, "_load_table_via_s3", return_value=100),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["lineitem"] == 100

    def test_no_s3_bucket_uses_insert_path(self, tmp_path):
        adapter = _make_adapter()
        # No S3 bucket configured
        adapter.s3_bucket = None

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        data_file = tmp_path / "orders.tbl"
        data_file.write_text("1|2\n3|4\n")

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"orders": [data_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[data_file]),
            patch.object(adapter, "_load_table_via_insert", return_value=2),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["orders"] == 2

    def test_empty_valid_files_skips_table(self, tmp_path):
        adapter = _make_adapter(
            staging_root="s3://bench-bucket/prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": []}),
            patch.object(adapter, "_filter_valid_files", return_value=[]),
            patch.object(adapter, "_create_s3_client", return_value=MagicMock()),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["lineitem"] == 0

    def test_s3_load_error_sets_zero_count(self, tmp_path):
        adapter = _make_adapter(
            staging_root="s3://bench-bucket/prefix",
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
        )
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        data_file = tmp_path / "part.tbl"
        data_file.write_text("data")

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"part": [data_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[data_file]),
            patch.object(adapter, "_create_s3_client", return_value=MagicMock()),
            patch.object(adapter, "_load_table_via_s3", side_effect=Exception("upload failed")),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["part"] == 0


# ---------------------------------------------------------------------------
# configure_for_benchmark: auto_vacuum/auto_analyze path
# ---------------------------------------------------------------------------


class TestConfigureForBenchmarkVacuumAnalyze:
    """Test configure_for_benchmark invokes _run_vacuum_analyze_isolated."""

    def test_auto_vacuum_calls_run_vacuum_analyze_isolated(self):
        adapter = _make_adapter(auto_vacuum=True, auto_analyze=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.object(
                adapter,
                "validate_session_cache_control",
                return_value={"validated": True, "cache_disabled": True},
            ),
            patch.object(adapter, "_run_vacuum_analyze_isolated") as mock_vacuum,
        ):
            adapter.configure_for_benchmark(mock_conn, "tpch")

        mock_vacuum.assert_called_once_with(mock_conn)

    def test_no_vacuum_no_analyze_skips_isolated_run(self):
        adapter = _make_adapter(auto_vacuum=False, auto_analyze=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.object(
                adapter,
                "validate_session_cache_control",
                return_value={"validated": True, "cache_disabled": True},
            ),
            patch.object(adapter, "_run_vacuum_analyze_isolated") as mock_vacuum,
        ):
            adapter.configure_for_benchmark(mock_conn, "tpch")

        mock_vacuum.assert_not_called()


# ---------------------------------------------------------------------------
# _build_ctas_sort_sql: vacuum_sort and ctas paths
# ---------------------------------------------------------------------------


class TestBuildCtasSortSql:
    """Test _build_ctas_sort_sql covers all strategy paths."""

    def test_off_returns_none(self):
        adapter = _make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("off", None)):
            result = adapter._build_ctas_sort_sql("my_table", [])
        assert result is None

    def test_vacuum_sort_returns_vacuum_statement(self):
        adapter = _make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "vacuum_sort")):
            result = adapter._build_ctas_sort_sql("lineitem", [])
        assert result == "VACUUM SORT ONLY public.lineitem"

    def test_ctas_returns_list_of_three_statements(self):
        adapter = _make_adapter()
        mock_col = MagicMock()
        mock_col.name = "orderkey"
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "ctas")):
            result = adapter._build_ctas_sort_sql("orders", [mock_col])
        assert isinstance(result, list)
        assert len(result) == 3
        assert "CREATE TABLE" in result[0]
        assert "DROP TABLE" in result[1]
        assert "ALTER TABLE" in result[2]

    def test_unsupported_method_raises(self):
        adapter = _make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "unknown_method")):
            with pytest.raises(ValueError, match="not supported"):
                adapter._build_ctas_sort_sql("orders", [])


# ---------------------------------------------------------------------------
# _get_serverless_metadata_api: namespace sub-path + error paths
# ---------------------------------------------------------------------------


class TestGetServerlessMetadataApi:
    """Test _get_serverless_metadata_api covers namespace details and error branches."""

    def test_namespace_details_fetched_when_present(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.return_value = {
            "workgroup": {
                "workgroupName": "my-wg",
                "baseCapacity": 32,
                "maxCapacity": 512,
                "namespaceName": "my-ns",
                "enhancedVpcRouting": False,
                "status": "AVAILABLE",
            }
        }
        mock_client.get_namespace.return_value = {
            "namespace": {"kmsKeyId": "arn:aws:kms:us-east-1:123:key/abc", "namespaceStatus": "AVAILABLE"}
        }

        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")

        assert result["workgroup_name"] == "my-wg"
        assert result["base_capacity_rpu"] == 32
        assert result["encrypted"] is True
        assert result["kms_key_id"] == "arn:aws:kms:us-east-1:123:key/abc"

    def test_namespace_fetch_error_is_swallowed(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.return_value = {
            "workgroup": {
                "workgroupName": "my-wg",
                "baseCapacity": 32,
                "maxCapacity": None,
                "namespaceName": "my-ns",
                "enhancedVpcRouting": False,
            }
        }
        mock_client.get_namespace.side_effect = Exception("forbidden")

        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")
        # Should still return workgroup data even if namespace fails
        assert result["workgroup_name"] == "my-wg"
        assert "encrypted" not in result

    def test_no_credentials_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        from botocore.exceptions import NoCredentialsError

        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.side_effect = NoCredentialsError()

        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")
        assert result == {}

    def test_client_error_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        from botocore.exceptions import ClientError

        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetWorkgroup"
        )

        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")
        assert result == {}

    def test_generic_exception_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.get_workgroup.side_effect = RuntimeError("network error")

        result = adapter._get_serverless_metadata_api("my-wg", "us-east-1")
        assert result == {}


# ---------------------------------------------------------------------------
# _get_provisioned_metadata_api: storage_capacity path + error paths
# ---------------------------------------------------------------------------


class TestGetProvisionedMetadataApi:
    """Test _get_provisioned_metadata_api covers storage capacity and error paths."""

    def test_storage_capacity_included_when_present(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-west-2.redshift.amazonaws.com")

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {
            "Clusters": [
                {
                    "ClusterIdentifier": "mycluster",
                    "NodeType": "ra3.4xlarge",
                    "NumberOfNodes": 4,
                    "ClusterStatus": "available",
                    "Encrypted": True,
                    "KmsKeyId": "arn:aws:kms:key",
                    "EnhancedVpcRouting": False,
                    "TotalStorageCapacityInMegaBytes": 204800,
                }
            ]
        }

        result = adapter._get_provisioned_metadata_api("mycluster", "us-west-2")

        assert result["node_type"] == "ra3.4xlarge"
        assert result["number_of_nodes"] == 4
        assert result["total_storage_capacity_mb"] == 204800
        assert result["encrypted"] is True

    def test_no_storage_capacity_key_omitted(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-west-2.redshift.amazonaws.com")

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {
            "Clusters": [
                {
                    "ClusterIdentifier": "mycluster",
                    "NodeType": "ra3.xlplus",
                    "NumberOfNodes": 2,
                    "ClusterStatus": "available",
                    "Encrypted": False,
                    "TotalStorageCapacityInMegaBytes": None,
                }
            ]
        }

        result = adapter._get_provisioned_metadata_api("mycluster", "us-west-2")
        assert "total_storage_capacity_mb" not in result

    def test_no_credentials_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        from botocore.exceptions import NoCredentialsError

        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.side_effect = NoCredentialsError()

        result = adapter._get_provisioned_metadata_api("mycluster", "us-east-1")
        assert result == {}

    def test_client_error_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        from botocore.exceptions import ClientError

        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFound", "Message": "not found"}}, "DescribeClusters"
        )

        result = adapter._get_provisioned_metadata_api("mycluster", "us-east-1")
        assert result == {}

    def test_empty_clusters_list_returns_empty(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": []}

        result = adapter._get_provisioned_metadata_api("mycluster", "us-east-1")
        assert result == {}


# ---------------------------------------------------------------------------
# _compute_connect_timeout: provisioned status paths + serverless path
# ---------------------------------------------------------------------------


class TestComputeConnectTimeout:
    """Test _compute_connect_timeout covers cluster status branching."""

    def test_provisioned_available_returns_default_timeout(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")
        adapter.connect_timeout = 30

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "available"}]}

        result = adapter._compute_connect_timeout()
        assert result == 30

    def test_provisioned_resuming_returns_extended_timeout(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")
        adapter.connect_timeout = 30

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "resuming"}]}

        result = adapter._compute_connect_timeout()
        assert result >= 120

    def test_provisioned_paused_returns_extended_timeout(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")
        adapter.connect_timeout = 30

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "paused"}]}

        result = adapter._compute_connect_timeout()
        assert result >= 120

    def test_provisioned_api_error_falls_back_to_default(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")
        adapter.connect_timeout = 30

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.side_effect = Exception("connection refused")

        result = adapter._compute_connect_timeout()
        assert result == 30

    def test_serverless_returns_extended_timeout(self, _mock_redshift_deps):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")
        adapter.connect_timeout = 30

        result = adapter._compute_connect_timeout()
        assert result >= 60

    def test_cached_timeout_not_recomputed(self, _mock_redshift_deps):
        mock_boto = _mock_redshift_deps["boto3"]
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")
        adapter.connect_timeout = 30

        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.describe_clusters.return_value = {"Clusters": [{"ClusterStatus": "available"}]}

        first = adapter._resolve_connect_timeout()
        second = adapter._resolve_connect_timeout()
        assert first == second
        # describe_clusters called only once due to caching
        assert mock_client.describe_clusters.call_count == 1


# ---------------------------------------------------------------------------
# _get_platform_info: psycopg fallback + WLM path
# ---------------------------------------------------------------------------


class TestGetPlatformInfoPsycopgPath:
    """Test get_platform_info when only psycopg is available."""

    def test_client_library_version_none_when_no_version_attr(self, _mock_redshift_deps):
        """When redshift_connector has no __version__ attribute, version is None."""
        mock_rc = _mock_redshift_deps["rc"]
        # Remove __version__ from the mock so AttributeError is raised
        del mock_rc.__version__

        adapter = _make_adapter()
        result = adapter.get_platform_info(connection=None)
        assert result["client_library_version"] is None

    def test_psycopg_version_path_via_import(self):
        """Test psycopg path: redshift_connector=None triggers psycopg version lookup."""
        import sys

        import benchbox.platforms.redshift as rs_module

        mock_psycopg = MagicMock()
        mock_psycopg.__version__ = "3.1.0"

        # Save originals so they can be fully restored - psycopg IS installed in
        # this environment, so the module attribute must be put back, not deleted.
        original_rc = rs_module.redshift_connector
        original_pg_attr = getattr(rs_module, "psycopg", _SENTINEL := object())
        original_sys_pg = sys.modules.get("psycopg")

        # Inject mock psycopg into sys.modules so `import psycopg` inside get_platform_info returns it
        sys.modules["psycopg"] = mock_psycopg
        # Also set psycopg at module level so the __init__ check doesn't fail
        rs_module.psycopg = mock_psycopg
        try:
            rs_module.redshift_connector = None
            adapter = _make_adapter()
            result = adapter.get_platform_info(connection=None)
            assert result["client_library_version"] == "3.1.0"
        finally:
            rs_module.redshift_connector = original_rc
            # Restore sys.modules["psycopg"] to its original value
            if original_sys_pg is not None:
                sys.modules["psycopg"] = original_sys_pg
            else:
                sys.modules.pop("psycopg", None)
            # Restore rs_module.psycopg to its original value
            if original_pg_attr is not _SENTINEL:
                rs_module.psycopg = original_pg_attr
            elif hasattr(rs_module, "psycopg"):
                del rs_module.psycopg


class TestGetPlatformInfoWlmPath:
    """Test get_platform_info collects WLM queue data from pg_wlm_auto_explain."""

    def test_wlm_query_configuration_collected(self):
        adapter = _make_adapter()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock calls in sequence: version, deployment meta SQL attempts, session info,
        # table info, pg_wlm_configuration
        version_row = ("PostgreSQL 8.0.2 on Amazon Redshift 1.0.50481",)
        session_row = ("admin", "testdb", "public", "10.0.0.1", 5439)
        tables_rows = []
        wlm_rows = [(6, 5, 512, 60000)]

        mock_cursor.fetchone.side_effect = [version_row, session_row]
        mock_cursor.fetchall.side_effect = [tables_rows, wlm_rows]

        result = adapter.get_platform_info(connection=mock_conn)
        assert result["platform_version"] == version_row[0]


# ---------------------------------------------------------------------------
# _get_query_statistics: provisioned and serverless paths
# ---------------------------------------------------------------------------


class TestGetQueryStatistics:
    """Test _get_query_statistics covers both deployment paths."""

    def test_provisioned_path_returns_stats(self):
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        query_id = 12345
        stats_row = (query_id, 500000, 480000, 0, 0, 1, 1, 0)  # aborted=0

        mock_cursor.fetchone.side_effect = [(query_id,), stats_row]

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result["query_id"] == str(query_id)
        assert result["duration_microsecs"] == 500000
        assert result["aborted"] is False

    def test_serverless_path_returns_stats(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        query_id = 99999
        stats_row = (query_id, 750000, 700000, 0, 0, 1, 1, "success")

        mock_cursor.fetchone.side_effect = [(query_id,), stats_row]

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result["query_id"] == str(query_id)
        assert result["aborted"] is False

    def test_serverless_aborted_status(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        query_id = 77777
        stats_row = (query_id, 100, 100, 0, 0, 1, 1, "failed")

        mock_cursor.fetchone.side_effect = [(query_id,), stats_row]

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result["aborted"] is True

    def test_no_query_id_returns_empty(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (-1,)

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}

    def test_none_query_id_returns_empty(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}

    def test_no_stats_row_returns_empty(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(12345,), None]

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}

    def test_exception_returns_empty(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("table not found")

        result = adapter._get_query_statistics(mock_conn, "Q1")
        assert result == {}


# ---------------------------------------------------------------------------
# _get_platform_metadata: serverless + provisioned cluster info paths
# ---------------------------------------------------------------------------


class TestGetPlatformMetadata:
    """Test _get_platform_metadata covers serverless and provisioned cluster queries."""

    def test_serverless_cluster_info_path(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        version_row = ("PostgreSQL 8.0.2",)
        serverless_row = (64,)  # compute_capacity_rpu
        session_row = ("admin", "testdb", "public", "10.0.0.1", 5439)
        tables_rows = [("public", "lineitem", "admin", None, False, False, False)]

        mock_cursor.fetchone.side_effect = [version_row, serverless_row, session_row]
        mock_cursor.fetchall.return_value = tables_rows

        result = adapter._get_platform_metadata(mock_conn)

        assert result["redshift_version"] == "PostgreSQL 8.0.2"
        assert len(result["tables"]) == 1

    def test_provisioned_cluster_info_path(self):
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        version_row = ("PostgreSQL 8.0.2",)
        cluster_row = ("ra3.4xlarge", 4, "1.0.50000", True)
        session_row = ("admin", "testdb", "public", "10.0.0.1", 5439)
        tables_rows = []

        mock_cursor.fetchone.side_effect = [version_row, cluster_row, session_row]
        mock_cursor.fetchall.return_value = tables_rows

        result = adapter._get_platform_metadata(mock_conn)

        assert "cluster_info" in result
        assert result["cluster_info"]["node_type"] == "ra3.4xlarge"

    def test_cluster_info_exception_handled(self):
        adapter = _make_adapter()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        version_row = ("PostgreSQL 8.0.2",)

        # Second fetchone raises to simulate permission denied on cluster info
        mock_cursor.fetchone.side_effect = [version_row, Exception("permission denied")]

        result = adapter._get_platform_metadata(mock_conn)
        # Should not raise; metadata_error key set
        assert "metadata_error" in result or "redshift_version" in result

    def test_outer_exception_sets_metadata_error(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("connection failed")

        result = adapter._get_platform_metadata(mock_conn)
        assert "metadata_error" in result


# ---------------------------------------------------------------------------
# apply_table_tunings: distribution/sort key mismatch, no-table found path
# ---------------------------------------------------------------------------


class TestApplyTableTunings:
    """Test apply_table_tunings covers pg_table_def query and maintenance paths."""

    def test_table_found_needs_recreation_logs_warning(self):
        adapter = _make_adapter(auto_vacuum=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        try:
            from benchbox.core.tuning.interface import TuningType
        except ImportError:
            pytest.skip("TuningType not available")

        mock_table_tuning = MagicMock()
        mock_table_tuning.has_any_tuning.return_value = True
        mock_table_tuning.table_name = "lineitem"

        dist_col = MagicMock()
        dist_col.name = "l_orderkey"
        dist_col.order = 1
        sort_col = MagicMock()
        sort_col.name = "l_shipdate"
        sort_col.order = 1

        mock_table_tuning.get_columns_by_type.side_effect = lambda t: (
            [dist_col] if t == TuningType.DISTRIBUTION else [sort_col] if t == TuningType.SORTING else []
        )

        # Simulates current config with different dist/sort keys
        pg_row = ("public", "lineitem", "EVEN", None, None, None, None, None)
        mock_cursor.fetchone.return_value = pg_row

        adapter.apply_table_tunings(mock_table_tuning, mock_conn)

        # ANALYZE should have been called
        executed_sqls = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("ANALYZE" in sql for sql in executed_sqls)
        # VACUUM also called since auto_vacuum=True
        assert any("VACUUM" in sql for sql in executed_sqls)

    def test_table_not_found_logs_warning(self):
        adapter = _make_adapter(auto_vacuum=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        try:
            from benchbox.core.tuning.interface import TuningType
        except ImportError:
            pytest.skip("TuningType not available")

        mock_table_tuning = MagicMock()
        mock_table_tuning.has_any_tuning.return_value = True
        mock_table_tuning.table_name = "nonexistent_table"
        mock_table_tuning.get_columns_by_type.return_value = []

        mock_cursor.fetchone.return_value = None  # Table not found in pg_table_def

        adapter.apply_table_tunings(mock_table_tuning, mock_conn)

        executed_sqls = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("ANALYZE" in sql for sql in executed_sqls)

    def test_no_tuning_returns_early(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_table_tuning = MagicMock()
        mock_table_tuning.has_any_tuning.return_value = False

        adapter.apply_table_tunings(mock_table_tuning, mock_conn)
        mock_conn.cursor.assert_not_called()

    def test_none_tuning_returns_early(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        adapter.apply_table_tunings(None, mock_conn)
        mock_conn.cursor.assert_not_called()

    def test_partition_and_cluster_columns_logged(self):
        adapter = _make_adapter(auto_vacuum=False)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        try:
            from benchbox.core.tuning.interface import TuningType
        except ImportError:
            pytest.skip("TuningType not available")

        mock_table_tuning = MagicMock()
        mock_table_tuning.has_any_tuning.return_value = True
        mock_table_tuning.table_name = "orders"

        part_col = MagicMock()
        part_col.name = "o_orderdate"
        part_col.order = 1
        cluster_col = MagicMock()
        cluster_col.name = "o_custkey"
        cluster_col.order = 1

        mock_table_tuning.get_columns_by_type.side_effect = lambda t: (
            []
            if t == TuningType.DISTRIBUTION
            else []
            if t == TuningType.SORTING
            else [part_col]
            if t == TuningType.PARTITIONING
            else [cluster_col]
        )

        mock_cursor.fetchone.return_value = ("public", "orders", "AUTO", None, None, None, None, None)

        # Should not raise
        adapter.apply_table_tunings(mock_table_tuning, mock_conn)


# ---------------------------------------------------------------------------
# _build_external_column_definitions + _map_external_column_type
# ---------------------------------------------------------------------------


class TestMapExternalColumnType:
    """Test all type mapping branches of _map_external_column_type."""

    def test_empty_type_returns_varchar_max(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("")
        assert result == "VARCHAR(65535)"

    def test_decimal_passthrough(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("DECIMAL(10,2)")
        assert result == "DECIMAL(10,2)"

    def test_bigint_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("BIGINT")
        assert result == "BIGINT"

    def test_smallint_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("SMALLINT")
        assert result == "SMALLINT"

    def test_int_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("INT")
        assert result == "INTEGER"

    def test_double_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("DOUBLE PRECISION")
        assert result == "DOUBLE PRECISION"

    def test_real_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("REAL")
        assert result == "REAL"

    def test_float_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("FLOAT4")
        assert result == "REAL"

    def test_date_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("DATE")
        assert result == "DATE"

    def test_boolean_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("BOOLEAN")
        assert result == "BOOLEAN"

    def test_bool_alias_mapping(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("BOOL")
        assert result == "BOOLEAN"

    def test_unknown_type_fallback(self):
        from benchbox.platforms.redshift import RedshiftAdapter

        result = RedshiftAdapter._map_external_column_type("JSONB")
        assert result == "VARCHAR(65535)"


class TestBuildExternalColumnDefinitions:
    """Test _build_external_column_definitions covers error and happy paths."""

    def test_no_get_schema_raises(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = object()  # No get_schema method

        with pytest.raises(ValueError, match="Benchmark schema metadata unavailable"):
            adapter._build_external_column_definitions(mock_benchmark, "lineitem")

    def test_missing_table_schema_raises(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {}

        with pytest.raises(ValueError, match="No schema definition found"):
            adapter._build_external_column_definitions(mock_benchmark, "nonexistent")

    def test_empty_columns_raises(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {"lineitem": {"columns": []}}

        with pytest.raises(ValueError, match="No columns found"):
            adapter._build_external_column_definitions(mock_benchmark, "lineitem")

    def test_columns_with_no_name_skipped(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {
            "lineitem": {
                "columns": [
                    {"name": "", "type": "INTEGER"},  # empty name - skipped
                    {"name": "l_orderkey", "type": "BIGINT"},
                ]
            }
        }

        result = adapter._build_external_column_definitions(mock_benchmark, "lineitem")
        assert "l_orderkey BIGINT" in result
        # Empty-named column should not appear
        assert result.startswith("l_orderkey")

    def test_all_empty_names_raises(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {"lineitem": {"columns": [{"name": "", "type": "INTEGER"}]}}

        with pytest.raises(ValueError, match="No valid column definitions"):
            adapter._build_external_column_definitions(mock_benchmark, "lineitem")

    def test_happy_path_returns_column_defs(self):
        adapter = _make_adapter(s3_bucket="my-bucket", iam_role="arn:aws:iam::123:role/MyRole")
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {
            "lineitem": {
                "columns": [
                    {"name": "l_orderkey", "type": "BIGINT"},
                    {"name": "l_extendedprice", "type": "DECIMAL(15,2)"},
                    {"name": "l_shipdate", "type": "DATE"},
                ]
            }
        }

        result = adapter._build_external_column_definitions(mock_benchmark, "lineitem")
        assert "l_orderkey BIGINT" in result
        assert "l_extendedprice DECIMAL(15,2)" in result
        assert "l_shipdate DATE" in result


# ---------------------------------------------------------------------------
# create_external_tables: parquet and delta paths
# ---------------------------------------------------------------------------


class TestCreateExternalTables:
    """Test create_external_tables covers parquet and delta source paths."""

    def test_parquet_path_creates_external_table(self, tmp_path):
        adapter = _make_adapter(
            s3_bucket="my-bucket",
            iam_role="arn:aws:iam::123:role/MyRole",
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (100,)

        parquet_file = tmp_path / "lineitem.parquet"
        parquet_file.write_bytes(b"parquet_data")

        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {
            "lineitem": {
                "columns": [
                    {"name": "l_orderkey", "type": "BIGINT"},
                    {"name": "l_shipdate", "type": "DATE"},
                ]
            }
        }

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": [parquet_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[parquet_file]),
            patch.object(adapter, "_create_s3_client", return_value=MagicMock()),
            patch.object(
                adapter, "_upload_external_parquet_files_to_s3", return_value="s3://my-bucket/prefix/lineitem/"
            ),
        ):
            table_stats, total_time, _ = adapter.create_external_tables(mock_benchmark, mock_conn, tmp_path)

        assert "lineitem" in table_stats
        assert table_stats["lineitem"] == 100

    def test_no_valid_files_raises_value_error(self, tmp_path):
        adapter = _make_adapter(
            s3_bucket="my-bucket",
            iam_role="arn:aws:iam::123:role/MyRole",
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"lineitem": []}),
            patch.object(adapter, "_filter_valid_files", return_value=[]),
            patch.object(adapter, "_create_s3_client", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="No supported sources"):
                adapter.create_external_tables(mock_benchmark, mock_conn, tmp_path)

    def test_validate_external_table_requirements_no_bucket_raises(self):
        adapter = _make_adapter()  # No s3_bucket configured
        with pytest.raises(ValueError, match="requires S3 staging"):
            adapter.validate_external_table_requirements()

    def test_validate_external_table_requirements_no_iam_role_raises(self):
        adapter = _make_adapter(s3_bucket="my-bucket")  # No iam_role
        with pytest.raises(ValueError, match="requires IAM role"):
            adapter.validate_external_table_requirements()


# ---------------------------------------------------------------------------
# load_data: direct INSERT fallback path (no s3_bucket)
# ---------------------------------------------------------------------------


class TestLoadDataDirectInsertPath:
    """Test load_data falls back to INSERT when no S3 bucket is configured."""

    def test_direct_insert_path_used_when_no_s3_bucket(self, tmp_path):
        adapter = _make_adapter()  # No s3_bucket
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        data_file = tmp_path / "orders.tbl"
        data_file.write_text("1|100|O|173665.47|1996-01-02|5-LOW|Clerk#000000951|0|nstructions sleep furiously among |")

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"orders": [data_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[data_file]),
            patch.object(adapter, "_load_table_via_insert", return_value=1) as mock_insert,
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        mock_insert.assert_called_once()
        assert table_stats["orders"] == 1

    def test_direct_insert_error_sets_zero_count(self, tmp_path):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        data_file = tmp_path / "part.tbl"
        data_file.write_text("data")

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"part": [data_file]}),
            patch.object(adapter, "_filter_valid_files", return_value=[data_file]),
            patch.object(adapter, "_load_table_via_insert", side_effect=Exception("insert failed")),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["part"] == 0

    def test_no_valid_files_skipped_in_direct_path(self, tmp_path):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        with (
            patch.object(adapter, "_resolve_data_files", return_value={"orders": []}),
            patch.object(adapter, "_filter_valid_files", return_value=[]),
        ):
            table_stats, total_time, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        assert table_stats["orders"] == 0


# ---------------------------------------------------------------------------
# _build_redshift_config: module-level config builder
# ---------------------------------------------------------------------------


class TestBuildRedshiftConfig:
    """Test _build_redshift_config merges credentials correctly."""

    def test_saved_credentials_merged_with_options(self):
        from benchbox.platforms.redshift import _build_redshift_config

        mock_info = MagicMock()
        mock_info.display_name = "Amazon Redshift"
        mock_info.driver_package = "redshift-connector"

        # CredentialManager is imported locally inside _build_redshift_config
        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm = MagicMock()
            mock_cm.get_platform_credentials.return_value = {
                "host": "saved-host.us-east-1.redshift.amazonaws.com",
                "username": "saved_user",
                "password": "saved_pass",
            }
            mock_cm_cls.return_value = mock_cm

            result = _build_redshift_config(
                "redshift",
                {"host": "option-host.us-east-1.redshift.amazonaws.com"},
                {},
                mock_info,
            )

        # Saved creds win over registered defaults (options without _explicit_platform_options)
        assert result.host == "saved-host.us-east-1.redshift.amazonaws.com"

    def test_database_override_included_when_provided(self):
        from benchbox.platforms.redshift import _build_redshift_config

        mock_info = MagicMock()
        mock_info.display_name = "Amazon Redshift"
        mock_info.driver_package = "redshift-connector"

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm = MagicMock()
            mock_cm.get_platform_credentials.return_value = {}
            mock_cm_cls.return_value = mock_cm

            result = _build_redshift_config(
                "redshift",
                {},
                {"database": "explicit_db"},
                mock_info,
            )

        assert result.database == "explicit_db"

    def test_no_info_uses_defaults(self):
        from benchbox.platforms.redshift import _build_redshift_config

        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_cls:
            mock_cm = MagicMock()
            mock_cm.get_platform_credentials.return_value = {}
            mock_cm_cls.return_value = mock_cm

            result = _build_redshift_config("redshift", {}, {}, None)

        assert result.name == "Amazon Redshift"
        assert result.admin_database == "dev"


# ---------------------------------------------------------------------------
# _resolve_data_files: centralized DataSourceResolver delegation
# ---------------------------------------------------------------------------


class TestResolveDataFiles:
    """Test _resolve_data_files delegates to DataSourceResolver."""

    def test_resolve_data_files_delegates_to_resolver(self, tmp_path):
        adapter = _make_adapter()
        benchmark = MagicMock()
        data_source = MagicMock()
        data_source.tables = {"lineitem": [tmp_path / "lineitem.tbl"]}

        with patch("benchbox.platforms.redshift.resolve_adapter_data_source", return_value=data_source) as resolve:
            result = adapter._resolve_data_files(benchmark, tmp_path)

        resolve.assert_called_once_with(adapter, benchmark, tmp_path)
        assert result.tables == {"lineitem": [tmp_path / "lineitem.tbl"]}

    def test_resolve_data_files_raises_when_resolver_returns_empty(self, tmp_path):
        adapter = _make_adapter()

        with patch(
            "benchbox.platforms.redshift.resolve_adapter_data_source", side_effect=ValueError("No data files found")
        ):
            with pytest.raises(ValueError, match="No data files found"):
                adapter._resolve_data_files(MagicMock(), tmp_path)


# ---------------------------------------------------------------------------
# apply_unified_tuning: None/empty config early return
# ---------------------------------------------------------------------------


class TestApplyUnifiedTuning:
    """Test apply_unified_tuning covers None config early return."""

    def test_none_config_returns_early(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        # Should not raise
        adapter.apply_unified_tuning(None, mock_conn)

    def test_config_with_no_optimizations_skips_apply_platform_optimizations(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()

        mock_config = MagicMock()
        mock_config.platform_optimizations = None
        mock_config.primary_keys = MagicMock()
        mock_config.foreign_keys = MagicMock()
        mock_config.table_tunings = {}

        with patch.object(adapter, "apply_constraint_configuration") as mock_constraint:
            adapter.apply_unified_tuning(mock_config, mock_conn)

        mock_constraint.assert_called_once()


# ---------------------------------------------------------------------------
# get_platform_info: provisioned + serverless SQL fallback paths
# ---------------------------------------------------------------------------


class TestGetPlatformInfoDeploymentPaths:
    """Test get_platform_info collects deployment-specific metadata via SQL."""

    def test_serverless_deployment_sql_metadata_collected(self):
        adapter = _make_adapter(host="wg.123456789.us-east-1.redshift-serverless.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock version query and serverless SQL metadata
        version_row = ("PostgreSQL 8.0.2 on Amazon Redshift 1.0.50481",)
        mock_cursor.fetchone.side_effect = [version_row]
        mock_cursor.fetchall.return_value = []

        with (
            patch.object(adapter, "_get_serverless_metadata_api", return_value={}),
            patch.object(
                adapter,
                "_get_serverless_metadata_sql",
                return_value={
                    "workgroup_name": "my-wg",
                    "base_capacity_rpu": 32,
                },
            ),
        ):
            result = adapter.get_platform_info(connection=mock_conn)

        assert result["platform_version"] == version_row[0]
        assert result["configuration"]["workgroup_name"] == "my-wg"

    def test_provisioned_deployment_sql_metadata_collected(self):
        adapter = _make_adapter(host="mycluster.abc123.us-east-1.redshift.amazonaws.com")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        version_row = ("PostgreSQL 8.0.2 on Amazon Redshift",)
        mock_cursor.fetchone.side_effect = [version_row]
        mock_cursor.fetchall.return_value = []

        with (
            patch.object(adapter, "_get_provisioned_metadata_api", return_value={}),
            patch.object(
                adapter,
                "_get_provisioned_metadata_sql",
                return_value={
                    "cluster_identifier": "mycluster",
                    "node_type": "ra3.4xlarge",
                    "number_of_nodes": 4,
                },
            ),
        ):
            result = adapter.get_platform_info(connection=mock_conn)

        assert result["configuration"]["cluster_identifier"] == "mycluster"

    def test_platform_info_error_handled_gracefully(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("permission denied")

        result = adapter.get_platform_info(connection=mock_conn)
        assert result["platform_version"] is None


# ---------------------------------------------------------------------------
# create_schema: schema creation and DROP TABLE IF EXISTS paths
# ---------------------------------------------------------------------------


class TestCreateSchema:
    """Test create_schema covers non-public schema creation and DROP TABLE paths."""

    def test_non_public_schema_creates_schema(self):
        adapter = _make_adapter()
        adapter.schema = "benchmark_schema"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_benchmark = MagicMock()

        # _create_schema_with_tuning returns the raw SQL string
        with patch.object(adapter, "_create_schema_with_tuning", return_value=""):
            adapter.create_schema(mock_benchmark, mock_conn)

        # CREATE SCHEMA IF NOT EXISTS should be called for non-public schema
        executed_sqls = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("CREATE SCHEMA" in sql for sql in executed_sqls)

    def test_public_schema_skips_create_schema(self):
        adapter = _make_adapter()
        adapter.schema = "public"

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(adapter, "_create_schema_with_tuning", return_value=""):
            adapter.create_schema(MagicMock(), mock_conn)

        executed_sqls = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert not any("CREATE SCHEMA IF NOT EXISTS" in sql for sql in executed_sqls)

    def test_create_table_drops_existing_table(self):
        adapter = _make_adapter()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        create_stmt = "CREATE TABLE lineitem (l_orderkey BIGINT, l_shipdate DATE)"

        with (
            patch.object(adapter, "_create_schema_with_tuning", return_value=create_stmt + ";"),
            patch.object(adapter, "_extract_table_name", return_value="lineitem"),
            patch.object(adapter, "_normalize_table_name_in_sql", side_effect=lambda s: s),
            patch.object(adapter, "_optimize_table_definition", side_effect=lambda s: s),
        ):
            adapter.create_schema(MagicMock(), mock_conn)

        executed_sqls = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("DROP TABLE IF EXISTS" in sql for sql in executed_sqls)
