"""CLI progress tracking display.

This module provides rich progress bars for benchmark execution phases.
Progress tracking is opt-in and gracefully degrades to simple text output
in non-TTY environments.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

try:
    from benchbox.monitoring import PerformanceMonitor

    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False
    PerformanceMonitor = None  # type: ignore[assignment,misc]


class BenchmarkProgress:
    """Manages rich progress bars for benchmark lifecycle.

    Provides:
    - Phase-based progress tracking (data generation, loading, query execution)
    - Integration with PerformanceMonitor for metrics collection
    - Graceful fallback to text mode in non-TTY environments

    Example:
        >>> progress = BenchmarkProgress(console)
        >>> with progress:
        ...     task_id = progress.add_task("Generating data", total=8)
        ...     for i in range(8):
        ...         progress.update(task_id, advance=1)
        ...     monitor = progress.get_monitor()
    """

    def __init__(
        self,
        console: Console,
        enable_monitoring: bool = True,
    ):
        """Initialize progress tracker.

        Args:
            console: Rich console for output
            enable_monitoring: Whether to create PerformanceMonitor (default: True)
        """
        self.console = console
        self.enable_monitoring = enable_monitoring

        # Create monitor if enabled
        self.monitor: PerformanceMonitor | None = None
        if enable_monitoring and _MONITORING_AVAILABLE:
            self.monitor = PerformanceMonitor()  # type: ignore[misc]

        # Create progress bar
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        self._live: Live | None = None
        self._is_started = False

    def start(self) -> None:
        """Start progress display."""
        if self._is_started:
            return

        # Start live display with progress bar
        self._live = Live(
            self.progress,
            console=self.console,
            refresh_per_second=4,
        )

        self._live.start()
        self._is_started = True

    def stop(self) -> None:
        """Stop progress display."""
        if not self._is_started:
            return

        if self._live is not None:
            self._live.stop()
            self._live = None

        self._is_started = False

    def __enter__(self) -> BenchmarkProgress:
        """Context manager entry - start progress display."""
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - stop progress display."""
        self.stop()

    def add_task(
        self,
        description: str,
        total: float | None = None,
        **kwargs: Any,
    ) -> TaskID:
        """Add a new progress task.

        Args:
            description: Task description shown in progress bar
            total: Total units for this task (None for indeterminate)
            **kwargs: Additional arguments passed to Progress.add_task()

        Returns:
            TaskID for updating progress
        """
        return self.progress.add_task(description, total=total, **kwargs)

    def update(self, task_id: TaskID, **kwargs: Any) -> None:
        """Update progress for a task.

        Args:
            task_id: Task ID returned from add_task()
            **kwargs: Update arguments (advance, completed, description, etc.)
        """
        self.progress.update(task_id, **kwargs)

    def get_monitor(self) -> PerformanceMonitor | None:
        """Get the PerformanceMonitor instance for metrics collection.

        Returns:
            PerformanceMonitor if monitoring enabled, None otherwise
        """
        return self.monitor


@contextmanager
def phase_progress(
    progress: BenchmarkProgress | None,
    phase_name: str,
    total: int | None = None,
):
    """Context manager for tracking a benchmark phase with progress.

    Args:
        progress: BenchmarkProgress instance (can be None for no-op)
        phase_name: Name of the phase (e.g., "Generating data")
        total: Total units for progress tracking (None for indeterminate)

    Yields:
        TaskID for updating progress (or None if progress disabled)

    Example:
        >>> with phase_progress(progress, "Generating data", total=8) as task_id:
        ...     for i in range(8):
        ...         # Do work
        ...         if task_id is not None:
        ...             progress.update(task_id, advance=1)
    """
    if progress is None:
        yield None
        return

    task_id = progress.add_task(phase_name, total=total)
    try:
        yield task_id
    finally:
        if task_id is not None:
            progress.update(task_id, completed=total if total is not None else None)


def should_show_progress() -> bool:
    """Determine if progress bars should be shown.

    Returns:
        True if stdout is a TTY and progress should be displayed
    """
    return sys.stdout.isatty()
