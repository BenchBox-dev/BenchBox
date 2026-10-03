from __future__ import annotations

import concurrent.futures
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Protocol

from benchbox.core.results.metrics import TPCMetricsCalculator
from benchbox.utils.clock import elapsed_seconds

from .result import (
    ThroughputResult,
    ThroughputStreamResult,
    throughput_result_succeeded,
    throughput_stream_succeeded,
)


class _RunnerConfig(Protocol):
    num_streams: int
    max_workers: int | None
    base_seed: int
    stream_timeout: int
    scale_factor: float
    verbose: bool


class StreamRunner:
    @staticmethod
    def _finalize_tentatively_cancelled(
        result: ThroughputResult,
        tentatively_cancelled: list[tuple[concurrent.futures.Future[ThroughputStreamResult], int]],
        record_completed: Callable[[concurrent.futures.Future[ThroughputStreamResult], int], None],
        leaked_error: Callable[[int], str],
        logger: logging.Logger,
    ) -> dict[int, concurrent.futures.Future[ThroughputStreamResult]]:
        still_owned: dict[int, concurrent.futures.Future[ThroughputStreamResult]] = {}
        for queued_future, queued_stream_id in tentatively_cancelled:
            if queued_future.cancelled():
                result.streams_executed += 1
                result.cancelled_stream_ids.append(queued_stream_id)
                result.outstanding_notes.append(
                    f"Stream {queued_stream_id} cancelled before dispatch; it never executed."
                )
            elif queued_future.done():
                record_completed(queued_future, queued_stream_id)
            else:
                result.streams_executed += 1
                result.outstanding_stream_ids.append(queued_stream_id)
                still_owned[queued_stream_id] = queued_future
                error_msg = leaked_error(queued_stream_id)
                result.errors.append(error_msg)
                result.outstanding_notes.append(
                    f"Stream {queued_stream_id} started after the deadline; worker still running."
                )
                logger.warning(error_msg)
        return still_owned

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
        cancel_events: dict[int, threading.Event] = {}

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_stream_id: dict[concurrent.futures.Future[ThroughputStreamResult], int] = {}

            if cooperative_cancel:
                cancel_events = {stream_id: threading.Event() for stream_id in range(config.num_streams)}
                config._stream_cancel_events = cancel_events  # type: ignore[attr-defined]
            else:
                config._stream_cancel_events = {}  # type: ignore[attr-defined]

            for stream_id in range(config.num_streams):
                future = executor.submit(
                    stream_fn,
                    stream_id,
                    config.base_seed + stream_id,
                    config,
                )
                future_to_stream_id[future] = stream_id

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

            pending = set(future_to_stream_id.keys())

            outstanding_futures: dict[int, concurrent.futures.Future[ThroughputStreamResult]] = {}
            tentatively_cancelled: list[tuple[concurrent.futures.Future[ThroughputStreamResult], int]] = []

            def _leaked_error(timed_out_stream_id: int) -> str:
                return (
                    f"Stream {timed_out_stream_id} timed out after {timeout}s and has not completed. "
                    "Python cannot forcibly cancel a running thread, so this stream's worker "
                    "may still be executing queries and holding its database connection in "
                    "the background (leaked)"
                    + (
                        "; cooperative cancellation has been signalled and the stream should stop before its next query"
                        if cooperative_cancel
                        else ""
                    )
                    + "."
                )

            try:
                for future in concurrent.futures.as_completed(pending, timeout=timeout):
                    stream_id = future_to_stream_id[future]
                    pending.discard(future)
                    _record_completed_future(future, stream_id)

            except concurrent.futures.TimeoutError:
                for future in list(pending):
                    stream_id = future_to_stream_id[future]

                    if future.done():
                        pending.discard(future)
                        _record_completed_future(future, stream_id)
                        continue

                    if cooperative_cancel:
                        cancel_events[stream_id].set()

                    if future.running():
                        result.streams_executed += 1
                        result.outstanding_stream_ids.append(stream_id)
                        outstanding_futures[stream_id] = future
                        error_msg = _leaked_error(stream_id)
                        result.errors.append(error_msg)
                        result.outstanding_notes.append(
                            f"Stream {stream_id} worker still running at timeout"
                            + (
                                "; cooperative cancellation signalled"
                                if cooperative_cancel
                                else "; no cooperative cancellation (cancel_on_timeout=False)"
                            )
                            + "."
                        )
                        logger.warning(error_msg)
                    else:
                        tentatively_cancelled.append((future, stream_id))
                        queued_msg = (
                            f"Stream {stream_id} timed out after {timeout}s without starting: "
                            f"it was still queued behind running streams and is cancelled "
                            f"before dispatch so it never executes."
                        )
                        result.errors.append(queued_msg)
                        logger.warning(queued_msg)
                    pending.discard(future)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

            outstanding_futures.update(
                StreamRunner._finalize_tentatively_cancelled(
                    result, tentatively_cancelled, _record_completed_future, _leaked_error, logger
                )
            )

            result._outstanding_futures = outstanding_futures  # type: ignore[attr-defined]
            result.cleanup_state = "outstanding" if result.outstanding_stream_ids else "complete"

    @staticmethod
    def compute_metrics(
        result: ThroughputResult,
        config: _RunnerConfig,
        start_time: float,
    ) -> bool:
        result.end_time = datetime.now().isoformat()

        if result.stream_results:
            first_stream_start = min(sr.start_time for sr in result.stream_results)
            last_stream_end = max(sr.end_time for sr in result.stream_results)
            total_time = last_stream_end - first_stream_start
        else:
            total_time = elapsed_seconds(start_time)

        result.total_time = total_time

        if not throughput_result_succeeded(result, config.num_streams) or total_time <= 0:
            result.throughput_at_size = 0.0
            result.query_throughput = 0.0
            result.success = False
            return False

        total_queries = sum(sr.queries_executed for sr in result.stream_results)
        result.throughput_at_size = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=total_queries,
            total_time_seconds=total_time,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
        )
        result.query_throughput = total_queries / total_time
        result.success = result.throughput_at_size > 0
        return result.success
