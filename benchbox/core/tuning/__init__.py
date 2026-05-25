"""Core tuning interface classes for BenchBox.

This module provides the core tuning interface classes that define how database
table tunings are configured, validated, and applied across different platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from .ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    ColumnNullability,
    DDLGenerator,
    NoOpDDLGenerator,
    TuningClauses,
)
from .interface import (
    BenchmarkTunings,
    ClusteringConfig,
    PartitioningConfig,
    SortKeyConfig,
    TableTuning,
    TuningColumn,
    TuningType,
)
from .metadata import (
    MetadataValidationResult,
    TuningMetadata,
    TuningMetadataManager,
)

__all__ = [
    # DDL Generator Protocol
    "DDLGenerator",
    "BaseDDLGenerator",
    "NoOpDDLGenerator",
    "TuningClauses",
    "ColumnDefinition",
    "ColumnNullability",
    # Tuning Interface
    "TuningType",
    "TuningColumn",
    "TableTuning",
    "BenchmarkTunings",
    # Advanced Tuning Configuration
    "PartitioningConfig",
    "SortKeyConfig",
    "ClusteringConfig",
    # Metadata
    "TuningMetadata",
    "TuningMetadataManager",
    "MetadataValidationResult",
]
