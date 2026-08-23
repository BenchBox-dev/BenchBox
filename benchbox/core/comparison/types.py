"""Shared types for unified platform comparison.

Provides common types and enums used across both SQL and DataFrame
platform comparisons.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PlatformType(Enum):
    """Type of platform being compared."""

    SQL = "sql"
    DATAFRAME = "dataframe"
    AUTO = "auto"  # Auto-detect from platform names


class ComparisonMode(Enum):
    """Mode of comparison operation."""

    RUN = "run"  # Run benchmarks then compare
    FILES = "files"  # Compare existing result files


# Known SQL platforms for auto-detection
SQL_PLATFORMS = frozenset(
    {
        "duckdb",
        "sqlite",
        "postgresql",
        "postgres",
        "clickhouse",
        "snowflake",
        "bigquery",
        "redshift",
        "databricks",
        "athena",
        "trino",
        "presto",
        "firebolt",
        "fabric_warehouse",
        "azure_synapse",
        "datafusion",  # SQL mode
    }
)

# Known DataFrame platforms (end with -df suffix)
DATAFRAME_PLATFORM_SUFFIX = "-df"


def detect_platform_type(platform_name: str) -> PlatformType:
    """Detect whether a platform is SQL or DataFrame.

    Args:
        platform_name: Platform identifier

    Returns:
        PlatformType.SQL or PlatformType.DATAFRAME
    """
    if platform_name.endswith(DATAFRAME_PLATFORM_SUFFIX):
        return PlatformType.DATAFRAME
    if platform_name.lower() in SQL_PLATFORMS:
        return PlatformType.SQL
    # Default to SQL for unknown platforms
    return PlatformType.SQL


def detect_platform_types(platforms: list[str]) -> tuple[PlatformType, list[str]]:
    """Detect platform types for a list of platforms.

    Args:
        platforms: List of platform names

    Returns:
        Tuple of (detected_type, list of inconsistent platforms)

    Raises:
        ValueError: If platforms have mixed types
    """
    if not platforms:
        return PlatformType.SQL, []

    types = {p: detect_platform_type(p) for p in platforms}
    unique_types = set(types.values())

    if len(unique_types) == 1:
        return list(unique_types)[0], []

    # Mixed types - identify which platforms are inconsistent
    sql_platforms = [p for p, t in types.items() if t == PlatformType.SQL]
    df_platforms = [p for p, t in types.items() if t == PlatformType.DATAFRAME]

    # Return the majority type and list minorities as inconsistent
    if len(sql_platforms) >= len(df_platforms):
        return PlatformType.SQL, df_platforms
    else:
        return PlatformType.DATAFRAME, sql_platforms


@dataclass
class UnifiedBenchmarkConfig:
    """Configuration for unified benchmark comparisons.

    Works for both SQL and DataFrame platform comparisons.

    Attributes:
        platform_type: Type of platforms (sql, dataframe, auto)
        scale_factor: Benchmark scale factor
        benchmark: Benchmark name (tpch, tpcds, ssb, clickbench)
        query_ids: Optional list of specific queries to run
        warmup_iterations: Warmup iterations before measurement
        benchmark_iterations: Number of measured iterations
        parallel: Run platforms in parallel
        track_memory: Track memory usage (DataFrame only)
        timeout_seconds: Per-query timeout
    """

    platform_type: PlatformType = PlatformType.AUTO
    scale_factor: float = 0.01
    benchmark: str = "tpch"
    query_ids: list[str] | None = None
    warmup_iterations: int = 1
    benchmark_iterations: int = 3
    parallel: bool = False
    track_memory: bool = True
    timeout_seconds: float = 300.0


@dataclass
class UnifiedQueryResult:
    """Result of benchmarking a single query.

    Common structure for both SQL and DataFrame results.

    Attributes:
        query_id: Query identifier
        platform: Platform name
        platform_type: SQL or DataFrame
        iterations: Number of successful iterations
        execution_times_ms: List of execution times
        mean_time_ms: Mean execution time
        std_time_ms: Standard deviation
        min_time_ms: Minimum time
        max_time_ms: Maximum time
        memory_peak_mb: Peak memory usage (if tracked)
        rows_returned: Number of rows returned
        status: SUCCESS or ERROR
        error_message: Error details if failed
    """

    query_id: str
    platform: str
    platform_type: PlatformType
    iterations: int = 0
    execution_times_ms: list[float] = field(default_factory=list)
    mean_time_ms: float = 0.0
    std_time_ms: float = 0.0
    min_time_ms: float = 0.0
    max_time_ms: float = 0.0
    memory_peak_mb: float = 0.0
    rows_returned: int = 0
    status: str = "SUCCESS"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "platform": self.platform,
            "platform_type": self.platform_type.value,
            "iterations": self.iterations,
            "execution_times_ms": self.execution_times_ms,
            "mean_time_ms": self.mean_time_ms,
            "std_time_ms": self.std_time_ms,
            "min_time_ms": self.min_time_ms,
            "max_time_ms": self.max_time_ms,
            "memory_peak_mb": self.memory_peak_mb,
            "rows_returned": self.rows_returned,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class UnifiedPlatformResult:
    """Aggregate results for a platform across all queries.

    Attributes:
        platform: Platform name
        platform_type: SQL or DataFrame
        query_results: Results for each query
        total_time_ms: Total execution time
        geometric_mean_ms: Geometric mean of query times
        success_rate: Percentage of successful queries. Defaults to 0.0: a
            result that has not been aggregated by
            ``UnifiedBenchmarkSuite._build_platform_result`` has not
            demonstrated any successful query, and defaulting to 100.0
            let failed platforms report full success.
    """

    platform: str
    platform_type: PlatformType
    query_results: list[UnifiedQueryResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    geometric_mean_ms: float = 0.0
    success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "platform": self.platform,
            "platform_type": self.platform_type.value,
            "query_results": [r.to_dict() for r in self.query_results],
            "total_time_ms": self.total_time_ms,
            "geometric_mean_ms": self.geometric_mean_ms,
            "success_rate": self.success_rate,
        }


@dataclass
class UnifiedComparisonSummary:
    """Summary of cross-platform comparison.

    Attributes:
        platforms: List of compared platforms
        platform_type: Type of platforms compared
        fastest_platform: Platform with best performance, or None when no
            platform produced a usable timing
        slowest_platform: Platform with worst performance, or None when no
            platform produced a usable timing
        speedup_ratio: How much faster the fastest is vs slowest, or None
            when there is nothing to compare
        query_winners: Best platform per query
        total_queries: Number of queries compared
    """

    platforms: list[str]
    platform_type: PlatformType
    fastest_platform: str | None
    slowest_platform: str | None
    speedup_ratio: float | None
    query_winners: dict[str, str]
    total_queries: int

    @property
    def is_comparable(self) -> bool:
        """True when at least one platform produced a usable timing.

        When no platform timed a query there is nothing to rank, and
        ``fastest_platform`` / ``slowest_platform`` / ``speedup_ratio`` are
        ``None`` rather than a fabricated self-comparison.
        """
        return self.fastest_platform is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "platforms": self.platforms,
            "platform_type": self.platform_type.value,
            "fastest_platform": self.fastest_platform,
            "slowest_platform": self.slowest_platform,
            "speedup_ratio": self.speedup_ratio,
            "query_winners": self.query_winners,
            "total_queries": self.total_queries,
        }


__all__ = [
    "PlatformType",
    "ComparisonMode",
    "SQL_PLATFORMS",
    "DATAFRAME_PLATFORM_SUFFIX",
    "detect_platform_type",
    "detect_platform_types",
    "UnifiedBenchmarkConfig",
    "UnifiedQueryResult",
    "UnifiedPlatformResult",
    "UnifiedComparisonSummary",
]
