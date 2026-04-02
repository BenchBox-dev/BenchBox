"""Parity checks between benchmark loader and benchmark registry."""

from __future__ import annotations

import pytest

from benchbox.core.benchmark_loader import get_benchmark_class
from benchbox.core.benchmark_registry import (
    get_benchmark_class as get_registry_benchmark_class,
    get_core_benchmark_class_name,
    list_benchmark_ids,
    list_loader_benchmark_ids,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_loader_and_registry_benchmark_ids_match() -> None:
    """Loader benchmark IDs should exactly match the registry benchmark IDs."""

    assert set(list_loader_benchmark_ids()) == set(list_benchmark_ids())


@pytest.mark.parametrize("benchmark_id", sorted(list_benchmark_ids()))
def test_loader_class_name_mapping_is_defined_for_each_registry_benchmark(benchmark_id: str) -> None:
    """Each registry benchmark should have an explicit core loader class mapping."""

    class_name = get_core_benchmark_class_name(benchmark_id)
    assert isinstance(class_name, str)
    assert len(class_name) > 0


@pytest.mark.parametrize("benchmark_id", sorted(list_benchmark_ids()))
def test_loader_resolves_registry_benchmark_classes(benchmark_id: str) -> None:
    """Loader should resolve a class for every registry benchmark ID."""

    benchmark_class = get_benchmark_class(benchmark_id)
    assert benchmark_class.__name__ == get_core_benchmark_class_name(benchmark_id)


def test_registry_class_lookup_falls_back_to_core_for_ai_primitives() -> None:
    """Registry lookup should return a class when top-level wrapper export is absent."""

    benchmark_class = get_registry_benchmark_class("ai_primitives")
    assert benchmark_class is not None
    assert benchmark_class.__name__ == get_core_benchmark_class_name("ai_primitives")
