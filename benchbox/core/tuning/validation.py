"""Tuning configuration validation system for BenchBox.

This module provides comprehensive validation for tuning configurations,
including column existence checks, type appropriateness validation,
and conflict detection between different tuning types.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml

from .interface import BenchmarkTunings, TableTuning, TuningType

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a validation issue found during tuning validation."""

    level: ValidationLevel
    message: str
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    tuning_type: Optional[TuningType] = None
    suggestion: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        parts = [f"[{self.level.value.upper()}]"]

        if self.table_name:
            parts.append(f"Table '{self.table_name}':")
        if self.column_name:
            parts.append(f"Column '{self.column_name}':")
        if self.tuning_type:
            parts.append(f"({self.tuning_type.value})")

        parts.append(self.message)

        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")

        return " ".join(parts)


@dataclass
class ValidationResult:
    """Results of tuning validation with detailed issues and summary."""

    is_valid: bool = True
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    info: list[ValidationIssue] = field(default_factory=list)

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add a validation issue to the appropriate list."""
        if issue.level == ValidationLevel.ERROR:
            self.errors.append(issue)
            self.is_valid = False
        elif issue.level == ValidationLevel.WARNING:
            self.warnings.append(issue)
        elif issue.level == ValidationLevel.INFO:
            self.info.append(issue)

    def has_errors(self) -> bool:
        """Check if there are any validation errors."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if there are any validation warnings."""
        return len(self.warnings) > 0

    def get_issue_count(self) -> dict[str, int]:
        """Get count of issues by level."""
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "info": len(self.info),
        }

    def get_all_issues(self) -> list[ValidationIssue]:
        """Get all issues sorted by severity."""
        return self.errors + self.warnings + self.info


def _load_validation_specs() -> dict[str, list[str]]:
    with (Path(__file__).with_name("validation_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_VALIDATION_SPECS = _load_validation_specs()

# SQL data type categorization for tuning appropriateness
TEMPORAL_TYPES = set(_VALIDATION_SPECS["temporal_types"])
NUMERIC_TYPES = set(_VALIDATION_SPECS["numeric_types"])
STRING_TYPES = set(_VALIDATION_SPECS["string_types"])
HIGH_CARDINALITY_INDICATORS = set(_VALIDATION_SPECS["high_cardinality_indicators"])
LOW_CARDINALITY_INDICATORS = set(_VALIDATION_SPECS["low_cardinality_indicators"])


def validate_columns_exist(
    table_tuning: TableTuning, table_schema: dict[str, str], case_sensitive: bool = True
) -> ValidationResult:
    """Validate that all tuning columns exist in the table schema.

    Args:
        table_tuning: The table tuning configuration to validate
        table_schema: Dictionary mapping column names to their data types
        case_sensitive: Whether to perform case-sensitive column matching

    Returns:
        ValidationResult with any column existence issues
    """
    result = ValidationResult()

    # Normalize schema column names for case-insensitive comparison if needed
    schema_columns = set(table_schema.keys())
    if not case_sensitive:
        schema_columns_lower = {col.lower(): col for col in schema_columns}

    # Check each tuning type for column existence
    for tuning_type in TuningType:
        columns = table_tuning.get_columns_by_type(tuning_type)
        if not columns:
            continue

        for column in columns:
            column_found = False
            actual_column_name = column.name

            if case_sensitive:
                if column.name in schema_columns:
                    column_found = True
            else:
                # Case-insensitive matching
                column_lower = column.name.lower()
                if column_lower in schema_columns_lower:
                    column_found = True
                    actual_column_name = schema_columns_lower[column_lower]

                    # Warn if case doesn't match exactly
                    if column.name != actual_column_name:
                        result.add_issue(
                            ValidationIssue(
                                level=ValidationLevel.WARNING,
                                message=f"Column name case mismatch: '{column.name}' vs '{actual_column_name}'",
                                table_name=table_tuning.table_name,
                                column_name=column.name,
                                tuning_type=tuning_type,
                                suggestion=f"Consider using exact case: '{actual_column_name}'",
                            )
                        )

            if not column_found:
                available_columns = sorted(schema_columns)
                result.add_issue(
                    ValidationIssue(
                        level=ValidationLevel.ERROR,
                        message=f"Column '{column.name}' does not exist in table schema",
                        table_name=table_tuning.table_name,
                        column_name=column.name,
                        tuning_type=tuning_type,
                        suggestion=f"Available columns: {', '.join(available_columns)}",
                        details={"available_columns": available_columns},
                    )
                )

    return result


def validate_column_types(
    table_tuning: TableTuning, table_schema: dict[str, str], strict_mode: bool = False
) -> ValidationResult:
    """Validate that column types are appropriate for their tuning usage.

    Args:
        table_tuning: The table tuning configuration to validate
        table_schema: Dictionary mapping column names to their data types
        strict_mode: Whether to treat warnings as errors

    Returns:
        ValidationResult with type appropriateness issues
    """
    result = ValidationResult()
    schema_lookup = {col.lower(): (col, dtype.upper()) for col, dtype in table_schema.items()}

    _validate_partitioning_types(result, table_tuning, schema_lookup, strict_mode)
    _validate_clustering_types(result, table_tuning, schema_lookup, strict_mode)
    _validate_distribution_types(result, table_tuning, schema_lookup)
    _validate_sorting_types(result, table_tuning, schema_lookup)

    return result


def _get_column_type(column_name: str, schema_lookup: dict[str, tuple[str, str]]) -> Optional[str]:
    """Get the normalized column type from schema."""
    entry = schema_lookup.get(column_name.lower())
    return entry[1] if entry else None


def _extract_base_type(sql_type: str) -> str:
    """Extract base type from SQL type (e.g., VARCHAR(255) -> VARCHAR)."""
    return sql_type.split("(")[0].strip().upper()


def _is_high_cardinality_column(column_name: str) -> bool:
    """Check if column appears to be high cardinality based on name."""
    col_lower = column_name.lower()
    return any(indicator in col_lower for indicator in HIGH_CARDINALITY_INDICATORS)


def _is_low_cardinality_column(column_name: str) -> bool:
    """Check if column appears to be low cardinality based on name."""
    col_lower = column_name.lower()
    return any(indicator in col_lower for indicator in LOW_CARDINALITY_INDICATORS)


def _validate_partitioning_types(
    result: ValidationResult,
    table_tuning: TableTuning,
    schema_lookup: dict[str, tuple[str, str]],
    strict_mode: bool,
) -> None:
    """Validate partitioning column type appropriateness."""
    for column in table_tuning.get_columns_by_type(TuningType.PARTITIONING):
        column_type = _get_column_type(column.name, schema_lookup)
        if not column_type:
            continue  # Column existence will be caught by validate_columns_exist

        base_type = _extract_base_type(column_type)

        if base_type in TEMPORAL_TYPES:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message=f"Good partitioning column choice: temporal type '{base_type}'",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.PARTITIONING,
                )
            )
        elif base_type in NUMERIC_TYPES:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message=f"Acceptable partitioning column: numeric type '{base_type}'",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.PARTITIONING,
                )
            )
        elif base_type in STRING_TYPES:
            level = ValidationLevel.ERROR if strict_mode else ValidationLevel.WARNING
            result.add_issue(
                ValidationIssue(
                    level=level,
                    message=f"Suboptimal partitioning column: string type '{base_type}'",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.PARTITIONING,
                    suggestion="Consider using date, timestamp, or numeric columns for partitioning",
                )
            )


def _validate_clustering_types(
    result: ValidationResult,
    table_tuning: TableTuning,
    schema_lookup: dict[str, tuple[str, str]],
    strict_mode: bool,
) -> None:
    """Validate clustering column type appropriateness."""
    for column in table_tuning.get_columns_by_type(TuningType.CLUSTERING):
        column_type = _get_column_type(column.name, schema_lookup)
        if not column_type:
            continue

        if _is_high_cardinality_column(column.name):
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message="Good clustering column: appears to be high cardinality",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.CLUSTERING,
                )
            )
        elif _is_low_cardinality_column(column.name):
            level = ValidationLevel.ERROR if strict_mode else ValidationLevel.WARNING
            result.add_issue(
                ValidationIssue(
                    level=level,
                    message="Suboptimal clustering column: appears to be low cardinality",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.CLUSTERING,
                    suggestion="Clustering works best with high-cardinality columns",
                )
            )


def _validate_distribution_types(
    result: ValidationResult,
    table_tuning: TableTuning,
    schema_lookup: dict[str, tuple[str, str]],
) -> None:
    """Validate distribution column type appropriateness."""
    for column in table_tuning.get_columns_by_type(TuningType.DISTRIBUTION):
        column_type = _get_column_type(column.name, schema_lookup)
        if not column_type:
            continue

        if _is_high_cardinality_column(column.name):
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message="Good distribution column: appears to be high cardinality",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.DISTRIBUTION,
                )
            )
        elif "key" in column.name.lower():
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message="Good distribution column: appears to be a key column",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.DISTRIBUTION,
                )
            )


def _validate_sorting_types(
    result: ValidationResult,
    table_tuning: TableTuning,
    schema_lookup: dict[str, tuple[str, str]],
) -> None:
    """Validate sorting column type appropriateness."""
    for column in table_tuning.get_columns_by_type(TuningType.SORTING):
        column_type = _get_column_type(column.name, schema_lookup)
        if not column_type:
            continue

        base_type = _extract_base_type(column_type)

        # Sorting is generally good for any frequently queried column
        if base_type in TEMPORAL_TYPES:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    message=f"Good sorting column: temporal type '{base_type}' often used in filters",
                    table_name=table_tuning.table_name,
                    column_name=column.name,
                    tuning_type=TuningType.SORTING,
                )
            )


def detect_tuning_conflicts(table_tuning: TableTuning, platform: Optional[str] = None) -> ValidationResult:
    """Detect conflicts between different tuning configurations.

    Args:
        table_tuning: The table tuning configuration to validate
        platform: The target database platform (affects conflict rules)

    Returns:
        ValidationResult with detected conflicts and resolution suggestions
    """
    result = ValidationResult()

    # Get all columns by tuning type
    tuning_columns = {}
    for tuning_type in TuningType:
        columns = table_tuning.get_columns_by_type(tuning_type)
        if columns:
            tuning_columns[tuning_type] = {col.name.lower(): col for col in columns}

    # Check for same column used in multiple tuning types
    all_column_usage = {}
    for tuning_type, columns in tuning_columns.items():
        for col_name_lower, column in columns.items():
            if col_name_lower not in all_column_usage:
                all_column_usage[col_name_lower] = []
            all_column_usage[col_name_lower].append((tuning_type, column))

    # Report conflicts for columns used in multiple tuning types
    for _col_name_lower, usages in all_column_usage.items():
        if len(usages) > 1:
            tuning_types = [usage[0] for usage in usages]
            column_name = usages[0][1].name  # Get original case

            # Some conflicts are more severe than others
            conflict_severity = _determine_conflict_severity(tuning_types, platform)

            result.add_issue(
                ValidationIssue(
                    level=conflict_severity,
                    message=f"Column used in multiple tuning types: {[t.value for t in tuning_types]}",
                    table_name=table_tuning.table_name,
                    column_name=column_name,
                    suggestion=_get_conflict_resolution_suggestion(tuning_types, platform),
                )
            )

    # Check for conflicting sort orders between clustering and sorting
    _check_sort_order_conflicts(table_tuning, result)

    # Platform-specific conflict checks
    if platform:
        _check_platform_specific_conflicts(table_tuning, platform, result)

    return result


def _determine_conflict_severity(tuning_types: list[TuningType], platform: Optional[str]) -> ValidationLevel:
    """Determine the severity of a tuning conflict."""
    # Some combinations are more problematic than others
    if TuningType.PARTITIONING in tuning_types and TuningType.CLUSTERING in tuning_types:
        if platform and platform.lower() in {"redshift", "clickhouse", "clickhouse-local", "clickhouse-server"}:
            return ValidationLevel.ERROR
        return ValidationLevel.WARNING

    if TuningType.DISTRIBUTION in tuning_types and TuningType.CLUSTERING in tuning_types:
        return ValidationLevel.WARNING

    # Most other conflicts are warnings
    return ValidationLevel.WARNING


def _get_conflict_resolution_suggestion(tuning_types: list[TuningType], platform: Optional[str]) -> str:
    """Generate a suggestion for resolving tuning conflicts."""
    if TuningType.PARTITIONING in tuning_types and TuningType.CLUSTERING in tuning_types:
        return "Consider using partitioning OR clustering, not both on the same column"

    if TuningType.DISTRIBUTION in tuning_types and TuningType.CLUSTERING in tuning_types:
        return "Distribution and clustering on same column may be redundant"

    if TuningType.SORTING in tuning_types:
        other_types = [t for t in tuning_types if t != TuningType.SORTING]
        if other_types:
            return f"Sorting with {other_types[0].value} may provide limited benefit"

    return "Consider using different columns for different tuning types"


def _check_sort_order_conflicts(table_tuning: TableTuning, result: ValidationResult) -> None:
    """Check for conflicting sort orders between clustering and sorting."""
    clustering_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
    sorting_columns = table_tuning.get_columns_by_type(TuningType.SORTING)

    if not clustering_columns or not sorting_columns:
        return

    # Build order maps
    clustering_order = {col.name.lower(): col.order for col in clustering_columns}
    sorting_order = {col.name.lower(): col.order for col in sorting_columns}

    # Check for conflicts in order specification
    common_columns = set(clustering_order.keys()) & set(sorting_order.keys())
    for col_name_lower in common_columns:
        if clustering_order[col_name_lower] != sorting_order[col_name_lower]:
            # Find the original column name
            original_name = next(
                col.name for col in clustering_columns + sorting_columns if col.name.lower() == col_name_lower
            )

            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message=(
                        f"Conflicting sort orders: clustering order "
                        f"{clustering_order[col_name_lower]} vs sorting order "
                        f"{sorting_order[col_name_lower]}"
                    ),
                    table_name=table_tuning.table_name,
                    column_name=original_name,
                    suggestion="Ensure consistent ordering across tuning types for the same column",
                )
            )


def _check_platform_specific_conflicts(table_tuning: TableTuning, platform: str, result: ValidationResult) -> None:
    """Check for platform-specific tuning conflicts."""
    platform_lower = platform.lower()

    # Snowflake-specific checks
    if platform_lower == "snowflake":
        partitioning_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partitioning_columns:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message="Snowflake uses automatic micro-partitioning; explicit partitioning may be unnecessary",
                    table_name=table_tuning.table_name,
                    tuning_type=TuningType.PARTITIONING,
                    suggestion="Consider using clustering instead of partitioning on Snowflake",
                )
            )

    # DuckDB-specific checks
    elif platform_lower == "duckdb":
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.ERROR,
                    message="DuckDB is single-node; distribution tuning is not applicable",
                    table_name=table_tuning.table_name,
                    tuning_type=TuningType.DISTRIBUTION,
                    suggestion="Remove distribution tuning for DuckDB",
                )
            )

    # BigQuery-specific checks
    elif platform_lower == "bigquery":
        sorting_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sorting_columns:
            result.add_issue(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message="BigQuery does not support explicit sorting; consider clustering instead",
                    table_name=table_tuning.table_name,
                    tuning_type=TuningType.SORTING,
                    suggestion="Use clustering for performance optimization on BigQuery",
                )
            )


def validate_benchmark_tunings(
    benchmark_tunings: BenchmarkTunings,
    schema_registry: dict[str, dict[str, str]],
    platform: Optional[str] = None,
    strict_mode: bool = False,
) -> dict[str, ValidationResult]:
    """Validate all table tunings in a benchmark configuration.

    Args:
        benchmark_tunings: The benchmark tuning configurations
        schema_registry: Dictionary mapping table names to their column schemas
        platform: Target database platform
        strict_mode: Whether to treat warnings as errors

    Returns:
        Dictionary mapping table names to their validation results
    """
    validation_results = {}

    for table_name in benchmark_tunings.get_table_names():
        table_tuning = benchmark_tunings.get_table_tuning(table_name)
        if not table_tuning:
            continue

        table_schema = schema_registry.get(table_name, {})

        # Combine all validation results for this table
        combined_result = ValidationResult()

        # Column existence validation
        existence_result = validate_columns_exist(table_tuning, table_schema, case_sensitive=False)
        for issue in existence_result.get_all_issues():
            combined_result.add_issue(issue)

        # Column type validation
        if table_schema:  # Only validate types if we have schema info
            type_result = validate_column_types(table_tuning, table_schema, strict_mode)
            for issue in type_result.get_all_issues():
                combined_result.add_issue(issue)

        # Conflict detection
        conflict_result = detect_tuning_conflicts(table_tuning, platform)
        for issue in conflict_result.get_all_issues():
            combined_result.add_issue(issue)

        validation_results[table_name] = combined_result

    return validation_results


def validate_constraint_consistency(
    benchmark_tunings: BenchmarkTunings,
) -> ValidationResult:
    """Validate that constraint settings are applied consistently across tables.

    Args:
        benchmark_tunings: The benchmark tunings to validate

    Returns:
        ValidationResult containing any constraint consistency issues
    """
    result = ValidationResult()

    # Get constraint status
    constraint_status = benchmark_tunings.get_constraint_status()

    # Add info messages about constraint settings
    if not constraint_status["primary_keys"]:
        result.add_issue(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="Primary key constraints are disabled for all tables",
                table_name="*ALL*",
                column_name=None,
                tuning_type=None,
            )
        )

    if not constraint_status["foreign_keys"]:
        result.add_issue(
            ValidationIssue(
                level=ValidationLevel.INFO,
                message="Foreign key constraints are disabled for all tables",
                table_name="*ALL*",
                column_name=None,
                tuning_type=None,
            )
        )

    if not constraint_status["primary_keys"] and not constraint_status["foreign_keys"]:
        result.add_issue(
            ValidationIssue(
                level=ValidationLevel.WARNING,
                message="All key constraints are disabled - performance testing without referential integrity",
                table_name="*ALL*",
                column_name=None,
                tuning_type=None,
            )
        )

    return result
