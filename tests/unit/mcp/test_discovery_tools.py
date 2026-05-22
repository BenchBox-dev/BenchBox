"""Tests for BenchBox MCP discovery tools.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from pathlib import Path

import pytest

# Skip all tests if Python < 3.10
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP server requires Python 3.10+"),
]


class TestListPlatformsTool:
    """Tests for list_platforms tool functionality."""

    def test_returns_platform_list(self):
        """Test that list_platforms returns a list of platforms."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()

        assert len(all_metadata) > 0
        assert "duckdb" in all_metadata

    def test_platform_has_required_fields(self):
        """Test that platforms have required metadata fields."""
        from benchbox.core.platform_registry import PlatformRegistry

        all_metadata = PlatformRegistry.get_all_platform_metadata()

        for name, metadata in all_metadata.items():
            assert "display_name" in metadata or name
            assert "capabilities" in metadata


class TestListBenchmarksTool:
    """Tests for list_benchmarks tool functionality."""

    def test_returns_benchmark_list(self):
        """Test that benchmarks are discoverable."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()

        assert len(benchmarks) > 0
        assert "tpch" in benchmarks
        assert "tpcds" in benchmarks

    def test_benchmark_has_required_fields(self):
        """Test that benchmarks have required metadata fields."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()

        for name, meta in benchmarks.items():
            assert "display_name" in meta
            assert "description" in meta
            assert "num_queries" in meta or meta.get("num_queries") == 0
            assert "category" in meta
            assert "support_status" in meta

    def test_list_benchmarks_projects_registry_support_status(self):
        """MCP benchmark discovery should consume registry support status."""
        from benchbox.mcp.tools.discovery import _list_benchmarks_impl

        result = _list_benchmarks_impl()
        benchmarks = {row["name"]: row for row in result["benchmarks"]}

        assert benchmarks["tpch"]["support_status"] == "stable"
        assert benchmarks["ai_primitives"]["support_status"] == "experimental"
        assert "joinorder_synthetic" not in benchmarks


class TestGetBenchmarkInfoTool:
    """Tests for get_benchmark_info tool functionality."""

    def test_get_tpch_info(self):
        """Test getting TPC-H benchmark info."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()
        assert "tpch" in benchmarks

        meta = benchmarks["tpch"]
        assert meta["display_name"] == "TPC-H"
        assert meta["num_queries"] == 22
        assert meta["support_status"] == "stable"

    def test_get_benchmark_info_projects_support_status(self):
        """Detailed MCP benchmark info should expose registry support status."""
        from benchbox.mcp.tools.discovery import _get_benchmark_info_impl

        result = _get_benchmark_info_impl("tpch")

        assert result["name"] == "tpch"
        assert result["support_status"] == "stable"

    def test_get_tpcds_info(self):
        """Test getting TPC-DS benchmark info."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()
        assert "tpcds" in benchmarks

        meta = benchmarks["tpcds"]
        assert meta["display_name"] == "TPC-DS"
        assert meta["num_queries"] == 99

    def test_unknown_benchmark_error(self):
        """Test that unknown benchmark returns appropriate error info."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()
        assert "nonexistent_benchmark" not in benchmarks

    def test_get_benchmark_info_docstring_does_not_repeat_registry_list(self):
        """Human-facing MCP hints should point callers at registry-backed discovery."""

        source = Path("benchbox/mcp/tools/discovery.py").read_text(encoding="utf-8")

        assert "tpch, tpcds, ssb, clickbench" not in source
        assert 'list_available("benchmarks")' in source


class TestSystemProfileTool:
    """Tests for system_profile tool functionality."""

    def test_returns_system_info(self):
        """Test that system profile returns CPU and memory info."""
        import psutil

        cpu_count = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()

        assert cpu_count is not None
        assert cpu_count > 0
        assert memory.total > 0
        assert memory.available > 0

    def test_benchbox_version_available(self):
        """Test that BenchBox version is available."""
        import benchbox

        version = getattr(benchbox, "__version__", None)
        assert version is not None


class TestChartDiscoveryContract:
    """Tests for visualization discovery metadata."""

    def test_chart_discovery_returns_complete_semantic_registry(self):
        from benchbox.core.visualization.chart_types import ALL_CHART_TYPES, CHART_TYPE_DESCRIPTIONS
        from benchbox.mcp.tools.discovery import _list_chart_templates_impl

        result = _list_chart_templates_impl()

        assert result["chart_type_coverage"] == "complete_semantic_registry"
        assert result["chart_namespace"] == "benchbox_result_aware_semantic_ids"
        assert set(result["chart_types"]) == set(ALL_CHART_TYPES)
        assert set(result["chart_types"]) == set(CHART_TYPE_DESCRIPTIONS)
        assert result["semantic_chart_ids"] == list(ALL_CHART_TYPES)

    def test_chart_discovery_keeps_textcharts_namespace_external(self):
        from benchbox.mcp.tools.discovery import _list_chart_templates_impl

        result = _list_chart_templates_impl()

        assert "bar" not in result["chart_types"]
        assert "heatmap" not in result["chart_types"]
        assert "query_heatmap" in result["chart_types"]
        assert "textcharts" in result["external_chart_namespaces"]
        assert "not accepted as BenchBox chart_type" in result["external_chart_namespaces"]["textcharts"]

    def test_chart_discovery_templates_follow_registry(self):
        from benchbox.core.visualization.templates import list_templates
        from benchbox.mcp.tools.discovery import _list_chart_templates_impl

        result = _list_chart_templates_impl()

        assert {item["name"] for item in result["templates"]} == {template.name for template in list_templates()}
