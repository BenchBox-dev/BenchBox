"""Tests for MCP tool handler functions exercising real code paths.

These tests call the actual MCP-registered tool functions (via the server's
internal registry) with appropriate mocking of heavy dependencies (benchmark
execution, file I/O) to verify argument handling, error paths, and response
structure.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.result_dict_fixtures import write_v2_result_file

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP server requires Python 3.10+"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tool_functions():
    """Create a fresh MCP server and extract registered tool functions."""
    from benchbox.mcp import create_server

    server = create_server()
    # FastMCP stores tools in _tool_manager._tools (private dict of name -> Tool)
    tools = {}
    if hasattr(server, "_tool_manager"):
        tool_dict = getattr(server._tool_manager, "_tools", {})
        for name, tool in tool_dict.items():
            tools[name] = tool.fn
    return tools


@pytest.fixture(scope="module")
def tool_functions():
    """Module-scoped fixture for tool function lookup."""
    return _get_tool_functions()


# ---------------------------------------------------------------------------
# run_benchmark with validate_only=True (consolidated validate_config)
# ---------------------------------------------------------------------------


class TestValidateConfigTool:
    """Tests for run_benchmark with validate_only=True (consolidated validate_config)."""

    def test_valid_duckdb_tpch_returns_valid(self, tool_functions):
        """Valid platform + benchmark returns valid=True."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, validate_only=True)

        assert result["valid"] is True
        assert result["platform"] == "duckdb"
        assert result["benchmark"] == "tpch"
        assert result["errors"] == []

    def test_unknown_platform_returns_error(self, tool_functions):
        """Unknown platform produces a validation error."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="nonexistent_db", benchmark="tpch", scale_factor=1.0, validate_only=True)

        assert result["valid"] is False
        assert any("Unknown platform" in e for e in result["errors"])

    def test_unknown_benchmark_returns_error(self, tool_functions):
        """Unknown benchmark produces a validation error."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="fake_benchmark", scale_factor=1.0, validate_only=True)

        assert result["valid"] is False
        assert any("Unknown benchmark" in e for e in result["errors"])

    def test_negative_scale_factor_returns_error(self, tool_functions):
        """Negative scale factor is invalid."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=-1.0, validate_only=True)

        assert result["valid"] is False
        assert any("positive" in e.lower() for e in result["errors"])

    def test_cloud_platform_produces_warning(self, tool_functions):
        """Cloud platforms produce credential warnings."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="snowflake", benchmark="tpch", scale_factor=1.0, validate_only=True)

        assert any("credential" in w.lower() for w in result["warnings"])

    def test_dataframe_unsupported_benchmark_returns_error(self, tool_functions):
        """DataFrame mode with unsupported benchmark produces error."""
        fn = tool_functions["run_benchmark"]
        # ai_primitives does not support DataFrame mode
        result = fn(platform="polars-df", benchmark="ai_primitives", scale_factor=1.0, validate_only=True)

        assert result["valid"] is False
        assert any("DataFrame" in e for e in result["errors"])

    def test_response_contains_execution_mode(self, tool_functions):
        """Response includes execution_mode field."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, validate_only=True)

        assert "execution_mode" in result
        assert result["execution_mode"] in ("sql", "dataframe", "data_only")


# ---------------------------------------------------------------------------
# get_query_details tool
# ---------------------------------------------------------------------------


class TestGetQueryDetailsTool:
    """Tests for the get_query_details tool handler."""

    def test_tpch_query_returns_sql(self, tool_functions):
        """TPC-H query 6 returns SQL text."""
        fn = tool_functions["get_query_details"]
        result = fn(benchmark="tpch", query_id="6")

        assert "error" not in result
        assert result["benchmark"] == "tpch"
        assert "sql" in result
        assert "select" in result["sql"].lower() or "SELECT" in result["sql"]

    def test_query_id_with_q_prefix(self, tool_functions):
        """Q-prefixed query IDs are normalized."""
        fn = tool_functions["get_query_details"]
        result = fn(benchmark="tpch", query_id="Q6")

        assert "error" not in result
        assert result["normalized_id"] == "6"

    def test_unknown_benchmark_returns_error(self, tool_functions):
        """Unknown benchmark returns error response."""
        fn = tool_functions["get_query_details"]
        result = fn(benchmark="fake_benchmark", query_id="1")

        assert result["error"] is True
        assert result["error_code"] == "RESOURCE_NOT_FOUND"

    def test_response_has_complexity_hints(self, tool_functions):
        """Response includes complexity hints."""
        fn = tool_functions["get_query_details"]
        result = fn(benchmark="tpch", query_id="6")

        assert "complexity_hints" in result
        assert "complexity" in result["complexity_hints"]

    def test_response_has_benchmark_info(self, tool_functions):
        """Response includes benchmark metadata."""
        fn = tool_functions["get_query_details"]
        result = fn(benchmark="tpch", query_id="1")

        assert "benchmark_info" in result
        assert "display_name" in result["benchmark_info"]


# ---------------------------------------------------------------------------
# list_available with category="platforms" (consolidated list_platforms)
# ---------------------------------------------------------------------------


class TestListPlatformsTool:
    """Tests for list_available with category='platforms' (consolidated list_platforms)."""

    def test_returns_platforms_list(self, tool_functions):
        """Response contains platforms list with expected structure."""
        fn = tool_functions["list_available"]
        result = fn(category="platforms")

        assert "platforms" in result
        assert "count" in result
        assert result["count"] > 0
        assert len(result["platforms"]) == result["count"]

    def test_platform_entries_have_required_fields(self, tool_functions):
        """Each platform entry has required fields."""
        fn = tool_functions["list_available"]
        result = fn(category="platforms")

        required_fields = {"name", "display_name", "category", "available", "supports_sql"}
        for platform in result["platforms"]:
            assert required_fields.issubset(platform.keys()), f"Missing fields in {platform['name']}"

    def test_duckdb_is_available(self, tool_functions):
        """DuckDB should be available in the test environment."""
        fn = tool_functions["list_available"]
        result = fn(category="platforms")

        duckdb_entries = [p for p in result["platforms"] if p["name"] == "duckdb"]
        assert len(duckdb_entries) == 1
        assert duckdb_entries[0]["available"] is True

    def test_summary_has_counts(self, tool_functions):
        """Summary section has aggregate counts."""
        fn = tool_functions["list_available"]
        result = fn(category="platforms")

        assert "summary" in result
        assert "available" in result["summary"]
        assert "sql_platforms" in result["summary"]
        assert "dataframe_platforms" in result["summary"]


# ---------------------------------------------------------------------------
# list_available with category="benchmarks" (consolidated list_benchmarks)
# ---------------------------------------------------------------------------


class TestListBenchmarksTool:
    """Tests for list_available with category='benchmarks' (consolidated list_benchmarks)."""

    def test_returns_benchmarks_list(self, tool_functions):
        """Response contains benchmarks list."""
        fn = tool_functions["list_available"]
        result = fn(category="benchmarks")

        assert "benchmarks" in result
        assert "count" in result
        assert result["count"] > 0

    def test_tpch_is_listed(self, tool_functions):
        """TPC-H is in the benchmarks list."""
        fn = tool_functions["list_available"]
        result = fn(category="benchmarks")

        names = [b["name"] for b in result["benchmarks"]]
        assert "tpch" in names

    def test_benchmark_entries_have_required_fields(self, tool_functions):
        """Each benchmark entry has required structure."""
        fn = tool_functions["list_available"]
        result = fn(category="benchmarks")

        for bm in result["benchmarks"]:
            assert "name" in bm
            assert "display_name" in bm
            assert "query_count" in bm
            assert "scale_factors" in bm

    def test_categories_grouping(self, tool_functions):
        """Response includes category grouping."""
        fn = tool_functions["list_available"]
        result = fn(category="benchmarks")

        assert "categories" in result
        assert isinstance(result["categories"], dict)


# ---------------------------------------------------------------------------
# get_benchmark_info tool
# ---------------------------------------------------------------------------


class TestGetBenchmarkInfoTool:
    """Tests for the get_benchmark_info tool handler."""

    def test_tpch_info_returns_details(self, tool_functions):
        """TPC-H benchmark info returns detailed response."""
        fn = tool_functions["get_benchmark_info"]
        result = fn(benchmark="tpch")

        assert "error" not in result
        assert result.get("name") == "tpch" or result.get("benchmark") == "tpch"

    def test_unknown_benchmark_returns_error(self, tool_functions):
        """Unknown benchmark returns error."""
        fn = tool_functions["get_benchmark_info"]
        result = fn(benchmark="nonexistent")

        assert "error" in result


# ---------------------------------------------------------------------------
# run_benchmark tool - error paths (no actual execution)
# ---------------------------------------------------------------------------


class TestRunBenchmarkToolErrors:
    """Tests for run_benchmark error handling (no actual benchmark execution)."""

    def test_unknown_benchmark_returns_not_found(self, tool_functions):
        """Unknown benchmark returns RESOURCE_NOT_FOUND error."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="nonexistent_bench", scale_factor=0.01)

        assert result.get("status") == "failed"
        assert result["error_code"] == "RESOURCE_NOT_FOUND"

    def test_unknown_platform_returns_error(self, tool_functions):
        """Unknown platform returns VALIDATION_UNSUPPORTED_PLATFORM error."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="nonexistent_platform", benchmark="tpch", scale_factor=0.01)

        assert result.get("status") == "failed"
        # Either platform validation or adapter creation fails
        assert "error" in result or "error_code" in result

    def test_response_has_execution_id(self, tool_functions):
        """All responses include an execution_id."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="nonexistent", scale_factor=0.01)

        assert "execution_id" in result
        assert result["execution_id"].startswith("mcp_")

    def test_not_found_error_has_error_code(self, tool_functions):
        """Not-found errors include proper error_code."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="nonexistent", scale_factor=0.01)

        assert result["error_code"] == "RESOURCE_NOT_FOUND"
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# run_benchmark tool - successful execution (mocked)
# ---------------------------------------------------------------------------


class TestRunBenchmarkToolSuccess:
    """Tests for run_benchmark success path with mocked execution."""

    def test_successful_run_returns_completed(self, tool_functions, tmp_path):
        """Successful benchmark run returns completed status with result_file."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        result_path = tmp_path / "result.json"
        write_v2_result_file(result_path, execution_id="mcp_test", timestamp="2026-01-01T00:00:00")

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01)

        assert result["mcp_metadata"]["status"] == "completed"
        assert result["platform"]["name"] == "duckdb"
        assert result["benchmark"]["id"] == "tpch"
        assert result["summary"]["queries"]["total"] == 22
        assert result["summary"]["queries"]["passed"] == 22
        assert result["mcp_metadata"]["result_file"] == str(result_path)

    def test_query_subset_forwarded(self, tool_functions):
        """Query subset string is parsed and forwarded."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.total_queries = 3
        mock_result.successful_queries = 3
        mock_result.failed_queries = 0
        mock_result.total_execution_time = 1.0
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result
        mock_bm_class = MagicMock(return_value=mock_instance)

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
        ):
            fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, queries="1,6,17")

            call_kwargs = mock_instance.run_with_platform.call_args[1]
            assert call_kwargs["query_subset"] == ["1", "6", "17"]

    def test_result_exported_with_execution_id(self, tool_functions):
        """Execution ID is set on result before export."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.total_queries = 1
        mock_result.successful_queries = 1
        mock_result.failed_queries = 0
        mock_result.total_execution_time = 1.0
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": Path("/tmp/result.json")}

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            fn(platform="duckdb", benchmark="tpch", scale_factor=0.01)

        # Verify execution_id was set on the result object before export
        assert mock_result.execution_id.startswith("mcp_")
        # Verify exporter was called with the result
        mock_exporter.export_result.assert_called_once_with(mock_result, formats=["json"])

    def test_export_failure_does_not_break_response(self, tool_functions):
        """Export failure is gracefully handled - response still returned."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.total_queries = 5
        mock_result.successful_queries = 5
        mock_result.failed_queries = 0
        mock_result.total_execution_time = 2.0
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        mock_exporter = MagicMock()
        mock_exporter.export_result.side_effect = OSError("disk full")

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01)

        # Response still succeeds without result_file
        assert result["mcp_metadata"]["status"] == "completed"
        assert result["mcp_metadata"]["result_file"] is None

    def test_all_query_results_included(self, tool_functions, tmp_path):
        """All query results are returned without truncation."""
        fn = tool_functions["run_benchmark"]

        # Simulate 99 queries (TPC-DS)
        mock_result = MagicMock()
        mock_result.query_results = [
            {"query_id": f"Q{i}", "execution_time": 0.1 * i, "status": "success"} for i in range(1, 100)
        ]

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        tpcds_queries = [
            {"id": str(i), "ms": 100 + i, "status": "SUCCESS", "run_type": "measurement"} for i in range(1, 100)
        ]
        result_path = tmp_path / "result.json"
        write_v2_result_file(
            result_path,
            execution_id="mcp_test",
            timestamp="2026-01-01T00:00:00",
            benchmark_id="tpcds",
            benchmark_name="TPC-DS",
            total_queries=99,
            passed_queries=99,
            queries=tpcds_queries,
        )

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            result = fn(platform="duckdb", benchmark="tpcds", scale_factor=0.01)

        assert result["mcp_metadata"]["status"] == "completed"
        assert len(result["queries"]) == 99
        # Verify first and last query
        assert result["queries"][0]["id"] == "1"
        assert result["queries"][98]["id"] == "99"

    def test_dataframe_platform_uses_dataframe_runner(self, tool_functions, tmp_path):
        """DataFrame platforms use the dedicated dataframe runner."""
        fn = tool_functions["run_benchmark"]

        mock_df_result = MagicMock()
        mock_df_result.query_results = [
            {"query_id": f"Q{i}", "execution_time": 0.1, "status": "SUCCESS"} for i in range(1, 23)
        ]

        polars_queries = [
            {"id": str(i), "ms": 100 + i, "status": "SUCCESS", "run_type": "measurement"} for i in range(1, 23)
        ]
        result_path = tmp_path / "result.json"
        write_v2_result_file(
            result_path,
            execution_id="mcp_test",
            timestamp="2026-01-01T00:00:00",
            platform="polars-df",
            queries=polars_queries,
        )

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        # Create mock benchmark instance that returns our mock result
        mock_benchmark_instance = MagicMock()
        mock_benchmark_instance.run_with_platform.return_value = mock_df_result

        mock_benchmark_class = MagicMock(return_value=mock_benchmark_instance)

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.platforms.is_dataframe_platform", return_value=True),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_benchmark_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            result = fn(platform="polars-df", benchmark="tpch", scale_factor=0.01)

        # Verify unified run_with_platform was called (DataFrame adapters now use same path)
        mock_benchmark_instance.run_with_platform.assert_called_once()

        assert result["mcp_metadata"]["status"] == "completed"
        assert result["platform"]["name"] == "polars-df"
        assert result["summary"]["queries"]["total"] == 22


# ---------------------------------------------------------------------------
# Results tools - _get_results_impl
# ---------------------------------------------------------------------------


class TestGetResultsImpl:
    """Tests for the results retrieval implementation."""

    def test_missing_file_returns_not_found(self):
        """Non-existent result file returns RESOURCE_NOT_FOUND."""
        from benchbox.mcp.tools.results import _get_results_impl

        result = _get_results_impl("missing_file.json", results_dir=Path("/nonexistent/path"))

        assert result["error"] is True
        assert result["error_code"] == "RESOURCE_NOT_FOUND"

    def test_valid_json_file_returns_data(self, tmp_path):
        """Valid JSON result file returns parsed data."""
        from benchbox.mcp.tools.results import _get_results_impl

        result_file = tmp_path / "test_run.json"
        write_v2_result_file(
            result_file,
            execution_id="test_run",
            timestamp="2026-01-01T00:00:00",
            total_queries=2,
            passed_queries=2,
            total_ms=5.0,
        )

        result = _get_results_impl("test_run.json", results_dir=tmp_path)

        assert "error" not in result
        assert result["benchmark"]["id"] == "tpch"
        assert result["benchmark"]["scale_factor"] == 0.01
        assert result["summary"]["timing"]["total_ms"] == 5.0

    def test_invalid_json_returns_format_error(self, tmp_path):
        """Malformed JSON returns RESOURCE_INVALID_FORMAT."""
        from benchbox.mcp.tools.results import _get_results_impl

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")

        result = _get_results_impl("bad.json", results_dir=tmp_path)

        assert result["error"] is True
        assert result["error_code"] == "RESOURCE_INVALID_FORMAT"

    def test_includes_query_results_when_requested(self, tmp_path):
        """Query results are included when include_queries=True."""
        from benchbox.mcp.tools.results import _get_results_impl

        query_list = [
            {"id": "1", "ms": 100, "status": "SUCCESS", "run_type": "measurement"},
            {"id": "6", "ms": 50, "status": "SUCCESS", "run_type": "measurement"},
        ]
        result_file = tmp_path / "with_queries.json"
        write_v2_result_file(
            result_file,
            execution_id="test_run",
            timestamp="2026-01-01T00:00:00",
            total_duration_ms=150,
            query_time_ms=150,
            total_queries=2,
            passed_queries=2,
            total_ms=150,
            queries=query_list,
        )

        result = _get_results_impl("with_queries.json", include_queries=True, results_dir=tmp_path)

        assert len(result["queries"]) == 2
        assert result["queries"][0]["id"] == "1"

    def test_auto_appends_json_extension(self, tmp_path):
        """Files without .json extension get it appended."""
        from benchbox.mcp.tools.results import _get_results_impl

        result_file = tmp_path / "run.json"
        write_v2_result_file(
            result_file,
            execution_id="test_run",
            timestamp="2026-01-01T00:00:00",
            total_duration_ms=0,
            query_time_ms=0,
            total_queries=0,
            passed_queries=0,
            total_ms=0,
        )

        result = _get_results_impl("run", results_dir=tmp_path)

        assert "error" not in result


# ---------------------------------------------------------------------------
# Discovery tool: check_dependencies
# ---------------------------------------------------------------------------


class TestCheckDependenciesTool:
    """Tests for the check_dependencies tool handler."""

    def test_returns_platform_status(self, tool_functions):
        """check_dependencies returns dependency status for platforms."""
        fn = tool_functions["check_dependencies"]
        result = fn()

        # Should return some platform info
        assert isinstance(result, dict)

    def test_specific_platform_check(self, tool_functions):
        """Checking a specific platform returns focused results."""
        fn = tool_functions["check_dependencies"]
        result = fn(platform="duckdb")

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Discovery tool: system_profile
# ---------------------------------------------------------------------------


class TestSystemProfileTool:
    """Tests for the system_profile tool handler."""

    def test_returns_system_info(self, tool_functions):
        """system_profile returns hardware and software info."""
        fn = tool_functions["system_profile"]
        result = fn()

        assert isinstance(result, dict)
        # Should have CPU, memory, or similar system info
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Mode parameter validation tests
# ---------------------------------------------------------------------------


class TestModeParameterValidation:
    """Tests for the mode parameter in MCP tools."""

    def test_validate_config_with_valid_sql_mode(self, tool_functions):
        """run_benchmark with validate_only accepts sql mode for SQL-capable platforms."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, mode="sql", validate_only=True)

        assert result["valid"] is True
        assert result["execution_mode"] == "sql"

    def test_validate_config_with_valid_dataframe_mode(self, tool_functions):
        """run_benchmark with validate_only accepts dataframe mode for DataFrame-capable platforms."""
        fn = tool_functions["run_benchmark"]
        # polars only supports dataframe mode
        result = fn(platform="polars", benchmark="tpch", scale_factor=1.0, mode="dataframe", validate_only=True)

        assert result["valid"] is True
        assert result["execution_mode"] == "dataframe"

    def test_validate_config_with_invalid_mode_value(self, tool_functions):
        """run_benchmark with validate_only rejects invalid mode values."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, mode="invalid", validate_only=True)

        assert result["valid"] is False
        assert any("Invalid mode" in e for e in result["errors"])

    def test_validate_config_unsupported_mode_for_platform(self, tool_functions):
        """run_benchmark with validate_only returns error when platform doesn't support the requested mode."""
        fn = tool_functions["run_benchmark"]
        # sqlite only supports SQL mode, not dataframe
        result = fn(platform="sqlite", benchmark="tpch", scale_factor=1.0, mode="dataframe", validate_only=True)

        assert result["valid"] is False
        assert any("doesn't support dataframe mode" in e for e in result["errors"])

    def test_validate_config_default_mode_when_not_specified(self, tool_functions):
        """run_benchmark with validate_only uses platform default mode when not specified."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, validate_only=True)

        # DuckDB defaults to SQL mode
        assert result["execution_mode"] == "sql"

    def test_validate_config_returns_execution_mode(self, tool_functions):
        """run_benchmark with validate_only response includes execution_mode field."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, validate_only=True)

        assert "execution_mode" in result

    def test_run_benchmark_rejects_unsupported_mode(self, tool_functions):
        """run_benchmark returns error for unsupported mode."""
        fn = tool_functions["run_benchmark"]
        # sqlite doesn't support dataframe mode
        result = fn(platform="sqlite", benchmark="tpch", scale_factor=0.01, mode="dataframe")

        assert result.get("status") == "failed"
        assert result.get("error_code") == "VALIDATION_UNSUPPORTED_MODE"
        assert "execution_id" in result

    def test_run_benchmark_accepts_valid_mode(self, tool_functions, tmp_path):
        """run_benchmark accepts valid mode for capable platforms."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        result_path = tmp_path / "result.json"
        write_v2_result_file(result_path, execution_id="mcp_test", timestamp="2026-01-01T00:00:00")

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, mode="sql")

        assert result["mcp_metadata"]["status"] == "completed"
        assert result["mcp_metadata"]["execution_mode"] == "sql"

    def test_dry_run_with_mode_parameter(self, tool_functions):
        """run_benchmark with dry_run accepts and uses mode parameter."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, mode="sql", dry_run=True)

        # Should succeed and show execution_mode in response
        assert result["status"] == "dry_run"
        assert result["execution_mode"] == "sql"

    def test_dry_run_rejects_unsupported_mode(self, tool_functions):
        """run_benchmark with dry_run returns error for unsupported mode."""
        fn = tool_functions["run_benchmark"]
        # sqlite doesn't support dataframe mode
        result = fn(platform="sqlite", benchmark="tpch", scale_factor=0.01, mode="dataframe", dry_run=True)

        assert result.get("status") == "error"
        assert result.get("error_code") == "VALIDATION_UNSUPPORTED_MODE"

    def test_mode_case_insensitive(self, tool_functions):
        """Mode parameter is case-insensitive."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, mode="SQL", validate_only=True)

        assert result["valid"] is True
        assert result["execution_mode"] == "sql"

    def test_dual_mode_platform_accepts_both_modes(self, tool_functions):
        """Dual-mode platforms (like datafusion) accept both sql and dataframe modes."""
        fn = tool_functions["run_benchmark"]

        # Test SQL mode
        result_sql = fn(platform="datafusion", benchmark="tpch", scale_factor=1.0, mode="sql", validate_only=True)
        assert result_sql["valid"] is True
        assert result_sql["execution_mode"] == "sql"

        # Test DataFrame mode
        result_df = fn(platform="datafusion", benchmark="tpch", scale_factor=1.0, mode="dataframe", validate_only=True)
        assert result_df["valid"] is True
        assert result_df["execution_mode"] == "dataframe"

    def test_validate_config_accepts_data_only_mode(self, tool_functions):
        """run_benchmark with validate_only accepts data_only mode for any platform."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, mode="data_only", validate_only=True)

        assert result["valid"] is True
        assert result["execution_mode"] == "data_only"

    def test_validate_config_accepts_datagen_alias(self, tool_functions):
        """run_benchmark with validate_only accepts 'datagen' as alias for data_only mode."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=1.0, mode="datagen", validate_only=True)

        assert result["valid"] is True
        assert result["execution_mode"] == "data_only"

    def test_run_benchmark_data_only_mode(self, tool_functions, tmp_path):
        """run_benchmark with data_only mode generates data without running queries."""
        fn = tool_functions["run_benchmark"]

        mock_bm = MagicMock()
        mock_bm.generate_data = MagicMock()
        mock_bm_class = MagicMock(return_value=mock_bm)

        with patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class):
            result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, mode="data_only")

        assert result["mcp_metadata"]["status"] == "completed"
        assert result["mcp_metadata"]["execution_mode"] == "data_only"
        assert "data_generation" in result
        assert result["data_generation"]["benchmark"] == "tpch"
        assert result["data_generation"]["scale_factor"] == 0.01

    def test_dry_run_accepts_data_only_mode(self, tool_functions):
        """run_benchmark with dry_run accepts data_only mode."""
        fn = tool_functions["run_benchmark"]
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, mode="data_only", dry_run=True)

        assert result["status"] == "dry_run"
        assert result["execution_mode"] == "data_only"


# ---------------------------------------------------------------------------
# Phases to test_execution_type mapping tests
# ---------------------------------------------------------------------------


class TestPhasesMapping:
    """Tests for phases to test_execution_type mapping."""

    def test_power_phase_maps_to_power_type(self):
        """Phases containing 'power' should map to power test_execution_type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type(["power"]) == "power"
        assert _map_phases_to_test_execution_type(["load", "power"]) == "power"
        assert _map_phases_to_test_execution_type(["warmup", "power"]) == "power"

    def test_throughput_phase_maps_to_throughput_type(self):
        """Phases containing only 'throughput' should map to throughput type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type(["throughput"]) == "throughput"
        assert _map_phases_to_test_execution_type(["load", "throughput"]) == "throughput"

    def test_combined_phases_map_to_combined_type(self):
        """All three query phases together should map to combined type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type(["power", "throughput", "maintenance"]) == "combined"

    def test_load_only_phase_maps_to_load_only_type(self):
        """Load-only phase should map to load_only type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type(["load"]) == "load_only"

    def test_generate_only_phase_maps_to_data_only_type(self):
        """Generate-only phase should map to data_only type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type(["generate"]) == "data_only"

    def test_empty_phases_maps_to_standard(self):
        """Empty or unrecognized phases should map to standard type."""
        from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

        assert _map_phases_to_test_execution_type([]) == "standard"
        assert _map_phases_to_test_execution_type(["warmup"]) == "standard"

    def test_run_benchmark_passes_test_execution_type(self, tool_functions, tmp_path):
        """run_benchmark should pass test_execution_type based on phases."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        result_path = tmp_path / "result.json"
        write_v2_result_file(result_path, execution_id="test", timestamp="2026-01-01T00:00:00")

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, phases="power")

        # Verify run_with_platform was called with test_execution_type="power"
        mock_instance.run_with_platform.assert_called_once()
        call_kwargs = mock_instance.run_with_platform.call_args[1]
        assert call_kwargs.get("test_execution_type") == "power"

    def test_run_benchmark_passes_mode_to_adapter(self, tool_functions, tmp_path):
        """run_benchmark should pass mode to _get_platform_adapter for correct adapter selection."""
        fn = tool_functions["run_benchmark"]

        mock_result = MagicMock()
        mock_result.query_results = []

        mock_instance = MagicMock()
        mock_instance.run_with_platform.return_value = mock_result

        mock_bm_class = MagicMock(return_value=mock_instance)

        result_path = tmp_path / "result.json"
        write_v2_result_file(
            result_path,
            execution_id="test",
            timestamp="2026-01-01T00:00:00",
            platform="datafusion",
        )

        mock_exporter = MagicMock()
        mock_exporter.export_result.return_value = {"json": result_path}

        mock_get_adapter = MagicMock()

        with (
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter", mock_get_adapter),
            patch("benchbox.mcp.tools.benchmark.get_benchmark_class", return_value=mock_bm_class),
            patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        ):
            fn(platform="datafusion", benchmark="tpch", scale_factor=0.01, mode="dataframe")

        # Verify _get_platform_adapter was called with mode="dataframe"
        mock_get_adapter.assert_called_once()
        call_kwargs = mock_get_adapter.call_args[1]
        assert call_kwargs.get("mode") == "dataframe"
