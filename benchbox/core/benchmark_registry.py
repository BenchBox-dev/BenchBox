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
from typing import Any, Literal, cast

BenchmarkSupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]

BENCHMARK_SUPPORT_STATUS_VALUES: tuple[BenchmarkSupportStatus, ...] = (
    "stable",
    "beta",
    "experimental",
    "repo_only",
    "deprecated",
    "document_only",
)

# Category ordering for display (most popular first)
CATEGORY_ORDER = ["TPC", "Primitives", "Industry", "Academic", "Time Series", "Real World", "AI/ML", "Experimental"]

# Benchmark ordering within categories (most popular first)
BENCHMARK_ORDER = {
    "TPC": ["tpch", "tpcds", "tpcdi"],
    "Primitives": [
        "read_primitives",
        "write_primitives",
        "transaction_primitives",
        "metadata_primitives",
        "ai_primitives",
    ],
    "Industry": ["clickbench", "h2odb", "coffeeshop"],
    "Academic": ["ssb", "joinorder", "joinorder_synthetic", "amplab"],
    "Time Series": ["tsbs_devops"],
    "Real World": ["nyctaxi", "flightdata"],
    "AI/ML": ["vector_search"],
    "Experimental": ["tpch_skew", "tpchavoc", "tpcds_obt", "datavault"],
}

# Mapping of benchmark IDs to their class names in the benchbox module
# Used for lazy loading via getattr(benchbox, class_name)
BENCHMARK_CLASS_NAMES: dict[str, str] = {
    "tpch": "TPCH",
    "tpcds": "TPCDS",
    "tpcdi": "TPCDI",
    "ssb": "SSB",
    "clickbench": "ClickBench",
    "h2odb": "H2ODB",
    "amplab": "AMPLab",
    "read_primitives": "ReadPrimitives",
    "write_primitives": "WritePrimitives",
    "metadata_primitives": "MetadataPrimitives",
    "ai_primitives": "AIPrimitives",
    "transaction_primitives": "TransactionPrimitives",
    "joinorder": "JoinOrder",
    "joinorder_synthetic": "JoinOrderSynthetic",
    "coffeeshop": "CoffeeShop",
    "tpchavoc": "TPCHavoc",
    "tpch_skew": "TPCHSkew",
    "tsbs_devops": "TSBSDevOps",
    "nyctaxi": "NYCTaxi",
    "flightdata": "FlightData",
    "datavault": "DataVault",
    "tpcds_obt": "TPCDSOBT",
    "vector_search": "VectorSearch",
}

# Concrete class names in benchbox.core.<id>.benchmark, derived from BENCHMARK_CLASS_NAMES.
# `benchbox.core.benchmark_loader` imports this map to avoid local benchmark-set drift.
# Override individual entries where the core class name doesn't follow the {wrapper}Benchmark pattern.
_CORE_CLASS_NAME_OVERRIDES: dict[str, str] = {
    "h2odb": "H2OBenchmark",  # core class is H2OBenchmark, not H2ODBBenchmark
    "vector_search": "VectorSearchBenchmark",  # core class name differs from wrapper
}
CORE_BENCHMARK_CLASS_NAMES: dict[str, str] = {
    bid: _CORE_CLASS_NAME_OVERRIDES.get(bid, f"{name}Benchmark") for bid, name in BENCHMARK_CLASS_NAMES.items()
}
_BENCHMARK_ID_BY_CLASS_NAME: dict[str, str] = {
    **{class_name: benchmark_id for benchmark_id, class_name in BENCHMARK_CLASS_NAMES.items()},
    **{class_name: benchmark_id for benchmark_id, class_name in CORE_BENCHMARK_CLASS_NAMES.items()},
}

# Benchmarks with runtime data-sharing declarations. The registry imports only
# this narrow set during metadata normalization to avoid eager-loading every
# benchmark at discovery time.
BENCHMARK_DATA_SOURCE_PROBE_IDS: tuple[str, ...] = (
    "read_primitives",
    "write_primitives",
    "transaction_primitives",
    "ai_primitives",
    "tpcds_obt",
)

TPC_OFFICIAL_SCALE_OPTIONS: tuple[float, ...] = (
    1.0,
    10.0,
    30.0,
    100.0,
    300.0,
    1000.0,
    3000.0,
    10000.0,
    30000.0,
    100000.0,
)


# Complete benchmark metadata - the single source of truth
# All metadata fields are documented here for consistency
BENCHMARK_METADATA: dict[str, dict[str, Any]] = {
    "tpch": {
        "display_name": "TPC-H",
        "description": "Decision Support Benchmark",
        "category": "TPC",
        "support_status": "stable",
        "num_queries": 22,
        "query_description": "22 analytical queries",
        "supports_streams": True,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, *TPC_OFFICIAL_SCALE_OPTIONS],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (2, 10),  # minutes
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "tpcds": {
        "display_name": "TPC-DS",
        "description": "Decision Support Benchmark",
        "category": "TPC",
        "support_status": "stable",
        "num_queries": 99,
        "query_description": "99 analytical queries",
        "supports_streams": True,
        "default_scale": 1.0,
        "scale_options": [0.01, 0.1, 1.0, 10.0, 100.0],
        # No min_scale here - TPC-DS scale validation is handled by the compliance
        # classifier in benchbox/core/tpcds/compliance.py. Sub-SF1 scales are allowed
        # for development use, but remain unofficial.
        "complexity": "High",
        "estimated_time_range": (10, 60),
        "base_memory_gb": 2.5,
        "data_source": None,
        "supports_dataframe": True,
    },
    "tpcds_obt": {
        "display_name": "TPC-DS-OBT",
        "description": "Single-table TPC-DS (One Big Table) benchmark",
        "category": "Experimental",
        "support_status": "experimental",
        "num_queries": 17,
        "query_description": "OBT-adapted analytical queries",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [1.0],
        "min_scale": 1.0,
        "complexity": "Medium",
        "estimated_time_range": (5, 20),
        "base_memory_gb": 2.5,
        "data_source": "tpcds",
        "supports_dataframe": True,
    },
    "tpcdi": {
        "display_name": "TPC-DI",
        "description": "Data Integration Benchmark",
        "category": "TPC",
        "support_status": "beta",
        "num_queries": 38,  # ETL operations
        "query_description": "ETL Pipeline",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "High",
        "estimated_time_range": (5, 30),
        "base_memory_gb": 1.5,
        "data_source": None,
        "supports_dataframe": True,
    },
    "ssb": {
        "display_name": "SSB",
        "description": "Star Schema Benchmark",
        "category": "Academic",
        "support_status": "stable",
        "num_queries": 13,
        "query_description": "13 queries",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "Low",
        "estimated_time_range": (1, 5),
        "base_memory_gb": 0.8,
        "data_source": None,
        "supports_dataframe": True,
    },
    "clickbench": {
        "display_name": "ClickBench",
        "description": "Analytics benchmark",
        "category": "Industry",
        "support_status": "stable",
        "num_queries": 43,
        "query_description": "43 queries",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [1.0],
        "min_scale": 1.0,
        "complexity": "Medium",
        "estimated_time_range": (5, 15),
        "base_memory_gb": 15.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "h2odb": {
        "display_name": "H2ODB",
        "description": "Data science benchmark",
        "category": "Industry",
        "support_status": "beta",
        "num_queries": 10,
        "query_description": "Multiple ML workloads",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (3, 15),
        "base_memory_gb": 2.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "amplab": {
        "display_name": "AMPLab",
        "description": "Big data benchmark suite",
        "category": "Academic",
        "support_status": "beta",
        "num_queries": 8,
        "query_description": "Multiple workloads",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (3, 15),
        "base_memory_gb": 1.2,
        "data_source": None,
        "supports_dataframe": True,
    },
    "read_primitives": {
        "display_name": "Read Primitives",
        "description": "Read operation benchmarks testing SELECT queries",
        "category": "Primitives",
        "support_status": "beta",
        "num_queries": 136,
        "query_description": "Multiple read test queries",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1],
        "min_scale": 0.01,
        "complexity": "Low",
        "estimated_time_range": (1, 3),
        "base_memory_gb": 0.1,
        "data_source": "tpch",
        "supports_dataframe": True,
    },
    "write_primitives": {
        "display_name": "Write Primitives",
        "description": "Database write operations benchmark",
        "category": "Primitives",
        "support_status": "beta",
        "num_queries": 12,
        "query_description": "12 write operations (INSERT, UPDATE, DELETE, BULK_LOAD, MERGE, DDL, TRANSACTION)",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (2, 5),
        "base_memory_gb": 1.0,
        "data_source": "tpch",
        "supports_dataframe": True,
    },
    "metadata_primitives": {
        "display_name": "Metadata",
        "description": "Database catalog introspection benchmark",
        "category": "Primitives",
        "support_status": "beta",
        "num_queries": 62,
        "query_description": "62 catalog queries in the full SQL catalog; DataFrame mode runs platform-specific metadata operation subsets",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [1.0],
        "min_scale": 1.0,
        "complexity": "Low",
        "estimated_time_range": (1, 2),
        "base_memory_gb": 0.01,
        "data_source": None,
        "supports_dataframe": True,
    },
    "transaction_primitives": {
        "display_name": "Transactions",
        "description": "ACID transaction testing benchmark",
        "category": "Primitives",
        "support_status": "beta",
        "num_queries": 12,
        "query_description": "12 transaction operations",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (2, 5),
        "base_memory_gb": 1.0,
        "data_source": "tpch",
        "supports_dataframe": True,
    },
    "ai_primitives": {
        "display_name": "AI Primitives",
        "description": "AI/ML function benchmarks (Snowflake Cortex, BigQuery ML, Databricks AI)",
        "category": "Primitives",
        "support_status": "experimental",
        "num_queries": 16,
        "query_description": "16 AI/ML function queries",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (3, 15),
        "base_memory_gb": 1.0,
        "data_source": "tpch",
        "supports_dataframe": False,
    },
    "joinorder": {
        "display_name": "JoinOrder",
        "description": "Canonical IMDb 2013 Join Order Benchmark",
        "category": "Academic",
        "support_status": "stable",
        "num_queries": 113,
        "query_description": "113 queries",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [1.0],
        "min_scale": 1.0,
        "complexity": "High",
        "estimated_time_range": (30, 90),
        "base_memory_gb": 5.0,
        "supports_dataframe": True,
        "surface": "public",
        "data_source": "canonical",
        "data_manifest": "benchbox/core/joinorder/data_manifest.toml",
    },
    "joinorder_synthetic": {
        "display_name": "JoinOrder Synthetic",
        "description": "Uniformly-random Join Order schema smoke-test data",
        "category": "Academic",
        "support_status": "repo_only",
        "num_queries": 13,
        "query_description": "13 synthetic smoke queries",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [0.001, 0.01, 0.1, 0.5, 1.0, 2.0],
        "min_scale": 0.001,
        "complexity": "Medium",
        "estimated_time_range": (2, 10),
        "base_memory_gb": 1.0,
        "supports_dataframe": True,
        "surface": "internal",
        "data_source": "synthetic",
    },
    "coffeeshop": {
        "display_name": "CoffeeShop",
        "description": "Order line benchmark with regional weighting",
        "category": "Industry",
        "support_status": "beta",
        "num_queries": 11,
        "query_description": "11 analytics queries",
        "supports_streams": False,
        "default_scale": 0.001,
        "scale_options": [0.001, 0.01, 0.1, 1.0],
        "min_scale": 0.001,
        "complexity": "Medium",
        "estimated_time_range": (3, 12),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "tpchavoc": {
        "display_name": "TPC-Havoc",
        "description": "TPC-H syntax variants for optimizer testing",
        "category": "Experimental",
        "support_status": "experimental",
        "num_queries": 220,
        "query_description": "220 query variants (22 queries x 10 variants)",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "High",
        "estimated_time_range": (15, 60),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "tpch_skew": {
        "display_name": "TPC-H Skew",
        "description": "TPC-H with configurable data skew distributions",
        "category": "Experimental",
        "support_status": "experimental",
        "num_queries": 22,
        "query_description": "22 TPC-H queries on skewed data (Zipfian, normal, exponential)",
        "supports_streams": True,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (2, 15),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "tsbs_devops": {
        "display_name": "TSBS DevOps",
        "description": "Time Series Benchmark Suite for DevOps monitoring",
        "category": "Time Series",
        "support_status": "beta",
        "num_queries": 18,
        "query_description": "18 time-series queries (CPU, memory, disk, network)",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (2, 10),
        "base_memory_gb": 0.8,
        "data_source": None,
        "supports_dataframe": True,
    },
    "nyctaxi": {
        "display_name": "NYC Taxi",
        "description": "NYC TLC trip data for OLAP analytics",
        "category": "Real World",
        "support_status": "beta",
        "num_queries": 25,
        "query_description": "25 OLAP queries (temporal, geographic, financial)",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [0.01, 0.1, 1.0, 10.0, 100.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (5, 30),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "flightdata": {
        "display_name": "Flight Data",
        "description": "US BTS On-Time Performance data for aviation analytics",
        "category": "Real World",
        "support_status": "beta",
        "num_queries": 20,
        "query_description": "20 OLAP queries (on-time, delays, routes, temporal, carriers)",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [0.01, 0.1, 1.0, 10.0, 100.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (5, 30),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "datavault": {
        "display_name": "TPC-H Data Vault",
        "description": "TPC-H adapted for Data Vault 2.0 modeling",
        "category": "Experimental",
        "support_status": "experimental",
        "num_queries": 22,
        "query_description": "22 analytical queries (TPC-H adapted for Hub-Link-Satellite model)",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0],
        "min_scale": 0.01,
        "complexity": "High",
        "estimated_time_range": (5, 30),
        "base_memory_gb": 3.0,
        "data_source": None,
        "supports_dataframe": True,
    },
    "vector_search": {
        "display_name": "Vector Search",
        "description": "Vector similarity search benchmark (kNN, ANN, filtered)",
        "category": "AI/ML",
        "support_status": "beta",
        "num_queries": 6,
        "query_description": "6 queries (kNN cosine/L2, filtered, recall@k, ANN, multi-category)",
        "supports_streams": False,
        "default_scale": 0.01,
        "scale_options": [0.01, 0.1, 1.0, 10.0, 100.0],
        "min_scale": 0.01,
        "complexity": "Medium",
        "estimated_time_range": (1, 10),
        "base_memory_gb": 1.0,
        "data_source": None,
        "supports_dataframe": False,
    },
}


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


def _validate_benchmark_estimate_metadata() -> None:
    missing = sorted(
        name
        for name, meta in BENCHMARK_METADATA.items()
        if "estimated_time_range" not in meta or "base_memory_gb" not in meta
    )
    invalid = sorted(
        name
        for name, meta in BENCHMARK_METADATA.items()
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


_validate_benchmark_data_sources()
_validate_benchmark_estimate_metadata()
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


def get_benchmark_id_for_class_name(class_name: str) -> str | None:
    """Return the canonical benchmark ID for a public or core benchmark class."""
    return _BENCHMARK_ID_BY_CLASS_NAME.get(class_name)


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
