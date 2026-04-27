"""Generate ASCII charts from comparison results.

Provides a shared helper for the ``--generate-charts`` CLI flag used by
``benchbox compare`` and ``benchbox compare-dataframes``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from benchbox.core.visualization.exporters import export_ascii
from benchbox.core.visualization.result_plotter import NormalizedQuery, NormalizedResult

logger = logging.getLogger(__name__)

# Chart types generated for comparison output
_COMPARISON_CHART_TYPES = ("performance_bar", "distribution_box", "query_heatmap")


def generate_comparison_charts(
    results: list[NormalizedResult],
    output_dir: str | Path,
    theme: str = "light",
) -> dict[str, Path]:
    """Render ASCII charts from normalized results and export to text files.

    Args:
        results: Normalized comparison results (one per platform).
        output_dir: Directory to write chart ``.txt`` files into.
        theme: Color theme (``"light"`` or ``"dark"``).

    Returns:
        Mapping of chart type to exported file path.
    """
    from benchbox.core.visualization.ascii_api import ChartOptions, render_ascii_chart_from_results
    from benchbox.core.visualization.utils import extract_chart_subtitle

    if not results:
        return {}

    opts = ChartOptions(use_color=False)
    subtitle = extract_chart_subtitle(results)
    exported: dict[str, Path] = {}

    for chart_type in _COMPARISON_CHART_TYPES:
        content = render_ascii_chart_from_results(results, chart_type, options=opts, subtitle=subtitle)
        if content:
            path = export_ascii(content, output_dir, chart_type)
            exported[chart_type] = path

    return exported


def normalized_from_unified(
    results: Any,
) -> list[NormalizedResult]:
    """Convert ``UnifiedPlatformResult`` objects to ``NormalizedResult``.

    Args:
        results: List of :class:`UnifiedPlatformResult` instances.
    """
    normalized: list[NormalizedResult] = []
    for r in results:
        queries = [
            NormalizedQuery(
                query_id=q.query_id,
                execution_time_ms=q.mean_time_ms if q.mean_time_ms > 0 else None,
                status=q.status,
            )
            for q in r.query_results
        ]
        total = r.total_time_ms if r.total_time_ms else None
        success = r.success_rate if hasattr(r, "success_rate") else None
        normalized.append(
            NormalizedResult(
                benchmark="comparison",
                platform=r.platform,
                scale_factor=0,
                execution_id=None,
                timestamp=None,
                total_time_ms=total,
                avg_time_ms=None,
                success_rate=success,
                cost_total=None,
                queries=queries,
            )
        )
    return normalized


def normalized_from_dataframe(
    results: Any,
) -> list[NormalizedResult]:
    """Convert ``PlatformBenchmarkResult`` objects to ``NormalizedResult``.

    Args:
        results: List of :class:`PlatformBenchmarkResult` instances.
    """
    normalized: list[NormalizedResult] = []
    for r in results:
        queries = [
            NormalizedQuery(
                query_id=q.query_id,
                execution_time_ms=q.mean_time_ms if q.mean_time_ms > 0 else None,
                status=q.status,
            )
            for q in r.query_results
        ]
        total = r.total_time_ms if r.total_time_ms else None
        success = r.success_rate if hasattr(r, "success_rate") else None
        normalized.append(
            NormalizedResult(
                benchmark="comparison",
                platform=r.platform,
                scale_factor=0,
                execution_id=None,
                timestamp=getattr(r, "timestamp", None),
                total_time_ms=total,
                avg_time_ms=None,
                success_rate=success,
                cost_total=None,
                queries=queries,
            )
        )
    return normalized


def normalized_from_sql_vs_df(
    summary: Any,
) -> list[NormalizedResult]:
    """Convert ``SQLVsDataFrameSummary`` to ``NormalizedResult`` pair.

    Creates two NormalizedResult entries - one for the SQL platform and one
    for the DataFrame platform - so that standard chart types work.

    Args:
        summary: A :class:`SQLVsDataFrameSummary` instance.
    """
    sql_queries: list[NormalizedQuery] = []
    df_queries: list[NormalizedQuery] = []
    sql_total = 0.0
    df_total = 0.0

    for q in summary.query_results:
        sql_queries.append(
            NormalizedQuery(
                query_id=q.query_id,
                execution_time_ms=q.sql_time_ms if q.sql_time_ms > 0 else None,
                status=q.status,
            )
        )
        df_queries.append(
            NormalizedQuery(
                query_id=q.query_id,
                execution_time_ms=q.df_time_ms if q.df_time_ms > 0 else None,
                status=q.status,
            )
        )
        sql_total += q.sql_time_ms
        df_total += q.df_time_ms

    return [
        NormalizedResult(
            benchmark="comparison",
            platform=summary.sql_platform,
            scale_factor=0,
            execution_id=None,
            timestamp=None,
            total_time_ms=sql_total or None,
            avg_time_ms=None,
            success_rate=None,
            cost_total=None,
            queries=sql_queries,
        ),
        NormalizedResult(
            benchmark="comparison",
            platform=summary.df_platform,
            scale_factor=0,
            execution_id=None,
            timestamp=None,
            total_time_ms=df_total or None,
            avg_time_ms=None,
            success_rate=None,
            cost_total=None,
            queries=df_queries,
        ),
    ]
