"""Tests for Databricks SQL generation branches - coverage extension.

Targets: catalog.schema.table naming in DDL, TBLPROPERTIES injection,
_build_ctas_sort_sql variants, vacuum_table SQL, get_target_dialect.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def databricks_deps():
    with patch("benchbox.platforms.databricks.adapter.check_platform_dependencies", return_value=(True, [])):
        yield


def _make_adapter(**kwargs):
    """Create a DatabricksAdapter without real credentials."""
    with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
        from benchbox.platforms.databricks.adapter import DatabricksAdapter

        defaults = {
            "server_hostname": "test.azuredatabricks.net",
            "http_path": "/sql/1.0/warehouses/abc",
            "access_token": "testtoken",
            "catalog": "main",
            "schema": "benchbox",
        }
        defaults.update(kwargs)
        return DatabricksAdapter(**defaults)


class TestDatabricksBuildCtasSortSql:
    def test_z_order_generates_optimize_zorder(self):
        adapter = _make_adapter()
        col = Mock()
        col.name = "l_orderkey"
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "z_order")):
            result = adapter._build_ctas_sort_sql("LINEITEM", [col])
        assert result == "OPTIMIZE LINEITEM ZORDER BY (l_orderkey)"

    def test_liquid_clustering_generates_alter_cluster_by(self):
        adapter = _make_adapter()
        col = Mock()
        col.name = "ps_partkey"
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "liquid_clustering")):
            result = adapter._build_ctas_sort_sql("PARTSUPP", [col])
        assert result == "ALTER TABLE PARTSUPP CLUSTER BY (ps_partkey)"

    def test_ctas_generates_create_or_replace(self):
        adapter = _make_adapter()
        col = Mock()
        col.name = "o_orderdate"
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "ctas")):
            result = adapter._build_ctas_sort_sql("ORDERS", [col])
        assert "CREATE OR REPLACE TABLE ORDERS" in result
        assert "ORDER BY o_orderdate" in result

    def test_off_mode_returns_none(self):
        adapter = _make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("off", "auto")):
            result = adapter._build_ctas_sort_sql("LINEITEM", [Mock()])
        assert result is None

    def test_multi_col_z_order(self):
        adapter = _make_adapter()
        col1, col2 = Mock(), Mock()
        col1.name = "l_orderkey"
        col2.name = "l_linenumber"
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "z_order")):
            result = adapter._build_ctas_sort_sql("LINEITEM", [col1, col2])
        assert "ZORDER BY (l_orderkey, l_linenumber)" in result


class TestDatabricksTblpropertiesInjection:
    def test_adds_tblproperties_when_missing(self):
        adapter = _make_adapter(delta_auto_optimize=True)
        # Simulate a CREATE TABLE statement without TBLPROPERTIES
        stmt = "CREATE TABLE main.benchbox.lineitem (l_orderkey BIGINT) USING DELTA"
        result = adapter._convert_to_delta_table(stmt)
        assert "TBLPROPERTIES" in result

    def test_adds_auto_optimize_properties(self):
        adapter = _make_adapter(delta_auto_optimize=True)
        stmt = "CREATE TABLE t (id INT) USING DELTA"
        result = adapter._convert_to_delta_table(stmt)
        assert "'delta.autoOptimize.optimizeWrite' = 'true'" in result
        assert "'delta.autoOptimize.autoCompact' = 'true'" in result

    def test_does_not_duplicate_tblproperties(self):
        adapter = _make_adapter(delta_auto_optimize=True)
        stmt = "CREATE TABLE t (id INT) USING DELTA TBLPROPERTIES ('x'='y')"
        result = adapter._convert_to_delta_table(stmt)
        assert result.count("TBLPROPERTIES") == 1

    def test_empty_tblproperties_when_auto_optimize_off(self):
        adapter = _make_adapter(delta_auto_optimize=False)
        stmt = "CREATE TABLE t (id INT) USING DELTA"
        result = adapter._convert_to_delta_table(stmt)
        # With auto_optimize off, TBLPROPERTIES is added but empty
        assert "TBLPROPERTIES ()" in result
        assert "autoOptimize" not in result


class TestDatabricksVacuumTable:
    def test_vacuum_executes_vacuum_statement(self):
        adapter = _make_adapter(enable_delta_optimization=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.vacuum_table(mock_conn, "lineitem", hours=24)
        executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list if call.args]
        assert any("VACUUM" in sql and "LINEITEM" in sql and "24" in sql for sql in executed_sql)


class TestDatabricksGetTargetDialect:
    def test_returns_databricks(self):
        adapter = _make_adapter()
        dialect = adapter.get_target_dialect()
        assert "databricks" in dialect.lower() or "spark" in dialect.lower()


class TestDatabricksCopyIntoSql:
    def test_copy_into_contains_table_name(self):
        adapter = _make_adapter()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (100,)
        mock_benchmark = MagicMock()
        mock_benchmark.get_schema.return_value = {}

        with (
            patch.object(
                adapter,
                "_resolve_file_uri_and_delimiter",
                return_value=("dbfs:/Volumes/data/lineitem.csv", "lineitem.csv", "|"),
            ),
            patch.object(adapter, "_get_column_list_for_table", return_value=""),
            patch.object(adapter, "get_effective_tuning_configuration", return_value=None),
        ):
            adapter._load_single_table(
                mock_cursor,
                MagicMock(),
                mock_benchmark,
                "lineitem",
                "lineitem.csv",
                "dbfs:/Volumes/main/benchbox/vol",
                {"lineitem"},
            )

        executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list if call.args]
        assert any("COPY INTO" in sql and "LINEITEM" in sql for sql in executed_sql)
