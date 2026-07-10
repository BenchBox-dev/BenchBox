from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from benchbox.core.tpcds.throughput_test import (
    TPCDSThroughputStreamResult,
    TPCDSThroughputTest,
    TPCDSThroughputTestConfig,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class DummyConn:
    def __init__(self):
        self.closed = False

    def execute(self, _sql):
        return SimpleNamespace(fetchall=list)

    def commit(self):
        return None

    def close(self):
        self.closed = True


@dataclass
class DummyStreamQuery:
    query_id: int
    variant: str | None = None


class DummyStreamManager:
    def __init__(self, queries):
        self._queries = queries

    def generate_streams(self):
        return {0: self._queries}


def test_run_computes_metrics(monkeypatch):
    benchmark = SimpleNamespace(get_query=lambda *_args, **_kwargs: "SELECT 1")
    throughput = TPCDSThroughputTest(benchmark=benchmark, connection_factory=DummyConn, num_streams=1)

    monkeypatch.setattr(throughput, "_preflight_validate_generation", lambda _config: None)

    def fake_execute_stream(stream_id, seed, config):
        return TPCDSThroughputStreamResult(
            stream_id=stream_id,
            start_time=10.0,
            end_time=20.0,
            duration=10.0,
            queries_executed=5,
            queries_successful=5,
            queries_failed=0,
            success=True,
        )

    monkeypatch.setattr(throughput, "_execute_stream", fake_execute_stream)

    result = throughput.run(TPCDSThroughputTestConfig(scale_factor=2.0, num_streams=1, enable_preflight=False))

    assert result.success is True
    assert result.total_time == 10.0
    assert result.streams_successful == 1
    assert result.throughput_at_size > 0
    assert result.query_throughput == pytest.approx(0.5)


def test_validate_results_branches():
    benchmark = SimpleNamespace(get_query=lambda *_args, **_kwargs: "SELECT 1")
    throughput = TPCDSThroughputTest(benchmark=benchmark, connection_factory=DummyConn, num_streams=1)

    good = throughput.run(TPCDSThroughputTestConfig(scale_factor=1.0, num_streams=1, enable_preflight=False))
    assert throughput.validate_results(good) is False

    good.success = True
    good.streams_successful = 1
    good.config.num_streams = 1
    good.throughput_at_size = 10.0
    assert throughput.validate_results(good) is True


def test_preflight_wraps_internal_error():
    benchmark = SimpleNamespace(get_query=lambda *_args, **_kwargs: "SELECT 1")
    throughput = TPCDSThroughputTest(benchmark=benchmark, connection_factory=DummyConn, num_streams=1)

    class BadBenchmark:
        def get_query(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    throughput.benchmark = BadBenchmark()

    with pytest.raises(RuntimeError, match="preflight failed"):
        throughput._preflight_validate_generation(TPCDSThroughputTestConfig(num_streams=1, verbose=False))


def test_execute_stream_handles_missing_query_manager(monkeypatch):
    benchmark = SimpleNamespace(
        get_queries=lambda: {"1": "SELECT 1"},
        get_query=lambda *_args, **_kwargs: "SELECT 1",
    )
    throughput = TPCDSThroughputTest(benchmark=benchmark, connection_factory=DummyConn, num_streams=1)

    result = throughput._execute_stream(0, 42, TPCDSThroughputTestConfig(num_streams=1, enable_preflight=False))

    assert result.success is False
    assert result.error is not None


def test_execute_stream_runs_query_path(monkeypatch):
    query_manager = object()
    benchmark = SimpleNamespace(
        query_manager=query_manager,
        get_queries=lambda: {"1": "SELECT 1"},
        get_query=lambda *_args, **_kwargs: "SELECT 1",
    )
    throughput = TPCDSThroughputTest(benchmark=benchmark, connection_factory=DummyConn, num_streams=1)

    monkeypatch.setattr(
        "benchbox.core.tpcds.streams.create_standard_streams",
        lambda **_kwargs: DummyStreamManager([DummyStreamQuery(query_id=1)]),
    )

    result = throughput._execute_stream(0, 100, TPCDSThroughputTestConfig(num_streams=1, enable_preflight=False))

    assert result.queries_executed == 1
    assert result.queries_successful == 1
    assert result.success is True
