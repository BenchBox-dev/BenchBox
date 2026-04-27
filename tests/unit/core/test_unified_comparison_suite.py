"""Fast-lane coverage tests for UnifiedBenchmarkSuite.

Covers: __init__, get_available_platforms, run_comparison routing,
_run_sql_comparison, _run_dataframe_comparison, _build_platform_result,
get_summary, export_results, _generate_markdown_report,
_generate_text_report, run_unified_comparison.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.comparison.suite import UnifiedBenchmarkSuite, run_unified_comparison
from benchbox.core.comparison.types import (
    PlatformType,
    UnifiedBenchmarkConfig,
    UnifiedPlatformResult,
    UnifiedQueryResult,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _qr(query_id: str, platform: str, mean_ms: float, status: str = "SUCCESS") -> UnifiedQueryResult:
    return UnifiedQueryResult(
        query_id=query_id,
        platform=platform,
        platform_type=PlatformType.SQL,
        mean_time_ms=mean_ms,
        status=status,
    )


def _pr(platform: str, geomean: float, total: float = 0.0, success_rate: float = 100.0) -> UnifiedPlatformResult:
    return UnifiedPlatformResult(
        platform=platform,
        platform_type=PlatformType.SQL,
        geometric_mean_ms=geomean,
        total_time_ms=total,
        success_rate=success_rate,
    )


def _pr_with_queries(platform: str, query_ids_ms: dict) -> UnifiedPlatformResult:
    qrs = [_qr(qid, platform, ms) for qid, ms in query_ids_ms.items()]
    suite = UnifiedBenchmarkSuite()
    return suite._build_platform_result(platform, PlatformType.SQL, qrs)


# ---------------------------------------------------------------------------
# __init__ and config defaults
# ---------------------------------------------------------------------------


class TestUnifiedBenchmarkSuiteInit:
    def test_default_config_created(self):
        suite = UnifiedBenchmarkSuite()
        assert suite.config is not None
        assert suite.config.platform_type == PlatformType.AUTO
        assert suite.config.benchmark == "tpch"

    def test_custom_config_stored(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.SQL, scale_factor=1.0)
        suite = UnifiedBenchmarkSuite(config=config)
        assert suite.config is config
        assert suite.config.scale_factor == 1.0


# ---------------------------------------------------------------------------
# get_available_platforms
# ---------------------------------------------------------------------------


class TestGetAvailablePlatforms:
    def test_returns_sql_platforms(self):
        suite = UnifiedBenchmarkSuite()
        with (
            patch("benchbox.core.comparison.suite.UnifiedBenchmarkSuite.get_available_platforms") as mock_method,
        ):
            # Direct call, mock list_available_platforms inside
            mock_method.return_value = ["duckdb", "sqlite"]
            result = suite.get_available_platforms(PlatformType.SQL)
            # Use the actual method but mock its imports
        with (
            patch("benchbox.platforms.list_available_platforms", return_value=["duckdb", "sqlite"]),
            patch("benchbox.platforms.list_available_dataframe_platforms", return_value={}),
        ):
            result = suite.get_available_platforms(PlatformType.SQL)
            assert "duckdb" in result

    def test_returns_dataframe_platforms(self):
        suite = UnifiedBenchmarkSuite()
        with (
            patch("benchbox.platforms.list_available_platforms", return_value=[]),
            patch(
                "benchbox.platforms.list_available_dataframe_platforms",
                return_value={"polars-df": True, "pandas-df": False},
            ),
        ):
            result = suite.get_available_platforms(PlatformType.DATAFRAME)
            assert "polars-df" in result
            assert "pandas-df" not in result

    def test_returns_all_platforms_when_none_type(self):
        suite = UnifiedBenchmarkSuite()
        with (
            patch("benchbox.platforms.list_available_platforms", return_value=["duckdb"]),
            patch(
                "benchbox.platforms.list_available_dataframe_platforms",
                return_value={"polars-df": True},
            ),
        ):
            result = suite.get_available_platforms(None)
            assert "duckdb" in result
            assert "polars-df" in result


# ---------------------------------------------------------------------------
# run_comparison routing
# ---------------------------------------------------------------------------


class TestRunComparison:
    def test_raises_on_empty_platforms(self):
        suite = UnifiedBenchmarkSuite()
        with pytest.raises(ValueError, match="At least one"):
            suite.run_comparison([])

    def test_routes_to_sql_comparison(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.SQL)
        suite = UnifiedBenchmarkSuite(config=config)
        with patch.object(suite, "_run_sql_comparison", return_value=[]) as mock_sql:
            suite.run_comparison(["duckdb"])
            mock_sql.assert_called_once_with(["duckdb"], None)

    def test_routes_to_dataframe_comparison(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.DATAFRAME)
        suite = UnifiedBenchmarkSuite(config=config)
        with patch.object(suite, "_run_dataframe_comparison", return_value=[]) as mock_df:
            suite.run_comparison(["polars-df"])
            mock_df.assert_called_once_with(["polars-df"], None)

    def test_auto_detects_sql(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.AUTO)
        suite = UnifiedBenchmarkSuite(config=config)
        with patch.object(suite, "_run_sql_comparison", return_value=[]) as mock_sql:
            suite.run_comparison(["duckdb", "sqlite"])
            mock_sql.assert_called_once()

    def test_auto_detects_dataframe(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.AUTO)
        suite = UnifiedBenchmarkSuite(config=config)
        with patch.object(suite, "_run_dataframe_comparison", return_value=[]) as mock_df:
            suite.run_comparison(["polars-df"])
            mock_df.assert_called_once()

    def test_raises_on_mixed_platform_types(self):
        config = UnifiedBenchmarkConfig(platform_type=PlatformType.AUTO)
        suite = UnifiedBenchmarkSuite(config=config)
        with pytest.raises(ValueError, match="Mixed platform types"):
            suite.run_comparison(["duckdb", "polars-df"])


# ---------------------------------------------------------------------------
# _run_sql_comparison error handling
# ---------------------------------------------------------------------------


class TestRunSqlComparison:
    def test_collects_results_for_each_platform(self):
        suite = UnifiedBenchmarkSuite()
        mock_result = _pr("duckdb", geomean=100.0)
        with patch.object(suite, "_benchmark_sql_platform", return_value=mock_result):
            results = suite._run_sql_comparison(["duckdb"])
        assert len(results) == 1
        assert results[0].platform == "duckdb"

    def test_captures_exception_as_error_result(self):
        suite = UnifiedBenchmarkSuite()
        with patch.object(suite, "_benchmark_sql_platform", side_effect=RuntimeError("boom")):
            results = suite._run_sql_comparison(["bad-platform"])
        assert len(results) == 1
        assert results[0].query_results[0].status == "ERROR"
        assert "boom" in results[0].query_results[0].error_message


# ---------------------------------------------------------------------------
# _build_platform_result
# ---------------------------------------------------------------------------


class TestBuildPlatformResult:
    def test_calculates_geometric_mean(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 100.0), _qr("Q2", "duckdb", 400.0)]
        result = suite._build_platform_result("duckdb", PlatformType.SQL, qrs)
        expected_geomean = math.exp((math.log(100.0) + math.log(400.0)) / 2)
        assert abs(result.geometric_mean_ms - expected_geomean) < 0.01

    def test_calculates_total_time(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 150.0), _qr("Q2", "duckdb", 250.0)]
        result = suite._build_platform_result("duckdb", PlatformType.SQL, qrs)
        assert result.total_time_ms == 400.0

    def test_excludes_error_queries_from_geomean(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 100.0), _qr("Q2", "duckdb", 0.0, status="ERROR")]
        result = suite._build_platform_result("duckdb", PlatformType.SQL, qrs)
        assert result.success_rate == 50.0

    def test_empty_query_results(self):
        suite = UnifiedBenchmarkSuite()
        result = suite._build_platform_result("duckdb", PlatformType.SQL, [])
        assert result.geometric_mean_ms == 0.0
        assert result.success_rate == 0.0

    def test_zero_mean_times_excluded_from_geomean(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 0.0)]  # zero time → excluded from geomean
        result = suite._build_platform_result("duckdb", PlatformType.SQL, qrs)
        assert result.geometric_mean_ms == 0.0


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_raises_on_empty_results(self):
        suite = UnifiedBenchmarkSuite()
        with pytest.raises(ValueError, match="No results"):
            suite.get_summary([])

    def test_identifies_fastest_slowest(self):
        suite = UnifiedBenchmarkSuite()
        results = [_pr("duckdb", geomean=100.0), _pr("sqlite", geomean=500.0)]
        summary = suite.get_summary(results)
        assert summary.fastest_platform == "duckdb"
        assert summary.slowest_platform == "sqlite"
        assert abs(summary.speedup_ratio - 5.0) < 0.01

    def test_handles_no_geomeans(self):
        suite = UnifiedBenchmarkSuite()
        results = [_pr("duckdb", geomean=0.0), _pr("sqlite", geomean=0.0)]
        summary = suite.get_summary(results)
        assert summary.speedup_ratio == 1.0

    def test_finds_query_winners(self):
        suite = UnifiedBenchmarkSuite()
        qr1 = _qr("Q1", "duckdb", 100.0)
        qr2 = _qr("Q1", "sqlite", 300.0)
        pr1 = UnifiedPlatformResult("duckdb", PlatformType.SQL, [qr1], geometric_mean_ms=100.0)
        pr2 = UnifiedPlatformResult("sqlite", PlatformType.SQL, [qr2], geometric_mean_ms=300.0)
        summary = suite.get_summary([pr1, pr2])
        assert summary.query_winners.get("Q1") == "duckdb"

    def test_total_queries_count(self):
        suite = UnifiedBenchmarkSuite()
        qrs1 = [_qr(f"Q{i}", "duckdb", float(i * 10)) for i in range(1, 4)]
        qrs2 = [_qr(f"Q{i}", "sqlite", float(i * 20)) for i in range(1, 4)]
        pr1 = UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs1, geometric_mean_ms=20.0)
        pr2 = UnifiedPlatformResult("sqlite", PlatformType.SQL, qrs2, geometric_mean_ms=40.0)
        summary = suite.get_summary([pr1, pr2])
        assert summary.total_queries == 3


# ---------------------------------------------------------------------------
# export_results
# ---------------------------------------------------------------------------


class TestExportResults:
    def _make_results(self):
        qrs = [_qr("Q1", "duckdb", 100.0)]
        return [UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs, geometric_mean_ms=100.0)]

    def test_exports_json_format(self, tmp_path):
        suite = UnifiedBenchmarkSuite()
        results = self._make_results()
        out = suite.export_results(results, tmp_path / "results.json", format="json")
        assert out.exists()
        data = json.loads(out.read_text())
        assert "results" in data
        assert data["benchmark_suite"] == "unified_comparison"

    def test_exports_markdown_format(self, tmp_path):
        suite = UnifiedBenchmarkSuite()
        results = self._make_results()
        out = suite.export_results(results, tmp_path / "report.md", format="markdown")
        assert out.exists()
        content = out.read_text()
        assert "# Platform Comparison Report" in content

    def test_exports_text_format(self, tmp_path):
        suite = UnifiedBenchmarkSuite()
        results = self._make_results()
        out = suite.export_results(results, tmp_path / "report.txt", format="text")
        assert out.exists()
        content = out.read_text()
        assert "PLATFORM COMPARISON RESULTS" in content

    def test_raises_on_unsupported_format(self, tmp_path):
        suite = UnifiedBenchmarkSuite()
        results = self._make_results()
        with pytest.raises(ValueError, match="Unsupported export format"):
            suite.export_results(results, tmp_path / "out.xyz", format="xyz")

    def test_creates_parent_directories(self, tmp_path):
        suite = UnifiedBenchmarkSuite()
        results = self._make_results()
        nested = tmp_path / "a" / "b" / "c" / "out.json"
        suite.export_results(results, nested, format="json")
        assert nested.exists()


# ---------------------------------------------------------------------------
# _generate_markdown_report
# ---------------------------------------------------------------------------


class TestGenerateMarkdownReport:
    def test_includes_platform_table(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 50.0), _qr("Q1", "sqlite", 200.0)]
        pr1 = UnifiedPlatformResult("duckdb", PlatformType.SQL, [qrs[0]], geometric_mean_ms=50.0)
        pr2 = UnifiedPlatformResult("sqlite", PlatformType.SQL, [qrs[1]], geometric_mean_ms=200.0)
        report = suite._generate_markdown_report([pr1, pr2])
        assert "Platform" in report
        assert "duckdb" in report
        assert "sqlite" in report

    def test_includes_query_winners_section(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 50.0)]
        pr = UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs, geometric_mean_ms=50.0)
        report = suite._generate_markdown_report([pr])
        assert "Query Winners" in report


# ---------------------------------------------------------------------------
# _generate_text_report
# ---------------------------------------------------------------------------


class TestGenerateTextReport:
    def test_includes_headers(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 100.0)]
        pr = UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs, geometric_mean_ms=100.0)
        report = suite._generate_text_report([pr])
        assert "PLATFORM COMPARISON RESULTS" in report
        assert "duckdb" in report
        assert "Fastest" in report


# ---------------------------------------------------------------------------
# _run_dataframe_comparison
# ---------------------------------------------------------------------------


class TestRunDataframeComparison:
    def test_delegates_to_dataframe_suite(self):
        suite = UnifiedBenchmarkSuite()

        # Build a fake DataFrame platform result
        fake_qr = SimpleNamespace(
            query_id="Q1",
            platform="polars-df",
            iterations=3,
            execution_times_ms=[100.0, 110.0, 90.0],
            mean_time_ms=100.0,
            std_time_ms=10.0,
            min_time_ms=90.0,
            max_time_ms=110.0,
            memory_peak_mb=0.0,
            rows_returned=100,
            status="SUCCESS",
            error_message=None,
        )
        fake_result = SimpleNamespace(
            platform="polars-df",
            query_results=[fake_qr],
            total_time_ms=100.0,
            geometric_mean_ms=100.0,
            success_rate=100.0,
        )

        mock_df_suite = MagicMock()
        mock_df_suite.run_comparison.return_value = [fake_result]

        with patch(
            "benchbox.core.dataframe.benchmark_suite.DataFrameBenchmarkSuite",
            return_value=mock_df_suite,
        ):
            results = suite._run_dataframe_comparison(["polars-df"], data_dir="/tmp/data")

        assert len(results) == 1
        assert results[0].platform == "polars-df"
        assert results[0].platform_type == PlatformType.DATAFRAME

    def test_auto_constructs_data_dir_when_none(self):
        suite = UnifiedBenchmarkSuite(config=UnifiedBenchmarkConfig(scale_factor=0.01))
        fake_result = SimpleNamespace(
            platform="polars-df",
            query_results=[],
            total_time_ms=0.0,
            geometric_mean_ms=0.0,
            success_rate=0.0,
        )
        mock_df_suite = MagicMock()
        mock_df_suite.run_comparison.return_value = [fake_result]

        with patch("benchbox.core.dataframe.benchmark_suite.DataFrameBenchmarkSuite", return_value=mock_df_suite):
            suite._run_dataframe_comparison(["polars-df"], data_dir=None)

        call_kwargs = mock_df_suite.run_comparison.call_args[1]
        assert "sf001" in str(call_kwargs.get("data_dir", ""))


# ---------------------------------------------------------------------------
# _benchmark_sql_platform (remote platform path)
# ---------------------------------------------------------------------------


class TestBenchmarkSqlPlatform:
    def test_remote_platform_uses_adapter_connect(self):
        """Test non-embedded platform calls adapter.connect() and runs queries."""
        config = UnifiedBenchmarkConfig(query_ids=["Q1"])
        suite = UnifiedBenchmarkSuite(config=config)

        mock_conn = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = mock_conn

        mock_qr = _qr("Q1", "snowflake", 150.0)
        with (
            patch("benchbox.platforms.get_adapter", return_value=mock_adapter),
            patch.object(suite, "_run_sql_query", return_value=mock_qr),
        ):
            result = suite._benchmark_sql_platform("snowflake")

        mock_adapter.connect.assert_called_once()
        mock_conn.close.assert_called_once()
        assert result.platform == "snowflake"

    def test_embedded_platform_raises_on_missing_data_dir(self, tmp_path):
        """Test embedded platform raises ValueError if data dir missing."""
        config = UnifiedBenchmarkConfig(query_ids=["Q1"])
        suite = UnifiedBenchmarkSuite(config=config)
        mock_adapter = MagicMock()

        with (
            patch("benchbox.platforms.get_adapter", return_value=mock_adapter),
            pytest.raises(ValueError, match="Data directory not found"),
        ):
            suite._benchmark_sql_platform("duckdb", data_dir="/nonexistent/path")

    def test_embedded_platform_auto_data_dir_missing(self):
        """Test embedded platform with None data_dir raises when auto-path missing."""
        config = UnifiedBenchmarkConfig(query_ids=["Q1"])
        suite = UnifiedBenchmarkSuite(config=config)
        mock_adapter = MagicMock()

        with (
            patch("benchbox.platforms.get_adapter", return_value=mock_adapter),
            pytest.raises(ValueError, match="Data directory not found"),
        ):
            suite._benchmark_sql_platform("duckdb", data_dir=None)


# ---------------------------------------------------------------------------
# _run_sql_query
# ---------------------------------------------------------------------------


class TestRunSqlQuery:
    def test_success_path(self):
        import sys

        config = UnifiedBenchmarkConfig(warmup_iterations=0, benchmark_iterations=1)
        suite = UnifiedBenchmarkSuite(config=config)

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("row1",), ("row2",)]

        mock_tpch_query = MagicMock()
        mock_tpch_query.sql = "SELECT 1"

        mock_tpch_class = MagicMock()
        mock_tpch_class.get_query.return_value = mock_tpch_query

        mock_queries_mod = MagicMock()
        mock_queries_mod.TPCHQuery = mock_tpch_class

        with patch.dict(sys.modules, {"benchbox.core.tpch.queries": mock_queries_mod}):
            result = suite._run_sql_query("Q1", "duckdb", mock_conn)

        assert result.status == "SUCCESS"
        assert result.rows_returned == 2
        assert result.query_id == "Q1"

    def test_error_path(self):
        import sys

        config = UnifiedBenchmarkConfig(warmup_iterations=0, benchmark_iterations=1)
        suite = UnifiedBenchmarkSuite(config=config)
        mock_conn = MagicMock()

        mock_tpch_class = MagicMock()
        mock_tpch_class.get_query.side_effect = RuntimeError("query not found")
        mock_queries_mod = MagicMock()
        mock_queries_mod.TPCHQuery = mock_tpch_class

        with patch.dict(sys.modules, {"benchbox.core.tpch.queries": mock_queries_mod}):
            result = suite._run_sql_query("Q1", "duckdb", mock_conn)

        assert result.status == "ERROR"
        assert "query not found" in result.error_message


# ---------------------------------------------------------------------------
# _generate_markdown_report - empty query_winners branch
# ---------------------------------------------------------------------------


class TestGenerateMarkdownReportBranches:
    def test_no_query_winners_when_all_errors(self):
        suite = UnifiedBenchmarkSuite()
        # All queries errored, so no winners found
        qrs = [_qr("Q1", "duckdb", 0.0, status="ERROR")]
        pr = UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs, geometric_mean_ms=0.0)
        report = suite._generate_markdown_report([pr])
        # summary.query_winners is empty, section skipped
        assert "Query Winners" not in report


# ---------------------------------------------------------------------------
# get_summary - no best_platform branch (query has only error results)
# ---------------------------------------------------------------------------


class TestGetSummaryBranches:
    def test_query_with_only_errors_has_no_winner(self):
        suite = UnifiedBenchmarkSuite()
        qrs = [_qr("Q1", "duckdb", 0.0, status="ERROR")]
        pr = UnifiedPlatformResult("duckdb", PlatformType.SQL, qrs, geometric_mean_ms=0.0)
        summary = suite.get_summary([pr])
        # Q1 has no winner (all errors)
        assert "Q1" not in summary.query_winners


# ---------------------------------------------------------------------------
# run_unified_comparison convenience function
# ---------------------------------------------------------------------------


class TestRunUnifiedComparison:
    def test_delegates_to_suite(self):
        mock_results = [_pr("duckdb", geomean=100.0)]
        with patch.object(UnifiedBenchmarkSuite, "run_comparison", return_value=mock_results) as mock_run:
            results = run_unified_comparison(["duckdb"], platform_type=PlatformType.SQL)
            mock_run.assert_called_once_with(platforms=["duckdb"], data_dir=None)
        assert results is mock_results
