"""Parity checks between benchmark loader and benchmark registry."""

from __future__ import annotations

import pytest

from benchbox.core.benchmark_loader import get_benchmark_class, get_benchmark_instance, get_core_benchmark_class
from benchbox.core.benchmark_registry import (
    get_benchmark_class as get_registry_benchmark_class,
    get_benchmark_default_scale,
    get_benchmark_id_for_class_name,
    get_core_benchmark_class_name,
    get_public_benchmark_class,
    list_benchmark_ids,
    list_loader_benchmark_ids,
)
from benchbox.core.schemas import BenchmarkConfig

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

    benchmark_class = get_core_benchmark_class(benchmark_id)
    assert benchmark_class.__name__ == get_core_benchmark_class_name(benchmark_id)


@pytest.mark.parametrize("benchmark_id", sorted(list_benchmark_ids()))
def test_loader_benchmark_runtime_identity_matches_registry_id(benchmark_id: str) -> None:
    """Runtime identity should use the registry ID, not class-name heuristics."""

    benchmark_class = get_core_benchmark_class(benchmark_id)
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

    benchmark_class = get_core_benchmark_class(benchmark_id)
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

    benchmark_class = get_core_benchmark_class(benchmark_id)
    benchmark = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_id))

    assert benchmark.logger.name == f"benchbox.core.{benchmark_id}"


def test_registry_class_lookup_falls_back_to_core_for_ai_primitives() -> None:
    """Registry lookup should return a class when top-level wrapper export is absent."""

    benchmark_class = get_registry_benchmark_class("ai_primitives")
    assert benchmark_class is not None
    assert benchmark_class.__name__ == get_core_benchmark_class_name("ai_primitives")


def test_public_and_core_class_lookup_names_expose_distinct_surfaces() -> None:
    """Intent-revealing lookup names should make wrapper/core surface explicit."""

    assert get_public_benchmark_class("tpch").__name__ == "TPCH"
    assert get_core_benchmark_class("tpch").__name__ == "TPCHBenchmark"
    assert get_registry_benchmark_class("tpch") is get_public_benchmark_class("tpch")
    assert get_benchmark_class("tpch") is get_core_benchmark_class("tpch")


def test_loader_does_not_retry_internal_constructor_type_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An internal TypeError from __init__ should surface instead of being treated as missing parallel support."""

    calls: list[int | None] = []

    class RaisesInternally:
        def __init__(self, *, parallel: int | None = None, **kwargs):
            calls.append(parallel)
            raise TypeError("internal constructor bug")

    monkeypatch.setattr("benchbox.core.benchmark_loader.get_core_benchmark_class", lambda _name: RaisesInternally)
    monkeypatch.setattr("benchbox.core.benchmark_loader.validate_scale_factor", lambda _name, _scale: None)

    config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)
    with pytest.raises(TypeError, match="internal constructor bug"):
        get_benchmark_instance(config, system_profile=None)

    assert calls == [1]


def test_loader_omits_parallel_when_constructor_signature_rejects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Benchmarks that genuinely lack a parallel parameter should still instantiate."""

    calls: list[dict[str, object]] = []

    class NoParallel:
        def __init__(
            self, *, scale_factor: float, compress_data: bool, compression_type: str, compression_level: int | None
        ):
            calls.append(
                {
                    "scale_factor": scale_factor,
                    "compress_data": compress_data,
                    "compression_type": compression_type,
                    "compression_level": compression_level,
                }
            )

    monkeypatch.setattr("benchbox.core.benchmark_loader.get_core_benchmark_class", lambda _name: NoParallel)
    monkeypatch.setattr("benchbox.core.benchmark_loader.validate_scale_factor", lambda _name, _scale: None)

    config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)
    assert isinstance(get_benchmark_instance(config, system_profile=None), NoParallel)
    assert calls == [
        {
            "scale_factor": 0.01,
            "compress_data": False,
            "compression_type": "zstd",
            "compression_level": None,
        }
    ]
