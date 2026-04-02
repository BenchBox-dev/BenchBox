"""Monitoring utilities exposed for public consumption.

This package intentionally lazy-loads reporting helpers so callers that only
need core monitoring primitives do not import charting dependencies such as
``textcharts`` during unrelated CLI startup.
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "PerformanceHistory": "performance",
    "PerformanceMonitor": "performance",
    "PerformanceRegressionAlert": "performance",
    "PerformanceSnapshot": "performance",
    "PerformanceTracker": "performance",
    "ResourceMonitor": "performance",
    "TimingStats": "performance",
    "attach_snapshot_to_result": "performance",
    "EnhancedResourceProfiler": "profiler",
    "ResourceSample": "profiler",
    "ResourceTimeline": "profiler",
    "ResourceType": "profiler",
    "ResourceUtilization": "profiler",
    "calculate_utilization": "profiler",
    "BottleneckAnalysis": "bottleneck",
    "BottleneckDetector": "bottleneck",
    "BottleneckIndicator": "bottleneck",
    "BottleneckSeverity": "bottleneck",
    "BottleneckType": "bottleneck",
    "quick_bottleneck_check": "bottleneck",
    "ResourceChart": "report",
    "ResourceReport": "report",
    "ResourceReporter": "report",
    "format_bytes": "report",
    "format_duration": "report",
    "generate_ascii_chart": "report",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily expose monitoring helpers and sibling submodules."""
    module_name = _EXPORTS.get(name)
    if module_name is not None:
        module = importlib.import_module(f"{__name__}.{module_name}")
        value = getattr(module, name)
        globals()[name] = value
        return value

    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    globals()[name] = module
    return module


def __dir__() -> list[str]:
    """Return stable introspection output for lazy exports."""
    return sorted(set(globals()) | set(__all__))
