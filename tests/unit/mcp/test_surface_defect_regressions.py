"""Regressions for the incidental MCP defects found in the 2026-08-04 review.

Each test corresponds to one defect and fails on the unfixed tree.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

pytest.importorskip("mcp", reason="MCP SDK not installed. Install with: uv add benchbox --extra mcp")


class TestValidateResultsNotFoundError:
    """Defect 1: make_not_found_error was called as (resource_id, results_dir)."""

    def test_not_found_names_a_resource_type_not_the_filename(self, tmp_path: Path):
        from benchbox.mcp import create_server
        from tests.unit.mcp.public_api import call_tool

        server = create_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")
        response = call_tool(server, "validate_results", result_file="myrun.json")

        assert response["error"] is True
        assert response["details"]["resource_type"] == "result_file"
        assert response["details"]["requested"] == "myrun.json"
        assert response["message"] == "Result_file 'myrun.json' not found"
        # The suggestion must name a tool that exists.
        assert response["suggestion"] == 'Use get_results(format="list") to see available result files'

    def test_not_found_does_not_leak_the_server_results_root(self, tmp_path: Path):
        """The old binding passed the configured results dir as the resource id."""
        from benchbox.mcp import create_server
        from tests.unit.mcp.public_api import call_tool

        server = create_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")
        response = call_tool(server, "validate_results", result_file="myrun.json")

        assert str(tmp_path) not in repr(response)


class TestQueryDetailsVisibilityMatrix:
    """Defect 4: get_query_details against the benchmark visibility matrix.

    The ratified matrix (docs/reference/public-contracts.md, "Benchmark
    Visibility Policy") keeps internal benchmarks addressable by explicit ID on
    this tool but withholds their support-status claim. These tests pin that row
    so the tool cannot drift toward either exposing the claim or hiding the
    benchmark outright.
    """

    def test_public_benchmark_details_carry_support_status(self):
        from benchbox.core.benchmark_registry import get_all_benchmarks
        from benchbox.mcp.tools.benchmark import _build_query_details_benchmark_info

        meta = get_all_benchmarks()["tpch"]
        info = _build_query_details_benchmark_info("tpch", meta)

        assert info["support_status"] == meta["support_status"]

    def test_internal_benchmark_details_omit_support_status(self):
        from benchbox.core.benchmark_registry import get_all_benchmarks, get_benchmark_surface
        from benchbox.mcp.tools.benchmark import _build_query_details_benchmark_info

        benchmarks = get_all_benchmarks()
        internal = sorted(b for b in benchmarks if get_benchmark_surface(b) != "public")
        assert internal, "the matrix row is vacuous without at least one internal benchmark"

        for benchmark in internal:
            info = _build_query_details_benchmark_info(benchmark, benchmarks[benchmark])
            assert set(info) == {"display_name", "category"}, benchmark

    def test_internal_benchmarks_stay_addressable_by_explicit_id(self, tmp_path: Path):
        """ "Runnable/readable by explicit ID" is the matrix's internal row."""
        from benchbox.core.benchmark_registry import get_all_benchmarks, get_benchmark_surface
        from benchbox.mcp import create_server
        from tests.unit.mcp.public_api import call_tool

        internal = sorted(b for b in get_all_benchmarks() if get_benchmark_surface(b) != "public")
        server = create_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")

        for benchmark in internal:
            response = call_tool(server, "get_query_details", benchmark=benchmark, query_id="1")
            # It may fail for benchmark-specific reasons, but never as "unknown
            # benchmark" -- that would be the discovery gate leaking into this tool.
            assert response.get("details", {}).get("resource_type") != "benchmark", benchmark

    def test_every_registered_benchmark_matches_its_matrix_row(self):
        """The gate is driven by `surface`, not by a hand-maintained list."""
        from benchbox.core.benchmark_registry import get_all_benchmarks, get_benchmark_surface
        from benchbox.mcp.tools.benchmark import _build_query_details_benchmark_info

        for benchmark, meta in get_all_benchmarks().items():
            info = _build_query_details_benchmark_info(benchmark, meta)
            expected_public = get_benchmark_surface(benchmark) == "public"
            assert ("support_status" in info) is expected_public, benchmark


class TestRemoteModeAnonymization:
    """Defect 5: exporters were pinned to anonymize=False in every mode."""

    @staticmethod
    def _security_runtime(tmp_path: Path):
        from benchbox.mcp.security import RemoteSecurityRuntime
        from tests.integration.mcp._security import write_security_config

        config = write_security_config(
            tmp_path,
            tokens={"token": ("tenant", ("benchbox:read", "benchbox:execute"))},
        )
        return RemoteSecurityRuntime.from_file(config)

    def test_local_stdio_server_does_not_anonymize(self, tmp_path: Path):
        import benchbox.mcp.server as server_module

        with (
            patch.object(server_module, "register_benchmark_tools") as benchmark_tools,
            patch.object(server_module, "register_analytics_tools") as analytics_tools,
        ):
            server_module.create_benchbox_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")

        assert benchmark_tools.call_args.kwargs["anonymize_results"] is False
        assert analytics_tools.call_args.kwargs["anonymize_results"] is False

    def test_remote_authenticated_server_anonymizes(self, tmp_path: Path):
        import benchbox.mcp.server as server_module

        with (
            patch.object(server_module, "register_benchmark_tools") as benchmark_tools,
            patch.object(server_module, "register_analytics_tools") as analytics_tools,
        ):
            server_module.create_benchbox_server(
                results_dir=tmp_path,
                charts_dir=tmp_path,
                log_level="ERROR",
                remote_security=self._security_runtime(tmp_path),
            )

        assert benchmark_tools.call_args.kwargs["anonymize_results"] is True
        assert analytics_tools.call_args.kwargs["anonymize_results"] is True

    def test_durable_job_execution_anonymizes(self, tmp_path: Path):
        """Durable jobs exist only under a remote policy, so the worker is remote."""
        from benchbox.mcp.jobs import DurableJobWorker, JobRecord

        record = JobRecord(
            execution_id="mcp_job_test",
            principal_id="p",
            state="running",
            request={"platform": "duckdb", "benchmark": "tpch"},
            idempotency_key=None,
            attempts=1,
            lease_owner="w",
            lease_expires_at=None,
            lease_version=1,
            lease_generation=0,
            cancel_requested=False,
            artifact_path=None,
            error_code=None,
            created_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
            completed_at=None,
        )

        with patch("benchbox.mcp.jobs._run_benchmark_impl", return_value={}) as run_impl:
            DurableJobWorker._execute_benchmark(record, tmp_path)

        assert run_impl.call_args.kwargs["anonymize"] is True

    def test_compare_results_threads_the_anonymization_decision(self, tmp_path: Path):
        from benchbox.mcp.tools import analytics as analytics_module

        with patch.object(analytics_module, "ResultExporter") as exporter_cls:
            analytics_module._compare_results_impl("a.json", "b.json", 10.0, tmp_path, anonymize=True)

        assert exporter_cls.call_args.kwargs["anonymize"] is True


class TestChartOutputContract:
    """Defect 3: the docstring promised ANSI colors the renderer never emits."""

    def test_renderer_is_constructed_without_color(self):
        from benchbox.mcp.tools import visualization as visualization_module

        source = inspect.getsource(visualization_module._generate_ascii_chart)

        assert "ChartOptions(use_color=False)" in source

    def test_generate_chart_docstring_matches_the_renderer(self):
        from benchbox.mcp.tools import visualization as visualization_module

        source = inspect.getsource(visualization_module.register_visualization_tools)

        assert "ANSI colors for terminal display" not in source
        assert "ANSI-color-free" in source
