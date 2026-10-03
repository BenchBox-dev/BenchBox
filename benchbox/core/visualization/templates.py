from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from benchbox.core.visualization.exceptions import VisualizationError


@dataclass(frozen=True)
class ChartTemplate:
    name: str
    description: str
    chart_types: Sequence[str]
    formats: Sequence[str] = field(default_factory=lambda: ("ascii",))
    options: dict[str, Any] = field(default_factory=dict)


_TEMPLATES: dict[str, ChartTemplate] = {
    "default": ChartTemplate(
        name="default",
        description="Baseline set for a single benchmark run with phase breakdown and percentile analysis.",
        chart_types=(
            "performance_bar",
            "distribution_box",
            "query_histogram",
            "query_heatmap",
            "percentile_ladder",
            "stacked_phase",
        ),
        formats=("ascii",),
    ),
    "flagship": ChartTemplate(
        name="flagship",
        description="Multi-platform flagship comparison with full chart suite.",
        chart_types=(
            "performance_bar",
            "power_bar",
            "query_heatmap",
            "query_histogram",
            "cost_scatter",
            "distribution_box",
            "percentile_ladder",
            "normalized_speedup",
            "sparkline_table",
            "cdf_chart",
            "rank_table",
        ),
        formats=("ascii",),
    ),
    "head_to_head": ChartTemplate(
        name="head_to_head",
        description="Two-platform comparison with ranking and normalized speedup.",
        chart_types=(
            "performance_bar",
            "power_bar",
            "distribution_box",
            "query_histogram",
            "query_heatmap",
            "normalized_speedup",
            "rank_table",
        ),
        formats=("ascii",),
    ),
    "trends": ChartTemplate(
        name="trends",
        description="Multi-period performance trend lines with regression overlay.",
        chart_types=("time_series", "power_bar", "performance_bar"),
        formats=("ascii",),
    ),
    "cost_optimization": ChartTemplate(
        name="cost_optimization",
        description="Cost breakdown and price/performance frontier.",
        chart_types=("cost_scatter", "performance_bar"),
        formats=("ascii",),
    ),
    "comparison": ChartTemplate(
        name="comparison",
        description="Two-run comparison report with paired bars, diverging distribution, and summary box.",
        chart_types=("comparison_bar", "diverging_bar", "summary_box"),
        formats=("ascii",),
    ),
    "latency_deep_dive": ChartTemplate(
        name="latency_deep_dive",
        description="Latency-focused bundle for distribution, tails, and per-query hotspots.",
        chart_types=(
            "distribution_box",
            "query_histogram",
            "percentile_ladder",
            "cdf_chart",
            "query_heatmap",
        ),
        formats=("ascii",),
    ),
    "regression_triage": ChartTemplate(
        name="regression_triage",
        description="Two-run triage pack to pinpoint regressions and summarize impact quickly.",
        chart_types=("power_bar", "comparison_bar", "diverging_bar", "summary_box", "rank_table"),
        formats=("ascii",),
    ),
    "executive_summary": ChartTemplate(
        name="executive_summary",
        description="Compact high-level view of total performance, relative speedups, and key metrics.",
        chart_types=("performance_bar", "power_bar", "normalized_speedup", "sparkline_table", "summary_box"),
        formats=("ascii",),
    ),
}


def get_template(name: str) -> ChartTemplate:
    normalized = name.lower().replace("-", "_")
    try:
        return _TEMPLATES[normalized]
    except KeyError as exc:
        raise VisualizationError(
            f"Unknown chart template '{name}'. Available: {', '.join(sorted(_TEMPLATES))}"
        ) from exc


def list_templates() -> list[ChartTemplate]:
    return list(_TEMPLATES.values())
