"""Tests for Databricks liquid clustering tuning behavior."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from benchbox.core.tuning.interface import UnifiedTuningConfiguration
from benchbox.platforms.databricks import DatabricksAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


def _make_col(name: str, order: int):
    col = Mock()
    col.name = name
    col.order = order
    return col


def _make_table_tuning(cluster_cols=None, distribution_cols=None, sort_cols=None):
    from benchbox.core.tuning.interface import TuningType

    table_tuning = Mock()
    table_tuning.table_name = "test_table"
    table_tuning.has_any_tuning.return_value = True

    cluster_cols = cluster_cols or []
    distribution_cols = distribution_cols or []
    sort_cols = sort_cols or []

    def get_columns_by_type(tuning_type):
        if tuning_type == TuningType.CLUSTERING:
            return cluster_cols
        if tuning_type == TuningType.DISTRIBUTION:
            return distribution_cols
        if tuning_type == TuningType.SORTING:
            return sort_cols
        return []

    table_tuning.get_columns_by_type.side_effect = get_columns_by_type
    return table_tuning


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
def test_apply_table_tunings_uses_liquid_clustering_when_configured(_mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.databricks_clustering_strategy = "liquid_clustering"
    unified.platform_optimizations.liquid_clustering_enabled = True
    unified.platform_optimizations.liquid_clustering_columns = ["event_time", "customer_id"]
    adapter.unified_tuning_configuration = unified

    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [("Provider", "delta")]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    table_tuning = _make_table_tuning(cluster_cols=[_make_col("cluster_key", 1)])
    adapter.apply_table_tunings(table_tuning, mock_connection)

    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    assert any("ALTER TABLE TEST_TABLE CLUSTER BY (event_time, customer_id)" in call for call in execute_calls)
    assert not any("ZORDER BY" in call for call in execute_calls)
    assert adapter._liquid_clustering_operations == [
        {
            "table": "TEST_TABLE",
            "columns": ["event_time", "customer_id"],
            "statement": "ALTER TABLE TEST_TABLE CLUSTER BY (event_time, customer_id)",
            "mode": "manual",
        }
    ]
    assert [operation["mechanism"] for operation in adapter._applied_layout_operations] == [
        "liquid_clustering",
        "optimize",
        "analyze",
    ]


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
def test_apply_table_tunings_keeps_z_order_default_behavior(_mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.databricks_clustering_strategy = "z_order"
    adapter.unified_tuning_configuration = unified

    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [("Provider", "delta")]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    table_tuning = _make_table_tuning(
        cluster_cols=[_make_col("cluster_key", 1)],
        distribution_cols=[_make_col("dist_key", 2)],
    )
    adapter.apply_table_tunings(table_tuning, mock_connection)

    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    assert any("OPTIMIZE TEST_TABLE ZORDER BY (cluster_key, dist_key)" in call for call in execute_calls)
    assert adapter._z_order_operations == [
        {
            "table": "TEST_TABLE",
            "columns": ["cluster_key", "dist_key"],
            "statement": "OPTIMIZE TEST_TABLE ZORDER BY (cluster_key, dist_key)",
        }
    ]
    assert [operation["mechanism"] for operation in adapter._applied_layout_operations] == [
        "z_order",
        "optimize",
        "analyze",
    ]


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
def test_strategy_conflict_rejects_liquid_when_legacy_z_order_is_also_enabled(_mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.z_ordering_enabled = True
    unified.platform_optimizations.databricks_clustering_strategy = "z_order"
    unified.platform_optimizations.liquid_clustering_enabled = True
    unified.platform_optimizations.liquid_clustering_columns = ["event_time"]
    adapter.unified_tuning_configuration = unified

    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [("Provider", "delta")]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    table_tuning = _make_table_tuning(cluster_cols=[_make_col("cluster_key", 1)])
    with pytest.raises(ValueError, match="Liquid Clustering cannot be combined"):
        adapter.apply_table_tunings(table_tuning, mock_connection)


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
def test_apply_table_tunings_uses_liquid_auto_when_configured(_mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.databricks_clustering_strategy = "liquid_clustering_auto"
    unified.platform_optimizations.liquid_clustering_enabled = True
    adapter.unified_tuning_configuration = unified

    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [("Provider", "delta")]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    table_tuning = _make_table_tuning(cluster_cols=[_make_col("cluster_key", 1)])
    adapter.apply_table_tunings(table_tuning, mock_connection)

    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    assert any("ALTER TABLE TEST_TABLE CLUSTER BY AUTO" in call for call in execute_calls)
    assert adapter._liquid_clustering_operations == [
        {
            "table": "TEST_TABLE",
            "columns": [],
            "statement": "ALTER TABLE TEST_TABLE CLUSTER BY AUTO",
            "mode": "auto",
        }
    ]
    assert [operation["mechanism"] for operation in adapter._applied_layout_operations] == [
        "liquid_clustering_auto",
        "optimize",
        "analyze",
    ]


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
def test_apply_table_tunings_liquid_clustering_falls_back_to_sort_columns(_mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.databricks_clustering_strategy = "liquid_clustering"
    unified.platform_optimizations.liquid_clustering_enabled = True
    adapter.unified_tuning_configuration = unified

    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [("Provider", "delta")]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    table_tuning = _make_table_tuning(sort_cols=[_make_col("ship_date", 1), _make_col("order_key", 2)])
    adapter.apply_table_tunings(table_tuning, mock_connection)

    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    assert any("ALTER TABLE TEST_TABLE CLUSTER BY (ship_date, order_key)" in call for call in execute_calls)


@patch("benchbox.platforms.databricks.adapter.databricks_sql")
@patch("databricks.sdk.WorkspaceClient")
def test_platform_metadata_includes_clustering_strategy_and_operations(_mock_workspace_client, _mock_databricks_sql):
    adapter = DatabricksAdapter(
        server_hostname="test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/test",
        access_token="test_token",
        catalog="main",
        schema="benchbox",
    )

    unified = UnifiedTuningConfiguration()
    unified.platform_optimizations.databricks_clustering_strategy = "liquid_clustering"
    unified.platform_optimizations.liquid_clustering_enabled = True
    unified.platform_optimizations.liquid_clustering_columns = ["event_time"]
    adapter.unified_tuning_configuration = unified

    adapter._liquid_clustering_operations.append(
        {
            "table": "TEST_TABLE",
            "columns": ["event_time"],
            "statement": "ALTER TABLE TEST_TABLE CLUSTER BY (event_time)",
        }
    )

    mock_cursor = Mock()
    mock_cursor.fetchone.side_effect = [["Spark 3.5.0"], ["main", "benchbox"]]
    mock_cursor.fetchall.side_effect = [[["current_catalog"]], []]
    mock_connection = Mock()
    mock_connection.cursor.return_value = mock_cursor

    metadata = adapter._get_platform_metadata(mock_connection)
    assert metadata["databricks_clustering_strategy"] == "liquid_clustering"
    assert metadata["liquid_clustering_enabled"] is True
    assert metadata["liquid_clustering_columns_config"] == ["event_time"]
    assert metadata["liquid_clustering_operations"] == [
        {
            "table": "TEST_TABLE",
            "columns": ["event_time"],
            "statement": "ALTER TABLE TEST_TABLE CLUSTER BY (event_time)",
        }
    ]
    assert metadata["z_order_operations"] == []
    assert metadata["requested_databricks_clustering_strategy"] == "liquid_clustering"
    assert metadata["resolved_databricks_clustering_strategy"] == "liquid_clustering"
    assert metadata["applied_layout_operations"] == []
    assert metadata["skipped_layout_operations"] == []

    platform_info = adapter.get_platform_info(mock_connection)
    assert platform_info["configuration"]["requested_databricks_clustering_strategy"] == "liquid_clustering"
    assert platform_info["configuration"]["resolved_databricks_clustering_strategy"] == "liquid_clustering"
    assert platform_info["configuration"]["databricks_clustering_strategy"] == "liquid_clustering"
    assert platform_info["configuration"]["liquid_clustering_enabled"] is True
    assert platform_info["configuration"]["liquid_clustering_columns_config"] == ["event_time"]
    assert platform_info["configuration"]["liquid_clustering_operations"] == [
        {
            "table": "TEST_TABLE",
            "columns": ["event_time"],
            "statement": "ALTER TABLE TEST_TABLE CLUSTER BY (event_time)",
        }
    ]
    assert platform_info["configuration"]["z_order_operations"] == []
    assert platform_info["configuration"]["applied_layout_operations"] == []
    assert platform_info["configuration"]["skipped_layout_operations"] == []
