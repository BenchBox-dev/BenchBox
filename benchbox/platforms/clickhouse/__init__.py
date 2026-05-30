"""ClickHouse platform package.

Symbols are re-exported lazily (PEP 562) so importing a lightweight submodule
such as ``deployment_mode`` does not eagerly pull the heavy adapter/client/setup
modules. ``adapter_factory`` imports ``clickhouse.deployment_mode`` on the
``import benchbox`` path; eager re-exports here previously defeated the lazy
``ClickHouseAdapter`` loading in ``platforms/__init__.py`` and dragged optional
engine dependencies onto the base import surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

if TYPE_CHECKING:
    from .adapter import ClickHouseAdapter
    from .client import ClickHouseLocalClient
    from .diagnostics import ClickHouseDiagnosticsMixin
    from .metadata import ClickHouseMetadataMixin
    from .setup import ClickHouseSetupMixin
    from .tuning import ClickHouseTuningMixin
    from .workload import ClickHouseWorkloadMixin

# Lazy-loaded re-exports: attribute name -> submodule providing it.
_LAZY_EXPORTS = {
    "ClickHouseAdapter": ".adapter",
    "ClickHouseLocalClient": ".client",
    "ClickHouseDiagnosticsMixin": ".diagnostics",
    "ClickHouseMetadataMixin": ".metadata",
    "ClickHouseSetupMixin": ".setup",
    "ClickHouseTuningMixin": ".tuning",
    "ClickHouseWorkloadMixin": ".workload",
}

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


def __getattr__(name: str):
    """Load re-exported symbols on first access (PEP 562)."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
