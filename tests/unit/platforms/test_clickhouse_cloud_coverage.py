"""Coverage-focused tests for clickhouse_cloud adapter helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import benchbox.platforms.clickhouse_cloud as cloud
from benchbox.platforms.clickhouse_cloud import ClickHouseCloudAdapter, _build_clickhouse_cloud_config

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_from_config_maps_cloud_and_optional_fields() -> None:
    captured = {}

    def _fake_init(self, **kwargs):
        captured.update(kwargs)

    with patch.object(ClickHouseCloudAdapter, "__init__", _fake_init):
        ClickHouseCloudAdapter.from_config(
            {
                "host": "h",
                "password": "p",
                "username": "u",
                "database": "d",
                "compression": "lz4",
                "benchmark": "tpch",
            }
        )

    assert captured["host"] == "h"
    assert captured["compression"] == "lz4"
    assert captured["benchmark"] == "tpch"


def test_from_config_maps_oauth_token() -> None:
    """from_config should pass through oauth_token when present."""
    captured = {}

    def _fake_init(self, **kwargs):
        captured.update(kwargs)

    with patch.object(ClickHouseCloudAdapter, "__init__", _fake_init):
        ClickHouseCloudAdapter.from_config(
            {
                "host": "h",
                "oauth_token": "my-token",
                "database": "d",
            }
        )

    assert captured["oauth_token"] == "my-token"
    assert captured["host"] == "h"


def test_from_config_maps_cloud_storage_staging() -> None:
    """from_config should pass through S3/GCS staging options."""
    captured = {}

    def _fake_init(self, **kwargs):
        captured.update(kwargs)

    with patch.object(ClickHouseCloudAdapter, "__init__", _fake_init):
        ClickHouseCloudAdapter.from_config(
            {
                "host": "h",
                "password": "p",
                "s3_staging_url": "s3://bucket/prefix/",
                "s3_region": "us-east-1",
                "gcs_staging_url": "gs://bucket/prefix/",
            }
        )

    assert captured["s3_staging_url"] == "s3://bucket/prefix/"
    assert captured["s3_region"] == "us-east-1"
    assert captured["gcs_staging_url"] == "gs://bucket/prefix/"


def test_get_platform_info_adds_cloud_metadata() -> None:
    adapter = ClickHouseCloudAdapter(host="h", password="p")

    with patch(
        "benchbox.platforms.clickhouse_cloud.ClickHouseAdapter.get_platform_info", return_value={"configuration": {}}
    ):
        info = adapter.get_platform_info(connection=None)

    assert info["platform_type"] == "clickhouse-cloud"
    assert info["connection_mode"] == "cloud"
    assert info["configuration"]["deployment"] == "managed"
    assert info["configuration"]["auth_method"] == "password"


def test_get_platform_info_oauth_auth_method() -> None:
    """Platform info should report 'oauth' auth_method when token is set."""
    adapter = ClickHouseCloudAdapter(host="h", oauth_token="tok")

    with patch(
        "benchbox.platforms.clickhouse_cloud.ClickHouseAdapter.get_platform_info", return_value={"configuration": {}}
    ):
        info = adapter.get_platform_info(connection=None)

    assert info["configuration"]["auth_method"] == "oauth"


def test_get_platform_info_includes_staging_urls() -> None:
    """Platform info should include staging URLs when configured."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://b/p/", gcs_staging_url="gs://b/p/")

    with patch(
        "benchbox.platforms.clickhouse_cloud.ClickHouseAdapter.get_platform_info", return_value={"configuration": {}}
    ):
        info = adapter.get_platform_info(connection=None)

    assert info["configuration"]["s3_staging_url"] == "s3://b/p/"
    assert info["configuration"]["gcs_staging_url"] == "gs://b/p/"


def test_build_clickhouse_cloud_config_merges_saved_options(monkeypatch: pytest.MonkeyPatch) -> None:
    cred_manager = MagicMock()
    cred_manager.get_platform_credentials.return_value = {"host": "saved", "username": "saved_user"}
    info = type("Info", (), {"display_name": "CH Cloud", "driver_package": "clickhouse-connect"})
    with patch("benchbox.security.credentials.CredentialManager", return_value=cred_manager):
        config = _build_clickhouse_cloud_config(
            "clickhouse-cloud",
            {"host": "option-host", "password": "option-pass"},
            {"database": "db1", "benchmark": "tpch", "scale_factor": 0.01},
            info,
        )

    assert config.type == "clickhouse-cloud"
    assert config.host == "option-host"
    assert config.password == "option-pass"
    assert config.options["username"] == "saved_user"


def test_build_config_includes_oauth_and_staging() -> None:
    """_build_clickhouse_cloud_config should include oauth_token and staging fields."""
    cred_manager = MagicMock()
    cred_manager.get_platform_credentials.return_value = {}
    info = type("Info", (), {"display_name": "CH Cloud", "driver_package": "clickhouse-connect"})
    with patch("benchbox.security.credentials.CredentialManager", return_value=cred_manager):
        config = _build_clickhouse_cloud_config(
            "clickhouse-cloud",
            {
                "host": "h",
                "oauth_token": "tok",
                "s3_staging_url": "s3://b/",
                "s3_region": "us-west-2",
                "gcs_staging_url": "gs://b/",
            },
            {},
            info,
        )

    assert config.options["oauth_token"] == "tok"
    assert config.options["s3_staging_url"] == "s3://b/"
    assert config.options["s3_region"] == "us-west-2"
    assert config.options["gcs_staging_url"] == "gs://b/"


# ---- OAuth token authentication tests ----


def test_adapter_init_with_oauth_token_instead_of_password() -> None:
    """Adapter should accept oauth_token without password."""
    adapter = ClickHouseCloudAdapter(host="h", oauth_token="my-token")
    assert adapter.oauth_token == "my-token"
    assert adapter.host == "h"


def test_adapter_init_with_oauth_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter should read CLICKHOUSE_CLOUD_OAUTH_TOKEN from env."""
    monkeypatch.setenv("CLICKHOUSE_CLOUD_HOST", "cloud-host")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_OAUTH_TOKEN", "env-token")
    adapter = ClickHouseCloudAdapter()
    assert adapter.oauth_token == "env-token"
    assert adapter.host == "cloud-host"


def test_apply_cloud_defaults_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """_apply_cloud_defaults should read all expected env vars."""
    monkeypatch.setenv("CLICKHOUSE_CLOUD_HOST", "env-host")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_PASSWORD", "env-pass")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_OAUTH_TOKEN", "env-oauth")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_USER", "env-user")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_S3_STAGING_URL", "s3://env-bucket/")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_S3_REGION", "eu-west-1")
    monkeypatch.setenv("CLICKHOUSE_CLOUD_GCS_STAGING_URL", "gs://env-bucket/")

    config: dict = {}
    # Use a temporary instance method via class
    ClickHouseCloudAdapter._apply_cloud_defaults(None, config)

    assert config["host"] == "env-host"
    assert config["password"] == "env-pass"
    assert config["oauth_token"] == "env-oauth"
    assert config["username"] == "env-user"
    assert config["s3_staging_url"] == "s3://env-bucket/"
    assert config["s3_region"] == "eu-west-1"
    assert config["gcs_staging_url"] == "gs://env-bucket/"


# ---- CLI arguments tests ----


def test_add_cli_arguments_includes_new_options() -> None:
    """add_cli_arguments should register OAuth and staging arguments."""
    parser = argparse.ArgumentParser()
    ClickHouseCloudAdapter.add_cli_arguments(parser)

    # Parse empty args to check defaults
    args = parser.parse_args([])
    # These optional args should be None when not provided
    assert getattr(args, "clickhouse_cloud_oauth_token", "MISSING") is None
    assert getattr(args, "clickhouse_cloud_s3_staging_url", "MISSING") is None
    assert getattr(args, "clickhouse_cloud_s3_region", "MISSING") is None
    assert getattr(args, "clickhouse_cloud_gcs_staging_url", "MISSING") is None


def test_add_cli_arguments_parses_values() -> None:
    """add_cli_arguments should parse provided values."""
    parser = argparse.ArgumentParser()
    ClickHouseCloudAdapter.add_cli_arguments(parser)

    args = parser.parse_args(
        [
            "--clickhouse-cloud-oauth-token",
            "my-tok",
            "--clickhouse-cloud-s3-staging-url",
            "s3://b/p/",
            "--clickhouse-cloud-s3-region",
            "us-east-1",
            "--clickhouse-cloud-gcs-staging-url",
            "gs://b/p/",
        ]
    )
    assert args.clickhouse_cloud_oauth_token == "my-tok"
    assert args.clickhouse_cloud_s3_staging_url == "s3://b/p/"
    assert args.clickhouse_cloud_s3_region == "us-east-1"
    assert args.clickhouse_cloud_gcs_staging_url == "gs://b/p/"


# ---- URL parsing tests ----


def test_parse_s3_url() -> None:
    assert ClickHouseCloudAdapter._parse_s3_url("s3://my-bucket/staging/") == ("my-bucket", "staging/")
    assert ClickHouseCloudAdapter._parse_s3_url("s3://my-bucket/") == ("my-bucket", "")
    assert ClickHouseCloudAdapter._parse_s3_url("s3://bucket") == ("bucket", "")


def test_parse_gcs_url() -> None:
    assert ClickHouseCloudAdapter._parse_gcs_url("gs://my-bucket/staging/") == ("my-bucket", "staging/")
    assert ClickHouseCloudAdapter._parse_gcs_url("gs://my-bucket/") == ("my-bucket", "")
    assert ClickHouseCloudAdapter._parse_gcs_url("gs://bucket") == ("bucket", "")


# ---- S3 URL validation tests ----


def test_invalid_s3_url_raises_error() -> None:
    """Invalid S3 URL should raise ConfigurationError."""
    from benchbox.core.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError, match="Invalid S3 staging URL"):
        ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="http://not-s3/")


def test_invalid_gcs_url_raises_error() -> None:
    """Invalid GCS URL should raise ConfigurationError."""
    from benchbox.core.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError, match="Invalid GCS staging URL"):
        ClickHouseCloudAdapter(host="h", password="p", gcs_staging_url="http://not-gcs/")


def test_s3_url_gets_trailing_slash() -> None:
    """S3 URL without trailing slash should get one added."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://bucket/prefix")
    assert adapter.s3_staging_url == "s3://bucket/prefix/"


def test_gcs_url_gets_trailing_slash() -> None:
    """GCS URL without trailing slash should get one added."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", gcs_staging_url="gs://bucket/prefix")
    assert adapter.gcs_staging_url == "gs://bucket/prefix/"


# ---- load_data dispatch tests ----


def test_load_data_dispatches_to_s3_when_configured() -> None:
    """load_data should call _load_data_via_s3 when s3_staging_url is set."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://b/p/")
    mock_result = ({"t": 10}, 1.0, {"loading_method": "s3_staging"})

    benchmark, connection = MagicMock(), MagicMock()
    with patch.object(adapter, "_load_data_via_s3", return_value=mock_result) as mock_s3:
        result = adapter.load_data(benchmark, connection, Path("/tmp"))

    mock_s3.assert_called_once_with(benchmark, connection, Path("/tmp"))
    assert result[2]["loading_method"] == "s3_staging"


def test_load_data_dispatches_to_gcs_when_configured() -> None:
    """load_data should call _load_data_via_gcs when gcs_staging_url is set."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", gcs_staging_url="gs://b/p/")
    mock_result = ({"t": 10}, 1.0, {"loading_method": "gcs_staging"})

    benchmark, connection = MagicMock(), MagicMock()
    with patch.object(adapter, "_load_data_via_gcs", return_value=mock_result) as mock_gcs:
        result = adapter.load_data(benchmark, connection, Path("/tmp"))

    mock_gcs.assert_called_once_with(benchmark, connection, Path("/tmp"))
    assert result[2]["loading_method"] == "gcs_staging"


def test_load_data_falls_back_to_default_when_no_staging() -> None:
    """load_data should use inherited path when no staging URL configured."""
    adapter = ClickHouseCloudAdapter(host="h", password="p")
    mock_result = ({"t": 10}, 1.0, None)

    benchmark, connection = MagicMock(), MagicMock()
    with patch(
        "benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.load_data",
        return_value=mock_result,
    ) as mock_parent:
        result = adapter.load_data(benchmark, connection, Path("/tmp"))

    mock_parent.assert_called_once_with(benchmark, connection, Path("/tmp"))
    assert result[2] is None


def test_external_mode_requires_staging_url() -> None:
    """External mode should require S3 or GCS staging URL."""
    adapter = ClickHouseCloudAdapter(host="h", password="p")
    assert adapter.supports_external_tables is True

    with pytest.raises(ValueError, match="requires cloud staging URL"):
        adapter.validate_external_table_requirements()


def test_create_external_tables_dispatches_to_s3() -> None:
    """create_external_tables should dispatch to S3 helper when configured."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://bucket/staging/")
    mock_result = ({"orders": 100}, 1.0, {"loading_method": "s3_external_views"})

    benchmark, connection = MagicMock(), MagicMock()
    with patch.object(adapter, "_create_external_tables_via_s3", return_value=mock_result) as mock_s3:
        result = adapter.create_external_tables(benchmark, connection, Path("/tmp"))

    mock_s3.assert_called_once_with(benchmark, connection, Path("/tmp"))
    assert result[2]["loading_method"] == "s3_external_views"


def test_create_external_tables_via_s3_builds_view_sql(tmp_path: Path) -> None:
    """S3 external mode should upload Parquet files and register view SQL."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://bucket/staging/")

    parquet_file = tmp_path / "orders.parquet"
    parquet_file.write_bytes(b"PAR1")

    benchmark = MagicMock()
    benchmark.tables = {"orders": [str(parquet_file)]}

    connection = MagicMock()

    def _execute(sql: str):
        if sql.startswith("SELECT COUNT(*)"):
            return [(17,)]
        return []

    connection.execute.side_effect = _execute

    mock_s3_client = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3_client

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        stats, _, metadata = adapter._create_external_tables_via_s3(benchmark, connection, tmp_path)

    assert stats["orders"] == 17
    assert metadata["loading_method"] == "s3_external_views"
    upload_args = mock_s3_client.upload_file.call_args
    assert upload_args is not None, "upload_file should have been called"
    assert "bucket" in str(upload_args), "Upload should target the configured bucket"

    executed_sql = " ".join(call.args[0] for call in connection.execute.call_args_list)
    assert "CREATE OR REPLACE VIEW orders AS SELECT * FROM s3(" in executed_sql
    assert "'Parquet'" in executed_sql


def test_create_external_tables_via_s3_builds_iceberg_view_sql(tmp_path: Path) -> None:
    """S3 external mode should register iceberg() views for Iceberg directories."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://bucket/staging/")
    iceberg_dir = tmp_path / "orders"
    (iceberg_dir / "metadata").mkdir(parents=True)
    (iceberg_dir / "metadata" / "v1.metadata.json").write_text("{}")

    benchmark = MagicMock()
    benchmark.tables = {"orders": [str(iceberg_dir)]}
    connection = MagicMock()

    def _execute(sql: str):
        if sql.startswith("SELECT COUNT(*)"):
            return [(4,)]
        return []

    connection.execute.side_effect = _execute

    mock_s3_client = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3_client

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        stats, _, metadata = adapter._create_external_tables_via_s3(benchmark, connection, tmp_path)

    assert stats["orders"] == 4
    assert metadata["loading_method"] == "s3_external_views"
    executed_sql = " ".join(call.args[0] for call in connection.execute.call_args_list)
    assert "CREATE OR REPLACE VIEW orders AS SELECT * FROM iceberg(" in executed_sql


# ---- S3 staging data loading tests ----


def test_load_data_via_s3_boto3_import_error() -> None:
    """_load_data_via_s3 should raise ImportError when boto3 is not available."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://b/p/")

    with patch.dict("sys.modules", {"boto3": None}):
        with pytest.raises(ImportError, match="boto3 is required"):
            adapter._load_data_via_s3(MagicMock(), MagicMock(), Path("/tmp"))


def test_load_data_via_s3_uploads_and_ingests(tmp_path: Path) -> None:
    """_load_data_via_s3 should upload files and execute INSERT FROM s3()."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", s3_staging_url="s3://bucket/staging/")

    # Create test data file
    data_file = tmp_path / "test_table.csv"
    data_file.write_text("col1,col2\n1,a\n2,b\n")

    # Mock benchmark with tables attribute
    benchmark = MagicMock()
    benchmark.tables = {"test_table": [str(data_file)]}

    # Mock connection
    connection = MagicMock()
    connection.execute.return_value = [(100,)]

    # Mock boto3
    mock_s3_client = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3_client

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        table_stats, total_time, metadata = adapter._load_data_via_s3(benchmark, connection, tmp_path)

    assert "test_table" in table_stats
    assert metadata["loading_method"] == "s3_staging"
    assert metadata["s3_staging_url"] == "s3://bucket/staging/"
    # Verify S3 upload was called with the data file
    upload_args = mock_s3_client.upload_file.call_args
    assert upload_args is not None, "upload_file should have been called"
    # Check positional and keyword args directly to avoid repr escaping of backslashes on Windows
    all_arg_values = list(upload_args.args) + list(upload_args.kwargs.values())
    assert any(str(data_file) == str(a) for a in all_arg_values), f"Upload should include {data_file}"
    # Verify INSERT FROM s3() was executed
    execute_calls = [str(c) for c in connection.execute.call_args_list]
    assert any("s3(" in str(c) for c in execute_calls)


# ---- GCS staging data loading tests ----


def test_load_data_via_gcs_import_error() -> None:
    """_load_data_via_gcs should raise ImportError when google-cloud-storage is not available."""
    adapter = ClickHouseCloudAdapter(host="h", password="p", gcs_staging_url="gs://b/p/")

    with patch.dict("sys.modules", {"google.cloud": None, "google.cloud.storage": None, "google": None}):
        with pytest.raises(ImportError, match="google-cloud-storage is required"):
            adapter._load_data_via_gcs(MagicMock(), MagicMock(), Path("/tmp"))


# ---- ClickHouseCloudClient OAuth tests ----


def test_cloud_client_uses_access_token() -> None:
    """ClickHouseCloudClient should pass access_token to clickhouse-connect when provided."""
    mock_cc = MagicMock()
    mock_client = MagicMock()
    mock_cc.get_client.return_value = mock_client

    with patch("benchbox.platforms.clickhouse._dependencies.clickhouse_connect", mock_cc):
        from benchbox.platforms.clickhouse.client import ClickHouseCloudClient

        ClickHouseCloudClient(
            host="h",
            access_token="my-token",
        )

    # Verify access_token was passed and password was NOT
    call_kwargs = mock_cc.get_client.call_args[1]
    assert call_kwargs["access_token"] == "my-token"
    assert "password" not in call_kwargs
    assert "username" not in call_kwargs


def test_cloud_client_uses_password_when_no_token() -> None:
    """ClickHouseCloudClient should use username/password when no access_token."""
    mock_cc = MagicMock()
    mock_client = MagicMock()
    mock_cc.get_client.return_value = mock_client

    with patch("benchbox.platforms.clickhouse._dependencies.clickhouse_connect", mock_cc):
        from benchbox.platforms.clickhouse.client import ClickHouseCloudClient

        ClickHouseCloudClient(
            host="h",
            user="testuser",
            password="testpass",
        )

    call_kwargs = mock_cc.get_client.call_args[1]
    assert call_kwargs["username"] == "testuser"
    assert call_kwargs["password"] == "testpass"
    assert "access_token" not in call_kwargs


# ---- Setup mixin cloud mode tests ----


def test_setup_cloud_mode_requires_auth() -> None:
    """Cloud mode should fail if neither password nor oauth_token is provided."""
    with pytest.raises(ValueError, match="requires authentication"):
        ClickHouseCloudAdapter(host="h")


def test_setup_cloud_mode_with_oauth_only() -> None:
    """Cloud mode should accept oauth_token without password."""
    adapter = ClickHouseCloudAdapter(host="h", oauth_token="tok")
    assert adapter.oauth_token == "tok"
    assert adapter.password is None or adapter.password == ""


def test_create_cloud_connection_passes_oauth_token() -> None:
    """_create_cloud_connection should pass access_token to ClickHouseCloudClient."""
    adapter = ClickHouseCloudAdapter(host="h", oauth_token="tok")

    mock_client = MagicMock()
    mock_client.execute.return_value = [(1,)]

    with patch("benchbox.platforms.clickhouse.setup.ClickHouseCloudClient", return_value=mock_client) as MockClient:
        adapter._create_cloud_connection()

    call_kwargs = MockClient.call_args[1]
    assert call_kwargs["access_token"] == "tok"


# ---- _resolve_cloud_data_files tests ----


def test_resolve_cloud_data_files_from_benchmark_tables(tmp_path: Path) -> None:
    """_resolve_cloud_data_files should use benchmark.tables if available."""
    adapter = ClickHouseCloudAdapter(host="h", password="p")
    benchmark = MagicMock()
    benchmark.tables = {"orders": [str(tmp_path / "orders.csv")]}

    result = adapter._resolve_cloud_data_files(benchmark, tmp_path)
    assert "orders" in result
    assert result["orders"][0] == tmp_path / "orders.csv"


def test_resolve_cloud_data_files_from_manifest(tmp_path: Path) -> None:
    """_resolve_cloud_data_files should fall back to manifest."""
    import json

    manifest = {
        "tables": {
            "lineitem": [{"path": "lineitem.csv"}],
        }
    }
    (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

    adapter = ClickHouseCloudAdapter(host="h", password="p")
    benchmark = MagicMock(spec=[])  # No .tables attribute

    result = adapter._resolve_cloud_data_files(benchmark, tmp_path)
    assert "lineitem" in result


def test_resolve_cloud_data_files_raises_when_no_data(tmp_path: Path) -> None:
    """_resolve_cloud_data_files should raise ValueError when no data found."""
    adapter = ClickHouseCloudAdapter(host="h", password="p")
    benchmark = MagicMock(spec=[])  # No .tables attribute

    with pytest.raises(ValueError, match="No data files found"):
        adapter._resolve_cloud_data_files(benchmark, tmp_path)


def test_normalize_external_file_inputs_splits_cloud_and_local(tmp_path: Path) -> None:
    """Verify _normalize_external_file_inputs correctly separates local and cloud URIs."""
    local_file = tmp_path / "data.parquet"
    local_file.write_bytes(b"\x00" * 10)
    inputs = [str(local_file), "s3://bucket/data.parquet", "gs://bucket/data.parquet"]
    local_paths, cloud_uris = ClickHouseCloudAdapter._normalize_external_file_inputs(inputs)
    assert len(local_paths) == 1
    assert len(cloud_uris) == 2
    assert str(local_file) == str(local_paths[0])


def test_s3_external_credential_warning_logged(tmp_path: Path, caplog) -> None:
    """Credential embedding in VIEW SQL should produce a warning log."""
    import logging
    import os
    import sys

    adapter = ClickHouseCloudAdapter(
        host="h",
        password="p",
        s3_staging_url="s3://test-bucket/prefix/",
    )
    parquet_file = tmp_path / "lineitem.parquet"
    parquet_file.write_bytes(b"\x00" * 10)

    benchmark = MagicMock()
    benchmark.tables = {"lineitem": [str(parquet_file)]}

    mock_conn = MagicMock()
    mock_conn.execute.return_value = [(42,)]

    env_patch = {
        "AWS_ACCESS_KEY_ID": "AKIATEST",
        "AWS_SECRET_ACCESS_KEY": "secret123",
    }

    # boto3 is imported inside the method, so we inject a mock into sys.modules
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = MagicMock()

    with (
        patch.dict(os.environ, env_patch),
        patch.dict(sys.modules, {"boto3": mock_boto3}),
        caplog.at_level(logging.WARNING),
    ):
        adapter._create_external_tables_via_s3(benchmark, mock_conn, tmp_path)

    assert any("credentials will be embedded" in r.message.lower() for r in caplog.records)
