"""PostgreSQL Extension Comparison Report Generator.

Generates comparison reports between PostgreSQL baseline and extension
benchmark results. Supports comparing any PostgreSQL extension (pg_duckdb,
pg_mooncake, TimescaleDB) against vanilla PostgreSQL or against each other.

Report types:
- Query-by-query speedup ratios
- Load time comparison
- Total execution time comparison

Example:
    >>> from benchbox.core.pg_extension_comparison import generate_comparison_report
    >>> report = generate_comparison_report(baseline_results, extension_results)
    >>> emit(report)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.utils import format_duration


def _format_metric_section(
    title: str,
    label: str,
    baseline_value: Any,
    extension_value: Any,
    baseline_platform: str,
    extension_platform: str,
) -> list[str]:
    """Format a simple baseline/extension metric comparison section."""
    if baseline_value is None or extension_value is None or baseline_value <= 0:
        return []

    ratio = baseline_value / extension_value if extension_value > 0 else float("inf")
    return [
        title,
        "-" * 40,
        f"  {baseline_platform}: {format_duration(baseline_value)}",
        f"  {extension_platform}: {format_duration(extension_value)}",
        f"  {label}: {ratio:.2f}x",
        "",
    ]


def _format_query_comparison_section(
    baseline_queries: dict[str, Any],
    extension_queries: dict[str, Any],
) -> list[str]:
    """Format the query-by-query comparison section."""
    if not baseline_queries or not extension_queries:
        return []

    common_queries = sorted(set(baseline_queries.keys()) & set(extension_queries.keys()))
    if not common_queries:
        return []

    lines = [
        "Query-by-Query Comparison",
        "-" * 60,
        f"  {'Query':<10} {'Baseline':>12} {'Extension':>12} {'Speedup':>10}",
        f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 10}",
    ]
    speedup_entries: list[tuple[str, float]] = []

    for qid in common_queries:
        b_time = baseline_queries[qid].get("execution_time", 0)
        e_time = extension_queries[qid].get("execution_time", 0)
        if b_time > 0 and e_time > 0:
            speedup = b_time / e_time
            speedup_entries.append((qid, speedup))
            lines.append(f"  {qid:<10} {format_duration(b_time):>12} {format_duration(e_time):>12} {speedup:>9.2f}x")
        elif b_time > 0:
            lines.append(f"  {qid:<10} {format_duration(b_time):>12} {'FAILED':>12} {'N/A':>10}")
        elif e_time > 0:
            lines.append(f"  {qid:<10} {'FAILED':>12} {format_duration(e_time):>12} {'N/A':>10}")

    if speedup_entries:
        speedups = [speedup for _, speedup in speedup_entries]
        max_qid, max_speedup = max(speedup_entries, key=lambda entry: entry[1])
        min_qid, min_speedup = min(speedup_entries, key=lambda entry: entry[1])
        lines.extend(
            [
                "",
                f"  Geometric mean speedup: {_geometric_mean(speedups):.2f}x",
                f"  Max speedup: {max_speedup:.2f}x ({max_qid})",
                f"  Min speedup: {min_speedup:.2f}x ({min_qid})",
            ]
        )

    lines.append("")
    return lines


def _format_summary_section(
    baseline: dict[str, Any],
    extension: dict[str, Any],
    baseline_platform: str,
    extension_platform: str,
) -> list[str]:
    """Format the summary section."""
    lines = [
        "Summary",
        "-" * 40,
        f"  {baseline_platform}: {'PASSED' if baseline.get('success', False) else 'FAILED'}",
        f"  {extension_platform}: {'PASSED' if extension.get('success', False) else 'FAILED'}",
    ]
    baseline_total = baseline.get("total_execution_time")
    extension_total = extension.get("total_execution_time")
    if not baseline_total or not extension_total or baseline_total <= 0:
        return lines

    speedup = baseline_total / extension_total if extension_total > 0 else float("inf")
    if speedup > 1:
        lines.append(f"  {extension_platform} is {speedup:.1f}x faster than {baseline_platform}")
    elif speedup < 1:
        lines.append(f"  {baseline_platform} is {1 / speedup:.1f}x faster than {extension_platform}")
    else:
        lines.append("  Performance is equivalent")
    return lines


def generate_comparison_report(
    baseline: dict[str, Any],
    extension: dict[str, Any],
) -> str:
    """Generate a comparison report between two benchmark results.

    Compares a baseline run (typically vanilla PostgreSQL) against an
    extension run (pg_duckdb, pg_mooncake, etc.) and produces a formatted
    report with speedup ratios and timing differences.

    Args:
        baseline: Result data from the baseline platform run.
        extension: Result data from the extension platform run.

    Returns:
        Formatted multi-line comparison report string.
    """
    lines = []

    baseline_platform = baseline.get("platform", "baseline")
    extension_platform = extension.get("platform", "extension")
    benchmark = baseline.get("benchmark", extension.get("benchmark", "unknown")).upper()
    scale = baseline.get("scale_factor", extension.get("scale_factor", "unknown"))

    lines.extend(
        [
            "PostgreSQL Extension Comparison Report",
            "=" * 60,
            f"Benchmark: {benchmark} (SF {scale})",
            f"Baseline:  {baseline_platform}",
            f"Extension: {extension_platform}",
            "",
        ]
    )
    lines.extend(
        _format_metric_section(
            "Overall Execution",
            "Speedup",
            baseline.get("total_execution_time"),
            extension.get("total_execution_time"),
            baseline_platform,
            extension_platform,
        )
    )
    lines.extend(
        _format_metric_section(
            "Data Loading",
            "Ratio",
            baseline.get("data_loading_time"),
            extension.get("data_loading_time"),
            baseline_platform,
            extension_platform,
        )
    )
    lines.extend(
        _format_query_comparison_section(
            baseline.get("query_results", {}),
            extension.get("query_results", {}),
        )
    )
    lines.extend(_format_summary_section(baseline, extension, baseline_platform, extension_platform))

    return "\n".join(lines)


def _geometric_mean(values: list[float]) -> float:
    """Calculate geometric mean of positive values.

    Args:
        values: List of positive float values.

    Returns:
        Geometric mean of the values.
    """
    if not values:
        return 0.0
    import math

    positive = [v for v in values if v > 0]
    if not positive:
        return 0.0
    log_sum = sum(math.log(v) for v in positive)
    return math.exp(log_sum / len(positive))
