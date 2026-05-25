"""Shared schema validation for migrated YAML catalogs.

The shrink campaign moved benchmark metadata and static query catalogs from
Python literals into YAML (PRs #590, #604). Those catalogs are loaded as plain
dicts, so a typo'd field name, a missing required field, or a wrong type
surfaces as a runtime error at first use rather than a CI failure -- the
implicit type safety the Python literals used to provide is gone.

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
from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from benchbox.utils.printing import emit

SupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]
Surface = Literal["public", "internal"]


class CatalogSchemaError(ValueError):
    """Raised when a migrated catalog fails schema validation."""


class BenchmarkMeta(BaseModel):
    """Per-benchmark metadata entry in ``benchmark_registry.yaml``."""

    model_config = ConfigDict(extra="forbid")

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
    estimated_time_range: tuple[float, float]
    base_memory_gb: float
    data_source: str | None
    supports_dataframe: bool
    min_scale: float | None = None
    surface: Surface | None = None
    data_manifest: str | None = None


class BenchmarkRegistryCatalog(BaseModel):
    """Schema for ``benchbox/core/benchmark_registry.yaml`` (PR #590)."""

    model_config = ConfigDict(extra="forbid")

    category_order: list[str]
    benchmark_order: dict[str, list[str]]
    benchmark_class_names: dict[str, str]
    core_class_name_overrides: dict[str, str]
    data_source_probe_ids: list[str]
    tpc_official_scale_options: list[float]
    benchmark_metadata: dict[str, BenchmarkMeta]


class StaticQueryEntry(BaseModel):
    """A single query in a static ``query_catalog.yaml`` collection."""

    model_config = ConfigDict(extra="forbid")

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


# (package, filename) -> Pydantic model. Register a migrated catalog here to put
# it under the CI schema gate. Covers the campaign catalogs that lack a
# field-level dataclass layer; catalogs already parsed into typed dataclasses
# (e.g. write_primitives/catalog/loader.py) keep their existing field safety.
CATALOG_SCHEMAS: dict[tuple[str, str], type[BaseModel]] = {
    ("benchbox.core", "benchmark_registry.yaml"): BenchmarkRegistryCatalog,
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
