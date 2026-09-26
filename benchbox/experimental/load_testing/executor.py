"""Concurrent load executor for database workload testing.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from benchbox.experimental.load_testing.patterns import SteadyPattern, WorkloadPattern, WorkloadPhase
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


@dataclass
class QueryExecution:
    """Record of a single query execution."""

    query_id: str
    stream_id: int
    start_time: float
    end_time: float
    success: bool
    error: str | None = None
    rows_returned: int | None = None
    queue_wait_time: float = 0.0  # Time waiting in queue before execution


@dataclass
class StreamResult:
    """Results from a single concurrent stream."""

    stream_id: int
    queries_executed: int
    queries_succeeded: int
    queries_failed: int
    total_time_seconds: float
    query_executions: list[QueryExecution] = field(default_factory=list)
    error: str | None = None

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.queries_executed == 0:
            return 0.0
        return (self.queries_succeeded / self.queries_executed) * 100

    @property
    def throughput(self) -> float:
        """Queries per second for this stream."""
        if self.total_time_seconds == 0:
            return 0.0
        return self.queries_executed / self.total_time_seconds


@dataclass
class ConcurrentLoadConfig:
    """Configuration for concurrent load testing."""

    # Query execution
    query_factory: Callable[[int], tuple[str, str]]
    """Factory returning (query_id, sql) for stream iteration index."""

    role_factories: dict[str, Callable[[int], tuple[str, str]]] | None = field(default=None, kw_only=True)
    """Optional per-role query factories for role-aware patterns.

    Maps a stream role (e.g. "writer", "reader") to the factory used for
    streams launched in that role. When a pattern phase declares `roles`
    targets, launched streams use the matching role factory; phases without
    role targets keep using `query_factory`. Every role named by the
    pattern must have a factory entry.
    """

    connection_factory: Callable[[], Any]
    """Factory creating new database connections.

    Must return an independent, thread-confined connection per call: one
    stream owns its connection for its whole lifetime and closes it on
    exit. Never return a shared connection; concurrent streams closing or
    writing through the same handle corrupts every in-flight stream.
    """

    execute_query: Callable[[Any, str], tuple[bool, int | None, str | None]]
    """Function to execute query: (connection, sql) -> (success, rows, error)."""

    # Workload configuration
    pattern: WorkloadPattern = field(default_factory=lambda: SteadyPattern(1, 60))
    """Workload pattern defining concurrency over time."""

    queries_per_stream: int = 10
    """Number of queries each stream executes."""

    query_timeout_seconds: float = 300.0
    """Timeout for individual query execution."""

    # Resource monitoring
    collect_resource_metrics: bool = True
    """Whether to collect CPU/memory metrics during execution."""

    resource_sample_interval: float = 1.0
    """Interval between resource metric samples in seconds."""

    # Queue analysis
    track_queue_times: bool = True
    """Whether to track time queries spend waiting in queue."""


@dataclass
class ConcurrentLoadResult:
    """Results from concurrent load testing."""

    # Timing
    start_time: float
    end_time: float
    total_duration_seconds: float

    # Stream results
    streams: list[StreamResult]
    total_streams_executed: int
    total_streams_succeeded: int

    # Query metrics
    total_queries_executed: int
    total_queries_succeeded: int
    total_queries_failed: int

    # Throughput
    overall_throughput: float  # Queries per second across all streams

    # Queue analysis
    queue_metrics: dict[str, float] = field(default_factory=dict)

    # Resource metrics
    resource_metrics: dict[str, Any] = field(default_factory=dict)

    # Pattern info
    pattern_name: str = ""
    max_concurrency_reached: int = 0

    @property
    def success_rate(self) -> float:
        """Overall query success rate as a percentage."""
        if self.total_queries_executed == 0:
            return 0.0
        return (self.total_queries_succeeded / self.total_queries_executed) * 100

    def get_percentile_latency(self, percentile: float) -> float:
        """Get query latency at given percentile.

        Args:
            percentile: Percentile (0-100)

        Returns:
            Latency in seconds at the percentile
        """
        latencies = []
        for stream in self.streams:
            for execution in stream.query_executions:
                latencies.append(execution.end_time - execution.start_time)

        if not latencies:
            return 0.0

        latencies.sort()
        index = int((percentile / 100) * len(latencies))
        index = min(index, len(latencies) - 1)
        return latencies[index]


class ConcurrentLoadExecutor:
    """Executes concurrent database load tests with configurable patterns.

    This executor manages concurrent query streams, tracks execution metrics,
    and provides queue analysis capabilities.
    """

    def __init__(self, config: ConcurrentLoadConfig):
        """Initialize the executor.

        Args:
            config: Configuration for the load test
        """
        self._config = config
        self._lock = threading.Lock()
        self._stream_results: list[StreamResult] = []
        self._active_streams = 0
        self._active_roles: dict[str, int] = {}
        self._max_concurrency_reached = 0
        self._queue: deque[tuple[int, float]] = deque()  # (stream_id, enqueue_time)
        self._resource_samples: list[dict[str, float]] = []
        self._stop_monitoring = threading.Event()

    def run(self) -> ConcurrentLoadResult:
        """Execute the concurrent load test.

        Returns:
            Results from the load test

        Raises:
            ValueError: If the pattern declares stream roles but the config
                does not provide a matching `role_factories` entry.
        """
        start_time = time.time()
        pattern = self._config.pattern
        self._validate_role_factories(pattern)

        logger.info(
            f"Starting concurrent load test: pattern={pattern.__class__.__name__}, "
            f"max_concurrency={pattern.max_concurrency}, "
            f"duration={pattern.total_duration}s"
        )

        # Start resource monitoring
        monitor_thread = None
        if self._config.collect_resource_metrics:
            monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
            monitor_thread.start()

        try:
            self._execute_pattern(pattern)
        finally:
            self._stop_monitoring.set()
            if monitor_thread:
                monitor_thread.join(timeout=2.0)

        end_time = time.time()
        total_duration = end_time - start_time

        # Aggregate results
        total_queries = sum(s.queries_executed for s in self._stream_results)
        total_succeeded = sum(s.queries_succeeded for s in self._stream_results)
        total_failed = sum(s.queries_failed for s in self._stream_results)
        streams_succeeded = sum(1 for s in self._stream_results if s.error is None)

        # Calculate queue metrics
        queue_metrics = self._calculate_queue_metrics()

        # Calculate resource metrics
        resource_metrics = self._calculate_resource_metrics()

        result = ConcurrentLoadResult(
            start_time=start_time,
            end_time=end_time,
            total_duration_seconds=total_duration,
            streams=self._stream_results,
            total_streams_executed=len(self._stream_results),
            total_streams_succeeded=streams_succeeded,
            total_queries_executed=total_queries,
            total_queries_succeeded=total_succeeded,
            total_queries_failed=total_failed,
            overall_throughput=total_queries / total_duration if total_duration > 0 else 0,
            queue_metrics=queue_metrics,
            resource_metrics=resource_metrics,
            pattern_name=pattern.__class__.__name__,
            max_concurrency_reached=self._max_concurrency_reached,
        )

        logger.info(
            f"Load test complete: {total_queries} queries in {total_duration:.2f}s "
            f"({result.overall_throughput:.2f} qps), "
            f"success_rate={result.success_rate:.1f}%"
        )

        return result

    def _validate_role_factories(self, pattern: WorkloadPattern) -> None:
        """Validate role factory coverage for role-aware patterns.

        Args:
            pattern: Workload pattern about to execute.

        Raises:
            ValueError: If any phase declares roles without a matching
                factory entry, or a role target is negative.
        """
        declared_roles: set[str] = set()
        for phase in pattern.iter_phases():
            if phase.roles:
                for role, target in phase.roles.items():
                    if target < 0:
                        raise ValueError(f"phase '{phase.phase_name}': negative target for role '{role}'")
                declared_roles.update(phase.roles)
        if declared_roles:
            missing = declared_roles - set(self._config.role_factories or {})
            if missing:
                raise ValueError(
                    f"pattern declares roles {sorted(declared_roles)} but role_factories is missing {sorted(missing)}"
                )

    def _role_targets(self, phase: WorkloadPhase) -> dict[str, int]:
        """Compute per-role stream launch counts for a phase.

        For role-aware phases, each role is topped up to its declared
        target independently, so roles absent from the phase (such as
        readers during a writer-only drain) get no replacement streams
        once their in-flight streams finish. Phases without role targets
        keep the historical behavior of topping up total concurrency.

        Must be called with `self._lock` held.

        Args:
            phase: Phase currently executing.

        Returns:
            Mapping of role (or "" for undifferentiated phases) to the
            number of streams to launch now.
        """
        if phase.roles:
            return {role: max(0, target - self._active_roles.get(role, 0)) for role, target in phase.roles.items()}
        return {"": max(0, phase.concurrency - self._active_streams)}

    def _execute_pattern(self, pattern: WorkloadPattern) -> None:
        """Execute the workload pattern."""
        stream_counter = 0

        # Use ThreadPoolExecutor for managing concurrent streams
        with ThreadPoolExecutor(max_workers=pattern.max_concurrency) as executor:
            futures: dict[Future, tuple[int, str]] = {}
            phase_streams: dict[str, int] = {}
            phases = list(pattern.iter_phases())

            for index, phase in enumerate(phases):
                phase_start = mono_time()
                phase_streams[phase.phase_name] = 0

                logger.debug(
                    f"Starting phase '{phase.phase_name}': "
                    f"concurrency={phase.concurrency}, duration={phase.duration_seconds}s"
                )

                # Launch streams for this phase
                while elapsed_seconds(phase_start) < phase.duration_seconds:
                    with self._lock:
                        current_active = self._active_streams
                        if current_active > self._max_concurrency_reached:
                            self._max_concurrency_reached = current_active
                        targets = self._role_targets(phase)

                    for role, streams_to_launch in targets.items():
                        for _ in range(max(0, streams_to_launch)):
                            stream_id = stream_counter
                            stream_counter += 1
                            phase_streams[phase.phase_name] += 1

                            # Track queue time on the monotonic clock: queue_wait
                            # is computed against mono_time() in _execute_stream,
                            # so wall-clock time.time() here would corrupt it.
                            enqueue_time = mono_time() if self._config.track_queue_times else 0.0

                            with self._lock:
                                self._active_streams += 1
                                self._active_roles[role] = self._active_roles.get(role, 0) + 1
                                if self._config.track_queue_times:
                                    self._queue.append((stream_id, enqueue_time))

                            future = executor.submit(self._execute_stream, stream_id, enqueue_time, role)
                            futures[future] = (stream_id, role)

                    # Check for completed streams
                    completed = [f for f in futures if f.done()]
                    for future in completed:
                        try:
                            result = future.result()
                            self._stream_results.append(result)
                        except Exception as e:
                            stream_id = futures[future][0]
                            self._stream_results.append(
                                StreamResult(
                                    stream_id=stream_id,
                                    queries_executed=0,
                                    queries_succeeded=0,
                                    queries_failed=0,
                                    total_time_seconds=0,
                                    error=str(e),
                                )
                            )
                        finally:
                            _, role = futures[future]
                            with self._lock:
                                self._active_streams -= 1
                                self._decrement_role_locked(role)
                        del futures[future]

                    # Small sleep to prevent busy-waiting
                    time.sleep(0.1)

                # Phase boundary: roles excluded from the next phase (readers
                # during a writer-only drain) must finish before the next
                # phase clock starts, otherwise they bleed into the drain.
                # Roles continuing into the next phase keep running.
                upcoming = phases[index + 1].roles if index + 1 < len(phases) else None
                self._await_role_drain(futures, next_phase_roles=upcoming)

            # Wait for remaining streams to complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    self._stream_results.append(result)
                except Exception as e:
                    stream_id = futures[future][0]
                    self._stream_results.append(
                        StreamResult(
                            stream_id=stream_id,
                            queries_executed=0,
                            queries_succeeded=0,
                            queries_failed=0,
                            total_time_seconds=0,
                            error=str(e),
                        )
                    )
                finally:
                    _, role = futures[future]
                    with self._lock:
                        self._active_streams -= 1
                        self._decrement_role_locked(role)

    def _decrement_role_locked(self, role: str) -> None:
        """Release one active-stream slot. Call with `self._lock` held."""
        remaining = self._active_roles.get(role, 0) - 1
        if remaining > 0:
            self._active_roles[role] = remaining
        else:
            self._active_roles.pop(role, None)

    def _decrement_role(self, role: str) -> None:
        """Release one active-stream slot for a finished stream role."""
        with self._lock:
            self._decrement_role_locked(role)

    def _await_role_drain(
        self,
        futures: dict[Future, tuple[int, str]],
        next_phase_roles: dict[str, int] | None,
    ) -> None:
        """Wait for in-flight streams whose role ends at a phase boundary."""
        if not next_phase_roles:
            return
        draining = [f for f, (_, role) in futures.items() if role not in next_phase_roles]
        for future in as_completed(draining):
            try:
                self._stream_results.append(future.result())
            except Exception as e:  # noqa: BLE001 - record per-stream failures as data
                stream_id = futures[future][0]
                self._stream_results.append(
                    StreamResult(
                        stream_id=stream_id,
                        queries_executed=0,
                        queries_succeeded=0,
                        queries_failed=0,
                        total_time_seconds=0,
                        error=str(e),
                    )
                )
            finally:
                _, role = futures[future]
                with self._lock:
                    self._active_streams -= 1
                    self._decrement_role_locked(role)
            del futures[future]

    def _execute_stream(self, stream_id: int, enqueue_time: float, role: str = "") -> StreamResult:
        """Execute a single stream of queries.

        Args:
            stream_id: Unique stream identifier.
            enqueue_time: Queue entry timestamp for wait-time tracking.
            role: Stream role used to select a per-role query factory.
        """
        stream_start = mono_time()
        queue_wait = stream_start - enqueue_time if enqueue_time > 0 else 0
        query_factory = self._query_factory_for(role)

        # Remove from queue by identity: ThreadPoolExecutor does not start
        # streams in enqueue order, so head-of-queue removal strands entries.
        with self._lock:
            self._queue = deque((sid, ts) for sid, ts in self._queue if sid != stream_id)

        executions: list[QueryExecution] = []
        queries_succeeded = 0
        queries_failed = 0

        try:
            # Create connection for this stream
            connection = self._config.connection_factory()

            try:
                for i in range(self._config.queries_per_stream):
                    query_id, sql = query_factory(i)
                    query_start = time.time()

                    try:
                        success, rows, error = self._config.execute_query(connection, sql)
                        query_end = time.time()

                        if success:
                            queries_succeeded += 1
                        else:
                            queries_failed += 1

                        executions.append(
                            QueryExecution(
                                query_id=query_id,
                                stream_id=stream_id,
                                start_time=query_start,
                                end_time=query_end,
                                success=success,
                                error=error,
                                rows_returned=rows,
                                queue_wait_time=queue_wait if i == 0 else 0,
                            )
                        )

                    except Exception as e:
                        query_end = time.time()
                        queries_failed += 1
                        executions.append(
                            QueryExecution(
                                query_id=query_id,
                                stream_id=stream_id,
                                start_time=query_start,
                                end_time=query_end,
                                success=False,
                                error=str(e),
                                queue_wait_time=queue_wait if i == 0 else 0,
                            )
                        )

            finally:
                # Close connection
                if hasattr(connection, "close"):
                    connection.close()

        except Exception as e:
            return StreamResult(
                stream_id=stream_id,
                queries_executed=len(executions),
                queries_succeeded=queries_succeeded,
                queries_failed=queries_failed,
                total_time_seconds=elapsed_seconds(stream_start),
                query_executions=executions,
                error=f"Stream error: {e}",
            )

        return StreamResult(
            stream_id=stream_id,
            queries_executed=len(executions),
            queries_succeeded=queries_succeeded,
            queries_failed=queries_failed,
            total_time_seconds=elapsed_seconds(stream_start),
            query_executions=executions,
        )

    def _query_factory_for(self, role: str) -> Callable[[int], tuple[str, str]]:
        """Select the query factory for a stream role.

        Args:
            role: Stream role; "" denotes an undifferentiated stream.

        Returns:
            The per-role factory when one is configured, else the default.
        """
        if role and self._config.role_factories and role in self._config.role_factories:
            return self._config.role_factories[role]
        return self._config.query_factory

    def _monitor_resources(self) -> None:
        """Background thread for resource monitoring."""
        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available, skipping resource monitoring")
            return

        while not self._stop_monitoring.is_set():
            try:
                sample = {
                    "timestamp": time.time(),
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "memory_percent": psutil.virtual_memory().percent,
                    "active_streams": self._active_streams,
                }
                self._resource_samples.append(sample)
            except Exception as e:
                logger.debug(f"Resource monitoring error: {e}")

            self._stop_monitoring.wait(self._config.resource_sample_interval)

    def _calculate_queue_metrics(self) -> dict[str, float]:
        """Calculate queue wait time metrics."""
        wait_times = []
        for stream in self._stream_results:
            for execution in stream.query_executions:
                if execution.queue_wait_time > 0:
                    wait_times.append(execution.queue_wait_time)

        if not wait_times:
            return {}

        wait_times.sort()
        return {
            "min_queue_wait_ms": min(wait_times) * 1000,
            "max_queue_wait_ms": max(wait_times) * 1000,
            "avg_queue_wait_ms": sum(wait_times) / len(wait_times) * 1000,
            "p50_queue_wait_ms": wait_times[len(wait_times) // 2] * 1000,
            "p95_queue_wait_ms": wait_times[int(len(wait_times) * 0.95)] * 1000
            if len(wait_times) > 1
            else wait_times[0] * 1000,
            "p99_queue_wait_ms": wait_times[int(len(wait_times) * 0.99)] * 1000
            if len(wait_times) > 1
            else wait_times[0] * 1000,
        }

    def _calculate_resource_metrics(self) -> dict[str, Any]:
        """Calculate resource utilization metrics."""
        if not self._resource_samples:
            return {}

        cpu_values = [s["cpu_percent"] for s in self._resource_samples]
        memory_values = [s["memory_percent"] for s in self._resource_samples]
        stream_counts = [s["active_streams"] for s in self._resource_samples]

        return {
            "cpu_avg_percent": sum(cpu_values) / len(cpu_values),
            "cpu_max_percent": max(cpu_values),
            "memory_avg_percent": sum(memory_values) / len(memory_values),
            "memory_max_percent": max(memory_values),
            "max_active_streams": max(stream_counts),
            "sample_count": len(self._resource_samples),
        }
