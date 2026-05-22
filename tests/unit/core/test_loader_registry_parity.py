"""Parity checks between benchmark loader and benchmark registry."""

from __future__ import annotations

import pytest

from benchbox.core.benchmark_loader import get_benchmark_class
from benchbox.core.benchmark_registry import (
    get_benchmark_class as get_registry_benchmark_class,
    get_benchmark_default_scale,
    get_benchmark_id_for_class_name,
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


@pytest.mark.parametrize("benchmark_id", sorted(list_benchmark_ids()))
def test_loader_benchmark_runtime_identity_matches_registry_id(benchmark_id: str) -> None:
    """Runtime identity should use the registry ID, not class-name heuristics."""

    benchmark_class = get_benchmark_class(benchmark_id)
    benchmark = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_id))

    if hasattr(benchmark, "_get_benchmark_name"):
        assert benchmark._get_benchmark_name() == benchmark_id


@pytest.mark.parametrize("benchmark_id", sorted(list_benchmark_ids()))
def test_registry_resolves_core_class_name_back_to_benchmark_id(benchmark_id: str) -> None:
    """Core benchmark class names should reverse-map to their canonical IDs."""

    class_name = get_core_benchmark_class_name(benchmark_id)
    assert class_name is not None
    assert get_benchmark_id_for_class_name(class_name) == benchmark_id


@pytest.mark.parametrize(
    ("benchmark_id", "path_fragment"),
    [
        ("joinorder_synthetic", "joinorder_synthetic_sf1"),
        ("metadata_primitives", "metadata_primitives_sf1"),
        ("tpch_skew", "tpch_skew_sf001"),
        ("vector_search", "vector_search_sf001"),
    ],
)
def test_direct_default_output_paths_use_canonical_registry_ids(benchmark_id: str, path_fragment: str) -> None:
    """Benchmarks that own their data directory should not collapse underscores."""

    benchmark_class = get_benchmark_class(benchmark_id)
    benchmark = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_id))

    assert path_fragment in str(benchmark.output_dir)


@pytest.mark.parametrize(
    "benchmark_id",
    [
        "ai_primitives",
        "joinorder_synthetic",
        "metadata_primitives",
        "read_primitives",
        "tpch_skew",
        "transaction_primitives",
        "vector_search",
        "write_primitives",
    ],
)
def test_previous_heuristic_mismatches_use_canonical_logger_names(benchmark_id: str) -> None:
    """The known class-name heuristic failures should no longer leak into loggers."""

    benchmark_class = get_benchmark_class(benchmark_id)
    benchmark = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_id))

    assert benchmark.logger.name == f"benchbox.core.{benchmark_id}"


def test_registry_class_lookup_falls_back_to_core_for_ai_primitives() -> None:
    """Registry lookup should return a class when top-level wrapper export is absent."""

    benchmark_class = get_registry_benchmark_class("ai_primitives")
    assert benchmark_class is not None
    assert benchmark_class.__name__ == get_core_benchmark_class_name("ai_primitives")
