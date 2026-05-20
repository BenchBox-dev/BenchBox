"""ClickHouse platform package."""

from importlib import import_module
from typing import Any

from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

_LAZY_EXPORTS = {
    "ClickHouseAdapter": ".adapter",
    "ClickHouseLocalClient": ".client",
    "ClickHouseDiagnosticsMixin": ".diagnostics",
    "ClickHouseMetadataMixin": ".metadata",
    "ClickHouseSetupMixin": ".setup",
    "ClickHouseTuningMixin": ".tuning",
    "ClickHouseWorkloadMixin": ".workload",
}


def __getattr__(name: str) -> Any:
    """Load ClickHouse implementation classes on first access."""

    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_path, __package__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "ClickHouseAdapter",
    "ClickHouseLocalClient",
    "ClickHouseDiagnosticsMixin",
    "ClickHouseMetadataMixin",
    "ClickHouseSetupMixin",
    "ClickHouseTuningMixin",
    "ClickHouseWorkloadMixin",
    "check_platform_dependencies",
    "get_dependency_error_message",
]
