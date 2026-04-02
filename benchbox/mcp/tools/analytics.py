"""Analytics tools for BenchBox MCP server.

Provides tools for result comparison, regression detection, and performance trends.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.query_normalizer import normalize_query_id
from benchbox.mcp.errors import ErrorCode, make_error, make_not_found_error
from benchbox.mcp.tools.path_utils import resolve_result_file_path
from benchbox.utils.printing import get_quiet_console

logger = logging.getLogger(__name__)

# Tool annotations for read-only analytics tools
ANALYTICS_READONLY_ANNOTATIONS = ToolAnnotations(
    title="Read-only analytics tool",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def register_analytics_tools(mcp: FastMCP, *, results_dir: Path) -> None:
    """Register analytics tools with the MCP server."""
    configured_results_dir = Path(results_dir)

    @mcp.tool(annotations=ANALYTICS_READONLY_ANNOTATIONS)
    def analyze_results(
        analysis: str = "compare",
        file1: str | None = None,
        file2: str | None = None,
        platform: str | None = None,
        benchmark: str | None = None,
        threshold_percent: float = 10.0,
        metric: str = "geometric_mean",
        group_by: str = "platform",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Analyze benchmark results.

        Args:
            analysis: Analysis type: 'compare', 'regressions', 'trends', 'aggregate'
            file1: Baseline result file (for 'compare')
            file2: Comparison result file (for 'compare')
            platform: Filter by platform name
            benchmark: Filter by benchmark name
            threshold_percent: Change threshold for regressions (default: 10%)
            metric: Metric for trends: geometric_mean, p50, p95, p99, total_time
            group_by: Grouping for aggregate: platform, benchmark, date
            limit: Max runs to analyze (default: 10)

        Returns:
            Analysis results based on the selected type.
        """
        analysis_lower = analysis.lower()

        if analysis_lower == "compare":
            if not file1 or not file2:
                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    "compare analysis requires file1 and file2 parameters",
                    suggestion="Provide both file1 and file2 for comparison",
                )
            return _compare_results_impl(file1, file2, threshold_percent, configured_results_dir)

        elif analysis_lower == "regressions":
            return _detect_regressions_impl(platform, benchmark, threshold_percent, limit, configured_results_dir)

        elif analysis_lower == "trends":
            return _get_performance_trends_impl(platform, benchmark, metric, limit, configured_results_dir)

        elif analysis_lower == "aggregate":
            return _aggregate_results_impl(platform, benchmark, group_by, configured_results_dir)

        else:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid analysis type: {analysis}",
                details={"valid_types": ["compare", "regressions", "trends", "aggregate"]},
            )

    @mcp.tool(annotations=ANALYTICS_READONLY_ANNOTATIONS)
    def get_query_plan(
        result_file: str,
        query_id: str,
        format: str = "tree",
    ) -> dict[str, Any]:
        """Get query execution plan from benchmark results.

        Args:
            result_file: Result file containing query plans
            query_id: Query identifier (e.g., '1', 'Q1', 'q05')
            format: Output format: 'tree', 'json', 'summary'

        Returns:
            Query plan in the requested format.
        """
        valid_formats = ["tree", "json", "summary"]
        format_lower = format.lower()
        if format_lower not in valid_formats:
            return make_error(
                ErrorCode.VALIDATION_INVALID_FORMAT,
                f"Invalid format: {format}",
                details={"valid_formats": valid_formats},
            )

        file_path = resolve_result_file_path(result_file, configured_results_dir)
        if file_path is None:
            return make_error(
                ErrorCode.RESOURCE_NOT_FOUND,
                f"Result file not found: {result_file}",
                details={"requested_file": result_file},
            )

        try:
            return _get_query_plan_impl(file_path, result_file, query_id, format_lower)
        except json.JSONDecodeError as e:
            return make_error(
                ErrorCode.RESOURCE_INVALID_FORMAT,
                f"Invalid JSON in result file: {e}",
                details={"file": result_file, "parse_error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Failed to get query plan: {e}")
            return make_error(
                ErrorCode.INTERNAL_ERROR,
                f"Failed to get query plan: {e}",
                details={"exception_type": type(e).__name__},
            )


def _list_result_files(results_dir: Path) -> list[Path]:
    """List and sort result JSON files, excluding plans and tuning files."""
    result_files = [
        path
        for path in results_dir.glob("*.json")
        if not path.name.endswith(".plans.json") and not path.name.endswith(".tuning.json")
    ]
    return sorted(result_files, key=lambda p: p.stat().st_mtime, reverse=True)


def _extract_measurement_timings(data: dict[str, Any]) -> list[float]:
    """Extract measurement timings from result data."""
    timings: list[float] = []
    for query in data.get("queries", []):
        if query.get("run_type") != "measurement":
            continue
        runtime = query.get("ms")
        if runtime is not None and runtime > 0:
            timings.append(float(runtime))
    return timings


def _matches_filters(
    run_platform: str,
    run_benchmark: str,
    platform: str | None,
    benchmark: str | None,
) -> bool:
    """Check if a run matches platform and benchmark filters."""
    if platform and platform.lower() not in run_platform.lower():
        return False
    if benchmark and benchmark.lower() not in run_benchmark.lower():
        return False
    return True


def _extract_run_identity(data: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Extract platform name, benchmark block, and benchmark id from result data."""
    run_platform = data.get("platform", {}).get("name", "unknown")
    benchmark_block = data.get("benchmark", {}) if isinstance(data.get("benchmark"), dict) else {}
    run_benchmark = benchmark_block.get("id", "unknown")
    return run_platform, benchmark_block, run_benchmark


def _find_query_execution(data: dict[str, Any], normalized_id: str) -> dict | None:
    """Find a query execution result by normalized query ID."""
    for query_result in data.get("queries", []):
        qid = query_result.get("id", "")
        if normalize_query_id(qid) == normalized_id:
            return query_result
    return None


def _resolve_plans_path(file_path: Path) -> Path | None:
    """Resolve the plans file path for a result file."""
    plans_path = file_path.with_suffix("").with_suffix(".plans.json")
    if not plans_path.exists():
        plans_path = Path(str(file_path).replace(".json", ".plans.json"))
    return plans_path if plans_path.exists() else None


def _format_plan_response(query_plan: dict, format_lower: str, normalized_id: str, runtime_ms: Any) -> dict[str, Any]:
    """Format a query plan into the requested output format."""
    response: dict[str, Any] = {
        "status": "success",
        "query_id": normalized_id,
        "runtime_ms": runtime_ms,
    }

    if format_lower == "json":
        response["plan"] = query_plan
    elif format_lower == "summary":
        response["summary"] = _extract_plan_summary(query_plan)
    else:
        response["plan_tree"] = _format_plan_tree(query_plan)

    return response


def _get_query_plan_impl(file_path: Path, result_file: str, query_id: str, format_lower: str) -> dict[str, Any]:
    """Core implementation for getting a query plan."""
    with open(file_path) as f:
        data = json.load(f)

    normalized_id = normalize_query_id(query_id)
    query_exec = _find_query_execution(data, normalized_id)

    if not query_exec:
        available_ids = [str(q.get("id", "")) for q in data.get("queries", []) if q.get("id")]
        return make_not_found_error("query", query_id, available=sorted(set(available_ids))[:20])

    plans_path = _resolve_plans_path(file_path)
    query_info = {"runtime_ms": query_exec.get("ms"), "status": query_exec.get("status")}

    if plans_path is None:
        return {
            "status": "no_plan",
            "query_id": normalized_id,
            "message": "No query plan captured for this query",
            "suggestion": "Run benchmark with --capture-plans flag",
            "query_info": query_info,
        }

    with open(plans_path) as plans_handle:
        plans_data = json.load(plans_handle)

    query_plan_entry = plans_data.get("queries", {}).get(normalized_id)
    if not query_plan_entry or "plan" not in query_plan_entry:
        return {
            "status": "no_plan",
            "query_id": normalized_id,
            "message": "No query plan captured for this query",
            "query_info": query_info,
        }

    return _format_plan_response(query_plan_entry["plan"], format_lower, normalized_id, query_exec.get("ms"))


def _compare_results_impl(file1: str, file2: str, threshold_percent: float, results_dir: Path) -> dict[str, Any]:
    """Compare two benchmark runs."""
    exporter = ResultExporter(anonymize=False, console=get_quiet_console())
    path1 = resolve_result_file_path(file1, results_dir)
    path2 = resolve_result_file_path(file2, results_dir)

    if path1 is None:
        return make_error(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"Baseline file not found: {file1}",
            details={"file_type": "baseline", "requested_file": file1},
        )
    if path2 is None:
        return make_error(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"Comparison file not found: {file2}",
            details={"file_type": "comparison", "requested_file": file2},
        )

    comparison = exporter.compare_results(path1, path2)
    if "error" in comparison:
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            comparison.get("error", "Failed to compare results"),
            details={
                "baseline_loaded": comparison.get("baseline_loaded"),
                "current_loaded": comparison.get("current_loaded"),
            },
        )

    regressions: list[str] = []
    improvements: list[str] = []
    stable: list[str] = []

    for entry in comparison.get("query_comparisons", []):
        change_pct = entry.get("change_percent", 0)
        if change_pct > threshold_percent:
            regressions.append(entry.get("query_id"))
        elif change_pct < -threshold_percent:
            improvements.append(entry.get("query_id"))
        else:
            stable.append(entry.get("query_id"))

    comparison["summary"] = {
        "total_queries_compared": len(comparison.get("query_comparisons", [])),
        "regressions": len(regressions),
        "improvements": len(improvements),
        "stable": len(stable),
        "threshold_percent": threshold_percent,
    }
    comparison["regressions"] = [q for q in regressions if q]
    comparison["improvements"] = [q for q in improvements if q]

    return comparison


def _load_regression_runs(
    result_files: list[Path],
    platform: str | None,
    benchmark: str | None,
    lookback_runs: int,
) -> list[dict[str, Any]]:
    """Load and filter result files for regression detection."""
    runs: list[dict[str, Any]] = []
    for file_path in result_files[: lookback_runs * 2]:
        try:
            with open(file_path) as f:
                data = json.load(f)

            run_platform, benchmark_block, run_benchmark = _extract_run_identity(data)

            if not _matches_filters(run_platform, run_benchmark, platform, benchmark):
                continue

            runs.append(
                {
                    "file": file_path.name,
                    "path": str(file_path),
                    "platform": run_platform,
                    "benchmark": run_benchmark,
                    "scale_factor": benchmark_block.get("scale_factor"),
                    "timestamp": data.get("run", {}).get("timestamp", file_path.stat().st_mtime),
                    "data": data,
                }
            )

            if len(runs) >= lookback_runs:
                break

        except Exception as e:
            logger.warning(f"Could not parse result file {file_path}: {e}")
            continue
    return runs


def _extract_keyed_timings(run_data: dict) -> dict[str, float]:
    """Extract query ID to timing mapping from result data."""
    timings: dict[str, float] = {}
    for query in run_data.get("queries", []):
        if query.get("run_type") != "measurement":
            continue
        qid = str(query.get("id", ""))
        runtime = query.get("ms")
        if qid and runtime is not None:
            timings[qid] = float(runtime)
    return timings


def _classify_query_changes(
    older_timings: dict[str, float],
    newer_timings: dict[str, float],
    threshold_percent: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Classify queries as regressions, improvements, or stable."""
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    stable: list[str] = []

    all_queries = set(older_timings.keys()) | set(newer_timings.keys())
    for qid in sorted(all_queries):
        old_time = older_timings.get(qid)
        new_time = newer_timings.get(qid)

        if old_time is None or new_time is None or old_time <= 0:
            continue

        delta_ms = new_time - old_time
        delta_pct = (delta_ms / old_time) * 100

        if delta_pct > threshold_percent:
            regressions.append(
                {
                    "query_id": qid,
                    "baseline_ms": round(old_time, 2),
                    "current_ms": round(new_time, 2),
                    "delta_ms": round(delta_ms, 2),
                    "delta_percent": round(delta_pct, 1),
                    "severity": _classify_regression_severity(delta_pct),
                }
            )
        elif delta_pct < -threshold_percent:
            improvements.append(
                {
                    "query_id": qid,
                    "baseline_ms": round(old_time, 2),
                    "current_ms": round(new_time, 2),
                    "delta_ms": round(delta_ms, 2),
                    "delta_percent": round(delta_pct, 1),
                }
            )
        else:
            stable.append(qid)

    regressions.sort(key=lambda r: r["delta_percent"], reverse=True)
    return regressions, improvements, stable


def _detect_regressions_impl(
    platform: str | None,
    benchmark: str | None,
    threshold_percent: float,
    lookback_runs: int,
    results_dir: Path,
) -> dict[str, Any]:
    """Detect performance regressions across recent runs."""
    if not results_dir.exists():
        return {"status": "no_data", "message": f"No results directory found at {results_dir}", "regressions": []}

    result_files = _list_result_files(results_dir)
    if len(result_files) < 2:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 2 benchmark runs for comparison, found {len(result_files)}",
            "regressions": [],
        }

    runs = _load_regression_runs(result_files, platform, benchmark, lookback_runs)

    if len(runs) < 2:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 2 comparable runs, found {len(runs)} matching filters",
            "filters_applied": {"platform": platform, "benchmark": benchmark},
            "regressions": [],
        }

    newer_run = runs[0]
    older_run = runs[1]

    older_timings = _extract_keyed_timings(older_run["data"])
    newer_timings = _extract_keyed_timings(newer_run["data"])

    regressions, improvements, stable = _classify_query_changes(older_timings, newer_timings, threshold_percent)

    all_queries = set(older_timings.keys()) | set(newer_timings.keys())
    total_old = sum(older_timings.values())
    total_new = sum(newer_timings.values())
    total_delta_pct = ((total_new - total_old) / total_old * 100) if total_old > 0 else 0

    return {
        "status": "completed",
        "comparison": {
            "baseline": {
                "file": older_run["file"],
                "platform": older_run["platform"],
                "benchmark": older_run["benchmark"],
                "timestamp": older_run["timestamp"],
            },
            "current": {
                "file": newer_run["file"],
                "platform": newer_run["platform"],
                "benchmark": newer_run["benchmark"],
                "timestamp": newer_run["timestamp"],
            },
        },
        "summary": {
            "total_queries": len(all_queries),
            "regressions": len(regressions),
            "improvements": len(improvements),
            "stable": len(stable),
            "total_runtime_delta_percent": round(total_delta_pct, 1),
            "threshold_percent": threshold_percent,
        },
        "regressions": regressions,
        "improvements": improvements[:5],
    }


def _resolve_timestamp_str(timestamp: Any, file_path: Path) -> str:
    """Resolve a timestamp value to an ISO format string."""
    if timestamp:
        try:
            if isinstance(timestamp, str):
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                ts = datetime.fromtimestamp(timestamp)
            return ts.isoformat()
        except Exception:
            return str(timestamp)
    return datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()


def _compute_trend_direction(runs: list[dict[str, Any]]) -> tuple[str, float]:
    """Compute trend direction and percentage from ordered data points."""
    if len(runs) < 2:
        return "insufficient_data", 0

    first_value = runs[0]["value"]
    last_value = runs[-1]["value"]
    if first_value <= 0:
        return "unknown", 0

    trend_pct = ((last_value - first_value) / first_value) * 100
    if trend_pct < -5:
        return "improving", trend_pct
    elif trend_pct > 5:
        return "degrading", trend_pct
    return "stable", trend_pct


def _load_trend_data_point(
    file_path: Path,
    platform: str | None,
    benchmark: str | None,
    metric_lower: str,
) -> dict[str, Any] | None:
    """Load a single result file as a trend data point, or None if filtered/invalid."""
    try:
        with open(file_path) as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Could not parse result file {file_path}: {e}")
        return None

    run_platform = data.get("platform", {}).get("name", "unknown")
    benchmark_block = data.get("benchmark", {}) if isinstance(data.get("benchmark"), dict) else {}
    run_benchmark = benchmark_block.get("id", "unknown")

    if platform and platform.lower() not in run_platform.lower():
        return None
    if benchmark and benchmark.lower() not in run_benchmark.lower():
        return None

    timings = _extract_measurement_timings(data)
    if not timings:
        return None

    metric_value = _calculate_metric(timings, metric_lower)
    timestamp_str = _resolve_timestamp_str(data.get("run", {}).get("timestamp"), file_path)

    return {
        "file": file_path.name,
        "platform": run_platform,
        "benchmark": run_benchmark,
        "scale_factor": benchmark_block.get("scale_factor"),
        "timestamp": timestamp_str,
        "query_count": len(timings),
        "metric": metric_lower,
        "value": round(metric_value, 2),
    }


def _get_performance_trends_impl(
    platform: str | None,
    benchmark: str | None,
    metric: str,
    limit: int,
    results_dir: Path,
) -> dict[str, Any]:
    """Get performance trends over multiple benchmark runs."""
    valid_metrics = ["geometric_mean", "p50", "p95", "p99", "total_time"]
    metric_lower = metric.lower()
    if metric_lower not in valid_metrics:
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid metric: {metric}",
            details={"valid_metrics": valid_metrics},
        )

    if not results_dir.exists():
        return {"status": "no_data", "message": f"No results directory found at {results_dir}", "trends": []}

    result_files = _list_result_files(results_dir)

    runs: list[dict[str, Any]] = []
    for file_path in result_files:
        if len(runs) >= limit:
            break
        data_point = _load_trend_data_point(file_path, platform, benchmark, metric_lower)
        if data_point is not None:
            runs.append(data_point)

    if not runs:
        return {
            "status": "no_matching_data",
            "message": "No benchmark runs match the specified filters",
            "filters_applied": {"platform": platform, "benchmark": benchmark},
            "trends": [],
        }

    runs.reverse()
    trend_direction, trend_pct = _compute_trend_direction(runs)

    return {
        "status": "success",
        "metric": metric_lower,
        "filters_applied": {"platform": platform, "benchmark": benchmark, "limit": limit},
        "summary": {
            "run_count": len(runs),
            "first_run": runs[0]["timestamp"] if runs else None,
            "last_run": runs[-1]["timestamp"] if runs else None,
            "trend_direction": trend_direction,
            "trend_percent": round(trend_pct, 1),
        },
        "data_points": runs,
    }


def _resolve_date_group_key(data: dict[str, Any], file_path: Path) -> str:
    """Resolve date-based group key from result data."""
    timestamp = data.get("run", {}).get("timestamp", file_path.stat().st_mtime)
    if isinstance(timestamp, str):
        try:
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return ts.strftime("%Y-%m-%d")
        except Exception:
            return timestamp[:10] if len(timestamp) >= 10 else "unknown"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _resolve_group_key(
    group_by_lower: str,
    run_platform: str,
    run_benchmark: str,
    data: dict[str, Any],
    file_path: Path,
) -> str:
    """Resolve group key based on the grouping strategy."""
    if group_by_lower == "platform":
        return run_platform
    elif group_by_lower == "benchmark":
        return run_benchmark
    return _resolve_date_group_key(data, file_path)


def _compute_group_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics for a group of runs."""
    all_timings = [t for run in runs for t in run["timings"]]
    total_times = [run["total_time"] for run in runs]

    return {
        "run_count": len(runs),
        "total_queries": len(all_timings),
        "query_stats": {
            "mean_ms": round(sum(all_timings) / len(all_timings), 2) if all_timings else 0,
            "std_ms": round(_std_dev(all_timings), 2) if len(all_timings) > 1 else 0,
            "min_ms": round(min(all_timings), 2) if all_timings else 0,
            "max_ms": round(max(all_timings), 2) if all_timings else 0,
            "p50_ms": round(_percentile(all_timings, 50), 2) if all_timings else 0,
            "p95_ms": round(_percentile(all_timings, 95), 2) if all_timings else 0,
        },
        "run_stats": {
            "mean_total_ms": round(sum(total_times) / len(total_times), 2) if total_times else 0,
            "std_total_ms": round(_std_dev(total_times), 2) if len(total_times) > 1 else 0,
            "min_total_ms": round(min(total_times), 2) if total_times else 0,
            "max_total_ms": round(max(total_times), 2) if total_times else 0,
        },
        "files": [run["file"] for run in runs],
    }


def _aggregate_results_impl(
    platform: str | None,
    benchmark: str | None,
    group_by: str,
    results_dir: Path,
) -> dict[str, Any]:
    """Aggregate multiple benchmark results into summary statistics."""
    valid_group_by = ["platform", "benchmark", "date"]
    group_by_lower = group_by.lower()
    if group_by_lower not in valid_group_by:
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid group_by: {group_by}",
            details={"valid_options": valid_group_by},
        )

    if not results_dir.exists():
        return {"status": "no_data", "message": f"No results directory found at {results_dir}", "aggregates": {}}

    result_files = _list_result_files(results_dir)
    groups: dict[str, list[dict[str, Any]]] = {}

    for file_path in result_files:
        try:
            with open(file_path) as f:
                data = json.load(f)

            run_platform, benchmark_block, run_benchmark = _extract_run_identity(data)

            if not _matches_filters(run_platform, run_benchmark, platform, benchmark):
                continue

            timings = _extract_measurement_timings(data)
            if not timings:
                continue

            group_key = _resolve_group_key(group_by_lower, run_platform, run_benchmark, data, file_path)
            groups.setdefault(group_key, []).append(
                {
                    "file": file_path.name,
                    "timings": timings,
                    "total_time": sum(timings),
                    "query_count": len(timings),
                    "scale_factor": benchmark_block.get("scale_factor"),
                }
            )

        except Exception as e:
            logger.warning(f"Could not parse result file {file_path}: {e}")
            continue

    if not groups:
        return {
            "status": "no_matching_data",
            "message": "No benchmark runs match the specified filters",
            "filters_applied": {"platform": platform, "benchmark": benchmark},
            "aggregates": {},
        }

    aggregates = {key: _compute_group_stats(runs) for key, runs in sorted(groups.items())}

    return {
        "status": "success",
        "group_by": group_by_lower,
        "filters_applied": {"platform": platform, "benchmark": benchmark},
        "summary": {
            "total_groups": len(aggregates),
            "total_runs": sum(a["run_count"] for a in aggregates.values()),
        },
        "aggregates": aggregates,
    }


def _extract_plan_summary(plan: dict) -> dict[str, Any]:
    """Extract summary statistics from a query plan."""
    summary = {
        "operator_count": 0,
        "estimated_rows": None,
        "estimated_cost": None,
        "join_count": 0,
        "scan_count": 0,
    }

    def count_operators(node: dict | list) -> None:
        if isinstance(node, dict):
            _update_plan_summary(summary, node)
            for value in node.values():
                count_operators(value)
            return
        if isinstance(node, list):
            for item in node:
                count_operators(item)

    count_operators(plan)
    return summary


def _update_plan_summary(summary: dict[str, Any], node: dict[str, Any]) -> None:
    summary["operator_count"] += 1
    op_type = node.get("type", node.get("operator", "")).lower()
    if "join" in op_type:
        summary["join_count"] += 1
    if "scan" in op_type or "read" in op_type:
        summary["scan_count"] += 1
    if summary["estimated_rows"] is None and "rows" in node:
        summary["estimated_rows"] = node["rows"]
    if summary["estimated_cost"] is None and "cost" in node:
        summary["estimated_cost"] = node["cost"]


def _format_plan_tree(plan: dict, indent: int = 0) -> str:
    """Format a query plan as a readable tree string."""
    lines = []
    prefix = "  " * indent

    if isinstance(plan, dict):
        op_type = plan.get("type") or plan.get("operator") or plan.get("name") or "Node"
        lines.append(f"{prefix}├── {op_type}")

        for key in ["table", "alias", "condition", "rows", "cost"]:
            if key in plan:
                lines.append(f"{prefix}│   {key}: {plan[key]}")

        children = plan.get("children") or plan.get("inputs") or plan.get("plans") or []
        if isinstance(children, list):
            for child in children:
                lines.append(_format_plan_tree(child, indent + 1))
        elif isinstance(children, dict):
            lines.append(_format_plan_tree(children, indent + 1))

    return "\n".join(lines)


def _classify_regression_severity(delta_pct: float) -> str:
    """Classify regression severity based on percentage change."""
    if delta_pct >= 100:
        return "critical"
    elif delta_pct >= 50:
        return "high"
    elif delta_pct >= 25:
        return "medium"
    else:
        return "low"


def _calculate_metric(timings: list[float], metric: str) -> float:
    """Calculate the specified performance metric from query timings."""
    if not timings:
        return 0

    if metric == "geometric_mean":
        log_sum = sum(math.log(t) for t in timings if t > 0)
        return math.exp(log_sum / len(timings)) if timings else 0
    elif metric == "p50":
        return _percentile(timings, 50)
    elif metric == "p95":
        return _percentile(timings, 95)
    elif metric == "p99":
        return _percentile(timings, 99)
    elif metric == "total_time":
        return sum(timings)
    else:
        return sum(timings) / len(timings)


def _percentile(data: list[float], p: float) -> float:
    """Calculate the p-th percentile of the data."""
    if not data:
        return 0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    if f == c:
        return sorted_data[f]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _std_dev(data: list[float]) -> float:
    """Calculate standard deviation."""
    if len(data) < 2:
        return 0
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)
    return math.sqrt(variance)
