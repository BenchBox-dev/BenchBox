"""Core lifecycle runner package.

Keep package imports lightweight so sibling submodules such as
``benchbox.core.runner.conversion`` do not pull in the full lifecycle runner
and its transitive monitoring/reporting stack as an import side effect.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["run_benchmark_lifecycle", "LifecyclePhases", "ValidationOptions"]


def __getattr__(name: str) -> Any:
    """Lazily expose lifecycle APIs and sibling submodules."""
    if name in __all__:
        from .runner import LifecyclePhases, ValidationOptions, run_benchmark_lifecycle

        globals().update(
            {
                "LifecyclePhases": LifecyclePhases,
                "ValidationOptions": ValidationOptions,
                "run_benchmark_lifecycle": run_benchmark_lifecycle,
            }
        )
        return globals()[name]

    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    globals()[name] = module
    return module


def __dir__() -> list[str]:
    """Return stable introspection output for lazy exports."""
    return sorted(set(globals()) | set(__all__))
