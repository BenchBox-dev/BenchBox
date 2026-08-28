"""Tests for the opt-in statistics phase exposed through the MCP run_benchmark tool.

Covers benchbox/mcp/tools/benchmark.py's handling of `statistics` in the
`phases` argument: threading `gather_statistics`/`benchmark_name` into
`run_with_platform`, and pass-through of the resulting `phases.statistics`
block in the MCP response.

The per-benchmark `supports_statistics_phase` registry gate itself is
exercised at the adapter level in tests/unit/platforms/test_base_adapter.py
(added with PR #980, e.g. test_run_statistics_phase_skips_benchmark_without_opt_in
and test_run_statistics_phase_completed_for_opted_in_benchmark). This file
locks down that the MCP layer forwards the flag correctly (without
bypassing that gate) and leaves non-statistics requests byte-identical.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.result_dict_fixtures import write_v2_result_file

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP server requires Python 3.10+"),
]


def _get_tool_functions() -> dict[str, Any]:
    """Create a fresh MCP server and expose public tool invokers."""
    from benchbox.mcp import create_server
    from tests.unit.mcp.public_api import get_tool_functions

    server = create_server()
    return get_tool_functions(server)


@pytest.fixture(scope="module")
def tool_functions() -> dict[str, Any]:
    """Module-scoped fixture for tool function lookup."""
    return _get_tool_functions()


def _mock_run(
    tool_functions: dict[str, Any],
    tmp_path: Path,
    *,
    phases: str,
    extra_result_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call run_benchmark with the shared core service mocked."""
    fn = tool_functions["run_benchmark"]

    mock_result = MagicMock()
    mock_result.query_results = []

    captured: dict[str, Any] = {}

    def execute_run(**kwargs):
        config = kwargs["config"]
        captured.update(config.options or {})
        captured["test_execution_type"] = config.test_execution_type
        return mock_result

    result_path = tmp_path / "result.json"
    write_v2_result_file(
        result_path,
        execution_id="mcp_test",
        timestamp="2026-01-01T00:00:00",
        **(extra_result_kwargs or {}),
    )

    mock_exporter = MagicMock()
    mock_exporter.export_result.return_value = {"json": result_path}

    with (
        patch("benchbox.mcp.tools.benchmark._get_platform_adapter"),
        patch("benchbox.mcp.tools.benchmark.get_public_benchmark_class", return_value=MagicMock),
        patch("benchbox.mcp.tools.benchmark.ResultExporter", return_value=mock_exporter),
        patch("benchbox.core.run_service.execute_run", side_effect=execute_run),
    ):
        result = fn(platform="duckdb", benchmark="tpch", scale_factor=0.01, phases=phases)

    return result, captured


class TestStatisticsPhaseFlagThreading:
    """gather_statistics/statistics_benchmark_name threading into core config."""

    def test_statistics_in_phases_forwards_gather_statistics_flag(self, tool_functions, tmp_path):
        """`statistics` in phases sets gather_statistics=True and statistics_benchmark_name
        for the registry gate."""
        _, call_kwargs = _mock_run(tool_functions, tmp_path, phases="load,statistics,power")

        assert call_kwargs.get("gather_statistics") is True
        assert call_kwargs.get("statistics_benchmark_name") == "tpch"

    def test_statistics_never_sets_benchmark_name(self, tool_functions, tmp_path):
        """Requesting statistics must not set `benchmark_name` itself: that key also
        drives power/throughput/maintenance/combined harness routing (and, in
        run_enhanced_benchmark, dialect selection / validation gating), so setting it
        only here would make a stats-opt-in run incomparable to the same run without
        the opt-in."""
        _, call_kwargs = _mock_run(tool_functions, tmp_path, phases="load,statistics,power")

        assert "benchmark_name" not in call_kwargs

    def test_statistics_absent_from_phases_omits_the_flag(self, tool_functions, tmp_path):
        """Callers that don't request statistics get an unchanged run_config (must_preserve)."""
        _, call_kwargs = _mock_run(tool_functions, tmp_path, phases="load,power")

        assert "gather_statistics" not in call_kwargs
        assert "statistics_benchmark_name" not in call_kwargs
        assert "benchmark_name" not in call_kwargs

    def test_statistics_does_not_change_test_execution_type(self, tool_functions, tmp_path):
        """statistics is not a query phase; test_execution_type mapping is unaffected."""
        _, call_kwargs = _mock_run(tool_functions, tmp_path, phases="load,statistics,power")

        assert call_kwargs.get("test_execution_type") == "power"


class TestStatisticsPhaseResponsePassThrough:
    """phases.statistics pass-through from the exported result into the MCP response.

    These are deliberately shallow pass-through checks: the core run service is
    mocked and the exported result file is hand-written, so they only prove the MCP
    response carries through whatever ``phases`` the exporter produced. They do NOT
    exercise the ``supports_statistics_phase`` registry gate or ``run_statistics_phase``
    (those run inside the real adapter and are covered in
    tests/unit/platforms/test_base_adapter.py). Their value is guarding against the
    MCP layer dropping or mangling the phases block on the way to the response.
    """

    def test_response_carries_through_a_statistics_block_when_present(self, tool_functions, tmp_path):
        """A result whose exported phases include statistics surfaces it in the response."""
        result, _ = _mock_run(
            tool_functions,
            tmp_path,
            phases="load,statistics,power",
            extra_result_kwargs={
                "phases": {
                    "statistics": {"status": "COMPLETED", "stats_mode": "explicit", "tables_analyzed": 8},
                }
            },
        )

        assert result["phases"]["statistics"]["stats_mode"] == "explicit"

    def test_response_has_no_statistics_block_when_result_omits_it(self, tool_functions, tmp_path):
        """A result without a statistics phase (e.g. the phase never ran) yields no phases.statistics."""
        result, _ = _mock_run(
            tool_functions,
            tmp_path,
            phases="load,statistics,power",
            extra_result_kwargs={
                "phases": {
                    "power_test": {"status": "COMPLETED"},
                }
            },
        )

        assert "statistics" not in result["phases"]
