"""Benchmark registry - single source of truth for benchmark metadata.

This module provides centralized metadata for all benchmarks in BenchBox.
Both CLI and MCP modules should import from here rather than maintaining
their own copies of benchmark metadata.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib
import math
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal, Protocol, cast, runtime_checkable

import yaml

from benchbox.utils.singleflight_cache import SingleFlightValueCache

BenchmarkSupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]

BENCHMARK_SUPPORT_STATUS_VALUES: tuple[BenchmarkSupportStatus, ...] = (
    "stable",
    "beta",
    "experimental",
    "repo_only",
    "deprecated",
    "document_only",
)

# Benchmark metadata is stored as package data so this module keeps only
# behavior and validation logic in Python. The payload is loaded lazily and
# cached on first access (see _registry) so the file I/O + YAML parse stay off
# the import-critical path -- benchmark_loader imports this module -- matching
# the repo's other catalog loaders (e.g. write_primitives/catalog/loader.py).


def _load_registry_payload() -> dict[str, Any]:
    with resources.files(__package__).joinpath("benchmark_registry.yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("benchmark_registry.yaml must contain a mapping")
    return payload


def _normalize_benchmark_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    if "estimated_time_range" in normalized:
        normalized["estimated_time_range"] = tuple(normalized["estimated_time_range"])
    return normalized


@runtime_checkable
class BenchmarkFamilyPlugin(Protocol):
    """Small registry-backed family seam. This is not a BaseBenchmark subclass."""

    benchmark_id: str
    public_class_name: str | None
    surface: str

    @property
    def core_class(self) -> type[Any]: ...

    def default_scale(self, scale_factor: float | None = None) -> float: ...

    def create(self, config: Any, system_profile: Any) -> Any: ...

    def phases(self) -> tuple[str, ...]: ...

    def result_metadata(self) -> dict[str, Any]: ...


_FAMILY_PLUGIN_REQUIRED_ATTRS = (
    "benchmark_id",
    "core_class",
    "public_class_name",
    "surface",
    "default_scale",
    "create",
    "phases",
    "result_metadata",
)

# Kept in the registry module rather than YAML: BenchmarkRegistryCatalog
# forbids unknown top-level keys, and this item cannot expand that schema.
FAMILY_PLUGIN_IMPORTS: dict[str, str] = {
    "ssb": "benchbox.core.ssb.family:SSBFamily",
}


@dataclass(frozen=True)
class _RegistryData:
    """Derived registry structures, built once from the YAML payload."""

    category_order: list[str]
    benchmark_order: dict[str, list[str]]
    benchmark_class_names: dict[str, str]
    core_benchmark_class_names: dict[str, str]
    benchmark_id_by_class_name: dict[str, str]
    data_source_probe_ids: tuple[str, ...]
    tpc_official_scale_options: tuple[float, ...]
    benchmark_metadata: dict[str, dict[str, Any]]
    family_plugin_imports: dict[str, str]


def _build_registry() -> _RegistryData:
    """Load, derive, and validate benchmark metadata once, on first access."""
    payload = _load_registry_payload()
    benchmark_class_names = dict(payload["benchmark_class_names"])
    core_class_name_overrides = dict(payload["core_class_name_overrides"])
    core_benchmark_class_names = {
        bid: core_class_name_overrides.get(bid, f"{name}Benchmark") for bid, name in benchmark_class_names.items()
    }
    benchmark_metadata = {
        benchmark_id: _normalize_benchmark_metadata(meta)
        for benchmark_id, meta in payload["benchmark_metadata"].items()
    }
    family_plugin_imports = dict(FAMILY_PLUGIN_IMPORTS)
    data = _RegistryData(
        category_order=list(payload["category_order"]),
        benchmark_order={category: list(benchmarks) for category, benchmarks in payload["benchmark_order"].items()},
        benchmark_class_names=benchmark_class_names,
        core_benchmark_class_names=core_benchmark_class_names,
        benchmark_id_by_class_name={
            **{class_name: benchmark_id for benchmark_id, class_name in benchmark_class_names.items()},
            **{class_name: benchmark_id for benchmark_id, class_name in core_benchmark_class_names.items()},
        },
        data_source_probe_ids=tuple(payload["data_source_probe_ids"]),
        tpc_official_scale_options=tuple(payload["tpc_official_scale_options"]),
        benchmark_metadata=benchmark_metadata,
        family_plugin_imports=family_plugin_imports,
    )
    _validate_registry(data.benchmark_metadata)
    _validate_family_plugins(set(data.benchmark_metadata), data.family_plugin_imports)
    return data


_registry = SingleFlightValueCache(_build_registry)

# Public module constants resolve to the lazily built, cached payload above via
# PEP 562 module __getattr__, so importers keep their names while the file I/O
# stays off the import path.
_PUBLIC_REGISTRY_ATTRS = {
    "CATEGORY_ORDER": "category_order",
    "BENCHMARK_ORDER": "benchmark_order",
    "BENCHMARK_CLASS_NAMES": "benchmark_class_names",
    "CORE_BENCHMARK_CLASS_NAMES": "core_benchmark_class_names",
    "BENCHMARK_DATA_SOURCE_PROBE_IDS": "data_source_probe_ids",
    "TPC_OFFICIAL_SCALE_OPTIONS": "tpc_official_scale_options",
    "BENCHMARK_METADATA": "benchmark_metadata",
}


def __getattr__(name: str) -> Any:
    attr = _PUBLIC_REGISTRY_ATTRS.get(name)
    if attr is not None:
        return getattr(_registry(), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _validate_benchmark_support_status(metadata: dict[str, dict[str, Any]]) -> None:
    missing = sorted(name for name, meta in metadata.items() if "support_status" not in meta)
    invalid = sorted(
        f"{name}={meta.get('support_status')!r}"
        for name, meta in metadata.items()
        if meta.get("support_status") not in BENCHMARK_SUPPORT_STATUS_VALUES
    )
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append(f"missing support_status for: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid support_status entries: {', '.join(invalid)}")
        raise ValueError("Invalid benchmark support_status metadata: " + "; ".join(details))


def _validate_benchmark_data_sources(metadata: dict[str, dict[str, Any]]) -> None:
    missing = sorted(name for name, meta in metadata.items() if "data_source" not in meta)
    invalid = sorted(
        f"{name}={meta.get('data_source')!r}"
        for name, meta in metadata.items()
        if meta.get("data_source") is not None and not isinstance(meta.get("data_source"), str)
    )
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append(f"missing data_source for: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid data_source entries: {', '.join(invalid)}")
        raise ValueError("Invalid benchmark data_source metadata: " + "; ".join(details))


def _validate_benchmark_estimate_metadata(metadata: dict[str, dict[str, Any]]) -> None:
    missing = sorted(
        name for name, meta in metadata.items() if "estimated_time_range" not in meta or "base_memory_gb" not in meta
    )
    invalid = sorted(
        name
        for name, meta in metadata.items()
        if (
            "estimated_time_range" in meta
            and "base_memory_gb" in meta
            and (
                not _is_valid_time_range(meta.get("estimated_time_range"))
                or not _is_valid_base_memory(meta.get("base_memory_gb"))
            )
        )
    )
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append(f"missing estimate metadata for: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid estimate metadata for: {', '.join(invalid)}")
        raise ValueError("Invalid benchmark estimate metadata: " + "; ".join(details))


def _is_valid_time_range(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, (int, float)) and item >= 0 for item in value)
        and float(value[0]) <= float(value[1])
    )


def _is_valid_base_memory(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _validate_family_plugins(benchmark_ids: set[str], family_plugins: dict[str, str]) -> None:
    """Reject plugin rows that do not name a registry benchmark or import spec."""
    unknown = sorted(plugin_id for plugin_id in family_plugins if plugin_id not in benchmark_ids)
    invalid = sorted(
        f"{plugin_id}={spec!r}" for plugin_id, spec in family_plugins.items() if not spec or ":" not in spec
    )
    if unknown or invalid:
        details: list[str] = []
        if unknown:
            details.append(f"unknown benchmark ids: {', '.join(unknown)}")
        if invalid:
            details.append(f"invalid import specs: {', '.join(invalid)}")
        raise ValueError("Invalid family_plugins metadata: " + "; ".join(details))


def _validate_registry(metadata: dict[str, dict[str, Any]]) -> None:
    """Run all metadata validations; called once from the cached loader."""
    _validate_benchmark_data_sources(metadata)
    _validate_benchmark_estimate_metadata(metadata)
    _validate_benchmark_support_status(metadata)


def get_all_benchmarks() -> dict[str, dict[str, Any]]:
    """Get metadata for all available benchmarks.

    Returns:
        Dictionary mapping benchmark IDs to their metadata.
    """
    return _registry().benchmark_metadata.copy()


def get_benchmark_metadata(benchmark_id: str) -> dict[str, Any] | None:
    """Get metadata for a specific benchmark.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Benchmark metadata dict, or None if not found.
    """
    return _registry().benchmark_metadata.get(benchmark_id.lower())


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
    return _registry().benchmark_class_names.get(benchmark_id.lower())


def get_core_benchmark_class_name(benchmark_id: str) -> str | None:
    """Get the class name for a benchmark in benchbox.core.<id>.benchmark.

    Args:
        benchmark_id: Benchmark identifier (e.g., 'tpch', 'tpcds')

    Returns:
        Core benchmark class name (e.g., 'TPCHBenchmark'), or None if not found.
    """
    return _registry().core_benchmark_class_names.get(benchmark_id.lower())


def get_benchmark_id_for_class_name(class_name: str) -> str | None:
    """Return the canonical benchmark ID for a public or core benchmark class."""
    return _registry().benchmark_id_by_class_name.get(class_name)


def get_public_benchmark_class(benchmark_id: str):
    """Get the public benchmark class from the benchbox module.

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


def get_benchmark_class(benchmark_id: str):
    """Compatibility alias for :func:`get_public_benchmark_class`."""
    return get_public_benchmark_class(benchmark_id)


def is_benchmark_available(benchmark_id: str) -> bool:
    """Check if a benchmark is available (can be imported).

    Args:
        benchmark_id: Benchmark identifier

    Returns:
        True if benchmark class can be imported.
    """
    return get_public_benchmark_class(benchmark_id) is not None


def list_benchmark_ids() -> list[str]:
    """Get list of all benchmark IDs.

    Returns:
        List of benchmark identifiers.
    """
    return list(_registry().benchmark_metadata.keys())


def list_public_benchmark_ids() -> list[str]:
    """Get benchmark IDs visible on public discovery surfaces."""
    return [bid for bid in list_benchmark_ids() if get_benchmark_surface(bid) == "public"]


def list_loader_benchmark_ids() -> list[str]:
    """Get benchmark IDs supported by the core benchmark loader.

    Returns:
        List of benchmark identifiers loadable via benchbox.core.benchmark_loader.
    """
    return list(_registry().core_benchmark_class_names.keys())


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
    metadata = _registry().benchmark_metadata
    return sorted(name for name, meta in metadata.items() if meta["support_status"] == status)


def get_benchmark_registry_summary() -> dict[str, Any]:
    """Return count summaries for benchmark contract and docs drift checks."""
    metadata = _registry().benchmark_metadata
    support_counts = Counter(cast(BenchmarkSupportStatus, meta["support_status"]) for meta in metadata.values())
    surface_counts = Counter(str(meta.get("surface", "public")) for meta in metadata.values())
    return {
        "total": len(metadata),
        "loader": len(list_loader_benchmark_ids()),
        "public": len(list_public_benchmark_ids()),
        "dataframe_supported": sum(1 for meta in metadata.values() if meta.get("supports_dataframe", False)),
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
    return {bid: meta for bid, meta in _registry().benchmark_metadata.items() if meta.get("category") == category}


def get_categories() -> list[str]:
    """Get list of all categories in display order.

    Returns:
        List of category names.
    """
    # Return categories that actually have benchmarks
    registry = _registry()
    categories_with_benchmarks = set()
    for meta in registry.benchmark_metadata.values():
        categories_with_benchmarks.add(meta.get("category", "Unknown"))

    # Return in preferred order, adding any extras at the end
    result = [c for c in registry.category_order if c in categories_with_benchmarks]
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
       ClickBench is the exception: its synthetic generator accepts any
       scale factor at or above ``min_scale``; its list is for common CLI
       choices, not an exhaustive restriction.
    3. Otherwise fall back to the legacy ``min_scale`` key, which only
       enforces a lower bound.

    Args:
        benchmark_id: The benchmark identifier (e.g., 'tpcds', 'tpch').
        scale_factor: The requested scale factor.

    Raises:
        ScaleFactorNotSupportedError: If the benchmark declares
            ``scale_options`` and ``scale_factor`` is not in that list.
        ValueError: If ``benchmark_id`` is unknown or the legacy ``min_scale``
            lower bound is violated (subclass-compatible —
            ``ScaleFactorNotSupportedError`` inherits from ``ValueError`` so
            existing handlers keep working).
    """
    from benchbox.core.errors import ScaleFactorNotSupportedError

    if benchmark_id == "tpcds":
        # TPC-DS uses the shared compliance classifier - not a simple min_scale check.
        from benchbox.core.tpcds.compliance import validate_tpcds_scale

        validate_tpcds_scale(scale_factor)
        return

    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        available = ", ".join(list_benchmark_ids())
        raise ValueError(f"Unknown benchmark '{benchmark_id}'. Available: {available}")

    if benchmark_id == "clickbench":
        try:
            sf = float(scale_factor)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"CLICKBENCH requires a finite scale_factor (got {scale_factor}).") from exc
        if not math.isfinite(sf):
            raise ValueError(f"CLICKBENCH requires a finite scale_factor (got {scale_factor}).")
        min_scale = meta.get("min_scale")
        if min_scale is not None and sf < min_scale:
            raise ValueError(f"{benchmark_id.upper()} requires scale_factor >= {min_scale} (got {scale_factor}).")
        return

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


def get_presort_table_configs(benchmark_id: str) -> dict[str, Any] | None:
    """Return a benchmark's default presort sort keys, or None.

    A benchmark supports `benchbox run --presort` exactly when it declares
    `presort_table_configs` in the registry. These lived as hardcoded column
    literals in benchbox/cli/commands/run.py; which column to sort on is
    benchmark knowledge, not CLI knowledge.
    """
    meta = get_benchmark_metadata(benchmark_id)
    if meta is None:
        return None
    configs = meta.get("presort_table_configs")
    return dict(configs) if configs else None


def presort_capable_benchmarks() -> tuple[str, ...]:
    """Return every benchmark id that declares presort defaults."""
    return tuple(
        sorted(bid for bid, meta in _registry().benchmark_metadata.items() if meta.get("presort_table_configs"))
    )


def list_family_plugin_ids() -> list[str]:
    """Return registry keys that declare a family plugin import spec."""
    return sorted(_registry().family_plugin_imports)


def get_family_plugin(benchmark_id: str) -> BenchmarkFamilyPlugin | None:
    """Load the registry-backed family plugin for *benchmark_id*, if declared.

    Plugin imports stay lazy so registry metadata load does not import family
    packages. A declared spec that cannot be imported or does not match the
    seam shape fails closed.
    """
    spec = _registry().family_plugin_imports.get(benchmark_id.lower())
    if spec is None:
        return None
    module_name, _, attr_name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
        raw = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"family plugin {spec!r} for {benchmark_id!r} could not be imported") from exc
    plugin = raw() if isinstance(raw, type) else raw
    missing = [name for name in _FAMILY_PLUGIN_REQUIRED_ATTRS if not hasattr(plugin, name)]
    if missing:
        raise ValueError(f"family plugin {spec!r} is missing: {', '.join(missing)}")
    plugin_id = str(plugin.benchmark_id)
    if plugin_id != benchmark_id.lower():
        raise ValueError(
            f"family plugin {spec!r} benchmark_id {plugin_id!r} does not match registry key {benchmark_id!r}"
        )
    return plugin


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


__all__ = sorted(
    list(_PUBLIC_REGISTRY_ATTRS)
    + [
        "BENCHMARK_SUPPORT_STATUS_VALUES",
        "BenchmarkFamilyPlugin",
        "BenchmarkSupportStatus",
        "FAMILY_PLUGIN_IMPORTS",
        "get_all_benchmarks",
        "get_family_plugin",
        "get_benchmark_class",
        "get_benchmark_class_name",
        "get_presort_table_configs",
        "presort_capable_benchmarks",
        "get_benchmark_default_scale",
        "get_benchmark_id_for_class_name",
        "get_benchmark_metadata",
        "get_benchmark_registry_summary",
        "get_benchmark_support_status",
        "get_benchmark_surface",
        "get_benchmarks_by_category",
        "get_benchmarks_by_support_status",
        "get_categories",
        "get_core_benchmark_class_name",
        "get_public_benchmark_class",
        "is_benchmark_available",
        "list_benchmark_ids",
        "list_family_plugin_ids",
        "list_loader_benchmark_ids",
        "list_public_benchmark_ids",
        "validate_scale_factor",
    ]
)
