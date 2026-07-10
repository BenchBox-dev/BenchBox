"""Shared concurrent-stream executor for TPC throughput tests.

``StreamRunner`` provides two static methods extracted from the near-identical
``run()`` bodies in TPC-H and TPC-DS throughput_test modules:

* ``execute()`` - ThreadPoolExecutor block, future collection, timeout/error
  handling; mutates the ``ThroughputResult`` in-place.
* ``compute_metrics()`` - TTT calculation, Throughput@Size, query throughput;
  also mutates ``ThroughputResult`` in-place.

Success-rate gating is intentionally left to each spec's ``run()`` so that
TPC-H's configurable ``min_success_rate`` and TPC-DS's hard-coded 70% gate
remain independently testable and auditable.  Verbose summary logging
(Throughput@Size, query throughput, success rate) is also left spec-local
because the two specs format the gate threshold differently.
"""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime
from typing import Any, Callable, Protocol

from benchbox.utils.clock import elapsed_seconds

from .result import ThroughputResult, ThroughputStreamResult


class _RunnerConfig(Protocol):
    """Structural type for config objects accepted by StreamRunner.

    Both ``TPCHThroughputTestConfig`` and ``TPCDSThroughputTestConfig``
    satisfy this protocol; no explicit ``implements`` declaration is needed.
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
        """Run all streams concurrently and populate *result* in-place.

        Submits ``config.num_streams`` futures via a ``ThreadPoolExecutor``,
        collects results (or timeout/exception errors), and increments
        ``result.streams_executed``, ``result.streams_successful``, and
        ``result.errors``.

        Args:
            stream_fn: Callable accepting ``(stream_id, seed, config)`` and
                returning a ``ThroughputStreamResult``.  Typically
                ``self._execute_stream`` from the spec test class.
            config: Test configuration satisfying ``_RunnerConfig``.
            result: Mutable ``ThroughputResult`` to accumulate stream outcomes.
            logger: Spec-local logger for verbose and error messages.
        """
        max_workers = config.max_workers or config.num_streams
        timeout: float | None = config.stream_timeout if config.stream_timeout > 0 else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Track future -> stream_id mapping for timeout error reporting
            future_to_stream_id: dict[concurrent.futures.Future[ThroughputStreamResult], int] = {}

            for stream_id in range(config.num_streams):
                future = executor.submit(
                    stream_fn,
                    stream_id,
                    config.base_seed + stream_id,
                    config,
                )
                future_to_stream_id[future] = stream_id

            # Wait for all streams to complete with per-stream timeout enforcement
            # Note: Timed-out streams continue executing in background (Python threading limitation)
            for future in concurrent.futures.as_completed(future_to_stream_id.keys()):
                stream_id = future_to_stream_id[future]

                try:
                    # Enforce per-stream timeout
                    stream_result = future.result(timeout=timeout)
                    result.stream_results.append(stream_result)
                    result.streams_executed += 1

                    if stream_result.success:
                        result.streams_successful += 1
                    else:
                        result.errors.append(f"Stream {stream_result.stream_id} failed: {stream_result.error}")

                    if config.verbose:
                        logger.info(
                            f"Stream {stream_result.stream_id}: "
                            f"{stream_result.queries_successful}/{stream_result.queries_executed} successful"
                        )

                except concurrent.futures.TimeoutError:
                    result.streams_executed += 1
                    error_msg = f"Stream {stream_id} timeout after {timeout}s"
                    result.errors.append(error_msg)
                    if config.verbose:
                        logger.error(error_msg)

                except Exception as e:
                    result.streams_executed += 1
                    result.errors.append(f"Stream {stream_id} execution failed: {e}")
                    if config.verbose:
                        logger.error(f"Stream {stream_id} execution failed: {e}")

    @staticmethod
    def compute_metrics(
        result: ThroughputResult,
        config: _RunnerConfig,
        start_time: float,
    ) -> None:
        """Compute TTT, Throughput@Size, and query throughput; mutates *result*.

        Sets ``result.end_time``, ``result.total_time``,
        ``result.throughput_at_size``, and ``result.query_throughput``.
        The success-rate gate and verbose summary logging are left to the
        calling spec's ``run()`` method.

        Args:
            result: Mutable ``ThroughputResult`` populated by ``execute()``.
            config: Test configuration (needs ``num_streams`` and
                ``scale_factor``).
            start_time: ``mono_time()`` captured before the test body began;
                used as a fallback total-time when no streams recorded timing.
        """
        result.end_time = datetime.now().isoformat()

        # Per TPC-H/DS specification: Total Test Time (TTT) is measured from
        # when the first stream begins execution until the last stream completes.
        # This is the actual concurrent execution time, excluding setup overhead.
        if result.stream_results:
            first_stream_start = min(sr.start_time for sr in result.stream_results)
            last_stream_end = max(sr.end_time for sr in result.stream_results)
            total_time = last_stream_end - first_stream_start
        else:
            # Fallback if no streams executed (shouldn't happen in normal operation)
            total_time = elapsed_seconds(start_time)

        result.total_time = total_time

        if total_time > 0:
            # Throughput@Size = S × 3600 × SF / TTT
            # where S = num_streams, SF = scale_factor, TTT = total_test_time
            result.throughput_at_size = (config.num_streams * 3600.0 * config.scale_factor) / total_time

            # Calculate query throughput
            total_queries = sum(sr.queries_executed for sr in result.stream_results)
            result.query_throughput = total_queries / total_time
