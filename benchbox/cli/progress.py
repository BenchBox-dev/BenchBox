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
    def __init__(
        self,
        console: Console,
        enable_monitoring: bool = True,
    ):
        self.console = console
        self.enable_monitoring = enable_monitoring

        self.monitor: PerformanceMonitor | None = None
        if enable_monitoring and _MONITORING_AVAILABLE:
            self.monitor = PerformanceMonitor()  # type: ignore[misc]

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
        if self._is_started:
            return

        self._live = Live(
            self.progress,
            console=self.console,
            refresh_per_second=4,
        )

        self._live.start()
        self._is_started = True

    def stop(self) -> None:
        if not self._is_started:
            return

        if self._live is not None:
            self._live.stop()
            self._live = None

        self._is_started = False

    def __enter__(self) -> BenchmarkProgress:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def add_task(
        self,
        description: str,
        total: float | None = None,
        **kwargs: Any,
    ) -> TaskID:
        return self.progress.add_task(description, total=total, **kwargs)

    def update(self, task_id: TaskID, **kwargs: Any) -> None:
        self.progress.update(task_id, **kwargs)

    def get_monitor(self) -> PerformanceMonitor | None:
        return self.monitor


@contextmanager
def phase_progress(
    progress: BenchmarkProgress | None,
    phase_name: str,
    total: int | None = None,
):
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
    return sys.stdout.isatty()
