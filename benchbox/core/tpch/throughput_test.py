"""TPC-H Throughput Test Implementation.

This module implements the TPC-H Throughput Test according to the official TPC-H
specification. The Throughput Test executes multiple concurrent query streams
to calculate the Throughput@Size metric.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import concurrent.futures
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from benchbox.core.plan_capture_phase import propagate_plan_capture_fields
from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner
from benchbox.core.validation.query_validation import (
    clear_reference_seed_context,
    set_reference_seed_context,
)
from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCHThroughputTestConfig:
    """Configuration for TPC-H Throughput Test."""

    scale_factor: float = 1.0
    num_streams: int = 2
    base_seed: int = 42
    stream_timeout: int = 3600  # Timeout per stream in seconds (0 = no timeout)
    max_workers: Optional[int] = None
    verbose: bool = False
    # Opt-in cooperative cancellation (default OFF, behavior-preserving): when
    # True, a timed-out stream (see StreamRunner.execute()) gets a
    # threading.Event signalled so its query loop can notice and stop between
    # queries instead of continuing to run in the background indefinitely.
    # Python cannot forcibly cancel a running thread, so this is opt-in and
    # never hard-kills anything -- see benchbox/core/throughput/runner.py's
    # module docstring ("Timed-out streams") for the full design.
    cancel_on_timeout: bool = False
    # Minimum success rate for streams (0.0-1.0). Default 0.99 = 99% must succeed.
    #
    # Spec citation: NOT derived from a TPC-H "acceptable failure rate" clause
    # -- no such partial-success allowance exists. TPC-H specification 5.1.1.6
    # defines: "A failed run is defined as a run that did not complete
    # successfully due to unforeseen system failures," i.e. an
    # audited/compliant run requires every stream to complete successfully.
    # 0.99 is a BenchBox-internal tolerance for treating a run as "usable" for
    # iterative development/CI despite an occasional stream failure; it is NOT
    # an official TPC-H compliance gate, and results with
    # streams_successful < num_streams are not eligible for TPC-H-compliant/
    # audited reporting regardless of this setting.
    min_success_rate: float = 0.99


# Backward-compatibility alias - ThroughputStreamResult is the canonical type.
TPCHThroughputStreamResult = ThroughputStreamResult


def _derive_query_seed(seed: int, stream_id: int, position: int) -> int:
    """Per-query qgen seed for one throughput stream position.

    ``seed`` is the per-stream base seed StreamRunner hands to
    ``_execute_stream`` (``config.base_seed + stream_id`` -- see
    ``benchbox.core.throughput.runner``). The SINGLE definition of the
    per-position formula: query generation (pre-generation pass and the
    ``_resolve_query_text`` inline fallback) and the reference-seed
    validation context in ``_execute_stream`` must all derive the seed
    through this helper so validation can never silently desynchronize
    from the SQL that was actually generated.
    """
    return seed + stream_id * 1000 + position


def _count_cursor_rows(cursor: Any) -> int:
    """Return a row count without importing benchbox.platforms from core.

    The layering convention `utils < core < platforms < cli` forbids `core`
    importing from `platforms`, so this duck-types on the `row_count()`
    method `PlatformAdapterCursor` exposes (see
    `benchbox.platforms.base.connection_wrappers`) instead of importing
    `count_query_rows` directly. On the real throughput path the cursor IS
    a `PlatformAdapterCursor`, so this always resolves there and the
    "never materialize rows just to count them" behavior is preserved.

    The fallback below only serves raw DB-API cursors / test doubles that
    lack `row_count()`, and mirrors `count_query_rows`'s truthfulness rule:
    a `-1` (unknown) rowcount must never be reported as a count.
    """
    counter = getattr(cursor, "row_count", None)
    if callable(counter):
        return counter()

    rowcount = getattr(cursor, "rowcount", None)
    if isinstance(rowcount, int) and rowcount >= 0:
        return rowcount
    return len(cursor.fetchall())


@dataclass
class TPCHThroughputTestResult(ThroughputResult):
    """Result of TPC-H Throughput Test."""

    config: TPCHThroughputTestConfig = field(kw_only=True)

    @property
    def scale_factor(self) -> float:
        """Get scale factor from config."""
        return self.config.scale_factor


class TPCHThroughputTest:
    """TPC-H Throughput Test implementation."""

    def __init__(
        self,
        benchmark: Any,
        connection_factory: Callable[[], Any],
        scale_factor: float = 1.0,
        num_streams: int = 2,
        verbose: bool = False,
    ) -> None:
        """Initialize TPC-H Throughput Test.

        Args:
            benchmark: TPCHBenchmark instance
            connection_factory: Factory function to create database connections
            scale_factor: Scale factor for the benchmark
            num_streams: Number of concurrent streams
            verbose: Enable verbose logging
        """
        self.benchmark = benchmark
        self.connection_factory = connection_factory
        self.config = TPCHThroughputTestConfig(scale_factor=scale_factor, num_streams=num_streams, verbose=verbose)

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)

        # Initialize captured items for dry-run SQL preview
        self.captured_items: list[tuple[str, str]] = []

        # Populated by run() via _pregenerate_stream_queries() before the timed
        # concurrent window starts. When set, _execute_stream() consumes this
        # pre-built SQL instead of generating inline. Left as None when
        # _execute_stream() is invoked directly (bypassing run()), which
        # preserves the historical inline-generation behavior for direct/unit
        # callers and test doubles.
        self._pregenerated_queries: Optional[dict[int, list[Any]]] = None

    def run(self, config: Optional[TPCHThroughputTestConfig] = None) -> TPCHThroughputTestResult:
        """Execute the TPC-H Throughput Test.

        Args:
            config: Optional test configuration (uses default if not provided)

        Returns:
            Throughput Test results with Throughput@Size metric

        Raises:
            RuntimeError: If Throughput Test execution fails
        """
        if config is None:
            config = self.config

        # NOTE: start_time here is for test metadata only, not for TTT calculation.
        # Per TPC-H specification, Total Test Time (TTT) must be measured from when
        # the first stream begins execution until the last stream completes execution.
        # This excludes setup overhead (executor creation, future submission, etc.).
        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = TPCHThroughputTestResult(
            config=config,
            start_time=start_time_str,
            end_time="",
            total_time=0.0,
            throughput_at_size=0.0,
            streams_executed=0,
            streams_successful=0,
            query_throughput=0.0,
        )

        try:
            if config.verbose:
                self.logger.info("Starting TPC-H Throughput Test")
                self.logger.info(f"Number of streams: {config.num_streams}")
                self.logger.info(f"Scale factor: {config.scale_factor}")

            # Pre-generate every stream's ordered SQL text BEFORE the timed
            # concurrent window starts. This removes qgen subprocess/tempdir
            # cost from execution_time_seconds and TTT -- _execute_stream()
            # only performs connection use and DB execution once this is set.
            self._pregenerated_queries = self._pregenerate_stream_queries(config)

            # Execute concurrent streams
            StreamRunner.execute(self._execute_stream, config, result, self.logger)

            # Calculate metrics
            StreamRunner.compute_metrics(result, config, start_time)

            # TPC-H success criteria: configurable stream success rate (see
            # TPCHThroughputTestConfig.min_success_rate for the spec citation
            # -- this default is a BenchBox tolerance, not an official gate).
            if config.num_streams > 0:
                success_rate = result.streams_successful / config.num_streams
                result.success = success_rate >= config.min_success_rate
            else:
                result.success = False

            if config.verbose:
                self.logger.info(f"Throughput Test completed in {result.total_time:.3f}s")
                self.logger.info(f"Successful streams: {result.streams_successful}/{config.num_streams}")
                if config.num_streams > 0:
                    success_rate = result.streams_successful / config.num_streams
                    self.logger.info(
                        f"Stream success rate: {success_rate:.2%} (threshold: {config.min_success_rate:.2%})"
                    )
                self.logger.info(f"Throughput@Size: {result.throughput_at_size:.2f}")
                self.logger.info(f"Query throughput: {result.query_throughput:.2f} queries/sec")

            return result

        except Exception as e:
            result.total_time = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Throughput Test execution failed: {e}")

            if config.verbose:
                self.logger.error(f"Throughput Test failed: {e}")

            return result

    def _pregenerate_stream_queries(self, config: TPCHThroughputTestConfig) -> dict[int, list[Any]]:
        """Pre-generate ordered SQL text for every stream before the timed window.

        Builds a ``{stream_id: [sql_or_exception, ...]}`` map (one entry per
        permutation position) using the *exact* per-stream, per-position seed
        formula ``seed + stream_id * 1000 + position`` that ``_execute_stream``
        has always used, so generated SQL is byte-identical to before -- only
        *when* it is generated changes.

        Deviation from the TODO's literal instruction: the native
        ``qgen -p <stream>`` batch path (``TPCHStreamManager.
        _generate_stream_queries_qgen``) seeds its single subprocess call with
        ``rng_seed + stream_id`` and lets qgen derive all 22 per-query seeds
        internally from that ONE value (see ``qgen.c`` main(): ``Seed[0] =
        rndm; Seed[i] = NextRand(Seed[i-1])`` for i=1..22, indexed by query
        number). That is a fundamentally different Park-Miller LCG seed chain
        than this throughput test's per-*position* seed convention. Routing
        through the batch path would silently change every generated query's
        substitution parameters -- a correctness regression the TODO's own
        ``must_preserve`` explicitly forbids. So per-query generation is kept
        (via the existing ``self.benchmark.get_query`` path), but moved
        entirely out of the timed loop and parallelized across streams here;
        see ``QGenBinary._ensure_work_dir`` (queries.py) for the complementary
        fix that removes the per-call temp-dir + dists.dss copy overhead this
        TODO also flagged.

        Generation failures are captured per-position (not raised) so a
        single bad query still only fails that one query during execution,
        matching today's per-query fault isolation in ``_execute_stream``.
        """
        from benchbox.core.tpch.streams import TPCHStreams

        def _generate_one_stream(stream_id: int) -> tuple[int, list[Any]]:
            seed = config.base_seed + stream_id
            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]
            sql_list: list[Any] = []
            for position, query_id in enumerate(query_permutation):
                stream_seed = _derive_query_seed(seed, stream_id, position)
                try:
                    sql_list.append(
                        self.benchmark.get_query(
                            query_id,
                            seed=stream_seed,
                            stream_id=stream_id,
                            scale_factor=config.scale_factor,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - deferred to per-query fault isolation
                    sql_list.append(exc)
            return stream_id, sql_list

        stream_queries: dict[int, list[Any]] = {}
        if config.num_streams <= 0:
            return stream_queries

        max_workers = max(1, config.max_workers or config.num_streams)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_generate_one_stream, sid) for sid in range(config.num_streams)]
            for future in concurrent.futures.as_completed(futures):
                stream_id, sql_list = future.result()
                stream_queries[stream_id] = sql_list

        return stream_queries

    def _resolve_query_text(
        self,
        pregenerated: Optional[list[Any]],
        position: int,
        stream_id: int,
        seed: int,
        query_id: int,
        config: TPCHThroughputTestConfig,
    ) -> str:
        """Return this position's SQL: pre-generated if available, else inline.

        Re-raises a cached generation failure so it still only fails this one
        query, matching the per-query fault isolation _execute_stream has
        always had.
        """
        if pregenerated is not None:
            pre = pregenerated[position]
            if isinstance(pre, BaseException):
                raise pre
            return pre

        # Fall back to inline generation (_execute_stream called directly,
        # bypassing run()'s pre-generation pass).
        stream_seed = _derive_query_seed(seed, stream_id, position)
        return self.benchmark.get_query(
            query_id,
            seed=stream_seed,
            stream_id=stream_id,
            scale_factor=config.scale_factor,
        )

    def _resolve_cancel_event(self, config: TPCHThroughputTestConfig, stream_id: int) -> Optional[threading.Event]:
        """Return this stream's cooperative-cancel event, if any.

        Gated directly on ``config.cancel_on_timeout``: when it is not the
        literal ``True`` (the default is ``False``, and a malformed/mock
        config's attribute is neither), this always returns None and the
        per-query loop never checks for cancellation, preserving today's
        behavior exactly -- regardless of what ``config._stream_cancel_events``
        currently holds. This guard is deliberately independent of
        (belt-and-suspenders alongside) ``StreamRunner.execute()`` resetting
        ``_stream_cancel_events`` to ``{}`` when cooperative cancel is
        disabled: if a config object is reused across runs (e.g. run 1 with
        ``cancel_on_timeout=True`` where a stream times out and its Event
        gets ``set()``, then run 2 reusing the same config object with
        ``cancel_on_timeout=False``), a stale/leftover ``_stream_cancel_events``
        entry can never take effect here even if that reset were ever
        skipped or bypassed.

        Also requires ``_stream_cancel_events`` to be a genuine ``dict`` and
        the resolved per-stream entry to be a genuine ``threading.Event`` --
        not merely truthy -- so a malformed config (e.g. a ``MagicMock`` in a
        test double, where every attribute access is truthy by default) can
        never be mistaken for a real cancellation signal.
        """
        if getattr(config, "cancel_on_timeout", False) is not True:
            return None
        cancel_events = getattr(config, "_stream_cancel_events", None)
        if not isinstance(cancel_events, dict):
            return None
        cancel_event = cancel_events.get(stream_id)
        return cancel_event if isinstance(cancel_event, threading.Event) else None

    def _cooperative_cancel_requested(
        self,
        cancel_event: Optional[threading.Event],
        config: TPCHThroughputTestConfig,
        stream_id: int,
        position: int,
        total_queries: int,
    ) -> bool:
        """Check + log a cooperative-cancel request for one loop iteration.

        Extracted from ``_execute_stream`` purely to keep that method's
        cyclomatic complexity within the linter's threshold; behavior is
        identical to an inline check.
        """
        if cancel_event is None or not cancel_event.is_set():
            return False
        if config.verbose:
            self.logger.warning(
                f"Stream {stream_id} cooperative cancel signalled; stopping after {position}/{total_queries} queries"
            )
        return True

    def _finalize_stream_outcome(
        self, stream_result: TPCHThroughputStreamResult, cancelled: bool, total_queries: int
    ) -> None:
        """Set final `success`/`error` once the per-query loop has finished.

        A cooperatively-cancelled stream (see ``_cooperative_cancel_requested``)
        never counts as successful, regardless of how many of its queries
        that did run happened to succeed -- it stopped before completing its
        permutation. Extracted from ``_execute_stream`` to keep that method's
        cyclomatic complexity within the linter's threshold.
        """
        if cancelled:
            stream_result.success = False
            stream_result.error = (
                f"Stream cancelled cooperatively after timeout "
                f"({stream_result.queries_executed}/{total_queries} queries completed)"
            )
        else:
            stream_result.success = stream_result.queries_failed == 0

    def _execute_stream(
        self, stream_id: int, seed: int, config: TPCHThroughputTestConfig
    ) -> TPCHThroughputStreamResult:
        """Execute a single throughput test stream.

        Args:
            stream_id: Stream identifier
            seed: Random seed for this stream
            config: Test configuration

        Returns:
            Stream execution result
        """
        start_time = mono_time()

        stream_result = TPCHThroughputStreamResult(
            stream_id=stream_id,
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            queries_executed=0,
            queries_successful=0,
            queries_failed=0,
        )

        connection = None
        try:
            if config.verbose:
                self.logger.info(f"Starting stream {stream_id} with seed {seed}")

            # Create connection for this stream
            connection = self.connection_factory()

            # Execute all 22 TPC-H queries in proper TPC-H permutation order for this stream
            from benchbox.core.tpch.streams import TPCHStreams

            # Use stream-specific permutation from TPC-H specification
            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

            if config.verbose:
                self.logger.info(f"Stream {stream_id} using TPC-H permutation: {query_permutation}")

            # If run() pre-generated this stream's SQL (the normal path), use
            # it; otherwise (e.g. _execute_stream() called directly, bypassing
            # run()) fall back to inline generation exactly as before.
            pregenerated = self._pregenerated_queries.get(stream_id) if self._pregenerated_queries is not None else None

            # Opt-in cooperative cancellation (config.cancel_on_timeout,
            # default OFF): StreamRunner.execute() sets this stream's event
            # when its per-stream timeout elapses. Checked once per query so
            # a timed-out stream can stop soon instead of running unbounded
            # in the background. See runner.py's module docstring.
            cancel_event = self._resolve_cancel_event(config, stream_id)

            # Reference seed for this scale factor (None if scale_factor has no
            # pinned reference, e.g. != 1.0) -- used below to tell QueryValidator
            # whether EACH query's derived seed (seed + stream_id*1000 + position,
            # same formula _resolve_query_text() uses to generate the SQL; not
            # re-derived here, just re-read for validation-context purposes)
            # matches the reference answer set, so parameter-sensitive queries
            # (Q11/16/18/20) can be excluded instead of EXACT-failed when it
            # doesn't. See benchbox.core.validation.query_validation.
            from benchbox.core.tpch.benchmark import get_reference_seed

            reference_seed = get_reference_seed(config.scale_factor)

            cancelled = False
            for position, query_id in enumerate(query_permutation):
                if self._cooperative_cancel_requested(
                    cancel_event, config, stream_id, position, len(query_permutation)
                ):
                    cancelled = True
                    break

                query_start = mono_time()
                query_result = {
                    "query_id": query_id,
                    "position": position + 1,
                    "stream_id": stream_id,
                    "execution_time_seconds": 0.0,
                    "success": False,
                    "error": None,
                    "result_count": 0,
                }

                try:
                    query_text = self._resolve_query_text(pregenerated, position, stream_id, seed, query_id, config)

                    # Execute the actual query against the database
                    label = f"Stream_{stream_id}_Position_{position + 1}_Query_{query_id}"
                    try:
                        # Set query context for validation
                        if hasattr(connection, "set_query_context"):
                            connection.set_query_context(query_id)

                        # Tell QueryValidator whether THIS query's derived seed
                        # (_derive_query_seed -- the same single definition query
                        # generation uses, so validation can never desynchronize
                        # from the generated SQL) matches the pinned reference
                        # seed -- lets parameter-sensitive queries (Q11/16/18/20)
                        # be excluded instead of EXACT-failed when the derivation
                        # doesn't happen to reproduce the reference answer set.
                        # Cleared in the finally below regardless of outcome so it
                        # never leaks into unrelated validate_query_result() calls
                        # on this thread.
                        stream_seed = _derive_query_seed(seed, stream_id, position)
                        set_reference_seed_context(stream_seed == reference_seed)

                        cursor = connection.execute(query_text)

                        # Check for validation failures from platform adapter
                        if hasattr(cursor, "platform_result"):
                            result_dict = cursor.platform_result
                            if result_dict.get("status") == "FAILED":
                                error_msg = result_dict.get(
                                    "error", result_dict.get("row_count_validation_error", "Query validation failed")
                                )
                                raise RuntimeError(error_msg)
                            # Propagate captured plan metadata (including the internal
                            # _plan_capture_key) so a combined power+throughput run can
                            # match this row by its exact key rather than the ambiguous
                            # public-id fallback in _attach_captured_plans.
                            propagate_plan_capture_fields(result_dict, query_result)

                        if hasattr(connection, "commit"):
                            connection.commit()
                    finally:
                        clear_reference_seed_context()
                        # Capture labeled SQL for dry-run preview
                        if hasattr(self, "captured_items"):
                            self.captured_items.append((label, query_text))

                    # _count_cursor_rows() reads the adapter-reported count
                    # directly (when available) instead of re-materializing
                    # the result set via fetchall() a second time - see
                    # PlatformAdapterCursor.row_count() in connection_wrappers.py.
                    # Counted before elapsed_seconds() (matching the TPC-DS
                    # driver's _run_single_stream_query): a raw DB-API
                    # cursor/test double without row_count() falls through to
                    # len(cursor.fetchall()), which does real materialization
                    # work, so that cost must stay inside the timed window
                    # rather than being excluded from execution_time_seconds.
                    result_count = _count_cursor_rows(cursor)
                    execution_time = elapsed_seconds(query_start)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": True,
                            "result_count": result_count,
                        }
                    )

                    stream_result.queries_successful += 1

                except Exception as e:
                    execution_time = elapsed_seconds(query_start)
                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": False,
                            "error": str(e),
                        }
                    )

                    stream_result.queries_failed += 1

                    if config.verbose:
                        self.logger.error(f"Stream {stream_id} Query {query_id} failed: {e}")

                stream_result.query_results.append(query_result)
                stream_result.queries_executed += 1

            self._finalize_stream_outcome(stream_result, cancelled, len(query_permutation))

            if config.verbose:
                self.logger.info(
                    f"Stream {stream_id} completed: "
                    f"{stream_result.queries_successful}/{stream_result.queries_executed} successful"
                )

        except Exception as e:
            stream_result.error = str(e)
            stream_result.success = False

            if config.verbose:
                self.logger.error(f"Stream {stream_id} failed: {e}")

        finally:
            # Ensure connection is always closed, even on exception
            if connection is not None:
                try:
                    connection.close()
                except Exception as close_error:
                    if config.verbose:
                        self.logger.warning(f"Failed to close connection for stream {stream_id}: {close_error}")

            # Record end time and duration
            stream_result.end_time = mono_time()
            stream_result.duration = stream_result.end_time - stream_result.start_time

        return stream_result

    def validate_results(self, result: TPCHThroughputTestResult) -> bool:
        """Validate Throughput Test results against TPC-H specification.

        Args:
            result: Throughput Test results to validate

        Returns:
            True if results are valid, False otherwise
        """
        if not result.success:
            return False

        if result.streams_successful != result.config.num_streams:
            return False

        if result.throughput_at_size <= 0:
            return False

        # Ensure all streams executed all 22 queries
        return all(stream_result.queries_executed == 22 for stream_result in result.stream_results)
