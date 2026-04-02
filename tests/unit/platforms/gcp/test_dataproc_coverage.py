"""Additional coverage tests for Dataproc adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.gcp import DataprocAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter(**kwargs) -> DataprocAdapter:
    with (
        patch("benchbox.platforms.gcp.dataproc_adapter.GOOGLE_CLOUD_AVAILABLE", True),
        patch("benchbox.platforms.gcp.dataproc_adapter.dataproc_v1", MagicMock()),
        patch("benchbox.platforms.gcp.dataproc_adapter.storage", MagicMock()),
        patch("benchbox.platforms.gcp.dataproc_adapter.CloudSparkStaging") as mock_staging,
    ):
        mock_staging.from_uri.return_value = MagicMock()
        return DataprocAdapter(project_id="proj", gcs_staging_dir="gs://bucket/path", **kwargs)


def test_client_helpers_cache_clients() -> None:
    adapter = _adapter()

    cluster_client = MagicMock()
    job_client = MagicMock()
    storage_client = MagicMock()

    with (
        patch("benchbox.platforms.gcp.dataproc_adapter.dataproc_v1") as mock_dp,
        patch("benchbox.platforms.gcp.dataproc_adapter.storage") as mock_storage,
    ):
        mock_dp.ClusterControllerClient.return_value = cluster_client
        mock_dp.JobControllerClient.return_value = job_client
        mock_storage.Client.return_value = storage_client

        assert adapter._get_cluster_client() is adapter._get_cluster_client()
        assert adapter._get_job_client() is adapter._get_job_client()
        assert adapter._get_storage_client() is adapter._get_storage_client()


def test_create_connection_returns_pending_for_missing_ephemeral_cluster() -> None:
    adapter = _adapter(create_ephemeral_cluster=True)
    client = MagicMock()
    client.get_cluster.side_effect = RuntimeError("404 NotFound")

    with patch.object(adapter, "_get_cluster_client", return_value=client):
        result = adapter.create_connection()

    assert result["status"] == "pending"
    assert "will be created" in result["message"]


def test_close_deletes_cluster_when_created_by_us() -> None:
    adapter = _adapter(create_ephemeral_cluster=True)
    adapter._cluster_created_by_us = True

    with patch.object(adapter, "_delete_cluster") as mock_delete:
        adapter.close()

    mock_delete.assert_called_once_with()


def test_apply_tuning_configuration_collects_results() -> None:
    adapter = _adapter()
    adapter.apply_primary_keys = MagicMock(return_value={"pk": 1})
    adapter.apply_foreign_keys = MagicMock(return_value={"fk": 1})
    adapter.apply_platform_optimizations = MagicMock(return_value={"opt": 1})

    config = SimpleNamespace(scale_factor=5.0, primary_keys=["a"], foreign_keys=["b"], platform={"x": 1})
    result = adapter.apply_tuning_configuration(config)

    assert adapter._scale_factor == 5.0
    assert result["primary_keys"] == {"pk": 1}
    assert result["foreign_keys"] == {"fk": 1}
    assert result["platform_optimizations"] == {"opt": 1}
