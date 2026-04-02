"""Tests for shared benchmark query retrieval helpers."""

from __future__ import annotations

import pytest

from benchbox.core.amplab.benchmark import AMPLabBenchmark
from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
from benchbox.core.h2odb.benchmark import H2OBenchmark
from benchbox.core.ssb.benchmark import SSBBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _build_benchmark(name: str, tmp_path):
    if name == "amplab":
        return AMPLabBenchmark(scale_factor=0.01, output_dir=tmp_path)
    if name == "clickbench":
        return ClickBenchBenchmark(scale_factor=0.01, output_dir=tmp_path)
    if name == "h2odb":
        return H2OBenchmark(scale_factor=0.01, output_dir=tmp_path)
    if name == "ssb":
        return SSBBenchmark(scale_factor=0.01, output_dir=tmp_path, compress_data=False, compression_type="none")
    raise AssertionError(f"Unknown benchmark: {name}")


@pytest.mark.parametrize("benchmark_name", ["amplab", "clickbench", "h2odb", "ssb"])
def test_get_queries_without_dialect_returns_base_queries(benchmark_name: str, tmp_path) -> None:
    """Benchmarks should return their query-manager SQL unchanged without a dialect."""
    benchmark = _build_benchmark(benchmark_name, tmp_path)

    assert benchmark.get_queries() == benchmark.query_manager.get_all_queries()


@pytest.mark.parametrize("benchmark_name", ["amplab", "clickbench", "h2odb", "ssb"])
def test_get_queries_with_dialect_translates_each_query(
    benchmark_name: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Benchmarks should translate each query exactly once when a dialect is requested."""
    benchmark = _build_benchmark(benchmark_name, tmp_path)
    base_queries = benchmark.query_manager.get_all_queries()
    calls: list[tuple[str, str]] = []

    def fake_translate(query_text: str, dialect: str) -> str:
        calls.append((query_text, dialect))
        return f"{dialect}::{query_text}"

    monkeypatch.setattr(benchmark, "translate_query_text", fake_translate)

    translated = benchmark.get_queries(dialect="duckdb")

    assert translated == {query_id: f"duckdb::{query_text}" for query_id, query_text in base_queries.items()}
    assert calls == [(query_text, "duckdb") for query_text in base_queries.values()]
