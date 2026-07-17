"""Shared concurrent-stream executor for TPC throughput tests.

``StreamRunner`` provides two static methods extracted from the near-identical
``run()`` bodies in TPC-H and TPC-DS throughput_test modules:

* ``execute()`` - ThreadPoolExecutor block, future collection, timeout/error
  handling; mutates the ``ThroughputResult`` in-place.
* ``compute_metrics()`` - TTT calculation, Throughput@Size, query throughput;
  also mutates ``ThroughputResult`` in-place.

Success-rate gating is intentionally left to each spec's ``run()`` so that
TPC-H's and TPC-DS's independently configurable ``min_success_rate`` gates
remain independently testable and auditable (see each module's config
dataclass for its spec-derived default).  Verbose summary logging
(Throughput@Size, query throughput, success rate) is also left spec-local
because the two specs format the gate threshold differently.

Timed-out streams
------------------
Python cannot forcibly cancel a running thread. ``execute()`` therefore
offers two complementary, both-optional mitigations for a stream that
exceeds ``config.stream_timeout``:

* **Detection/surfacing** (always on): the per-stream timeout is enforced
  via ``concurrent.futures.as_completed(pending, timeout=...)`` -- NOT via
  ``future.result(timeout=...)`` on an already-completed future, which can
  never raise ``TimeoutError`` and would silently make timeout enforcement
  a no-op. Any stream still not ``done()`` when the deadline elapses is
  recorded as timed-out/leaked in ``result.errors`` and logged via
  ``logger.warning`` unconditionally (not gated on ``config.verbose``),
  because a leaked background stream can keep consuming CPU/DB connections
  and skew a subsequent phase's timing -- this must not be silent.
* **Cooperative cancellation** (opt-in via ``config.cancel_on_timeout``,
  default ``False``): when enabled, every stream gets a ``threading.Event``
  exposed on ``config._stream_cancel_events`` that each spec's
  ``_execute_stream`` query loop polls between queries. On timeout, this
  method sets that stream's event so its loop can notice and return soon
  after its current query finishes -- the only safe way to make a timeout
  actually stop work without hard-killing a thread. When disabled,
  ``execute()`` explicitly resets ``config._stream_cancel_events`` to ``{}``
  (never leaving a stale dict from a prior call on a reused config object);
  each spec's cancel-event lookup also independently gates on
  ``config.cancel_on_timeout`` directly, so a stale/leftover attribute value
  can never be mistaken for this run's cancellation state.

Non-blocking shutdown (return without joining a leaked thread)
----------------------------------------------------------------
``execute()`` manages the ``ThreadPoolExecutor`` manually (no ``with``
block) so it can call ``executor.shutdown(wait=False)`` in a ``finally``
instead of relying on the context manager's implicit
``shutdown(wait=True)``. This means ``execute()`` returns as soon as its
own timeout/accounting window closes -- bounded by ``config.stream_timeout``
plus classification overhead -- rather than blocking until every submitted
thread finishes.

On the healthy path (no timeout fires), every future is already ``done()``
by the time ``as_completed()`` returns, so ``shutdown(wait=False)`` is a
no-op: there is nothing left to join, and default-timeout behavior for
healthy runs is unchanged. On the hung path, any future still not
``done()`` when the deadline elapses is *abandoned*, not killed -- Python
cannot forcibly stop a running thread. ``shutdown(wait=False)`` only stops
the executor from accepting new submissions; it does not touch threads
already running, so the leaked thread keeps executing in the background
until ``stream_fn`` itself returns (naturally, or via cooperative
cancellation if enabled) and exits.

**Zombie connection/accounting semantics** (see also
``docs/development/throughput-result-alignment.md``): a leaked stream's
database connection is owned by that stream's own ``stream_fn`` and is
closed by its own ``finally`` block whenever the thread eventually ends --
``execute()`` never touches it. Until then, the zombie thread holds an open
session and may still be issuing queries against the database after
``execute()`` -- and the whole throughput phase -- has returned; a
subsequent phase (e.g. data maintenance) that starts immediately after can
run concurrently with it. This residual hazard is why cooperative
cancellation (bounding the zombie's remaining lifetime to ~one more query)
is recommended whenever a hard stream_timeout matters operationally. TTT
and success-rate accounting are unaffected: a leaked stream was already
excluded from ``result.stream_results`` (and therefore from TTT and
``streams_successful``) under the *old* blocking behavior too -- it only
contributes to ``result.streams_executed`` and ``result.errors``, exactly
as before. What changes here is only how long ``execute()`` itself blocks
before returning, not what gets counted.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Protocol

from benchbox.utils.clock import elapsed_seconds

from .result import ThroughputResult, ThroughputStreamResult


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

        # The as_completed(timeout=...) deadline below is a single overall
        # wait bound, not a per-future one (see the NOTE at that call site).
        # Treating it as equivalent to each stream's own per-stream timeout
        # relies on every stream starting to run immediately -- true only
        # when max_workers >= num_streams (all streams submitted back-to-back
        # with no queueing). If max_workers < num_streams, later streams sit
        # queued behind earlier ones and are still charged against the same
        # t0 deadline, so a queued stream could be flagged as timed-out
        # before it ever ran a single query.
        if max_workers < config.num_streams and timeout is not None:
            logger.warning(
                f"max_workers ({max_workers}) < num_streams ({config.num_streams}) with a "
                f"stream_timeout of {timeout}s set: queued streams share the same overall "
                "deadline as immediately-started ones and may be reported as timed-out before "
                "executing a single query. Set max_workers >= num_streams (or leave it unset) "
                "for the timeout to behave as a true per-stream timeout."
            )

        # Opt-in cooperative cancellation (default OFF, behavior-preserving).
        # See module docstring "Timed-out streams" for the full design.
        cooperative_cancel = bool(getattr(config, "cancel_on_timeout", False))
        cancel_events: dict[int, threading.Event] = {}

        # Managed manually (no `with` block): the context manager's implicit
        # `__exit__` calls `shutdown(wait=True)`, which would block this
        # method's return on every submitted thread -- including a leaked
        # one that never completes. The `finally` below calls
        # `shutdown(wait=False)` instead, so a still-running (abandoned, not
        # killed) thread cannot hold `execute()` hostage. See the module
        # docstring "Non-blocking shutdown" section for the full rationale
        # and the zombie connection/accounting semantics this implies.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            # Track future -> stream_id mapping for timeout error reporting
            future_to_stream_id: dict[concurrent.futures.Future[ThroughputStreamResult], int] = {}

            if cooperative_cancel:
                cancel_events = {stream_id: threading.Event() for stream_id in range(config.num_streams)}
                # Runtime-only attribute (not a declared config field) so each
                # spec's _execute_stream query loop can poll its own stream's
                # event between queries; set() below when that stream's own
                # timeout elapses.
                config._stream_cancel_events = cancel_events  # type: ignore[attr-defined]
            else:
                # Explicitly reset (never leave stale) -- if this same config
                # object was reused from a prior execute() call that had
                # cancel_on_timeout=True and a stream timed out, that stream's
                # Event would still be set(). Without this reset, this run's
                # _resolve_cancel_event would observe the leftover dict purely
                # by presence and immediately treat an unrelated stream as
                # cancelled. Each spec's _resolve_cancel_event also gates on
                # config.cancel_on_timeout directly as a second, independent
                # guard -- see that method's docstring -- but resetting here
                # keeps the attribute itself honest for any other reader.
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
                """Apply success/failure accounting for one *completed* future.

                Shared by the main as_completed() loop below and the timeout
                fallback loop so streams_executed/streams_successful/errors
                accounting is identical regardless of which loop observed
                the future's completion.
                """
                try:
                    stream_result = completed_future.result()
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

                except Exception as e:
                    result.streams_executed += 1
                    result.errors.append(f"Stream {completed_stream_id} execution failed: {e}")
                    if config.verbose:
                        logger.error(f"Stream {completed_stream_id} execution failed: {e}")

            pending = set(future_to_stream_id.keys())

            try:
                # NOTE: `timeout` bounds this as_completed() call as a whole,
                # not any individual future.result() call. Passing it to
                # future.result(timeout=...) instead (the previous approach)
                # is a no-op once as_completed() has already yielded that
                # future as done() -- it can never raise TimeoutError there,
                # silently making per-stream timeout enforcement dead code.
                # Since every stream is submitted back-to-back immediately
                # before this loop (max_workers defaults to num_streams, i.e.
                # no queueing), a single overall deadline here is equivalent
                # to each stream's own per-stream timeout starting from when
                # it began running.
                for future in concurrent.futures.as_completed(pending, timeout=timeout):
                    stream_id = future_to_stream_id[future]
                    pending.discard(future)
                    _record_completed_future(future, stream_id)

            except concurrent.futures.TimeoutError:
                # One or more streams did not complete within `timeout`
                # seconds. Python cannot forcibly cancel a running thread, so
                # each such stream's worker may still be executing queries
                # and holding its database connection in the background
                # (leaked) -- unless cooperative cancellation is enabled,
                # which signals the stream's loop to stop soon.
                for future in list(pending):
                    stream_id = future_to_stream_id[future]

                    if future.done():
                        # Completed in the small window between the deadline
                        # firing and us reacting to it; process normally.
                        pending.discard(future)
                        _record_completed_future(future, stream_id)
                        continue

                    if cooperative_cancel:
                        cancel_events[stream_id].set()

                    result.streams_executed += 1
                    error_msg = (
                        f"Stream {stream_id} timed out after {timeout}s and has not completed. "
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
                    # Always surfaced -- NOT gated on config.verbose. A leaked
                    # background stream can keep consuming CPU/DB connections
                    # and skew a subsequent phase's timing, so this must not
                    # be silent even in non-verbose runs.
                    logger.warning(error_msg)
                    pending.discard(future)
        finally:
            # wait=False: never block this method's return on a still-running
            # (abandoned, not killed) thread. On the healthy path every
            # future is already done() by this point, so this is a no-op --
            # nothing to join, default timeout behavior for healthy runs is
            # unchanged. On the hung path, any leaked thread keeps running
            # to completion in the background; its connection is closed by
            # its own stream_fn's finally whenever that eventually happens.
            # See the module docstring "Non-blocking shutdown" section.
            executor.shutdown(wait=False)

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
