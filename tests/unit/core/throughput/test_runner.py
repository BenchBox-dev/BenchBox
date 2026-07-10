"""Fast-lane unit tests for benchbox.core.throughput (StreamRunner + result models).

Mirrors the mocking style used in ``tests/integration/test_tpch_throughput_test.py``
(fake benchmark/config objects, no real database or benchmark work) but targets
``StreamRunner`` directly and stays deterministic - no real multi-threaded
timing/wall-clock behavior is exercised here. That remains the job of the
slow-marked integration test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from unittest.mock import Mock

import pytest

from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@dataclass
class _FakeConfig:
    """Minimal stand-in satisfying the structural ``_RunnerConfig`` protocol."""

    num_streams: int = 1
    max_workers: Optional[int] = None
    base_seed: int = 42
    stream_timeout: int = 0
    scale_factor: float = 1.0
    verbose: bool = False


def _make_result() -> ThroughputResult:
    return ThroughputResult(
        start_time="2026-01-01T00:00:00",
        end_time="",
        total_time=0.0,
        throughput_at_size=0.0,
        streams_executed=0,
        streams_successful=0,
    )


def _make_stream_result(
    stream_id: int,
    *,
    start_time: float = 0.0,
    end_time: float = 1.0,
    queries_executed: int = 22,
    queries_successful: int = 22,
    queries_failed: int = 0,
    success: bool = True,
    error: Optional[str] = None,
) -> ThroughputStreamResult:
    return ThroughputStreamResult(
        stream_id=stream_id,
        start_time=start_time,
        end_time=end_time,
        duration=end_time - start_time,
        queries_executed=queries_executed,
        queries_successful=queries_successful,
        queries_failed=queries_failed,
        success=success,
        error=error,
    )


class TestStreamRunnerExecute:
    """Cover StreamRunner.execute()'s aggregation/bookkeeping paths."""

    def test_all_streams_succeed(self) -> None:
        config = _FakeConfig(num_streams=3)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 3
        assert result.streams_successful == 3
        assert len(result.stream_results) == 3
        assert result.errors == []
        assert stream_fn.call_count == 3

    def test_failed_stream_recorded_as_error(self) -> None:
        config = _FakeConfig(num_streams=1)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        stream_fn = Mock(
            return_value=_make_stream_result(
                0,
                queries_successful=20,
                queries_failed=2,
                success=False,
                error="boom",
            )
        )

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 0
        assert len(result.errors) == 1
        assert "Stream 0 failed" in result.errors[0]
        assert "boom" in result.errors[0]

    def test_exception_from_stream_fn_is_captured_as_error(self) -> None:
        config = _FakeConfig(num_streams=1)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        stream_fn = Mock(side_effect=RuntimeError("stream blew up"))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 0
        assert result.stream_results == []
        assert len(result.errors) == 1
        assert "execution failed" in result.errors[0]
        assert "stream blew up" in result.errors[0]

    def test_zero_queries_stream_is_aggregated_without_error(self) -> None:
        """A stream that legitimately executes zero queries should still count as successful."""
        config = _FakeConfig(num_streams=1)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        stream_fn = Mock(
            return_value=_make_stream_result(
                0,
                queries_executed=0,
                queries_successful=0,
                queries_failed=0,
                success=True,
            )
        )

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 1
        assert result.errors == []
        assert result.stream_results[0].queries_executed == 0

    def test_single_stream_fallback_when_max_workers_unset(self) -> None:
        """config.max_workers=None falls back to config.num_streams (single-thread case)."""
        config = _FakeConfig(num_streams=1, max_workers=None)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 1
        stream_fn.assert_called_once_with(0, config.base_seed, config)

    def test_verbose_logging_does_not_affect_aggregation(self) -> None:
        config = _FakeConfig(num_streams=1, verbose=True)
        result = _make_result()
        logger = Mock(spec=logging.Logger)

        stream_fn = Mock(return_value=_make_stream_result(0))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_successful == 1
        assert logger.info.called


class TestStreamRunnerComputeMetrics:
    """Cover StreamRunner.compute_metrics()'s pure aggregation math."""

    def test_computes_throughput_from_stream_results(self) -> None:
        config = _FakeConfig(num_streams=2, scale_factor=1.0)
        result = _make_result()
        result.stream_results = [
            _make_stream_result(0, start_time=0.0, end_time=10.0, queries_executed=22),
            _make_stream_result(1, start_time=1.0, end_time=11.0, queries_executed=22),
        ]

        StreamRunner.compute_metrics(result, config, start_time=0.0)

        # TTT spans from the earliest stream start to the latest stream end.
        assert result.total_time == pytest.approx(11.0)
        expected_throughput_at_size = (config.num_streams * 3600.0 * config.scale_factor) / result.total_time
        assert result.throughput_at_size == pytest.approx(expected_throughput_at_size)
        assert result.query_throughput == pytest.approx(44 / 11.0)
        assert result.end_time != ""

    def test_zero_queries_yields_zero_query_throughput(self) -> None:
        config = _FakeConfig(num_streams=1, scale_factor=0.1)
        result = _make_result()
        result.stream_results = [_make_stream_result(0, start_time=0.0, end_time=5.0, queries_executed=0)]

        StreamRunner.compute_metrics(result, config, start_time=0.0)

        assert result.total_time == pytest.approx(5.0)
        assert result.query_throughput == 0.0
        assert result.throughput_at_size > 0

    def test_falls_back_to_elapsed_time_when_no_streams_ran(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No stream_results (e.g. all streams raised before producing a result)."""
        monkeypatch.setattr(
            "benchbox.core.throughput.runner.elapsed_seconds",
            lambda start: 7.5,
        )
        config = _FakeConfig(num_streams=1)
        result = _make_result()
        assert result.stream_results == []

        StreamRunner.compute_metrics(result, config, start_time=0.0)

        assert result.total_time == pytest.approx(7.5)

    def test_zero_total_time_leaves_throughput_fields_untouched(self) -> None:
        """When total_time is 0 (degenerate identical start/end), division is skipped entirely."""
        config = _FakeConfig(num_streams=1)
        result = _make_result()
        result.throughput_at_size = -1.0
        result.query_throughput = -1.0
        result.stream_results = [_make_stream_result(0, start_time=5.0, end_time=5.0)]

        StreamRunner.compute_metrics(result, config, start_time=0.0)

        assert result.total_time == 0.0
        assert result.throughput_at_size == -1.0
        assert result.query_throughput == -1.0


class TestThroughputResultAggregation:
    """Cover the plain dataclass shape/defaults in result.py."""

    def test_defaults(self) -> None:
        result = _make_result()
        assert result.stream_results == []
        assert result.query_throughput == 0.0
        assert result.success is True
        assert result.errors == []

    def test_stream_result_defaults(self) -> None:
        stream_result = ThroughputStreamResult(
            stream_id=0,
            start_time=0.0,
            end_time=1.0,
            duration=1.0,
            queries_executed=1,
            queries_successful=1,
            queries_failed=0,
        )
        assert stream_result.query_results == []
        assert stream_result.success is True
        assert stream_result.error is None
