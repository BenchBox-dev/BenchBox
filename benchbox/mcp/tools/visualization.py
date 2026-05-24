"""Visualization tools for BenchBox MCP server.

Provides tools for generating ASCII charts and visualizations from benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from benchbox.core.visualization.chart_types import CHART_TYPE_DESCRIPTIONS
from benchbox.core.visualization.orchestration import render_chart_set
from benchbox.core.visualization.suggestions import build_visualization_profile, recommend_charts, select_primary_chart
from benchbox.mcp.errors import ErrorCode, make_error
from benchbox.mcp.tools.path_utils import resolve_result_file_path

logger = logging.getLogger(__name__)

BENCHBOX_CHART_NAMESPACE_NOTE = (
    "BenchBox chart_type values are result-aware semantic chart IDs from "
    "benchbox.core.visualization.chart_types. They are not raw textcharts primitive "
    "tool names such as bar or heatmap."
)


def _semantic_chart_id_help() -> str:
    return ", ".join(CHART_TYPE_DESCRIPTIONS)


def _template_name_help() -> str:
    from benchbox.core.visualization.templates import list_templates

    return ", ".join(t.name for t in list_templates())


def _renderer_failure_error(
    skipped: Any | None,
    *,
    chart_type: str | None = None,
    template_name: str | None = None,
) -> dict[str, Any] | None:
    if skipped is None or skipped.reason != "renderer failed":
        return None

    message = skipped.details.get("message") or skipped.details.get("exception_type") or skipped.reason
    details: dict[str, Any] = {"skip": skipped.as_dict()}
    if chart_type is not None:
        details["chart_type"] = chart_type
    if template_name is not None:
        details["template"] = template_name
    if "exception_type" in skipped.details:
        details["exception_type"] = skipped.details["exception_type"]

    return make_error(
        ErrorCode.INTERNAL_ERROR,
        f"ASCII chart generation failed: {message}",
        details=details,
    )


MCP_SUGGEST_CHARTS_DESCRIPTION = (
    "Analyze BenchBox result files and suggest result-aware semantic chart IDs. "
    f"{BENCHBOX_CHART_NAMESPACE_NOTE} "
    f"Current semantic chart IDs: {_semantic_chart_id_help()}."
)

MCP_GENERATE_CHART_DESCRIPTION = (
    "Generate ASCII chart output from BenchBox result files using semantic chart IDs or chart templates. "
    f"{BENCHBOX_CHART_NAMESPACE_NOTE} "
    f"Current semantic chart IDs: {_semantic_chart_id_help()}. "
    f"Current templates: {_template_name_help()}."
)

# Tool annotations for read-only visualization info tools
VIZ_READONLY_ANNOTATIONS = ToolAnnotations(
    title="Visualization information",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

# Tool annotations for chart generation (creates files)
VIZ_GENERATE_ANNOTATIONS = ToolAnnotations(
    title="Generate visualization",
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _generate_ascii_chart(
    resolved_paths: list[Path],
    chart_type: str,
    file_list: list[str],
    template_name: str | None = None,
) -> dict[str, Any]:
    """Generate ASCII chart from result files.

    Returns chart content as inline string.
    """
    from benchbox.core.visualization.ascii_api import ChartOptions
    from benchbox.core.visualization.result_plotter import ResultPlotter

    try:
        plotter = ResultPlotter.from_sources(resolved_paths)
        results = plotter.results

        opts = ChartOptions(use_color=False)
        outcome = render_chart_set(
            results,
            [chart_type],
            template_name=template_name,
            options=opts,
            strict_pairwise_validation=True,
        )

        if outcome.validation_error:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                outcome.validation_error.message,
                details=outcome.validation_error.details,
            )

        if template_name is not None and outcome.template is not None:
            if outcome.template.name == "comparison" and len(results) != 2:
                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Template 'comparison' requires exactly 2 result files",
                    details={"template": "comparison", "expected_result_count": 2, "actual_result_count": len(results)},
                )

            separator = "\n" + "─" * 60 + "\n\n"

            if not outcome.rendered:
                renderer_failure = next(
                    (skipped for skipped in outcome.skipped if skipped.reason == "renderer failed"),
                    None,
                )
                if error := _renderer_failure_error(renderer_failure, template_name=template_name):
                    return error

                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    "No charts were applicable for the provided template inputs",
                    details={
                        "template": template_name,
                        "chart_types": list(outcome.template.chart_types),
                        "skipped_chart_types": [skipped.as_dict() for skipped in outcome.skipped],
                    },
                )

            combined_content = separator.join(chart.content for chart in outcome.rendered)

            return {
                "status": "generated",
                "template": template_name,
                "template_description": outcome.template.description,
                "chart_types": outcome.chart_types_rendered,
                "chart_count": len(outcome.rendered),
                "format": "ascii",
                "content": combined_content,
                "source_files": file_list,
                "skipped_chart_types": [skipped.as_dict() for skipped in outcome.skipped],
                "note": f"Template '{template_name}' rendered {len(outcome.rendered)} ASCII charts inline.",
            }

        if not outcome.rendered:
            skipped_chart = outcome.skipped[0] if outcome.skipped else None
            if error := _renderer_failure_error(skipped_chart, chart_type=chart_type):
                return error

            skipped = skipped_chart.as_dict() if skipped_chart is not None else {"chart_type": chart_type}
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                f"Chart type '{chart_type}' is not applicable for the provided result data",
                details={
                    "chart_type": chart_type,
                    "valid_types": list(CHART_TYPE_DESCRIPTIONS.keys()),
                    "skip": skipped,
                },
            )

        rendered = outcome.rendered[0]
        return {
            "status": "generated",
            "chart_type": rendered.chart_type,
            "format": "ascii",
            "content": rendered.content,
            "source_files": file_list,
            "note": "ASCII chart rendered inline. Copy the 'content' field to display.",
        }

    except Exception as e:
        logger.exception(f"ASCII chart generation failed: {e}")
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            f"ASCII chart generation failed: {e}",
            details={"exception_type": type(e).__name__},
        )


def _resolve_and_validate_result_files(
    file_list: list[str],
    results_dir: Path,
) -> dict[str, Any] | tuple[list[Path], list[str]]:
    """Resolve result file paths and validate they exist.

    Returns either an error dict or a tuple of (resolved_paths, file_list).
    """
    resolved_paths: list[Path] = []
    missing_files: list[str] = []

    for result_file in file_list:
        path = resolve_result_file_path(result_file, results_dir)
        if path:
            resolved_paths.append(path)
        else:
            missing_files.append(result_file)

    if missing_files:
        return make_error(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"Result file(s) not found: {', '.join(missing_files)}",
            details={"missing_files": missing_files},
        )

    if not resolved_paths:
        return make_error(ErrorCode.VALIDATION_ERROR, "No valid result files found")

    return resolved_paths, file_list


def _build_chart_suggestions(results: list) -> list[dict[str, str]]:
    """Build chart type suggestions based on result data characteristics."""
    return [recommendation.as_dict() for recommendation in recommend_charts(results)]


def _select_primary_chart(results: list) -> dict[str, str]:
    """Select the primary recommended chart type based on result characteristics."""
    recommendation = select_primary_chart(results)
    return {"chart_type": recommendation.chart_type, "reason": recommendation.reason}


def _suggest_charts_impl(file_list: list[str], resolved_paths: list[Path]) -> dict[str, Any]:
    """Core implementation for the suggest_charts tool."""
    from benchbox.core.visualization.exceptions import VisualizationError
    from benchbox.core.visualization.result_plotter import ResultPlotter

    try:
        plotter = ResultPlotter.from_sources(resolved_paths)
        results = plotter.results

        suggestions = _build_chart_suggestions(results)
        primary = _select_primary_chart(results)

        profile = build_visualization_profile(results)

        return {
            "suggestions": suggestions,
            "primary": primary,
            "data_profile": profile.as_mcp_dict(),
            "source_files": file_list,
        }

    except VisualizationError as e:
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            f"Could not analyze results: {e}",
            details={"result_files": file_list},
        )
    except Exception as e:
        logger.exception(f"Chart suggestion failed: {e}")
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            f"Chart suggestion failed: {e}",
            details={"exception_type": type(e).__name__},
        )


def _generate_chart_impl(
    file_list: list[str],
    resolved_paths: list[Path],
    chart_type: str,
    template: str | None,
) -> dict[str, Any]:
    """Core implementation for the generate_chart tool."""
    # Validate chart type if no template
    if template is None and chart_type not in CHART_TYPE_DESCRIPTIONS:
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown chart type: {chart_type}",
            details={"valid_chart_types": list(CHART_TYPE_DESCRIPTIONS.keys())},
        )

    # Validate template if provided
    if template is not None:
        from benchbox.core.visualization.templates import get_template, list_templates

        try:
            get_template(template)
        except Exception:
            available_templates = [t.name for t in list_templates()]
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                f"Unknown template: {template}",
                details={"available_templates": available_templates},
            )

    return _generate_ascii_chart(resolved_paths, chart_type, file_list, template_name=template)


def register_visualization_tools(
    mcp: FastMCP,
    *,
    results_dir: Path,
    charts_dir: Path,
) -> None:
    """Register visualization tools with the MCP server."""
    configured_results_dir = Path(results_dir)
    configured_charts_dir = Path(charts_dir)

    @mcp.tool(description=MCP_SUGGEST_CHARTS_DESCRIPTION, annotations=VIZ_READONLY_ANNOTATIONS)
    def suggest_charts(result_files: str) -> dict[str, Any]:
        """Analyze results and suggest appropriate chart types.

        Args:
            result_files: Comma-separated list of result filenames

        Returns:
            Chart suggestions with data profile and primary recommendation.
        """
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        if not file_list:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                "No result files provided",
                suggestion="Provide comma-separated list of result filenames",
            )

        result = _resolve_and_validate_result_files(file_list, configured_results_dir)
        if isinstance(result, dict):
            return result
        resolved_paths, file_list = result

        return _suggest_charts_impl(file_list, resolved_paths)

    @mcp.tool(description=MCP_GENERATE_CHART_DESCRIPTION, annotations=VIZ_GENERATE_ANNOTATIONS)
    def generate_chart(
        result_files: str,
        chart_type: str = "performance_bar",
        template: str | None = None,
        output_dir: str | None = None,
        format: str = "ascii",
    ) -> dict[str, Any]:
        """Generate chart(s) from benchmark results.

        Args:
            result_files: Comma-separated list of result filenames
            chart_type: Semantic BenchBox chart ID from CHART_TYPE_DESCRIPTIONS
            template: Template name from benchbox.core.visualization.templates
            output_dir: Custom output directory (relative to charts dir)
            format: Output format: 'ascii' for terminal-friendly text output

        Returns:
            Chart generation status with ASCII chart content if format='ascii'.

        ASCII Format Examples:
            - Single chart: generate_chart(result_files="run1.json", chart_type="performance_bar", format="ascii")
            - Template: generate_chart(result_files="run1.json,run2.json", template="head_to_head", format="ascii")
            - Comparison: generate_chart(result_files="duckdb.json,polars.json", chart_type="query_heatmap", format="ascii")

        ASCII charts are rendered inline and returned in the 'content' field. They include:
            - ANSI colors for terminal display (copy-paste preserves formatting)
            - Unicode box-drawing characters for clean visualization
            - Best/worst highlighting, legends, and scale indicators
        """
        file_list = [f.strip() for f in result_files.split(",") if f.strip()]
        if not file_list:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                "No result files provided",
                suggestion="Provide comma-separated list of result filenames",
            )

        _ = configured_charts_dir  # reserved for future chart file outputs
        result = _resolve_and_validate_result_files(file_list, configured_results_dir)
        if isinstance(result, dict):
            return result
        resolved_paths, file_list = result

        return _generate_chart_impl(file_list, resolved_paths, chart_type, template)
