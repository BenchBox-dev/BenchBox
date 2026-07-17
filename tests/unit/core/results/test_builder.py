"""Unit tests for centralized result builder."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from benchbox.core.results.builder import (
    BenchmarkInfoInput,
    ResultBuilder,
    RunConfigInput,
    build_benchmark_results,
    normalize_benchmark_id,
)
from benchbox.core.results.platform_info import PlatformInfoInput
from benchbox.core.results.query_normalizer import QueryResultInput, normalize_query_result

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestNormalizeBenchmarkId:
    """Tests for normalize_benchmark_id function."""

    @pytest.mark.parametrize(
        ("input_name", "expected_id"),
        [
            # TPC-H variants
            ("TPC-H", "tpch"),
            ("TPC-H Benchmark", "tpch"),
            ("tpch", "tpch"),
            ("tpc-h", "tpch"),
            ("tpc_h", "tpch"),
            ("TPCH", "tpch"),
            # TPC-DS variants
            ("TPC-DS", "tpcds"),
            ("TPC-DS Benchmark", "tpcds"),
            ("tpcds", "tpcds"),
            ("tpc-ds", "tpcds"),
            ("tpc_ds", "tpcds"),
            ("TPCDS", "tpcds"),
            # SSB variants
            ("SSB", "ssb"),
            ("ssb", "ssb"),
            ("SSB Benchmark", "ssb"),
            # ClickBench variants
            ("ClickBench", "clickbench"),
            ("clickbench", "clickbench"),
            ("ClickBench Benchmark", "clickbench"),
            # Derived benchmarks (must NOT false-match parent patterns)
            ("tpcds_obt", "tpcds_obt"),
            ("tpcds-obt", "tpcds_obt"),
            ("TPC-DS One Big Table Benchmark", "tpcds_obt"),
            ("tpch_skew", "tpch_skew"),
            ("tpch-skew", "tpch_skew"),
            # Custom benchmarks (generic normalization)
            ("Custom Benchmark", "custom"),
            ("My-Custom-Test", "my_custom_test"),
            ("Some Other Benchmark", "some_other"),
        ],
    )
    def test_normalize_benchmark_id(self, input_name: str, expected_id: str) -> None:
        """Test benchmark ID normalization for various inputs."""
        assert normalize_benchmark_id(input_name) == expected_id

    def test_normalize_removes_double_underscores(self) -> None:
        """Test that double underscores are collapsed."""
        assert normalize_benchmark_id("my__test") == "my_test"
        assert normalize_benchmark_id("my - - test") == "my_test"

    def test_derived_benchmarks_not_confused_with_parents(self) -> None:
        """Derived benchmarks must resolve to their own ID, not the parent's."""
        # tpcds_obt contains "tpcds" as substring - must NOT resolve to "tpcds"
        assert normalize_benchmark_id("tpcds_obt") != "tpcds"
        assert normalize_benchmark_id("tpcds_obt") == "tpcds_obt"
        # tpch_skew contains "tpch" as substring - must NOT resolve to "tpch"
        assert normalize_benchmark_id("tpch_skew") != "tpch"
        assert normalize_benchmark_id("tpch_skew") == "tpch_skew"


class TestBenchmarkInfoInput:
    """Tests for BenchmarkInfoInput dataclass."""

    def test_create_basic(self) -> None:
        """Test creating basic BenchmarkInfoInput."""
        info = BenchmarkInfoInput(name="TPC-H", scale_factor=1.0)

        assert info.name == "TPC-H"
        assert info.scale_factor == 1.0
        assert info.test_type == "power"
        assert info.display_name is None

    def test_create_with_all_fields(self) -> None:
        """Test creating BenchmarkInfoInput with all fields."""
        info = BenchmarkInfoInput(
            name="TPC-H",
            scale_factor=10.0,
            test_type="throughput",
            display_name="TPC-H Benchmark",
        )

        assert info.name == "TPC-H"
        assert info.scale_factor == 10.0
        assert info.test_type == "throughput"
        assert info.display_name == "TPC-H Benchmark"


class TestResultBuilder:
    """Tests for ResultBuilder class."""

    def create_builder(
        self,
        benchmark_name: str = "TPC-H",
        scale_factor: float = 1.0,
        platform_name: str = "DuckDB",
        execution_mode: str = "sql",
    ) -> ResultBuilder:
        """Create a ResultBuilder for testing."""
        return ResultBuilder(
            benchmark=BenchmarkInfoInput(name=benchmark_name, scale_factor=scale_factor),
            platform=PlatformInfoInput(name=platform_name, execution_mode=execution_mode),
        )

    def create_query_result(
        self,
        query_id: str = "1",
        execution_time: float = 1.0,
        rows: int = 100,
        status: str = "SUCCESS",
    ) -> QueryResultInput:
        """Create a QueryResultInput for testing."""
        return QueryResultInput(
            query_id=query_id,
            execution_time_seconds=execution_time,
            rows_returned=rows,
            status=status,
        )

    def test_build_empty_results(self) -> None:
        """Test building results with no queries."""
        builder = self.create_builder()
        result = builder.build()

        assert result.benchmark_name == "TPC-H"
        assert result.platform == "DuckDB"
        assert result.scale_factor == 1.0
        assert result.total_queries == 0
        assert result.successful_queries == 0
        assert result.failed_queries == 0

    def test_build_with_query_results(self) -> None:
        """Test building results with query results."""
        builder = self.create_builder()
        builder.add_query_result(self.create_query_result("1", 1.0, 100))
        builder.add_query_result(self.create_query_result("2", 2.0, 200))
        builder.add_query_result(self.create_query_result("3", 3.0, 300))

        result = builder.build()

        assert result.total_queries == 3
        assert result.successful_queries == 3
        assert result.failed_queries == 0
        assert len(result.query_results) == 3

    def test_build_with_failed_queries(self) -> None:
        """Test building results with failed queries."""
        builder = self.create_builder()
        builder.add_query_result(self.create_query_result("1", 1.0, 100, "SUCCESS"))
        builder.add_query_result(self.create_query_result("2", 0.0, 0, "FAILED"))

        result = builder.build()

        assert result.total_queries == 2
        assert result.successful_queries == 1
        assert result.failed_queries == 1
        assert result.validation_status == "PARTIAL"

    def test_build_with_validation_failed_query_counts_as_failed(self) -> None:
        """#1150 review: a write/op that ran but failed a post-condition check
        (write_primitives/transaction_primitives status="VALIDATION_FAILED")
        must count as a failure in aggregate accounting, not vanish from both
        successful_queries and failed_queries.
        """
        builder = self.create_builder()
        builder.add_query_result(self.create_query_result("1", 1.0, 100, "SUCCESS"))
        builder.add_query_result(self.create_query_result("2", 1.0, 100, "VALIDATION_FAILED"))

        result = builder.build()

        assert result.total_queries == 2
        assert result.successful_queries == 1
        assert result.failed_queries == 1
        assert result.validation_status == "PARTIAL"

    def test_build_calculates_tpc_metrics(self) -> None:
        """Test that TPC metrics are calculated."""
        builder = self.create_builder(scale_factor=1.0)

        # Add 4 queries with 1 second each (geom mean = 1)
        for i in range(1, 5):
            builder.add_query_result(self.create_query_result(str(i), 1.0, 100))

        result = builder.build()

        # Power@Size = (SF * 3600) / geom_mean = (1 * 3600) / 1 = 3600
        assert result.power_at_size is not None
        assert result.power_at_size == 3600.0
        # Use approximate comparison for floating point
        assert result.geometric_mean_execution_time is not None
        assert abs(result.geometric_mean_execution_time - 1.0) < 0.0001

    def test_build_with_table_stats(self) -> None:
        """Test building results with table loading statistics."""
        builder = self.create_builder()
        builder.add_table_stats("lineitem", 6001215, load_time_ms=1000)
        builder.add_table_stats("orders", 1500000, load_time_ms=500)
        builder.set_loading_time(1500.0)

        result = builder.build()

        assert result.total_rows_loaded == 6001215 + 1500000
        assert result.data_loading_time == 1.5  # 1500ms -> 1.5s
        assert "lineitem" in result.table_statistics
        assert result.table_statistics["lineitem"] == {"rows": 6001215, "load_time_ms": 1000}

    def test_build_with_execution_phases(self) -> None:
        """Test that execution phases are built correctly."""
        builder = self.create_builder()
        builder.add_table_stats("lineitem", 1000, load_time_ms=100)
        builder.set_loading_time(100.0)
        builder.add_query_result(self.create_query_result("1", 1.0, 100))

        result = builder.build()

        assert result.execution_phases is not None
        assert result.execution_phases.setup is not None
        assert result.execution_phases.setup.data_loading is not None
        assert result.execution_phases.power_test is not None

    def test_build_dataframe_platform_display(self) -> None:
        """Test that DataFrame platforms get correct display name."""
        builder = self.create_builder(
            platform_name="Polars",
            execution_mode="dataframe",
        )
        result = builder.build()

        assert result.platform == "Polars"

    def test_build_with_timestamps(self) -> None:
        """Test building results with explicit timestamps."""
        builder = self.create_builder()
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 30)
        builder.set_start_time(start)
        builder.set_end_time(end)

        result = builder.build()

        assert result.timestamp == start
        assert result.duration_seconds == 30.0

    def test_build_with_mark_timestamps(self) -> None:
        """Test building results with mark_started/mark_completed."""
        builder = self.create_builder()
        builder.mark_started()
        # Simulate some time passing
        builder.mark_completed()

        result = builder.build()

        assert result.timestamp is not None
        assert result.duration_seconds >= 0

    def test_build_with_validation_status(self) -> None:
        """Test building results with explicit validation status."""
        builder = self.create_builder()
        builder.set_validation_status("FAILED", {"error": "Test error", "phase": "load"})

        result = builder.build()

        assert result.validation_status == "FAILED"
        assert result.validation_details == {"error": "Test error", "phase": "load"}

    def test_build_with_execution_metadata(self) -> None:
        """Test building results with execution metadata."""
        builder = self.create_builder()
        builder.set_execution_metadata({"custom_key": "value"})
        builder.add_execution_metadata("another_key", "another_value")

        result = builder.build()

        assert "custom_key" in result.execution_metadata
        assert result.execution_metadata["custom_key"] == "value"
        assert result.execution_metadata["another_key"] == "another_value"

    def test_build_with_system_profile(self) -> None:
        """Test building results with system profile."""
        builder = self.create_builder()
        profile = {"cpu": "Apple M1", "memory": "16GB"}
        builder.set_system_profile(profile)

        result = builder.build()

        assert result.system_profile == profile

    def test_build_with_tuning_info(self) -> None:
        """Test building results with tuning information."""
        builder = self.create_builder()
        builder.set_tuning_info(
            tunings_applied={"memory": "8GB"},
            config_hash="abc123",
            source_file="tuning.yaml",
        )

        result = builder.build()

        assert result.tunings_applied == {"memory": "8GB"}
        assert result.tuning_config_hash == "abc123"
        assert result.tuning_source_file == "tuning.yaml"

    def test_build_with_cost_summary(self) -> None:
        """Test building results with cost summary."""
        builder = self.create_builder()
        builder.set_cost_summary({"total_cost": 1.50, "currency": "USD"})

        result = builder.build()

        assert result.cost_summary == {"total_cost": 1.50, "currency": "USD"}

    def test_build_with_plan_capture_stats(self) -> None:
        """Test building results with query plan capture statistics."""
        builder = self.create_builder()
        builder.add_plan_capture_stats(
            plans_captured=20,
            capture_failures=2,
            capture_errors=[{"query_id": "Q1", "error": "Timeout"}],
        )

        result = builder.build()

        assert result.query_plans_captured == 20
        assert result.plan_capture_failures == 2
        assert len(result.plan_capture_errors) == 1

    def test_add_query_results_batch(self) -> None:
        """Test adding multiple query results at once."""
        builder = self.create_builder()
        results = [
            self.create_query_result("1", 1.0, 100),
            self.create_query_result("2", 2.0, 200),
        ]
        builder.add_query_results(results)

        result = builder.build()

        assert result.total_queries == 2

    def test_query_results_format(self) -> None:
        """Test that query results are formatted correctly."""
        builder = self.create_builder()
        builder.add_query_result(
            QueryResultInput(
                query_id="1",
                execution_time_seconds=1.5,
                rows_returned=100,
                status="SUCCESS",
                iteration=2,
                stream_id=1,
            )
        )

        result = builder.build()
        qr = result.query_results[0]

        assert qr["query_id"] == "Q1"  # Should have Q prefix
        assert qr["execution_time"] == 1.5
        assert qr["execution_time_ms"] == 1500
        assert qr["status"] == "SUCCESS"
        assert qr["rows_returned"] == 100
        assert qr["iteration"] == 2
        assert qr["stream_id"] == 1

    def test_query_results_format_includes_plan_capture_error(self) -> None:
        """A DataFrame plan-capture failure's real cause (qpc-05 / F4.4) must
        reach the persisted query row, not just the companion errors list."""
        builder = self.create_builder()
        builder.add_query_result(
            QueryResultInput(
                query_id="1",
                execution_time_seconds=1.5,
                rows_returned=100,
                status="SUCCESS",
                plan_capture_error="TypeError: unsupported operand",
            )
        )

        result = builder.build()
        qr = result.query_results[0]

        assert qr["plan_capture_error"] == "TypeError: unsupported operand"

    def test_query_results_format_omits_plan_capture_error_when_none(self) -> None:
        builder = self.create_builder()
        builder.add_query_result(self.create_query_result("1", 1.0, 100))

        result = builder.build()
        qr = result.query_results[0]

        assert "plan_capture_error" not in qr

    def test_platform_info_dict_format(self) -> None:
        """Test that platform_info dict is formatted correctly."""
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(name="TPC-H", scale_factor=1.0),
            platform=PlatformInfoInput(
                name="DuckDB",
                platform_version="1.0.0",
                client_library_version="2.0.0",
                execution_mode="sql",
                connection_mode="in-memory",
                config={"threads": 4},
            ),
        )

        result = builder.build()

        assert result.platform_info["platform_name"] == "DuckDB"
        assert result.platform_info["platform_version"] == "1.0.0"
        assert result.platform_info["client_library_version"] == "2.0.0"
        assert result.platform_info["execution_mode"] == "sql"
        assert result.platform_info["connection_mode"] == "in-memory"
        assert result.platform_info["configuration"] == {"threads": 4}

    def test_build_preserves_test_type_through_real_pipeline(self) -> None:
        """test_type must survive the REAL production pipeline: raw platform-adapter
        dict -> normalize_query_result -> ResultBuilder.add_query_result -> build()
        -> BenchmarkResults.query_results. This is the phase discriminator
        build_plans_payload uses to disambiguate a power row and a throughput row
        sharing the same query_id/stream_id in a combined run; a synthetic
        QueryResultInput built directly (bypassing normalize_query_result) would
        hide a regression where the raw dict's "test_type" key gets silently
        dropped at the normalization boundary."""
        power_raw = {
            "query_id": "Q6",
            "execution_time_seconds": 1.0,
            "rows_returned": 10,
            "status": "SUCCESS",
            "stream_id": 0,
            "test_type": "power",
        }
        throughput_raw = {
            "query_id": "Q6",
            "execution_time_seconds": 2.0,
            "rows_returned": 10,
            "status": "SUCCESS",
            "stream_id": 0,
            "test_type": "throughput",
        }

        builder = self.create_builder()
        builder.add_query_result(normalize_query_result(power_raw))
        builder.add_query_result(normalize_query_result(throughput_raw))

        result = builder.build()

        assert len(result.query_results) == 2
        power_row, throughput_row = result.query_results
        assert power_row["test_type"] == "power"
        assert throughput_row["test_type"] == "throughput"


class TestBuildBenchmarkResults:
    """Tests for build_benchmark_results convenience function."""

    def test_basic_usage(self) -> None:
        """Test basic usage of convenience function."""
        query_results = [
            QueryResultInput(
                query_id="1",
                execution_time_seconds=1.0,
                rows_returned=100,
                status="SUCCESS",
            ),
        ]

        result = build_benchmark_results(
            benchmark_name="TPC-H",
            platform_name="DuckDB",
            scale_factor=1.0,
            query_results=query_results,
        )

        assert result.benchmark_name == "TPC-H"
        assert result.platform == "DuckDB"
        assert result.scale_factor == 1.0
        assert result.total_queries == 1

    def test_with_all_options(self) -> None:
        """Test convenience function with all options."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 30)
        query_results = [
            QueryResultInput(
                query_id="1",
                execution_time_seconds=1.0,
                rows_returned=100,
                status="SUCCESS",
            ),
        ]

        result = build_benchmark_results(
            benchmark_name="TPC-H",
            platform_name="DuckDB",
            scale_factor=1.0,
            query_results=query_results,
            execution_mode="sql",
            test_type="power",
            platform_version="1.0.0",
            table_stats={"lineitem": 1000},
            loading_time_ms=500.0,
            start_time=start,
            end_time=end,
        )

        assert result.platform_info["platform_version"] == "1.0.0"
        assert result.total_rows_loaded == 1000
        assert result.data_loading_time == 0.5
        assert result.timestamp == start
        assert result.duration_seconds == 30.0

    def test_dataframe_mode(self) -> None:
        """Test convenience function with DataFrame mode."""
        query_results = [
            QueryResultInput(
                query_id="1",
                execution_time_seconds=1.0,
                rows_returned=100,
                status="SUCCESS",
            ),
        ]

        result = build_benchmark_results(
            benchmark_name="TPC-H",
            platform_name="Polars",
            scale_factor=1.0,
            query_results=query_results,
            execution_mode="dataframe",
        )

        assert result.platform == "Polars"
        assert result.execution_metadata["execution_mode"] == "dataframe"


class TestRunConfigInputTableMode:
    """Verify table_mode is correctly serialized in RunConfigInput."""

    def test_external_mode_included_in_dict(self):
        rc = RunConfigInput(table_mode="external", phases=["power"])
        d = rc.to_dict()
        assert d["table_mode"] == "external"

    def test_native_mode_omitted_from_dict(self):
        rc = RunConfigInput(table_mode="native", phases=["power"])
        d = rc.to_dict()
        assert "table_mode" not in d

    def test_none_mode_omitted_from_dict(self):
        rc = RunConfigInput(table_mode=None, phases=["power"])
        d = rc.to_dict()
        assert "table_mode" not in d

    def test_round_trip_through_builder(self):
        """table_mode should survive set_run_config -> build -> config."""
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(name="tpch", scale_factor=0.01),
            platform=PlatformInfoInput(name="DuckDB", execution_mode="sql"),
        )
        builder.set_run_config(RunConfigInput(table_mode="external", phases=["power"]))
        builder.mark_started()
        builder.mark_completed()
        result = builder.build()
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_mode") == "external"


class TestRunConfigInputExternalFormat:
    """Verify external_format is correctly serialized in RunConfigInput."""

    def test_external_format_included_in_dict(self):
        rc = RunConfigInput(table_mode="external", external_format="parquet", phases=["power"])
        d = rc.to_dict()
        assert d["external_format"] == "parquet"

    def test_external_format_tbl_included(self):
        rc = RunConfigInput(table_mode="external", external_format="tbl", phases=["power"])
        d = rc.to_dict()
        assert d["external_format"] == "tbl"

    def test_none_format_omitted_from_dict(self):
        rc = RunConfigInput(table_mode="external", external_format=None, phases=["power"])
        d = rc.to_dict()
        assert "external_format" not in d

    def test_empty_format_omitted_from_dict(self):
        rc = RunConfigInput(table_mode="external", external_format="", phases=["power"])
        d = rc.to_dict()
        assert "external_format" not in d

    def test_round_trip_through_builder(self):
        """external_format should survive set_run_config -> build -> execution_metadata."""
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(name="tpch", scale_factor=0.01),
            platform=PlatformInfoInput(name="DuckDB", execution_mode="sql"),
        )
        builder.set_run_config(RunConfigInput(table_mode="external", external_format="parquet", phases=["power"]))
        builder.mark_started()
        builder.mark_completed()
        result = builder.build()
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_mode") == "external"
        assert config.get("external_format") == "parquet"

    def test_round_trip_tbl_format(self):
        """TBL format should survive the full round-trip through builder."""
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(name="tpch", scale_factor=1.0),
            platform=PlatformInfoInput(name="DuckDB", execution_mode="sql"),
        )
        builder.set_run_config(RunConfigInput(table_mode="external", external_format="tbl", phases=["power"]))
        builder.mark_started()
        builder.mark_completed()
        result = builder.build()
        config = result.execution_metadata.get("run_config", {})
        assert config.get("external_format") == "tbl"


class TestRunConfigInputTableFormat:
    """Verify table format settings are serialized in RunConfigInput."""

    def test_table_format_fields_included_in_dict(self):
        rc = RunConfigInput(
            table_format="parquet",
            table_format_compression="zstd",
            table_format_partition_cols=["region"],
            phases=["power"],
        )
        d = rc.to_dict()
        assert d["table_format"] == "parquet"
        assert d["table_format_compression"] == "zstd"
        assert d["table_format_partition_cols"] == ["region"]

    def test_table_format_fields_omitted_without_table_format(self):
        rc = RunConfigInput(
            table_format=None,
            table_format_compression="zstd",
            table_format_partition_cols=["region"],
            phases=["power"],
        )
        d = rc.to_dict()
        assert "table_format" not in d
        assert "table_format_compression" not in d
        assert "table_format_partition_cols" not in d

    def test_table_format_round_trip_through_builder(self):
        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(name="tpch", scale_factor=0.01),
            platform=PlatformInfoInput(name="DuckDB", execution_mode="sql"),
        )
        builder.set_run_config(
            RunConfigInput(
                table_format="iceberg",
                table_format_compression="zstd",
                table_format_partition_cols=["region"],
                phases=["power"],
            )
        )
        builder.mark_started()
        builder.mark_completed()
        result = builder.build()
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_format") == "iceberg"
        assert config.get("table_format_compression") == "zstd"
        assert config.get("table_format_partition_cols") == ["region"]


class TestResultFactoryExternalFormat:
    """Verify external_format propagates through build_enhanced_benchmark_result."""

    def _make_benchmark(self, name="TPC-H Benchmark", scale=0.01):
        from unittest.mock import Mock

        bm = Mock()
        bm.benchmark_name = name
        bm.scale_factor = scale
        return bm

    def test_external_format_reaches_result_config(self):
        """external_format in run_config should survive the result factory pipeline."""
        from benchbox.core.results.result_factory import build_enhanced_benchmark_result

        result = build_enhanced_benchmark_result(
            benchmark=self._make_benchmark(),
            platform="duckdb",
            query_results=[],
            execution_metadata={
                "run_config": {
                    "table_mode": "external",
                    "external_format": "parquet",
                    "phases": ["power"],
                },
            },
        )
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_mode") == "external"
        assert config.get("external_format") == "parquet"

    def test_tbl_format_reaches_result_config(self):
        """TBL format should propagate through result factory."""
        from benchbox.core.results.result_factory import build_enhanced_benchmark_result

        result = build_enhanced_benchmark_result(
            benchmark=self._make_benchmark(),
            platform="duckdb",
            query_results=[],
            execution_metadata={
                "run_config": {
                    "table_mode": "external",
                    "external_format": "tbl",
                },
            },
        )
        config = result.execution_metadata.get("run_config", {})
        assert config.get("external_format") == "tbl"

    def test_missing_external_format_omitted(self):
        """When external_format is absent, it should not appear in config."""
        from benchbox.core.results.result_factory import build_enhanced_benchmark_result

        result = build_enhanced_benchmark_result(
            benchmark=self._make_benchmark(),
            platform="duckdb",
            query_results=[],
            execution_metadata={
                "run_config": {
                    "table_mode": "external",
                },
            },
        )
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_mode") == "external"
        assert "external_format" not in config

    def test_table_format_reaches_result_config(self):
        """table_format in run_config should survive the result factory pipeline."""
        from benchbox.core.results.result_factory import build_enhanced_benchmark_result

        result = build_enhanced_benchmark_result(
            benchmark=self._make_benchmark(),
            platform="duckdb",
            query_results=[],
            execution_metadata={
                "run_config": {
                    "table_format": "parquet",
                    "table_format_compression": "zstd",
                    "table_format_partition_cols": ["region"],
                },
            },
        )
        config = result.execution_metadata.get("run_config", {})
        assert config.get("table_format") == "parquet"
        assert config.get("table_format_compression") == "zstd"
        assert config.get("table_format_partition_cols") == ["region"]
