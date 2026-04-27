"""Centralized, quiet-aware output helpers for BenchBox runtime surfaces.

Policy:
- All runtime user-facing output must flow through this module.
- `quiet` mode (--quiet / -q) suppresses all normal user output.
- MCP/tooling callers can force sink behavior via `get_quiet_console()` or
  `silence_output(...)` to guard transitive stdout/stderr writes.

Approved output patterns (in preference order):
1. `emit(msg)` - primary interface for all user-facing text and Rich renderables.
   Accepts any Rich-renderable (str, Panel, Table, Text, …) and respects quiet mode.
   Use this everywhere unless one of the exceptions below applies.

2. `console.print(...)` via module-level alias `console = quiet_console` - approved
   for CLI command modules that need Rich keyword arguments (style=, justify=, end=,
   markup=, highlight=) not exposed by emit(). The alias ensures quiet-mode fidelity
   through QuietConsoleProxy.

3. `self.console.print(...)` via constructor injection - approved for display/handler
   classes that need to be testable in isolation (e.g. ExceptionHandler, DryRunDisplay,
   BenchmarkOrchestrator). The injected console must default to `quiet_console`.

Raw `print()`, `sys.stdout.write()`, and `logging.*` must NOT be used for
user-facing messages; they bypass quiet mode and the centralized output channel.
"""

from __future__ import annotations

import contextlib
import io
import sys
from collections.abc import Iterator
from typing import Any, cast

from rich.console import Console

_QUIET: bool = False
_STD_CONSOLE: Console | None = None
_SINK_CONSOLE: Console | None = None


def set_quiet(enabled: bool) -> None:
    """Globally enable/disable quiet mode for CLI output helpers."""
    global _QUIET
    _QUIET = bool(enabled)


def is_quiet() -> bool:
    """Return True if quiet mode is enabled."""
    return _QUIET


def get_console(quiet: bool | None = None) -> Console:
    """Return a Console that respects quiet mode.

    When quiet is True (or global quiet is enabled), a sink console that
    writes to an in-memory stream is returned so output is discarded.
    """
    q = _QUIET if quiet is None else bool(quiet)
    if not q:
        global _STD_CONSOLE
        if _STD_CONSOLE is None:
            _STD_CONSOLE = Console()
        return cast(Console, _STD_CONSOLE)

    global _SINK_CONSOLE
    if _SINK_CONSOLE is None:
        _SINK_CONSOLE = Console(file=io.StringIO(), stderr=True, force_jupyter=False)
    return cast(Console, _SINK_CONSOLE)


@contextlib.contextmanager
def silence_output(enabled: bool = True) -> Iterator[None]:
    """Context manager to silence stdout and stderr when enabled.

    This suppresses any direct print() calls and third-party console output.
    """
    if not enabled:
        # No-op
        yield
        return

    stdout_backup, stderr_backup = sys.stdout, sys.stderr
    try:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        yield
    finally:
        sys.stdout = stdout_backup
        sys.stderr = stderr_backup


def info(msg: str) -> None:
    emit(msg)


def emit(msg: Any = "", *, quiet: bool | None = None) -> None:
    """Emit user-facing output through the centralized console channel.

    This is the primary interface for all user-facing output. It accepts any
    value that Rich's Console.print() accepts, including plain strings, f-strings,
    Rich renderables (Panel, Table, Text, Rule, …), and markup strings.

    Args:
        msg: Message or Rich renderable to print. Defaults to a blank line.
        quiet: Per-call quiet override. If True, suppresses this call regardless
            of the global quiet flag. If False, forces output even in quiet mode.
            If None (default), defers to the global quiet policy set by set_quiet().
    """
    q = _QUIET if quiet is None else bool(quiet)
    if q:
        return
    get_console(quiet=False).print(msg)


class QuietConsoleProxy:
    """Proxy that always forwards to the current quiet-aware Console.

    This class acts as a transparent proxy to a Console object that respects
    quiet mode. It's compatible with Console for type checking purposes.
    """

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - simple delegation
        return getattr(get_console(), item)

    def __enter__(self) -> Console:  # pragma: no cover - context manager support
        """Support context manager protocol by delegating to Console."""
        return get_console().__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:  # pragma: no cover - context manager support
        """Support context manager protocol by delegating to Console."""
        return get_console().__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        mode = "quiet" if is_quiet() else "verbose"
        return f"<QuietConsoleProxy mode={mode}>"


quiet_console = QuietConsoleProxy()


def warn(msg: str) -> None:
    emit(msg)


def error(msg: str) -> None:
    emit(msg)


def debug(msg: str) -> None:
    emit(msg)


def get_quiet_console() -> Console:
    """Return a sink console regardless of the global quiet flag."""
    return get_console(quiet=True)
