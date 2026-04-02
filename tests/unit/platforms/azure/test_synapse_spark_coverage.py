"""Additional coverage tests for Synapse Spark adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.azure import SynapseSparkAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter() -> SynapseSparkAdapter:
    with (
        patch("benchbox.platforms.azure.synapse_spark_adapter.AZURE_IDENTITY_AVAILABLE", True),
        patch("benchbox.platforms.azure.synapse_spark_adapter.DefaultAzureCredential", MagicMock()),
        patch("benchbox.platforms.azure.synapse_spark_adapter.REQUESTS_AVAILABLE", True),
        patch("benchbox.platforms.azure.synapse_spark_adapter.CloudSparkStaging") as mock_staging,
    ):
        mock_staging.from_uri.return_value = MagicMock()
        return SynapseSparkAdapter(
            workspace_name="ws",
            spark_pool_name="pool",
            storage_account="acct",
            storage_container="container",
        )


def test_get_access_token_refreshes_and_reuses_cached_token() -> None:
    adapter = _adapter()
    token = SimpleNamespace(token="abc", expires_on=9999999999)
    cred = MagicMock()
    cred.get_token.return_value = token

    with patch.object(adapter, "_get_credential", return_value=cred):
        assert adapter._get_access_token() == "abc"
        assert adapter._get_access_token() == "abc"

    cred.get_token.assert_called_once_with("https://dev.azuresynapse.net/.default")


def test_get_headers_includes_bearer_token() -> None:
    adapter = _adapter()

    with patch.object(adapter, "_get_access_token", return_value="token123"):
        headers = adapter._get_headers()

    assert headers["Authorization"] == "Bearer token123"
    assert headers["Content-Type"] == "application/json"


def test_apply_unified_tuning_calls_platform_tuning_when_present() -> None:
    adapter = _adapter()
    adapter.apply_platform_tuning = MagicMock()

    adapter.apply_unified_tuning(SimpleNamespace(platform_optimization={"spark.sql.shuffle.partitions": "4"}))

    call_args = adapter.apply_platform_tuning.call_args
    assert call_args is not None, "apply_platform_tuning should have been called"
    assert "spark.sql.shuffle.partitions" in str(call_args), "Should pass Spark config"


def test_create_schema_default_and_non_default_paths() -> None:
    adapter = _adapter()
    adapter._execute_statement = MagicMock()

    adapter.create_schema()
    adapter.create_schema("benchbox")

    call_args = adapter._execute_statement.call_args
    assert call_args is not None, "_execute_statement should have been called"
    assert "benchbox" in str(call_args).lower(), "Should reference 'benchbox' schema"


def test_load_data_validates_source_dir_and_builds_table_uris(tmp_path: Path) -> None:
    adapter = _adapter()
    adapter._staging = MagicMock()
    adapter._staging.tables_exist.return_value = False
    adapter._execute_statement = MagicMock(side_effect=[None, RuntimeError("table create failed")])

    with pytest.raises(ConfigurationError, match="Source directory not found"):
        adapter.load_data(["lineitem"], tmp_path / "missing")

    (tmp_path / "lineitem.parquet").write_text("data", encoding="utf-8")
    result = adapter.load_data(["lineitem", "orders"], tmp_path)

    assert "lineitem" in result
    assert result["orders"].endswith("/tables/orders")


def test_execute_query_shapes_result_payload() -> None:
    adapter = _adapter()
    adapter._execute_statement = MagicMock(
        return_value={
            "data": {
                "schema": {"fields": [{"name": "c1"}, {"name": "c2"}]},
                "values": [[1, "a"], [2, "b"]],
            }
        }
    )

    output = adapter.execute_query("SELECT * FROM t")

    assert output["success"] is True
    assert output["row_count"] == 2
    assert output["columns"] == ["c1", "c2"]


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "Authentication failed"),
        (403, "Access denied"),
        (404, "not found"),
        (500, "Failed to access Synapse"),
    ],
)
def test_create_connection_maps_http_failures(status_code: int, message: str) -> None:
    adapter = _adapter()
    response = MagicMock()
    response.status_code = status_code
    response.text = "error"
    response.json.return_value = {}

    with (
        patch.object(adapter, "_get_access_token", return_value="token"),
        patch.object(adapter, "_get_headers", return_value={"Authorization": "Bearer token"}),
        patch("benchbox.platforms.azure.synapse_spark_adapter.requests.get", return_value=response),
    ):
        with pytest.raises(ConfigurationError, match=message):
            adapter.create_connection()


def test_close_clears_session_id_when_delete_raises() -> None:
    adapter = _adapter()
    adapter._session_id = 7
    adapter._session_created_by_us = True

    with (
        patch.object(adapter, "_get_headers", return_value={"Authorization": "Bearer token"}),
        patch("benchbox.platforms.azure.synapse_spark_adapter.requests.delete", side_effect=RuntimeError("boom")),
    ):
        adapter.close()

    assert adapter._session_id is None
