"""Unit tests for DataFrame BenchmarkExecutionMixin behavior.

Covers:
- Missing data detection with adapter path
- Fail-fast on load errors (no query execution)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dataframe.query import DataFrameQuery, QueryRegistry
from benchbox.core.schemas import BenchmarkConfig
from benchbox.platforms.dataframe.benchmark_mixin import (
    BenchmarkExecutionMixin,
    DataFramePhases,
    DataFrameRunOptions,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class DummyAdapter(BenchmarkExecutionMixin):
    platform_name = "Polars"
    family = "expression"

    def __init__(self) -> None:
        self.execute_called = False
        self.executed_query_ids: list[str] = []
        self.loaded_paths: dict[str, list] = {}

    def create_context(self):
        return SimpleNamespace()

    def load_table(self, ctx, table_name, file_paths, column_names=None, delimiter=None, benchmark=None, **kwargs):
        self.loaded_paths[table_name] = file_paths
        return 1

    def execute_query(self, ctx, query, query_id=None):
        self.execute_called = True
        self.executed_query_ids.append(str(query.query_id))
        return {
            "query_id": query.query_id,
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
            "rows_returned": 1,
        }

    def get_platform_info(self):
        return {"platform": "Polars"}


class DummyPandasProfiledAdapter(DummyAdapter):
    family = "pandas"

    def __init__(self, *, query_plan=None) -> None:  # noqa: ANN001
        super().__init__()
        self._query_plan = query_plan
        self.profiled_called = False

    # Intentionally no `capture_plan` parameter: this matches PandasFamilyAdapter.
    def execute_query_profiled(self, ctx, query, query_id=None):
        _ = (ctx, query, query_id)
        self.profiled_called = True
        result = {
            "query_id": query.query_id,
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
            "rows_returned": 1,
        }
        profile = SimpleNamespace(query_plan=self._query_plan, plan_capture_time_ms=0.0)
        return result, profile


class FailingLoadAdapter(DummyAdapter):
    def load_table(self, ctx, table_name, file_paths, column_names=None, delimiter=None, benchmark=None, **kwargs):
        raise RuntimeError("load failed")


class DummyDataFusionAdapter(DummyAdapter):
    platform_name = "DataFusion"
    family = "expression"


class DummyBenchmarkWithPlatformSkips:
    """Benchmark that vends platform-specific skip lists via get_platform_skip_queries."""

    def get_platform_skip_queries(self, platform_name: str) -> list[str]:
        if platform_name.lower() == "datafusion":
            return ["list_filter", "list_transform"]
        if platform_name.lower() == "lakesail":
            return ["empty_build_join"]
        return []


class DummyBenchmark:
    def __init__(self, tables):
        self.name = "dummy"
        self.display_name = "Dummy"
        self.scale_factor = 1.0
        self.tables = tables

    def get_dataframe_queries(self):
        return [
            DataFrameQuery(
                query_id="Q1",
                query_name="Test",
                description="Test query",
                expression_impl=lambda _ctx: None,
            )
        ]


class DummyRegistryBenchmark:
    def __init__(self, tables):
        self.name = "read_primitives"
        self.display_name = "Read Primitives"
        self.scale_factor = 1.0
        self.tables = tables

    def get_dataframe_queries(self):
        registry = QueryRegistry("read_primitives")
        registry.register(
            DataFrameQuery(
                query_id="aggregation_simple",
                query_name="Aggregation",
                description="Aggregation query",
                expression_impl=lambda _ctx: None,
            )
        )
        registry.register(
            DataFrameQuery(
                query_id="filter_selective",
                query_name="Filter",
                description="Filter query",
                expression_impl=lambda _ctx: None,
            )
        )
        registry.register(
            DataFrameQuery(
                query_id="optimizer_exists_to_semijoin",
                query_name="Optimizer Exists",
                description="Should be skipped in DataFrame mode",
                expression_impl=lambda _ctx: None,
            )
        )
        return registry

    def get_dataframe_skip_queries(self):
        return ["optimizer_exists_to_semijoin"]


def test_fail_fast_on_missing_data(tmp_path):
    adapter = DummyAdapter()
    benchmark = DummyBenchmark({"customer": tmp_path / "missing.tbl"})
    config = BenchmarkConfig(name="dummy", display_name="Dummy", scale_factor=1.0)

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=True, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "FAILED"
    assert result.validation_details is not None
    assert result.validation_details.get("phase") == "data_loading"
    assert adapter.execute_called is False


def test_fail_fast_on_load_error(tmp_path):
    adapter = FailingLoadAdapter()
    tbl_path = tmp_path / "customer.tbl"
    tbl_path.write_text("1|Alice|\n")
    benchmark = DummyBenchmark({"customer": tbl_path})
    config = BenchmarkConfig(name="dummy", display_name="Dummy", scale_factor=1.0)

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=True, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "FAILED"
    assert result.validation_details is not None
    assert result.validation_details.get("phase") == "data_loading"
    assert adapter.execute_called is False


def test_registry_queries_and_skip_summary_are_supported(tmp_path):
    adapter = DummyAdapter()
    tbl_path = tmp_path / "lineitem.tbl"
    tbl_path.write_text("1|A|\n")
    benchmark = DummyRegistryBenchmark({"lineitem": tbl_path})
    config = BenchmarkConfig(name="read_primitives", display_name="Read Primitives", scale_factor=1.0)

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    query_ids = [q["query_id"] for q in result.query_results]
    assert "QOPTIMIZER_EXISTS_TO_SEMIJOIN" in query_ids
    assert any(qid.endswith("DF_SKIP_SUMMARY") for qid in query_ids)
    assert "optimizer_exists_to_semijoin" not in [q.lower() for q in adapter.executed_query_ids]

    summary = next(q for q in result.query_results if q["query_id"].endswith("DF_SKIP_SUMMARY"))
    skip_summary = summary["dataframe_skip_summary"]
    assert "row_count_validation" not in summary
    assert skip_summary["executed_total"] == 2
    assert skip_summary["skipped_total"] == 1
    assert skip_summary["skipped_by_category"]["optimizer"] == 1


def test_skip_summary_respects_query_filter(tmp_path):
    adapter = DummyAdapter()
    tbl_path = tmp_path / "lineitem.tbl"
    tbl_path.write_text("1|A|\n")
    benchmark = DummyRegistryBenchmark({"lineitem": tbl_path})
    config = BenchmarkConfig(name="read_primitives", display_name="Read Primitives", scale_factor=1.0)
    config.queries = ["aggregation_simple"]

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    query_ids = [q["query_id"] for q in result.query_results]
    assert "QOPTIMIZER_EXISTS_TO_SEMIJOIN" not in query_ids
    assert not any(qid.endswith("DF_SKIP_SUMMARY") for qid in query_ids)


def test_sharded_tables_use_prepared_paths_when_prefer_parquet(tmp_path):
    adapter = DummyAdapter()
    shard1 = tmp_path / "lineitem.tbl.1"
    shard2 = tmp_path / "lineitem.tbl.2"
    shard1.write_text("1|A|\n")
    shard2.write_text("2|B|\n")
    prepared = tmp_path / "lineitem.parquet"
    prepared.write_text("placeholder")

    benchmark = DummyBenchmark({"lineitem": [shard1, shard2]})
    config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)

    with patch("benchbox.platforms.dataframe.benchmark_mixin.DataFrameDataLoader.prepare_benchmark_data") as prep:
        prep.return_value = {"lineitem": prepared}
        result = adapter.run_benchmark(
            benchmark,
            benchmark_config=config,
            phases=DataFramePhases(load=True, execute=False),
            options=DataFrameRunOptions(prefer_parquet=True),
        )

    assert result.validation_status == "PASSED"
    prep.assert_called_once()
    assert adapter.loaded_paths["lineitem"] == [prepared]


def test_prefer_parquet_fails_fast_when_preparation_raises(tmp_path):
    adapter = DummyAdapter()
    source = tmp_path / "lineitem.tbl"
    source.write_text("1|A|\n")
    benchmark = DummyBenchmark({"lineitem": source})
    config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)

    with patch("benchbox.platforms.dataframe.benchmark_mixin.DataFrameDataLoader.prepare_benchmark_data") as prep:
        prep.side_effect = RuntimeError("conversion failed")
        result = adapter.run_benchmark(
            benchmark,
            benchmark_config=config,
            phases=DataFramePhases(load=True, execute=True),
            options=DataFrameRunOptions(prefer_parquet=True),
        )

    assert result.validation_status == "FAILED"
    assert result.validation_details is not None
    assert result.validation_details.get("phase") == "data_loading"
    assert "Data preparation failed in prefer_parquet mode" in result.validation_details.get("error", "")
    assert adapter.execute_called is False


def test_magicmock_benchmark_does_not_false_positive_skip_loader(tmp_path):
    adapter = DummyAdapter()
    tbl_path = tmp_path / "customer.tbl"
    tbl_path.write_text("1|Alice|\n")

    benchmark = MagicMock()
    benchmark.name = "dummy"
    benchmark.display_name = "Dummy"
    benchmark.scale_factor = 1.0
    benchmark.tables = {"customer": tbl_path}

    config = BenchmarkConfig(name="dummy", display_name="Dummy", scale_factor=1.0)

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=True, execute=False),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "PASSED"
    assert adapter.loaded_paths["customer"] == [tbl_path]


def test_magicmock_benchmark_does_not_false_positive_execute_workload():
    adapter = DummyAdapter()
    benchmark = MagicMock()
    benchmark.name = "dummy"
    benchmark.display_name = "Dummy"
    benchmark.scale_factor = 1.0
    benchmark.get_dataframe_queries = MagicMock(
        return_value=[
            DataFrameQuery(
                query_id="Q1",
                query_name="Test",
                description="Test query",
                expression_impl=lambda _ctx: None,
            )
        ]
    )
    config = BenchmarkConfig(
        name="dummy",
        display_name="Dummy",
        scale_factor=1.0,
        options={"power_warmup_iterations": 0, "power_iterations": 1},
    )

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "PASSED"
    assert benchmark.execute_dataframe_workload.called is False
    assert adapter.executed_query_ids == ["Q1"]


def test_capture_plans_uses_profiled_execution_without_capture_plan_kw(tmp_path):
    adapter = DummyPandasProfiledAdapter(query_plan={"kind": "logical"})
    tbl_path = tmp_path / "customer.tbl"
    tbl_path.write_text("1|Alice|\n")
    benchmark = DummyBenchmark({"customer": tbl_path})
    config = BenchmarkConfig(
        name="dummy",
        display_name="Dummy",
        scale_factor=1.0,
        options={"power_warmup_iterations": 0, "power_iterations": 1},
        capture_plans=True,
    )

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "PASSED"
    assert adapter.profiled_called is True
    assert result.query_plans_captured == 1
    assert result.plan_capture_failures == 0


def test_capture_plans_counts_missing_plan_as_failure(tmp_path):
    adapter = DummyPandasProfiledAdapter(query_plan=None)
    tbl_path = tmp_path / "customer.tbl"
    tbl_path.write_text("1|Alice|\n")
    benchmark = DummyBenchmark({"customer": tbl_path})
    config = BenchmarkConfig(
        name="dummy",
        display_name="Dummy",
        scale_factor=1.0,
        options={"power_warmup_iterations": 0, "power_iterations": 1},
        capture_plans=True,
    )

    result = adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=True),
        options=DataFrameRunOptions(prefer_parquet=False),
    )

    assert result.validation_status == "PASSED"
    assert result.query_plans_captured == 0
    assert result.plan_capture_failures == 1
    assert result.plan_capture_errors
    assert result.plan_capture_errors[0]["query_id"] == "Q1"


def test_collect_skip_query_ids_routes_through_get_platform_skip_queries():
    """Platform-specific skips flow through get_platform_skip_queries, not a hardcoded check."""
    adapter = DummyDataFusionAdapter()
    benchmark = DummyBenchmarkWithPlatformSkips()

    skip_ids = adapter._collect_skip_query_ids(benchmark)

    assert "LIST_FILTER" in skip_ids
    assert "LIST_TRANSFORM" in skip_ids


def test_collect_skip_query_ids_platform_dispatch_is_parameterized():
    """Different platforms get different skip lists from the same dispatch point."""
    datafusion_adapter = DummyDataFusionAdapter()
    polars_adapter = DummyAdapter()  # platform_name = "Polars"
    benchmark = DummyBenchmarkWithPlatformSkips()

    datafusion_skips = datafusion_adapter._collect_skip_query_ids(benchmark)
    polars_skips = polars_adapter._collect_skip_query_ids(benchmark)

    assert "LIST_FILTER" in datafusion_skips
    assert "LIST_FILTER" not in polars_skips


def test_collect_skip_query_ids_no_platform_skips_method():
    """Benchmarks without get_platform_skip_queries silently produce no platform skips."""
    adapter = DummyDataFusionAdapter()
    benchmark = DummyBenchmark(tables={})  # no get_platform_skip_queries

    skip_ids = adapter._collect_skip_query_ids(benchmark)

    assert "LIST_FILTER" not in skip_ids
    assert "LIST_TRANSFORM" not in skip_ids


class _StubTPCDSQueryManager:
    def get_query(self, query_id, seed=None, variant=None):  # noqa: ANN001
        _ = (query_id, seed, variant)
        return "SELECT 1"


def test_tpcds_dataframe_requires_variant_parity_in_mixin():
    """Mixin path should fail when TPC-DS variants are missing in DataFrame registry."""
    adapter = DummyAdapter()
    config = BenchmarkConfig(
        name="tpcds",
        display_name="TPC-DS",
        scale_factor=1.0,
        options={"tpcds_dataframe_variant_fallback": False},
    )

    benchmark = SimpleNamespace(query_manager=_StubTPCDSQueryManager())

    with pytest.raises(RuntimeError, match="missing variant DataFrame implementations"):
        adapter._get_queries_for_benchmark(config, benchmark, stream_id=0)
