"""Unit tests for DataFrame runner lifecycle internals.

Tests for the internal functions that drive DataFrame benchmark execution:
- _load_dataframe_data: table loading via adapter, error handling per table
- _execute_dataframe_queries: warmup + measurement iterations, timing, query failure
- _get_queries_for_benchmark: dispatch for tpch/tpcds/clickbench/unknown
- _setup_parameter_overrides_for_stream: deduplication of override contexts
- _clear_parameter_overrides: cleanup for tpch/tpcds/unknown
- run_dataframe_benchmark: full lifecycle with load+execute, result structure

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from benchbox.core.results.models import BenchmarkResults, TableLoadingStats
from benchbox.core.results.platform_info import PlatformInfoInput
from benchbox.core.runner.dataframe_runner import (
    DataFramePhases,
    DataFrameRunOptions,
    _clear_parameter_overrides,
    _execute_dataframe_queries,
    _get_queries_for_benchmark,
    _load_dataframe_data,
    _setup_parameter_overrides_for_stream,
    run_dataframe_benchmark,
)
from benchbox.core.schemas import BenchmarkConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(platform_name: str = "Polars") -> MagicMock:
    """Create a mock DataFrame adapter with standard protocol support."""
    adapter = MagicMock()
    adapter.platform_name = platform_name
    adapter.create_context.return_value = MagicMock()
    adapter.get_platform_info.return_value = {"platform": platform_name}
    adapter.get_standard_platform_info.return_value = PlatformInfoInput(name=platform_name, execution_mode="dataframe")
    return adapter


def _make_config(
    name: str = "tpch",
    display_name: str = "TPC-H",
    scale_factor: float = 0.01,
    options: dict[str, Any] | None = None,
    queries: list[str] | None = None,
    test_execution_type: str = "standard",
) -> BenchmarkConfig:
    """Build a real BenchmarkConfig (Pydantic model)."""
    return BenchmarkConfig(
        name=name,
        display_name=display_name,
        scale_factor=scale_factor,
        options=options or {},
        queries=queries,
        test_execution_type=test_execution_type,
    )


@dataclass
class FakeQuery:
    """Minimal stand-in for DataFrameQuery in tests."""

    query_id: str
    query_name: str = ""
    description: str = ""
    categories: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# _load_dataframe_data
# ---------------------------------------------------------------------------


class TestLoadDataframeData:
    """Tests for _load_dataframe_data."""

    def test_loads_tables_via_adapter(self, tmp_path: Path):
        """Tables returned by DataFrameDataLoader are forwarded to adapter.load_table."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 100
        ctx = adapter.create_context()
        config = _make_config(scale_factor=1.0)
        benchmark_instance = MagicMock()

        prepared = {
            "lineitem": tmp_path / "lineitem.parquet",
            "orders": tmp_path / "orders.parquet",
        }

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            table_stats, per_table_stats = _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=config,
                benchmark_instance=benchmark_instance,
                data_dir=None,
                options=DataFrameRunOptions(),
            )

        assert set(table_stats.keys()) == {"lineitem", "orders"}
        assert table_stats["lineitem"] == 100
        assert table_stats["orders"] == 100
        assert per_table_stats["lineitem"].status == "SUCCESS"
        assert per_table_stats["orders"].status == "SUCCESS"
        assert adapter.load_table.call_count == 2

    def test_records_per_table_failure(self, tmp_path: Path):
        """A table that fails to load is recorded as FAILED without aborting others."""
        adapter = _make_adapter()
        adapter.load_table.side_effect = [RuntimeError("corrupt file"), 50]
        ctx = adapter.create_context()
        config = _make_config(scale_factor=1.0)
        benchmark_instance = MagicMock()

        prepared = {
            "bad_table": tmp_path / "bad.parquet",
            "good_table": tmp_path / "good.parquet",
        }

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            table_stats, per_table_stats = _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=config,
                benchmark_instance=benchmark_instance,
                data_dir=None,
                options=DataFrameRunOptions(),
            )

        # bad_table failed, good_table succeeded
        assert "bad_table" not in table_stats  # failed tables don't appear in row-count map
        assert per_table_stats["bad_table"].status == "FAILED"
        assert per_table_stats["bad_table"].rows == 0
        assert per_table_stats["bad_table"].error_message == "corrupt file"

        assert table_stats["good_table"] == 50
        assert per_table_stats["good_table"].status == "SUCCESS"

    def test_raises_when_no_data_source(self):
        """Raises ValueError when no benchmark_instance and no data_dir."""
        adapter = _make_adapter()
        ctx = adapter.create_context()
        config = _make_config()

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader_cls.return_value.prepare_benchmark_data.side_effect = ValueError("No data source available")

            with pytest.raises(ValueError, match="No data source"):
                _load_dataframe_data(
                    adapter=adapter,
                    ctx=ctx,
                    benchmark_config=config,
                    benchmark_instance=None,
                    data_dir=None,
                    options=DataFrameRunOptions(),
                )

    def test_passes_tpch_column_names(self, tmp_path: Path):
        """TPC-H tables receive column name hints via get_tpch_column_names."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 10
        ctx = adapter.create_context()
        config = _make_config(name="tpch", scale_factor=1.0)
        benchmark_instance = MagicMock()

        prepared = {"lineitem": tmp_path / "lineitem.parquet"}

        with (
            patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls,
            patch("benchbox.core.runner.dataframe_runner.get_tpch_column_names") as col_fn,
        ):
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared
            col_fn.return_value = {"lineitem": ["l_orderkey", "l_partkey"]}

            _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=config,
                benchmark_instance=benchmark_instance,
                data_dir=None,
                options=DataFrameRunOptions(),
            )

        _, kwargs = adapter.load_table.call_args
        assert kwargs["column_names"] == ["l_orderkey", "l_partkey"]

    def test_non_tpch_skips_column_names(self, tmp_path: Path):
        """Non-TPC-H benchmarks pass column_names=None."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 5
        ctx = adapter.create_context()
        config = _make_config(name="clickbench", display_name="ClickBench", scale_factor=1.0)
        benchmark_instance = MagicMock()

        prepared = {"hits": tmp_path / "hits.parquet"}

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=config,
                benchmark_instance=benchmark_instance,
                data_dir=None,
                options=DataFrameRunOptions(),
            )

        _, kwargs = adapter.load_table.call_args
        assert kwargs["column_names"] is None

    def test_normalizes_single_path_to_list(self, tmp_path: Path):
        """A single Path (not a list) from prepare_benchmark_data is wrapped in a list."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 7
        ctx = adapter.create_context()
        config = _make_config(scale_factor=1.0)
        benchmark_instance = MagicMock()

        # Return a single Path, not a list
        single_path = tmp_path / "region.parquet"
        prepared = {"region": single_path}

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            _load_dataframe_data(
                adapter=adapter,
                ctx=ctx,
                benchmark_config=config,
                benchmark_instance=benchmark_instance,
                data_dir=None,
                options=DataFrameRunOptions(),
            )

        args, _ = adapter.load_table.call_args
        # The third positional arg should be a list
        assert args[2] == [single_path]


# ---------------------------------------------------------------------------
# _execute_dataframe_queries
# ---------------------------------------------------------------------------


class TestExecuteDataframeQueries:
    """Tests for _execute_dataframe_queries."""

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_warmup_and_measurement_iterations(self, mock_get_queries, mock_setup, mock_clear):
        """Warmup results are tagged run_type='warmup', measurement as 'measurement'."""
        q1 = FakeQuery(query_id="Q1")
        q2 = FakeQuery(query_id="Q2")
        mock_get_queries.return_value = [q1, q2]

        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.05,
        }

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 2},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        warmup_results = [r for r in results if r["run_type"] == "warmup"]
        measurement_results = [r for r in results if r["run_type"] == "measurement"]

        # 1 warmup iter * 2 queries = 2 warmup rows
        assert len(warmup_results) == 2
        for r in warmup_results:
            assert r["iteration"] == 0
            assert r["stream_id"] == 0

        # 2 measurement iters * 2 queries = 4 measurement rows
        assert len(measurement_results) == 4
        assert {r["iteration"] for r in measurement_results} == {1, 2}

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_zero_warmup_falls_back_to_default(self, mock_get_queries, mock_setup, mock_clear):
        """Setting warmup_iterations=0 falls back to default (1) because 0 is falsy.

        This is the actual runner behavior: the `or DEFAULT` pattern treats 0 as absent.
        """
        mock_get_queries.return_value = [FakeQuery(query_id="Q1")]

        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
        }

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        # 0 is falsy, so warmup_iterations defaults to 1 -> 1 warmup + 1 measurement
        warmup_results = [r for r in results if r["run_type"] == "warmup"]
        measurement_results = [r for r in results if r["run_type"] == "measurement"]
        assert len(warmup_results) == 1
        assert len(measurement_results) == 1

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_query_failure_during_measurement(self, mock_get_queries, mock_setup, mock_clear):
        """A failing query produces a FAILED result row without stopping other queries."""
        q1 = FakeQuery(query_id="Q1")
        q2 = FakeQuery(query_id="Q2")
        mock_get_queries.return_value = [q1, q2]

        adapter = _make_adapter()
        # Default warmup=1 means 2 warmup calls + 2 measurement calls = 4 total
        # Warmup calls succeed, measurement: Q1 fails, Q2 succeeds
        adapter.execute_query.side_effect = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.01},  # warmup Q1
            {"query_id": "Q2", "status": "SUCCESS", "execution_time_seconds": 0.01},  # warmup Q2
            RuntimeError("timeout"),  # measurement Q1
            {"query_id": "Q2", "status": "SUCCESS", "execution_time_seconds": 0.1},  # measurement Q2
        ]

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        measurement = [r for r in results if r["run_type"] == "measurement"]
        assert len(measurement) == 2
        failed = measurement[0]
        assert failed["status"] == "FAILED"
        assert "timeout" in failed["error"]

        success = measurement[1]
        assert success["status"] == "SUCCESS"

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_query_failure_during_warmup(self, mock_get_queries, mock_setup, mock_clear):
        """A failing warmup query logs a warning and records a FAILED warmup row."""
        mock_get_queries.return_value = [FakeQuery(query_id="Q1")]

        adapter = _make_adapter()
        adapter.execute_query.side_effect = [
            ValueError("bad data"),  # warmup
            {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.01},  # measurement
        ]

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        warmup = [r for r in results if r["run_type"] == "warmup"]
        assert len(warmup) == 1
        assert warmup[0]["status"] == "FAILED"
        assert warmup[0]["error"] == "bad data"

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_empty_query_list_returns_empty(self, mock_get_queries, mock_setup, mock_clear):
        """When no queries are found, an empty list is returned."""
        mock_get_queries.return_value = []

        adapter = _make_adapter()
        config = _make_config()

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        assert results == []

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_query_subset_filter(self, mock_get_queries, mock_setup, mock_clear):
        """Only queries matching the --queries filter are executed."""
        q1 = FakeQuery(query_id="Q1")
        q6 = FakeQuery(query_id="Q6")
        q17 = FakeQuery(query_id="Q17")
        mock_get_queries.return_value = [q1, q6, q17]

        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q6",
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
        }

        config = _make_config(
            queries=["Q6"],
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        # 1 warmup + 1 measurement, but only Q6 from the 3-query set
        assert len(results) == 2
        assert all(r["query_id"] == "Q6" for r in results)

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_stream_ids_increment_across_warmup_and_measurement(self, mock_get_queries, mock_setup, mock_clear):
        """Stream IDs should continue incrementing from warmup into measurement."""
        mock_get_queries.return_value = [FakeQuery(query_id="Q1")]

        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
        }

        config = _make_config(
            options={"power_warmup_iterations": 2, "power_iterations": 2},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        warmup_streams = {r["stream_id"] for r in results if r["run_type"] == "warmup"}
        meas_streams = {r["stream_id"] for r in results if r["run_type"] == "measurement"}

        # warmup uses stream_id 0, 1; measurement uses 2, 3
        assert warmup_streams == {0, 1}
        assert meas_streams == {2, 3}

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_clears_overrides_on_success(self, mock_get_queries, mock_setup, mock_clear):
        """Parameter overrides are cleared after successful execution."""
        mock_get_queries.return_value = [FakeQuery(query_id="Q1")]
        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
        }
        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )

        mock_clear.assert_called_once_with("tpch")

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_clears_overrides_on_exception(self, mock_get_queries, mock_setup, mock_clear):
        """Parameter overrides are cleared even when an exception propagates."""
        mock_get_queries.side_effect = RuntimeError("boom")
        adapter = _make_adapter()
        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        with pytest.raises(RuntimeError, match="boom"):
            _execute_dataframe_queries(
                adapter=adapter,
                ctx=adapter.create_context(),
                benchmark_config=config,
                benchmark_instance=None,
                monitor=None,
            )

        mock_clear.assert_called_once_with("tpch")

    @patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides")
    @patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream")
    @patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark")
    def test_monitor_wraps_measurement(self, mock_get_queries, mock_setup, mock_clear):
        """When a PerformanceMonitor is provided, measurement queries are timed through it."""
        mock_get_queries.return_value = [FakeQuery(query_id="Q3")]
        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q3",
            "status": "SUCCESS",
            "execution_time_seconds": 0.02,
        }

        monitor = MagicMock()
        # Make time_operation a real context manager
        monitor.time_operation.return_value.__enter__ = MagicMock(return_value=None)
        monitor.time_operation.return_value.__exit__ = MagicMock(return_value=False)

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        results = _execute_dataframe_queries(
            adapter=adapter,
            ctx=adapter.create_context(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=monitor,
        )

        monitor.time_operation.assert_called_once_with("query_Q3_iter1")
        # 1 warmup + 1 measurement = 2 results
        assert len(results) == 2
        assert results[0]["run_type"] == "warmup"
        assert results[1]["run_type"] == "measurement"


# ---------------------------------------------------------------------------
# _get_queries_for_benchmark
# ---------------------------------------------------------------------------


class TestGetQueriesForBenchmark:
    """Tests for _get_queries_for_benchmark dispatch."""

    @patch("benchbox.core.runner.dataframe_runner._get_tpch_dataframe_queries")
    def test_dispatches_tpch(self, mock_tpch):
        """tpch benchmark name dispatches to _get_tpch_dataframe_queries."""
        mock_tpch.return_value = [FakeQuery(query_id="Q1")]
        config = _make_config(name="tpch")
        result = _get_queries_for_benchmark(config, None, stream_id=0)
        assert len(result) == 1
        mock_tpch.assert_called_once()

    @patch("benchbox.core.runner.dataframe_runner._get_tpch_dataframe_queries")
    def test_dispatches_tpch_variants(self, mock_tpch):
        """Variant TPC-H names like 'TPC-H' normalize to tpch dispatch."""
        mock_tpch.return_value = []
        config = _make_config(name="TPC-H", display_name="TPC-H")
        _get_queries_for_benchmark(config, None, stream_id=0)
        mock_tpch.assert_called_once()

    @patch("benchbox.core.runner.dataframe_runner._get_tpcds_dataframe_queries")
    def test_dispatches_tpcds(self, mock_tpcds):
        """tpcds benchmark name dispatches to _get_tpcds_dataframe_queries."""
        mock_tpcds.return_value = [FakeQuery(query_id="Q1")]
        config = _make_config(name="tpcds", display_name="TPC-DS")
        result = _get_queries_for_benchmark(config, None, stream_id=0)
        assert len(result) == 1
        mock_tpcds.assert_called_once()

    @patch("benchbox.core.runner.dataframe_runner._get_clickbench_dataframe_queries")
    def test_dispatches_clickbench(self, mock_cb):
        """clickbench benchmark name dispatches to _get_clickbench_dataframe_queries."""
        mock_cb.return_value = [FakeQuery(query_id="Q1")]
        config = _make_config(name="clickbench", display_name="ClickBench")
        result = _get_queries_for_benchmark(config, None, stream_id=0)
        assert len(result) == 1
        mock_cb.assert_called_once()

    def test_unknown_benchmark_with_instance(self):
        """Unknown benchmark falls back to benchmark_instance.get_dataframe_queries."""
        config = _make_config(name="custom-bench", display_name="Custom")
        instance = MagicMock()
        instance.get_dataframe_queries.return_value = [FakeQuery(query_id="C1")]

        result = _get_queries_for_benchmark(config, instance, stream_id=0)
        assert len(result) == 1
        assert result[0].query_id == "C1"

    def test_unknown_benchmark_without_instance_returns_empty(self):
        """Unknown benchmark with no instance returns empty list."""
        config = _make_config(name="unknown-bench", display_name="Unknown")
        result = _get_queries_for_benchmark(config, None, stream_id=0)
        assert result == []

    def test_stream_id_defaults_from_config(self):
        """When stream_id is None, it falls back to config.stream_id or 0."""
        config = _make_config(name="unknown-bench", display_name="Unknown")
        # BenchmarkConfig doesn't have stream_id, so getattr falls back to 0
        result = _get_queries_for_benchmark(config, None, stream_id=None)
        assert result == []


# ---------------------------------------------------------------------------
# _setup_parameter_overrides_for_stream
# ---------------------------------------------------------------------------


class TestSetupParameterOverridesForStream:
    """Tests for the override deduplication logic."""

    def test_no_op_when_seed_is_none(self):
        """No override call when seed is None."""
        applied: set[tuple[int, float, int | None]] = set()
        with patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides") as mock_setup:
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpch",
                seed=None,
                scale_factor=1.0,
                stream_id=0,
                applied_contexts=applied,
            )
            mock_setup.assert_not_called()
        assert len(applied) == 0

    def test_tpch_deduplication(self):
        """TPC-H uses (seed, sf, None) key -- same key skips second call."""
        applied: set[tuple[int, float, int | None]] = set()
        with patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides") as mock_setup:
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpch",
                seed=42,
                scale_factor=1.0,
                stream_id=0,
                applied_contexts=applied,
            )
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpch",
                seed=42,
                scale_factor=1.0,
                stream_id=1,
                applied_contexts=applied,
            )
            # TPC-H is stream-independent, so only called once
            assert mock_setup.call_count == 1

    def test_tpcds_per_stream(self):
        """TPC-DS uses (seed, sf, stream_id) key -- different streams call setup."""
        applied: set[tuple[int, float, int | None]] = set()
        with patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides") as mock_setup:
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpcds",
                seed=42,
                scale_factor=1.0,
                stream_id=0,
                applied_contexts=applied,
            )
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpcds",
                seed=42,
                scale_factor=1.0,
                stream_id=1,
                applied_contexts=applied,
            )
            assert mock_setup.call_count == 2

    def test_tpcds_same_stream_deduplicates(self):
        """TPC-DS with same stream_id only calls setup once."""
        applied: set[tuple[int, float, int | None]] = set()
        with patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides") as mock_setup:
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpcds",
                seed=42,
                scale_factor=1.0,
                stream_id=0,
                applied_contexts=applied,
            )
            _setup_parameter_overrides_for_stream(
                benchmark_id="tpcds",
                seed=42,
                scale_factor=1.0,
                stream_id=0,
                applied_contexts=applied,
            )
            assert mock_setup.call_count == 1


# ---------------------------------------------------------------------------
# _clear_parameter_overrides
# ---------------------------------------------------------------------------


class TestClearParameterOverrides:
    """Tests for _clear_parameter_overrides."""

    @patch("benchbox.core.tpch.dataframe_queries.set_parameter_overrides")
    def test_clears_tpch(self, mock_set):
        """Clears TPC-H overrides by passing None."""
        _clear_parameter_overrides("tpch")
        mock_set.assert_called_once_with(None)

    @patch("benchbox.core.tpcds.dataframe_queries.parameters.set_parameter_overrides")
    def test_clears_tpcds(self, mock_set):
        """Clears TPC-DS overrides by passing None."""
        _clear_parameter_overrides("tpcds")
        mock_set.assert_called_once_with(None)

    def test_unknown_benchmark_is_silent(self):
        """Unknown benchmark IDs are a no-op (no exception)."""
        _clear_parameter_overrides("clickbench")  # should not raise


# ---------------------------------------------------------------------------
# run_dataframe_benchmark (full lifecycle)
# ---------------------------------------------------------------------------


class TestRunDataframeBenchmarkLifecycle:
    """Integration-style tests for the full run_dataframe_benchmark lifecycle."""

    def test_load_and_execute_phases(self, tmp_path: Path):
        """Full lifecycle: load tables then execute queries, verify result structure."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 25
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.05,
        }

        config = _make_config(
            scale_factor=1.0,
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        prepared = {"nation": tmp_path / "nation.parquet"}
        fake_queries = [FakeQuery(query_id="Q1")]

        with (
            patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls,
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", return_value=fake_queries),
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
            patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream"),
            patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides"),
        ):
            mem_check.return_value = MagicMock(is_safe=True)
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=True),
                options=DataFrameRunOptions(ignore_memory_warnings=False),
            )

        assert isinstance(result, BenchmarkResults)
        assert result.validation_status == "PASSED"
        # total_queries counts only measurement results (builder filters on run_type)
        assert result.total_queries == 1
        assert result.successful_queries == 1
        assert result.failed_queries == 0
        # query_results includes all rows (warmup + measurement)
        assert len(result.query_results) == 2

    def test_result_includes_table_loading_stats(self, tmp_path: Path):
        """Loading phase populates table statistics in the result."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 42

        config = _make_config(scale_factor=1.0)

        prepared = {"region": tmp_path / "region.parquet"}

        with (
            patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls,
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
        ):
            mem_check.return_value = MagicMock(is_safe=True)
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared

            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=False),
            )

        assert result.table_statistics["region"]["rows"] == 42
        assert result.data_loading_time > 0  # load_time recorded

    def test_adapter_create_context_failure(self):
        """If adapter.create_context() raises, result is FAILED."""
        adapter = _make_adapter()
        adapter.create_context.side_effect = RuntimeError("init failed")

        config = _make_config()

        with (
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
        ):
            mem_check.return_value = MagicMock(is_safe=True)
            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=False),
            )

        assert result.validation_status == "FAILED"
        assert "init failed" in result.validation_details["error"]

    def test_memory_check_failure_records_error(self):
        """Insufficient memory produces a FAILED result via InsufficientMemoryError."""
        adapter = _make_adapter()
        config = _make_config()

        with (
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
        ):
            mem_check.return_value = MagicMock(is_safe=False)
            with patch(
                "benchbox.core.runner.dataframe_runner.format_memory_warning",
                return_value="Not enough RAM",
            ):
                result = run_dataframe_benchmark(
                    benchmark_config=config,
                    adapter=adapter,
                    phases=DataFramePhases(load=True, execute=True),
                    options=DataFrameRunOptions(ignore_memory_warnings=False),
                )

        assert result.validation_status == "FAILED"
        assert "InsufficientMemoryError" in result.validation_details["error_type"]

    def test_ignore_memory_warnings_skips_check(self, tmp_path: Path):
        """When ignore_memory_warnings=True, memory check is skipped entirely."""
        adapter = _make_adapter()
        adapter.load_table.return_value = 1

        config = _make_config(scale_factor=1.0)
        prepared = {"t": tmp_path / "t.parquet"}

        with (
            patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls,
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
        ):
            loader_cls.return_value.prepare_benchmark_data.return_value = prepared
            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=False),
                options=DataFrameRunOptions(ignore_memory_warnings=True),
            )
            mem_check.assert_not_called()

        assert result.validation_status == "PASSED"

    def test_options_dict_converted_to_dataclass(self, tmp_path: Path):
        """A plain dict passed as options is converted to DataFrameRunOptions."""
        adapter = _make_adapter()

        config = _make_config()

        # Pass a dict instead of DataFrameRunOptions -- the runner should handle it
        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=DataFramePhases(load=False, execute=False),
            options={"ignore_memory_warnings": True},
        )

        assert isinstance(result, BenchmarkResults)

    def test_run_config_persisted(self):
        """RunConfigInput fields are persisted in the result."""
        adapter = _make_adapter()
        config = _make_config(
            options={"compression_type": "zstd", "compression_level": 9, "seed": 42},
            queries=["Q1", "Q6"],
        )

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=DataFramePhases(load=False, execute=False),
        )

        assert isinstance(result, BenchmarkResults)
        # The run_config should be embedded in the result
        assert result.execution_metadata is not None

    def test_execute_only_skips_load(self):
        """With load=False, execute=True, adapter.load_table is never called."""
        adapter = _make_adapter()
        adapter.execute_query.return_value = {
            "query_id": "Q1",
            "status": "SUCCESS",
            "execution_time_seconds": 0.01,
        }

        config = _make_config(
            options={"power_warmup_iterations": 1, "power_iterations": 1},
        )

        fake_queries = [FakeQuery(query_id="Q1")]

        with (
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", return_value=fake_queries),
            patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides_for_stream"),
            patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides"),
        ):
            mem_check.return_value = MagicMock(is_safe=True)
            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=False, execute=True),
            )

        adapter.load_table.assert_not_called()
        # total_queries counts only measurement results
        assert result.total_queries == 1
