"""Analytics tools for BenchBox MCP server.

Provides tools for result comparison, regression detection, and performance trends.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from benchbox.core.results.metrics import calculate_named_metric, percentile_ms, sample_stdev_ms
from benchbox.core.results.query_normalizer import normalize_query_id
from benchbox.core.results.regression_policy import (
    classify_change,
    classify_severity,
    percent_change,
)
from benchbox.mcp.errors import ErrorCode, make_error, make_not_found_error
from benchbox.mcp.security import PathProvider, resolve_path_provider
from benchbox.mcp.tools.path_utils import resolve_result_file_path
from benchbox.validation.bundle import COMPANION_SUFFIXES

logger = logging.getLogger(__name__)

# Tool annotations for read-only analytics tools
ANALYTICS_READONLY_ANNOTATIONS = ToolAnnotations(
    title="Read-only analytics tool",
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _resolve_validation_directory(directory: str, results_dir: Path, *, tenant_scoped: bool) -> Path | dict[str, Any]:
    """Resolve a validation directory while containing remote tenants."""
    candidate = Path(directory)
    if tenant_scoped and candidate.is_absolute():
        return make_error(ErrorCode.VALIDATION_ERROR, "Absolute validation directories are not allowed")
    if not candidate.is_absolute():
        candidate = results_dir / candidate
    if tenant_scoped:
        try:
            candidate.resolve().relative_to(results_dir.resolve())
        except ValueError:
            return make_error(ErrorCode.VALIDATION_ERROR, "Validation directory escapes tenant workspace")
    return candidate


def register_analytics_tools(
    mcp: MCPServer,
    *,
    results_dir: PathProvider,
    anonymize_results: bool = False,
) -> None:
    """Register analytics tools with the MCP server.

    Args:
        mcp: Server to register on.
        results_dir: Provider for the server-owned result root.
        anonymize_results: True when the server runs under a remote security
            policy; see ``register_benchmark_tools``.
    """
    tenant_scoped = not isinstance(results_dir, Path)

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
        configured_results_dir = resolve_path_provider(results_dir)
        analysis_lower = analysis.lower()

        if analysis_lower == "compare":
            if not file1 or not file2:
                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    "compare analysis requires file1 and file2 parameters",
                    suggestion="Provide both file1 and file2 for comparison",
                )
            return _compare_results_impl(
                file1, file2, threshold_percent, configured_results_dir, anonymize=anonymize_results
            )

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

        configured_results_dir = resolve_path_provider(results_dir)
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
            logger.error("Failed to get query plan (%s)", type(e).__name__)
            return make_error(
                ErrorCode.INTERNAL_ERROR,
                f"Failed to get query plan: {e}",
                details={"exception_type": type(e).__name__},
            )

    @mcp.tool(annotations=ANALYTICS_READONLY_ANNOTATIONS)
    def validate_results(
        result_file: str = "",
        directory: str = "",
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Validate integrity, completeness, and believability of result JSON files.

        Provide result_file (single file path) or directory (batch mode).
        Returns structured check results with PASS/WARN/FAIL status per check.

        Args:
            result_file: Path to a single result JSON file
            directory: Path to a directory of result JSON files
            verbose: Include PASS checks in output (default: WARN+FAIL only)

        Returns:
            Validation report with per-check status and overall result.
        """
        from benchbox.core.results.integrity_validator import (
            validate_directory as _validate_directory,
            validate_file as _validate_file,
        )

        configured_results_dir = resolve_path_provider(results_dir)
        if result_file:
            file_path = resolve_result_file_path(result_file, configured_results_dir)
            if file_path is None or not file_path.exists():
                return make_not_found_error(
                    "result_file",
                    result_file,
                    suggestion='Use get_results(format="list") to see available result files',
                )
            report = _validate_file(file_path)
            checks = [
                {
                    "category": c.category.value,
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                }
                for c in report.checks
                if verbose or c.status.value != "PASS"
            ]
            return {
                "file": report.file,
                "benchmark_id": report.benchmark_id,
                "platform": report.platform,
                "scale_factor": report.scale_factor,
                "overall_status": report.overall_status.value,
                "summary": report.summary,
                "checks": checks,
            }
        elif directory:
            resolved_directory = _resolve_validation_directory(
                directory,
                configured_results_dir,
                tenant_scoped=tenant_scoped,
            )
            if isinstance(resolved_directory, dict):
                return resolved_directory
            dir_path = resolved_directory
            if not dir_path.is_dir():
                return make_error(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    f"Directory not found: {directory}",
                )
            reports = _validate_directory(dir_path)
            return {
                "total": len(reports),
                "pass": sum(1 for r in reports if r.overall_status.value == "PASS"),
                "warn": sum(1 for r in reports if r.overall_status.value == "WARN"),
                "fail": sum(1 for r in reports if r.overall_status.value == "FAIL"),
                "files": [
                    {
                        "file": r.file,
                        "benchmark_id": r.benchmark_id,
                        "platform": r.platform,
                        "overall_status": r.overall_status.value,
                    }
                    for r in reports
                ],
            }
        else:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                "Provide either result_file or directory parameter",
            )


def _list_result_files(results_dir: Path) -> list[Path]:
    """List and sort result JSON files, excluding plans and tuning files."""
    result_files = [path for path in results_dir.glob("*.json") if not path.name.endswith(COMPANION_SUFFIXES)]
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
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    normalized_id = normalize_query_id(query_id)
    query_exec = _find_query_execution(data, normalized_id)

    if not query_exec:
        available_ids = [str(q.get("id", "")) for q in data.get("queries", []) if q.get("id")]
        return make_not_found_error(
            "query",
            query_id,
            available=sorted(set(available_ids))[:20],
            suggestion="Use get_query_details() with a query ID from `details.available`",
        )

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

    with open(plans_path, encoding="utf-8") as plans_handle:
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


def _compare_results_impl(
    file1: str,
    file2: str,
    threshold_percent: float,
    results_dir: Path,
    *,
    anonymize: bool,
) -> dict[str, Any]:
    """Compare two benchmark runs (transport wrapper; core owns assembly)."""
    from benchbox.core.results.analytics import compare_results as _core_compare

    # egress-reviewed: local stdio serves a same-trust-boundary agent that
    # needs real paths/hostnames to act on results; secrets are already
    # redacted at capture time by sanitize_platform_options, and exception
    # text is scrubbed in mcp/errors.py. Remote/tenant mode is a different
    # trust boundary, so the caller sets anonymize=True there.
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

    comparison = _core_compare(path1, path2, threshold_percent, anonymize=anonymize)
    if "error" in comparison:
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            comparison.get("error", "Failed to compare results"),
            details={
                "baseline_loaded": comparison.get("baseline_loaded"),
                "current_loaded": comparison.get("current_loaded"),
            },
        )

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
            with open(file_path, encoding="utf-8") as f:
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
            logger.warning("Could not parse result file %s (%s)", file_path.name, type(e).__name__)
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
        delta_pct = percent_change(old_time, new_time)
        if delta_pct is None:
            continue

        change_class = classify_change(delta_pct, threshold_percent)
        if change_class == "regression":
            regressions.append(
                {
                    "query_id": qid,
                    "baseline_ms": round(old_time, 2),
                    "current_ms": round(new_time, 2),
                    "delta_ms": round(delta_ms, 2),
                    "delta_percent": round(delta_pct, 1),
                    "severity": classify_severity(delta_pct),
                }
            )
        elif change_class == "improvement":
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
    """Detect performance regressions across recent runs (transport wrapper)."""
    from benchbox.core.results.analytics import detect_regressions as _core_detect

    return _core_detect(results_dir, platform, benchmark, threshold_percent, lookback_runs)


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


def _load_trend_data_point(
    file_path: Path,
    platform: str | None,
    benchmark: str | None,
    metric_lower: str,
) -> dict[str, Any] | None:
    """Load a single result file as a trend data point, or None if filtered/invalid."""
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Could not parse result file %s (%s)", file_path.name, type(e).__name__)
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

    metric_value = calculate_named_metric(timings, metric_lower)
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
    """Get performance trends over multiple benchmark runs (transport wrapper)."""
    from benchbox.core.results.analytics import get_performance_trends as _core_trends

    result = _core_trends(results_dir, platform, benchmark, metric, limit)
    # Map core error sentinel to MCP error envelope for invalid-metric case.
    if "error" in result and result.get("error_code") == "VALIDATION_ERROR":
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            result["error"],
            details=result.get("details", {}),
        )
    return result


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
            "std_ms": round(sample_stdev_ms(all_timings), 2) if len(all_timings) > 1 else 0,
            "min_ms": round(min(all_timings), 2) if all_timings else 0,
            "max_ms": round(max(all_timings), 2) if all_timings else 0,
            "p50_ms": round(percentile_ms(all_timings, 0.50), 2) if all_timings else 0,
            "p95_ms": round(percentile_ms(all_timings, 0.95), 2) if all_timings else 0,
        },
        "run_stats": {
            "mean_total_ms": round(sum(total_times) / len(total_times), 2) if total_times else 0,
            "std_total_ms": round(sample_stdev_ms(total_times), 2) if len(total_times) > 1 else 0,
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
    """Aggregate multiple benchmark results (transport wrapper; core owns assembly)."""
    from benchbox.core.results.analytics import aggregate_results as _core_aggregate

    result = _core_aggregate(results_dir, platform, benchmark, group_by)
    if "error" in result and result.get("error_code") == "VALIDATION_ERROR":
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            result["error"],
            details=result.get("details", {}),
        )
    return result


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
