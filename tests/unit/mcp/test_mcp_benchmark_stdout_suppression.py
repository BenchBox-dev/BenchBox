"""Regression tests for MCP benchmark stdout suppression boundaries."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.utils.clock import mono_time

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_run_benchmark_impl_suppresses_transitive_stdout() -> None:
    """_run_benchmark_impl should suppress print() leakage from benchmark execution."""
    from benchbox.mcp.tools.benchmark import _run_benchmark_impl

    class DummyBenchmark:
        def __init__(self, scale_factor: float) -> None:
            self.scale_factor = scale_factor

        def run_with_platform(self, *_args, **_kwargs):
            print("LEAK: benchmark run output")
            return None

    captured = io.StringIO()
    original_stdout = sys.stdout
    try:
        sys.stdout = captured
        with (
            patch("benchbox.mcp.tools.benchmark.get_all_benchmarks", return_value={"tpch": {"name": "tpch"}}),
            patch("benchbox.mcp.tools.benchmark.get_public_benchmark_class", return_value=DummyBenchmark),
            patch("benchbox.mcp.tools.benchmark._get_platform_adapter", return_value=object()),
        ):
            response = _run_benchmark_impl(
                "duckdb", "tpch", 0.01, None, "load,power", "sql", results_dir=Path("benchmark_runs/results")
            )
        assert response["mcp_metadata"]["status"] in {"completed", "no_results"}
        assert captured.getvalue() == ""
    finally:
        sys.stdout = original_stdout


def test_generate_data_impl_suppresses_transitive_stdout(tmp_path: Path) -> None:
    """_generate_data_impl should suppress print() leakage from benchmark generation."""
    from benchbox.mcp.tools.benchmark import _generate_data_impl

    class DummyBenchmark:
        def __init__(self, scale_factor: float) -> None:
            self.scale_factor = scale_factor

        def generate_data(self, **_kwargs):
            print("LEAK: data generation output")
            return []

    captured = io.StringIO()
    original_stdout = sys.stdout
    try:
        sys.stdout = captured
        with patch("benchbox.mcp.tools.benchmark.get_benchmark_runs_datagen_path", return_value=tmp_path):
            response = _generate_data_impl("tpch", DummyBenchmark, 0.01, "mcp_test_id", mono_time())
        assert response["mcp_metadata"]["status"] == "completed"
        assert captured.getvalue() == ""
    finally:
        sys.stdout = original_stdout


def test_silence_output_suppresses_emit_calls() -> None:
    """silence_output() must suppress emit() calls, not just raw print().

    Rich's Console() resolves sys.stdout at call time rather than construction
    time, so emit() is effectively suppressed when silence_output() is active.
    This test makes that contract explicit so any future change that breaks it
    (e.g. constructing Console with an explicit file=) fails loudly.
    """
    from benchbox.utils.printing import emit, silence_output

    captured = io.StringIO()
    original_stdout = sys.stdout
    try:
        sys.stdout = captured
        with silence_output(enabled=True):
            emit("LEAK: emit output should be suppressed by silence_output")
        assert captured.getvalue() == "", "emit() leaked past silence_output()"
    finally:
        sys.stdout = original_stdout
