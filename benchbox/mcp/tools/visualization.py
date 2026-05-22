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

from benchbox.core.visualization.ascii_api import render_ascii_chart_from_results
from benchbox.core.visualization.chart_types import CHART_TYPE_DESCRIPTIONS, CHART_TYPE_SPECS
from benchbox.core.visualization.utils import extract_chart_subtitle
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


def _render_single_ascii_chart(
    results: list,
    chart_type: str,
    opts: Any,
) -> str | None:
    """Render a single ASCII chart for the given chart type."""
    subtitle = extract_chart_subtitle(results)
    return render_ascii_chart_from_results(results, chart_type, options=opts, subtitle=subtitle)


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

        if template_name is not None:
            from benchbox.core.visualization.templates import get_template

            try:
                chart_template = get_template(template_name)
            except Exception:
                from benchbox.core.visualization.templates import list_templates

                available = [t.name for t in list_templates()]
                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"Unknown template: {template_name}",
                    details={"available_templates": available},
                )

            # Comparison template semantics are strictly pairwise.
            if chart_template.name == "comparison" and len(results) != 2:
                return make_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Template 'comparison' requires exactly 2 result files",
                    details={"template": "comparison", "expected_result_count": 2, "actual_result_count": len(results)},
                )

            chart_contents: list[str] = []
            chart_types_rendered: list[str] = []
            skipped_chart_types: list[dict[str, str]] = []
            separator = "\n" + "─" * 60 + "\n\n"

            for ct in chart_template.chart_types:
                content = _render_single_ascii_chart(results, ct, opts)
                if content:
                    chart_contents.append(content)
                    chart_types_rendered.append(ct)
                else:
                    skipped_chart_types.append(
                        {
                            "chart_type": ct,
                            "reason": "not applicable for provided inputs",
                        }
                    )

            if not chart_contents:
                return make_error(
                    ErrorCode.INTERNAL_ERROR,
                    "No charts could be generated from the template",
                    details={
                        "template": template_name,
                        "chart_types": list(chart_template.chart_types),
                        "skipped_chart_types": skipped_chart_types,
                    },
                )

            combined_content = separator.join(chart_contents)

            return {
                "status": "generated",
                "template": template_name,
                "template_description": chart_template.description,
                "chart_types": chart_types_rendered,
                "chart_count": len(chart_contents),
                "format": "ascii",
                "content": combined_content,
                "source_files": file_list,
                "skipped_chart_types": skipped_chart_types,
                "note": f"Template '{template_name}' rendered {len(chart_contents)} ASCII charts inline.",
            }

        content = _render_single_ascii_chart(results, chart_type, opts)

        spec = CHART_TYPE_SPECS.get(chart_type)
        if spec and spec.requires_two_results and len(results) != 2:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                f"Chart type '{chart_type}' requires exactly 2 result files",
                details={"chart_type": chart_type, "expected_result_count": 2, "actual_result_count": len(results)},
            )

        if content is None:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                f"Unsupported chart type for ASCII format: {chart_type}",
                details={"valid_types": list(CHART_TYPE_DESCRIPTIONS.keys())},
            )

        return {
            "status": "generated",
            "chart_type": chart_type,
            "format": "ascii",
            "content": content,
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
    num_results = len(results)
    total_queries = sum(len(r.queries) for r in results)
    platforms = sorted({r.platform for r in results})
    has_cost_data = any(r.cost_total is not None for r in results)
    has_query_data = any(r.queries for r in results)
    has_timestamps = any(r.timestamp is not None for r in results)
    has_phase_data = any(
        isinstance((getattr(r, "raw", {}) or {}).get("phases"), dict)
        or isinstance((((getattr(r, "raw", {}) or {}).get("results") or {}).get("timing") or {}).get("phases"), dict)
        for r in results
    )

    suggestions: list[dict[str, str]] = []

    suggestions.append(
        {
            "chart_type": "performance_bar",
            "reason": "Compare total runtime across platforms/configurations",
            "priority": "high",
        }
    )

    if has_query_data:
        suggestions.append(
            {
                "chart_type": "distribution_box",
                "reason": f"Show query time distribution ({total_queries} queries)",
                "priority": "high" if total_queries > 5 else "medium",
            }
        )

    if num_results >= 2 and has_query_data:
        suggestions.append(
            {
                "chart_type": "query_heatmap",
                "reason": f"Compare per-query performance across {len(platforms)} platform(s)",
                "priority": "high" if num_results == 2 else "medium",
            }
        )

    if has_query_data:
        suggestions.append(
            {
                "chart_type": "query_histogram",
                "reason": f"Show per-query latency bars ({total_queries} queries)"
                + (" - auto-splits for readability" if total_queries > 33 else ""),
                "priority": "high" if total_queries > 20 else "medium",
            }
        )
        suggestions.append(
            {
                "chart_type": "percentile_ladder",
                "reason": "Highlight P50/P90/P95/P99 tail-latency spread across platforms",
                "priority": "medium",
            }
        )
        suggestions.append(
            {
                "chart_type": "cdf_chart",
                "reason": "Visualize cumulative latency distribution differences across platforms",
                "priority": "medium",
            }
        )

    if has_cost_data:
        suggestions.append(
            {
                "chart_type": "cost_scatter",
                "reason": "Plot cost vs performance trade-offs",
                "priority": "high",
            }
        )

    if num_results >= 3 and has_timestamps:
        suggestions.append(
            {
                "chart_type": "time_series",
                "reason": f"Show performance trends over {num_results} runs",
                "priority": "medium",
            }
        )

    if num_results >= 2:
        suggestions.append(
            {
                "chart_type": "normalized_speedup",
                "reason": "Compare relative speedups against a baseline platform",
                "priority": "medium",
            }
        )
        suggestions.append(
            {
                "chart_type": "sparkline_table",
                "reason": "Compact overview of total, geo-mean, and tail latency metrics",
                "priority": "medium",
            }
        )

    if num_results >= 2 and has_query_data:
        suggestions.append(
            {
                "chart_type": "rank_table",
                "reason": "Rank each platform per query to highlight consistency of wins/losses",
                "priority": "medium",
            }
        )

    if num_results == 2 and has_query_data:
        suggestions.append(
            {
                "chart_type": "comparison_bar",
                "reason": "Compare two runs per query with paired bars and percent deltas",
                "priority": "high",
            }
        )
        suggestions.append(
            {
                "chart_type": "diverging_bar",
                "reason": "Show regression/improvement distribution around zero baseline",
                "priority": "high",
            }
        )
        suggestions.append(
            {
                "chart_type": "summary_box",
                "reason": "Summarize geo-mean, total time, and improved/regressed query counts",
                "priority": "high",
            }
        )

    if has_phase_data:
        suggestions.append(
            {
                "chart_type": "stacked_phase",
                "reason": "Break down runtime by benchmark phase across platforms",
                "priority": "medium",
            }
        )

    return suggestions


def _select_primary_chart(results: list) -> dict[str, str]:
    """Select the primary recommended chart type based on result characteristics."""
    num_results = len(results)
    has_query_data = any(r.queries for r in results)

    if num_results >= 2 and has_query_data:
        return {"chart_type": "query_heatmap", "reason": "Best for comparing per-query performance"}
    elif has_query_data:
        return {"chart_type": "distribution_box", "reason": "Best for understanding query time distribution"}
    else:
        return {"chart_type": "performance_bar", "reason": "Best general-purpose comparison chart"}


def _suggest_charts_impl(file_list: list[str], resolved_paths: list[Path]) -> dict[str, Any]:
    """Core implementation for the suggest_charts tool."""
    from benchbox.core.visualization.exceptions import VisualizationError
    from benchbox.core.visualization.result_plotter import ResultPlotter

    try:
        plotter = ResultPlotter.from_sources(resolved_paths)
        results = plotter.results

        suggestions = _build_chart_suggestions(results)
        primary = _select_primary_chart(results)

        num_results = len(results)
        platforms = sorted({r.platform for r in results})
        total_queries = sum(len(r.queries) for r in results)
        has_cost_data = any(r.cost_total is not None for r in results)
        has_timestamps = any(r.timestamp is not None for r in results)

        return {
            "suggestions": suggestions,
            "primary": primary,
            "data_profile": {
                "result_count": num_results,
                "platforms": platforms,
                "total_queries": total_queries,
                "has_cost_data": has_cost_data,
                "has_timestamps": has_timestamps,
            },
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
