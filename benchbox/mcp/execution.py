"""Async execution model for BenchBox MCP server.

Provides infrastructure for running benchmarks asynchronously with
status tracking and cancellation support.

This module uses the public BenchBox API (benchbox.*, benchbox.platforms.*)
and the core benchmark registry for all benchmark operations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any

from benchbox.core.benchmark_registry import get_public_benchmark_class

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Status of an async benchmark execution."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionState:
    """State of a benchmark execution.

    Tracks all information about an in-progress or completed benchmark run.
    """

    execution_id: str
    platform: str
    benchmark: str
    scale_factor: float
    status: ExecutionStatus = ExecutionStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_phase: str | None = None
    progress_percent: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for MCP response."""
        return {
            "execution_id": self.execution_id,
            "platform": self.platform,
            "benchmark": self.benchmark,
            "scale_factor": self.scale_factor,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_phase": self.current_phase,
            "progress_percent": round(self.progress_percent, 1),
            "error": self.error,
            "error_code": self.error_code,
        }


class ExecutionTracker:
    """Tracks active and recent benchmark executions.

    Thread-safe tracker that maintains state for:
    - Active (running) executions
    - Recently completed executions (for status queries)

    Uses LRU-style eviction to bound memory usage.
    """

    def __init__(self, max_completed: int = 100):
        """Initialize the tracker.

        Args:
            max_completed: Maximum completed executions to retain
        """
        self._lock = Lock()
        self._executions: dict[str, ExecutionState] = {}
        self._max_completed = max_completed
        self._completion_order: list[str] = []  # For LRU eviction

    def create_execution(
        self,
        platform: str,
        benchmark: str,
        scale_factor: float,
    ) -> ExecutionState:
        """Create a new execution entry.

        Args:
            platform: Target platform
            benchmark: Benchmark name
            scale_factor: Data scale factor

        Returns:
            New ExecutionState instance
        """
        execution_id = f"mcp_{uuid.uuid4().hex[:12]}"

        state = ExecutionState(
            execution_id=execution_id,
            platform=platform,
            benchmark=benchmark,
            scale_factor=scale_factor,
        )

        with self._lock:
            self._executions[execution_id] = state
            self._cleanup_completed()

        logger.info(f"Created execution {execution_id} for {benchmark} on {platform}")
        return state

    def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Get execution state by ID.

        Args:
            execution_id: Execution ID

        Returns:
            ExecutionState if found, None otherwise
        """
        with self._lock:
            return self._executions.get(execution_id)

    def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
        current_phase: str | None = None,
        progress_percent: float | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        """Update execution status.

        Args:
            execution_id: Execution ID
            status: New status
            current_phase: Current phase name (optional)
            progress_percent: Progress percentage (optional)
            error: Error message if failed (optional)
            error_code: Error code if failed (optional)

        Returns:
            True if execution exists and was updated
        """
        with self._lock:
            state = self._executions.get(execution_id)
            if state is None:
                return False

            # Update timestamps
            if status == ExecutionStatus.RUNNING and state.started_at is None:
                state.started_at = datetime.now(timezone.utc)
            elif status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                state.completed_at = datetime.now(timezone.utc)
                self._completion_order.append(execution_id)

            # Update state
            state.status = status
            if current_phase is not None:
                state.current_phase = current_phase
            if progress_percent is not None:
                state.progress_percent = progress_percent
            if error is not None:
                state.error = error
            if error_code is not None:
                state.error_code = error_code

            return True

    def set_result(self, execution_id: str, result: dict[str, Any]) -> bool:
        """Set the result for a completed execution.

        Args:
            execution_id: Execution ID
            result: Result data

        Returns:
            True if execution exists and was updated
        """
        with self._lock:
            state = self._executions.get(execution_id)
            if state is None:
                return False
            state.result = result
            return True

    def list_executions(
        self,
        status_filter: ExecutionStatus | None = None,
        limit: int = 20,
    ) -> list[ExecutionState]:
        """List executions, optionally filtered by status.

        Args:
            status_filter: Filter by status (optional)
            limit: Maximum results to return

        Returns:
            List of ExecutionState instances, most recent first
        """
        with self._lock:
            states = list(self._executions.values())

            if status_filter:
                states = [s for s in states if s.status == status_filter]

            # Sort by created_at descending
            states.sort(key=lambda s: s.created_at, reverse=True)

            return states[:limit]

    def cancel_execution(self, execution_id: str) -> bool:
        """Request cancellation of an execution.

        Args:
            execution_id: Execution ID

        Returns:
            True if execution exists and can be cancelled
        """
        with self._lock:
            state = self._executions.get(execution_id)
            if state is None:
                return False

            # Can only cancel queued or running executions
            if state.status not in (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING):
                return False

            state.status = ExecutionStatus.CANCELLED
            state.completed_at = datetime.now(timezone.utc)
            self._completion_order.append(execution_id)

            logger.info(f"Cancelled execution {execution_id}")
            return True

    def _cleanup_completed(self) -> None:
        """Remove old completed executions to bound memory."""
        # Count completed executions
        completed_count = sum(
            1
            for s in self._executions.values()
            if s.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED)
        )

        # Remove oldest completed if over limit
        while completed_count > self._max_completed and self._completion_order:
            old_id = self._completion_order.pop(0)
            if old_id in self._executions:
                state = self._executions[old_id]
                if state.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                    del self._executions[old_id]
                    completed_count -= 1


# Global tracker instance
_execution_tracker: ExecutionTracker | None = None


def get_execution_tracker() -> ExecutionTracker:
    """Get the global execution tracker instance."""
    global _execution_tracker
    if _execution_tracker is None:
        _execution_tracker = ExecutionTracker()
    return _execution_tracker


def _get_platform_adapter(platform: str, **config):
    """Get platform adapter from public API.

    Uses benchbox.platforms factory functions.
    """
    from benchbox.platforms import get_dataframe_adapter, get_platform_adapter, is_dataframe_platform

    platform_lower = platform.lower()

    if is_dataframe_platform(platform_lower):
        return get_dataframe_adapter(platform_lower, **config)
    else:
        return get_platform_adapter(platform_lower, **config)


async def run_benchmark_async(
    state: ExecutionState,
    tracker: ExecutionTracker,
    queries: str | None = None,
    phases: str | None = None,
) -> None:
    """Run a benchmark asynchronously.

    This is the async entry point that wraps the synchronous benchmark
    execution for use with asyncio.

    Uses the public BenchBox API (benchbox.*, benchbox.platforms.*) for
    all benchmark operations.

    Args:
        state: Execution state to update
        tracker: Tracker for status updates
        queries: Optional query subset
        phases: Optional phase list
    """
    execution_id = state.execution_id

    try:
        # Mark as running
        tracker.update_status(
            execution_id,
            ExecutionStatus.RUNNING,
            current_phase="initializing",
            progress_percent=5.0,
        )

        # Get benchmark class using public API
        benchmark_lower = state.benchmark.lower()
        benchmark_class = get_public_benchmark_class(benchmark_lower)

        if benchmark_class is None:
            tracker.update_status(
                execution_id,
                ExecutionStatus.FAILED,
                error=f"Unknown or unavailable benchmark: {state.benchmark}",
                error_code="VALIDATION_UNKNOWN_BENCHMARK",
            )
            return

        # Create benchmark instance using public API
        benchmark_instance = benchmark_class(scale_factor=state.scale_factor)

        # Get platform adapter using public API
        try:
            adapter = _get_platform_adapter(state.platform)
        except (ValueError, ImportError) as e:
            tracker.update_status(
                execution_id,
                ExecutionStatus.FAILED,
                error=f"Platform error: {e}",
                error_code="VALIDATION_UNSUPPORTED_PLATFORM",
            )
            return

        # Parse query subset if provided
        query_subset = None
        if queries:
            query_subset = [q.strip() for q in queries.split(",")]

        # Update progress
        tracker.update_status(
            execution_id,
            ExecutionStatus.RUNNING,
            current_phase="loading",
            progress_percent=20.0,
        )

        # Run in executor to not block event loop
        # Uses the public API: run_with_platform()
        loop = asyncio.get_running_loop()

        result = await loop.run_in_executor(
            None,
            lambda: benchmark_instance.run_with_platform(
                adapter,
                query_subset=query_subset,
            ),
        )

        # Process result
        if result:
            response = {
                "execution_id": execution_id,
                "status": "completed",
                "platform": state.platform,
                "benchmark": state.benchmark,
                "scale_factor": state.scale_factor,
            }

            # Extract summary metrics from BenchmarkResults
            response["summary"] = {
                "total_queries": getattr(result, "total_queries", 0),
                "successful_queries": getattr(result, "successful_queries", 0),
                "failed_queries": getattr(result, "failed_queries", 0),
                "total_execution_time": getattr(result, "total_execution_time", 0),
            }

            tracker.set_result(execution_id, response)
            tracker.update_status(
                execution_id,
                ExecutionStatus.COMPLETED,
                current_phase="completed",
                progress_percent=100.0,
            )
        else:
            tracker.update_status(
                execution_id,
                ExecutionStatus.COMPLETED,
                current_phase="completed",
                progress_percent=100.0,
            )

    except Exception as e:
        logger.exception(f"Async benchmark execution failed: {e}")
        tracker.update_status(
            execution_id,
            ExecutionStatus.FAILED,
            error=str(e),
            error_code=type(e).__name__,
        )
