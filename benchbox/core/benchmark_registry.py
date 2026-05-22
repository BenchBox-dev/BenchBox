"""Benchmark registry - single source of truth for benchmark metadata.

This module provides centralized metadata for all benchmarks in BenchBox.
Both CLI and MCP modules should import from here rather than maintaining
their own copies of benchmark metadata.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib
from collections import Counter
from pathlib import Path
from typing import Any, Literal, cast

import yaml

BenchmarkSupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]

BENCHMARK_SUPPORT_STATUS_VALUES: tuple[BenchmarkSupportStatus, ...] = (
    "stable",
    "beta",
    "experimental",
    "repo_only",
    "deprecated",
    "document_only",
)


def _load_registry_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("benchmark_registry.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _metadata_from_specs(specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata = cast(dict[str, dict[str, Any]], specs["benchmark_metadata"])
    for meta in metadata.values():
        if "estimated_time_range" in meta:
            meta["estimated_time_range"] = tuple(meta["estimated_time_range"])
    return metadata


_REGISTRY_SPECS = _load_registry_specs()

# Category ordering for display (most popular first)
CATEGORY_ORDER = list(_REGISTRY_SPECS["category_order"])

# Benchmark ordering within categories (most popular first)
BENCHMARK_ORDER = cast(dict[str, list[str]], _REGISTRY_SPECS["benchmark_order"])

# Mapping of benchmark IDs to their class names in the benchbox module.
# Used for lazy loading via getattr(benchbox, class_name).
BENCHMARK_CLASS_NAMES = cast(dict[str, str], _REGISTRY_SPECS["benchmark_class_names"])

# Concrete class names in benchbox.core.<id>.benchmark, derived from BENCHMARK_CLASS_NAMES.
# `benchbox.core.benchmark_loader` imports this map to avoid local benchmark-set drift.
# Override individual entries where the core class name doesn't follow the {wrapper}Benchmark pattern.
_CORE_CLASS_NAME_OVERRIDES = cast(dict[str, str], _REGISTRY_SPECS["core_class_name_overrides"])
CORE_BENCHMARK_CLASS_NAMES: dict[str, str] = {
    bid: _CORE_CLASS_NAME_OVERRIDES.get(bid, f"{name}Benchmark") for bid, name in BENCHMARK_CLASS_NAMES.items()
}

# Benchmarks with runtime data-sharing declarations. The registry imports only
# this narrow set during metadata normalization to avoid eager-loading every
# benchmark at discovery time.
BENCHMARK_DATA_SOURCE_PROBE_IDS = tuple(_REGISTRY_SPECS["benchmark_data_source_probe_ids"])

TPC_OFFICIAL_SCALE_OPTIONS = tuple(float(value) for value in _REGISTRY_SPECS["tpc_official_scale_options"])


# Complete benchmark metadata - the single source of truth.
# All metadata fields are documented here for consistency.
BENCHMARK_METADATA = _metadata_from_specs(_REGISTRY_SPECS)


def _validate_benchmark_support_status() -> None:
    missing = sorted(name for name, meta in BENCHMARK_METADATA.items() if "support_status" not in meta)
    invalid = sorted(
        f"{name}={meta.get('support_status')!r}"
        for name, meta in BENCHMARK_METADATA.items()
        if meta.get("support_status") not in BENCHMARK_SUPPORT_STATUS_VALUES
    )
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append(f"missing support_status for: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid support_status entries: {', '.join(invalid)}")
        raise ValueError("Invalid benchmark support_status metadata: " + "; ".join(details))


def _default_scale_for_metadata_probe(benchmark_id: str) -> float:
    meta = BENCHMARK_METADATA[benchmark_id]
    default_scale = meta.get("default_scale")
    if default_scale is not None:
        return float(default_scale)
    scale_options = meta.get("scale_options") or ()
    if scale_options:
        return float(scale_options[0])
    return 1.0


def _benchmark_data_source_from_instance(benchmark_id: str) -> str | None:
    class_name = CORE_BENCHMARK_CLASS_NAMES[benchmark_id]
    module = importlib.import_module(f"benchbox.core.{benchmark_id}.benchmark")
    benchmark_class = getattr(module, class_name)
    instance = benchmark_class(scale_factor=_default_scale_for_metadata_probe(benchmark_id))
    getter = getattr(instance, "get_data_source_benchmark", None)
    if getter is None:
        return None
    data_source = getter()
    if data_source is None:
        return None
    return str(data_source)


def _populate_benchmark_data_sources() -> None:
    for meta in BENCHMARK_METADATA.values():
        meta.setdefault("data_source", None)
    for benchmark_id in BENCHMARK_DATA_SOURCE_PROBE_IDS:
        BENCHMARK_METADATA[benchmark_id]["data_source"] = _benchmark_data_source_from_instance(benchmark_id)


def _validate_benchmark_data_sources() -> None:
    missing = sorted(name for name, meta in BENCHMARK_METADATA.items() if "data_source" not in meta)
    invalid = sorted(
        f"{name}={meta.get('data_source')!r}"
        for name, meta in BENCHMARK_METADATA.items()
        if meta.get("data_source") is not None and not isinstance(meta.get("data_source"), str)
    )
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append(f"missing data_source for: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid data_source entries: {', '.join(invalid)}")
        raise ValueError("Invalid benchmark data_source metadata: " + "; ".join(details))


_populate_benchmark_data_sources()
_validate_benchmark_data_sources()
_validate_benchmark_support_status()


def get_all_benchmarks() -> dict[str, dict[str, Any]]:
    """Get metadata for all available benchmarks.

    Returns:
        Dictionary mapping benchmark IDs to their metadata.
    """
    return BENCHMARK_METADATA.copy()


def get_benchmark_metadata(benchmark_id: str) -> dict[str, Any] | None:
    """Get metadata for a specific benchmark.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Benchmark metadata dict, or None if not found.
    """
    return BENCHMARK_METADATA.get(benchmark_id.lower())


def get_benchmark_default_scale(benchmark_id: str, fallback: float = 0.01) -> float:
    """Return a valid default scale factor for benchmark instantiation."""
    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        return fallback
    default_scale = meta.get("default_scale")
    if default_scale is not None:
        return float(default_scale)
    scale_options = meta.get("scale_options") or ()
    if scale_options:
        return float(scale_options[0])
    return fallback


def get_benchmark_class_name(benchmark_id: str) -> str | None:
    """Get the class name for a benchmark in the benchbox module.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Class name (e.g., 'TPCH', 'TPCDS'), or None if not found.
    """
    return BENCHMARK_CLASS_NAMES.get(benchmark_id.lower())


def get_core_benchmark_class_name(benchmark_id: str) -> str | None:
    """Get the class name for a benchmark in benchbox.core.<id>.benchmark.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Core benchmark class name (e.g., 'TPCHBenchmark'), or None if not found.
    """
    return CORE_BENCHMARK_CLASS_NAMES.get(benchmark_id.lower())


def get_benchmark_class(benchmark_id: str):
    """Get the benchmark class from the benchbox module.

    Uses benchbox module's lazy loading mechanism.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Benchmark class, or None if not available.
    """
    import benchbox

    benchmark_id = benchmark_id.lower()
    class_name = get_benchmark_class_name(benchmark_id)
    if class_name is None:
        return None

    try:
        return getattr(benchbox, class_name)
    except (AttributeError, ImportError):
        # Fallback for benchmarks that are implemented in core but not exported
        # by the top-level benchbox lazy registry.
        core_class_name = get_core_benchmark_class_name(benchmark_id)
        if core_class_name is None:
            return None

        module_name = f"benchbox.core.{benchmark_id}.benchmark"
        try:
            module = importlib.import_module(module_name)
            return getattr(module, core_class_name)
        except (ImportError, AttributeError):
            return None


def is_benchmark_available(benchmark_id: str) -> bool:
    """Check if a benchmark is available (can be imported).

    Args:
        benchmark_id: Benchmark identifier

    Returns:
        True if benchmark class can be imported.
    """
    return get_benchmark_class(benchmark_id) is not None


def list_benchmark_ids() -> list[str]:
    """Get list of all benchmark IDs.

    Returns:
        List of benchmark identifiers.
    """
    return list(BENCHMARK_METADATA.keys())


def list_public_benchmark_ids() -> list[str]:
    """Get benchmark IDs visible on public discovery surfaces."""
    return [bid for bid in list_benchmark_ids() if get_benchmark_surface(bid) == "public"]


def list_loader_benchmark_ids() -> list[str]:
    """Get benchmark IDs supported by the core benchmark loader.

    Returns:
        List of benchmark identifiers loadable via benchbox.core.benchmark_loader.
    """
    return list(CORE_BENCHMARK_CLASS_NAMES.keys())


def get_benchmark_support_status(benchmark_id: str) -> BenchmarkSupportStatus | None:
    """Return the registry-declared product support status for a benchmark."""
    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        return None
    return cast(BenchmarkSupportStatus, meta["support_status"])


def get_benchmarks_by_support_status(status: BenchmarkSupportStatus) -> list[str]:
    """Return benchmark IDs classified with *status*."""
    if status not in BENCHMARK_SUPPORT_STATUS_VALUES:
        raise ValueError(
            f"Unknown benchmark support_status {status!r}. "
            f"Expected one of: {', '.join(BENCHMARK_SUPPORT_STATUS_VALUES)}"
        )
    return sorted(name for name, meta in BENCHMARK_METADATA.items() if meta["support_status"] == status)


def get_benchmark_registry_summary() -> dict[str, Any]:
    """Return count summaries for benchmark contract and docs drift checks."""
    support_counts = Counter(
        cast(BenchmarkSupportStatus, meta["support_status"]) for meta in BENCHMARK_METADATA.values()
    )
    surface_counts = Counter(str(meta.get("surface", "public")) for meta in BENCHMARK_METADATA.values())
    return {
        "total": len(BENCHMARK_METADATA),
        "loader": len(list_loader_benchmark_ids()),
        "public": len(list_public_benchmark_ids()),
        "dataframe_supported": sum(1 for meta in BENCHMARK_METADATA.values() if meta.get("supports_dataframe", False)),
        "support_status": {status: support_counts.get(status, 0) for status in BENCHMARK_SUPPORT_STATUS_VALUES},
        "surface": dict(sorted(surface_counts.items())),
    }


def get_benchmarks_by_category(category: str) -> dict[str, dict[str, Any]]:
    """Get benchmarks filtered by category.

    Args:
        category: Category name (e.g., 'TPC', 'Academic')

    Returns:
        Dictionary of benchmarks in that category.
    """
    return {bid: meta for bid, meta in BENCHMARK_METADATA.items() if meta.get("category") == category}


def get_categories() -> list[str]:
    """Get list of all categories in display order.

    Returns:
        List of category names.
    """
    # Return categories that actually have benchmarks
    categories_with_benchmarks = set()
    for meta in BENCHMARK_METADATA.values():
        categories_with_benchmarks.add(meta.get("category", "Unknown"))

    # Return in preferred order, adding any extras at the end
    result = [c for c in CATEGORY_ORDER if c in categories_with_benchmarks]
    for c in categories_with_benchmarks:
        if c not in result:
            result.append(c)
    return result


def validate_scale_factor(
    benchmark_id: str,
    scale_factor: float,
) -> None:
    """Validate scale factor against benchmark requirements.

    Resolution order:

    1. TPC-DS delegates to the compliance classifier in
       ``benchbox.core.tpcds.compliance``.
    2. If the benchmark declares ``scale_options`` (a list of canonical
       scales), require ``scale_factor`` to be one of those values. This
       is the primary gate — single-element lists like joinorder's
       ``[1.0]`` reject everything else, multi-element lists like
       tpch's development subscales plus official TPC scale ladder reject
       any non-canonical SF.
    3. Otherwise fall back to the legacy ``min_scale`` key, which only
       enforces a lower bound.

    Args:
        benchmark_id: The benchmark identifier (e.g., 'tpcds', 'tpch').
        scale_factor: The requested scale factor.

    Raises:
        ScaleFactorNotSupportedError: If the benchmark declares
            ``scale_options`` and ``scale_factor`` is not in that list.
        ValueError: If the legacy ``min_scale`` lower bound is violated
            (subclass-compatible — ``ScaleFactorNotSupportedError``
            inherits from ``ValueError`` so existing handlers keep
            working).
    """
    from benchbox.core.errors import ScaleFactorNotSupportedError

    if benchmark_id == "tpcds":
        # TPC-DS uses the shared compliance classifier - not a simple min_scale check.
        from benchbox.core.tpcds.compliance import validate_tpcds_scale

        validate_tpcds_scale(scale_factor)
        return

    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        return  # Unknown benchmark, skip validation

    scale_options = meta.get("scale_options")
    if scale_options:
        # Compare as floats to avoid 1 vs 1.0 mismatches (e.g., when callers
        # pass int literals).
        try:
            sf = float(scale_factor)
        except (TypeError, ValueError) as exc:
            raise ScaleFactorNotSupportedError(benchmark_id, scale_factor, scale_options) from exc
        if not any(abs(sf - float(opt)) < 1e-9 for opt in scale_options):
            raise ScaleFactorNotSupportedError(benchmark_id, scale_factor, scale_options)
        return

    min_scale = meta.get("min_scale")
    if min_scale is not None and scale_factor < min_scale:
        raise ValueError(f"{benchmark_id.upper()} requires scale_factor >= {min_scale} (got {scale_factor}).")


def get_benchmark_surface(benchmark_id: str) -> str:
    """Return the registry-declared surface visibility for a benchmark.

    "public" (default) means the benchmark is visible to public discovery
    surfaces: CLI listing/filter/category selection, MCP listings, result
    publisher discovery, and the result explorer. "internal" means those
    discovery surfaces hide the benchmark, but explicit callers can still run
    it by ID; result bundles publish locally.

    Returns "public" for unregistered benchmarks (defensive default).
    """
    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        return "public"
    return str(meta.get("surface", "public"))
