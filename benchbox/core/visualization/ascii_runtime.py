"""Shared runtime helpers to render ASCII charts from normalized results."""

from __future__ import annotations

import math
import re
import warnings
from datetime import datetime
from typing import Any, Protocol

from benchbox.core.visualization.ascii import (
    BarChart,
    BoxPlot,
    Heatmap,
    Histogram,
    LineChart,
    ScatterPlot,
)
from benchbox.core.visualization.ascii.bar_chart import BarData
from benchbox.core.visualization.ascii.box_plot import BoxPlotSeries
from benchbox.core.visualization.ascii.histogram import HistogramBar
from benchbox.core.visualization.ascii.line_chart import LinePoint
from benchbox.core.visualization.ascii.scatter_plot import ScatterPoint

# Percentage change within ±STABLE_THRESHOLD is classified as "stable" (no meaningful regression or improvement).
# 2% accounts for typical run-to-run variance in OLAP benchmarks at SF≥1.
_STABLE_THRESHOLD_PCT = 2.0

# Number of best/worst queries shown in summary boxes.
# 3 balances signal density vs. noise — enough to spot patterns, few enough to scan quickly.
_SUMMARY_QUERY_COUNT = 3

_SUBTITLE_KEYS = frozenset({"benchmark", "scale_factor", "platform_version", "tuning"})
_SUMMARY_LABELS = {
    "primary_label": "Geo Mean",
    "secondary_label": "Median",
    "total_label": "Total",
    "count_label": "Queries",
}
_PHASE_TIMING_KEYS = ("phases", "phase_breakdown", "phase_times")


class QueryResultLike(Protocol):
    """Minimal query contract required by ASCII runtime renderers."""

    query_id: str
    execution_time_ms: float | None


class NormalizedResultLike(Protocol):
    """Minimal normalized result contract required by ASCII runtime renderers."""

    platform: str
    total_time_ms: float | None
    power_at_size: float | None
    queries: list[QueryResultLike]
    cost_total: float | None
    timestamp: datetime | None
    success_rate: float | None
    raw: dict[str, Any] | None


def render_ascii_chart_from_results(
    results: list[NormalizedResultLike],
    chart_type: str,
    options: Any,
    metadata: dict[str, Any] | None = None,
    subtitle: str | None = None,
) -> str | None:
    """Render one chart from normalized results.

    Returns rendered chart string, or None when the chart is not applicable.

    Args:
        results: Normalized benchmark results.
        chart_type: Chart type key (e.g., "performance_bar").
        options: ChartOptions instance.
        metadata: Deprecated — use subtitle instead. If provided without
            subtitle, it is converted via build_chart_subtitle().
        subtitle: Pre-formatted subtitle string for chart display.
    """
    if subtitle is None and metadata:
        warnings.warn(
            "render_ascii_chart_from_results(metadata=) is deprecated, use subtitle= instead",
            DeprecationWarning,
            stacklevel=2,
        )
        from benchbox.core.visualization.utils import build_chart_subtitle

        # Filter to recognized subtitle keys before forwarding
        subtitle_kwargs = {k: v for k, v in metadata.items() if k in _SUBTITLE_KEYS}
        subtitle = build_chart_subtitle(**subtitle_kwargs)

    handler = _CHART_TYPE_DISPATCH.get(chart_type)
    if handler is None:
        return None
    return handler(results, options, subtitle)


def _render_performance_bar(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    bar_data: list[BarData] = [BarData(label=r.platform, value=r.total_time_ms or 0) for r in results]
    if bar_data:
        sorted_data = sorted(bar_data, key=lambda x: x.value)
        sorted_data[0].is_best = True
        if len(sorted_data) > 1:
            sorted_data[-1].is_worst = True

    chart = BarChart(
        data=bar_data,
        title="Performance Comparison",
        metric_label="Execution Time (ms)",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_power_bar(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    bar_data: list[BarData] = [
        BarData(label=r.platform, value=float(r.power_at_size)) for r in results if r.power_at_size is not None
    ]
    if not bar_data:
        return None
    # Higher Power@Size = better performance; mark accordingly (descending sort)
    sorted_data = sorted(bar_data, key=lambda x: x.value, reverse=True)
    sorted_data[0].is_best = True
    if len(sorted_data) > 1:
        sorted_data[-1].is_worst = True

    chart = BarChart(
        data=bar_data,
        title="Power@Size Comparison",
        metric_label="Power@Size",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_distribution_box(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    series_data: list[BoxPlotSeries] = []
    for r in results:
        timings = [q.execution_time_ms for q in r.queries if q.execution_time_ms is not None]
        if timings:
            series_data.append(BoxPlotSeries(name=r.platform, values=timings))
    if not series_data:
        return None

    chart = BoxPlot(
        series=series_data,
        title="Query Time Distribution",
        y_label="Execution Time (ms)",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_query_heatmap(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    platforms, query_ids, matrix = _build_query_matrix(results)
    if not query_ids:
        return None
    chart = Heatmap(
        matrix=matrix,
        row_labels=query_ids,
        col_labels=platforms,
        title="Query Execution Heatmap",
        value_label="ms",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_query_histogram(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    query_timings: dict[tuple[str, str], list[float]] = {}
    platforms_in_results = [r.platform for r in results]
    use_platform = len(set(platforms_in_results)) > 1

    for r in results:
        for q in r.queries:
            if q.execution_time_ms is not None:
                key = (r.platform, q.query_id)
                query_timings.setdefault(key, []).append(q.execution_time_ms)

    histogram_data: list[HistogramBar] = []
    for (platform, query_id), timings in query_timings.items():
        mean_latency = sum(timings) / len(timings)
        histogram_data.append(
            HistogramBar(label=query_id, value=mean_latency, platform=platform if use_platform else None)
        )
    if not histogram_data:
        return None

    query_means: dict[str, list[float]] = {}
    for bar in histogram_data:
        query_means.setdefault(bar.label, []).append(bar.value)
    avg_by_query = {qid: sum(v) / len(v) for qid, v in query_means.items()}
    if avg_by_query:
        best_qid = min(avg_by_query, key=avg_by_query.get)  # type: ignore[arg-type]
        worst_qid = max(avg_by_query, key=avg_by_query.get)  # type: ignore[arg-type]
        for bar in histogram_data:
            bar.is_best = bar.label == best_qid
            bar.is_worst = bar.label == worst_qid

    chart = Histogram(
        data=histogram_data,
        title="Query Latency Histogram",
        y_label="Execution Time (ms)",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_cost_scatter(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    scatter_data: list[ScatterPoint] = []
    for r in results:
        total_time = r.total_time_ms or 0
        cost = r.cost_total or 0
        performance = 3600000 / total_time if total_time > 0 else 0
        scatter_data.append(ScatterPoint(name=r.platform, x=cost, y=performance))
    if not scatter_data:
        return None

    chart = ScatterPlot(
        points=scatter_data,
        title="Cost vs Performance",
        x_label="Cost (USD)",
        y_label="Queries per Hour",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_time_series(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    line_data: list[LinePoint] = []
    for i, r in enumerate(results):
        total_time = r.total_time_ms or 0
        x_label = r.timestamp.strftime("%Y-%m-%d") if r.timestamp else f"Run {i + 1}"
        line_data.append(LinePoint(series=r.platform, x=x_label, y=total_time))
    if not line_data:
        return None

    chart = LineChart(
        points=line_data,
        title="Performance Trend",
        x_label="Run",
        y_label="Execution Time (ms)",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_comparison_bar(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    if len(results) != 2:
        return None
    from benchbox.core.visualization.ascii.comparison_bar import ComparisonBar, ComparisonBarData

    baseline, comparison = results
    b_map = {q.query_id: q.execution_time_ms for q in baseline.queries if q.execution_time_ms is not None}
    c_map = {q.query_id: q.execution_time_ms for q in comparison.queries if q.execution_time_ms is not None}
    shared_queries = sorted(set(b_map) & set(c_map))
    if not shared_queries:
        return None

    data = [
        ComparisonBarData(
            label=qid,
            baseline_value=b_map[qid],
            comparison_value=c_map[qid],
            baseline_name=baseline.platform,
            comparison_name=comparison.platform,
        )
        for qid in shared_queries
    ]
    chart = ComparisonBar(
        data=data,
        title=f"{baseline.platform} vs {comparison.platform}",
        metric_label="Execution Time (ms)",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_diverging_bar(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    if len(results) != 2:
        return None
    from benchbox.core.visualization.ascii.diverging_bar import DivergingBar, DivergingBarData

    baseline, comparison = results
    b_map = {q.query_id: q.execution_time_ms for q in baseline.queries if q.execution_time_ms is not None}
    c_map = {q.query_id: q.execution_time_ms for q in comparison.queries if q.execution_time_ms is not None}
    shared_queries = sorted(set(b_map) & set(c_map))
    if not shared_queries:
        return None

    data = []
    for qid in shared_queries:
        bv = b_map[qid]
        cv = c_map[qid]
        pct = ((cv - bv) / bv * 100) if bv > 0 else 0
        data.append(DivergingBarData(label=qid, pct_change=pct))

    chart = DivergingBar(
        data=data,
        title=f"{baseline.platform} vs {comparison.platform}: Changes",
        options=options,
        subtitle=subtitle,
    )
    return chart.render()


def _render_summary_box(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.summary_box import SummaryBox

    if len(results) == 2:
        stats = _build_comparison_summary_stats(results)
    elif len(results) == 1:
        stats = _build_single_summary_stats(results[0])
    else:
        return None

    chart = SummaryBox(stats=stats, options=options, subtitle=subtitle)
    return chart.render()


def _build_comparison_summary_stats(results: list[NormalizedResultLike]) -> Any:
    from benchbox.core.visualization.ascii.summary_box import SummaryStats

    baseline, comparison = results
    b_times = [q.execution_time_ms for q in baseline.queries if q.execution_time_ms and q.execution_time_ms > 0]
    c_times = [q.execution_time_ms for q in comparison.queries if q.execution_time_ms and q.execution_time_ms > 0]
    b_geo = math.exp(sum(math.log(t) for t in b_times) / len(b_times)) if b_times else None
    c_geo = math.exp(sum(math.log(t) for t in c_times) / len(c_times)) if c_times else None

    b_map = {q.query_id: q.execution_time_ms for q in baseline.queries if q.execution_time_ms is not None}
    c_map = {q.query_id: q.execution_time_ms for q in comparison.queries if q.execution_time_ms is not None}
    shared = sorted(set(b_map) & set(c_map))
    changes: list[tuple[str, float]] = []
    for qid in shared:
        bv = b_map[qid]
        cv = c_map[qid]
        pct = ((cv - bv) / bv * 100) if bv > 0 else 0
        changes.append((qid, pct))

    n_improved = sum(1 for _, p in changes if p < -_STABLE_THRESHOLD_PCT)
    n_regressed = sum(1 for _, p in changes if p > _STABLE_THRESHOLD_PCT)
    n_stable = len(changes) - n_improved - n_regressed
    sorted_changes = sorted(changes, key=lambda x: x[1])
    best = [(q, p) for q, p in sorted_changes if p < 0][:_SUMMARY_QUERY_COUNT]
    worst = [(q, p) for q, p in reversed(sorted_changes) if p > 0][:_SUMMARY_QUERY_COUNT]

    return SummaryStats(
        title=f"{baseline.platform} vs {comparison.platform} Summary",
        primary_baseline=b_geo,
        primary_comparison=c_geo,
        total_baseline=baseline.total_time_ms,
        total_comparison=comparison.total_time_ms,
        baseline_name=baseline.platform,
        comparison_name=comparison.platform,
        num_items=len(shared),
        num_improved=n_improved,
        num_stable=n_stable,
        num_regressed=n_regressed,
        best_items=best,
        worst_items=worst,
        **_SUMMARY_LABELS,
    )


def _build_single_summary_stats(result: Any) -> Any:
    from benchbox.core.visualization.ascii.summary_box import SummaryStats

    times = [q.execution_time_ms for q in result.queries if q.execution_time_ms and q.execution_time_ms > 0]
    geo = math.exp(sum(math.log(t) for t in times) / len(times)) if times else None
    sorted_by_time = sorted(
        [(q.query_id, q.execution_time_ms) for q in result.queries if q.execution_time_ms is not None],
        key=lambda x: x[1],
    )
    return SummaryStats(
        title=f"{result.platform} Summary",
        primary_value=geo,
        total_value=result.total_time_ms,
        num_items=len(result.queries),
        best_items=sorted_by_time[:_SUMMARY_QUERY_COUNT],
        worst_items=sorted_by_time[-_SUMMARY_QUERY_COUNT:][::-1] if len(sorted_by_time) > _SUMMARY_QUERY_COUNT else [],
        **_SUMMARY_LABELS,
    )


def _render_percentile_ladder(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.percentile_ladder import from_series

    platform_queries = _extract_platform_query_timings(results)
    if not platform_queries:
        return None
    chart = from_series(
        platform_queries,
        title="Percentile Latency by Platform",
        metric_label="ms",
        options=options,
    )
    chart.subtitle = subtitle
    return chart.render()


def _render_normalized_speedup(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.normalized_speedup import from_ratios

    platform_times = [(r.platform, r.total_time_ms) for r in results if r.total_time_ms and r.total_time_ms > 0]
    if len(platform_times) < 2:
        return None
    chart = from_ratios(
        platform_times,
        baseline="slowest",
        title="Normalized Performance",
        options=options,
    )
    chart.subtitle = subtitle
    return chart.render()


def _render_stacked_phase(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.stacked_bar import StackedBar, StackedBarData, StackedBarSegment

    data: list[StackedBarData] = []
    for r in results:
        phase_values = _extract_phase_timings_ms(getattr(r, "raw", {}) or {})
        if not phase_values:
            continue
        segments = [StackedBarSegment(phase_name=name, value=value) for name, value in phase_values]
        data.append(StackedBarData(label=r.platform, segments=segments))
    if not data:
        return None

    chart = StackedBar(
        data=data,
        title="Phase Breakdown by Platform",
        options=options,
        subtitle=subtitle,
        metric_label="ms",
    )
    return chart.render()


def _render_sparkline_table(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.sparkline_table import from_data as sparkline_from_data

    platforms = [r.platform for r in results]
    if not platforms:
        return None

    total_values = {r.platform: float(r.total_time_ms or 0) for r in results}
    geomean_values = {r.platform: _geomean_query_ms(r) for r in results}
    p95_values = {r.platform: _percentile_query_ms(r, 95) for r in results}

    metrics: list[tuple[str, dict[str, float], bool]] = [
        ("Total(ms)", total_values, False),
        ("GeoMean", geomean_values, False),
        ("P95(ms)", p95_values, False),
    ]
    if any(r.success_rate is not None for r in results):
        success = {r.platform: float((r.success_rate or 0) * 100.0) for r in results}
        metrics.append(("Success(%)", success, True))

    chart = sparkline_from_data(rows=platforms, metrics=metrics, title="Platform Comparison Overview", options=options)
    chart.subtitle = subtitle
    return chart.render()


def _render_cdf_chart(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.cdf_chart import from_series as cdf_from_series

    platform_queries = _extract_platform_query_timings(results)
    if not platform_queries:
        return None

    chart = cdf_from_series(platform_queries, title="Cumulative Distribution of Query Latency", options=options)
    chart.subtitle = subtitle
    return chart.render()


def _render_rank_table(results: list[NormalizedResultLike], options: Any, subtitle: str | None) -> str | None:
    from benchbox.core.visualization.ascii.rank_table import from_matrix

    platforms, query_ids, matrix = _build_query_matrix(results)
    if not query_ids or not platforms:
        return None

    chart = from_matrix(
        matrix=matrix,
        items=query_ids,
        groups=platforms,
        title="Query Rankings (1st = fastest)",
        options=options,
    )
    chart.subtitle = subtitle
    return chart.render()


_CHART_TYPE_DISPATCH: dict[str, Any] = {
    "performance_bar": _render_performance_bar,
    "power_bar": _render_power_bar,
    "distribution_box": _render_distribution_box,
    "query_heatmap": _render_query_heatmap,
    "query_histogram": _render_query_histogram,
    "cost_scatter": _render_cost_scatter,
    "time_series": _render_time_series,
    "comparison_bar": _render_comparison_bar,
    "diverging_bar": _render_diverging_bar,
    "summary_box": _render_summary_box,
    "percentile_ladder": _render_percentile_ladder,
    "normalized_speedup": _render_normalized_speedup,
    "stacked_phase": _render_stacked_phase,
    "sparkline_table": _render_sparkline_table,
    "cdf_chart": _render_cdf_chart,
    "rank_table": _render_rank_table,
}


def _extract_platform_query_timings(results: list[NormalizedResultLike]) -> list[tuple[str, list[float]]]:
    platform_queries: list[tuple[str, list[float]]] = []
    for result in results:
        values = [
            q.execution_time_ms for q in result.queries if q.execution_time_ms is not None and q.execution_time_ms > 0
        ]
        if values:
            platform_queries.append((result.platform, [float(v) for v in values]))
    return platform_queries


def _natural_sort_key(s: str) -> tuple[float, str]:
    """Sort key for natural ordering of query IDs (e.g. Q1, Q2, ... Q10)."""
    match = re.match(r"^(\D*)(\d+)(.*)$", s)
    if match:
        prefix, num, suffix = match.groups()
        return (float(num), prefix + suffix)
    return (float("inf"), s)


def _build_query_matrix(results: list[NormalizedResultLike]) -> tuple[list[str], list[str], list[list[float]]]:
    platforms = [r.platform for r in results]
    query_ids: list[str] = []
    platform_timings: dict[str, dict[str, float]] = {}
    for result in results:
        platform_timings[result.platform] = {}
        for query in result.queries:
            if query.execution_time_ms is not None:
                platform_timings[result.platform][query.query_id] = float(query.execution_time_ms)
                if query.query_id not in query_ids:
                    query_ids.append(query.query_id)

    query_ids.sort(key=_natural_sort_key)

    matrix: list[list[float]] = []
    for qid in query_ids:
        matrix.append([platform_timings.get(p, {}).get(qid, 0.0) for p in platforms])

    return platforms, query_ids, matrix


def _geomean_query_ms(result: Any) -> float:
    values = [q.execution_time_ms for q in result.queries if q.execution_time_ms and q.execution_time_ms > 0]
    if not values:
        return 0.0
    return float(math.exp(sum(math.log(v) for v in values) / len(values)))


def _percentile_query_ms(result: Any, pct: float) -> float:
    values = sorted(q.execution_time_ms for q in result.queries if q.execution_time_ms is not None)
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    k = (len(values) - 1) * (pct / 100.0)
    low = int(math.floor(k))
    high = int(math.ceil(k))
    if low == high:
        return float(values[low])
    return float(values[low] + (k - low) * (values[high] - values[low]))


def _extract_phase_timings_ms(raw: dict[str, Any]) -> list[tuple[str, float]]:
    for phase_map in _phase_timing_candidates(raw):
        parsed = [
            entry
            for phase_name, value in phase_map.items()
            if (entry := _normalize_phase_timing_entry(phase_name, value)) is not None
        ]
        if parsed:
            return parsed
    return []


def _phase_timing_candidates(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(raw.get("phases"), dict):
        candidates.append(raw["phases"])

    results_block = raw.get("results")
    if not isinstance(results_block, dict):
        return candidates
    timing = results_block.get("timing")
    if not isinstance(timing, dict):
        return candidates
    for key in _PHASE_TIMING_KEYS:
        phase_obj = timing.get(key)
        if isinstance(phase_obj, dict):
            candidates.append(phase_obj)
    return candidates


def _normalize_phase_timing_entry(phase_name: str, value: Any) -> tuple[str, float] | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric <= 0:
        return None
    if phase_name.endswith("_seconds") or phase_name.endswith("_s"):
        numeric *= 1000.0
    clean_name = phase_name.replace("_ms", "").replace("_seconds", "").replace("_s", "").replace("_", " ")
    return clean_name.title(), numeric
