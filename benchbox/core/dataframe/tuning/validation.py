"""DataFrame tuning validation.

This module provides validation functions for DataFrame tuning configurations,
including platform compatibility checking and configuration-specific validations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration


class ValidationLevel(Enum):
    """Severity level for validation issues."""

    ERROR = "error"  # Configuration is invalid, will cause failures
    WARNING = "warning"  # Configuration may cause unexpected behavior
    INFO = "info"  # Informational, may affect performance


@dataclass
class ValidationIssue:
    """Represents a validation issue found in a configuration.

    Attributes:
        level: Severity of the issue
        message: Description of the issue
        setting: The setting that caused the issue (if applicable)
        suggestion: Recommended action to fix the issue
    """

    level: ValidationLevel
    message: str
    setting: str | None = None
    suggestion: str | None = None

    def __str__(self) -> str:
        """Return string representation of the issue."""
        prefix = f"[{self.level.value.upper()}]"
        if self.setting:
            prefix = f"{prefix} {self.setting}:"
        result = f"{prefix} {self.message}"
        if self.suggestion:
            result = f"{result} ({self.suggestion})"
        return result


class TuningValidationError(Exception):
    """Raised when tuning validation fails with ERROR level issues."""

    def __init__(self, message: str, issues: list[ValidationIssue] | None = None):
        super().__init__(message)
        self.issues = issues or []


def validate_dataframe_tuning(
    config: DataFrameTuningConfiguration,
    platform: str,
) -> list[ValidationIssue]:
    """Validate a DataFrame tuning configuration for a platform.

    This function performs comprehensive validation including:
    - Platform compatibility checking for all enabled settings
    - Value range validation
    - Platform-specific semantic validation

    Args:
        config: The configuration to validate
        platform: The target DataFrame platform

    Returns:
        List of ValidationIssue objects (empty if valid)
    """
    issues: list[ValidationIssue] = []

    # Normalize platform name
    platform_lower = platform.lower()
    if platform_lower.endswith("-df"):
        platform_lower = platform_lower[:-3]

    # Check platform compatibility for all enabled settings
    enabled = config.get_enabled_settings()
    for setting in enabled:
        if not setting.is_compatible_with_platform(platform_lower):
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message=f"Setting not supported on {platform_lower}",
                    setting=setting.value,
                    suggestion=f"This setting will be ignored on {platform_lower}",
                )
            )

    # Platform-specific validations
    if platform_lower == "polars":
        issues.extend(_validate_polars(config))
    elif platform_lower == "pandas":
        issues.extend(_validate_pandas(config))
    elif platform_lower == "dask":
        issues.extend(_validate_dask(config))
    elif platform_lower == "cudf":
        issues.extend(_validate_cudf(config))

    return issues


def _validate_polars(config: DataFrameTuningConfiguration) -> list[ValidationIssue]:
    """Validate Polars-specific configuration."""
    issues: list[ValidationIssue] = []

    # Warn if streaming_mode=True but chunk_size not set
    if config.execution.streaming_mode and config.memory.chunk_size is None:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="Streaming mode enabled without explicit chunk_size",
                setting="streaming_mode",
                suggestion="Consider setting chunk_size for large string columns to avoid OOM",
            )
        )

    # Validate engine_affinity values
    valid_engines = {"streaming", "in-memory", None}
    if config.execution.engine_affinity is not None and config.execution.engine_affinity not in valid_engines:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=f"Invalid engine_affinity value: '{config.execution.engine_affinity}'",
                setting="engine_affinity",
                suggestion="Use 'streaming' or 'in-memory'",
            )
        )

    # Warn about conflicting streaming settings
    if config.execution.streaming_mode and config.execution.engine_affinity == "in-memory":
        issues.append(
            ValidationIssue(
                level=ValidationLevel.WARNING,
                message="streaming_mode=True conflicts with engine_affinity='in-memory'",
                setting="streaming_mode",
                suggestion="Set engine_affinity='streaming' or disable streaming_mode",
            )
        )

    return issues


def _validate_pandas(config: DataFrameTuningConfiguration) -> list[ValidationIssue]:
    """Validate Pandas-specific configuration."""
    issues: list[ValidationIssue] = []

    # Warn about auto_categorize with pyarrow backend
    if config.data_types.auto_categorize_strings and config.data_types.dtype_backend == "pyarrow":
        issues.append(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="auto_categorize_strings with pyarrow backend may have limited effect",
                setting="auto_categorize_strings",
                suggestion="PyArrow has its own dictionary encoding for strings",
            )
        )

    # Warn about categorical_threshold at extremes
    if config.data_types.auto_categorize_strings:
        if config.data_types.categorical_threshold < 0.1:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message="Very low categorical_threshold may convert many columns",
                    setting="categorical_threshold",
                    suggestion="Consider a threshold of 0.3-0.5 for most workloads",
                )
            )
        elif config.data_types.categorical_threshold > 0.9:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message="Very high categorical_threshold may not convert any columns",
                    setting="categorical_threshold",
                    suggestion="Consider a threshold of 0.3-0.5 for most workloads",
                )
            )

    return issues


def _validate_dask(config: DataFrameTuningConfiguration) -> list[ValidationIssue]:
    """Validate Dask-specific configuration."""
    issues: list[ValidationIssue] = []

    # Validate memory_limit format is already done in dataclass
    # Add semantic validations

    # Warn about high thread count per worker
    if config.parallelism.threads_per_worker is not None and config.parallelism.threads_per_worker > 8:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.WARNING,
                message="High threads_per_worker may cause memory contention",
                setting="threads_per_worker",
                suggestion="Consider 1-4 threads per worker for memory-intensive workloads",
            )
        )

    # Warn if spill_to_disk without memory_limit
    if config.memory.spill_to_disk and config.memory.memory_limit is None:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="spill_to_disk enabled without explicit memory_limit",
                setting="spill_to_disk",
                suggestion="Set memory_limit to control when spilling occurs",
            )
        )

    # Warn about very low worker count
    if config.parallelism.worker_count is not None and config.parallelism.worker_count < 2:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="Single worker may limit parallelism",
                setting="worker_count",
                suggestion="Consider at least 2 workers for parallel execution",
            )
        )

    return issues


def _validate_cudf(config: DataFrameTuningConfiguration) -> list[ValidationIssue]:
    """Validate cuDF-specific configuration."""
    issues: list[ValidationIssue] = []

    # GPU must be enabled for cuDF
    if not config.gpu.enabled:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.WARNING,
                message="GPU is disabled but cuDF requires GPU",
                setting="gpu.enabled",
                suggestion="Set gpu.enabled=True for cuDF platform",
            )
        )

    # Validate pool_type
    valid_pools = {"default", "managed", "pool", "cuda"}
    if config.gpu.pool_type not in valid_pools:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=f"Invalid GPU pool_type: '{config.gpu.pool_type}'",
                setting="gpu.pool_type",
                suggestion=f"Use one of: {', '.join(valid_pools)}",
            )
        )

    # Warn about disabling spill_to_host
    if not config.gpu.spill_to_host:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="GPU spill_to_host disabled, may cause OOM for large datasets",
                setting="gpu.spill_to_host",
                suggestion="Enable spill_to_host for datasets larger than GPU memory",
            )
        )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    """Check if any validation issues are errors.

    Args:
        issues: List of validation issues

    Returns:
        True if any issue has ERROR level
    """
    return any(issue.level == ValidationLevel.ERROR for issue in issues)


def has_warnings(issues: list[ValidationIssue]) -> bool:
    """Check if any validation issues are warnings.

    Args:
        issues: List of validation issues

    Returns:
        True if any issue has WARNING level
    """
    return any(issue.level == ValidationLevel.WARNING for issue in issues)


def format_issues(issues: list[ValidationIssue], include_info: bool = True) -> str:
    """Format validation issues as a human-readable string.

    Args:
        issues: List of validation issues
        include_info: Whether to include INFO level issues

    Returns:
        Formatted string with all issues
    """
    if not issues:
        return "No validation issues found."

    filtered = issues if include_info else [i for i in issues if i.level != ValidationLevel.INFO]

    if not filtered:
        return "No validation issues found."

    lines = []
    for issue in filtered:
        lines.append(str(issue))

    return "\n".join(lines)
