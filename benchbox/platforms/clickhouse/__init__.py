from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

if TYPE_CHECKING:
    from .adapter import ClickHouseAdapter
    from .client import ClickHouseLocalClient
    from .diagnostics import ClickHouseDiagnosticsMixin
    from .metadata import ClickHouseMetadataMixin
    from .setup import ClickHouseSetupMixin
    from .tuning import ClickHouseTuningMixin
    from .workload import ClickHouseWorkloadMixin

_EXPORTS = {
    "ClickHouseAdapter": "adapter",
    "ClickHouseLocalClient": "client",
    "ClickHouseDiagnosticsMixin": "diagnostics",
    "ClickHouseMetadataMixin": "metadata",
    "ClickHouseSetupMixin": "setup",
    "ClickHouseTuningMixin": "tuning",
    "ClickHouseWorkloadMixin": "workload",
}

__all__ = [
    *_EXPORTS,
    "check_platform_dependencies",
    "get_dependency_error_message",
]


def __getattr__(name: str) -> Any:
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
    return sorted(set(globals()) | set(__all__))
