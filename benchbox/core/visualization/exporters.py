"""Export helpers for BenchBox visualizations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbox.core.visualization.exceptions import VisualizationError


def export_ascii(
    ascii_content: str,
    output_dir: str | Path,
    base_name: str,
    format: str = "txt",
) -> Path:
    """Export ASCII chart content to a text file.

    Args:
        ascii_content: The rendered ASCII chart string.
        output_dir: Directory to write files into.
        base_name: Base filename without extension.
        format: Output format (txt or ascii).

    Returns:
        Path to the exported file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extension = "txt" if format in ("ascii", "txt") else format
    target = output_path / f"{base_name}.{extension}"

    try:
        target.write_text(ascii_content, encoding="utf-8")
    except Exception as exc:
        raise VisualizationError(f"Failed to write ASCII chart: {exc}") from exc

    return target


def _build_performance_bar(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import BarChart, BarData

    converted = [
        item
        if isinstance(item, BarData)
        else BarData(
            label=getattr(item, "label", str(item)),
            value=getattr(item, "value", 0),
            group=getattr(item, "group", None),
            error=getattr(item, "error", None),
            is_best=getattr(item, "is_best", False),
            is_worst=getattr(item, "is_worst", False),
        )
        for item in data
    ]
    return BarChart(data=converted, title=title, options=opts, **kwargs)


def _build_distribution_box(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import BoxPlot, BoxPlotSeries

    converted = [
        item
        if isinstance(item, BoxPlotSeries)
        else BoxPlotSeries(
            name=getattr(item, "name", str(item)),
            values=list(getattr(item, "values", [])),
        )
        for item in data
    ]
    return BoxPlot(series=converted, title=title, options=opts, **kwargs)


def _build_query_heatmap(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import Heatmap

    if not isinstance(data, dict):
        raise VisualizationError("Heatmap data must be a dict with matrix, queries, platforms")
    kwargs.setdefault("value_label", "ms")
    return Heatmap(
        matrix=data.get("matrix", []),
        row_labels=data.get("queries", data.get("row_labels", [])),
        col_labels=data.get("platforms", data.get("col_labels", [])),
        title=title,
        options=opts,
        **kwargs,
    )


def _build_query_histogram(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import Histogram, HistogramBar

    converted = [
        item
        if isinstance(item, HistogramBar)
        else HistogramBar(
            label=getattr(item, "label", str(item)),
            value=getattr(item, "value", 0),
            platform=getattr(item, "platform", None),
            error=getattr(item, "error", None),
            is_best=getattr(item, "is_best", False),
            is_worst=getattr(item, "is_worst", False),
        )
        for item in data
    ]
    kwargs.setdefault("y_label", "Execution Time (ms)")
    return Histogram(data=converted, title=title, options=opts, **kwargs)


def _build_cost_scatter(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import ScatterPlot, ScatterPoint

    converted = [
        item
        if isinstance(item, ScatterPoint)
        else ScatterPoint(
            name=getattr(item, "name", str(item)),
            x=getattr(item, "x", 0),
            y=getattr(item, "y", 0),
        )
        for item in data
    ]
    kwargs.setdefault("x_label", "Cost (USD)")
    kwargs.setdefault("y_label", "Performance")
    return ScatterPlot(points=converted, title=title, options=opts, **kwargs)


def _build_time_series(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import LineChart, LinePoint

    converted = [
        item
        if isinstance(item, LinePoint)
        else LinePoint(
            series=getattr(item, "series", "Series"),
            x=getattr(item, "x", 0),
            y=getattr(item, "y", 0),
            label=getattr(item, "label", None),
        )
        for item in data
    ]
    return LineChart(points=converted, title=title, options=opts, **kwargs)


def _build_comparison_bar(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import ComparisonBar, ComparisonBarData

    converted = [
        item
        if isinstance(item, ComparisonBarData)
        else ComparisonBarData(
            label=getattr(item, "label", str(item)),
            baseline_value=getattr(item, "baseline_value", 0),
            comparison_value=getattr(item, "comparison_value", 0),
            baseline_name=getattr(item, "baseline_name", "Baseline"),
            comparison_name=getattr(item, "comparison_name", "Comparison"),
        )
        for item in data
    ]
    kwargs.setdefault("metric_label", "Execution Time (ms)")
    return ComparisonBar(data=converted, title=title, options=opts, **kwargs)


def _build_diverging_bar(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import DivergingBar, DivergingBarData

    converted = [
        item
        if isinstance(item, DivergingBarData)
        else DivergingBarData(
            label=getattr(item, "label", str(item)),
            pct_change=getattr(item, "pct_change", 0),
        )
        for item in data
    ]
    return DivergingBar(data=converted, title=title, options=opts, **kwargs)


def _build_percentile_ladder(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import PercentileData, PercentileLadder

    converted = [
        item
        if isinstance(item, PercentileData)
        else PercentileData(
            name=getattr(item, "name", str(item)),
            p50=getattr(item, "p50", 0),
            p90=getattr(item, "p90", 0),
            p95=getattr(item, "p95", 0),
            p99=getattr(item, "p99", 0),
        )
        for item in data
    ]
    kwargs.setdefault("metric_label", "ms")
    return PercentileLadder(data=converted, title=title, options=opts, **kwargs)


def _build_normalized_speedup(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import NormalizedSpeedup, SpeedupData

    converted = [
        item
        if isinstance(item, SpeedupData)
        else SpeedupData(
            name=getattr(item, "name", str(item)),
            ratio=getattr(item, "ratio", 1.0),
            is_baseline=getattr(item, "is_baseline", False),
        )
        for item in data
    ]
    return NormalizedSpeedup(data=converted, title=title, options=opts, **kwargs)


def _build_stacked_phase(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import StackedBar, StackedBarData, StackedBarSegment

    converted = []
    for item in data:
        if isinstance(item, StackedBarData):
            converted.append(item)
        else:
            segments = [
                StackedBarSegment(
                    phase_name=getattr(s, "phase_name", str(s)),
                    value=getattr(s, "value", 0),
                    color=getattr(s, "color", None),
                )
                for s in getattr(item, "segments", [])
            ]
            converted.append(
                StackedBarData(
                    label=getattr(item, "label", str(item)),
                    segments=segments,
                    total=getattr(item, "total", None),
                )
            )
    kwargs.setdefault("metric_label", "ms")
    return StackedBar(data=converted, title=title, options=opts, **kwargs)


def _build_sparkline_table(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import SparklineTable, SparklineTableData

    if not isinstance(data, SparklineTableData):
        raise VisualizationError("sparkline_table data must be a SparklineTableData instance")
    return SparklineTable(data=data, title=title, options=opts, **kwargs)


def _build_cdf_chart(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import CDFChart, CDFSeriesData

    converted = [
        item
        if isinstance(item, CDFSeriesData)
        else CDFSeriesData(
            name=getattr(item, "name", str(item)),
            values=list(getattr(item, "values", [])),
        )
        for item in data
    ]
    return CDFChart(data=converted, title=title, options=opts, **kwargs)


def _build_rank_table(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import RankTable, RankTableData

    if not isinstance(data, RankTableData):
        raise VisualizationError("rank_table data must be a RankTableData instance")
    return RankTable(data=data, title=title, options=opts, **kwargs)


def _build_summary_box(data: Any, title: str | None, opts: Any, kwargs: dict) -> Any:
    from benchbox.core.visualization.ascii_api import SummaryBox, SummaryStats

    if isinstance(data, SummaryStats):
        stats = data
    elif isinstance(data, dict):
        field_names = [f.name for f in SummaryStats.__dataclass_fields__.values()]
        stats_payload = {
            "title": title or "Benchmark Summary",
            "primary_label": "Geo Mean",
            "secondary_label": "Median",
            "total_label": "Total",
            "count_label": "Queries",
        }
        stats_payload.update({k: v for k, v in data.items() if k in field_names})
        stats = SummaryStats(**stats_payload)
    else:
        stats = SummaryStats(
            title=title or "Benchmark Summary",
            primary_label="Geo Mean",
            secondary_label="Median",
            total_label="Total",
            count_label="Queries",
        )
    return SummaryBox(stats=stats, options=opts)


_CHART_BUILDERS: dict[str, Any] = {
    "performance_bar": _build_performance_bar,
    "distribution_box": _build_distribution_box,
    "query_heatmap": _build_query_heatmap,
    "query_histogram": _build_query_histogram,
    "cost_scatter": _build_cost_scatter,
    "time_series": _build_time_series,
    "comparison_bar": _build_comparison_bar,
    "diverging_bar": _build_diverging_bar,
    "percentile_ladder": _build_percentile_ladder,
    "normalized_speedup": _build_normalized_speedup,
    "stacked_phase": _build_stacked_phase,
    "sparkline_table": _build_sparkline_table,
    "cdf_chart": _build_cdf_chart,
    "rank_table": _build_rank_table,
    "summary_box": _build_summary_box,
}


def render_ascii_chart(
    chart_type: str,
    data: Any,
    title: str | None = None,
    options: Any | None = None,
    **kwargs: Any,
) -> str:
    """Render data as an ASCII chart.

    Args:
        chart_type: Type of chart (performance_bar, distribution_box, query_heatmap,
                    query_histogram, cost_scatter, time_series, comparison_bar,
                    diverging_bar, summary_box).
        data: Chart data in the appropriate format for the chart type.
        title: Optional chart title.
        options: ChartOptions instance.
        **kwargs: Additional arguments passed to the chart constructor.

    Returns:
        Rendered ASCII chart as a string.

    Raises:
        VisualizationError: If chart type is not supported.
    """
    from benchbox.core.visualization.ascii_api import ChartOptions

    opts = options or ChartOptions()

    builder = _CHART_BUILDERS.get(chart_type)
    if builder is None:
        raise VisualizationError(f"Unsupported ASCII chart type: {chart_type}")

    chart = builder(data, title, opts, kwargs)
    return chart.render()
