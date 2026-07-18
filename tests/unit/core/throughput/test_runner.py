"""Fast-lane unit tests for benchbox.core.throughput (StreamRunner + result models).

Mirrors the mocking style used in ``tests/integration/test_tpch_throughput_test.py``
(fake benchmark/config objects, no real database or benchmark work) but targets
``StreamRunner`` directly. Most cases stay fully deterministic; a few
(``TestStreamRunnerTimeoutDetectionAndLeakSurfacing``,
``TestStreamRunnerCooperativeCancellation``,
``TestStreamRunnerNonBlockingShutdown``) use small real sleeps with generous
margins to exercise genuine multi-threaded timeout/wall-clock behavior
end-to-end rather than mocking time itself -- the fuller, slower-margin
real-DuckDB oracle for this remains
``tests/integration/test_throughput_real_duckdb.py``.
"""

from __future__ import annotations

import logging
import threading
import time
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
    stream_timeout: float = 0
    scale_factor: float = 1.0
    verbose: bool = False
    # Opt-in, default OFF -- deliberately NOT part of the structural
    # _RunnerConfig protocol (see runner.py); included here so tests can
    # exercise both the enabled and disabled paths.
    cancel_on_timeout: bool = False


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


class TestStreamRunnerTimeoutDetectionAndLeakSurfacing:
    """Cover execute()'s per-stream timeout detection (w1).

    ``execute()`` used to enforce the per-stream timeout via
    ``future.result(timeout=...)`` inside a ``concurrent.futures.
    as_completed()`` loop -- a no-op, since as_completed() only yields a
    future once it is already done(), so .result(timeout=...) on it can
    never raise TimeoutError. These tests use a real (but small) sleep
    exceeding a tiny ``stream_timeout`` so the fixed code path -- timeout
    passed to as_completed() itself, with a fallback loop classifying any
    still-not-done() future as leaked -- is exercised end-to-end rather than
    mocked, proving detection is no longer dead code.
    """

    SLOW_STREAM_SLEEP = 0.1
    TINY_TIMEOUT = 0.01

    def test_slow_stream_is_annotated_as_leaked_and_always_logged(self) -> None:
        def slow_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.SLOW_STREAM_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, verbose=False)
        result = _make_result()
        logger = Mock(spec=logging.Logger)

        StreamRunner.execute(slow_stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 0
        assert len(result.errors) == 1
        assert "timed out" in result.errors[0].lower()
        assert "leaked" in result.errors[0].lower()
        assert "cannot forcibly cancel" in result.errors[0].lower()

        # Always surfaced via logger.warning -- NOT gated on config.verbose
        # (verbose=False above) -- a leaked stream must never be silent.
        logger.warning.assert_called_once_with(result.errors[0])
        logger.error.assert_not_called()

    def test_fast_stream_within_timeout_is_not_flagged_as_leaked(self) -> None:
        """Sanity check: a stream that finishes well within its timeout is
        processed normally, with no leaked/timeout annotation at all."""

        def fast_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=5)
        result = _make_result()
        logger = Mock(spec=logging.Logger)

        StreamRunner.execute(fast_stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 1
        assert result.errors == []
        logger.warning.assert_not_called()


class TestStreamRunnerCooperativeCancellation:
    """Cover execute()'s opt-in cooperative-cancellation wiring (w2).

    ``config.cancel_on_timeout`` defaults to False/absent, which must
    preserve today's behavior exactly (no cancel-event machinery at all).
    When enabled, a per-stream ``threading.Event`` is attached to
    ``config._stream_cancel_events`` and set() when that stream's own
    timeout fires -- never a hard thread-kill.
    """

    SLOW_STREAM_SLEEP = 0.1
    TINY_TIMEOUT = 0.01

    def test_disabled_by_default_no_cancel_events_attached(self) -> None:
        """cancel_on_timeout defaults False -- execute() must still
        explicitly reset ``_stream_cancel_events`` to an empty dict (not
        leave it unset, and never leave a stale dict from a prior call on a
        reused config object -- see
        TestStreamRunnerCancelEventsResetAcrossReusedConfig below)."""
        config = _FakeConfig(num_streams=2)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")
        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert getattr(config, "_stream_cancel_events", None) == {}

    def test_enabled_but_streams_finish_normally_leaves_events_unset(self) -> None:
        """Opt-in cooperative cancellation must not affect the normal
        (no-timeout) path: events exist but are never set()."""
        config = _FakeConfig(num_streams=2, cancel_on_timeout=True, stream_timeout=5)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")
        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_successful == 2
        assert result.errors == []
        cancel_events = getattr(config, "_stream_cancel_events", None)
        assert cancel_events is not None and len(cancel_events) == 2
        assert all(not event.is_set() for event in cancel_events.values())

    def test_timeout_signals_that_streams_own_cancel_event_only(self) -> None:
        """Only the timed-out stream's event is set -- never a hard thread
        kill, and never every stream's event (a single slow stream must not
        cancel unrelated healthy streams)."""

        def slow_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.SLOW_STREAM_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=True)
        result = _make_result()
        logger = Mock(spec=logging.Logger)

        StreamRunner.execute(slow_stream_fn, config, result, logger)

        cancel_events = getattr(config, "_stream_cancel_events", None)
        assert cancel_events is not None and len(cancel_events) == 1
        assert cancel_events[0].is_set()
        assert "cooperative cancellation has been signalled" in result.errors[0]

    def test_stale_cancel_events_reset_when_reusing_config_with_cancel_disabled(self) -> None:
        """Regression (review follow-up): a SET Event from a prior
        execute() call on this same config object must not survive into a
        later execute() call that has cooperative cancel disabled.

        Reproduces: call 1 has cancel_on_timeout=True and its one stream
        times out, so its Event ends up set(). Call 2 reuses the SAME
        config object with cancel_on_timeout=False -- execute() must
        explicitly reset ``_stream_cancel_events`` to ``{}`` rather than
        leaving call 1's stale, already-set dict in place (which a spec's
        presence-only lookup would otherwise treat as this call's own
        cancellation state).
        """

        def slow_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.SLOW_STREAM_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=True)
        result1 = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        StreamRunner.execute(slow_stream_fn, config, result1, logger)

        stale_cancel_events = getattr(config, "_stream_cancel_events", None)
        assert stale_cancel_events is not None and stale_cancel_events[0].is_set()

        # Reuse the SAME config object; cooperative cancel now disabled and
        # no timeout pressure. A fresh dict must replace the stale one.
        config.cancel_on_timeout = False
        config.stream_timeout = 5
        result2 = _make_result()

        def fast_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            return _make_stream_result(stream_id)

        StreamRunner.execute(fast_stream_fn, config, result2, logger)

        refreshed_cancel_events = getattr(config, "_stream_cancel_events", None)
        assert refreshed_cancel_events == {}
        assert refreshed_cancel_events is not stale_cancel_events
        assert result2.streams_successful == 1
        assert result2.errors == []


class TestStreamRunnerNonBlockingShutdown:
    """Cover execute()'s non-blocking shutdown (w1/w3): a hung stream must
    not hold execute() hostage for its own lifetime.

    ``execute()`` used to run inside a ``with ThreadPoolExecutor(...)``
    block whose implicit ``shutdown(wait=True)`` at ``__exit__`` blocked
    the method's return until every submitted thread finished -- including
    a leaked one. It now manages the pool manually and calls
    ``shutdown(wait=False)`` in a ``finally``, so it returns once its own
    timeout/accounting window closes, abandoning (never killing) any
    still-running thread. These tests use a real, but generous margin
    (hang sleep >> timeout, by 20x+) so wall-clock assertions are not
    flake-prone on a loaded CI box.
    """

    TINY_TIMEOUT = 0.05
    # Deliberately >> TINY_TIMEOUT so a passing assertion that execute()
    # returned near the timeout (and not near the hang) has a wide margin.
    HANG_SLEEP = 2.0

    def test_execute_returns_near_timeout_not_after_full_hang(self) -> None:
        """The headline w1 fix: execute()'s wall-clock is bounded by
        stream_timeout, not by how long the hung stream actually sleeps."""

        def hung_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.HANG_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=False)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        start = time.monotonic()
        StreamRunner.execute(hung_stream_fn, config, result, logger)
        elapsed = time.monotonic() - start

        # Bounded by the timeout window plus classification overhead --
        # nowhere near the full 2s hang. A generous 1s ceiling still leaves
        # a 20x margin over TINY_TIMEOUT for CI scheduling jitter while
        # remaining far short of HANG_SLEEP.
        assert elapsed < 1.0, f"execute() blocked for {elapsed:.3f}s -- did not return near the timeout"

    def test_leaked_stream_from_non_blocking_path_still_surfaced_in_errors(self) -> None:
        """The non-blocking shutdown must not regress leak surfacing: the
        abandoned stream is still logged and recorded in result.errors,
        exactly as under the old (blocking) behavior."""

        def hung_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.HANG_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=False)
        result = _make_result()
        logger = Mock(spec=logging.Logger)

        StreamRunner.execute(hung_stream_fn, config, result, logger)

        assert result.streams_executed == 1
        assert result.streams_successful == 0
        assert len(result.errors) == 1
        assert "timed out" in result.errors[0].lower()
        assert "leaked" in result.errors[0].lower()
        logger.warning.assert_called_once_with(result.errors[0])

    def test_healthy_all_streams_complete_path_unaffected(self) -> None:
        """Non-blocking shutdown must be a pure no-op on the healthy path:
        every future is already done() before shutdown() runs, so timing
        and accounting for a normal (no-timeout) run are unchanged."""
        config = _FakeConfig(num_streams=4, stream_timeout=5)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")
        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 4
        assert result.streams_successful == 4
        assert result.errors == []
        assert stream_fn.call_count == 4

    def test_cooperative_cancel_with_real_set_event_still_cancels(self) -> None:
        """Composition with #1106: a genuine, timeout-set threading.Event
        must still signal cancellation under the new non-blocking shutdown
        -- the executor lifecycle change must not disturb this wiring."""

        def slow_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(0.1)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=True)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        StreamRunner.execute(slow_stream_fn, config, result, logger)

        cancel_events = getattr(config, "_stream_cancel_events", None)
        assert cancel_events is not None
        assert isinstance(cancel_events[0], threading.Event)
        assert cancel_events[0].is_set()

    def test_cooperative_cancel_disabled_by_default_never_cancels(self) -> None:
        """Composition with #1106: cancel_on_timeout defaults False, so no
        cancel-event machinery is attached at all, even on a hung stream,
        under the new non-blocking shutdown."""

        def hung_stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            time.sleep(self.HANG_SLEEP)
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=1, stream_timeout=self.TINY_TIMEOUT)
        assert config.cancel_on_timeout is False
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        StreamRunner.execute(hung_stream_fn, config, result, logger)

        assert getattr(config, "_stream_cancel_events", None) == {}

    def test_mock_truthy_config_healthy_path_unaffected(self) -> None:
        """Composition with #1106, at the StreamRunner boundary: an
        unconfigured ``Mock()`` config's ``cancel_on_timeout`` attribute is
        truthy-by-default (``bool(Mock()) is True``), so ``execute()``'s own
        ``bool(getattr(config, "cancel_on_timeout", False))`` read treats it
        as opted-in and *does* populate ``_stream_cancel_events`` -- that
        alone is harmless bookkeeping. The actual protection against a
        stale/mock-truthy value causing a *spurious cancellation* is the
        stricter ``is True`` identity gate in each spec's
        ``_resolve_cancel_event`` (``benchbox/core/tpch/throughput_test.py``,
        ``benchbox/core/tpcds/throughput_test.py`` -- out of this module's
        scope, exercised by ``tests/unit/tpch/test_tpch_compliance.py`` and
        ``tests/integration/test_throughput_corrections.py``). What this
        test pins down is that the non-blocking shutdown change does not
        disturb that composition: on a healthy (no-timeout) run, a
        Mock-truthy ``cancel_on_timeout`` still yields a normal, fully
        successful result with no event ever set() -- nothing times out, so
        no cancellation signal fires regardless of the flag's truthiness.
        """
        stream_fn = Mock(side_effect=lambda stream_id, seed, cfg: _make_stream_result(stream_id))
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        config = Mock()
        config.num_streams = 1
        config.max_workers = None
        config.base_seed = 1
        config.stream_timeout = 5
        config.scale_factor = 1.0
        config.verbose = False
        # Deliberately NOT setting cancel_on_timeout -- an unconfigured Mock
        # attribute access returns a truthy child Mock by default.

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_successful == 1
        assert result.errors == []
        cancel_events = getattr(config, "_stream_cancel_events", None)
        assert isinstance(cancel_events, dict) and len(cancel_events) == 1
        assert all(not event.is_set() for event in cancel_events.values())

    def test_queued_stream_never_starts_after_max_workers_throttled_timeout(self) -> None:
        """#1141 review: with max_workers < num_streams, a future can still
        be QUEUED (never dispatched to a worker) at the timeout deadline -
        distinct from a leaked RUNNING future. Without cancel_futures=True,
        that queued stream would start executing once the sole worker frees
        up (when the hung stream 0 finally returns), well after execute()
        has already returned and counted stream 1 as timed out too - extra
        DB work overlapping with whatever runs next."""
        started = threading.Event()

        def stream_fn(stream_id: int, seed: int, cfg: _FakeConfig) -> ThroughputStreamResult:
            if stream_id == 0:
                time.sleep(self.HANG_SLEEP)  # occupies the sole worker past the timeout
            else:
                started.set()  # only reachable if stream 1 was ever dispatched
            return _make_stream_result(stream_id)

        config = _FakeConfig(num_streams=2, max_workers=1, stream_timeout=self.TINY_TIMEOUT, cancel_on_timeout=False)
        result = _make_result()
        logger = logging.getLogger("test-throughput-runner")

        StreamRunner.execute(stream_fn, config, result, logger)

        assert result.streams_executed == 2
        assert len(result.errors) == 2

        # Wait well past HANG_SLEEP (when the sole worker frees up) - a
        # cancelled queued future must never be dispatched, even once a
        # worker becomes free.
        assert not started.wait(timeout=self.HANG_SLEEP + 1.0)
