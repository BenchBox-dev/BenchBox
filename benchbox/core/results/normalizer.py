"""Result normalization for multi-schema support.

This module provides a unified interface for extracting data from benchmark
result JSON files, supporting both legacy v1.x and current v2.x schemas.

All modules that need to read result JSON should use these utilities rather
than implementing their own schema detection and field extraction.

Schema Differences:
    v1.x Schema:
        - results.timing.total_ms, results.timing.avg_ms
        - results.queries.details[] with execution_time_ms, query_id
        - execution.platform, execution.timestamp, execution.id
        - cost_summary or results.cost_summary

    v2.x Schema (2.0, 2.1):
        - summary.timing.total_ms, summary.timing.avg_ms
        - queries[] (top-level) with ms, id fields
        - platform.name, run.timestamp, run.id
        - cost.total_cost (note: different key)

Usage:
    >>> from benchbox.core.results.normalizer import normalize_result_dict
    >>> with open("result.json") as f:
    ...     data = json.load(f)
    >>> normalized = normalize_result_dict(data)
    >>> emit(normalized.total_time_ms, normalized.platform)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedQuery:
    """Normalized representation of a single query result."""

    query_id: str
    execution_time_ms: float | None = None
    rows_returned: int | None = None
    status: str = "UNKNOWN"


@dataclass
class NormalizedResultDict:
    """Normalized representation of benchmark result data.

    This dataclass provides a schema-agnostic view of benchmark results,
    allowing consuming code to work with a consistent interface regardless
    of whether the source JSON uses v1.x or v2.x schema.

    Attributes:
        schema_version: Detected schema version ("1.x", "2.0", "2.1")
        benchmark: Benchmark name (e.g., "TPC-H", "TPC-DS")
        benchmark_id: Benchmark identifier (e.g., "tpch", "tpcds")
        platform: Platform name (e.g., "DuckDB", "Snowflake")
        scale_factor: Scale factor as string or number
        execution_id: Unique run identifier
        timestamp: Run timestamp (parsed datetime or None)
        execution_mode: Execution mode (e.g., "sql", "dataframe")
        total_time_ms: Total query execution time in milliseconds
        avg_time_ms: Average query time in milliseconds
        min_time_ms: Minimum query time in milliseconds
        max_time_ms: Maximum query time in milliseconds
        total_queries: Total number of queries
        passed_queries: Number of successful queries
        failed_queries: Number of failed queries
        success_rate: Success rate (0.0 to 1.0)
        cost_total: Total cost in USD (if available)
        queries: List of per-query results
        raw: Original unmodified JSON data
    """

    # Schema info
    schema_version: str

    # Core identification
    benchmark: str
    benchmark_id: str
    platform: str
    scale_factor: str | float | int

    # Run metadata
    execution_id: str | None
    timestamp: datetime | None
    execution_mode: str | None

    # Timing metrics
    total_time_ms: float | None
    avg_time_ms: float | None
    min_time_ms: float | None = None
    max_time_ms: float | None = None

    # Query counts
    total_queries: int = 0
    passed_queries: int = 0
    failed_queries: int = 0
    success_rate: float | None = None

    # Cost
    cost_total: float | None = None

    # Per-query details
    queries: list[NormalizedQuery] = field(default_factory=list)

    # Methodology/comparability classification (e.g., "official", "unofficial_subscale")
    compliance_class: str | None = None

    # Original data (for fields not normalized)
    raw: dict[str, Any] = field(default_factory=dict)


def detect_schema_version(data: dict[str, Any]) -> str:
    """Detect the schema version of a result JSON.

    Args:
        data: Result JSON as a dictionary

    Returns:
        Schema version string: "2.0", "2.1", or "1.x"
    """
    version = data.get("version") or data.get("schema_version", "")
    if version in ("2.0", "2.1"):
        return version
    return "1.x"


def normalize_result_dict(data: dict[str, Any]) -> NormalizedResultDict:
    """Normalize a benchmark result JSON to a consistent format.

    This function extracts commonly needed fields from benchmark result JSON,
    handling differences between v1.x and v2.x schemas transparently.

    Args:
        data: Result JSON as a dictionary

    Returns:
        NormalizedResultDict with extracted fields

    Example:
        >>> data = json.load(open("result.json"))
        >>> result = normalize_result_dict(data)
        >>> emit(f"{result.platform}: {result.total_time_ms}ms")
    """
    schema_version = detect_schema_version(data)
    is_v2 = schema_version in ("2.0", "2.1")

    # Common blocks present in both schemas
    benchmark_block = data.get("benchmark", {}) or {}
    config_block = data.get("config", {}) or {}
    platform_block = data.get("platform", {}) or {}

    if is_v2:
        return _normalize_v2(data, schema_version, benchmark_block, config_block, platform_block)
    else:
        return _normalize_v1(data, schema_version, benchmark_block, config_block, platform_block)


def _normalize_v2(
    data: dict[str, Any],
    schema_version: str,
    benchmark_block: dict[str, Any],
    config_block: dict[str, Any],
    platform_block: dict[str, Any],
) -> NormalizedResultDict:
    """Normalize v2.x schema result."""
    run_block = data.get("run", {}) or {}
    summary_block = data.get("summary", {}) or {}
    timing_block = summary_block.get("timing", {}) or {}
    queries_summary = summary_block.get("queries", {}) or {}
    cost_block = data.get("cost", {}) or {}

    # Core identification
    benchmark = benchmark_block.get("name") or benchmark_block.get("id") or "unknown"
    benchmark_id = benchmark_block.get("id") or ""
    platform = platform_block.get("name", "unknown")
    scale_factor = benchmark_block.get("scale_factor") or "unknown"

    # Run metadata
    execution_id = run_block.get("id")
    timestamp = _parse_timestamp(run_block.get("timestamp"))
    execution_mode = (
        config_block.get("mode")
        or config_block.get("execution_mode")
        or (platform_block.get("config") or {}).get("execution_mode")
    )

    # Timing metrics
    total_time_ms = timing_block.get("total_ms")
    avg_time_ms = timing_block.get("avg_ms")
    min_time_ms = timing_block.get("min_ms")
    max_time_ms = timing_block.get("max_ms")

    # Query counts
    total_queries = queries_summary.get("total", 0)
    passed_queries = queries_summary.get("passed", 0)
    failed_queries = queries_summary.get("failed", 0)
    success_rate = (passed_queries / total_queries) if total_queries > 0 else None

    # Cost
    cost_total = cost_block.get("total_usd") or cost_block.get("total_cost")

    # Per-query details (v2.x uses top-level "queries" list with "id" and "ms")
    queries = []
    for q in data.get("queries", []) or []:
        queries.append(
            NormalizedQuery(
                query_id=q.get("id") or "unknown",
                execution_time_ms=q.get("ms"),
                rows_returned=q.get("rows"),
                status=q.get("status", "UNKNOWN"),
            )
        )

    return NormalizedResultDict(
        schema_version=schema_version,
        benchmark=str(benchmark),
        benchmark_id=str(benchmark_id),
        platform=str(platform),
        scale_factor=scale_factor,
        execution_id=execution_id,
        timestamp=timestamp,
        execution_mode=execution_mode,
        total_time_ms=total_time_ms,
        avg_time_ms=avg_time_ms,
        min_time_ms=min_time_ms,
        max_time_ms=max_time_ms,
        total_queries=total_queries,
        passed_queries=passed_queries,
        failed_queries=failed_queries,
        success_rate=success_rate,
        cost_total=cost_total,
        queries=queries,
        compliance_class=benchmark_block.get("compliance_class"),
        raw=data,
    )


def _normalize_v1(
    data: dict[str, Any],
    schema_version: str,
    benchmark_block: dict[str, Any],
    config_block: dict[str, Any],
    platform_block: dict[str, Any],
) -> NormalizedResultDict:
    """Normalize v1.x schema result."""
    execution_block = data.get("execution", {}) or {}
    results_block = data.get("results", {}) or {}
    queries_block = results_block.get("queries", {}) or {}
    timing_block = results_block.get("timing", {}) or {}
    cost_block = data.get("cost_summary") or results_block.get("cost_summary") or {}

    # Core identification
    benchmark = benchmark_block.get("name") or benchmark_block.get("id") or "unknown"
    benchmark_id = benchmark_block.get("id") or ""
    platform = execution_block.get("platform") or platform_block.get("name", "unknown")
    scale_factor = benchmark_block.get("scale_factor") or "unknown"

    # Run metadata
    execution_id = execution_block.get("id") or execution_block.get("execution_id")
    timestamp = _parse_timestamp(execution_block.get("timestamp"))
    execution_mode = (
        config_block.get("mode")
        or config_block.get("execution_mode")
        or (platform_block.get("config") or {}).get("execution_mode")
    )

    # Timing metrics
    total_time_ms = timing_block.get("total_ms")
    avg_time_ms = timing_block.get("avg_ms")
    min_time_ms = timing_block.get("min_ms")
    max_time_ms = timing_block.get("max_ms")

    # Query counts
    total_queries = queries_block.get("total", 0) if isinstance(queries_block, dict) else 0
    passed_queries = queries_block.get("successful", 0) if isinstance(queries_block, dict) else 0
    failed_queries = queries_block.get("failed", 0) if isinstance(queries_block, dict) else 0
    success_rate = queries_block.get("success_rate") if isinstance(queries_block, dict) else None

    # Cost
    cost_total = cost_block.get("total_cost") if isinstance(cost_block, dict) else None

    # Per-query details (v1.x uses results.queries.details with query_id and execution_time_ms)
    queries = []
    details = queries_block.get("details", []) if isinstance(queries_block, dict) else []
    for q in details or []:
        queries.append(
            NormalizedQuery(
                query_id=q.get("id") or q.get("query_id") or "unknown",
                execution_time_ms=q.get("execution_time_ms"),
                rows_returned=q.get("rows_returned"),
                status=q.get("status", "UNKNOWN"),
            )
        )

    return NormalizedResultDict(
        schema_version=schema_version,
        benchmark=str(benchmark),
        benchmark_id=str(benchmark_id),
        platform=str(platform),
        scale_factor=scale_factor,
        execution_id=execution_id,
        timestamp=timestamp,
        execution_mode=execution_mode,
        total_time_ms=total_time_ms,
        avg_time_ms=avg_time_ms,
        min_time_ms=min_time_ms,
        max_time_ms=max_time_ms,
        total_queries=total_queries,
        passed_queries=passed_queries,
        failed_queries=failed_queries,
        success_rate=success_rate,
        cost_total=cost_total,
        queries=queries,
        raw=data,
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO timestamp string to datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_query_map(normalized: NormalizedResultDict) -> dict[str, NormalizedQuery]:
    """Get a mapping of query ID to query result.

    Args:
        normalized: Normalized result dict

    Returns:
        Dictionary mapping query_id to NormalizedQuery
    """
    return {q.query_id: q for q in normalized.queries}


__all__ = [
    "NormalizedQuery",
    "NormalizedResultDict",
    "detect_schema_version",
    "normalize_result_dict",
    "get_query_map",
]
