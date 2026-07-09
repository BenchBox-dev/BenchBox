"""TPC-DS Throughput Test Implementation.

This module implements the TPC-DS Throughput Test according to the official TPC-DS
specification. The Throughput Test executes multiple concurrent query streams
to calculate the Throughput@Size metric.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from benchbox.core.connection import DatabaseConnection
from benchbox.core.plan_capture_phase import propagate_plan_capture_fields
from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner
from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCDSThroughputTestConfig:
    """Configuration for TPC-DS Throughput Test."""

    scale_factor: float = 1.0
    num_streams: int = 4
    base_seed: int = 42
    stream_timeout: int = 7200  # Timeout per stream in seconds (0 = no timeout)
    max_workers: Optional[int] = None
    verbose: bool = False
    # Number of queries to execute per stream (None = all queries, ~99 for TPC-DS)
    # NOTE: Per TPC-DS spec, full query set should be executed. Use subset only for testing.
    queries_per_stream: Optional[int] = None  # Default: execute all queries
    # Enable preflight validation (validates query generation before execution)
    enable_preflight: bool = True


# Backward-compatibility alias - ThroughputStreamResult is the canonical type.
TPCDSThroughputStreamResult = ThroughputStreamResult


@dataclass
class TPCDSThroughputTestResult(ThroughputResult):
    """Result of TPC-DS Throughput Test."""

    config: TPCDSThroughputTestConfig = field(kw_only=True)

    @property
    def scale_factor(self) -> float:
        """Get scale factor from config."""
        return self.config.scale_factor


class TPCDSThroughputTest:
    """TPC-DS Throughput Test implementation."""

    def __init__(
        self,
        benchmark: Any,
        connection_factory: Optional[Callable[[], Any]] = None,
        scale_factor: float = 1.0,
        num_streams: int = 4,
        verbose: bool = False,
        connection_string: Optional[str] = None,
        dialect: Optional[str] = None,
    ) -> None:
        """Initialize TPC-DS Throughput Test.

        Args:
            benchmark: TPCDSBenchmark instance
            connection_factory: Factory function to create database connections
            scale_factor: Scale factor for the benchmark
            num_streams: Number of concurrent streams
            verbose: Enable verbose logging
            connection_string: Database connection string (legacy parameter)
            dialect: SQL dialect (legacy parameter)
        """
        self.benchmark = benchmark

        # Handle legacy connection_string parameter
        if connection_string is not None:
            conn_str = connection_string  # Type narrowing for lambda
            self.connection_factory = lambda: self._create_connection_from_string(conn_str)
        elif connection_factory is not None:
            self.connection_factory = connection_factory
        else:
            # Default to local in-memory SQLite when no explicit connection source is provided.
            self.connection_factory = lambda: DatabaseConnection(sqlite3.connect(":memory:"), dialect="sqlite")

        self.config = TPCDSThroughputTestConfig(scale_factor=scale_factor, num_streams=num_streams, verbose=verbose)

        # Store target dialect for query translation
        self.target_dialect = dialect

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)
        # Captured SQL items for dry-run preview: (label, sql)
        self.captured_items: list[tuple[str, str]] = []

        # Populated by run() via _pregenerate_stream_queries() before the
        # timed concurrent window starts: {stream_id: [(stream_query, sql_or_
        # exception), ...]} aligned by position. When set, _execute_single_
        # query() consumes the cached SQL instead of regenerating inline.
        # Left as None when _execute_stream()/_execute_single_query() are
        # invoked directly (bypassing run()), preserving the historical
        # inline-generation behavior for direct/unit callers.
        self._pregenerated_queries: Optional[dict[int, list[tuple[Any, Any]]]] = None

        # Lock for concurrent stream capture
        import threading

        self._capture_lock = threading.Lock()

    def _create_connection_from_string(self, connection_string: str) -> DatabaseConnection:
        """Create a connection wrapper from a supported connection string."""
        if connection_string in {"sqlite::memory:", ":memory:", "sqlite://:memory:"}:
            return DatabaseConnection(sqlite3.connect(":memory:"), dialect="sqlite")

        if connection_string.startswith("sqlite:///"):
            db_path = connection_string.replace("sqlite:///", "", 1)
            return DatabaseConnection(sqlite3.connect(db_path), dialect="sqlite")

        raise ValueError(
            "Unsupported connection_string for TPCDSThroughputTest. Provide connection_factory for non-SQLite backends."
        )

    def run(self, config: Optional[TPCDSThroughputTestConfig] = None) -> TPCDSThroughputTestResult:
        """Execute the TPC-DS Throughput Test.

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
        # Per TPC-DS specification, Total Test Time (TTT) must be measured from when
        # the first stream begins execution until the last stream completes execution.
        # This excludes setup overhead (executor creation, future submission, preflight, etc.).
        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = TPCDSThroughputTestResult(
            config=config,
            start_time=start_time_str,
            end_time="",
            total_time=0.0,
            throughput_at_size=0.0,
            streams_executed=0,
            streams_successful=0,
            stream_results=[],
            query_throughput=0.0,
            success=True,
            errors=[],
        )

        # Logging
        try:
            if config.verbose:
                self.logger.info("Starting TPC-DS Throughput Test")
                self.logger.info(f"Number of streams: {config.num_streams}")
                self.logger.info(f"Scale factor: {config.scale_factor}")

            # Preflight: validate that selected query subsets in all streams can be generated
        except Exception:
            # Reraise any logging/prep errors
            raise

        # Pre-generate every stream's ordered SQL before the timed concurrent
        # window starts (outside try, so failures raise -- matching the
        # historical fail-fast preflight contract). This removes dsqgen
        # subprocess cost from execution_time_seconds and TTT. Left disabled
        # (falls back to inline per-query generation in _execute_single_query)
        # when enable_preflight=False, matching today's behavior for callers
        # that explicitly opt out of upfront validation/generation.
        if config.enable_preflight:
            self._pregenerated_queries = self._pregenerate_stream_queries(config)

        try:
            # Execute concurrent streams
            StreamRunner.execute(self._execute_stream, config, result, self.logger)

            # Calculate metrics
            StreamRunner.compute_metrics(result, config, start_time)

            # TPC-DS success criteria: at least 70% of streams must succeed
            success_rate = result.streams_successful / max(config.num_streams, 1)
            result.success = success_rate >= 0.7

            if config.verbose:
                self.logger.info(f"Throughput Test completed in {result.total_time:.3f}s")
                self.logger.info(f"Successful streams: {result.streams_successful}/{config.num_streams}")
                self.logger.info(f"Stream success rate: {success_rate:.2%}")
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

    def _preflight_validate_generation(self, config: TPCDSThroughputTestConfig) -> None:
        """Validate that queries can be generated for all streams.

        This validates all 99 TPC-DS queries for each stream to ensure no runtime
        generation failures. This is conservative but guarantees safety regardless
        of which queries the stream permutation algorithm selects.

        Raises RuntimeError with details if any generation fails.
        """
        failures = []

        # Log the preflight strategy
        if config.verbose:
            self.logger.info(
                f"Preflight validation: checking all 99 queries × {config.num_streams} streams "
                f"= {99 * config.num_streams} total validations"
            )

        try:
            # Use standard TPC-DS query id range: 1-99
            available_query_ids = list(range(1, 100))

            for stream_id in range(config.num_streams):
                for position, query_id in enumerate(available_query_ids):
                    stream_seed = config.base_seed + stream_id * 1000 + position
                    try:
                        _ = self.benchmark.get_query(
                            query_id, seed=stream_seed, scale_factor=config.scale_factor, dialect=self.target_dialect
                        )
                    except Exception as e:
                        failures.append(f"stream {stream_id} q{query_id} pos {position + 1}: {e}")
        except Exception as e:
            raise RuntimeError(f"Throughput preflight internal error: {e}") from e

        if failures:
            msg = (
                f"TPC-DS ThroughputTest preflight failed for {len(failures)} queries. "
                f"Examples: {', '.join(failures[:3])}"
            )
            raise RuntimeError(msg)

    def _pregenerate_stream_queries(self, config: TPCDSThroughputTestConfig) -> dict[int, list[tuple[Any, str]]]:
        """Pre-generate every stream's ordered (StreamQuery, SQL) pairs before
        the timed concurrent window starts.

        This is the real generation cache that ``_execute_single_query``
        consumes, keyed by (stream_id, position): for each stream,
        ``_build_stream_queries`` resolves the ordering/variant subset exactly
        as it does today (TPC-DS stream/permutation logic --
        ``create_standard_streams`` / ``streams.py`` -- is untouched and out
        of scope for this TODO), then each entry is generated with the
        *exact* per-position seed formula ``seed + stream_id * 1000 +
        position`` (``seed = config.base_seed + stream_id``, matching
        ``StreamRunner.execute``'s per-stream seed) via
        ``_get_stream_query_text``, so generated SQL is byte-identical to
        before -- only *when* it is generated changes.

        This supersedes ``_preflight_validate_generation`` as the source of
        truth for what actually runs: that legacy sweep iterated query IDs
        1..99 in natural order with ``stream_seed = config.base_seed +
        stream_id * 1000 + position`` -- no permutation, no variant
        selection, and (notably) missing the ``+ stream_id`` seed offset
        that real execution applies -- so it never matched the queries a
        stream actually executes. It is kept unchanged (unused by ``run()``)
        purely for API/test back-compat.

        Only called when ``config.enable_preflight`` is True; any generation
        failure raises immediately (matching the historical fail-fast
        preflight contract) before the timed window starts.
        """
        stream_queries: dict[int, list[tuple[Any, str]]] = {}
        failures: list[str] = []

        for stream_id in range(config.num_streams):
            seed = config.base_seed + stream_id
            query_subset = self._build_stream_queries(stream_id, seed, config)
            entries: list[tuple[Any, str]] = []

            for position, stream_query in enumerate(query_subset):
                stream_seed = seed + stream_id * 1000 + position
                try:
                    sql_text = self._get_stream_query_text(
                        stream_query.query_id, stream_query.variant, stream_seed, config.scale_factor
                    )
                    entries.append((stream_query, sql_text))
                except Exception as e:
                    failures.append(f"stream {stream_id} q{stream_query.query_id} pos {position + 1}: {e}")

            stream_queries[stream_id] = entries

        if failures:
            msg = (
                f"TPC-DS ThroughputTest preflight failed for {len(failures)} queries. "
                f"Examples: {', '.join(failures[:3])}"
            )
            raise RuntimeError(msg)

        return stream_queries

    def _resolve_available_query_ids(self) -> list[int]:
        try:
            all_queries = self.benchmark.get_queries()
            ids = [int(k) for k in all_queries if k.isdigit()]
            return ids if ids else list(range(1, 100))
        except Exception:
            return list(range(1, 100))

    def _resolve_query_manager(self):
        if hasattr(self.benchmark, "query_manager"):
            return self.benchmark.query_manager
        if hasattr(self.benchmark, "_impl") and hasattr(self.benchmark._impl, "query_manager"):
            return self.benchmark._impl.query_manager
        raise RuntimeError("No query_manager found - ThroughputTest requires a TPCDSBenchmark instance")

    def _build_stream_queries(self, stream_id: int, seed: int, config: TPCDSThroughputTestConfig) -> list:
        from benchbox.core.tpcds.streams import create_standard_streams

        available_query_ids = self._resolve_available_query_ids()
        query_manager = self._resolve_query_manager()

        query_range = (min(available_query_ids), max(available_query_ids)) if available_query_ids else (1, 99)
        stream_manager = create_standard_streams(
            query_manager=query_manager,
            num_streams=stream_id + 1,
            query_range=query_range,
            base_seed=seed + stream_id,
        )

        streams = stream_manager.generate_streams()
        all_queries = streams.get(stream_id, [])

        if config.queries_per_stream is not None:
            subset = all_queries[: min(config.queries_per_stream, len(all_queries))]
            if config.verbose:
                self.logger.info(
                    f"Stream {stream_id} using TPC-DS permutation with {len(subset)} queries "
                    f"(limited by queries_per_stream={config.queries_per_stream})"
                )
            return subset
        if config.verbose:
            self.logger.info(
                f"Stream {stream_id} using TPC-DS permutation with {len(all_queries)} queries (full query set)"
            )
        return all_queries

    def _cached_query_text(self, stream_id: int, position: int) -> Optional[str]:
        """Return pre-generated SQL for (stream_id, position), if available.

        Returns None when no pre-generation cache exists (enable_preflight is
        False, or _execute_stream/_execute_single_query were invoked directly
        without going through run()), signalling the caller should generate
        the query text inline instead -- exactly as it always has.
        """
        if self._pregenerated_queries is None:
            return None
        entries = self._pregenerated_queries.get(stream_id)
        if entries is None or position >= len(entries):
            return None
        return entries[position][1]

    def _get_stream_query_text(self, query_id: int, variant, stream_seed: int, scale_factor) -> str:
        if variant is not None:
            return self.benchmark.get_query(
                query_id,
                seed=stream_seed,
                scale_factor=scale_factor,
                variant=variant,
                dialect=self.target_dialect,
            )
        return self.benchmark.get_query(
            query_id, seed=stream_seed, scale_factor=scale_factor, dialect=self.target_dialect
        )

    def _run_single_stream_query(
        self, connection, query_text: str, query_display_id: str, stream_id: int
    ) -> dict[str, Any] | None:
        if hasattr(connection, "set_query_context"):
            connection.set_query_context(query_display_id, stream_id=stream_id)
        cursor = connection.execute(query_text)
        if hasattr(cursor, "fetchall"):
            cursor.fetchall()
        if hasattr(connection, "commit"):
            connection.commit()
        return getattr(cursor, "platform_result", None)

    def _execute_single_query(
        self,
        connection,
        stream_id: int,
        position: int,
        stream_query,
        seed: int,
        config: TPCDSThroughputTestConfig,
        stream_result: TPCDSThroughputStreamResult,
    ) -> None:
        query_id = stream_query.query_id
        variant = stream_query.variant
        query_display_id = f"{query_id}{variant}" if variant else str(query_id)
        query_start = mono_time()
        query_result = {
            "query_id": query_display_id,
            "position": position + 1,
            "stream_id": stream_id,
            "execution_time_seconds": 0.0,
            "success": False,
            "error": None,
            "result_count": 0,
        }

        try:
            cached_text = self._cached_query_text(stream_id, position)
            if cached_text is not None:
                query_text = cached_text
            else:
                stream_seed = seed + stream_id * 1000 + position
                query_text = self._get_stream_query_text(query_id, variant, stream_seed, config.scale_factor)
            label = f"Stream_{stream_id}_Position_{position + 1}_Query_{query_display_id}"
            try:
                platform_result = self._run_single_stream_query(connection, query_text, query_display_id, stream_id)
            finally:
                with self._capture_lock:
                    self.captured_items.append((label, query_text))

            if platform_result is not None:
                # Propagate captured plan metadata (including the internal
                # _plan_capture_key) so a combined power+throughput run can match
                # this row by its exact key rather than the ambiguous public-id
                # fallback in _attach_captured_plans.
                propagate_plan_capture_fields(platform_result, query_result)

            query_result.update(
                {
                    "execution_time_seconds": elapsed_seconds(query_start),
                    "success": True,
                    "result_count": 0,
                }
            )
            stream_result.queries_successful += 1
        except Exception as e:
            query_result.update(
                {
                    "execution_time_seconds": elapsed_seconds(query_start),
                    "success": False,
                    "error": str(e),
                }
            )
            stream_result.queries_failed += 1
            if "Template substitution error" not in str(e) and config.verbose:
                self.logger.warning(f"Stream {stream_id} Query {query_id} failed: {e}")

        stream_result.query_results.append(query_result)
        stream_result.queries_executed += 1

    def _finalize_stream_success(
        self, stream_id: int, stream_result: TPCDSThroughputStreamResult, config: TPCDSThroughputTestConfig
    ) -> None:
        if stream_result.queries_executed == 0:
            stream_result.success = False
            if config.verbose:
                self.logger.info(f"Stream {stream_id} completed: no queries executed")
            return

        success_rate = stream_result.queries_successful / stream_result.queries_executed
        stream_result.success = success_rate >= 0.7
        if config.verbose:
            self.logger.info(
                f"Stream {stream_id} completed: "
                f"{stream_result.queries_successful}/{stream_result.queries_executed} successful "
                f"(success rate: {success_rate:.2%})"
            )

    def _close_stream_connection(self, connection, stream_id: int, config: TPCDSThroughputTestConfig) -> None:
        if connection is None:
            return
        try:
            connection.close()
        except Exception as close_error:
            if config.verbose:
                self.logger.warning(f"Failed to close connection for stream {stream_id}: {close_error}")

    def _execute_stream(
        self, stream_id: int, seed: int, config: TPCDSThroughputTestConfig
    ) -> TPCDSThroughputStreamResult:
        """Execute a single TPC-DS throughput test stream."""
        start_time = mono_time()
        stream_result = TPCDSThroughputStreamResult(
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

            connection = self.connection_factory()

            # When run() pre-generated this stream (the normal path with
            # enable_preflight=True), reuse its already-resolved ordering
            # instead of calling _build_stream_queries() again inside the
            # timed window -- that call also (re-)invokes stream permutation
            # generation, which this avoids repeating here entirely.
            cached_entries = (
                self._pregenerated_queries.get(stream_id) if self._pregenerated_queries is not None else None
            )
            if cached_entries is not None:
                query_subset = [stream_query for stream_query, _sql in cached_entries]
            else:
                query_subset = self._build_stream_queries(stream_id, seed, config)

            for position, stream_query in enumerate(query_subset):
                self._execute_single_query(connection, stream_id, position, stream_query, seed, config, stream_result)

            self._finalize_stream_success(stream_id, stream_result, config)
        except Exception as e:
            stream_result.error = str(e)
            stream_result.success = False
            if config.verbose:
                self.logger.error(f"Stream {stream_id} failed: {e}")
        finally:
            self._close_stream_connection(connection, stream_id, config)
            stream_result.end_time = mono_time()
            stream_result.duration = stream_result.end_time - stream_result.start_time

        return stream_result

    def validate_results(self, result: TPCDSThroughputTestResult) -> bool:
        """Validate Throughput Test results against TPC-DS specification.

        Args:
            result: Throughput Test results to validate

        Returns:
            True if results are valid, False otherwise
        """
        if not result.success:
            return False

        # TPC-DS requires at least 70% stream success rate
        if result.config.num_streams > 0:
            stream_success_rate = result.streams_successful / result.config.num_streams
            if stream_success_rate < 0.7:
                return False

        return not result.throughput_at_size <= 0
