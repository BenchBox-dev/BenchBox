from __future__ import annotations

import concurrent.futures
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Protocol

from benchbox.core.results.metrics import TPCMetricsCalculator
from benchbox.utils.clock import elapsed_seconds

from .containment import record_outstanding_result
from .executor import DaemonStreamExecutor
from .result import (
    ThroughputResult,
    ThroughputStreamResult,
    throughput_result_succeeded,
    throughput_stream_succeeded,
)


class _RunnerConfig(Protocol):
    """Structural type for config objects accepted by StreamRunner.

    Both ``TPCHThroughputTestConfig`` and ``TPCDSThroughputTestConfig``
    satisfy this protocol; no explicit ``implements`` declaration is needed.

    ``cancel_on_timeout`` is deliberately NOT declared here: it is an
    optional, opt-in attribute read defensively via ``getattr(...,
    False)`` in ``execute()`` so configs (and test doubles) that predate it
    keep working unchanged.
    """

    num_streams: int
    max_workers: int | None
    base_seed: int
    stream_timeout: int
    scale_factor: float
    verbose: bool


class StreamRunner:
    """Concurrent-stream executor shared by TPC-H and TPC-DS throughput tests."""

    @staticmethod
    def execute(
        stream_fn: Callable[[int, int, Any], ThroughputStreamResult],
        config: _RunnerConfig,
        result: ThroughputResult,
        logger: logging.Logger,
    ) -> None:
        max_workers = config.max_workers or config.num_streams
        timeout: float | None = config.stream_timeout if config.stream_timeout > 0 else None

        if max_workers < config.num_streams and timeout is not None:
            logger.warning(
                f"max_workers ({max_workers}) < num_streams ({config.num_streams}) with a "
                f"stream_timeout of {timeout}s set: queued streams share the same overall "
                "deadline as immediately-started ones and may be reported as timed-out before "
                "executing a single query. Set max_workers >= num_streams (or leave it unset) "
                "for the timeout to behave as a true per-stream timeout."
            )

        cooperative_cancel = bool(getattr(config, "cancel_on_timeout", False))
        cancel_events: dict[int, threading.Event] = (
            {stream_id: threading.Event() for stream_id in throughput_stream_ids(config.num_streams)}
            if cooperative_cancel
            else {}
        )
        config._stream_cancel_events = cancel_events  # type: ignore[attr-defined]

        future_to_stream_id: dict[concurrent.futures.Future[ThroughputStreamResult], int] = {}
        pending: set[concurrent.futures.Future[ThroughputStreamResult]] = set()
        outstanding_futures: dict[int, concurrent.futures.Future[ThroughputStreamResult]] = {}

        def _record_completed_future(
            completed_future: concurrent.futures.Future[ThroughputStreamResult], completed_stream_id: int
        ) -> None:
            try:
                stream_result = completed_future.result()
                result.stream_results.append(stream_result)
                result.streams_executed += 1

                if throughput_stream_succeeded(stream_result):
                    result.streams_successful += 1
                else:
                    stream_result.success = False
                    if not stream_result.error:
                        query_errors = [
                            str(query.get("error"))
                            for query in stream_result.query_results
                            if not query.get("success", True) and query.get("error")
                        ]
                        stream_result.error = "; ".join(query_errors) or (
                            f"{stream_result.queries_successful}/{stream_result.queries_executed} queries succeeded"
                        )
                    result.errors.append(f"Stream {stream_result.stream_id} failed: {stream_result.error}")

                if config.verbose:
                    logger.info(
                        f"Stream {stream_result.stream_id}: "
                        f"{stream_result.queries_successful}/{stream_result.queries_executed} successful"
                    )

            except Exception as e:
                result.streams_executed += 1
                result.errors.append(f"Stream {completed_stream_id} execution failed: {e}")
                if config.verbose:
                    logger.error(f"Stream {completed_stream_id} execution failed: {e}")

        def _settle_pending(reason: str) -> None:
            for future in sorted(pending, key=future_to_stream_id.__getitem__):
                stream_id = future_to_stream_id[future]
                pending.discard(future)

                if cooperative_cancel:
                    cancel_events[stream_id].set()

                if future.cancel():
                    result.cancelled_stream_ids.append(stream_id)
                    result.outstanding_notes.append(f"Stream {stream_id} cancelled before dispatch; it never executed.")
                    cancelled_msg = (
                        f"Stream {stream_id} {reason} without starting: it was still queued behind "
                        "running streams and is cancelled before dispatch so it never executes."
                    )
                    result.errors.append(cancelled_msg)
                    logger.warning(cancelled_msg)
                elif future.done():
                    _record_completed_future(future, stream_id)
                else:
                    result.streams_executed += 1
                    result.outstanding_stream_ids.append(stream_id)
                    outstanding_futures[stream_id] = future
                    error_msg = (
                        f"Stream {stream_id} {reason} and has not completed. "
                        "Python cannot forcibly cancel a running thread, so this stream's worker "
                        "may still be executing queries and holding its database connection in "
                        "the background (leaked)"
                        + (
                            "; cooperative cancellation has been signalled and the stream should "
                            "stop before its next query"
                            if cooperative_cancel
                            else ""
                        )
                        + "."
                    )
                    result.errors.append(error_msg)
                    result.outstanding_notes.append(
                        f"Stream {stream_id} worker still running when it was settled"
                        + (
                            "; cooperative cancellation signalled"
                            if cooperative_cancel
                            else "; no cooperative cancellation (cancel_on_timeout=False)"
                        )
                        + "."
                    )
                    logger.warning(error_msg)

        executor = DaemonStreamExecutor(max_workers=max_workers)
        try:
            for stream_id in throughput_stream_ids(config.num_streams):
                future = executor.submit(stream_fn, stream_id, config.base_seed + stream_id, config)
                future_to_stream_id[future] = stream_id
                pending.add(future)

            try:
                for future in concurrent.futures.as_completed(pending, timeout=timeout):
                    pending.discard(future)
                    _record_completed_future(future, future_to_stream_id[future])
            except concurrent.futures.TimeoutError:
                _settle_pending(f"timed out after {timeout}s")
        except BaseException:
            _settle_pending("was abandoned after the runner failed")
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            result._outstanding_futures = outstanding_futures  # type: ignore[attr-defined]
            result.cleanup_state = "outstanding" if result.outstanding_stream_ids else "complete"
            if result.outstanding_stream_ids:
                record_outstanding_result(result)

    @staticmethod
    def compute_metrics(
        result: ThroughputResult,
        config: _RunnerConfig,
        start_time: float,
        queries_per_stream: int | None = None,
    ) -> bool:
        """Compute TTT, Throughput@Size, and query throughput; mutates *result*.

        Sets ``result.end_time``, ``result.total_time``,
        ``result.throughput_at_size``, and ``result.query_throughput``.
        A metric is emitted only when every requested stream completed and
        reported success. Returning ``False`` lets both TPC drivers use this
        product-level validity gate without duplicating it.

        Args:
            result: Mutable ``ThroughputResult`` populated by ``execute()``.
            config: Test configuration (needs ``num_streams`` and
                ``scale_factor``).
            start_time: ``mono_time()`` captured before the test body began;
                used as a fallback total-time when no streams recorded timing.
            queries_per_stream: Per-stream query count used as Q in
                Throughput@Size; defaults to the executed statement count.
        """
        result.end_time = datetime.now().isoformat()

        # Per TPC-H/DS specification: Total Test Time (TTT) is measured from
        # when the first stream begins execution until the last stream completes.
        # This is the actual concurrent execution time, excluding setup overhead.
        if result.stream_results:
            first_stream = min(result.stream_results, key=lambda sr: sr.start_time)
            last_stream = max(result.stream_results, key=lambda sr: sr.end_time)
            total_time = last_stream.end_time - first_stream.start_time
            result.start_time = first_stream.start_wall_time or result.start_time
            result.end_time = last_stream.end_wall_time or result.end_time
        else:
            # Fallback if no streams executed (shouldn't happen in normal operation)
            total_time = elapsed_seconds(start_time)

        result.total_time = total_time

        if not throughput_result_succeeded(result, config.num_streams) or total_time <= 0:
            # Keep the internal numeric sentinel compatible with spec-local
            # log formatting. The adapter/export seam omits this invalid metric.
            result.throughput_at_size = 0.0
            result.query_throughput = 0.0
            result.success = False
            return False

        executed_queries = sum(sr.queries_executed for sr in result.stream_results)
        scored_queries = executed_queries if queries_per_stream is None else queries_per_stream * config.num_streams
        result.throughput_at_size = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=scored_queries,
            total_time_seconds=total_time,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
        )
        result.query_throughput = executed_queries / total_time
        result.success = result.throughput_at_size > 0
        return result.success
