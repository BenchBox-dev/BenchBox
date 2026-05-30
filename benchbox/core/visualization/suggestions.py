"""Shared result-aware chart recommendation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchbox.core.visualization.chart_types import CHART_TYPE_DESCRIPTIONS, CHART_TYPE_SPECS
from benchbox.core.visualization.utils import is_power_run_result


@dataclass(frozen=True)
class VisualizationDataProfile:
    """Normalized result-set facts used for chart applicability decisions."""

    result_count: int
    platforms: tuple[str, ...]
    total_queries: int
    has_query_data: bool
    has_power_data: bool
    has_cost_data: bool
    has_timestamps: bool
    has_phase_data: bool
    pairwise_eligible: bool

    def as_mcp_dict(self) -> dict[str, Any]:
        """Return the MCP-compatible profile shape."""
        return {
            "result_count": self.result_count,
            "platforms": list(self.platforms),
            "total_queries": self.total_queries,
            "has_cost_data": self.has_cost_data,
            "has_timestamps": self.has_timestamps,
            "has_power_data": self.has_power_data,
            "has_phase_data": self.has_phase_data,
        }


@dataclass(frozen=True)
class ChartRecommendation:
    """Structured chart recommendation."""

    chart_type: str
    reason: str
    priority: str
    applicability: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the MCP-compatible recommendation shape."""
        result = {
            "chart_type": self.chart_type,
            "reason": self.reason,
            "priority": self.priority,
        }
        if self.applicability:
            result["applicability"] = self.applicability
        return result


def build_visualization_profile(results: list[Any]) -> VisualizationDataProfile:
    """Build a shared profile for result-aware chart decisions."""
    total_queries = sum(len(getattr(result, "queries", []) or []) for result in results)
    has_phase_data = any(
        isinstance((getattr(result, "raw", {}) or {}).get("phases"), dict)
        or isinstance(
            ((((getattr(result, "raw", {}) or {}).get("results") or {}).get("timing") or {}).get("phases")),
            dict,
        )
        for result in results
    )
    has_power_data = any(
        getattr(result, "power_at_size", None) is not None or is_power_run_result(result) for result in results
    )

    return VisualizationDataProfile(
        result_count=len(results),
        platforms=tuple(sorted({str(getattr(result, "platform", "unknown")) for result in results})),
        total_queries=total_queries,
        has_query_data=total_queries > 0,
        has_power_data=has_power_data,
        has_cost_data=any(getattr(result, "cost_total", None) is not None for result in results),
        has_timestamps=any(getattr(result, "timestamp", None) is not None for result in results),
        has_phase_data=has_phase_data,
        pairwise_eligible=len(results) == 2,
    )


def recommend_charts(results: list[Any]) -> list[ChartRecommendation]:
    """Recommend semantic BenchBox chart IDs for normalized results."""
    profile = build_visualization_profile(results)
    recommendations: list[ChartRecommendation] = []

    def add(chart_type: str, reason: str, priority: str, **applicability: Any) -> None:
        spec = CHART_TYPE_SPECS.get(chart_type)
        if chart_type not in CHART_TYPE_DESCRIPTIONS:
            return
        if spec and spec.requires_two_results and not profile.pairwise_eligible:
            return
        recommendations.append(
            ChartRecommendation(
                chart_type=chart_type,
                reason=reason,
                priority=priority,
                applicability=applicability or None,
            )
        )

    add("performance_bar", "Compare total runtime across platforms/configurations", "high")

    if profile.has_power_data:
        add("power_bar", "Compare TPC Power@Size or power-run query latency", "high")

    if profile.has_query_data:
        add(
            "distribution_box",
            f"Show query time distribution ({profile.total_queries} queries)",
            "high" if profile.total_queries > 5 else "medium",
        )

    if profile.result_count >= 2 and profile.has_query_data:
        add(
            "query_heatmap",
            f"Compare per-query performance across {len(profile.platforms)} platform(s)",
            "high" if profile.result_count == 2 else "medium",
        )

    if profile.has_query_data:
        add(
            "query_histogram",
            f"Show per-query latency bars ({profile.total_queries} queries)"
            + (" - auto-splits for readability" if profile.total_queries > 33 else ""),
            "high" if profile.total_queries > 20 else "medium",
        )
        add("percentile_ladder", "Highlight P50/P90/P95/P99 tail-latency spread across platforms", "medium")
        add("cdf_chart", "Visualize cumulative latency distribution differences across platforms", "medium")

    if profile.has_cost_data:
        add("cost_scatter", "Plot cost vs performance trade-offs", "high")

    if profile.result_count >= 3 and profile.has_timestamps:
        add("time_series", f"Show performance trends over {profile.result_count} runs", "medium")

    if profile.result_count >= 2:
        add("normalized_speedup", "Compare relative speedups against a baseline platform", "medium")
        add("sparkline_table", "Compact overview of total, geo-mean, and tail latency metrics", "medium")

    if profile.result_count >= 2 and profile.has_query_data:
        add("rank_table", "Rank each platform per query to highlight consistency of wins/losses", "medium")

    if profile.pairwise_eligible and profile.has_query_data:
        add("comparison_bar", "Compare two runs per query with paired bars and percent deltas", "high")
        add("diverging_bar", "Show regression/improvement distribution around zero baseline", "high")
        add("summary_box", "Summarize geo-mean, total time, and improved/regressed query counts", "high")

    if profile.has_phase_data:
        add("stacked_phase", "Break down runtime by benchmark phase across platforms", "medium")

    return recommendations


def select_primary_chart(results: list[Any]) -> ChartRecommendation:
    """Select the primary chart recommendation."""
    profile = build_visualization_profile(results)
    if profile.has_power_data:
        return ChartRecommendation("power_bar", "Best for power-run or Power@Size results", "high")
    if profile.result_count >= 2 and profile.has_query_data:
        return ChartRecommendation("query_heatmap", "Best for comparing per-query performance", "high")
    if profile.has_query_data:
        return ChartRecommendation("distribution_box", "Best for understanding query time distribution", "high")
    return ChartRecommendation("performance_bar", "Best general-purpose comparison chart", "high")
