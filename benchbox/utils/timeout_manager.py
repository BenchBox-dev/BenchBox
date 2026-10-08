# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TimeoutError(Exception):
    def __init__(self, message: str, timeout_seconds: float, operation: str = ""):
        self.timeout_seconds = timeout_seconds
        self.operation = operation
        super().__init__(message)


@dataclass
class TimeoutConfig:
    timeout_seconds: float
    operation_name: str = "operation"
    raise_on_timeout: bool = True
    on_timeout: Callable[[], None] | None = None

    def __post_init__(self):
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class TimeoutManager:
    def __init__(self, default_timeout_seconds: float = 300):
        self.default_timeout_seconds = default_timeout_seconds
        self._active_timers: dict[int, threading.Timer] = {}
        self._lock = threading.Lock()

    @contextmanager
    def timeout_context(
        self,
        timeout_seconds: float | None = None,
        operation_name: str = "operation",
        raise_on_timeout: bool = True,
    ):
        timeout = timeout_seconds or self.default_timeout_seconds
        context = _TimeoutContext(timeout, operation_name)

        timer = threading.Timer(timeout, context._trigger_timeout)
        timer.daemon = True

        timer_id = id(context)
        with self._lock:
            self._active_timers[timer_id] = timer

        timer.start()

        try:
            yield context
        finally:
            timer.cancel()
            with self._lock:
                self._active_timers.pop(timer_id, None)

            if context.timed_out and raise_on_timeout:
                raise TimeoutError(
                    f"{operation_name} timed out after {timeout:.1f} seconds",
                    timeout_seconds=timeout,
                    operation=operation_name,
                )

    def cancel_all_timers(self):
        with self._lock:
            for timer in self._active_timers.values():
                timer.cancel()
            self._active_timers.clear()


class _TimeoutContext:
    def __init__(self, timeout_seconds: float, operation_name: str):
        self.timeout_seconds = timeout_seconds
        self.operation_name = operation_name
        self.timed_out = False
        self._triggered_at: float | None = None

    def _trigger_timeout(self):
        import time

        self.timed_out = True
        self._triggered_at = time.time()
        logger.warning(f"Timeout triggered for {self.operation_name} after {self.timeout_seconds:.1f}s")

    @property
    def triggered_at(self) -> float | None:
        return self._triggered_at


def run_with_timeout(
    func: Callable[..., T],
    timeout_seconds: float,
    operation_name: str = "operation",
    *args: Any,
    **kwargs: Any,
) -> tuple[T | None, bool]:
    result_container: dict[str, Any] = {"result": None, "exception": None}

    def wrapper():
        try:
            result_container["result"] = func(*args, **kwargs)
        except Exception as e:
            result_container["exception"] = e

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        logger.warning(f"{operation_name} timed out after {timeout_seconds:.1f}s (thread still running)")
        return None, True

    if result_container["exception"] is not None:
        raise result_container["exception"]

    return result_container["result"], False


_default_manager: TimeoutManager | None = None


def get_timeout_manager() -> TimeoutManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = TimeoutManager()
    return _default_manager


@contextmanager
def timeout(timeout_seconds: float, operation_name: str = "operation", raise_on_timeout: bool = True):
    manager = get_timeout_manager()
    with manager.timeout_context(timeout_seconds, operation_name, raise_on_timeout) as ctx:
        yield ctx
