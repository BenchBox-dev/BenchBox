"""Base platform adapter package."""

from __future__ import annotations

from .adapter import (
    BenchmarkResults,
    DriverIsolationCapability,
    EnhancedBenchmarkResults,
    ExecutionPhases,
    PlatformAdapter,
    PlatformAdapterConnection,
    PlatformAdapterCursor,
    QueryDefinition,
    check_isolation_capability,
)
from .models import (
    ConnectionConfig,
    DatabaseValidationResult,
    DataGenerationPhase,
    MaintenanceOperation,
    MaintenanceTestPhase,
    PowerTestPhase,
    QueryExecution,
    SchemaCreationPhase,
    SetupPhase,
    StatisticsGatheringPhase,
    TableCreationStats,
    TableGenerationStats,
    TableLoadingStats,
    ThroughputStream,
    ThroughputTestPhase,
    ValidationPhase,
)
from .psycopg2_mixin import PsycopgConnectionMixin
from .utils import FileFormatInfo, detect_file_format, is_non_interactive

__all__ = [
    "ConnectionConfig",
    "DatabaseValidationResult",
    "DataGenerationPhase",
    "BenchmarkResults",
    "DriverIsolationCapability",
    "EnhancedBenchmarkResults",
    "check_isolation_capability",
    "ExecutionPhases",
    "FileFormatInfo",
    "MaintenanceOperation",
    "MaintenanceTestPhase",
    "PlatformAdapter",
    "PlatformAdapterConnection",
    "PlatformAdapterCursor",
    "PowerTestPhase",
    "QueryExecution",
    "SchemaCreationPhase",
    "SetupPhase",
    "StatisticsGatheringPhase",
    "TableCreationStats",
    "TableGenerationStats",
    "TableLoadingStats",
    "ThroughputStream",
    "ThroughputTestPhase",
    "ValidationPhase",
    "QueryDefinition",
    "detect_file_format",
    "is_non_interactive",
    "PsycopgConnectionMixin",
]
