"""ClickHouse platform package."""

from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

from .adapter import ClickHouseAdapter
from .client import ClickHouseLocalClient
from .diagnostics import ClickHouseDiagnosticsMixin
from .metadata import ClickHouseMetadataMixin
from .setup import ClickHouseSetupMixin
from .tuning import ClickHouseTuningMixin
from .workload import ClickHouseWorkloadMixin

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
