"""Schema validation for migrated YAML catalogs (PRs #590, #604).

Asserts the shared Pydantic schemas accept every real migrated catalog and
reject realistic corruptions (missing field, wrong type/value, typo'd key),
recovering the field-level type safety the pre-migration Python literals had.
"""

from __future__ import annotations

import copy
from importlib import resources

import pytest
import yaml
from pydantic import ValidationError

from benchbox.core.catalog_schema import (
    CATALOG_SCHEMAS,
    BenchmarkRegistryCatalog,
    StaticQueryCatalog,
    validate_all_catalogs,
    validate_catalog,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _load(package: str, filename: str) -> dict:
    return yaml.safe_load(resources.files(package).joinpath(filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("package", "filename", "model"),
    [(package, filename, model) for (package, filename), model in CATALOG_SCHEMAS.items()],
    ids=[f"{package}:{filename}" for package, filename in CATALOG_SCHEMAS],
)
def test_real_catalog_validates(package: str, filename: str, model: type) -> None:
    validate_catalog(package, filename, model)  # raises CatalogSchemaError on failure


def test_validate_all_catalogs_passes() -> None:
    assert validate_all_catalogs() == len(CATALOG_SCHEMAS)


def test_registry_missing_required_field_rejected() -> None:
    bad = copy.deepcopy(_load("benchbox.core", "benchmark_registry.yaml"))
    first = next(iter(bad["benchmark_metadata"]))
    del bad["benchmark_metadata"][first]["category"]
    with pytest.raises(ValidationError):
        BenchmarkRegistryCatalog.model_validate(bad)


def test_registry_wrong_type_rejected() -> None:
    bad = copy.deepcopy(_load("benchbox.core", "benchmark_registry.yaml"))
    first = next(iter(bad["benchmark_metadata"]))
    bad["benchmark_metadata"][first]["num_queries"] = "not-an-int"
    with pytest.raises(ValidationError):
        BenchmarkRegistryCatalog.model_validate(bad)


def test_registry_bad_support_status_rejected() -> None:
    bad = copy.deepcopy(_load("benchbox.core", "benchmark_registry.yaml"))
    first = next(iter(bad["benchmark_metadata"]))
    bad["benchmark_metadata"][first]["support_status"] = "totally-bogus"
    with pytest.raises(ValidationError):
        BenchmarkRegistryCatalog.model_validate(bad)


def test_registry_unknown_field_rejected() -> None:
    # extra="forbid" turns a misspelled/unknown field into a schema failure, not
    # a silently-ignored key that surfaces as a runtime KeyError later.
    bad = copy.deepcopy(_load("benchbox.core", "benchmark_registry.yaml"))
    first = next(iter(bad["benchmark_metadata"]))
    bad["benchmark_metadata"][first]["unexpected_extra_key"] = bad["benchmark_metadata"][first]["category"]
    with pytest.raises(ValidationError):
        BenchmarkRegistryCatalog.model_validate(bad)


def test_query_catalog_missing_sql_rejected() -> None:
    bad = {"QUERIES": {"q1": {"id": "1", "name": "n", "description": "d", "category": "c"}}}
    with pytest.raises(ValidationError):
        StaticQueryCatalog.model_validate(bad)


def test_query_catalog_typoed_field_rejected() -> None:
    bad = {
        "QUERIES": {"q1": {"id": "1", "name": "n", "description": "d", "category": "c", "sql": "SELECT 1", "sqll": "x"}}
    }
    with pytest.raises(ValidationError):
        StaticQueryCatalog.model_validate(bad)
