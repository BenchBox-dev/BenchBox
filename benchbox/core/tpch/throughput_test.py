"""TPC-H Throughput Test Implementation.

This module implements the TPC-H Throughput Test according to the official TPC-H
specification. The Throughput Test executes multiple concurrent query streams
to calculate the Throughput@Size metric.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner
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
    # Minimum success rate for streams (0.0-1.0). Default 0.99 = 99% must succeed.
    # TPC-H spec allows up to 1% query failures in production environments.
    min_success_rate: float = 0.99


# Backward-compatibility alias - ThroughputStreamResult is the canonical type.
TPCHThroughputStreamResult = ThroughputStreamResult


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

            # Execute concurrent streams
            StreamRunner.execute(self._execute_stream, config, result, self.logger)

            # Calculate metrics
            StreamRunner.compute_metrics(result, config, start_time)

            # TPC-H success criteria: configurable stream success rate
            # Default is 99% (allows up to 1% failures per TPC-H spec)
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

            for position, query_id in enumerate(query_permutation):
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
                    # Get the query with stream-specific parameters
                    # Use stream and position-specific seed as per TPC-H specification
                    stream_seed = seed + stream_id * 1000 + position
                    query_text = self.benchmark.get_query(
                        query_id,
                        seed=stream_seed,
                        stream_id=stream_id,
                        scale_factor=config.scale_factor,
                    )

                    # Execute the actual query against the database
                    label = f"Stream_{stream_id}_Position_{position + 1}_Query_{query_id}"
                    try:
                        # Set query context for validation
                        if hasattr(connection, "set_query_context"):
                            connection.set_query_context(query_id)

                        cursor = connection.execute(query_text)
                        rows = cursor.fetchall() if hasattr(cursor, "fetchall") else []

                        # Check for validation failures from platform adapter
                        if hasattr(cursor, "platform_result"):
                            result_dict = cursor.platform_result
                            if result_dict.get("status") == "FAILED":
                                error_msg = result_dict.get(
                                    "error", result_dict.get("row_count_validation_error", "Query validation failed")
                                )
                                raise RuntimeError(error_msg)

                        if hasattr(connection, "commit"):
                            connection.commit()
                    finally:
                        # Capture labeled SQL for dry-run preview
                        if hasattr(self, "captured_items"):
                            self.captured_items.append((label, query_text))

                    execution_time = elapsed_seconds(query_start)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": True,
                            "result_count": len(rows),
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

            stream_result.success = stream_result.queries_failed == 0

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
