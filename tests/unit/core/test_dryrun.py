"""Tests for benchbox.core.dryrun module.

Focuses on pure-computation methods and save_dry_run_results to bring
coverage from ~40% to ≥50%.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from benchbox.core.dryrun import DryRunExecutor

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# DryRunExecutor.__init__
# ---------------------------------------------------------------------------


class TestDryRunExecutorInit:
    def test_with_output_dir(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path / "custom")
        assert executor.output_dir == tmp_path / "custom"
        assert executor.output_dir.exists()

    def test_without_output_dir(self):
        executor = DryRunExecutor()
        assert executor.output_dir.exists()
        assert "benchbox_dryrun_" in str(executor.output_dir)


# ---------------------------------------------------------------------------
# _serialize_config
# ---------------------------------------------------------------------------


class TestSerializeConfig:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_serialize_object_with_dict(self):
        obj = MagicMock()
        obj.__dict__ = {"name": "tpch", "scale_factor": 0.01, "_private": "skip", "method": lambda: None}
        # callable check filters out the method; _private is filtered by prefix
        result = self.executor._serialize_config(obj)
        assert result["name"] == "tpch"
        assert result["scale_factor"] == 0.01
        assert "_private" not in result

    def test_serialize_plain_value(self):
        # Non-object without __dict__ returns empty dict
        result = self.executor._serialize_config(42)
        assert result == {}

    def test_serialize_none(self):
        result = self.executor._serialize_config(None)
        assert result == {}


# ---------------------------------------------------------------------------
# _estimate_data_size
# ---------------------------------------------------------------------------


class TestEstimateDataSize:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def _make_benchmark(self, sf=0.01):
        bm = MagicMock()
        bm.scale_factor = sf
        return bm

    def test_tpch(self):
        bm = self._make_benchmark(1.0)
        result = self.executor._estimate_data_size(bm, "tpch")
        assert result == 8 * 1.0 * 100  # 800 MB

    def test_tpcds(self):
        bm = self._make_benchmark(1.0)
        result = self.executor._estimate_data_size(bm, "tpcds")
        assert result == 24 * 1.0 * 100  # 2400 MB

    def test_ssb(self):
        bm = self._make_benchmark(0.01)
        result = self.executor._estimate_data_size(bm, "ssb")
        assert result == 6 * 0.01 * 100  # 6 MB

    def test_clickbench(self):
        bm = self._make_benchmark(0.01)
        result = self.executor._estimate_data_size(bm, "clickbench")
        assert result == 100 * 0.01 * 100

    def test_unknown(self):
        bm = self._make_benchmark(1.0)
        result = self.executor._estimate_data_size(bm, "custom")
        assert result == 10 * 1.0 * 100  # default 10 MB base


# ---------------------------------------------------------------------------
# _estimate_memory_usage
# ---------------------------------------------------------------------------


class TestEstimateMemoryUsage:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_basic(self):
        bm = MagicMock()
        bm.scale_factor = 0.01
        sp = MagicMock()
        sp.memory_gb = 16

        result = self.executor._estimate_memory_usage(bm, sp, "tpch")
        # data_size = 8 * 0.01 * 100 = 8; memory = min(8*2.5, 16*1024*0.8) = 20
        assert result == pytest.approx(20.0)

    def test_capped_by_system_memory(self):
        bm = MagicMock()
        bm.scale_factor = 100.0
        sp = MagicMock()
        sp.memory_gb = 4

        result = self.executor._estimate_memory_usage(bm, sp, "tpch")
        # data_size = 8*100*100 = 80000; capped at 4*1024*0.8 = 3276.8
        assert result == pytest.approx(4 * 1024 * 0.8)


# ---------------------------------------------------------------------------
# _estimate_runtime
# ---------------------------------------------------------------------------


class TestEstimateRuntime:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_basic(self):
        bm = MagicMock()
        bm.get_all_queries.return_value = {str(i): f"SELECT {i}" for i in range(22)}
        bm.scale_factor = 1.0

        result = self.executor._estimate_runtime(bm)
        # 22 queries * 10s * max(1.0, 0.01) / 60 = 220/60 ≈ 3.67
        assert result == pytest.approx(22 * 10 * 1.0 / 60.0)

    def test_small_scale(self):
        bm = MagicMock()
        bm.get_all_queries.return_value = {"1": "SELECT 1"}
        bm.scale_factor = 0.001

        result = self.executor._estimate_runtime(bm)
        # 1 * 10 * max(0.001, 0.01) / 60 = 0.1/60
        assert result == pytest.approx(10 * 0.01 / 60.0)


# ---------------------------------------------------------------------------
# _extract_constraint_config
# ---------------------------------------------------------------------------


class TestExtractConstraintConfig:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_tuning_disabled(self):
        config = MagicMock()
        config.options = {"tuning_enabled": False}
        result = self.executor._extract_constraint_config(config)
        assert result["enable_primary_keys"] is False
        assert result["enable_foreign_keys"] is False

    def test_tuning_enabled_with_config(self):
        tuning = MagicMock()
        tuning.primary_keys.enabled = True
        tuning.foreign_keys.enabled = True

        config = MagicMock()
        config.options = {"tuning_enabled": True, "unified_tuning_configuration": tuning}
        result = self.executor._extract_constraint_config(config)
        assert result["enable_primary_keys"] is True
        assert result["enable_foreign_keys"] is True

    def test_tuning_enabled_no_config(self):
        config = MagicMock()
        config.options = {"tuning_enabled": True}
        result = self.executor._extract_constraint_config(config)
        assert result["enable_primary_keys"] is False
        assert result["enable_foreign_keys"] is False


# ---------------------------------------------------------------------------
# _get_execution_context
# ---------------------------------------------------------------------------


class TestGetExecutionContext:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def _make_config(self, name="tpch", test_type="standard"):
        config = MagicMock()
        config.name = name
        config.test_execution_type = test_type
        return config

    def test_standard(self):
        cfg = self._make_config(test_type="standard")
        result = self.executor._get_execution_context(cfg, 22)
        assert "Standard sequential execution" in result
        assert "22 queries" in result

    def test_power_tpch(self):
        cfg = self._make_config(name="tpch", test_type="power")
        result = self.executor._get_execution_context(cfg, 22)
        assert "TPC-H PowerTest" in result

    def test_power_tpcds(self):
        cfg = self._make_config(name="tpcds", test_type="power")
        result = self.executor._get_execution_context(cfg, 99)
        assert "TPC-DS PowerTest" in result

    def test_power_other(self):
        cfg = self._make_config(name="ssb", test_type="power")
        result = self.executor._get_execution_context(cfg, 13)
        assert "Power test execution" in result

    def test_throughput_tpcds(self):
        cfg = self._make_config(name="tpcds", test_type="throughput")
        result = self.executor._get_execution_context(cfg, 396)
        assert "TPC-DS ThroughputTest" in result
        assert "concurrent streams" in result

    def test_throughput_other(self):
        cfg = self._make_config(name="tpch", test_type="throughput")
        result = self.executor._get_execution_context(cfg, 88)
        assert "Throughput test execution" in result

    def test_maintenance_tpcds(self):
        cfg = self._make_config(name="tpcds", test_type="maintenance")
        result = self.executor._get_execution_context(cfg, 0)
        assert "TPC-DS MaintenanceTest" in result

    def test_maintenance_other(self):
        cfg = self._make_config(name="tpch", test_type="maintenance")
        result = self.executor._get_execution_context(cfg, 0)
        assert "Maintenance test execution" in result


# ---------------------------------------------------------------------------
# _estimate_resources
# ---------------------------------------------------------------------------


class TestEstimateResources:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_basic(self):
        bm = MagicMock()
        bm.scale_factor = 0.01
        bm.get_all_queries.return_value = {str(i): "" for i in range(22)}

        sp = MagicMock()
        sp.cpu_cores_logical = 8
        sp.memory_gb = 16

        result = self.executor._estimate_resources(bm, sp, "tpch")
        assert result["scale_factor"] == 0.01
        assert result["estimated_data_size_mb"] > 0
        assert result["cpu_cores_available"] == 8
        assert result["memory_gb_available"] == 16

    def test_with_error(self):
        bm = MagicMock()
        bm.scale_factor = MagicMock(side_effect=AttributeError("no sf"))

        sp = MagicMock()
        result = self.executor._estimate_resources(bm, sp, "tpch")
        assert "error" in result


# ---------------------------------------------------------------------------
# save_dry_run_results
# ---------------------------------------------------------------------------


class TestSaveDryRunResults:
    def _make_result(self, queries=None, execution_mode="sql"):
        """Create a mock DryRunResult."""
        result = MagicMock()
        result.timestamp = datetime(2026, 2, 7, 12, 0, 0)
        result.model_dump.return_value = {
            "timestamp": datetime(2026, 2, 7, 12, 0, 0),
            "benchmark_config": {"name": "tpch"},
            "database_config": {"type": "duckdb"},
            "system_profile": {},
            "platform_config": {},
            "queries": queries or {"1": "SELECT 1", "2": "SELECT 2"},
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
        result.queries = queries or {"1": "SELECT 1", "2": "SELECT 2"}
        result.execution_mode = execution_mode
        result.schema_sql = None
        result.dataframe_schema = None
        result.ddl_preview = None
        result.post_load_statements = None
        return result

    def test_save_json_and_yaml(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result()
        saved = executor.save_dry_run_results(result, filename_prefix="test")

        assert "json" in saved
        assert "yaml" in saved
        assert saved["json"].exists()
        assert saved["yaml"].exists()

        # Verify JSON content
        data = json.loads(saved["json"].read_text())
        assert data["benchmark_config"]["name"] == "tpch"

        # Verify YAML content
        data = yaml.safe_load(saved["yaml"].read_text())
        assert data["benchmark_config"]["name"] == "tpch"

    def test_save_sql_queries(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result(queries={"1": "SELECT 1", "6": "SELECT COUNT(*) FROM lineitem"})
        saved = executor.save_dry_run_results(result)

        assert "queries_dir" in saved
        queries_dir = saved["queries_dir"]
        assert queries_dir.exists()

        sql_files = list(queries_dir.glob("*.sql"))
        assert len(sql_files) == 2

    def test_save_dataframe_queries(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        queries = {
            "Q1": "def query_1(df):\n    return df.select('col')",
            "Q2": "def query_2(df):\n    return df.filter(True)",
        }
        result = self._make_result(queries=queries, execution_mode="dataframe")
        saved = executor.save_dry_run_results(result)

        assert "queries_dir" in saved
        py_files = list(saved["queries_dir"].glob("*.py"))
        assert len(py_files) == 2

    def test_save_dataframe_queries_skips_errors(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        queries = {"_error": "# Failed", "Q1": "def query_1(df): pass"}
        result = self._make_result(queries=queries, execution_mode="dataframe")
        saved = executor.save_dry_run_results(result)

        py_files = list(saved["queries_dir"].glob("*.py"))
        assert len(py_files) == 1  # Only Q1, not _error

    def test_save_with_ddl_preview(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result()
        result.ddl_preview = {
            "lineitem": {
                "ddl_clauses": "ORDER BY (l_shipdate)",
                "tuning_summary": {"sort_by": "l_shipdate"},
            }
        }
        saved = executor.save_dry_run_results(result)

        assert "ddl" in saved
        content = saved["ddl"].read_text()
        assert "lineitem" in content
        assert "ORDER BY" in content

    def test_save_with_post_load(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result()
        result.post_load_statements = {
            "orders": ["CREATE INDEX idx_orderdate ON orders(o_orderdate)"],
        }
        saved = executor.save_dry_run_results(result)

        assert "post_load" in saved
        content = saved["post_load"].read_text()
        assert "orders" in content
        assert "CREATE INDEX" in content

    def test_save_with_sql_schema(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result()
        result.schema_sql = "CREATE TABLE t (id INT);"
        saved = executor.save_dry_run_results(result)

        assert "schema" in saved
        content = saved["schema"].read_text()
        assert "CREATE TABLE" in content

    def test_save_with_dataframe_schema(self, tmp_path):
        executor = DryRunExecutor(output_dir=tmp_path)
        result = self._make_result(execution_mode="dataframe")
        result.dataframe_schema = "import polars as pl\nSCHEMA = {}"
        saved = executor.save_dry_run_results(result)

        assert "schema" in saved
        content = saved["schema"].read_text()
        assert "polars" in content

    def test_save_no_output_dir(self):
        executor = DryRunExecutor()
        executor.output_dir = None
        result = self._make_result()
        saved = executor.save_dry_run_results(result)
        assert saved == {}


# ---------------------------------------------------------------------------
# _extract_standard_queries
# ---------------------------------------------------------------------------


class TestExtractStandardQueries:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_get_queries(self):
        bm = MagicMock()
        bm.get_queries.return_value = {"Q1": "SELECT 1", "Q2": "SELECT 2"}
        del bm.get_all_queries  # Ensure it uses get_queries first
        del bm.query_manager
        result = self.executor._extract_standard_queries(bm)
        assert result == {"Q1": "SELECT 1", "Q2": "SELECT 2"}

    def test_get_queries_with_int_keys(self):
        bm = MagicMock()
        bm.get_queries.return_value = {1: "SELECT 1", 2: "SELECT 2"}
        del bm.get_all_queries
        del bm.query_manager
        result = self.executor._extract_standard_queries(bm)
        assert result == {"1": "SELECT 1", "2": "SELECT 2"}

    def test_get_all_queries_fallback(self):
        bm = MagicMock()
        bm.get_queries.return_value = None
        bm.get_all_queries.return_value = {"Q1": "SELECT 1"}
        del bm.query_manager
        result = self.executor._extract_standard_queries(bm)
        assert result == {"Q1": "SELECT 1"}

    def test_query_manager_fallback(self):
        bm = MagicMock()
        bm.get_queries.return_value = None
        bm.get_all_queries.return_value = None
        bm.query_manager.get_all_queries.return_value = {1: "SELECT 1"}
        result = self.executor._extract_standard_queries(bm)
        assert result == {"1": "SELECT 1"}

    def test_no_queries_found(self):
        bm = MagicMock(spec=[])  # No attributes
        result = self.executor._extract_standard_queries(bm)
        assert result == {}


# ---------------------------------------------------------------------------
# _generate_schema_sql - external table mode dispatch
# ---------------------------------------------------------------------------


class TestGenerateSchemaSQL:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def test_native_mode_uses_create_tables_sql(self):
        bm = MagicMock()
        bm.get_create_tables_sql.return_value = "CREATE TABLE t (id INT);"
        config = MagicMock()
        config.options = {"table_mode": "native"}

        result = self.executor._generate_schema_sql(bm, config)
        assert "CREATE TABLE" in result

    def test_external_mode_delegates_to_external_schema(self):
        bm = MagicMock()
        bm.get_schema.return_value = {"orders": {"name": "orders", "columns": []}}
        config = MagicMock()
        config.options = {"table_mode": "external", "table_format": "iceberg"}

        result = self.executor._generate_schema_sql(bm, config)
        assert "CREATE VIEW" in result
        assert "iceberg_scan" in result

    def test_missing_table_mode_defaults_to_native(self):
        bm = MagicMock()
        bm.get_create_tables_sql.return_value = "CREATE TABLE t (id INT);"
        config = MagicMock()
        config.options = {}

        result = self.executor._generate_schema_sql(bm, config)
        assert "CREATE TABLE" in result


# ---------------------------------------------------------------------------
# _generate_external_schema_sql
# ---------------------------------------------------------------------------


class TestGenerateExternalSchemaSQL:
    def setup_method(self):
        self.executor = DryRunExecutor()

    def _make_config(self, table_format=None):
        config = MagicMock()
        config.options = {"table_mode": "external", "table_format": table_format}
        return config

    def _make_benchmark(self, table_names):
        bm = MagicMock()
        bm.get_schema.return_value = {name: {"name": name, "columns": []} for name in table_names}
        return bm

    def test_iceberg_format(self):
        bm = self._make_benchmark(["lineitem", "orders"])
        config = self._make_config("iceberg")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "iceberg_scan" in result
        assert "CREATE VIEW lineitem" in result
        assert "CREATE VIEW orders" in result

    def test_delta_format(self):
        bm = self._make_benchmark(["lineitem"])
        config = self._make_config("delta")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "delta_scan" in result

    def test_parquet_format(self):
        bm = self._make_benchmark(["lineitem"])
        config = self._make_config("parquet")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "read_parquet" in result

    def test_vortex_format(self):
        bm = self._make_benchmark(["lineitem"])
        config = self._make_config("vortex")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "read_vortex" in result

    def test_none_format_defaults_to_parquet(self):
        bm = self._make_benchmark(["lineitem"])
        config = self._make_config(None)

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "read_parquet" in result

    def test_no_schema_returns_fallback_message(self):
        bm = MagicMock(spec=[])  # no get_schema
        config = self._make_config("iceberg")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "schema not available" in result

    def test_list_schema_format(self):
        """Some benchmarks return list[dict] with 'name' keys."""
        bm = MagicMock()
        bm.get_schema.return_value = [{"name": "region"}, {"name": "nation"}]
        config = self._make_config("delta")

        result = self.executor._generate_external_schema_sql(bm, config)
        assert "CREATE VIEW region" in result
        assert "CREATE VIEW nation" in result
        assert "delta_scan" in result


# ---------------------------------------------------------------------------
# execute_dry_run - dry_run=True injected into platform config
# ---------------------------------------------------------------------------


class TestDryRunPlatformConfigInjection:
    def test_dry_run_flag_injected(self):
        executor = DryRunExecutor()
        config = MagicMock()
        config.name = "tpch"
        config.scale_factor = 0.01
        config.options = {}
        config.queries = None
        config.compress_data = False
        config.test_execution_type = "standard"

        db_config = MagicMock()
        db_config.type = "duckdb"
        db_config.execution_mode = None

        sp = MagicMock()
        sp.cpu_cores_logical = 4
        sp.memory_gb = 8

        with (
            patch.object(executor, "_get_benchmark_instance") as mock_bm,
            patch("benchbox.core.dryrun.get_platform_adapter") as mock_adapter,
            patch.object(executor, "_get_platform_config", return_value={"some": "config"}),
        ):
            mock_bm.return_value = MagicMock()
            mock_adapter.return_value = MagicMock()

            executor.execute_dry_run(config, sp, db_config)

            # Verify dry_run=True was passed to get_platform_adapter
            call_kwargs = mock_adapter.call_args
            assert call_kwargs[1].get("dry_run") is True or (
                len(call_kwargs[0]) > 1 and call_kwargs[0][1].get("dry_run") is True
            )

    def test_get_platform_config_resolves_data_source_benchmark(self):
        """_get_platform_config should override benchmark_name with data source name."""
        executor = DryRunExecutor()
        benchmark_config = MagicMock()
        benchmark_config.name = "read_primitives"
        benchmark_config.scale_factor = 1.0

        benchmark = MagicMock()
        benchmark.get_data_source_benchmark.return_value = "tpch"

        with patch("benchbox.core.platform_config.get_platform_config", return_value={}) as mock_core:
            executor._get_platform_config(
                database_config=MagicMock(),
                system_profile=MagicMock(),
                benchmark_config=benchmark_config,
                benchmark=benchmark,
            )

        assert mock_core.call_args[0][2] == "tpch"

    def test_get_platform_config_passes_through_when_no_data_source(self):
        """_get_platform_config should keep original benchmark_name when no data source."""
        executor = DryRunExecutor()
        benchmark_config = MagicMock()
        benchmark_config.name = "tpch"
        benchmark_config.scale_factor = 0.01

        benchmark = MagicMock()
        benchmark.get_data_source_benchmark.return_value = None

        with patch("benchbox.core.platform_config.get_platform_config", return_value={}) as mock_core:
            executor._get_platform_config(
                database_config=MagicMock(),
                system_profile=MagicMock(),
                benchmark_config=benchmark_config,
                benchmark=benchmark,
            )

        assert mock_core.call_args[0][2] == "tpch"


# ---------------------------------------------------------------------------
# Benchmark identity contract regression tests (w10 of
# eliminate-non-data-loading-wrong-layer-compensation)
# ---------------------------------------------------------------------------


class TestDryRunBenchmarkIdentityContract:
    """_extract_queries must use BenchmarkConfig.name for TPC routing, not
    benchmark object internals (_name, display_name, class names)."""

    def test_extract_queries_uses_benchmark_config_name_for_tpch_routing(self):
        """Routing to TPC-H maintenance path uses BenchmarkConfig.name, not _name."""
        executor = DryRunExecutor()
        # Benchmark object whose _name does NOT contain "tpch" - would fail old sniffing.
        benchmark = MagicMock()
        benchmark._name = "adhoc"

        benchmark_config = MagicMock()
        benchmark_config.name = "tpch"
        benchmark_config.test_execution_type = "maintenance"

        with patch.object(executor, "_extract_tpch_maintenance_operations", return_value={"RF1": "..."}) as patched:
            result = executor._extract_queries(benchmark, benchmark_config)

        patched.assert_called_once()
        assert result == {"RF1": "..."}

    def test_extract_queries_uses_benchmark_config_name_for_tpcds_routing(self):
        """Routing to TPC-DS combined path uses BenchmarkConfig.name, not _name."""
        executor = DryRunExecutor()
        benchmark = MagicMock()
        benchmark._name = "custom"

        benchmark_config = MagicMock()
        benchmark_config.name = "tpcds"
        benchmark_config.test_execution_type = "combined"

        with (
            patch.object(executor, "_extract_standard_queries", return_value={"1": "SELECT 1"}) as std,
            patch.object(executor, "_extract_tpcds_maintenance_operations", return_value={"RF1": "..."}) as maint,
        ):
            result = executor._extract_queries(benchmark, benchmark_config)

        std.assert_called_once()
        maint.assert_called_once()
        assert "1" in result and "RF1" in result

    def test_extract_queries_via_real_test_execution_uses_benchmark_config_name(self):
        """_extract_queries_via_real_test_execution routes using BenchmarkConfig.name."""
        executor = DryRunExecutor()
        benchmark = MagicMock()
        benchmark._name = "anything"

        benchmark_config = MagicMock()
        benchmark_config.name = "tpch"
        benchmark_config.scale_factor = 0.01

        with patch.object(executor, "_execute_tpch_test_class", return_value={"Q1": "SELECT 1"}) as patched:
            result = executor._extract_queries_via_real_test_execution(benchmark, benchmark_config, "power")

        patched.assert_called_once()
        assert result == {"Q1": "SELECT 1"}
