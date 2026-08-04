"""MCP must reject an unknown benchmark phase instead of dropping it.

`run_benchmark(phases=...)` accepted any string and passed it through, so a
typo such as ``load,lodad`` ran only the load phase and reported nothing. The CLI
has always rejected unknown phases; `one-engine-unify-constants` closed the gap
against the same shared list.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.constants import VALID_PHASES

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

pytest.importorskip("mcp", reason="MCP SDK not installed. Install with: uv add benchbox --extra mcp")


class TestRunSurfaceRejectsUnknownPhases:
    """The gap this item closed: MCP silently dropped a mistyped phase."""

    def test_run_benchmark_rejects_a_bogus_phase(self, tmp_path):
        from benchbox.mcp import create_server
        from tests.unit.mcp.public_api import call_tool

        server = create_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")
        response = call_tool(
            server, "run_benchmark", platform="duckdb", benchmark="tpch", phases="load,lodad", scale_factor=0.01
        )

        assert response["error"] is True
        assert response["status"] == "failed"
        assert "lodad" in response["message"]
        assert set(response["details"]["valid_phases"]) == set(VALID_PHASES)

    def test_a_bogus_phase_is_rejected_before_any_execution(self, tmp_path):
        """Rejection must happen at admission, not after data generation."""
        from unittest.mock import patch

        from benchbox.mcp import create_server
        from benchbox.mcp.tools import benchmark as benchmark_tools
        from tests.unit.mcp.public_api import call_tool

        server = create_server(results_dir=tmp_path, charts_dir=tmp_path, log_level="ERROR")
        with patch.object(benchmark_tools, "_run_benchmark_impl") as run_impl:
            call_tool(server, "run_benchmark", platform="duckdb", benchmark="tpch", phases="lodad", scale_factor=0.01)

        run_impl.assert_not_called()
