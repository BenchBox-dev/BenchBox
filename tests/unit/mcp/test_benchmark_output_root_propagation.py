"""Regression tests for output-root propagation on the MCP benchmark path.

The MCP ``run_benchmark`` tool constructs benchmark instances directly via
``get_public_benchmark_class(...)(scale_factor=...)`` and the data-only path
resolves a datagen directory via ``get_benchmark_runs_datagen_path``. Both must
honor ``BENCHBOX_OUTPUT_DIR`` so MCP-driven runs do not write generated data
under a stale ``cwd/benchmark_runs`` default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.benchmark_registry import get_public_benchmark_class
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Generator-backed benchmarks reachable through the public MCP surface.
MCP_BENCHMARKS = ["h2odb", "ssb", "vector_search", "tpch"]


@pytest.mark.parametrize("benchmark_id", MCP_BENCHMARKS)
def test_mcp_run_construction_honors_env_output_root(benchmark_id, tmp_path, monkeypatch):
    """Mirror MCP ``_run_benchmark_impl`` construction under BENCHBOX_OUTPUT_DIR."""
    root = tmp_path / "mcp_runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(root))

    benchmark_class = get_public_benchmark_class(benchmark_id)
    if benchmark_class is None:
        pytest.skip(f"{benchmark_id} not available in this environment")

    # Same call shape MCP uses: scale_factor only, no explicit output_dir.
    benchmark = benchmark_class(scale_factor=0.01)

    output_dir = Path(str(benchmark.output_dir))
    assert str(output_dir).startswith(str(root)), output_dir
    assert Path.cwd() not in output_dir.parents, output_dir

    # Public benchmark wrappers delegate to a core ``_impl`` that owns the
    # nested data generator.
    core = getattr(benchmark, "_impl", benchmark)
    generator = core.__dict__.get("data_generator")
    assert generator is not None and hasattr(generator, "output_dir")
    gen_dir = Path(str(generator.output_dir))
    assert str(gen_dir).startswith(str(root)), gen_dir
    assert Path.cwd() not in gen_dir.parents, gen_dir


def test_mcp_data_only_datagen_path_honors_env_output_root(tmp_path, monkeypatch):
    """The MCP data-only datagen directory resolves under the env output root."""
    root = tmp_path / "mcp_runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(root))

    data_dir = get_benchmark_runs_datagen_path("tpch", 0.01)

    assert str(data_dir).startswith(str(root)), data_dir
    assert data_dir.name == "tpch_sf001", data_dir
    assert Path.cwd() not in data_dir.parents, data_dir


def test_mcp_default_without_env_uses_cwd(monkeypatch):
    """Without an output-root override the MCP datagen path stays cwd-local."""
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

    data_dir = get_benchmark_runs_datagen_path("tpch", 0.01)

    assert data_dir == Path.cwd() / "benchmark_runs" / "datagen" / "tpch_sf001"
