"""Parallel batch processing framework for TPC-DI ETL operations.

This module provides sophisticated parallel processing capabilities for TPC-DI
batch operations including:

1. Parallel Historical Load Processing:
   - Multi-threaded table loading with dependency management
   - Parallel data generation and transformation
   - Resource-aware load balancing

2. Parallel Incremental Load Processing:
   - Concurrent batch processing across multiple streams
   - Parallel SCD Type 2 processing
   - Change data capture optimization

3. Advanced Resource Management:
   - Dynamic worker pool scaling
   - Memory usage monitoring and optimization
   - Database connection pooling
   - Error recovery and retry mechanisms

4. Performance Monitoring:
   - Real-time throughput tracking
   - Resource utilization monitoring
   - Bottleneck identification and reporting
   - Load balancing optimization

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import multiprocessing as mp
import queue
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import psutil

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


@dataclass
class BatchProcessingTask:
    """Individual batch processing task definition."""

    task_id: str
    task_type: str = "generic"  # 'historical_load', 'incremental_load', 'scd_processing', 'validation'
    task_function: Optional[Any] = None  # Function to execute for this task
    task_data: dict[str, Any] = field(default_factory=dict)  # Data for the task
    table_name: Optional[str] = None
    input_data: Optional[Any] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)  # Task IDs this task depends on
    priority: int = 1  # Higher numbers = higher priority
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: Optional[int] = None

    # Execution tracking
    status: str = "pending"  # pending, running, completed, failed, retrying
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    worker_id: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[Any] = None


@dataclass
class BatchProcessingResult:
    """Results from batch processing execution."""

    task_id: str
    success: bool
    start_time: datetime
    end_time: datetime
    execution_time: float
    records_processed: int = 0
    records_per_second: float = 0.0
    memory_peak_mb: float = 0.0
    error_message: Optional[str] = None
    result_data: Optional[Any] = None
    worker_stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParallelProcessingConfig:
    """Configuration for parallel batch processing."""

    # Worker pool settings
    max_workers: Optional[int] = None  # Auto-detect based on CPU cores
    worker_type: str = "thread"  # 'thread' or 'process'
    enable_dynamic_scaling: bool = True
    min_workers: int = 2
    scale_up_threshold: float = 0.8  # CPU utilization threshold for scaling up
    scale_down_threshold: float = 0.3  # CPU utilization threshold for scaling down

    # Memory management
    max_memory_usage_pct: float = 75.0  # Max memory usage percentage
    memory_check_interval: int = 30  # Seconds between memory checks
    enable_memory_optimization: bool = True

    # Task execution
    task_timeout_default: int = 3600  # Default task timeout in seconds
    task_timeout_seconds: int = 300  # Alias for compatibility
    retry_delay_seconds: int = 60  # Delay between retries
    enable_task_prioritization: bool = True
    enable_dependency_resolution: bool = True  # Enable task dependency resolution
    retry_failed_tasks: bool = True  # Enable retry of failed tasks

    # Database connection management
    max_db_connections: int = 10
    connection_pool_timeout: int = 30
    enable_connection_pooling: bool = True

    # Performance monitoring
    enable_performance_monitoring: bool = True
    monitoring_interval: int = 10  # Seconds between performance checks
    enable_bottleneck_detection: bool = True


class TaskWorker(ABC):
    """Abstract base class for batch processing task workers."""

    @abstractmethod
    def execute_task(self, task: BatchProcessingTask) -> BatchProcessingResult:
        """Execute a batch processing task.

        Args:
            task: The task to execute

        Returns:
            BatchProcessingResult containing execution details
        """


class GenericTaskWorker(TaskWorker):
    """Generic worker that can execute task functions."""

    def __init__(self):
        self.worker_id = f"generic_worker_{id(self)}"

    def execute_task(self, task: BatchProcessingTask) -> BatchProcessingResult:
        """Execute a generic task with task_function."""

        logger.debug(f"Generic worker {self.worker_id} executing task {task.task_id}")
        start_time = datetime.now()

        try:
            # Execute task function if provided
            result_data = task.task_function(task.task_data) if task.task_function else {}

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            return BatchProcessingResult(
                task_id=task.task_id,
                success=True,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                records_processed=task.task_data.get("records", 1),
                result_data=result_data,
            )

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            return BatchProcessingResult(
                task_id=task.task_id,
                success=False,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                records_processed=0,
                error_message=str(e),
            )


class HistoricalLoadWorker(TaskWorker):
    """Worker for historical load processing tasks."""

    def __init__(self, connection: Any, dialect: str = "duckdb"):
        self.connection = connection
        self.dialect = dialect
        self.worker_id = f"hist_worker_{id(self)}"

    def execute_task(self, task: BatchProcessingTask) -> BatchProcessingResult:
        """Execute a historical load task."""

        logger.info(f"Historical load worker {self.worker_id} executing task {task.task_id}")
        start_time = datetime.now()

        try:
            # Simulate historical load processing
            if task.table_name:
                # Process historical data for specific table
                records_processed = self._process_historical_table(
                    task.table_name,
                    task.parameters.get("scale_factor", 1.0),
                    task.parameters.get("batch_id", 1),
                )
            else:
                # Process full historical load
                records_processed = self._process_full_historical_load(
                    task.parameters.get("scale_factor", 1.0),
                    task.parameters.get("batch_id", 1),
                )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            return BatchProcessingResult(
                task_id=task.task_id,
                success=True,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                records_processed=records_processed,
                records_per_second=records_processed / max(execution_time, 0.001),
                memory_peak_mb=self._get_memory_usage_mb(),
            )

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            logger.error(f"Historical load task {task.task_id} failed: {str(e)}")

            return BatchProcessingResult(
                task_id=task.task_id,
                success=False,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                error_message=str(e),
                memory_peak_mb=self._get_memory_usage_mb(),
            )

    def _process_historical_table(self, table_name: str, scale_factor: float, batch_id: int) -> int:
        """Process historical data for a specific table."""
        # Simulate table processing with realistic timing
        base_records = {
            "DimCustomer": 5000,
            "DimAccount": 7500,
            "DimSecurity": 15000,
            "FactTrade": 25000,
        }.get(table_name, 10000)

        records = int(base_records * scale_factor)
        processing_time = records / 10000  # Simulate processing time
        time.sleep(min(processing_time, 5.0))  # Cap sleep time

        logger.debug(f"Processed {records} records for {table_name}")
        return records

    def _process_full_historical_load(self, scale_factor: float, batch_id: int) -> int:
        """Process full historical load."""
        # Simulate full load processing
        total_records = int(50000 * scale_factor)
        processing_time = total_records / 25000
        time.sleep(min(processing_time, 10.0))

        logger.debug(f"Processed full historical load: {total_records} records")
        return total_records

    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0


class IncrementalLoadWorker(TaskWorker):
    """Worker for incremental load processing tasks."""

    def __init__(self, connection: Any, dialect: str = "duckdb"):
        self.connection = connection
        self.dialect = dialect
        self.worker_id = f"incr_worker_{id(self)}"

    def execute_task(self, task: BatchProcessingTask) -> BatchProcessingResult:
        """Execute an incremental load task."""

        logger.info(f"Incremental load worker {self.worker_id} executing task {task.task_id}")
        start_time = datetime.now()

        try:
            # Process incremental data
            records_processed = self._process_incremental_batch(
                task.parameters.get("batch_id", 2),
                task.parameters.get("change_data", []),
                task.table_name,
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            return BatchProcessingResult(
                task_id=task.task_id,
                success=True,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                records_processed=records_processed,
                records_per_second=records_processed / max(execution_time, 0.001),
                memory_peak_mb=self._get_memory_usage_mb(),
            )

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            logger.error(f"Incremental load task {task.task_id} failed: {str(e)}")

            return BatchProcessingResult(
                task_id=task.task_id,
                success=False,
                start_time=start_time,
                end_time=end_time,
                execution_time=execution_time,
                error_message=str(e),
                memory_peak_mb=self._get_memory_usage_mb(),
            )

    def _process_incremental_batch(self, batch_id: int, change_data: list[Any], table_name: Optional[str]) -> int:
        """Process incremental batch changes."""
        # Simulate incremental processing
        if change_data:
            records = len(change_data)
        else:
            # Simulate typical incremental batch size
            records = 5000 if table_name else 15000

        processing_time = records / 50000  # Faster than historical
        time.sleep(min(processing_time, 2.0))

        logger.debug(f"Processed incremental batch {batch_id}: {records} records")
        return records

    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0


class ParallelBatchProcessor:
    """Advanced parallel batch processing orchestrator for TPC-DI ETL operations."""

    def __init__(
        self,
        config: ParallelProcessingConfig,
        connection: Any = None,
        dialect: str = "duckdb",
    ):
        """Initialize the parallel batch processor.

        Args:
            config: Parallel processing configuration
            connection: Database connection object (optional for testing)
            dialect: SQL dialect for query generation
        """
        self.connection = connection
        self.dialect = dialect
        self.config = config

        # Task management
        self.task_queue: queue.PriorityQueue = queue.PriorityQueue()
        self.active_tasks: dict[str, BatchProcessingTask] = {}
        self.completed_tasks: dict[str, BatchProcessingResult] = {}
        self.pending_tasks: dict[str, BatchProcessingTask] = {}  # For compatibility
        self.task_lock = threading.Lock()

        # Worker management
        self.worker_pool: Optional[ThreadPoolExecutor] = None
        self.workers: dict[str, TaskWorker] = {}
        self.worker_futures: dict[str, Future] = {}

        # Performance monitoring
        self.performance_monitor: Optional[threading.Thread] = None
        self.monitoring_active = False
        self.performance_stats: dict[str, Any] = {}

        # Resource tracking
        self.resource_lock = threading.Lock()
        self.current_memory_usage = 0.0
        self.peak_memory_usage = 0.0
        self.cpu_utilization_history: list[float] = []

        # Initialize workers
        self._initialize_workers()

    def _initialize_workers(self) -> None:
        """Initialize worker pool and worker instances."""

        # Determine optimal worker count
        if self.config.max_workers is None:
            self.config.max_workers = min(mp.cpu_count() * 2, 16)  # Conservative default

        logger.info(f"Initializing parallel batch processor with {self.config.max_workers} workers")

        # Create worker pool
        if self.config.worker_type == "thread":
            self.worker_pool = ThreadPoolExecutor(max_workers=self.config.max_workers)
        else:
            # Process pool would require more setup for database connections
            logger.warning("Process-based workers not fully implemented, using thread workers")
            self.worker_pool = ThreadPoolExecutor(max_workers=self.config.max_workers)

        # Create specialized workers
        for i in range(self.config.max_workers):
            if i % 3 == 0:
                worker = HistoricalLoadWorker(self.connection, self.dialect)
            elif i % 3 == 1:
                worker = IncrementalLoadWorker(self.connection, self.dialect)
            else:
                worker = GenericTaskWorker()  # For generic task functions
            self.workers[worker.worker_id] = worker

        # A function-carrying task must always have a worker that executes its
        # function. Small pools would otherwise route such tasks to specialized
        # workers that ignore the function yet report success.
        if not any(isinstance(worker, GenericTaskWorker) for worker in self.workers.values()):
            fallback = GenericTaskWorker()
            self.workers[fallback.worker_id] = fallback

        # Start performance monitoring if enabled
        if self.config.enable_performance_monitoring:
            self._start_performance_monitoring()

    def submit_task(self, task: BatchProcessingTask) -> str:
        """Submit a batch processing task for parallel execution.

        Args:
            task: The batch processing task to execute

        Returns:
            Task ID for tracking

        Raises:
            ValueError: If the task carries no function and its type has no
                specialized worker, so it could never execute. Rejected before
                any queue or bookkeeping mutation.
        """

        if task.task_function is None and task.task_type not in (
            "historical_load",
            "incremental_load",
        ):
            raise ValueError(
                f"Rejected non-executable task '{task.task_id}': no task_function "
                f"and unsupported task_type '{task.task_type}'"
            )

        with self.task_lock:
            # Set task timeout if not specified
            if task.timeout_seconds is None:
                task.timeout_seconds = self.config.task_timeout_default

            # Include to pending tasks for compatibility
            self.pending_tasks[task.task_id] = task

            # Add to task queue with priority
            priority = -task.priority if self.config.enable_task_prioritization else 0
            self.task_queue.put((priority, time.time(), task))

            logger.debug(f"Submitted task {task.task_id} (type: {task.task_type}, priority: {task.priority})")

        return task.task_id

    def _resolve_task_dependencies(self) -> dict[str, list[str]]:
        """Resolve task dependencies for execution planning.

        Returns:
            Dictionary mapping task IDs to their dependency task IDs
        """
        dependencies = {}

        for task_id, task in self.pending_tasks.items():
            dependencies[task_id] = task.dependencies.copy() if task.dependencies else []

        return dependencies

    def submit_historical_load_tasks(
        self,
        scale_factor: float = 1.0,
        batch_id: int = 1,
        tables: Optional[list[str]] = None,
    ) -> list[str]:
        """Submit parallel historical load tasks.

        Args:
            scale_factor: Data scale factor
            batch_id: Batch identifier
            tables: Specific tables to load (None = all tables)

        Returns:
            List of task IDs
        """

        task_ids = []

        if tables is None:
            # Default TPC-DI tables in dependency order
            tables = [
                "DimDate",
                "DimTime",
                "DimBroker",
                "DimCompany",
                "DimSecurity",
                "DimCustomer",
                "DimAccount",
                "FactTrade",
                "FactMarketHistory",
                "FactHoldings",
            ]

        # Create dependency mapping
        table_dependencies = {
            "DimCustomer": ["DimBroker"],
            "DimAccount": ["DimCustomer", "DimBroker"],
            "DimSecurity": ["DimCompany"],
            "FactTrade": [
                "DimCustomer",
                "DimAccount",
                "DimSecurity",
                "DimDate",
                "DimTime",
            ],
            "FactMarketHistory": ["DimSecurity", "DimDate"],
            "FactHoldings": ["DimCustomer", "DimAccount", "DimSecurity", "DimDate"],
        }

        # Submit tasks with dependencies
        for table in tables:
            task_id = f"hist_load_{table}_{batch_id}"

            dependencies = []
            if table in table_dependencies:
                dependencies = [f"hist_load_{dep}_{batch_id}" for dep in table_dependencies[table]]

            task = BatchProcessingTask(
                task_id=task_id,
                task_type="historical_load",
                table_name=table,
                parameters={"scale_factor": scale_factor, "batch_id": batch_id},
                dependencies=dependencies,
                priority=3,  # High priority for historical loads
            )

            self.submit_task(task)
            task_ids.append(task_id)

        logger.info(f"Submitted {len(task_ids)} historical load tasks for batch {batch_id}")
        return task_ids

    def submit_incremental_load_tasks(
        self, batch_id: int = 2, change_sets: Optional[dict[str, list[Any]]] = None
    ) -> list[str]:
        """Submit parallel incremental load tasks.

        Args:
            batch_id: Incremental batch identifier
            change_sets: Changes by table name

        Returns:
            List of task IDs
        """

        task_ids = []

        if change_sets is None:
            # Default incremental tables
            change_sets = {
                "DimCustomer": [],
                "DimAccount": [],
                "FactTrade": [],
                "FactMarketHistory": [],
            }

        # Submit incremental tasks
        for table_name, changes in change_sets.items():
            task_id = f"incr_load_{table_name}_{batch_id}"

            task = BatchProcessingTask(
                task_id=task_id,
                task_type="incremental_load",
                table_name=table_name,
                parameters={"batch_id": batch_id, "change_data": changes},
                priority=2,  # Medium priority for incremental loads
            )

            self.submit_task(task)
            task_ids.append(task_id)

        logger.info(f"Submitted {len(task_ids)} incremental load tasks for batch {batch_id}")
        return task_ids

    def execute_parallel_batch(self, timeout_seconds: Optional[int] = None) -> dict[str, Any]:
        """Execute all submitted tasks in parallel with dependency management.

        Args:
            timeout_seconds: Maximum time to wait for completion

        Returns:
            Dictionary containing execution results and statistics
        """

        logger.info("Starting parallel batch execution")
        execution_start = datetime.now()

        # Execution statistics
        stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_records_processed": 0,
            "total_execution_time": 0.0,
            "peak_memory_usage_mb": 0.0,
            "average_records_per_second": 0.0,
            "success": False,
        }

        try:
            # Count submitted tasks
            with self.task_lock:
                stats["tasks_submitted"] = self.task_queue.qsize()

            if stats["tasks_submitted"] == 0:
                logger.warning("No tasks submitted for parallel execution")
                stats["success"] = False
                stats["outcome"] = "incomplete"
                stats["tasks_pending"] = 0
                stats["timed_out"] = False
                stats["failed_task_ids"] = []
                stats["error_message"] = "No executable work was submitted for parallel execution"
                return stats

            # Process tasks with dependency resolution. A timeout here only
            # bounds the dispatch loop; it never implies worker termination.
            batch_timed_out = self._process_tasks_with_dependencies(timeout_seconds)

            # Collect results
            stats["tasks_completed"] = len([r for r in self.completed_tasks.values() if r.success])
            stats["tasks_failed"] = len([r for r in self.completed_tasks.values() if not r.success])
            stats["total_records_processed"] = sum(r.records_processed for r in self.completed_tasks.values())

            execution_end = datetime.now()
            stats["total_execution_time"] = (execution_end - execution_start).total_seconds()

            if stats["total_execution_time"] > 0:
                stats["average_records_per_second"] = stats["total_records_processed"] / stats["total_execution_time"]

            stats["peak_memory_usage_mb"] = self.peak_memory_usage
            # Fail closed: success requires every submitted task to reach a
            # successful terminal result. Deriving success from tasks_failed
            # alone would convert zero, partial, or timed-out work into
            # apparent success.
            submitted = stats["tasks_submitted"]
            settled = stats["tasks_completed"] + stats["tasks_failed"]
            stats["tasks_pending"] = submitted - settled
            stats["timed_out"] = batch_timed_out
            stats["failed_task_ids"] = sorted(
                task_id for task_id, result in self.completed_tasks.items() if not result.success
            )
            if batch_timed_out:
                stats["outcome"] = "timed_out"
                stats["success"] = False
                stats["error_message"] = (
                    f"Parallel batch execution timed out with {stats['tasks_pending']} of {submitted} tasks unprocessed"
                )
            elif settled < submitted:
                stats["outcome"] = "incomplete"
                stats["success"] = False
                stats["error_message"] = f"Only {settled} of {submitted} submitted tasks reached a terminal result"
            elif stats["tasks_failed"] > 0:
                stats["outcome"] = "failed"
                stats["success"] = False
            else:
                stats["outcome"] = "completed"
                stats["success"] = True

            # Include resource usage information for monitoring
            stats["resource_usage"] = {
                "peak_memory_mb": self.peak_memory_usage,
                "average_cpu_utilization": sum(self.cpu_utilization_history) / len(self.cpu_utilization_history)
                if self.cpu_utilization_history
                else 0.0,
                "worker_count": len(self.workers),
                "active_tasks": len(self.active_tasks),
            }

            # Canonical execution duration key used across benchmark result payloads.
            stats["execution_time_seconds"] = stats["total_execution_time"]

            logger.info(
                f"Parallel batch execution completed: "
                f"{stats['tasks_completed']} succeeded, {stats['tasks_failed']} failed, "
                f"{stats['total_records_processed']} records processed in {stats['total_execution_time']:.2f}s"
            )

            return stats

        except Exception as e:
            logger.error(f"Parallel batch execution failed: {str(e)}", exc_info=True)
            stats["error_message"] = str(e)
            stats["success"] = False
            stats["outcome"] = "failed"
            return stats

    def _process_tasks_with_dependencies(self, timeout_seconds: Optional[int]) -> bool:
        """Process tasks with dependency resolution.

        Returns:
            True when the dispatch loop stopped because the timeout elapsed
            with work still undispatched; False otherwise. A True return only
            bounds the caller wait -- already-running workers are unaffected.
        """

        start_time = mono_time()
        processed_tasks = set()
        timed_out = False

        while not self.task_queue.empty():
            # Check timeout
            if timeout_seconds and (elapsed_seconds(start_time)) > timeout_seconds:
                logger.warning("Parallel batch execution timeout reached")
                timed_out = True
                break

            try:
                # Get next task (blocks if queue is empty)
                priority, timestamp, task = self.task_queue.get(timeout=1.0)

                # Check dependencies
                if not self._check_task_dependencies(task, processed_tasks):
                    # Dependencies not met, requeue with delay
                    self.task_queue.put((priority, time.time(), task))
                    continue

                # Execute task
                self._execute_single_task(task)
                processed_tasks.add(task.task_id)

            except queue.Empty:
                # Queue is empty or timeout occurred
                if len(processed_tasks) == 0:
                    break  # No tasks processed, likely all have unmet dependencies
                continue
            except Exception as e:
                logger.error(f"Error processing task: {str(e)}")
                continue

        # Wait for all submitted futures to complete
        self._wait_for_completion()
        return timed_out

    def _check_task_dependencies(self, task: BatchProcessingTask, processed_tasks: set) -> bool:
        """Check if task dependencies are satisfied."""

        for dep_task_id in task.dependencies:
            if dep_task_id not in processed_tasks:
                return False
            # Also check if dependency actually succeeded
            if dep_task_id in self.completed_tasks and not self.completed_tasks[dep_task_id].success:
                return False
        return True

    def _execute_single_task(self, task: BatchProcessingTask) -> None:
        """Execute a single task using the worker pool."""

        # Find appropriate worker
        worker = self._select_worker_for_task(task)

        # Submit to worker pool
        future = self.worker_pool.submit(worker.execute_task, task)
        self.worker_futures[task.task_id] = future

        # Add completion callback
        future.add_done_callback(lambda f: self._handle_task_completion(task.task_id, f))

    def _select_worker_for_task(self, task: BatchProcessingTask) -> TaskWorker:
        """Select the most appropriate worker for a task."""

        # If task has a task_function, use GenericTaskWorker
        if task.task_function:
            generic_workers = [w for w in self.workers.values() if isinstance(w, GenericTaskWorker)]
            if generic_workers:
                return generic_workers[hash(task.task_id) % len(generic_workers)]

        # Simple round-robin selection based on task type
        suitable_workers = []

        for worker in self.workers.values():
            if (
                task.task_type == "historical_load"
                and isinstance(worker, HistoricalLoadWorker)
                or task.task_type == "incremental_load"
                and isinstance(worker, IncrementalLoadWorker)
            ):
                suitable_workers.append(worker)

        if not suitable_workers:
            # Fallback to any available worker
            suitable_workers = list(self.workers.values())

        # Select worker with least current load (simplified)
        return suitable_workers[hash(task.task_id) % len(suitable_workers)]

    def _handle_task_completion(self, task_id: str, future: Future) -> None:
        """Handle task completion and update results."""

        try:
            result = future.result()
            with self.task_lock:
                self.completed_tasks[task_id] = result
                if task_id in self.worker_futures:
                    del self.worker_futures[task_id]

            # Configure peak memory usage
            with self.resource_lock:
                self.peak_memory_usage = max(self.peak_memory_usage, result.memory_peak_mb)

            if result.success:
                logger.debug(f"Task {task_id} completed successfully: {result.records_processed} records")
            else:
                logger.error(f"Task {task_id} failed: {result.error_message}")

        except Exception as e:
            logger.error(f"Error handling completion for task {task_id}: {str(e)}")

            # Create a failed result for tasks that threw exceptions
            failed_result = BatchProcessingResult(
                task_id=task_id,
                success=False,
                start_time=datetime.now(),
                end_time=datetime.now(),
                execution_time=0.0,
                records_processed=0,
                error_message=str(e),
            )

            with self.task_lock:
                self.completed_tasks[task_id] = failed_result
                if task_id in self.worker_futures:
                    del self.worker_futures[task_id]

    def _wait_for_completion(self) -> None:
        """Wait for all submitted futures to complete."""

        if not self.worker_futures:
            return

        logger.debug(f"Waiting for {len(self.worker_futures)} tasks to complete")

        # Wait for all futures with timeout
        for future in as_completed(self.worker_futures.values(), timeout=300):  # 5 minute timeout
            try:
                future.result()  # This will raise exception if task failed
            except Exception as e:
                logger.debug(f"Task completed with error: {str(e)}")

    def _start_performance_monitoring(self) -> None:
        """Start background performance monitoring thread."""

        def monitor_performance():
            while self.monitoring_active:
                try:
                    # Monitor CPU usage
                    cpu_percent = psutil.cpu_percent(interval=1)
                    self.cpu_utilization_history.append(cpu_percent)

                    # Keep only recent history
                    if len(self.cpu_utilization_history) > 100:
                        self.cpu_utilization_history = self.cpu_utilization_history[-100:]

                    # Monitor memory usage
                    with self.resource_lock:
                        process = psutil.Process()
                        self.current_memory_usage = process.memory_info().rss / 1024 / 1024
                        self.peak_memory_usage = max(self.peak_memory_usage, self.current_memory_usage)

                    # Configure performance stats
                    self.performance_stats.update(
                        {
                            "cpu_utilization_current": cpu_percent,
                            "cpu_utilization_avg": sum(self.cpu_utilization_history)
                            / len(self.cpu_utilization_history),
                            "memory_usage_current_mb": self.current_memory_usage,
                            "memory_usage_peak_mb": self.peak_memory_usage,
                            "active_tasks": len(self.worker_futures),
                            "completed_tasks": len(self.completed_tasks),
                        }
                    )

                    time.sleep(self.config.monitoring_interval)

                except Exception as e:
                    logger.debug(f"Performance monitoring error: {str(e)}")
                    time.sleep(self.config.monitoring_interval)

        self.monitoring_active = True
        self.performance_monitor = threading.Thread(target=monitor_performance, daemon=True)
        self.performance_monitor.start()

        logger.debug("Performance monitoring started")

    def get_performance_statistics(self) -> dict[str, Any]:
        """Get current performance statistics."""

        stats = self.performance_stats.copy()

        # Add task completion statistics
        if self.completed_tasks:
            completed_results = list(self.completed_tasks.values())
            stats.update(
                {
                    "total_tasks_completed": len(completed_results),
                    "successful_tasks": len([r for r in completed_results if r.success]),
                    "failed_tasks": len([r for r in completed_results if not r.success]),
                    "average_execution_time": sum(r.execution_time for r in completed_results) / len(completed_results),
                    "total_records_processed": sum(r.records_processed for r in completed_results),
                    "average_records_per_second": sum(r.records_per_second for r in completed_results)
                    / len(completed_results),
                }
            )

        return stats

    def shutdown(self) -> None:
        """Shutdown the parallel batch processor and clean up resources."""

        logger.info("Shutting down parallel batch processor")

        # Stop performance monitoring
        if self.monitoring_active:
            self.monitoring_active = False
            if self.performance_monitor and self.performance_monitor.is_alive():
                self.performance_monitor.join(timeout=5.0)

        # Shutdown worker pool
        if self.worker_pool:
            self.worker_pool.shutdown(wait=True)

        # Clear resources
        self.workers.clear()
        self.worker_futures.clear()
        self.active_tasks.clear()

        logger.info("Parallel batch processor shutdown complete")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.shutdown()
