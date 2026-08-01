"""Tests for BenchBox MCP analytics tools.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from pathlib import Path

import pytest

from tests.unit.mcp.public_api import get_tool

# Skip all tests if Python < 3.10
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP server requires Python 3.10+"),
]


def _make_analytics_mcp(results_dir: Path):
    """Create an MCPServer with analytics tools registered."""
    from mcp.server.mcpserver import MCPServer

    from benchbox.mcp.tools.analytics import register_analytics_tools

    mcp = MCPServer("test", version="test")
    register_analytics_tools(mcp, results_dir=results_dir)
    return mcp


def _get_tool(mcp, name: str):
    """Look up a registered MCP tool by public name."""
    return get_tool(mcp, name)


@pytest.fixture
def analytics_mcp(tmp_path):
    """Pre-registered MCP server with analytics tools."""
    return _make_analytics_mcp(tmp_path)


class TestGetQueryPlanTool:
    """Tests for get_query_plan tool functionality."""

    def test_invalid_format_returns_error(self, analytics_mcp):
        """Test that invalid format parameter returns validation error."""
        get_query_plan = _get_tool(analytics_mcp, "get_query_plan")

        result = get_query_plan.fn(result_file="test.json", query_id="1", format="invalid")

        assert "error" in result
        assert result["error_code"] == "VALIDATION_INVALID_FORMAT"

    def test_valid_formats_accepted(self, analytics_mcp):
        """Test that valid format parameters are accepted."""
        get_query_plan = _get_tool(analytics_mcp, "get_query_plan")

        for fmt in ["tree", "json", "summary"]:
            result = get_query_plan.fn(result_file="nonexistent.json", query_id="1", format=fmt)

            # Should fail with file not found, not format validation
            if "error" in result:
                assert result["error_code"] != "VALIDATION_INVALID_FORMAT"

    def test_missing_file_returns_error(self, analytics_mcp):
        """Test that missing result file returns appropriate error."""
        get_query_plan = _get_tool(analytics_mcp, "get_query_plan")

        result = get_query_plan.fn(result_file="nonexistent_file.json", query_id="1", format="tree")

        assert "error" in result
        assert result["error_code"] == "RESOURCE_NOT_FOUND"


class TestAnalyzeResultsRegressions:
    """Tests for analyze_results with analysis='regressions'."""

    def test_no_results_directory_returns_no_data(self, tmp_path):
        """Test that missing results directory returns no_data status."""
        mcp = _make_analytics_mcp(tmp_path / "nonexistent")
        analyze_results = _get_tool(mcp, "analyze_results")

        result = analyze_results.fn(analysis="regressions")

        assert result["status"] in ["no_data", "insufficient_data"]

    def test_threshold_percent_default(self, analytics_mcp):
        """Test default threshold percent is used."""
        analyze_results = _get_tool(analytics_mcp, "analyze_results")

        # The tool should accept no arguments beyond analysis type
        result = analyze_results.fn(analysis="regressions")

        # Should not fail on missing arguments
        assert "status" in result


class TestAnalyzeResultsTrends:
    """Tests for analyze_results with analysis='trends'."""

    def test_invalid_metric_returns_error(self, analytics_mcp):
        """Test that invalid metric parameter returns validation error."""
        analyze_results = _get_tool(analytics_mcp, "analyze_results")

        result = analyze_results.fn(analysis="trends", metric="invalid_metric")

        assert "error" in result
        assert result["error_code"] == "VALIDATION_ERROR"

    def test_valid_metrics_accepted(self, analytics_mcp):
        """Test that valid metric parameters are accepted."""
        analyze_results = _get_tool(analytics_mcp, "analyze_results")

        for metric in ["geometric_mean", "p50", "p95", "p99", "total_time"]:
            result = analyze_results.fn(analysis="trends", metric=metric)

            # Should not fail with metric validation error
            if "error" in result:
                assert result.get("error_code") != "VALIDATION_ERROR"

    def test_no_results_returns_no_data(self, tmp_path):
        """Test that missing results returns appropriate status."""
        mcp = _make_analytics_mcp(tmp_path / "nonexistent")
        analyze_results = _get_tool(mcp, "analyze_results")

        result = analyze_results.fn(analysis="trends")

        assert result["status"] in ["no_data", "no_matching_data"]


class TestAnalyzeResultsAggregate:
    """Tests for analyze_results with analysis='aggregate'."""

    def test_invalid_group_by_returns_error(self, analytics_mcp):
        """Test that invalid group_by parameter returns validation error."""
        analyze_results = _get_tool(analytics_mcp, "analyze_results")

        result = analyze_results.fn(analysis="aggregate", group_by="invalid")

        assert "error" in result
        assert result["error_code"] == "VALIDATION_ERROR"

    def test_valid_group_by_accepted(self, analytics_mcp):
        """Test that valid group_by parameters are accepted."""
        analyze_results = _get_tool(analytics_mcp, "analyze_results")

        for group in ["platform", "benchmark", "date"]:
            result = analyze_results.fn(analysis="aggregate", group_by=group)

            # Should not fail with validation error
            if "error" in result:
                assert result.get("error_code") != "VALIDATION_ERROR"


class TestAnalyticsHelperFunctions:
    """Tests for analytics helper functions."""

    def test_percentile_calculation(self):
        """Test percentile calculation helper."""
        from benchbox.mcp.tools.analytics import _percentile

        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        assert _percentile(data, 50) == 5.5
        assert _percentile(data, 0) == 1
        assert _percentile(data, 100) == 10

    def test_percentile_empty_data(self):
        """Test percentile with empty data."""
        from benchbox.mcp.tools.analytics import _percentile

        assert _percentile([], 50) == 0

    def test_std_dev_calculation(self):
        """Test standard deviation calculation helper."""
        from benchbox.mcp.tools.analytics import _std_dev

        data = [2, 4, 4, 4, 5, 5, 7, 9]
        std = _std_dev(data)

        # Sample standard deviation should be approximately 2.14
        assert 2.1 < std < 2.2

    def test_std_dev_single_value(self):
        """Test standard deviation with single value."""
        from benchbox.mcp.tools.analytics import _std_dev

        assert _std_dev([5]) == 0

    def test_calculate_metric_geometric_mean(self):
        """Test geometric mean calculation."""
        from benchbox.mcp.tools.analytics import _calculate_metric

        data = [1, 2, 4, 8]
        result = _calculate_metric(data, "geometric_mean")

        # Geometric mean of 1,2,4,8 = (1*2*4*8)^(1/4) = 64^0.25 ≈ 2.83
        assert 2.8 < result < 2.9

    def test_classify_regression_severity(self):
        """Test regression severity classification."""
        from benchbox.mcp.tools.analytics import _classify_regression_severity

        assert _classify_regression_severity(150) == "critical"
        assert _classify_regression_severity(75) == "high"
        assert _classify_regression_severity(30) == "medium"
        assert _classify_regression_severity(15) == "low"
