"""TPC Common Test Patterns and Utilities

This module provides common test execution patterns and utilities that are shared
between TPC-H and TPC-DS implementations. It includes stream execution management,
query permutation, parameter substitution, transaction management, and result aggregation.

Following TPC specification requirements for:
- Stream independence and isolation
- Proper query parameter generation
- Concurrent execution management
- Result aggregation and validation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import concurrent.futures
import logging
import random
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from benchbox.utils.clock import elapsed_seconds, mono_time

# Suppress specific warnings for cleaner output
warnings.filterwarnings("ignore", category=ResourceWarning)


def generate_official_benchmark_audit_trail(
    *,
    result: Any,
    benchmark_title: str,
    benchmark_slug: str,
    qph_label: str,
    qph_attr: str,
    output_file: Optional[Union[str, Path]] = None,
) -> Path:
    """Write the shared audit trail format used by official TPC benchmarks."""
    if output_file is None:
        if result.config.output_dir:
            output_dir = result.config.output_dir
        else:
            output_dir = Path.cwd() / "benchmark_results"
        output_file = output_dir / f"{benchmark_slug}_audit_trail_{int(time.time())}.txt"

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(f"{benchmark_title} Official Benchmark Audit Trail\n")
        file_obj.write("=" * 50 + "\n\n")
        file_obj.write(f"Scale Factor: {result.config.scale_factor}\n")
        file_obj.write(f"Number of Streams: {result.config.num_streams}\n")
        file_obj.write(f"Start Time: {result.start_time}\n")
        file_obj.write(f"End Time: {result.end_time}\n")
        file_obj.write(f"Total Time: {result.total_time:.3f} seconds\n\n")

        file_obj.write(f"Power@Size: {result.power_at_size:.2f}\n")
        file_obj.write(f"Throughput@Size: {result.throughput_at_size:.2f}\n")
        file_obj.write(f"{qph_label}: {getattr(result, qph_attr):.2f}\n\n")

        file_obj.write(f"Success: {result.success}\n")
        if result.errors:
            file_obj.write("Errors:\n")
            for error in result.errors:
                file_obj.write(f"  - {error}\n")

    return output_path


class ExecutionStatus(Enum):
    """Execution status for queries and streams."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryPolicy(Enum):
    """Retry policy for failed operations."""

    NONE = "none"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_DELAY = "fixed_delay"
    LINEAR_BACKOFF = "linear_backoff"


@dataclass
class QueryResult:
    """Result of a query execution."""

    query_id: Union[int, str]
    stream_id: Optional[int] = None
    execution_time: float = 0.0
    status: ExecutionStatus = ExecutionStatus.PENDING
    error: Optional[str] = None
    row_count: int = 0
    results: Optional[list[Any]] = None
    parameters: Optional[dict[str, Any]] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0

    def __post_init__(self) -> None:
        if self.start_time is not None and self.end_time is not None:
            self.execution_time = self.end_time - self.start_time


@dataclass
class StreamResult:
    """Result of a stream execution."""

    stream_id: int
    queries: list[QueryResult] = field(default_factory=list)
    total_execution_time: float = 0.0
    status: ExecutionStatus = ExecutionStatus.PENDING
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def __post_init__(self) -> None:
        if self.start_time is not None and self.end_time is not None:
            self.total_execution_time = self.end_time - self.start_time

    @property
    def successful_queries(self) -> int:
        """Number of successfully completed queries."""
        return sum(1 for q in self.queries if q.status == ExecutionStatus.COMPLETED)

    @property
    def failed_queries(self) -> int:
        """Number of failed queries."""
        return sum(1 for q in self.queries if q.status == ExecutionStatus.FAILED)


@dataclass
class PermutationConfig:
    """Configuration for query permutation."""

    mode: str = "random"  # "random", "sequential", "tpc_standard"
    seed: Optional[int] = None
    ensure_unique: bool = True
    respect_dependencies: bool = False
    dependency_groups: Optional[list[list[int]]] = None


@dataclass
class StreamConfig:
    """Configuration for a query stream."""

    stream_id: int
    query_ids: list[Union[int, str]]
    permutation_config: PermutationConfig = field(default_factory=PermutationConfig)
    parameter_seed: Optional[int] = None
    isolation_level: str = "READ_COMMITTED"
    timeout: Optional[float] = None
    retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL_BACKOFF
    max_retries: int = 3


@runtime_checkable
class DBCursor(Protocol):
    """Protocol for database cursors."""

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Fetch all results from cursor."""
        ...

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        """Fetch one result from cursor."""
        ...

    def close(self) -> None:
        """Close the cursor."""
        ...


@runtime_checkable
class DatabaseConnection(Protocol):
    """Protocol for database connections."""

    def execute(self, query: str, params: Optional[list[Any]] = None) -> "DBCursor":
        """Execute a query and return cursor."""
        ...

    def fetchall(self, cursor: "DBCursor") -> list[tuple[Any, ...]]:
        """Fetch all results from cursor."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


class QueryPermutator:
    """Creates TPC-compliant query permutations."""

    def __init__(self, config: PermutationConfig) -> None:
        """Initialize permutator with configuration."""
        self.config = config
        self.random_generator = random.Random(config.seed)
        self.logger = logging.getLogger(__name__)

    def generate_permutation(self, query_ids: list[Union[int, str]]) -> list[Union[int, str]]:
        """Generate a permutation of query IDs based on configuration."""
        if self.config.mode == "sequential":
            return self._sequential_permutation(query_ids)
        elif self.config.mode == "random":
            return self._random_permutation(query_ids)
        elif self.config.mode == "tpc_standard":
            return self._tpc_standard_permutation(query_ids)
        else:
            raise ValueError(f"Unknown permutation mode: {self.config.mode}")

    def _sequential_permutation(self, query_ids: list[Union[int, str]]) -> list[Union[int, str]]:
        """Generate sequential permutation."""
        return sorted(query_ids)

    def _random_permutation(self, query_ids: list[Union[int, str]]) -> list[Union[int, str]]:
        """Generate random permutation."""
        permuted = query_ids.copy()
        # Reset seed for consistent results
        if self.config.seed is not None:
            self.random_generator.seed(self.config.seed)
        self.random_generator.shuffle(permuted)
        return permuted

    def _tpc_standard_permutation(self, query_ids: list[Union[int, str]]) -> list[Union[int, str]]:
        """Generate TPC-compliant permutation using Fisher-Yates shuffle."""
        n = len(query_ids)
        if n <= 1:
            return query_ids.copy()

        permuted = query_ids.copy()

        # Fisher-Yates shuffle with deterministic seed
        for i in range(n - 1, 0, -1):
            if self.config.seed is not None:
                # Use seed-based deterministic "random" selection
                j = (self.config.seed + i * 17 + i * i * 7) % (i + 1)
            else:
                j = self.random_generator.randint(0, i)

            permuted[i], permuted[j] = permuted[j], permuted[i]

        return permuted

    def validate_permutation(self, original: list[Union[int, str]], permuted: list[Union[int, str]]) -> bool:
        """Validate that permutation contains all original elements."""
        if len(original) != len(permuted):
            return False

        if self.config.ensure_unique and len(set(permuted)) != len(permuted):
            return False

        return sorted(original) == sorted(permuted)


class ParameterManager:
    """Handles query parameter substitution with seeds."""

    def __init__(self, base_seed: Optional[int] = None) -> None:
        """Initialize parameter manager."""
        self.base_seed = base_seed or int(mono_time() * 1000) % 2**31
        self.logger = logging.getLogger(__name__)
        self._parameter_cache: dict[str, Any] = {}

    def generate_parameters(
        self,
        query_id: Union[int, str],
        stream_id: Optional[int] = None,
        scale_factor: float = 1.0,
        custom_seed: Optional[int] = None,
    ) -> dict[str, Any]:
        """Generate parameters for a query with deterministic seeding."""
        # Create unique seed for this query instance
        effective_seed = custom_seed or self._compute_seed(query_id, stream_id)

        # Use cache key to avoid recomputation
        cache_key = f"{query_id}_{stream_id}_{effective_seed}_{scale_factor}"
        if cache_key in self._parameter_cache:
            return self._parameter_cache[cache_key].copy()

        # Generate parameters
        rng = random.Random(effective_seed)
        parameters = self._generate_query_parameters(query_id, rng, scale_factor)

        # Cache the result
        self._parameter_cache[cache_key] = parameters.copy()
        return parameters

    def _compute_seed(self, query_id: Union[int, str], stream_id: Optional[int]) -> int:
        """Compute deterministic seed for query/stream combination."""
        query_hash = hash(str(query_id)) % 2**31
        stream_hash = hash(str(stream_id)) % 2**31 if stream_id is not None else 0
        return (self.base_seed + query_hash + stream_hash) % 2**31

    def _generate_query_parameters(
        self, query_id: Union[int, str], rng: random.Random, scale_factor: float
    ) -> dict[str, Any]:
        """Generate query-specific parameters."""
        # This is a basic implementation - real TPC implementations
        # would have query-specific parameter generation logic
        parameters = {
            "scale_factor": scale_factor,
            "query_id": query_id,
            "random_seed": rng.randint(1, 2**31 - 1),
            "generated_at": time.time(),
        }

        # Add some common TPC parameters
        parameters.update(
            {
                "date_offset": rng.randint(1, 365),
                "percentage": rng.uniform(0.01, 0.99),
                "limit_rows": rng.randint(1, 100),
                "category_id": rng.randint(1, 50),
                "region_id": rng.randint(1, 10),
            }
        )

        return parameters

    def clear_cache(self) -> None:
        """Clear parameter cache."""
        self._parameter_cache.clear()


class TransactionManager:
    """Manages database transactions and isolation."""

    def __init__(self, connection: DatabaseConnection) -> None:
        """Initialize transaction manager."""
        self.connection = connection
        self.logger = logging.getLogger(__name__)
        self._transaction_active = False
        self._lock = threading.Lock()

    @contextmanager
    def transaction(self, isolation_level: str = "READ_COMMITTED", timeout: Optional[float] = None) -> Iterator[Any]:
        """Context manager for database transactions."""
        # Check for nested transaction before acquiring lock to avoid deadlock
        if self._transaction_active:
            raise RuntimeError("Transaction already active")

        with self._lock:
            # Double-check after acquiring lock (for thread safety)
            if self._transaction_active:
                raise RuntimeError("Transaction already active")

            self._transaction_active = True
            start_time = mono_time()

            try:
                # Set isolation level if supported
                self._set_isolation_level(isolation_level)

                yield self.connection

                # Check timeout
                if timeout and (elapsed_seconds(start_time)) > timeout:
                    raise TimeoutError(f"Transaction exceeded timeout of {timeout} seconds")

                self.connection.commit()
                self.logger.debug("Transaction committed successfully")

            except Exception as e:
                self.logger.error(f"Transaction failed, rolling back: {e}")
                try:
                    self.connection.rollback()
                except Exception as rollback_error:
                    self.logger.error(f"Rollback failed: {rollback_error}")
                raise
            finally:
                self._transaction_active = False

    def _set_isolation_level(self, isolation_level: str) -> None:
        """Set transaction isolation level."""
        # This is database-specific - would need implementation for each DB
        isolation_commands = {
            "READ_UNCOMMITTED": "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
            "READ_COMMITTED": "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "REPEATABLE_READ": "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
            "SERIALIZABLE": "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        }

        if isolation_level in isolation_commands:
            try:
                self.connection.execute(isolation_commands[isolation_level])
            except Exception as e:
                self.logger.warning(f"Could not set isolation level {isolation_level}: {e}")


class ErrorHandler:
    """Standardized error handling for TPC tests."""

    def __init__(
        self,
        retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL_BACKOFF,
        max_retries: int = 3,
    ):
        """Initialize error handler."""
        self.retry_policy = retry_policy
        self.max_retries = max_retries
        self.logger = logging.getLogger(__name__)

    def handle_error(self, error: Exception, context: dict[str, Any]) -> bool:
        """Handle an error and determine if retry should be attempted."""
        retry_count = context.get("retry_count", 0)

        if retry_count >= self.max_retries:
            self.logger.error(f"Max retries ({self.max_retries}) exceeded for {context}")
            return False

        # Determine if error is retryable
        if not self._is_retryable_error(error):
            self.logger.error(f"Non-retryable error: {error}")
            return False

        # Calculate delay
        delay = self._calculate_delay(retry_count)

        self.logger.warning(f"Retrying after error (attempt {retry_count + 1}/{self.max_retries}): {error}")
        self.logger.info(f"Waiting {delay:.2f} seconds before retry...")

        time.sleep(delay)
        return True

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is retryable."""
        # Common retryable errors
        retryable_errors = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "lock",
            "deadlock",
        ]

        error_message = str(error).lower()
        return any(keyword in error_message for keyword in retryable_errors)

    def _calculate_delay(self, retry_count: int) -> float:
        """Calculate delay before retry."""
        if self.retry_policy == RetryPolicy.NONE:
            return 0.0
        elif self.retry_policy == RetryPolicy.FIXED_DELAY:
            return 1.0
        elif self.retry_policy == RetryPolicy.LINEAR_BACKOFF:
            return float(retry_count + 1)
        elif self.retry_policy == RetryPolicy.EXPONENTIAL_BACKOFF:
            return min(2.0**retry_count, 60.0)  # Cap at 60 seconds
        else:
            return 1.0


class ProgressTracker:
    """Tracks test progress and provides logging."""

    def __init__(self, total_items: int, description: str = "Processing") -> None:
        """Initialize progress tracker."""
        self.total_items = total_items
        self.description = description
        self.completed_items = 0
        self.failed_items = 0
        self.start_time = mono_time()
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()

    def update(
        self,
        completed: int = 1,
        failed: int = 0,
        item_description: Optional[str] = None,
    ) -> None:
        """Update progress."""
        with self._lock:
            self.completed_items += completed
            self.failed_items += failed

            if item_description:
                self.logger.info(f"Completed: {item_description}")

            # Log progress periodically
            total_processed = self.completed_items + self.failed_items
            if total_processed % max(1, self.total_items // 10) == 0 or total_processed == self.total_items:
                self._log_progress()

    def _log_progress(self) -> None:
        """Log current progress."""
        total_processed = self.completed_items + self.failed_items
        elapsed_time = elapsed_seconds(self.start_time)

        percentage = (total_processed / self.total_items) * 100 if self.total_items > 0 else 0
        rate = total_processed / elapsed_time if elapsed_time > 0 else 0

        eta = (self.total_items - total_processed) / rate if rate > 0 else 0

        self.logger.info(
            f"{self.description}: {total_processed}/{self.total_items} "
            f"({percentage:.1f}%) - {self.completed_items} succeeded, "
            f"{self.failed_items} failed - Rate: {rate:.1f}/s - ETA: {eta:.1f}s"
        )

    def get_summary(self) -> dict[str, Any]:
        """Get progress summary."""
        total_time = elapsed_seconds(self.start_time)
        total_processed = self.completed_items + self.failed_items

        return {
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "failed_items": self.failed_items,
            "total_processed": total_processed,
            "success_rate": (self.completed_items / total_processed) if total_processed > 0 else 0,
            "total_time": total_time,
            "rate": total_processed / total_time if total_time > 0 else 0,
        }


class ResultAggregator:
    """Combines results from multiple streams/queries."""

    def __init__(self) -> None:
        """Initialize result aggregator."""
        self.stream_results: dict[int, StreamResult] = {}
        self.query_results: list[QueryResult] = []
        self.logger = logging.getLogger(__name__)

    def add_stream_result(self, stream_result: StreamResult) -> None:
        """Add a stream result."""
        self.stream_results[stream_result.stream_id] = stream_result
        self.query_results.extend(stream_result.queries)

    def add_query_result(self, query_result: QueryResult) -> None:
        """Add a query result."""
        self.query_results.append(query_result)

    def get_aggregated_results(self) -> dict[str, Any]:
        """Get aggregated results across all streams and queries."""
        if not self.query_results:
            return self._empty_results()

        # Calculate overall statistics
        total_queries = len(self.query_results)
        successful_queries = sum(1 for q in self.query_results if q.status == ExecutionStatus.COMPLETED)
        failed_queries = sum(1 for q in self.query_results if q.status == ExecutionStatus.FAILED)

        execution_times = [q.execution_time for q in self.query_results if q.status == ExecutionStatus.COMPLETED]

        # Stream statistics
        stream_stats = {}
        for stream_id, stream_result in self.stream_results.items():
            stream_stats[stream_id] = {
                "total_queries": len(stream_result.queries),
                "successful_queries": stream_result.successful_queries,
                "failed_queries": stream_result.failed_queries,
                "total_execution_time": stream_result.total_execution_time,
                "status": stream_result.status.value,
            }

        return {
            "total_streams": len(self.stream_results),
            "total_queries": total_queries,
            "successful_queries": successful_queries,
            "failed_queries": failed_queries,
            "success_rate": successful_queries / total_queries if total_queries > 0 else 0,
            "total_execution_time": sum(execution_times),
            "average_execution_time": sum(execution_times) / len(execution_times) if execution_times else 0,
            "min_execution_time": min(execution_times) if execution_times else 0,
            "max_execution_time": max(execution_times) if execution_times else 0,
            "stream_statistics": stream_stats,
            "query_results": [self._serialize_query_result(q) for q in self.query_results],
        }

    def _empty_results(self) -> dict[str, Any]:
        """Return empty results structure."""
        return {
            "total_streams": 0,
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "success_rate": 0.0,
            "total_execution_time": 0.0,
            "average_execution_time": 0.0,
            "min_execution_time": 0.0,
            "max_execution_time": 0.0,
            "stream_statistics": {},
            "query_results": [],
        }

    def _serialize_query_result(self, query_result: QueryResult) -> dict[str, Any]:
        """Serialize query result for JSON compatibility."""
        return {
            "query_id": query_result.query_id,
            "stream_id": query_result.stream_id,
            "execution_time_seconds": query_result.execution_time,
            "status": query_result.status.value,
            "error": query_result.error,
            "row_count": query_result.row_count,
            "retry_count": query_result.retry_count,
            "parameters": query_result.parameters,
        }


class StreamExecutor:
    """Manages concurrent query stream execution."""

    def __init__(
        self,
        connection_factory: Callable[[], DatabaseConnection],
        max_concurrent_streams: int = 4,
    ):
        """Initialize stream executor."""
        self.connection_factory = connection_factory
        self.max_concurrent_streams = max_concurrent_streams
        self.logger = logging.getLogger(__name__)
        self.parameter_manager = ParameterManager()
        self.error_handler = ErrorHandler()
        self.result_aggregator = ResultAggregator()

    def execute_streams(
        self,
        stream_configs: list[StreamConfig],
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        """Execute multiple streams concurrently."""
        if not stream_configs:
            return self.result_aggregator.get_aggregated_results()

        total_queries = sum(len(config.query_ids) for config in stream_configs)
        progress_tracker = ProgressTracker(total_queries, "Executing query streams")

        self.logger.info(f"Executing {len(stream_configs)} streams with {total_queries} total queries")

        # Execute streams concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent_streams) as executor:
            # Submit all streams for execution
            future_to_stream = {
                executor.submit(
                    self._execute_single_stream,
                    config,
                    query_executor,
                    progress_tracker,
                ): config
                for config in stream_configs
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_stream):
                stream_config = future_to_stream[future]
                try:
                    stream_result = future.result()
                    self.result_aggregator.add_stream_result(stream_result)

                    if progress_callback:
                        progress_callback(progress_tracker.get_summary())

                except Exception as e:
                    self.logger.error(f"Stream {stream_config.stream_id} failed: {e}")
                    # Create a failed stream result
                    failed_result = StreamResult(
                        stream_id=stream_config.stream_id,
                        status=ExecutionStatus.FAILED,
                        error=str(e),
                    )
                    self.result_aggregator.add_stream_result(failed_result)

        # Log final summary
        summary = progress_tracker.get_summary()
        self.logger.info(f"Stream execution completed: {summary}")

        return self.result_aggregator.get_aggregated_results()

    def _execute_single_stream(
        self,
        config: StreamConfig,
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        progress_tracker: ProgressTracker,
    ) -> StreamResult:
        """Execute a single stream."""
        stream_result = StreamResult(
            stream_id=config.stream_id,
            start_time=mono_time(),
            status=ExecutionStatus.RUNNING,
        )

        connection = None
        try:
            # Create database connection for this stream
            connection = self.connection_factory()

            # Generate query permutation
            permutator = QueryPermutator(config.permutation_config)
            permuted_queries = permutator.generate_permutation(config.query_ids)

            self.logger.debug(f"Stream {config.stream_id} executing queries: {permuted_queries}")

            # Execute queries in permuted order
            for query_id in permuted_queries:
                query_result = self._execute_query_with_retry(query_id, connection, config, query_executor)
                stream_result.queries.append(query_result)

                # Configure progress
                if query_result.status == ExecutionStatus.COMPLETED:
                    progress_tracker.update(
                        completed=1,
                        item_description=f"Stream {config.stream_id} Query {query_id}",
                    )
                else:
                    progress_tracker.update(
                        failed=1,
                        item_description=f"Stream {config.stream_id} Query {query_id} FAILED",
                    )

            stream_result.status = ExecutionStatus.COMPLETED

        except Exception as e:
            self.logger.error(f"Stream {config.stream_id} execution failed: {e}")
            stream_result.status = ExecutionStatus.FAILED
            stream_result.error = str(e)

        finally:
            if connection:
                try:
                    connection.close()
                except Exception as e:
                    self.logger.warning(f"Error closing connection for stream {config.stream_id}: {e}")

            stream_result.end_time = mono_time()

        return stream_result

    def _execute_query_with_retry(
        self,
        query_id: Union[int, str],
        connection: DatabaseConnection,
        config: StreamConfig,
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
    ) -> QueryResult:
        """Execute a query with retry logic."""
        retry_count = 0
        last_error = None

        while retry_count <= config.max_retries:
            try:
                # Generate parameters for this query
                parameters = self.parameter_manager.generate_parameters(
                    query_id, config.stream_id, custom_seed=config.parameter_seed
                )
                parameters["retry_count"] = retry_count

                # Execute query
                query_result = query_executor(query_id, connection, parameters)
                query_result.stream_id = config.stream_id
                query_result.retry_count = retry_count
                query_result.parameters = parameters

                return query_result

            except Exception as e:
                last_error = e

                # Check if we should retry
                context = {
                    "query_id": query_id,
                    "stream_id": config.stream_id,
                    "retry_count": retry_count,
                }

                if retry_count < config.max_retries and self.error_handler.handle_error(e, context):
                    retry_count += 1
                    continue
                else:
                    break

        # All retries failed
        return QueryResult(
            query_id=query_id,
            stream_id=config.stream_id,
            status=ExecutionStatus.FAILED,
            error=str(last_error) if last_error else "Unknown error",
            retry_count=retry_count,
        )


class BenchmarkTestRunner:
    """Common test execution patterns."""

    def __init__(self, connection_factory: Callable[[], DatabaseConnection]) -> None:
        """Initialize test runner."""
        self.connection_factory = connection_factory
        self.logger = logging.getLogger(__name__)

    def run_single_query_test(
        self,
        query_id: Union[int, str],
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        parameters: Optional[dict[str, Any]] = None,
    ) -> QueryResult:
        """Run a single query test."""
        connection = None
        try:
            connection = self.connection_factory()

            # Create transaction manager
            transaction_manager = TransactionManager(connection)

            with transaction_manager.transaction():
                result = query_executor(query_id, connection, parameters or {})
                return result

        except Exception as e:
            self.logger.error(f"Single query test failed for query {query_id}: {e}")
            return QueryResult(query_id=query_id, status=ExecutionStatus.FAILED, error=str(e))
        finally:
            if connection:
                connection.close()

    def run_sequential_test(
        self,
        query_ids: list[Union[int, str]],
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Run queries sequentially."""
        results = []
        progress_tracker = ProgressTracker(len(query_ids), "Sequential query execution")

        connection = None
        try:
            connection = self.connection_factory()

            for query_id in query_ids:
                try:
                    result = query_executor(query_id, connection, parameters or {})
                    results.append(result)

                    if result.status == ExecutionStatus.COMPLETED:
                        progress_tracker.update(completed=1, item_description=f"Query {query_id}")
                    else:
                        progress_tracker.update(failed=1, item_description=f"Query {query_id} FAILED")

                except Exception as e:
                    self.logger.error(f"Query {query_id} failed: {e}")
                    failed_result = QueryResult(query_id=query_id, status=ExecutionStatus.FAILED, error=str(e))
                    results.append(failed_result)
                    progress_tracker.update(failed=1, item_description=f"Query {query_id} FAILED")

        finally:
            if connection:
                connection.close()

        # Aggregate results
        aggregator = ResultAggregator()
        for result in results:
            aggregator.add_query_result(result)

        return aggregator.get_aggregated_results()

    def run_concurrent_test(
        self,
        stream_configs: list[StreamConfig],
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        max_concurrent_streams: int = 4,
    ) -> dict[str, Any]:
        """Run queries concurrently using streams."""
        stream_executor = StreamExecutor(self.connection_factory, max_concurrent_streams)
        return stream_executor.execute_streams(stream_configs, query_executor)

    def run_validation_test(
        self,
        query_ids: list[Union[int, str]],
        query_executor: Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult],
        validator: Callable[[QueryResult], bool],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Run queries with result validation."""
        results = []
        validation_results = []
        progress_tracker = ProgressTracker(len(query_ids), "Validation test execution")

        connection = None
        try:
            connection = self.connection_factory()

            for query_id in query_ids:
                try:
                    result = query_executor(query_id, connection, parameters or {})
                    results.append(result)

                    # Validate result
                    if result.status == ExecutionStatus.COMPLETED:
                        is_valid = validator(result)
                        validation_results.append({"query_id": query_id, "valid": is_valid, "result": result})

                        if is_valid:
                            progress_tracker.update(completed=1, item_description=f"Query {query_id} VALID")
                        else:
                            progress_tracker.update(failed=1, item_description=f"Query {query_id} INVALID")
                    else:
                        validation_results.append({"query_id": query_id, "valid": False, "result": result})
                        progress_tracker.update(failed=1, item_description=f"Query {query_id} FAILED")

                except Exception as e:
                    self.logger.error(f"Query {query_id} failed: {e}")
                    failed_result = QueryResult(query_id=query_id, status=ExecutionStatus.FAILED, error=str(e))
                    results.append(failed_result)
                    validation_results.append({"query_id": query_id, "valid": False, "result": failed_result})
                    progress_tracker.update(failed=1, item_description=f"Query {query_id} FAILED")

        finally:
            if connection:
                connection.close()

        # Aggregate results
        aggregator = ResultAggregator()
        for result in results:
            aggregator.add_query_result(result)

        aggregated_results = aggregator.get_aggregated_results()

        # Add validation statistics
        total_validated = len(validation_results)
        valid_results = sum(1 for v in validation_results if v["valid"])

        aggregated_results["validation"] = {
            "total_validated": total_validated,
            "valid_results": valid_results,
            "invalid_results": total_validated - valid_results,
            "validation_rate": valid_results / total_validated if total_validated > 0 else 0,
            "validation_details": validation_results,
        }

        return aggregated_results


# Utility functions for common TPC test patterns


def create_tpc_stream_configs(
    num_streams: int,
    query_ids: list[Union[int, str]],
    base_seed: int = 42,
    permutation_mode: str = "tpc_standard",
) -> list[StreamConfig]:
    """Create standard TPC stream configurations."""
    configs = []

    for stream_id in range(num_streams):
        permutation_config = PermutationConfig(mode=permutation_mode, seed=base_seed + stream_id, ensure_unique=True)

        config = StreamConfig(
            stream_id=stream_id,
            query_ids=query_ids.copy(),
            permutation_config=permutation_config,
            parameter_seed=base_seed + stream_id + 1000,
        )

        configs.append(config)

    return configs


def create_basic_query_executor(
    benchmark_instance: Any,
) -> Callable[[Union[int, str], DatabaseConnection, dict[str, Any]], QueryResult]:
    """Create a basic query executor for a benchmark instance."""
    logger = logging.getLogger(__name__)

    def execute_query(
        query_id: Union[int, str],
        connection: DatabaseConnection,
        parameters: dict[str, Any],
    ) -> QueryResult:
        """Execute a single query."""
        result = QueryResult(query_id=query_id, start_time=mono_time())

        try:
            # Get query text from benchmark
            query_text = benchmark_instance.get_query(query_id, params=parameters)

            # Execute query
            cursor = connection.execute(query_text)

            # Fetch results
            results = connection.fetchall(cursor)

            result.end_time = time.time()
            result.status = ExecutionStatus.COMPLETED
            result.results = results
            result.row_count = len(results) if results else 0

            logger.debug(f"Query {query_id} completed with {result.row_count} rows")

        except Exception as e:
            result.end_time = time.time()
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            logger.error(f"Query {query_id} failed: {e}")

        return result

    return execute_query


def create_validation_function(
    expected_results: Optional[dict[Union[int, str], Any]] = None,
) -> Callable[[QueryResult], bool]:
    """Create a validation function for query results."""

    def validate_result(result: QueryResult) -> bool:
        """Validate a query result."""
        if result.status != ExecutionStatus.COMPLETED:
            return False

        if result.results is None:
            return False

        if expected_results and result.query_id in expected_results:
            expected = expected_results[result.query_id]
            # Simple validation - in practice this would be more sophisticated
            return len(result.results) == expected.get("row_count", 0)

        # Basic validation - query completed and returned results
        return True

    return validate_result
