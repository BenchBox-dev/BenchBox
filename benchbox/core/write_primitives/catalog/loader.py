"""Utilities for loading the Write Primitives benchmark operation catalog.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

CATALOG_FILENAME = "operations.yaml"


class WritePrimitivesCatalogError(RuntimeError):
    """Raised when the Write Primitives operation catalog cannot be loaded or is invalid."""


@dataclass(frozen=True)
class ValidationQuery:
    """Representation of a validation query for a write operation."""

    id: str
    sql: str
    expected_rows: int | None = None
    expected_rows_min: int | None = None
    expected_rows_max: int | None = None
    expected_values: dict[str, Any] | None = None
    check_expression: str | None = None
    # Tolerance-based scalar validation for approximate sketch reads. The
    # validator asserts that the first column of the first row falls in
    # [expected_value_min, expected_value_max]. Both fields must be set
    # together; combining them with expected_rows*/expected_values is rejected
    # at load time because they describe a different validation kind.
    expected_value_min: float | None = None
    expected_value_max: float | None = None
    # Per-platform override for the validation SQL body. Mirrors the
    # operation-level platform_overrides semantics: a string replaces the
    # default sql for that platform; an explicit `null` skips validation
    # on that platform with a logged reason (the op result stays passed
    # because skip means "not applicable on this engine", not "failed").
    # Platforms with no key in this mapping fall through to the default sql.
    platform_overrides: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteOperation:
    """Representation of a single write operation entry."""

    id: str
    category: str
    description: str
    write_sql: str
    validation_queries: list[ValidationQuery] = field(default_factory=list)
    cleanup_sql: str | None = None
    expected_rows_affected: int | None = None
    file_dependencies: list[str] = field(default_factory=list)
    platform_overrides: dict[str, str] = field(default_factory=dict)
    requires_setup: bool = True  # Whether operation requires staging tables to be set up


@dataclass(frozen=True)
class WriteOperationsCatalog:
    """Container for the write operations catalog."""

    version: int
    operations: dict[str, WriteOperation]


def _load_catalog_payload() -> dict:
    try:
        catalog_file = resources.files(__package__).joinpath(CATALOG_FILENAME)
    except (AttributeError, FileNotFoundError) as exc:
        raise WritePrimitivesCatalogError("Write Primitives operation catalog resource not found") from exc

    try:
        with catalog_file.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise WritePrimitivesCatalogError("Unable to read write primitives operation catalog") from exc
    except yaml.YAMLError as exc:
        raise WritePrimitivesCatalogError("Invalid YAML in write primitives operation catalog") from exc

    if not isinstance(payload, dict):
        raise WritePrimitivesCatalogError("Write Primitives operation catalog must be a mapping")
    return payload


def _parse_validation_queries(operation_id: str, raw_validations: object) -> list[ValidationQuery]:
    if not isinstance(raw_validations, list):
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' validation_queries must be a list")
    queries: list[ValidationQuery] = []
    for val_idx, val_entry in enumerate(raw_validations):
        if not isinstance(val_entry, dict):
            raise WritePrimitivesCatalogError(
                f"Validation query {val_idx} in operation '{operation_id}' must be a mapping"
            )
        val_id = val_entry.get("id")
        if not isinstance(val_id, str) or not val_id.strip():
            raise WritePrimitivesCatalogError(f"Validation query {val_idx} in operation '{operation_id}' missing 'id'")
        val_sql = val_entry.get("sql")
        if not isinstance(val_sql, str) or not val_sql.strip():
            raise WritePrimitivesCatalogError(
                f"Validation query '{val_id}' in operation '{operation_id}' missing 'sql'"
            )
        expected_value_min, expected_value_max = _parse_expected_value_bounds(operation_id, val_id, val_entry)
        platform_overrides = _parse_validation_platform_overrides(operation_id, val_id, val_entry)
        queries.append(
            ValidationQuery(
                id=val_id.strip(),
                sql=val_sql,
                expected_rows=val_entry.get("expected_rows"),
                expected_rows_min=val_entry.get("expected_rows_min"),
                expected_rows_max=val_entry.get("expected_rows_max"),
                expected_values=val_entry.get("expected_values"),
                check_expression=val_entry.get("check_expression"),
                expected_value_min=expected_value_min,
                expected_value_max=expected_value_max,
                platform_overrides=platform_overrides,
            )
        )
    return queries


def _parse_validation_platform_overrides(
    operation_id: str,
    val_id: str,
    val_entry: dict,
) -> dict[str, str | None]:
    """Parse and validate per-platform validation SQL overrides.

    Each value must be either a non-empty string (replacement SQL for that
    platform) or `null` (explicit skip with a logged reason at runtime).
    Empty strings and other types are rejected at load time so a typo cannot
    silently disable validation.
    """
    raw = val_entry.get("platform_overrides")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' platform_overrides must be a mapping"
        )
    overrides: dict[str, str | None] = {}
    for platform_key, override in raw.items():
        if not isinstance(platform_key, str) or not platform_key.strip():
            raise WritePrimitivesCatalogError(
                f"Validation query '{val_id}' in operation '{operation_id}' "
                "platform_overrides keys must be non-empty platform names"
            )
        if override is None:
            overrides[platform_key.strip()] = None
            continue
        if not isinstance(override, str) or not override.strip():
            raise WritePrimitivesCatalogError(
                f"Validation query '{val_id}' in operation '{operation_id}' "
                f"platform_overrides['{platform_key}'] must be a non-empty string or null"
            )
        overrides[platform_key.strip()] = override
    return overrides


def _parse_expected_value_bounds(
    operation_id: str,
    val_id: str,
    val_entry: dict,
) -> tuple[float | None, float | None]:
    """Parse and validate expected_value_min/max for tolerance-based scalar checks."""
    raw_min = val_entry.get("expected_value_min")
    raw_max = val_entry.get("expected_value_max")
    if raw_min is None and raw_max is None:
        return None, None
    if raw_min is None or raw_max is None:
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' must set both "
            "expected_value_min and expected_value_max together"
        )
    try:
        bound_min = float(raw_min)
        bound_max = float(raw_max)
    except (TypeError, ValueError) as exc:
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' expected_value_min/max must be numeric"
        ) from exc
    if bound_min > bound_max:
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' expected_value_min "
            f"({bound_min}) must be <= expected_value_max ({bound_max})"
        )
    if any(val_entry.get(k) is not None for k in ("expected_rows", "expected_rows_min", "expected_rows_max")):
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' cannot combine "
            "expected_value_min/max with expected_rows fields — they describe different "
            "validation kinds"
        )
    if val_entry.get("expected_values") is not None:
        raise WritePrimitivesCatalogError(
            f"Validation query '{val_id}' in operation '{operation_id}' cannot combine "
            "expected_value_min/max with expected_values"
        )
    return bound_min, bound_max


def _parse_optional_scalars(operation_id: str, entry: dict) -> tuple[str | None, int | None]:
    cleanup_sql = entry.get("cleanup_sql")
    if cleanup_sql is not None and not isinstance(cleanup_sql, str):
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' cleanup_sql must be a string")

    expected_rows_affected = entry.get("expected_rows_affected")
    if expected_rows_affected is not None:
        try:
            expected_rows_affected = int(expected_rows_affected)
        except (TypeError, ValueError):
            raise WritePrimitivesCatalogError(
                f"Catalog entry '{operation_id}' expected_rows_affected must be an integer"
            ) from None
    return cleanup_sql, expected_rows_affected


def _parse_operation_entry(index: int, entry: object, existing_ids: set[str]) -> WriteOperation:
    if not isinstance(entry, dict):
        raise WritePrimitivesCatalogError(f"Catalog entry at index {index} must be a mapping")

    operation_id = entry.get("id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise WritePrimitivesCatalogError(f"Catalog entry at index {index} is missing a valid 'id'")
    operation_id = operation_id.strip()

    if operation_id in existing_ids:
        raise WritePrimitivesCatalogError(f"Duplicate operation id detected in catalog: {operation_id}")

    category = entry.get("category")
    if not isinstance(category, str) or not category.strip():
        category = operation_id.split("_")[0]
    category = category.strip().lower()

    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' must include a description")
    description = description.strip()

    write_sql = entry.get("write_sql")
    if not isinstance(write_sql, str) or not write_sql.strip():
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' must include non-empty write_sql")

    cleanup_sql, expected_rows_affected = _parse_optional_scalars(operation_id, entry)

    file_dependencies = entry.get("file_dependencies", [])
    if not isinstance(file_dependencies, list):
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' file_dependencies must be a list")

    platform_overrides = entry.get("platform_overrides", {})
    if not isinstance(platform_overrides, dict):
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' platform_overrides must be a mapping")

    requires_setup = entry.get("requires_setup", True)
    if not isinstance(requires_setup, bool):
        raise WritePrimitivesCatalogError(f"Catalog entry '{operation_id}' requires_setup must be a boolean")

    return WriteOperation(
        id=operation_id,
        category=category,
        description=description,
        write_sql=write_sql,
        validation_queries=_parse_validation_queries(operation_id, entry.get("validation_queries", [])),
        cleanup_sql=cleanup_sql,
        expected_rows_affected=expected_rows_affected,
        file_dependencies=file_dependencies,
        platform_overrides=platform_overrides,
        requires_setup=requires_setup,
    )


def load_write_primitives_catalog() -> WriteOperationsCatalog:
    """Load and validate the write primitives operation catalog from package resources.

    Returns:
        WriteOperationsCatalog containing all operations

    Raises:
        WritePrimitivesCatalogError: If catalog cannot be loaded or is invalid
    """
    payload = _load_catalog_payload()

    raw_version = payload.get("version", 1)
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise WritePrimitivesCatalogError("Write Primitives operation catalog version must be an integer") from exc

    raw_entries = payload.get("operations")
    if not isinstance(raw_entries, list):
        raise WritePrimitivesCatalogError("Write Primitives operation catalog must define an 'operations' list")

    operations: dict[str, WriteOperation] = {}
    for index, entry in enumerate(raw_entries):
        op = _parse_operation_entry(index, entry, set(operations.keys()))
        operations[op.id] = op

    return WriteOperationsCatalog(version=version, operations=operations)


__all__ = [
    "WriteOperationsCatalog",
    "WriteOperation",
    "ValidationQuery",
    "WritePrimitivesCatalogError",
    "load_write_primitives_catalog",
]
