"""Shared result-aware chart render orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from benchbox.core.visualization.chart_types import CHART_TYPE_DESCRIPTIONS, CHART_TYPE_SPECS
from benchbox.core.visualization.templates import ChartTemplate, get_template
from benchbox.core.visualization.utils import extract_chart_subtitle


@dataclass(frozen=True)
class RenderedChart:
    """One rendered chart entry."""

    chart_type: str
    content: str


@dataclass(frozen=True)
class SkippedChart:
    """One chart skipped or failed during a chart set render."""

    chart_type: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return an edge-serializable skip record."""
        result = {"chart_type": self.chart_type, "reason": self.reason}
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class RenderValidationError:
    """Validation error for an entire render request."""

    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChartRenderOutcome:
    """Structured result of rendering a chart list or template."""

    rendered: list[RenderedChart]
    skipped: list[SkippedChart]
    template: ChartTemplate | None = None
    validation_error: RenderValidationError | None = None
    strict_pairwise_validation: bool = True

    @property
    def chart_types_rendered(self) -> list[str]:
        return [chart.chart_type for chart in self.rendered]


def render_chart_set(
    results: list[Any],
    chart_types: Sequence[str] | None = None,
    *,
    template_name: str | None = None,
    options: Any | None = None,
    strict_pairwise_validation: bool = True,
) -> ChartRenderOutcome:
    """Render a chart list or template into a structured outcome."""
    from benchbox.core.visualization.ascii_api import ChartOptions, render_ascii_chart_from_results

    template: ChartTemplate | None = None
    if template_name is not None:
        template = get_template(template_name)
        chart_types = template.chart_types
    effective_strict_pairwise = strict_pairwise_validation and (template is None or template.name == "comparison")

    resolved_chart_types = list(chart_types or ("performance_bar",))
    invalid = [chart_type for chart_type in resolved_chart_types if chart_type not in CHART_TYPE_DESCRIPTIONS]
    if invalid:
        return ChartRenderOutcome(
            rendered=[],
            skipped=[],
            template=template,
            validation_error=RenderValidationError(
                f"Unknown chart type(s): {', '.join(invalid)}",
                {"invalid_chart_types": invalid, "valid_chart_types": list(CHART_TYPE_DESCRIPTIONS)},
            ),
            strict_pairwise_validation=effective_strict_pairwise,
        )

    pairwise_only = [
        chart_type for chart_type in resolved_chart_types if CHART_TYPE_SPECS[chart_type].requires_two_results
    ]
    if pairwise_only and len(results) != 2 and effective_strict_pairwise:
        return ChartRenderOutcome(
            rendered=[],
            skipped=[],
            template=template,
            validation_error=RenderValidationError(
                f"Chart type(s) require exactly 2 results: {', '.join(pairwise_only)}",
                {
                    "chart_types": pairwise_only,
                    "expected_result_count": 2,
                    "actual_result_count": len(results),
                },
            ),
            strict_pairwise_validation=effective_strict_pairwise,
        )

    opts = options or ChartOptions()
    subtitle = extract_chart_subtitle(results)
    rendered: list[RenderedChart] = []
    skipped: list[SkippedChart] = []

    for chart_type in resolved_chart_types:
        if CHART_TYPE_SPECS[chart_type].requires_two_results and len(results) != 2:
            skipped.append(
                SkippedChart(
                    chart_type=chart_type,
                    reason="requires exactly 2 results",
                    details={"expected_result_count": 2, "actual_result_count": len(results)},
                )
            )
            continue

        try:
            content = render_ascii_chart_from_results(results, chart_type, options=opts, subtitle=subtitle)
        except Exception as exc:
            skipped.append(
                SkippedChart(
                    chart_type=chart_type,
                    reason="renderer failed",
                    details={"exception_type": type(exc).__name__, "message": str(exc)},
                )
            )
            continue

        if content:
            rendered.append(RenderedChart(chart_type=chart_type, content=content))
        else:
            skipped.append(
                SkippedChart(
                    chart_type=chart_type,
                    reason=_not_applicable_reason(chart_type),
                    details={"result_count": len(results)},
                )
            )

    return ChartRenderOutcome(
        rendered=rendered,
        skipped=skipped,
        template=template,
        strict_pairwise_validation=effective_strict_pairwise,
    )


def _not_applicable_reason(chart_type: str) -> str:
    reasons = {
        "power_bar": "requires Power@Size metrics or power-run query timings",
        "distribution_box": "requires query timing data",
        "query_heatmap": "requires query timing data across results",
        "query_histogram": "requires query timing data",
        "cost_scatter": "requires cost data",
        "time_series": "requires timestamped results",
        "comparison_bar": "requires paired query timing data",
        "diverging_bar": "requires paired query timing data",
        "summary_box": "requires comparable query timing data",
        "percentile_ladder": "requires query timing data",
        "normalized_speedup": "requires comparable result timing data",
        "stacked_phase": "requires benchmark phase timing data",
        "sparkline_table": "requires comparable result timing data",
        "cdf_chart": "requires query timing data",
        "rank_table": "requires query timing data across results",
    }
    return reasons.get(chart_type, "not applicable for provided result data")
