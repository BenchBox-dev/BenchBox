"""Tests for post-run summary chart generation."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import patch

import pytest

from benchbox.core.visualization.post_run_summary import (
    PostRunSummary,
    _extract_environment,
    _extract_platform_config,
    _should_use_horizontal,
    generate_post_run_summary,
)
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_result(query_results: list | None = None, **kwargs):
    """Post-run summary test defaults delegating to shared factory."""
    qr = query_results or []
    defaults = {
        "benchmark_name": "TPC-H",
        "platform": "duckdb",
        "execution_id": "test123",
        "timestamp": datetime(2026, 1, 1),
        "duration_seconds": 10.0,
        "total_queries": len(qr),
        "successful_queries": len([q for q in qr if q.get("status") == "SUCCESS"]),
        "query_results": qr,
    }
    defaults.update(kwargs)
    return make_benchmark_results(**defaults)


def _make_query(query_id: str, time_ms: float, status: str = "SUCCESS") -> dict:
    return {
        "query_id": query_id,
        "execution_time_ms": time_ms,
        "execution_time": time_ms / 1000.0,
        "status": status,
    }


class TestGeneratePostRunSummary:
    def test_returns_post_run_summary_type(self):
        result = _make_result([_make_query("Q1", 100.0)])
        summary = generate_post_run_summary(result)
        assert isinstance(summary, PostRunSummary)

    def test_charts_contain_summary_box_and_histogram(self):
        queries = [_make_query(f"Q{i}", float(i * 10)) for i in range(1, 6)]
        result = _make_result(queries)
        summary = generate_post_run_summary(result)

        assert summary.summary_box != ""
        assert summary.query_histogram != ""
        assert len(summary.charts) == 2
        assert summary.charts[0] == summary.summary_box
        assert summary.charts[1] == summary.query_histogram

    def test_summary_box_contains_benchmark_info(self):
        result = _make_result(
            [_make_query("Q1", 100.0), _make_query("Q2", 200.0)],
            benchmark_name="TPC-H",
            platform="duckdb",
            scale_factor=0.01,
        )
        summary = generate_post_run_summary(result)
        assert "TPC-H" in summary.summary_box
        assert "duckdb" in summary.summary_box

    def test_empty_query_results_returns_empty(self):
        result = _make_result([])
        summary = generate_post_run_summary(result)
        assert summary.summary_box == ""
        assert summary.query_histogram == ""
        assert summary.charts == []

    def test_none_query_results_returns_empty(self):
        result = _make_result(None)
        summary = generate_post_run_summary(result)
        assert summary.charts == []

    def test_all_failed_queries_returns_empty(self):
        queries = [_make_query("Q1", 100.0, status="FAILED"), _make_query("Q2", 200.0, status="FAILED")]
        result = _make_result(queries)
        summary = generate_post_run_summary(result)
        assert summary.charts == []

    def test_mixed_success_and_failure_only_charts_successful(self):
        queries = [
            _make_query("Q1", 100.0, status="SUCCESS"),
            _make_query("Q2", 200.0, status="FAILED"),
            _make_query("Q3", 300.0, status="SUCCESS"),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result)
        # Should have charts (2 successful queries)
        assert len(summary.charts) == 2
        # Histogram should contain Q1 and Q3 but not Q2
        assert "Q1" in summary.query_histogram
        assert "Q3" in summary.query_histogram

    def test_color_disabled(self):
        result = _make_result([_make_query("Q1", 100.0)])
        summary = generate_post_run_summary(result, color=False)
        # Should not contain ANSI escape codes
        assert "\033[" not in summary.summary_box

    def test_unicode_disabled(self):
        result = _make_result([_make_query("Q1", 100.0), _make_query("Q2", 200.0)])
        summary = generate_post_run_summary(result, unicode=False)
        # Should not contain Unicode box-drawing characters
        assert "\u250c" not in summary.summary_box  # ┌
        assert "\u2500" not in summary.summary_box  # ─

    def test_single_query(self):
        result = _make_result([_make_query("Q1", 42.0)])
        summary = generate_post_run_summary(result)
        assert len(summary.charts) == 2
        assert "Q1" in summary.query_histogram

    def test_many_queries(self):
        queries = [_make_query(f"Q{i}", float(i * 5)) for i in range(1, 50)]
        result = _make_result(queries)
        summary = generate_post_run_summary(result)
        assert len(summary.charts) == 2
        assert summary.summary_box != ""
        assert summary.query_histogram != ""

    def test_multi_run_aggregates_to_one_bar_per_query(self):
        """4 power runs x 3 queries = 12 results should produce 3 histogram bars."""
        queries = [
            # 4 runs of Q1 (mean = 100)
            _make_query("Q1", 90.0),
            _make_query("Q1", 100.0),
            _make_query("Q1", 105.0),
            _make_query("Q1", 105.0),
            # 4 runs of Q2 (mean = 50)
            _make_query("Q2", 40.0),
            _make_query("Q2", 50.0),
            _make_query("Q2", 55.0),
            _make_query("Q2", 55.0),
            # 4 runs of Q3 (mean = 200)
            _make_query("Q3", 180.0),
            _make_query("Q3", 200.0),
            _make_query("Q3", 210.0),
            _make_query("Q3", 210.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        # Should report 3 unique queries, not 12 executions
        assert "3" in summary.summary_box

        # Each query ID should appear exactly once in histogram labels
        # (strip ANSI, count occurrences in the rendered histogram)
        histogram_lines = summary.query_histogram.split("\n")
        label_lines = [line for line in histogram_lines if "Q1" in line or "Q2" in line or "Q3" in line]
        # Flatten all label text
        label_text = " ".join(label_lines)
        assert label_text.count("Q1") == 1
        assert label_text.count("Q2") == 1
        assert label_text.count("Q3") == 1

    def test_multi_run_best_worst_uses_aggregated_mean(self):
        """Best/worst should be determined by per-query mean, not individual executions."""
        queries = [
            # Q1: mean = 100ms (one fast outlier at 5ms shouldn't make it "best")
            _make_query("Q1", 5.0),
            _make_query("Q1", 195.0),
            # Q2: mean = 50ms (consistently fast - should be best)
            _make_query("Q2", 45.0),
            _make_query("Q2", 55.0),
            # Q3: mean = 300ms (should be worst)
            _make_query("Q3", 280.0),
            _make_query("Q3", 320.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        # Q2 should be best (lowest mean), not Q1 (which has the lowest single execution)
        best_idx = summary.summary_box.find("Best:")
        worst_idx = summary.summary_box.find("Worst:")
        best_section = summary.summary_box[best_idx:worst_idx]
        worst_section = summary.summary_box[worst_idx:]

        assert "Q2" in best_section
        assert "Q3" in worst_section

    def test_multi_run_query_count_is_unique_queries(self):
        """num_queries should reflect unique query IDs, not total executions."""
        queries = [
            _make_query("Q1", 100.0),
            _make_query("Q1", 110.0),
            _make_query("Q2", 200.0),
            _make_query("Q2", 210.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        # Should say "2" queries, not "4"
        assert "Queries" in summary.summary_box
        # Extract the queries line
        for line in summary.summary_box.split("\n"):
            if "Queries" in line:
                assert "2" in line
                assert "4" not in line
                break

    def test_multi_run_aggregates_mixed_query_id_formats(self):
        """Equivalent query-id formats should aggregate into one per-query bar."""
        queries = [
            _make_query("Q1", 100.0),
            _make_query("1", 110.0),
            _make_query("query_1", 90.0),
            _make_query("Q2", 200.0),
            _make_query("2", 220.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        for line in summary.summary_box.split("\n"):
            if "Queries" in line:
                assert "2" in line
                break
        else:
            pytest.fail("Queries line missing from summary box")

        assert "Q1" in summary.query_histogram
        assert "Q2" in summary.query_histogram

    def test_multi_run_preserves_variant_query_ids(self):
        """Variant IDs (e.g., 14a/14b) must remain separate for aggregation."""
        queries = [
            _make_query("14a", 100.0),
            _make_query("Q14a", 110.0),
            _make_query("14b", 300.0),
            _make_query("Q14b", 290.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        for line in summary.summary_box.split("\n"):
            if "Queries" in line:
                assert "2" in line
                break
        else:
            pytest.fail("Queries line missing from summary box")

        assert "Q14a" in summary.query_histogram
        assert "Q14b" in summary.query_histogram

    def test_chart_rendering_failure_does_not_propagate(self):
        """Verify that the function itself doesn't swallow errors -
        callers are responsible for catching exceptions."""
        result = _make_result([_make_query("Q1", 100.0)])
        with patch(
            "benchbox.core.visualization.post_run_summary.SummaryBox.render",
            side_effect=RuntimeError("render boom"),
        ):
            with pytest.raises(RuntimeError, match="render boom"):
                generate_post_run_summary(result)


_SAMPLE_SYSTEM_PROFILE = {
    "os_name": "Darwin",
    "os_version": "25.2.0",
    "architecture": "arm64",
    "cpu_model": "Apple M1 Pro",
    "cpu_cores_physical": 10,
    "cpu_cores_logical": 10,
    "memory_total_gb": 16.0,
    "memory_available_gb": 8.0,
    "python_version": "3.12.11",
    "disk_space_gb": 500.0,
    "timestamp": "2026-01-01T00:00:00",
}


class TestEnvironmentInfoRendering:
    """Tests for system environment info in the summary box."""

    def test_env_info_renders_when_system_profile_present(self):
        """Environment column appears when system_profile is provided."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile=_SAMPLE_SYSTEM_PROFILE)
        summary = generate_post_run_summary(result, color=False, max_width=80)

        assert "Darwin 25.2.0" in summary.summary_box
        assert "3.12.11" in summary.summary_box
        assert "10 (arm64)" in summary.summary_box
        assert "16 GB" in summary.summary_box

    def test_env_info_renders_with_system_info_to_dict_keys(self):
        """Environment column works with SystemInfo.to_dict() key names."""
        profile = {
            "os_type": "Linux",
            "os_version": "6.1.0",
            "architecture": "x86_64",
            "cpu_cores": 16,
            "total_memory_gb": 64.0,
            "python_version": "3.11.9",
        }
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile=profile)
        summary = generate_post_run_summary(result, color=False, max_width=80)

        assert "Linux 6.1.0" in summary.summary_box
        assert "3.11.9" in summary.summary_box
        assert "16 (x86_64)" in summary.summary_box
        assert "64 GB" in summary.summary_box

    def test_env_info_absent_when_no_system_profile(self):
        """No environment column when system_profile is None."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile=None)
        summary = generate_post_run_summary(result, color=False, max_width=80)

        # Metrics still render, but no env info
        assert "Geo Mean" in summary.summary_box
        assert "Darwin" not in summary.summary_box

    def test_env_info_absent_when_empty_system_profile(self):
        """No environment column when system_profile is empty dict."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile={})
        summary = generate_post_run_summary(result, color=False, max_width=80)

        assert "Geo Mean" in summary.summary_box
        assert "OS:" not in summary.summary_box

    def test_narrow_terminal_falls_back_to_single_column(self):
        """Narrow terminal omits environment column even when data is present."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile=_SAMPLE_SYSTEM_PROFILE)
        summary = generate_post_run_summary(result, color=False, max_width=50)

        # Metrics still render in single-column mode
        assert "Geo Mean" in summary.summary_box
        # No column divider character in the box
        box_lines = summary.summary_box.split("\n")
        # The ┬ character would only appear in two-column mode separators
        assert not any("\u252c" in line for line in box_lines)  # ┬

    @pytest.mark.skipif(sys.platform == "win32", reason="Unicode box-drawing chars may not render on Windows")
    def test_two_column_has_column_divider(self):
        """Two-column mode uses box-drawing divider characters."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(queries, system_profile=_SAMPLE_SYSTEM_PROFILE)
        summary = generate_post_run_summary(result, color=False, max_width=80)

        box_lines = summary.summary_box.split("\n")
        # Should have ┬ in a separator and ┴ in the closing separator
        assert any("\u252c" in line for line in box_lines)  # ┬
        assert any("\u2534" in line for line in box_lines)  # ┴


class TestExtractEnvironment:
    """Tests for the _extract_environment helper."""

    def test_full_profile(self):
        env = _extract_environment(_SAMPLE_SYSTEM_PROFILE)
        assert env == {
            "OS": "Darwin 25.2.0",
            "Python": "3.12.11",
            "CPUs": "10 (arm64)",
            "Memory": "16 GB",
        }

    def test_none_profile(self):
        assert _extract_environment(None) is None

    def test_empty_profile(self):
        assert _extract_environment({}) is None

    def test_partial_profile_os_only(self):
        env = _extract_environment({"os_name": "Linux", "os_version": "6.1.0"})
        assert env == {"OS": "Linux 6.1.0"}

    def test_partial_profile_memory_only(self):
        env = _extract_environment({"memory_total_gb": 32.0})
        assert env == {"Memory": "32 GB"}

    def test_cpus_without_architecture(self):
        env = _extract_environment({"cpu_cores_logical": 8})
        assert env is not None
        assert env["CPUs"] == "8"

    def test_system_info_to_dict_keys(self):
        """SystemInfo.to_dict() uses os_type/cpu_cores/total_memory_gb - all should work."""
        profile = {
            "os_type": "Darwin",
            "os_version": "25.2.0",
            "architecture": "arm64",
            "cpu_cores": 10,
            "total_memory_gb": 16.0,
            "python_version": "3.12.11",
        }
        env = _extract_environment(profile)
        assert env == {
            "OS": "Darwin 25.2.0",
            "Python": "3.12.11",
            "CPUs": "10 (arm64)",
            "Memory": "16 GB",
        }

    def test_os_type_fallback(self):
        """os_type key (SystemInfo) should be used when os_name is absent."""
        env = _extract_environment({"os_type": "Linux", "os_version": "6.1.0"})
        assert env == {"OS": "Linux 6.1.0"}

    def test_cpu_cores_fallback(self):
        """cpu_cores key (SystemInfo) should be used when cpu_cores_logical is absent."""
        env = _extract_environment({"cpu_cores": 8, "architecture": "x86_64"})
        assert env is not None
        assert env["CPUs"] == "8 (x86_64)"

    def test_total_memory_gb_fallback(self):
        """total_memory_gb key (SystemInfo) should be used when memory_total_gb is absent."""
        env = _extract_environment({"total_memory_gb": 64.0})
        assert env == {"Memory": "64 GB"}

    def test_none_system_profile_returns_none(self):
        """None system_profile returns None."""
        assert _extract_environment(None) is None


class TestExtractPlatformConfig:
    """Tests for _extract_platform_config helper."""

    def test_platform_info_adds_driver_row(self):
        """platform_info with platform_version adds a Driver row."""
        cfg = _extract_platform_config({"platform_name": "DuckDB", "platform_version": "1.4.3"}, {})
        assert cfg is not None
        assert cfg["Driver"] == "DuckDB 1.4.3"

    def test_platform_info_version_fallback_keys(self):
        """Falls back to 'version' then 'driver_version_actual' when platform_version absent."""
        cfg = _extract_platform_config({"platform_name": "DuckDB", "version": "1.2.0"}, {})
        assert cfg is not None
        assert cfg["Driver"] == "DuckDB 1.2.0"

        cfg2 = _extract_platform_config({"driver_version_actual": "1.1.3"}, {})
        assert cfg2 is not None
        assert cfg2["Driver"] == "1.1.3"

    def test_platform_info_no_version_skips_driver_row(self):
        """platform_info without any version key produces no Driver row."""
        cfg = _extract_platform_config({"platform_name": "DuckDB"}, {})
        assert cfg is None

    def test_table_mode_external(self):
        """table_mode 'external' without format adds plain Tables row."""
        cfg = _extract_platform_config(None, {"table_mode": "external"})
        assert cfg is not None
        assert cfg["Tables"] == "External"

    def test_table_mode_external_with_format(self):
        """table_mode 'external' with external_format includes format in parentheses."""
        cfg = _extract_platform_config(None, {"table_mode": "external", "external_format": "parquet"})
        assert cfg is not None
        assert cfg["Tables"] == "External (Parquet)"

    def test_table_mode_external_tbl_format(self):
        """TBL format is capitalized correctly."""
        cfg = _extract_platform_config(None, {"table_mode": "external", "external_format": "tbl"})
        assert cfg is not None
        assert cfg["Tables"] == "External (Tbl)"

    def test_table_mode_native_excluded(self):
        """table_mode 'native' (the default) is omitted."""
        cfg = _extract_platform_config(None, {"table_mode": "native"})
        assert cfg is None

    def test_tuning_mode(self):
        """tuning_mode adds Tuning row."""
        cfg = _extract_platform_config(None, {"tuning_mode": "notuning"})
        assert cfg is not None
        assert cfg["Tuning"] == "Notuning"

    def test_table_format_with_compression(self):
        """table_format renders Table Format row with compression."""
        cfg = _extract_platform_config(None, {"table_format": "parquet", "table_format_compression": "zstd"})
        assert cfg is not None
        assert cfg["Table Format"] == "Parquet (zstd)"

    def test_table_format_without_compression(self):
        """table_format without table_format_compression renders plain format."""
        cfg = _extract_platform_config(None, {"table_format": "iceberg"})
        assert cfg is not None
        assert cfg["Table Format"] == "Iceberg"

    def test_combined_driver_and_table_mode(self):
        """Driver + table_mode + tuning_mode all appear together."""
        cfg = _extract_platform_config(
            {"platform_name": "DuckDB", "platform_version": "1.4.3"},
            {"table_mode": "external", "external_format": "parquet", "tuning_mode": "tuned"},
        )
        assert cfg is not None
        assert cfg["Driver"] == "DuckDB 1.4.3"
        assert cfg["Tables"] == "External (Parquet)"
        assert cfg["Tuning"] == "Tuned"

    def test_both_none_returns_none(self):
        """Both platform_info and run_cfg empty returns None."""
        assert _extract_platform_config(None, {}) is None


class TestExternalFormatSummaryDisplay:
    """End-to-end tests: external_format in execution_metadata renders in summary box.

    These tests verify the full pipeline: execution_metadata -> _extract_platform_config
    -> SummaryStats -> rendered summary box.  system_profile is required to activate
    the multi-column layout where platform_config (Tables row) appears.
    """

    def test_parquet_format_appears_in_summary_box(self):
        """Summary box should display 'External (Parquet)' when format is parquet."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(
            queries,
            platform="duckdb",
            execution_metadata={
                "run_config": {"table_mode": "external", "external_format": "parquet"},
            },
            platform_info={"platform_name": "DuckDB", "platform_version": "1.4.3"},
            system_profile=_SAMPLE_SYSTEM_PROFILE,
        )
        summary = generate_post_run_summary(result, color=False, max_width=120)
        assert "External (Parquet)" in summary.summary_box

    def test_tbl_format_appears_in_summary_box(self):
        """Summary box should display 'External (Tbl)' when format is tbl."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(
            queries,
            platform="duckdb",
            execution_metadata={
                "run_config": {"table_mode": "external", "external_format": "tbl"},
            },
            platform_info={"platform_name": "DuckDB", "platform_version": "1.4.3"},
            system_profile=_SAMPLE_SYSTEM_PROFILE,
        )
        summary = generate_post_run_summary(result, color=False, max_width=120)
        assert "External (Tbl)" in summary.summary_box

    def test_external_without_format_shows_plain_external(self):
        """When external_format is absent, summary shows just 'External'."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(
            queries,
            platform="duckdb",
            execution_metadata={
                "run_config": {"table_mode": "external"},
            },
            platform_info={"platform_name": "DuckDB", "platform_version": "1.4.3"},
            system_profile=_SAMPLE_SYSTEM_PROFILE,
        )
        summary = generate_post_run_summary(result, color=False, max_width=120)
        assert "External" in summary.summary_box
        assert "External (" not in summary.summary_box

    def test_native_mode_omits_tables_row_from_summary(self):
        """Native table mode should not produce a Tables row in the summary."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(
            queries,
            platform="duckdb",
            execution_metadata={
                "run_config": {"table_mode": "native"},
            },
            system_profile=_SAMPLE_SYSTEM_PROFILE,
        )
        summary = generate_post_run_summary(result, color=False, max_width=120)
        assert "Tables" not in summary.summary_box

    def test_table_format_appears_in_summary_box(self):
        """Summary box should display table format from run_config."""
        queries = [_make_query("Q1", 100.0), _make_query("Q2", 200.0)]
        result = _make_result(
            queries,
            platform="duckdb",
            execution_metadata={
                "run_config": {"table_format": "parquet", "table_format_compression": "zstd"},
            },
            platform_info={"platform_name": "DuckDB", "platform_version": "1.4.3"},
            system_profile=_SAMPLE_SYSTEM_PROFILE,
        )
        summary = generate_post_run_summary(result, color=False, max_width=120)
        assert "Parquet (zstd)" in summary.summary_box


class TestShouldUseHorizontal:
    """Tests for the _should_use_horizontal heuristic."""

    def test_short_tpch_ids_returns_false(self):
        """TPC-H style short IDs (Q1-Q22) should use vertical histogram."""
        ids = [f"Q{i}" for i in range(1, 23)]
        assert _should_use_horizontal(ids) is False

    def test_short_tpcds_ids_returns_false(self):
        """TPC-DS style IDs (Q1-Q99) should use vertical histogram."""
        ids = [f"Q{i}" for i in range(1, 100)]
        assert _should_use_horizontal(ids) is False

    def test_long_primitives_names_returns_true(self):
        """Primitives-style long descriptive names should use horizontal bars."""
        ids = [
            "aggregation_groupby_large",
            "shuffle_inner_join_one_to_many",
            "read_parquet_single_file",
            "filter_numeric_range",
            "sort_single_column_int",
        ]
        assert _should_use_horizontal(ids) is True

    def test_empty_list_returns_false(self):
        assert _should_use_horizontal([]) is False

    def test_single_short_id_returns_false(self):
        assert _should_use_horizontal(["Q1"]) is False

    def test_single_long_id_returns_true(self):
        assert _should_use_horizontal(["aggregation_groupby_large"]) is True

    def test_threshold_boundary_at_six(self):
        """IDs of exactly 6 chars should NOT trigger horizontal (threshold is >6)."""
        ids = ["ABCDEF", "GHIJKL", "MNOPQR"]
        assert _should_use_horizontal(ids) is False

    def test_threshold_boundary_above_six(self):
        """IDs of 7 chars should trigger horizontal."""
        ids = ["ABCDEFG", "HIJKLMN", "OPQRSTU"]
        assert _should_use_horizontal(ids) is True

    def test_mixed_lengths_uses_median(self):
        """Median determines the outcome, not max or min."""
        # 3 short + 2 long → median is short → vertical
        ids = ["Q1", "Q2", "Q3", "aggregation_groupby", "shuffle_join"]
        assert _should_use_horizontal(ids) is False

    def test_majority_long_uses_horizontal(self):
        """When most IDs are long, median is long → horizontal."""
        ids = ["Q1", "aggregation_groupby", "shuffle_join", "filter_range", "sort_column"]
        assert _should_use_horizontal(ids) is True


class TestHorizontalBarChartIntegration:
    """Tests that generate_post_run_summary() selects the correct chart type."""

    def test_long_query_names_produce_horizontal_bars(self):
        """Primitives-style long names should render using BarChart (horizontal)."""
        queries = [
            _make_query("aggregation_groupby_large", 100.0),
            _make_query("shuffle_inner_join", 200.0),
            _make_query("read_parquet_single", 150.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        assert len(summary.charts) == 2
        assert summary.query_histogram != ""
        # Horizontal bar chart labels appear on the left of each bar line,
        # so the full (or truncated-to-30-char) names should be visible
        assert "aggregation_groupby_large" in summary.query_histogram
        assert "shuffle_inner_join" in summary.query_histogram
        assert "read_parquet_single" in summary.query_histogram

    def test_short_query_names_produce_vertical_histogram(self):
        """TPC-H style short IDs should render using Histogram (vertical)."""
        queries = [_make_query(f"Q{i}", float(i * 10)) for i in range(1, 6)]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        assert len(summary.charts) == 2
        assert summary.query_histogram != ""
        # Vertical histogram has query IDs along the x-axis bottom row
        # All short IDs should appear
        assert "Q1" in summary.query_histogram
        assert "Q5" in summary.query_histogram

    def test_horizontal_chart_contains_query_latency_title(self):
        """Horizontal chart should still have the 'Query Latency' title."""
        queries = [
            _make_query("aggregation_groupby_large", 100.0),
            _make_query("shuffle_inner_join", 200.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        assert "Query Latency" in summary.query_histogram

    def test_horizontal_chart_summary_box_still_renders(self):
        """Summary box should render normally regardless of chart orientation."""
        queries = [
            _make_query("aggregation_groupby_large", 100.0),
            _make_query("shuffle_inner_join", 200.0),
        ]
        result = _make_result(queries, benchmark_name="Primitives", platform="duckdb")
        summary = generate_post_run_summary(result, color=False)

        assert "Primitives" in summary.summary_box
        assert "duckdb" in summary.summary_box
        assert "Geo Mean" in summary.summary_box

    def test_q_prefix_not_added_to_non_numeric_names(self):
        """Non-numeric query names like 'Qfilter_decimal' should display without Q prefix."""
        queries = [
            _make_query("Qfilter_decimal_selective", 1.0),
            _make_query("Qaggregation_groupby_large", 100.0),
            _make_query("Qexchange_merge", 50.0),
        ]
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        # Names should appear without the Q prefix
        assert "filter_decimal_selective" in summary.query_histogram
        assert "aggregation_groupby_large" in summary.query_histogram
        assert "exchange_merge" in summary.query_histogram
        # Should NOT have the Qprefix versions
        assert "Qfilter" not in summary.query_histogram
        assert "Qaggregation" not in summary.query_histogram

    def test_outlier_truncation_shows_truncation_marker(self):
        """Extreme outliers should be truncated with a marker so other bars are visible."""
        # Create data with extreme outlier: 1 query at 10000ms, rest at 1-10ms
        queries = [_make_query(f"fast_query_{i}", float(i)) for i in range(1, 20)]
        queries.append(_make_query("extreme_outlier", 10000.0))
        result = _make_result(queries)
        summary = generate_post_run_summary(result, color=False)

        # The truncation marker (▸) should appear for the outlier bar
        assert "\u25b8" in summary.query_histogram
