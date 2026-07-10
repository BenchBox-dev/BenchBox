"""Execution Management Utilities for BenchBox.

This module provides utilities for managing power run iterations and concurrent query
execution patterns, integrating with the BenchBox configuration system.

QUARANTINED (2026-07-09): ``PowerRunExecutor`` and ``ConcurrentQueryExecutor``
below are orphaned infrastructure -- as of the concurrency-executor
consolidation, nothing in ``benchbox`` calls either class. They previously
looked "live" only because ``benchbox.core.tpch.streams.TPCHStreamRunner``
and ``benchbox.core.tpcds.benchmark.runner.TPCDSBenchmark.run_streams`` routed
through ``ConcurrentQueryExecutor``, but that routing always terminated in a
non-executing stub that faked query success without running any SQL -- so no
real workload ever reached these executors. Both stub call sites have since
been changed to raise ``NotImplementedError`` instead of faking success, which
severs the only path that could reach this module's executors.

The classes are kept (rather than deleted) only because
``benchbox/utils/__init__.py`` re-exports them and that file is outside this
consolidation's scope; they are not wired into any current benchmark
execution path. The single production concurrent-stream executor is
``benchbox.core.throughput.runner.StreamRunner``, used by
``benchbox.core.tpch.throughput_test.TPCHThroughputTest`` and
``benchbox.core.tpcds.throughput_test.TPCDSThroughputTest``. Do not add new
callers of ``PowerRunExecutor``/``ConcurrentQueryExecutor``; extend
``StreamRunner`` instead.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean, median, stdev
from typing import Any, Callable, Optional

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.resource_limits import (
    ResourceLimitExceeded,
    ResourceLimitMonitor,
    ResourceLimitsConfig,
)
from benchbox.utils.timeout_manager import TimeoutError as BenchboxTimeoutError, TimeoutManager, run_with_timeout

# Import handled locally to avoid circular imports


@dataclass
class PowerRunIteration:
    """Result of a single power run iteration."""

    iteration_id: int
    start_time: float
    end_time: float
    duration: float
    power_at_size: float
    queries_executed: int
    queries_successful: int
    success: bool = True
    error: Optional[str] = None
    query_results: list[dict[str, Any]] = field(default_factory=list)
    timed_out: bool = False
    resource_usage: Optional[dict[str, Any]] = None


@dataclass
class PowerRunResult:
    """Aggregated result of multiple power run iterations."""

    config: dict[str, Any]
    start_time: str
    end_time: str
    total_duration: float
    iterations_completed: int
    iterations_successful: int
    warm_up_iterations: int

    # Aggregated metrics
    avg_power_at_size: float
    median_power_at_size: float
    min_power_at_size: float
    max_power_at_size: float
    power_at_size_stdev: Optional[float]

    # Detailed results
    iteration_results: list[PowerRunIteration] = field(default_factory=list)
    warm_up_results: list[PowerRunIteration] = field(default_factory=list)
    success: bool = True
    errors: list[str] = field(default_factory=list)

    # Resource usage tracking
    resource_usage: Optional[dict[str, Any]] = None
    iterations_timed_out: int = 0
    resource_limit_exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "config": self.config,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration": self.total_duration,
            "iterations_completed": self.iterations_completed,
            "iterations_successful": self.iterations_successful,
            "warm_up_iterations": self.warm_up_iterations,
            "avg_power_at_size": self.avg_power_at_size,
            "median_power_at_size": self.median_power_at_size,
            "min_power_at_size": self.min_power_at_size,
            "max_power_at_size": self.max_power_at_size,
            "power_at_size_stdev": self.power_at_size_stdev,
            "iteration_results": [iter_result.__dict__ for iter_result in self.iteration_results],
            "warm_up_results": [iter_result.__dict__ for iter_result in self.warm_up_results],
            "success": self.success,
            "errors": self.errors,
            "resource_usage": self.resource_usage,
            "iterations_timed_out": self.iterations_timed_out,
            "resource_limit_exceeded": self.resource_limit_exceeded,
        }


@dataclass
class ConcurrentQueryResult:
    """Result of concurrent query execution."""

    config: dict[str, Any]
    start_time: str
    end_time: str
    total_duration: float
    max_concurrent: int
    queries_executed: int
    queries_successful: int
    queries_failed: int
    throughput_queries_per_second: float

    # Stream results (for throughput tests)
    stream_results: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    errors: list[str] = field(default_factory=list)

    # Resource usage tracking
    resource_usage: Optional[dict[str, Any]] = None
    streams_timed_out: int = 0
    resource_limit_exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "config": self.config,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration": self.total_duration,
            "max_concurrent": self.max_concurrent,
            "queries_executed": self.queries_executed,
            "queries_successful": self.queries_successful,
            "queries_failed": self.queries_failed,
            "throughput_queries_per_second": self.throughput_queries_per_second,
            "stream_results": self.stream_results,
            "success": self.success,
            "errors": self.errors,
            "resource_usage": self.resource_usage,
            "streams_timed_out": self.streams_timed_out,
            "resource_limit_exceeded": self.resource_limit_exceeded,
        }


class PowerRunExecutor:
    """Manages power run execution with multiple iterations and warm-up.

    QUARANTINED: no production caller. TPC-H/TPC-DS power tests implement
    their own iteration/warm-up loops directly (see ``run_power_test`` on
    each benchmark class) instead of using this class. See the module
    docstring for the full consolidation rationale.
    """

    def __init__(
        self,
        config_manager: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        resource_config: Optional[ResourceLimitsConfig] = None,
    ):
        """Initialize power run executor.

        Args:
            config_manager: Configuration manager instance (ConfigInterface compatible)
            logger: Logger instance
            resource_config: Resource limits configuration (optional)
        """
        if config_manager is None:
            from benchbox.utils.config_interface import create_cli_config_adapter

            self.config_manager = create_cli_config_adapter()
        else:
            self.config_manager = config_manager
        self.logger = logger or logging.getLogger(__name__)
        self.config = self._load_power_run_config()
        self.resource_config = resource_config or self._load_resource_config()
        self.timeout_manager = TimeoutManager(default_timeout_seconds=self.config["timeout_per_iteration_minutes"] * 60)

    def _load_power_run_config(self) -> dict[str, Any]:
        """Load power run configuration from config manager."""
        return {
            "iterations": self.config_manager.get("execution.power_run.iterations", 4),
            "warm_up_iterations": self.config_manager.get("execution.power_run.warm_up_iterations", 0),
            "timeout_per_iteration_minutes": self.config_manager.get(
                "execution.power_run.timeout_per_iteration_minutes", 60
            ),
            "fail_fast": self.config_manager.get("execution.power_run.fail_fast", False),
            "collect_metrics": self.config_manager.get("execution.power_run.collect_metrics", True),
        }

    def _load_resource_config(self) -> ResourceLimitsConfig:
        """Load resource limits configuration from config manager."""
        return ResourceLimitsConfig(
            memory_limit_mb=self.config_manager.get("execution.resource_limits.memory_limit_mb"),
            memory_warning_percent=self.config_manager.get("execution.resource_limits.memory_warning_percent", 75.0),
            memory_critical_percent=self.config_manager.get("execution.resource_limits.memory_critical_percent", 90.0),
            cpu_warning_percent=self.config_manager.get("execution.resource_limits.cpu_warning_percent", 90.0),
            default_operation_timeout=self.config["timeout_per_iteration_minutes"] * 60,
            enforce_timeouts=self.config_manager.get("execution.resource_limits.enforce_timeouts", True),
            enable_graceful_degradation=self.config_manager.get(
                "execution.resource_limits.enable_graceful_degradation", False
            ),
            degradation_memory_threshold_percent=self.config_manager.get(
                "execution.resource_limits.degradation_memory_threshold_percent", 80.0
            ),
        )

    def execute_power_runs(self, power_test_factory: Callable[..., Any], scale_factor: float = 1.0) -> PowerRunResult:
        """Execute multiple power run iterations with different stream permutations.

        Each iteration uses a different stream ID to ensure different query orderings
        as per TPC specifications (iteration 0 = stream 0, iteration 1 = stream 1, etc.).

        Args:
            power_test_factory: Function that creates a power test instance.
                              Should accept stream_id parameter if TPC-compliant.
            scale_factor: Scale factor for the benchmark

        Returns:
            Aggregated power run results
        """
        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = PowerRunResult(
            config=self.config,
            start_time=start_time_str,
            end_time="",
            total_duration=0.0,
            iterations_completed=0,
            iterations_successful=0,
            warm_up_iterations=self.config["warm_up_iterations"],
            avg_power_at_size=0.0,
            median_power_at_size=0.0,
            min_power_at_size=0.0,
            max_power_at_size=0.0,
            power_at_size_stdev=None,
        )

        # Start resource monitoring
        resource_monitor = ResourceLimitMonitor(
            config=self.resource_config,
            sample_interval=2.0,
        )
        resource_monitor.start()

        try:
            # Execute warm-up iterations
            if self.config["warm_up_iterations"] > 0:
                self.logger.info(f"Starting {self.config['warm_up_iterations']} warm-up iterations")

                for i in range(self.config["warm_up_iterations"]):
                    # Use different stream for each warm-up iteration too
                    power_test = self._create_power_test_with_stream(power_test_factory, i)
                    warm_up_result = self._execute_single_iteration(
                        power_test,
                        iteration_id=-(i + 1),  # Negative ID for warm-up
                        is_warm_up=True,
                    )
                    result.warm_up_results.append(warm_up_result)

                    if not warm_up_result.success and self.config["fail_fast"]:
                        result.errors.append(f"Warm-up iteration {i + 1} failed: {warm_up_result.error}")
                        result.success = False
                        return result

            # Execute actual test iterations
            self.logger.info(f"Starting {self.config['iterations']} power run iterations")

            power_at_size_values = []

            for i in range(self.config["iterations"]):
                # Use different stream for each iteration to ensure different query orderings
                stream_id = i % 41  # TPC-H has 41 permutations, cycle through them
                power_test = self._create_power_test_with_stream(power_test_factory, stream_id)
                iteration_result = self._execute_single_iteration(power_test, iteration_id=i + 1, is_warm_up=False)

                result.iteration_results.append(iteration_result)
                result.iterations_completed += 1

                if resource_monitor.limit_exceeded:
                    usage = resource_monitor.get_current_usage()
                    raise ResourceLimitExceeded(
                        "Resource limit exceeded during power run",
                        resource_type="memory",
                        current_value=usage.get("memory_mb", 0.0),
                        limit_value=self.resource_config.memory_limit_mb or 0.0,
                    )

                if iteration_result.success:
                    result.iterations_successful += 1
                    power_at_size_values.append(iteration_result.power_at_size)
                else:
                    result.errors.append(f"Iteration {i + 1} failed: {iteration_result.error}")

                    if self.config["fail_fast"]:
                        result.success = False
                        break

            # Calculate aggregated metrics
            if power_at_size_values:
                result.avg_power_at_size = mean(power_at_size_values)
                result.median_power_at_size = median(power_at_size_values)
                result.min_power_at_size = min(power_at_size_values)
                result.max_power_at_size = max(power_at_size_values)

                if len(power_at_size_values) > 1:
                    result.power_at_size_stdev = stdev(power_at_size_values)

            result.success = result.iterations_successful > 0

        except ResourceLimitExceeded as e:
            result.success = False
            result.resource_limit_exceeded = True
            result.errors.append(f"Resource limit exceeded: {e}")
            self.logger.error(f"Resource limit exceeded: {e}")

        except Exception as e:
            result.success = False
            result.errors.append(f"Power run execution failed: {e}")
            self.logger.error(f"Power run execution failed: {e}")

        finally:
            # Stop resource monitoring and capture usage summary
            usage_summary = resource_monitor.stop()
            result.resource_usage = usage_summary.to_dict()
            result.resource_limit_exceeded = usage_summary.limit_exceeded

            # Count timed-out iterations
            result.iterations_timed_out = sum(1 for ir in result.iteration_results if ir.timed_out)

            result.total_duration = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()

            # Log resource usage summary
            if usage_summary.warnings:
                self.logger.warning(f"Resource warnings during execution: {len(usage_summary.warnings)}")
            self.logger.info(
                f"Peak memory: {usage_summary.peak_memory_mb:.1f}MB, Peak CPU: {usage_summary.peak_cpu_percent:.1f}%"
            )

        return result

    def _create_power_test_with_stream(self, power_test_factory: Callable[..., Any], stream_id: int) -> Any:
        """Create a power test instance with the specified stream_id.

        Args:
            power_test_factory: Factory function for creating power test instances
            stream_id: Stream ID for TPC specification compliance

        Returns:
            Power test instance
        """
        import inspect

        # Try to determine if the factory accepts stream_id parameter
        try:
            sig = inspect.signature(power_test_factory)
            if "stream_id" in sig.parameters:
                self.logger.debug(f"Creating power test with stream_id={stream_id}")
                return power_test_factory(stream_id=stream_id)
            else:
                # Fallback: create without stream_id, but log that TPC compliance may be affected
                self.logger.warning(
                    "Power test factory doesn't support stream_id parameter. "
                    "TPC specification compliance may be affected."
                )
                return power_test_factory()
        except Exception as e:
            # Fallback: try both approaches
            try:
                return power_test_factory(stream_id=stream_id)
            except Exception:
                self.logger.warning(
                    f"Failed to create power test with stream_id={stream_id}: {e}. Falling back to no stream_id."
                )
                return power_test_factory()

    def _execute_single_iteration(
        self, power_test: Any, iteration_id: int, is_warm_up: bool = False
    ) -> PowerRunIteration:
        """Execute a single power run iteration with timeout enforcement.

        Args:
            power_test: Power test instance to execute
            iteration_id: Iteration identifier
            is_warm_up: Whether this is a warm-up iteration

        Returns:
            Single iteration result
        """
        start_time = mono_time()
        timeout_seconds = self.config["timeout_per_iteration_minutes"] * 60

        iteration_result = PowerRunIteration(
            iteration_id=iteration_id,
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            power_at_size=0.0,
            queries_executed=0,
            queries_successful=0,
        )

        try:
            if not is_warm_up:
                self.logger.info(f"Executing power run iteration {iteration_id}")

            power_result, timed_out = run_with_timeout(
                power_test.run,
                timeout_seconds,
                f"power_run_iteration_{iteration_id}",
            )

            if timed_out:
                iteration_result.timed_out = True
                iteration_result.success = False
                iteration_result.error = f"Iteration timed out after {timeout_seconds:.0f} seconds"
                self.logger.warning(f"Power run iteration {iteration_id} timed out after {timeout_seconds:.0f} seconds")
            else:
                # Extract metrics from power test result
                if hasattr(power_result, "power_at_size"):
                    iteration_result.power_at_size = power_result.power_at_size
                elif hasattr(power_result, "to_dict"):
                    result_dict = power_result.to_dict()
                    iteration_result.power_at_size = result_dict.get("power_at_size", 0.0)
                else:
                    # Fallback for different result formats
                    iteration_result.power_at_size = getattr(power_result, "power_at_size", 0.0)

                if hasattr(power_result, "query_results"):
                    iteration_result.query_results = power_result.query_results
                    if isinstance(power_result.query_results, dict):
                        iteration_result.queries_executed = len(power_result.query_results)
                        iteration_result.queries_successful = sum(
                            1 for qr in power_result.query_results.values() if qr.get("status") == "success"
                        )
                    elif isinstance(power_result.query_results, list):
                        iteration_result.queries_executed = len(power_result.query_results)
                        iteration_result.queries_successful = sum(
                            1 for qr in power_result.query_results if qr.get("status") == "success"
                        )

                iteration_result.success = True

        except BenchboxTimeoutError as e:
            iteration_result.timed_out = True
            iteration_result.success = False
            iteration_result.error = str(e)
            self.logger.warning(f"Power run iteration {iteration_id} timed out: {e}")

        except Exception as e:
            iteration_result.success = False
            iteration_result.error = str(e)
            self.logger.error(f"Power run iteration {iteration_id} failed: {e}")

        finally:
            iteration_result.end_time = mono_time()
            iteration_result.duration = iteration_result.end_time - iteration_result.start_time

        return iteration_result


class ConcurrentQueryExecutor:
    """Manages concurrent query execution for throughput testing.

    QUARANTINED: no production caller. The only two call sites that ever
    routed through this class (``benchbox.core.tpch.streams.TPCHStreamRunner``
    and ``benchbox.core.tpcds.benchmark.runner.TPCDSBenchmark.run_streams``)
    always terminated in a non-executing stub that faked query success
    without running SQL, so no real workload ever reached this executor. Both
    stub call sites now raise ``NotImplementedError`` instead. The production
    concurrent-stream executor is
    ``benchbox.core.throughput.runner.StreamRunner``. See the module
    docstring for the full consolidation rationale.
    """

    def __init__(
        self,
        config_manager: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        resource_config: Optional[ResourceLimitsConfig] = None,
    ):
        """Initialize concurrent query executor.

        Args:
            config_manager: Configuration manager instance
            logger: Logger instance
            resource_config: Resource limits configuration (optional)
        """
        if config_manager is None:
            from benchbox.utils.config_interface import create_cli_config_adapter

            self.config_manager = create_cli_config_adapter()
        else:
            self.config_manager = config_manager
        self.logger = logger or logging.getLogger(__name__)
        self.config = self._load_concurrent_config()
        self.resource_config = resource_config or self._load_resource_config()
        self.timeout_manager = TimeoutManager(default_timeout_seconds=self.config["stream_timeout_seconds"])

    def _load_resource_config(self) -> ResourceLimitsConfig:
        """Load resource limits configuration from config manager."""
        return ResourceLimitsConfig(
            memory_limit_mb=self.config_manager.get("execution.resource_limits.memory_limit_mb"),
            memory_warning_percent=self.config_manager.get("execution.resource_limits.memory_warning_percent", 75.0),
            memory_critical_percent=self.config_manager.get("execution.resource_limits.memory_critical_percent", 90.0),
            cpu_warning_percent=self.config_manager.get("execution.resource_limits.cpu_warning_percent", 90.0),
            default_operation_timeout=self.config["stream_timeout_seconds"],
            enforce_timeouts=self.config_manager.get("execution.resource_limits.enforce_timeouts", True),
            enable_graceful_degradation=self.config_manager.get(
                "execution.resource_limits.enable_graceful_degradation", False
            ),
            degradation_memory_threshold_percent=self.config_manager.get(
                "execution.resource_limits.degradation_memory_threshold_percent", 80.0
            ),
        )

    def _load_concurrent_config(self) -> dict[str, Any]:
        """Load concurrent query configuration from config manager."""
        return {
            "enabled": self.config_manager.get("execution.concurrent_queries.enabled", False),
            "max_concurrent": self.config_manager.get("execution.concurrent_queries.max_concurrent", 2),
            "query_timeout_seconds": self.config_manager.get("execution.concurrent_queries.query_timeout_seconds", 300),
            "stream_timeout_seconds": self.config_manager.get(
                "execution.concurrent_queries.stream_timeout_seconds", 3600
            ),
            "retry_failed_queries": self.config_manager.get("execution.concurrent_queries.retry_failed_queries", True),
            "max_retries": self.config_manager.get("execution.concurrent_queries.max_retries", 3),
        }

    def execute_concurrent_queries(
        self,
        query_executor_factory: Callable[[int], Any],
        num_streams: Optional[int] = None,
    ) -> ConcurrentQueryResult:
        """Execute concurrent query streams for throughput testing with TPC specification compliance.

        Each concurrent stream uses a different stream ID to ensure different query permutations
        as per TPC specifications (stream 0, stream 1, stream 2, etc.).

        Args:
            query_executor_factory: Function that creates query executor for given stream ID.
                                   Should return executor that uses TPC-compliant permutation for the stream.
            num_streams: Number of concurrent streams (uses config if not specified)

        Returns:
            Concurrent query execution results
        """
        if not self.config["enabled"]:
            raise ValueError("Concurrent queries are not enabled in configuration")

        num_streams = num_streams or self.config["max_concurrent"]
        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = ConcurrentQueryResult(
            config=self.config,
            start_time=start_time_str,
            end_time="",
            total_duration=0.0,
            max_concurrent=num_streams,
            queries_executed=0,
            queries_successful=0,
            queries_failed=0,
            throughput_queries_per_second=0.0,
        )

        # Start resource monitoring
        resource_monitor = ResourceLimitMonitor(
            config=self.resource_config,
            sample_interval=2.0,
        )
        resource_monitor.start()

        try:
            self.logger.info(f"Starting concurrent execution with {num_streams} streams")

            # Execute streams concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_streams) as executor:
                futures = []

                for stream_id in range(num_streams):
                    future = executor.submit(
                        self._execute_stream,
                        query_executor_factory(stream_id),
                        stream_id,
                    )
                    futures.append(future)

                # Wait for all streams to complete
                for future in concurrent.futures.as_completed(futures):
                    try:
                        stream_result = future.result()
                        result.stream_results.append(stream_result)

                        result.queries_executed += stream_result.get("queries_executed", 0)
                        result.queries_successful += stream_result.get("queries_successful", 0)
                        result.queries_failed += stream_result.get("queries_failed", 0)

                        if resource_monitor.limit_exceeded:
                            usage = resource_monitor.get_current_usage()
                            raise ResourceLimitExceeded(
                                "Resource limit exceeded during concurrent execution",
                                resource_type="memory",
                                current_value=usage.get("memory_mb", 0.0),
                                limit_value=self.resource_config.memory_limit_mb or 0.0,
                            )

                    except Exception as e:
                        result.errors.append(f"Stream execution failed: {e}")
                        self.logger.error(f"Stream execution failed: {e}")

            # Calculate throughput (recalculated in finally after total_duration is set)
            result.success = result.queries_successful > 0

        except ResourceLimitExceeded as e:
            result.success = False
            result.resource_limit_exceeded = True
            result.errors.append(f"Resource limit exceeded: {e}")
            self.logger.error(f"Resource limit exceeded: {e}")

        except Exception as e:
            result.success = False
            result.errors.append(f"Concurrent query execution failed: {e}")
            self.logger.error(f"Concurrent query execution failed: {e}")

        finally:
            # Stop resource monitoring and capture usage summary
            usage_summary = resource_monitor.stop()
            result.resource_usage = usage_summary.to_dict()
            result.resource_limit_exceeded = usage_summary.limit_exceeded

            # Count timed-out streams
            result.streams_timed_out = sum(1 for sr in result.stream_results if sr.get("timed_out", False))

            result.total_duration = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()

            # Calculate throughput with actual total duration
            if result.total_duration > 0:
                result.throughput_queries_per_second = result.queries_executed / result.total_duration

            # Log resource usage summary
            if usage_summary.warnings:
                self.logger.warning(f"Resource warnings during execution: {len(usage_summary.warnings)}")
            self.logger.info(
                f"Peak memory: {usage_summary.peak_memory_mb:.1f}MB, Peak CPU: {usage_summary.peak_cpu_percent:.1f}%"
            )

        return result

    def _execute_stream(self, query_executor: Any, stream_id: int) -> dict[str, Any]:
        """Execute a single query stream with timeout enforcement.

        Args:
            query_executor: Query executor for this stream
            stream_id: Stream identifier

        Returns:
            Stream execution results
        """
        stream_start = time.time()
        timeout_seconds = self.config["stream_timeout_seconds"]

        stream_result = {
            "stream_id": stream_id,
            "start_time": stream_start,
            "end_time": 0.0,
            "duration": 0.0,
            "queries_executed": 0,
            "queries_successful": 0,
            "queries_failed": 0,
            "success": True,
            "timed_out": False,
            "error": None,
        }

        try:
            self.logger.info(f"Starting stream {stream_id}")

            executor_result, timed_out = run_with_timeout(
                query_executor.run if hasattr(query_executor, "run") else lambda: None,
                timeout_seconds,
                f"stream_{stream_id}",
            )

            if timed_out:
                stream_result["timed_out"] = True
                stream_result["success"] = False
                stream_result["error"] = f"Stream timed out after {timeout_seconds:.0f} seconds"
                self.logger.warning(f"Stream {stream_id} timed out after {timeout_seconds:.0f} seconds")

            elif executor_result is not None:
                # Extract metrics from executor result
                if hasattr(executor_result, "queries_executed"):
                    stream_result["queries_executed"] = executor_result.queries_executed
                if hasattr(executor_result, "queries_successful"):
                    stream_result["queries_successful"] = executor_result.queries_successful
                if hasattr(executor_result, "queries_failed"):
                    stream_result["queries_failed"] = executor_result.queries_failed
            else:
                self.logger.warning(f"Query executor for stream {stream_id} does not have run() method")

        except BenchboxTimeoutError as e:
            stream_result["timed_out"] = True
            stream_result["success"] = False
            stream_result["error"] = str(e)
            self.logger.warning(f"Stream {stream_id} timed out: {e}")

        except Exception as e:
            stream_result["success"] = False
            stream_result["error"] = str(e)
            self.logger.error(f"Stream {stream_id} failed: {e}")

        finally:
            stream_result["end_time"] = time.time()
            stream_result["duration"] = stream_result["end_time"] - stream_result["start_time"]

        return stream_result
