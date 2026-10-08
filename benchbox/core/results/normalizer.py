from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from benchbox.core.cost.models import published_total_cost
from benchbox.core.results.schema_policy import KNOWN_SCHEMA_V2_VERSIONS, detect_normalizer_schema_version


@dataclass
class NormalizedQuery:
    query_id: str
    execution_time_ms: float | None = None
    rows_returned: int | None = None
    status: str = "UNKNOWN"


@dataclass
class NormalizedResultDict:
    schema_version: str

    benchmark: str
    benchmark_id: str
    platform: str
    scale_factor: str | float | int

    execution_id: str | None
    timestamp: datetime | None
    execution_mode: str | None

    total_time_ms: float | None
    avg_time_ms: float | None
    min_time_ms: float | None = None
    max_time_ms: float | None = None

    total_queries: int = 0
    passed_queries: int = 0
    failed_queries: int = 0
    success_rate: float | None = None

    cost_total: float | None = None

    queries: list[NormalizedQuery] = field(default_factory=list)

    compliance_class: str | None = None

    raw: dict[str, Any] = field(default_factory=dict)


def detect_schema_version(data: dict[str, Any]) -> str:
    return detect_normalizer_schema_version(data)


def normalize_result_dict(data: dict[str, Any]) -> NormalizedResultDict:
    schema_version = detect_schema_version(data)
    is_v2 = schema_version in KNOWN_SCHEMA_V2_VERSIONS

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
    run_block = data.get("run", {}) or {}
    summary_block = data.get("summary", {}) or {}
    timing_block = summary_block.get("timing", {}) or {}
    queries_summary = summary_block.get("queries", {}) or {}
    cost_block = data.get("cost", {}) or {}

    benchmark = benchmark_block.get("name") or benchmark_block.get("id") or "unknown"
    benchmark_id = benchmark_block.get("id") or ""
    platform = platform_block.get("name", "unknown")
    scale_factor = benchmark_block.get("scale_factor") or "unknown"

    execution_id = run_block.get("id")
    timestamp = _parse_timestamp(run_block.get("timestamp"))
    execution_mode = (
        config_block.get("mode")
        or config_block.get("execution_mode")
        or (platform_block.get("config") or {}).get("execution_mode")
    )

    total_time_ms = timing_block.get("total_ms")
    avg_time_ms = timing_block.get("avg_ms")
    min_time_ms = timing_block.get("min_ms")
    max_time_ms = timing_block.get("max_ms")

    total_queries = queries_summary.get("total", 0)
    passed_queries = queries_summary.get("passed", 0)
    failed_queries = queries_summary.get("failed", 0)
    success_rate = (passed_queries / total_queries) if total_queries > 0 else None

    raw_total = cost_block.get("total_usd") or cost_block.get("total_cost")
    cost_total = published_total_cost({"total_cost": raw_total, "normalized_cost": data.get("normalized_cost")})

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
    execution_block = data.get("execution", {}) or {}
    results_block = data.get("results", {}) or {}
    queries_block = results_block.get("queries", {}) or {}
    timing_block = results_block.get("timing", {}) or {}
    cost_block = data.get("cost_summary") or results_block.get("cost_summary") or {}

    benchmark = benchmark_block.get("name") or benchmark_block.get("id") or "unknown"
    benchmark_id = benchmark_block.get("id") or ""
    platform = execution_block.get("platform") or platform_block.get("name", "unknown")
    scale_factor = benchmark_block.get("scale_factor") or "unknown"

    execution_id = execution_block.get("id") or execution_block.get("execution_id")
    timestamp = _parse_timestamp(execution_block.get("timestamp"))
    execution_mode = (
        config_block.get("mode")
        or config_block.get("execution_mode")
        or (platform_block.get("config") or {}).get("execution_mode")
    )

    total_time_ms = timing_block.get("total_ms")
    avg_time_ms = timing_block.get("avg_ms")
    min_time_ms = timing_block.get("min_ms")
    max_time_ms = timing_block.get("max_ms")

    total_queries = queries_block.get("total", 0) if isinstance(queries_block, dict) else 0
    passed_queries = queries_block.get("successful", 0) if isinstance(queries_block, dict) else 0
    failed_queries = queries_block.get("failed", 0) if isinstance(queries_block, dict) else 0
    success_rate = queries_block.get("success_rate") if isinstance(queries_block, dict) else None

    raw_total = cost_block.get("total_cost") if isinstance(cost_block, dict) else None
    cost_total = published_total_cost({"total_cost": raw_total, "normalized_cost": data.get("normalized_cost")})

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
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_query_map(normalized: NormalizedResultDict) -> dict[str, NormalizedQuery]:
    return {q.query_id: q for q in normalized.queries}


__all__ = [
    "NormalizedQuery",
    "NormalizedResultDict",
    "detect_schema_version",
    "normalize_result_dict",
    "get_query_map",
]
