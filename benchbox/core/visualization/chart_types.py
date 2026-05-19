"""Canonical ASCII chart type registry for visualization surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartTypeSpec:
    """Metadata for a supported chart type."""

    name: str
    description: str
    requires_two_results: bool = False


_CHART_SPECS: tuple[ChartTypeSpec, ...] = (
    ChartTypeSpec("performance_bar", "Bar chart comparing total runtime across platforms"),
    ChartTypeSpec(
        "power_bar",
        "Bar chart comparing TPC Power@Size; falls back to power-run query latency when no TPC metric exists",
    ),
    ChartTypeSpec("distribution_box", "Box plot showing query execution time distribution"),
    ChartTypeSpec("query_heatmap", "Heatmap comparing per-query execution times across platforms"),
    ChartTypeSpec(
        "query_histogram",
        "Per-query latency chart; uses horizontal bars for long query labels and vertical bars otherwise",
    ),
    ChartTypeSpec("cost_scatter", "Scatter plot of cost vs performance (requires cost data)"),
    ChartTypeSpec("time_series", "Line chart showing performance trends over time"),
    ChartTypeSpec(
        "comparison_bar",
        "Paired side-by-side bars comparing two runs per query with % change annotations",
        requires_two_results=True,
    ),
    ChartTypeSpec(
        "diverging_bar",
        "Centered-zero chart showing regression/improvement distribution sorted by magnitude",
        requires_two_results=True,
    ),
    ChartTypeSpec(
        "summary_box",
        "Bordered panel with aggregate stats (geo mean, total time, improved/regressed counts)",
    ),
    ChartTypeSpec("percentile_ladder", "Percentile ladder chart (P50/P90/P95/P99) across platforms"),
    ChartTypeSpec("normalized_speedup", "Normalized speedup chart relative to a selected baseline platform"),
    ChartTypeSpec("stacked_phase", "Stacked phase breakdown chart across benchmark execution phases"),
    ChartTypeSpec("sparkline_table", "Compact sparkline table of key metrics across platforms"),
    ChartTypeSpec("cdf_chart", "Cumulative distribution chart of per-query execution latency"),
    ChartTypeSpec("rank_table", "Per-query platform ranking table (1st=fastest)"),
)


CHART_TYPE_SPECS: dict[str, ChartTypeSpec] = {spec.name: spec for spec in _CHART_SPECS}
CHART_TYPE_DESCRIPTIONS: dict[str, str] = {spec.name: spec.description for spec in _CHART_SPECS}
ALL_CHART_TYPES: tuple[str, ...] = tuple(spec.name for spec in _CHART_SPECS)


def is_valid_chart_type(chart_type: str) -> bool:
    """Return whether a chart type is known."""
    return chart_type in CHART_TYPE_SPECS
