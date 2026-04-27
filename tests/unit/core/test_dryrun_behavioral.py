"""Behavioral tests for core/dryrun.py: helper functions and save logic.

Targets uncovered paths (particularly _extract_df_write_tuning,
_build_table_ddl_entry, _resolve_execution_mode, and the
_extract_dataframe_queries branch) to push coverage from ~71% toward 82%.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dryrun import (
    DryRunExecutor,
    _build_table_ddl_entry,
    _extract_df_write_tuning,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# _extract_df_write_tuning
# ---------------------------------------------------------------------------


class TestExtractDfWriteTuning:
    def _make_write_config(self, **overrides):
        cfg = MagicMock()
        cfg.sort_by = overrides.get("sort_by")
        cfg.partition_by = overrides.get("partition_by")
        cfg.row_group_size = overrides.get("row_group_size")
        cfg.repartition_count = overrides.get("repartition_count")
        cfg.compression = overrides.get("compression", "zstd")
        cfg.compression_level = overrides.get("compression_level")
        cfg.dictionary_columns = overrides.get("dictionary_columns")
        return cfg

    def test_empty_config_returns_empty_dict(self):
        cfg = self._make_write_config()
        result = _extract_df_write_tuning(cfg)
        assert result == {}

    def test_sort_by_extracted(self):
        col = MagicMock()
        col.name = "ts"
        col.order = "asc"
        cfg = self._make_write_config(sort_by=[col])
        result = _extract_df_write_tuning(cfg)
        assert result["sort_by"] == [{"name": "ts", "order": "asc"}]

    def test_partition_by_extracted(self):
        col = MagicMock()
        col.name = "region"
        col.strategy = MagicMock(value="hash")
        cfg = self._make_write_config(partition_by=[col])
        result = _extract_df_write_tuning(cfg)
        assert result["partition_by"] == [{"name": "region", "strategy": "hash"}]

    def test_row_group_size_extracted(self):
        cfg = self._make_write_config(row_group_size=65536)
        result = _extract_df_write_tuning(cfg)
        assert result["row_group_size"] == 65536

    def test_repartition_count_extracted(self):
        cfg = self._make_write_config(repartition_count=8)
        result = _extract_df_write_tuning(cfg)
        assert result["repartition_count"] == 8

    def test_non_default_compression_extracted(self):
        cfg = self._make_write_config(compression="gzip")
        result = _extract_df_write_tuning(cfg)
        assert result["compression"] == "gzip"

    def test_default_compression_not_in_output(self):
        cfg = self._make_write_config(compression="zstd")
        result = _extract_df_write_tuning(cfg)
        assert "compression" not in result

    def test_compression_level_extracted(self):
        cfg = self._make_write_config(compression_level=6)
        result = _extract_df_write_tuning(cfg)
        assert result["compression_level"] == 6

    def test_dictionary_columns_extracted(self):
        cfg = self._make_write_config(dictionary_columns=["status", "priority"])
        result = _extract_df_write_tuning(cfg)
        assert result["dictionary_columns"] == ["status", "priority"]


# ---------------------------------------------------------------------------
# _build_table_ddl_entry
# ---------------------------------------------------------------------------


class TestBuildTableDdlEntry:
    def _make_tuning_clauses(self, **kwargs):
        tc = MagicMock()
        tc.sort_by = kwargs.get("sort_by")
        tc.partition_by = kwargs.get("partition_by")
        tc.cluster_by = kwargs.get("cluster_by")
        tc.distribution_key = kwargs.get("distribution_key")
        tc.distribution_style = kwargs.get("distribution_style")
        return tc

    def test_empty_clauses(self):
        tc = self._make_tuning_clauses()
        result = _build_table_ddl_entry(tc)
        assert result["ddl_clauses"] is None
        assert result["tuning_summary"] == {}

    def test_sort_by_clause(self):
        tc = self._make_tuning_clauses(sort_by="l_shipdate")
        result = _build_table_ddl_entry(tc)
        assert "ORDER BY (l_shipdate)" in result["ddl_clauses"]
        assert result["tuning_summary"]["sort_by"] == "l_shipdate"

    def test_partition_by_clause(self):
        tc = self._make_tuning_clauses(partition_by="region")
        result = _build_table_ddl_entry(tc)
        assert "PARTITION BY (region)" in result["ddl_clauses"]
        assert result["tuning_summary"]["partition_by"] == "region"

    def test_cluster_by_clause(self):
        tc = self._make_tuning_clauses(cluster_by="customer_id")
        result = _build_table_ddl_entry(tc)
        assert "CLUSTER BY (customer_id)" in result["ddl_clauses"]
        assert result["tuning_summary"]["cluster_by"] == "customer_id"

    def test_distribution_style_and_key(self):
        tc = self._make_tuning_clauses(distribution_style="KEY", distribution_key="order_id")
        result = _build_table_ddl_entry(tc)
        assert "DISTSTYLE KEY" in result["ddl_clauses"]
        assert "DISTKEY (order_id)" in result["ddl_clauses"]
        assert result["tuning_summary"]["distribution_style"] == "KEY"
        assert result["tuning_summary"]["distribution_key"] == "order_id"

    def test_multiple_clauses_joined(self):
        tc = self._make_tuning_clauses(sort_by="ts", partition_by="region")
        result = _build_table_ddl_entry(tc)
        assert "ORDER BY (ts)" in result["ddl_clauses"]
        assert "PARTITION BY (region)" in result["ddl_clauses"]


# ---------------------------------------------------------------------------
# DryRunExecutor._resolve_execution_mode
# ---------------------------------------------------------------------------


class TestResolveExecutionMode:
    def test_none_database_config_returns_sql(self):
        mode = DryRunExecutor._resolve_execution_mode(None)
        assert mode == "sql"

    def test_explicit_dataframe_mode(self):
        db_config = MagicMock()
        db_config.type = "polars-df"
        db_config.execution_mode = "dataframe"
        mode = DryRunExecutor._resolve_execution_mode(db_config)
        assert mode == "dataframe"

    def test_explicit_sql_mode(self):
        db_config = MagicMock()
        db_config.type = "duckdb"
        db_config.execution_mode = "sql"
        mode = DryRunExecutor._resolve_execution_mode(db_config)
        assert mode == "sql"


# ---------------------------------------------------------------------------
# DryRunExecutor._extract_queries - dataframe / maintenance branches
# ---------------------------------------------------------------------------


class TestExtractQueriesBranches:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_load_only_returns_empty(self):
        bm = MagicMock()
        cfg = MagicMock()
        cfg.test_execution_type = "load_only"
        result = self.executor._extract_queries(bm, cfg)
        assert result == {}

    def test_dataframe_maintenance_returns_not_supported(self):
        bm = MagicMock()
        cfg = MagicMock()
        cfg.test_execution_type = "maintenance"
        result = self.executor._extract_queries(
            bm, cfg, platform_adapter=None, execution_mode="dataframe", platform_type="polars-df"
        )
        assert "_maintenance_not_supported" in result
        assert "not yet implemented" in result["_maintenance_not_supported"]

    def test_dataframe_combined_returns_not_supported(self):
        bm = MagicMock()
        cfg = MagicMock()
        cfg.test_execution_type = "combined"
        result = self.executor._extract_queries(
            bm, cfg, platform_adapter=None, execution_mode="dataframe", platform_type="polars-df"
        )
        assert "_maintenance_not_supported" in result


# ---------------------------------------------------------------------------
# DryRunExecutor._generate_dataframe_schema
# ---------------------------------------------------------------------------


class TestGenerateDataframeSchema:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_generates_polars_schema(self):
        bm = MagicMock()
        bm.get_create_tables_sql.return_value = """
        CREATE TABLE orders (
            order_id INTEGER,
            amount DECIMAL(10,2)
        );
        """
        cfg = MagicMock()
        cfg.name = "tpch"
        cfg.options = {}
        result = self.executor._generate_dataframe_schema(bm, cfg)
        assert isinstance(result, str)
        assert "orders" in result

    def test_no_schema_returns_fallback(self):
        bm = MagicMock(spec=[])
        cfg = MagicMock()
        cfg.name = "tpch"
        cfg.options = {}
        result = self.executor._generate_dataframe_schema(bm, cfg)
        assert result is None


# ---------------------------------------------------------------------------
# save_dry_run_results - additional edge cases
# ---------------------------------------------------------------------------


class TestSaveDryRunResultsExtended:
    def _make_result(self, queries=None, execution_mode="sql"):
        result = MagicMock()
        result.timestamp = datetime(2026, 3, 24, 10, 0, 0)
        result.model_dump.return_value = {
            "timestamp": datetime(2026, 3, 24, 10, 0, 0),
            "benchmark_config": {"name": "tpch"},
            "database_config": {"type": "duckdb"},
            "system_profile": {},
            "platform_config": {},
            "queries": queries or {},
            "execution_mode": execution_mode,
            "query_preview": {},
            "warnings": [],
            "schema_sql": None,
            "dataframe_schema": None,
            "ddl_preview": None,
            "post_load_statements": None,
            "tuning_config": None,
            "constraint_config": {},
            "estimated_resources": {},
        }
        result.queries = queries or {}
        result.execution_mode = execution_mode
        result.schema_sql = None
        result.dataframe_schema = None
        result.ddl_preview = None
        result.post_load_statements = None
        return result

    def test_save_with_empty_queries(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result(queries={})
        saved = executor.save_dry_run_results(result)
        assert "json" in saved
        assert "yaml" in saved
        # queries_dir should still be created (empty)
        assert "queries_dir" in saved
        sql_files = list(saved["queries_dir"].glob("*"))
        assert len(sql_files) == 0

    def test_save_with_ddl_and_post_load_together(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result(queries={"1": "SELECT 1"})
        result.ddl_preview = {
            "lineitem": {
                "ddl_clauses": "ORDER BY (l_shipdate)",
                "tuning_summary": {"sort_by": "l_shipdate"},
            },
            "orders": {
                "ddl_clauses": None,
                "tuning_summary": {},
            },
        }
        result.post_load_statements = {
            "lineitem": [
                "CREATE INDEX idx_shipdate ON lineitem(l_shipdate)",
                "ANALYZE lineitem",
            ],
        }
        saved = executor.save_dry_run_results(result)
        assert "ddl" in saved
        assert "post_load" in saved

        ddl_content = saved["ddl"].read_text()
        assert "lineitem" in ddl_content

        post_load_content = saved["post_load"].read_text()
        assert "CREATE INDEX" in post_load_content
        assert "ANALYZE" in post_load_content


# ---------------------------------------------------------------------------
# DryRunExecutor._estimate_data_size - additional benchmarks
# ---------------------------------------------------------------------------


class TestEstimateDataSizeExtended:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def _make_benchmark(self, sf=0.01):
        bm = MagicMock()
        bm.scale_factor = sf
        return bm

    def test_h2odb(self):
        bm = self._make_benchmark(1.0)
        result = self.executor._estimate_data_size(bm, "h2odb")
        # h2odb uses a specific multiplier; just verify it is positive
        assert result > 0

    def test_tpcdi(self):
        bm = self._make_benchmark(1.0)
        result = self.executor._estimate_data_size(bm, "tpcdi")
        assert result > 0

    def test_joinorder(self):
        bm = self._make_benchmark(0.1)
        result = self.executor._estimate_data_size(bm, "joinorder")
        assert result > 0
