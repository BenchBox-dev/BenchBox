"""Unit tests for client_link metadata wiring in adapters and runtime_metadata."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.base.adapter import PlatformAdapter
from benchbox.platforms.base.runtime_metadata import (
    build_default_normalized_result_metadata,
    collect_normalized_result_metadata,
)
from benchbox.platforms.databricks.adapter import DatabricksAdapter
from benchbox.platforms.firebolt import FireboltAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _DummyAdapter(PlatformAdapter):
    platform_name = "dummy"

    def __init__(self, **config) -> None:
        super().__init__(**config)

    @staticmethod
    def add_cli_arguments(parser) -> None:
        pass

    @classmethod
    def from_config(cls, config):
        return cls(**config)

    def get_target_dialect(self) -> str:
        return "duckdb"

    def create_connection(self, **kwargs):
        return None

    def apply_constraint_configuration(self, *args, **kwargs):
        pass

    def apply_platform_optimizations(self, *args, **kwargs):
        pass

    def configure_for_benchmark(self, *args, **kwargs):
        pass

    def create_schema(self, *args, **kwargs):
        pass

    def execute_query(self, *args, **kwargs):
        pass

    def load_data(self, *args, **kwargs):
        pass


def test_reset_run_scoped_state_clears_client_link_metadata() -> None:
    adapter = _DummyAdapter()
    adapter._client_link_metadata = {
        "collection_status": "available",
        "source": "observed",
        "client_region": "us-east-1",
    }
    adapter._reset_run_scoped_state()
    assert adapter._client_link_metadata is None


def test_collect_client_link_metadata_with_probe_and_region() -> None:
    adapter = _DummyAdapter()
    conn = MagicMock()

    with (
        patch(
            "benchbox.platforms.base.adapter.probe_statement_overhead",
            return_value={
                "collection_status": "available",
                "source": "observed",
                "statement_overhead_ms": {"samples": 5, "min": 1.2, "median": 1.5},
            },
        ),
        patch(
            "benchbox.platforms.base.adapter.discover_client_region",
            return_value={
                "client_region": "us-east-1",
                "client_cloud": "aws",
                "source": "observed",
            },
        ),
    ):
        adapter._collect_client_link_metadata(conn, {"link_probe": True})

    assert adapter._client_link_metadata == {
        "collection_status": "available",
        "source": "observed",
        "client_region": "us-east-1",
        "client_cloud": "aws",
        "statement_overhead_ms": {"samples": 5, "min": 1.2, "median": 1.5},
        "collection_error_class": None,
        "collection_error_message": None,
    }


def test_collect_client_link_metadata_link_probe_disabled() -> None:
    adapter = _DummyAdapter()
    conn = MagicMock()

    with (
        patch("benchbox.platforms.base.adapter.probe_statement_overhead") as mock_probe,
        patch(
            "benchbox.platforms.base.adapter.discover_client_region",
            return_value={
                "client_region": "us-west-2",
                "client_cloud": "aws",
                "source": "cli_option",
            },
        ),
    ):
        adapter._collect_client_link_metadata(conn, {"link_probe": False, "client_region": "us-west-2"})
        mock_probe.assert_not_called()

    assert adapter._client_link_metadata == {
        "collection_status": "partial",
        "source": "cli_option",
        "client_region": "us-west-2",
        "client_cloud": "aws",
        "statement_overhead_ms": None,
        "collection_error_class": None,
        "collection_error_message": None,
    }


def test_build_default_normalized_result_metadata_merges_client_link() -> None:
    adapter = _DummyAdapter()
    adapter._client_link_metadata = {
        "collection_status": "available",
        "source": "observed",
        "client_region": "us-east-1",
        "client_cloud": "aws",
        "statement_overhead_ms": {"samples": 5, "min": 2.1, "median": 2.3},
    }

    metadata = build_default_normalized_result_metadata(adapter)
    exec_env = metadata.get("execution_environment", {})
    assert "client_link" in exec_env
    assert exec_env["client_link"]["client_region"] == "us-east-1"
    assert exec_env["client_link"]["statement_overhead_ms"]["median"] == 2.3


def test_collect_normalized_result_metadata_merges_client_link() -> None:
    adapter = _DummyAdapter()
    adapter._client_link_metadata = {
        "collection_status": "available",
        "source": "cli_option",
        "client_region": "eu-central-1",
        "client_cloud": "aws",
    }

    metadata = collect_normalized_result_metadata(adapter)
    exec_env = metadata.get("execution_environment", {})
    assert "client_link" in exec_env
    assert exec_env["client_link"]["client_region"] == "eu-central-1"
    assert exec_env["client_link"]["source"] == "cli_option"


def test_firebolt_adapter_preserves_client_link_metadata() -> None:
    adapter = FireboltAdapter(url="http://localhost:8123")
    adapter._client_link_metadata = {
        "collection_status": "available",
        "source": "observed",
        "client_region": "us-east-1",
        "client_cloud": "aws",
        "statement_overhead_ms": {"samples": 5, "min": 1.1, "median": 1.4},
    }

    metadata = adapter.get_normalized_result_metadata()
    assert "execution_environment" in metadata
    assert "client_link" in metadata["execution_environment"]
    assert metadata["execution_environment"]["client_link"]["client_region"] == "us-east-1"


def test_databricks_adapter_state_reset_and_metadata_inheritance() -> None:
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/warehouses/w123",
        access_token="test-token",
    )
    adapter._client_link_metadata = {
        "collection_status": "available",
        "source": "observed",
        "client_region": "us-east-1",
        "client_cloud": "aws",
        "statement_overhead_ms": {"samples": 5, "min": 1.5, "median": 1.8},
    }

    metadata = adapter.get_normalized_result_metadata(platform_info={})
    assert "execution_environment" in metadata
    assert "client_link" in metadata["execution_environment"]
    assert metadata["execution_environment"]["client_link"]["client_region"] == "us-east-1"

    adapter._reset_run_scoped_state()
    assert adapter._client_link_metadata is None
