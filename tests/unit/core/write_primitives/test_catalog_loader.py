"""Loader-validation tests for write_primitives catalog (expected_value_min/max)."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from benchbox.core.write_primitives.catalog import loader as wp_loader
from benchbox.core.write_primitives.catalog.loader import (
    WritePrimitivesCatalogError,
    load_write_primitives_catalog,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, yaml_text: str) -> None:
    class DummyResource:
        def open(self, mode: str = "r", encoding: str | None = None):
            return io.StringIO(yaml_text)

    monkeypatch.setattr(
        wp_loader,
        "resources",
        SimpleNamespace(files=lambda package: SimpleNamespace(joinpath=lambda filename: DummyResource())),
    )


def test_loader_accepts_expected_value_min_and_max(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
version: 1
operations:
  - id: sketch_query_demo
    description: demo sketch query op
    write_sql: "SELECT 1;"
    validation_queries:
      - id: distinct_estimate_in_range
        sql: "SELECT 1.0;"
        expected_value_min: 100
        expected_value_max: 200
"""
    _patch_catalog(monkeypatch, yaml_text)
    catalog = load_write_primitives_catalog()
    op = catalog.operations["sketch_query_demo"]
    val = op.validation_queries[0]
    assert val.expected_value_min == pytest.approx(100.0)
    assert val.expected_value_max == pytest.approx(200.0)


def test_loader_rejects_expected_value_min_without_max(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
version: 1
operations:
  - id: bad_op
    description: missing max bound
    write_sql: "SELECT 1;"
    validation_queries:
      - id: bad
        sql: "SELECT 1.0;"
        expected_value_min: 100
"""
    _patch_catalog(monkeypatch, yaml_text)
    with pytest.raises(WritePrimitivesCatalogError, match="must set both"):
        load_write_primitives_catalog()


def test_loader_rejects_min_greater_than_max(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
version: 1
operations:
  - id: bad_op
    description: inverted bounds
    write_sql: "SELECT 1;"
    validation_queries:
      - id: bad
        sql: "SELECT 1.0;"
        expected_value_min: 200
        expected_value_max: 100
"""
    _patch_catalog(monkeypatch, yaml_text)
    with pytest.raises(WritePrimitivesCatalogError, match="must be <= expected_value_max"):
        load_write_primitives_catalog()


def test_loader_rejects_combination_with_expected_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
version: 1
operations:
  - id: bad_op
    description: mixed validation kinds
    write_sql: "SELECT 1;"
    validation_queries:
      - id: bad
        sql: "SELECT 1.0;"
        expected_rows: 1
        expected_value_min: 0
        expected_value_max: 10
"""
    _patch_catalog(monkeypatch, yaml_text)
    with pytest.raises(WritePrimitivesCatalogError, match="cannot combine"):
        load_write_primitives_catalog()


def test_loader_rejects_non_numeric_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
version: 1
operations:
  - id: bad_op
    description: non-numeric bound
    write_sql: "SELECT 1;"
    validation_queries:
      - id: bad
        sql: "SELECT 1.0;"
        expected_value_min: "not a number"
        expected_value_max: 10
"""
    _patch_catalog(monkeypatch, yaml_text)
    with pytest.raises(WritePrimitivesCatalogError, match="must be numeric"):
        load_write_primitives_catalog()


def test_loader_real_catalog_still_loads() -> None:
    """The real shipped catalog continues to load with the new schema field."""
    catalog = load_write_primitives_catalog()
    assert catalog.operations
    for op in catalog.operations.values():
        for v in op.validation_queries:
            # Pre-existing entries should keep these as None.
            if op.id and not op.id.startswith("sketch_"):
                assert v.expected_value_min is None
                assert v.expected_value_max is None
