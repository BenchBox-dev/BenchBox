"""Shared schema validation for shrink-campaign YAML migrations.

The shrink campaign moved benchmark metadata, benchmark result specs, and static
query catalogs from Python literals into YAML (PRs #590, #604). Those catalogs
are loaded as plain dicts, so a typo'd field name, a missing required field, or a
wrong type surfaces as a runtime error at first use rather than a CI failure --
the implicit type safety the Python literals used to provide is gone.

This module recovers that safety with one shared set of Pydantic models plus a
``CATALOG_SCHEMAS`` registry of ``(package, filename) -> model``. A single test
(``tests/unit/core/test_catalog_schema.py``) and the ``make catalog-schema-check``
gate validate every registered catalog, instead of per-loader ad-hoc checks.
Add a catalog by registering its model in ``CATALOG_SCHEMAS``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, field_validator

from benchbox.utils.printing import emit

SupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]
Surface = Literal["public", "internal"]
_STRICT_MODEL_CONFIG = ConfigDict(extra="forbid", strict=True)


class CatalogSchemaError(ValueError):
    """Raised when a migrated catalog fails schema validation."""


class BenchmarkMeta(BaseModel):
    """Per-benchmark metadata entry in ``benchmark_registry.yaml``."""

    model_config = _STRICT_MODEL_CONFIG

    display_name: str
    description: str
    category: str
    support_status: SupportStatus
    num_queries: int
    query_description: str
    supports_streams: bool
    default_scale: float
    scale_options: list[float]
    complexity: str
    estimated_time_range: list[float] = Field(min_length=2, max_length=2)
    base_memory_gb: float = Field(gt=0)
    data_source: str | None
    supports_dataframe: bool
    min_scale: float | None = None
    surface: Surface | None = None
    data_manifest: str | None = None
    # Opt-in: the runner inserts an explicit statistics phase between load and
    # query for this benchmark when the user requests --phases ...,statistics.
    supports_statistics_phase: bool = False

    @field_validator("estimated_time_range")
    @classmethod
    def _validate_estimated_time_range(cls, value: list[float]) -> list[float]:
        if any(item < 0 for item in value) or value[0] > value[1]:
            raise ValueError("estimated_time_range must contain non-negative ordered bounds")
        return value


class BenchmarkRegistryCatalog(BaseModel):
    """Schema for ``benchbox/core/benchmark_registry.yaml`` (PR #590)."""

    model_config = _STRICT_MODEL_CONFIG

    category_order: list[str]
    benchmark_order: dict[str, list[str]]
    benchmark_class_names: dict[str, str]
    core_class_name_overrides: dict[str, str]
    data_source_probe_ids: list[str]
    tpc_official_scale_options: list[float]
    benchmark_metadata: dict[str, BenchmarkMeta]


class BenchmarkSpecEntry(BaseModel):
    """Per-benchmark result-integrity spec in ``benchmark_specs.yaml``."""

    model_config = _STRICT_MODEL_CONFIG

    benchmark_id: str
    unique_query_ids: list[str]
    min_unique_queries: int = 0
    min_success_rate: float = 1.0
    high_failure_expected: bool = False
    requires_tables_object: bool = True
    sf1_row_counts: dict[str, int] | None = None
    sf1_power_at_size_range: list[float] | None = Field(default=None, min_length=2, max_length=2)


class BenchmarkSpecsCatalog(BaseModel):
    """Schema for ``benchbox/core/results/benchmark_specs.yaml`` (PR #590)."""

    model_config = _STRICT_MODEL_CONFIG

    legacy_aliases: dict[str, str]
    tpch_sf1_row_counts: dict[str, int]
    benchmark_specs: dict[str, BenchmarkSpecEntry]


class StaticQueryEntry(BaseModel):
    """A single query in a static ``query_catalog.yaml`` collection."""

    model_config = _STRICT_MODEL_CONFIG

    id: str
    name: str
    description: str
    category: str
    sql: str
    params: dict[str, object] | None = None


class StaticQueryCatalog(RootModel[dict[str, dict[str, StaticQueryEntry]]]):
    """Schema for static query catalogs (PR #604).

    The top-level keys are query-set names (``QUERIES`` and, for nyctaxi,
    ``GREEN_QUERIES`` / ``HVFHV_QUERIES`` / ``CROSS_TYPE_QUERIES``); each maps a
    query key to a :class:`StaticQueryEntry`.
    """

    model_config = ConfigDict(strict=True)


# (package, filename) -> Pydantic model. Register shrink-campaign migrated
# catalogs here to put them under the CI schema gate. This intentionally covers
# raw-dict migrations that lack a field-level dataclass layer; older catalogs
# already parsed into typed loaders keep their existing validators.
CATALOG_SCHEMAS: dict[tuple[str, str], type[BaseModel]] = {
    ("benchbox.core", "benchmark_registry.yaml"): BenchmarkRegistryCatalog,
    ("benchbox.core.results", "benchmark_specs.yaml"): BenchmarkSpecsCatalog,
    ("benchbox.core.flightdata", "query_catalog.yaml"): StaticQueryCatalog,
    ("benchbox.core.nyctaxi", "query_catalog.yaml"): StaticQueryCatalog,
    ("benchbox.core.tsbs_devops", "query_catalog.yaml"): StaticQueryCatalog,
}


def validate_catalog(package: str, filename: str, model: type[BaseModel]) -> BaseModel:
    """Load ``package/filename`` and validate it against ``model``.

    Raises:
        CatalogSchemaError: if the YAML does not satisfy the model.
    """
    text = resources.files(package).joinpath(filename).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise CatalogSchemaError(f"{package}/{filename} failed schema validation:\n{exc}") from exc


def validate_all_catalogs() -> int:
    """Validate every catalog in ``CATALOG_SCHEMAS``; return the count validated."""
    for (package, filename), model in CATALOG_SCHEMAS.items():
        validate_catalog(package, filename, model)
    return len(CATALOG_SCHEMAS)


def main() -> int:
    """CI entry point: ``uv run -- python -m benchbox.core.catalog_schema``."""
    try:
        count = validate_all_catalogs()
    except CatalogSchemaError as exc:
        emit(f"catalog-schema-check FAILED:\n{exc}")
        return 1
    emit(f"catalog-schema-check OK: {count} migrated catalogs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
