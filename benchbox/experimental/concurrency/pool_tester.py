"""Connection pool stress testing for database concurrency analysis.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PoolTestConfig:
    """Configuration for connection pool testing."""

    connection_factory: Callable[[], Any]
    """Factory creating new database connections."""

    health_check_query: str = "SELECT 1"
    """Simple query to verify connection health."""

    execute_query: Callable[[Any, str], bool] | None = None
    """Optional function to execute query: (connection, sql) -> success."""

    # Test parameters
    max_connections_to_test: int = 100
    """Maximum connections to attempt acquiring."""

    connection_acquire_timeout: float = 30.0
    """Timeout for acquiring a single connection."""

    hold_connection_seconds: float = 1.0
    """How long to hold each connection during stress test."""

    ramp_step_size: int = 10
    """Number of connections to add in each ramp step."""

    ramp_step_delay_seconds: float = 0.5
    """Delay between ramp steps."""


@dataclass
class ConnectionAttempt:
    """Record of a connection attempt."""

    attempt_id: int
    start_time: float
    end_time: float | None = None
    success: bool = False
    error: str | None = None
    connection_time_ms: float = 0.0


@dataclass
class PoolTestResult:
    """Results from connection pool testing."""

    # Connection acquisition
    total_attempts: int
    successful_connections: int
    failed_connections: int
    success_rate: float

    # Timing
    min_connect_time_ms: float
    max_connect_time_ms: float
    avg_connect_time_ms: float
    p95_connect_time_ms: float
    p99_connect_time_ms: float

    # Pool characteristics
    max_concurrent_connections: int
    estimated_pool_size: int
    pool_exhaustion_detected: bool
    exhaustion_threshold: int | None  # Connection count where pool exhaustion began

    # Connection attempts by status
    attempts: list[ConnectionAttempt] = field(default_factory=list)

    # Recommendations
    recommendations: list[str] = field(default_factory=list)


class ConnectionPoolTester:
    """Tests database connection pool behavior under load.

    This tester helps identify:
    - Actual pool size limits
    - Connection acquisition times under load
    - Pool exhaustion thresholds
    - Connection timeout behavior
    """

    def __init__(self, config: PoolTestConfig):
        """Initialize pool tester.

        Args:
            config: Configuration for pool testing
        """
        self._config = config
        self._lock = threading.Lock()
        self._active_connections: list[Any] = []
        self._max_concurrent = 0
        self._attempts: list[ConnectionAttempt] = []

    def test_pool_limits(self) -> PoolTestResult:
        """Test connection pool limits by gradually acquiring connections.

        Returns:
            Pool test results with limit analysis
        """
        logger.info(
            f"Starting pool limit test: max_to_test={self._config.max_connections_to_test}, "
            f"step_size={self._config.ramp_step_size}"
        )

        time.time()
        attempt_id = 0
        exhaustion_threshold = None

        try:
            # Ramp up connections gradually
            for target in range(
                self._config.ramp_step_size,
                self._config.max_connections_to_test + 1,
                self._config.ramp_step_size,
            ):
                current_count = len(self._active_connections)
                to_acquire = target - current_count

                logger.debug(f"Ramping to {target} connections (acquiring {to_acquire})")

                failures_in_step = 0
                for _ in range(to_acquire):
                    attempt = self._acquire_connection(attempt_id)
                    attempt_id += 1

                    if not attempt.success:
                        failures_in_step += 1
                        if exhaustion_threshold is None and failures_in_step > to_acquire * 0.5:
                            exhaustion_threshold = current_count + (to_acquire - failures_in_step)
                            logger.info(f"Pool exhaustion detected at ~{exhaustion_threshold} connections")

                # Check if we should stop
                if len(self._active_connections) == current_count and to_acquire > 0:
                    logger.info(f"No new connections acquired at target {target}, stopping")
                    break

                time.sleep(self._config.ramp_step_delay_seconds)

            # Hold connections briefly to verify stability
            time.sleep(self._config.hold_connection_seconds)

        finally:
            # Release all connections
            self._release_all_connections()

        return self._build_result(exhaustion_threshold)

    def test_pool_under_load(self, concurrency: int = 50, duration_seconds: float = 30.0) -> PoolTestResult:
        """Test connection pool under concurrent access load.

        Args:
            concurrency: Number of concurrent connection requesters
            duration_seconds: Duration of the test

        Returns:
            Pool test results with load analysis
        """
        logger.info(f"Starting pool load test: concurrency={concurrency}, duration={duration_seconds}s")

        start_time = time.time()
        end_time = start_time + duration_seconds
        attempt_counter = [0]  # Use list for mutability in closure

        def connection_worker(worker_id: int) -> None:
            """Worker that repeatedly acquires and releases connections."""
            while time.time() < end_time:
                with self._lock:
                    attempt_id = attempt_counter[0]
                    attempt_counter[0] += 1

                attempt = self._acquire_connection(attempt_id)

                if attempt.success:
                    # Find and release the connection we acquired
                    time.sleep(0.1)  # Brief hold
                    with self._lock:
                        if self._active_connections:
                            conn = self._active_connections.pop()
                            try:
                                if hasattr(conn, "close"):
                                    conn.close()
                            except Exception:
                                pass

        # Run concurrent workers
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(connection_worker, i) for i in range(concurrency)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.debug(f"Worker error: {e}")

        # Release any remaining connections
        self._release_all_connections()

        return self._build_result(None)

    def test_connection_churn(
        self,
        connections_per_second: float = 10.0,
        duration_seconds: float = 30.0,
    ) -> PoolTestResult:
        """Test connection pool with high churn rate.

        Args:
            connections_per_second: Target rate of new connections
            duration_seconds: Duration of the test

        Returns:
            Pool test results with churn analysis
        """
        logger.info(f"Starting pool churn test: rate={connections_per_second}/s, duration={duration_seconds}s")

        start_time = time.time()
        end_time = start_time + duration_seconds
        interval = 1.0 / connections_per_second
        attempt_id = 0

        while time.time() < end_time:
            # Acquire connection
            attempt = self._acquire_connection(attempt_id)
            attempt_id += 1

            # Immediately release
            if attempt.success:
                with self._lock:
                    if self._active_connections:
                        conn = self._active_connections.pop()
                        try:
                            if hasattr(conn, "close"):
                                conn.close()
                        except Exception:
                            pass

            # Wait for next acquisition
            time.sleep(interval)

        self._release_all_connections()
        return self._build_result(None)

    def _acquire_connection(self, attempt_id: int) -> ConnectionAttempt:
        """Attempt to acquire a single connection."""
        attempt = ConnectionAttempt(
            attempt_id=attempt_id,
            start_time=time.time(),
        )

        try:
            conn = self._config.connection_factory()

            # Verify connection with health check
            if self._config.execute_query:
                success = self._config.execute_query(conn, self._config.health_check_query)
                if not success:
                    raise RuntimeError("Health check query failed")

            attempt.end_time = time.time()
            attempt.success = True
            attempt.connection_time_ms = (attempt.end_time - attempt.start_time) * 1000

            with self._lock:
                self._active_connections.append(conn)
                if len(self._active_connections) > self._max_concurrent:
                    self._max_concurrent = len(self._active_connections)

        except Exception as e:
            attempt.end_time = time.time()
            attempt.success = False
            attempt.error = str(e)
            attempt.connection_time_ms = (attempt.end_time - attempt.start_time) * 1000

        with self._lock:
            self._attempts.append(attempt)

        return attempt

    def _release_all_connections(self) -> None:
        """Release all held connections."""
        with self._lock:
            connections = self._active_connections[:]
            self._active_connections.clear()

        for conn in connections:
            try:
                if hasattr(conn, "close"):
                    conn.close()
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")

    def _build_result(self, exhaustion_threshold: int | None) -> PoolTestResult:
        """Build result object from collected data."""
        successful = [a for a in self._attempts if a.success]
        failed = [a for a in self._attempts if not a.success]

        connect_times = [a.connection_time_ms for a in successful]
        connect_times.sort()

        if connect_times:
            min_time = min(connect_times)
            max_time = max(connect_times)
            avg_time = sum(connect_times) / len(connect_times)
            p95_time = connect_times[int(len(connect_times) * 0.95)] if len(connect_times) > 1 else connect_times[0]
            p99_time = connect_times[int(len(connect_times) * 0.99)] if len(connect_times) > 1 else connect_times[0]
        else:
            min_time = max_time = avg_time = p95_time = p99_time = 0

        # Generate recommendations
        recommendations = []
        if exhaustion_threshold is not None:
            recommendations.append(
                f"Pool exhaustion at {exhaustion_threshold} connections - consider increasing pool size"
            )

        if max_time > 1000:
            recommendations.append("Connection acquisition times > 1s - check network latency or pool configuration")

        if len(failed) > len(self._attempts) * 0.1:
            recommendations.append(
                f"High failure rate ({len(failed)}/{len(self._attempts)}) - review connection limits"
            )

            # Analyze error types
            timeout_errors = sum(1 for a in failed if a.error and "timeout" in a.error.lower())
            if timeout_errors > len(failed) * 0.5:
                recommendations.append("Most failures are timeouts - increase connection_acquire_timeout or pool size")

        return PoolTestResult(
            total_attempts=len(self._attempts),
            successful_connections=len(successful),
            failed_connections=len(failed),
            success_rate=len(successful) / len(self._attempts) * 100 if self._attempts else 0,
            min_connect_time_ms=min_time,
            max_connect_time_ms=max_time,
            avg_connect_time_ms=avg_time,
            p95_connect_time_ms=p95_time,
            p99_connect_time_ms=p99_time,
            max_concurrent_connections=self._max_concurrent,
            estimated_pool_size=self._max_concurrent,
            pool_exhaustion_detected=exhaustion_threshold is not None,
            exhaustion_threshold=exhaustion_threshold,
            attempts=self._attempts,
            recommendations=recommendations,
        )
