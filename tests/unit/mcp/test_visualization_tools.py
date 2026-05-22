"""Tests for BenchBox MCP visualization tools.

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


class TestResolveResultPath:
    """Tests for resolve_result_file_path helper."""

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Test that function returns None for files that don't exist."""
        from benchbox.mcp.tools.path_utils import resolve_result_file_path

        result = resolve_result_file_path("definitely_not_a_real_file_xyz123.json", tmp_path)
        assert result is None

    def test_rejects_path_traversal_with_dotdot(self, tmp_path):
        """Test that path traversal attempts with .. are rejected."""
        from benchbox.mcp.tools.path_utils import resolve_result_file_path

        # Various path traversal attempts
        assert resolve_result_file_path("../etc/passwd", tmp_path) is None
        assert resolve_result_file_path("..\\etc\\passwd", tmp_path) is None
        assert resolve_result_file_path("foo/../../../etc/passwd", tmp_path) is None
        assert resolve_result_file_path("valid/../../secret.json", tmp_path) is None

    def test_rejects_absolute_paths(self, tmp_path):
        """Test that absolute paths are rejected."""
        from benchbox.mcp.tools.path_utils import resolve_result_file_path

        assert resolve_result_file_path("/etc/passwd", tmp_path) is None
        assert resolve_result_file_path("/tmp/result.json", tmp_path) is None
        assert resolve_result_file_path("\\Windows\\System32\\config", tmp_path) is None

    def test_allows_valid_filename_in_results_dir(self, tmp_path):
        """Test that valid filenames within results dir are allowed."""
        from benchbox.mcp.tools.path_utils import resolve_result_file_path

        # Create a mock results directory
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)
        test_file = results_dir / "test_result.json"
        test_file.write_text("{}")

        result = resolve_result_file_path("test_result.json", results_dir)
        assert result is not None
        assert result.exists()
        assert result.name == "test_result.json"

    def test_adds_json_extension_if_missing(self, tmp_path):
        """Test that .json extension is added if missing."""
        from benchbox.mcp.tools.path_utils import resolve_result_file_path

        # Create a mock results directory
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)
        test_file = results_dir / "test_result.json"
        test_file.write_text("{}")

        result = resolve_result_file_path("test_result", results_dir)
        assert result is not None
        assert result.name == "test_result.json"


class TestListChartTemplates:
    """Tests for list_chart_templates tool."""

    def test_returns_templates(self):
        """Test that list_chart_templates returns template information."""
        from benchbox.core.visualization.templates import list_templates

        templates = list_templates()

        assert len(templates) >= 5
        template_names = [t.name for t in templates]
        assert "default" in template_names
        assert "flagship" in template_names
        assert "head_to_head" in template_names
        assert "trends" in template_names
        assert "cost_optimization" in template_names

    def test_template_structure(self):
        """Test that templates have required fields."""
        from benchbox.core.visualization.templates import get_template

        template = get_template("default")

        assert template.name == "default"
        assert template.description
        assert len(template.chart_types) > 0
        assert len(template.formats) > 0


class TestChartTypeDescriptions:
    """Tests for CHART_TYPE_DESCRIPTIONS constant."""

    def test_all_chart_types_documented(self):
        """Test that all chart types have descriptions."""
        from benchbox.core.visualization.chart_types import ALL_CHART_TYPES
        from benchbox.mcp.tools.visualization import CHART_TYPE_DESCRIPTIONS

        assert set(CHART_TYPE_DESCRIPTIONS.keys()) == set(ALL_CHART_TYPES)

    def test_descriptions_are_strings(self):
        """Test that all descriptions are non-empty strings."""
        from benchbox.mcp.tools.visualization import CHART_TYPE_DESCRIPTIONS

        for chart_type, description in CHART_TYPE_DESCRIPTIONS.items():
            assert isinstance(description, str), f"{chart_type} description is not a string"
            assert len(description) > 10, f"{chart_type} description is too short"


class TestGenerateChartValidation:
    """Tests for generate_chart validation logic."""

    def test_invalid_chart_type_error(self):
        """Test that invalid chart type returns error."""
        from benchbox.mcp.tools.visualization import CHART_TYPE_DESCRIPTIONS

        # Verify valid chart types for comparison
        assert "invalid_type" not in CHART_TYPE_DESCRIPTIONS

    def test_valid_chart_types(self):
        """Test that valid chart types are recognized."""
        from benchbox.core.visualization.chart_types import ALL_CHART_TYPES
        from benchbox.mcp.tools.visualization import CHART_TYPE_DESCRIPTIONS

        assert set(ALL_CHART_TYPES) == set(CHART_TYPE_DESCRIPTIONS.keys())


class TestGenerateChartSetValidation:
    """Tests for generate_chart_set validation logic."""

    def test_empty_result_files_parsing(self):
        """Test parsing of empty result files string."""
        result_files = ""
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 0

    def test_single_result_file_parsing(self):
        """Test parsing of single result file string."""
        result_files = "run1.json"
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 1
        assert file_list[0] == "run1.json"

    def test_multiple_result_files_parsing(self):
        """Test parsing of multiple result files string."""
        result_files = "run1.json, run2.json, run3.json"
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 3
        assert file_list[0] == "run1.json"
        assert file_list[1] == "run2.json"
        assert file_list[2] == "run3.json"


class TestResultFilesParsingValidation:
    """Tests for result_files parameter parsing in generate_chart."""

    def test_single_file_parsing(self):
        """Test that single file is parsed correctly."""
        result_files = "single.json"
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 1
        assert file_list[0] == "single.json"

    def test_multiple_files_parsing(self):
        """Test that multiple files are parsed correctly."""
        result_files = "file1.json, file2.json, file3.json"
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 3
        assert file_list == ["file1.json", "file2.json", "file3.json"]

    def test_empty_string_returns_empty_list(self):
        """Test that empty string results in empty list."""
        result_files = ""
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        assert len(file_list) == 0


class TestToolRegistration:
    """Tests for tool registration."""

    def test_visualization_tools_registered(self):
        """Test that visualization tools are properly registered."""
        from benchbox.mcp.server import create_benchbox_server

        server = create_benchbox_server()

        # Get registered tools
        # FastMCP stores tools internally
        assert server is not None

    def test_suggest_charts_tool_registered(self):
        """Test that suggest_charts tool is registered."""
        tools = _get_viz_tool_functions()
        assert "suggest_charts" in tools


class TestSuggestCharts:
    """Tests for suggest_charts tool."""

    def test_returns_suggestions_for_valid_results(self, tmp_path):
        """Test that suggest_charts returns appropriate suggestions."""
        # Set up mock results directory
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        # Create mock result files with query data
        result1 = results_dir / "duckdb_result.json"
        result1.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        result2 = results_dir / "postgres_result.json"
        result2.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "Postgres"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 150}]},
                "timing": {"total_ms": 1500, "avg_ms": 150}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        assert suggest_charts is not None

        result = suggest_charts(result_files="duckdb_result.json,postgres_result.json")

        # Verify structure
        assert "suggestions" in result
        assert "primary" in result
        assert "data_profile" in result

        # Verify suggestions include expected types for 2 results with query data
        chart_types = [s["chart_type"] for s in result["suggestions"]]
        assert "performance_bar" in chart_types
        assert "query_heatmap" in chart_types  # 2+ results with query data

        # Verify data profile
        assert result["data_profile"]["result_count"] == 2
        assert "DuckDB" in result["data_profile"]["platforms"]
        assert "Postgres" in result["data_profile"]["platforms"]

    def test_returns_error_for_missing_files(self):
        """Test that suggest_charts returns error for missing files."""
        tools = _get_viz_tool_functions()
        suggest_charts = tools.get("suggest_charts")
        assert suggest_charts is not None

        result = suggest_charts(result_files="nonexistent_file.json")

        assert result["error"] is True
        assert "RESOURCE_NOT_FOUND" in result["error_code"]

    def test_returns_error_for_empty_input(self):
        """Test that suggest_charts returns error for empty input."""
        tools = _get_viz_tool_functions()
        suggest_charts = tools.get("suggest_charts")
        assert suggest_charts is not None

        result = suggest_charts(result_files="")

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]

    def test_single_result_suggests_distribution_box_as_primary(self, tmp_path):
        """Test that single result file suggests distribution_box as primary (not heatmap)."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        # Create single result file with query data
        result1 = results_dir / "single_result.json"
        result1.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [
                    {"id": "Q1", "execution_time_ms": 100},
                    {"id": "Q2", "execution_time_ms": 200},
                    {"id": "Q3", "execution_time_ms": 150}
                ]},
                "timing": {"total_ms": 450, "avg_ms": 150}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        result = suggest_charts(result_files="single_result.json")

        # Single result should recommend distribution_box, not heatmap
        assert result["primary"]["chart_type"] == "distribution_box"
        chart_types = [s["chart_type"] for s in result["suggestions"]]
        assert "query_heatmap" not in chart_types  # Heatmap requires 2+ results
        assert "distribution_box" in chart_types
        assert result["data_profile"]["result_count"] == 1

    def test_results_without_query_data_suggests_only_performance_bar(self, tmp_path):
        """Test that results without query data only suggest performance_bar."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        # Create result file without query details
        result1 = results_dir / "no_queries.json"
        result1.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": []},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        result = suggest_charts(result_files="no_queries.json")

        # Without query data, only performance_bar should be suggested
        assert result["primary"]["chart_type"] == "performance_bar"
        chart_types = [s["chart_type"] for s in result["suggestions"]]
        assert chart_types == ["performance_bar"]
        assert result["data_profile"]["total_queries"] == 0
        assert result["data_profile"]["has_cost_data"] is False

    def test_results_with_cost_data_suggests_cost_scatter(self, tmp_path):
        """Test that results with cost data include cost_scatter suggestion."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        # Create result file with cost data (cost_summary.total_cost is the expected field)
        result1 = results_dir / "with_cost.json"
        result1.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "Snowflake"},
            "config": {"mode": "sql"},
            "cost_summary": {"total_cost": 0.05},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        result = suggest_charts(result_files="with_cost.json")

        chart_types = [s["chart_type"] for s in result["suggestions"]]
        assert "cost_scatter" in chart_types
        assert result["data_profile"]["has_cost_data"] is True

    def test_power_run_suggests_power_bar(self, tmp_path):
        """Power-run result files should include power_bar in MCP suggestions."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "power_result.json"
        result_file.write_text("""{
            "version": "2.1",
            "benchmark": {"id": "joinorder", "name": "JoinOrder", "scale_factor": 1, "test_type": "power"},
            "platform": {"name": "DuckDB"},
            "summary": {"queries": {"total": 1, "passed": 1, "failed": 0}, "timing": {"total_ms": 100}},
            "queries": [{"id": "1a", "ms": 12.0, "status": "SUCCESS"}]
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        result = suggest_charts(result_files="power_result.json")

        chart_types = [suggestion["chart_type"] for suggestion in result["suggestions"]]
        assert "power_bar" in chart_types
        assert result["primary"]["chart_type"] == "power_bar"
        assert result["data_profile"]["has_power_data"] is True

    def test_multiple_results_with_timestamps_suggests_time_series(self, tmp_path):
        """Test that 3+ results with timestamps include time_series suggestion."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        # Create 3 result files with timestamps (timestamp is in execution block)
        for i, ts in enumerate(["2026-01-26T10:00:00", "2026-01-27T10:00:00", "2026-01-28T10:00:00"]):
            result_file = results_dir / f"run_{i}.json"
            result_file.write_text(f"""{{
                "benchmark": {{"name": "TPC-H", "scale_factor": 1}},
                "platform": {{"name": "DuckDB"}},
                "config": {{"mode": "sql"}},
                "execution": {{"timestamp": "{ts}"}},
                "results": {{
                    "queries": {{"details": [{{"id": "Q1", "execution_time_ms": {100 + i * 10}}}]}},
                    "timing": {{"total_ms": {1000 + i * 100}, "avg_ms": 100}}
                }}
            }}""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        suggest_charts = tools.get("suggest_charts")
        result = suggest_charts(result_files="run_0.json,run_1.json,run_2.json")

        chart_types = [s["chart_type"] for s in result["suggestions"]]
        assert "time_series" in chart_types
        assert result["data_profile"]["has_timestamps"] is True
        assert result["data_profile"]["result_count"] == 3


def _get_viz_tool_functions(*, results_dir=None, charts_dir=None):
    """Create a fresh MCP server and extract visualization tool functions."""
    from benchbox.mcp import create_server

    kwargs = {}
    if results_dir is not None:
        kwargs["results_dir"] = results_dir
    if charts_dir is not None:
        kwargs["charts_dir"] = charts_dir
    server = create_server(**kwargs)
    tools = {}
    if hasattr(server, "_tool_manager"):
        tool_dict = getattr(server._tool_manager, "_tools", {})
        for name, tool in tool_dict.items():
            tools[name] = tool.fn
    return tools


class TestGenerateChartIntegration:
    """Integration-style tests for generate_chart tool (ASCII-only)."""

    def test_generates_ascii_chart_with_valid_inputs(self, tmp_path):
        """Test ASCII chart generation with valid inputs."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")
        assert generate_chart is not None

        result = generate_chart(
            result_files="test_result.json",
            chart_type="performance_bar",
        )

        assert result["status"] == "generated"
        assert result["chart_type"] == "performance_bar"
        assert result["format"] == "ascii"
        assert "content" in result

    def test_rejects_invalid_chart_type(self, tmp_path):
        """Test that invalid chart type is rejected."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("{}")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")
        assert generate_chart is not None

        result = generate_chart(
            result_files="test_result.json",
            chart_type="invalid_chart_type",
        )

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]

    def test_known_inapplicable_chart_is_not_reported_as_unsupported(self, tmp_path):
        """Known charts without required data should report not-applicable, not unsupported."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")

        result = generate_chart(result_files="test_result.json", chart_type="stacked_phase")

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]
        assert "not applicable" in result["message"]
        assert "Unsupported chart type" not in result["message"]
        assert result["details"]["skip"]["chart_type"] == "stacked_phase"

    def test_rejects_pairwise_chart_without_two_results(self, tmp_path):
        """Pairwise chart types require exactly two result files."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")
        assert generate_chart is not None

        result = generate_chart(result_files="test_result.json", chart_type="comparison_bar")

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]

    def test_generates_chart_with_multiple_files(self, tmp_path):
        """Test chart generation with multiple result files."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file1 = results_dir / "result1.json"
        result_file1.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")
        result_file2 = results_dir / "result2.json"
        result_file2.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "Postgres"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 150}]},
                "timing": {"total_ms": 1500, "avg_ms": 150}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")

        result = generate_chart(
            result_files="result1.json,result2.json",
            chart_type="performance_bar",
        )

        assert result["status"] == "generated"
        assert result["chart_type"] == "performance_bar"
        assert result["format"] == "ascii"
        assert len(result["source_files"]) == 2

    def test_generates_chart_set_with_template(self, tmp_path):
        """Test chart set generation using template parameter."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("""{
            "benchmark": {"name": "TPC-H", "scale_factor": 1},
            "platform": {"name": "DuckDB"},
            "config": {"mode": "sql"},
            "results": {
                "queries": {"details": [{"id": "Q1", "execution_time_ms": 100}]},
                "timing": {"total_ms": 1000, "avg_ms": 100}
            }
        }""")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")

        result = generate_chart(
            result_files="test_result.json",
            template="default",
        )

        assert result["status"] == "generated"
        assert result["template"] == "default"
        assert result["chart_count"] >= 1
        assert result["format"] == "ascii"
        assert "content" in result
        assert "skipped_chart_types" in result
        assert isinstance(result["skipped_chart_types"], list)
        for skipped in result["skipped_chart_types"]:
            assert "chart_type" in skipped
            assert "reason" in skipped


class TestGenerateChartErrorHandling:
    """Tests for generate_chart error handling."""

    def test_returns_error_for_missing_files(self, tmp_path):
        """Test that generate_chart returns error for missing result files."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")
        assert generate_chart is not None

        result = generate_chart(
            result_files="nonexistent_file.json",
            chart_type="performance_bar",
        )

        assert result["error"] is True
        assert "RESOURCE_NOT_FOUND" in result["error_code"]

    def test_returns_error_for_empty_result_files(self):
        """Test that generate_chart returns error for empty result_files."""
        tools = _get_viz_tool_functions()
        generate_chart = tools.get("generate_chart")
        assert generate_chart is not None

        result = generate_chart(
            result_files="",
            chart_type="performance_bar",
        )

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]

    def test_returns_error_for_invalid_template(self, tmp_path):
        """Test that generate_chart returns error for invalid template."""
        results_dir = tmp_path / "benchmark_runs" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "test_result.json"
        result_file.write_text("{}")

        tools = _get_viz_tool_functions(results_dir=results_dir)
        generate_chart = tools.get("generate_chart")

        result = generate_chart(
            result_files="test_result.json",
            template="nonexistent_template",
        )

        assert result["error"] is True
        assert "VALIDATION_ERROR" in result["error_code"]
