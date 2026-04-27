"""Results tools for BenchBox MCP server.

Provides tools for retrieving, comparing, and exporting benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from benchbox.core.results.loader import ResultLoadError, UnsupportedSchemaError, load_result_file
from benchbox.mcp.errors import ErrorCode, make_error
from benchbox.mcp.tools.path_utils import resolve_result_file_path

logger = logging.getLogger(__name__)

# Tool annotations for read-only results tools
RESULTS_READONLY_ANNOTATIONS = ToolAnnotations(
    title="Read benchmark results",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

# Tool annotations for export (creates files)
EXPORT_ANNOTATIONS = ToolAnnotations(
    title="Export benchmark results",
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def register_results_tools(mcp: FastMCP, *, results_dir: Path) -> None:
    """Register results tools with the MCP server."""
    configured_results_dir = Path(results_dir)

    @mcp.tool(annotations=RESULTS_READONLY_ANNOTATIONS)
    def get_results(
        result_file: str | None = None,
        format: str = "details",
        output_path: str | None = None,
        limit: int = 10,
        platform: str | None = None,
        benchmark: str | None = None,
        include_queries: bool = True,
    ) -> dict[str, Any]:
        """Get benchmark results or list recent runs.

        Args:
            result_file: Result filename (omit to list recent runs)
            format: Output format: 'list', 'details', 'json', 'csv', 'html', 'text', 'markdown'
            output_path: File path for export (relative to results dir)
            limit: Max results when listing (default: 10)
            platform: Filter by platform name (for listing)
            benchmark: Filter by benchmark name (for listing)
            include_queries: Include per-query details (default: True)

        Returns:
            List of runs, full results, or exported content.
        """
        # If no result_file, list recent runs
        if result_file is None or format == "list":
            return _list_recent_runs_impl(limit, platform, benchmark, configured_results_dir)

        # Get results for specific file
        results = _get_results_impl(result_file, include_queries, results_dir=configured_results_dir)
        if "error" in results:
            return results

        # Handle different output formats
        format_lower = format.lower()
        if format_lower == "details":
            return results
        elif format_lower in ("json", "csv", "html"):
            return _export_results_impl(results, result_file, format_lower, output_path, configured_results_dir)
        elif format_lower in ("text", "markdown"):
            return _export_summary_impl(results, format_lower)
        else:
            return make_error(
                ErrorCode.VALIDATION_INVALID_FORMAT,
                f"Invalid format: {format}",
                details={"valid_formats": ["list", "details", "json", "csv", "html", "text", "markdown"]},
            )


def _list_recent_runs_impl(
    limit: int,
    platform: str | None,
    benchmark: str | None,
    results_dir: Path,
) -> dict[str, Any]:
    """List recent benchmark runs."""
    if not results_dir.exists():
        return {"runs": [], "count": 0, "message": f"No results directory found at {results_dir}"}

    result_files = [
        path
        for path in results_dir.glob("*.json")
        if not path.name.endswith(".plans.json") and not path.name.endswith(".tuning.json")
    ]

    runs = []
    for file_path in sorted(result_files, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            run_platform = data.get("platform", {}).get("name", "unknown")
            benchmark_block = data.get("benchmark", {}) if isinstance(data.get("benchmark"), dict) else {}
            run_benchmark = benchmark_block.get("id", "unknown")
            run_scale = benchmark_block.get("scale_factor")
            run_timestamp = data.get("run", {}).get("timestamp", file_path.stat().st_mtime)
            run_execution_id = data.get("run", {}).get("id", "unknown")

            if platform and platform.lower() not in run_platform.lower():
                continue
            if benchmark and benchmark.lower() not in run_benchmark.lower():
                continue

            run_info = {
                "file": file_path.name,
                "platform": run_platform,
                "benchmark": run_benchmark,
                "scale_factor": run_scale if run_scale is not None else "unknown",
                "timestamp": run_timestamp,
                "execution_id": run_execution_id,
            }

            if "summary" in data:
                summary = data["summary"]
                timing = summary.get("timing", {})
                queries = summary.get("queries", {})
                run_info["summary"] = {
                    "total_queries": queries.get("total"),
                    "total_runtime_ms": timing.get("total_ms"),
                }

            runs.append(run_info)

            if len(runs) >= limit:
                break

        except Exception as e:
            logger.warning(f"Could not parse result file {file_path}: {e}")
            continue

    return {
        "runs": runs,
        "count": len(runs),
        "total_available": len(result_files),
        "filters_applied": {"platform": platform, "benchmark": benchmark, "limit": limit},
    }


def _get_results_impl(result_file: str, include_queries: bool = True, *, results_dir: Path) -> dict[str, Any]:
    """Core implementation for getting benchmark results."""
    if ".." in result_file or result_file.startswith("/") or result_file.startswith("\\"):
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid result file path",
            details={"requested_file": result_file},
        )

    file_path = resolve_result_file_path(result_file, results_dir)

    if file_path is None or not file_path.exists():
        return make_error(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"Result file not found: {result_file}",
            details={"requested_file": result_file},
            suggestion="Use get_results() without result_file to list available files",
        )

    try:
        _, data = load_result_file(file_path)
        response: dict[str, Any] = data
        response["file"] = file_path.name
        if not include_queries and "queries" in response:
            response = dict(response)
            response.pop("queries", None)
        return response

    except FileNotFoundError:
        return make_error(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"Result file not found: {result_file}",
            details={"requested_file": result_file},
        )
    except (ResultLoadError, UnsupportedSchemaError) as e:
        return make_error(
            ErrorCode.RESOURCE_INVALID_FORMAT,
            f"Invalid result file: {e}",
            details={"file": result_file, "parse_error": str(e)},
        )
    except Exception as e:
        return make_error(
            ErrorCode.INTERNAL_ERROR,
            f"Could not read result file: {e}",
            details={"file": result_file, "exception_type": type(e).__name__},
        )


def _export_results_impl(
    results: dict[str, Any],
    result_file: str,
    format: str,
    output_path: str | None,
    results_dir: Path,
) -> dict[str, Any]:
    """Export results to JSON, CSV, or HTML format."""
    content: str = ""

    if format == "json":
        content = json.dumps(results, indent=2, default=str)

    elif format == "csv":
        output = io.StringIO()
        queries = results.get("queries", [])

        if queries:
            fieldnames = ["query_id", "runtime_ms", "status"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for q in queries:
                writer.writerow(
                    {
                        "query_id": q.get("id", ""),
                        "runtime_ms": q.get("ms", ""),
                        "status": q.get("status", ""),
                    }
                )
            content = output.getvalue()
        else:
            content = "query_id,runtime_ms,status\n"

    elif format == "html":
        content = _generate_html_report(results)

    # Write to file if output_path provided
    if output_path:
        if ".." in output_path or output_path.startswith("/"):
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                "Invalid output path",
                details={"path": output_path},
                suggestion="Use a relative path without '..' components",
            )

        output_file = results_dir / output_path
        try:
            output_file.resolve().relative_to(results_dir.resolve())
        except ValueError:
            return make_error(
                ErrorCode.VALIDATION_ERROR,
                "Output path escapes allowed directory",
                details={"path": output_path},
            )

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content)
            return {
                "status": "exported",
                "format": format,
                "source_file": result_file,
                "output_path": str(output_file),
                "size_bytes": len(content),
            }
        except Exception as e:
            return make_error(
                ErrorCode.INTERNAL_ERROR,
                f"Failed to write output file: {e}",
                details={"output_path": output_path, "exception_type": type(e).__name__},
            )

    return {
        "status": "exported",
        "format": format,
        "source_file": result_file,
        "content": content if len(content) < 50000 else content[:50000] + "\n... (truncated)",
        "size_bytes": len(content),
        "truncated": len(content) >= 50000,
    }


def _generate_html_report(results: dict[str, Any]) -> str:
    """Generate HTML report with XSS prevention."""
    esc = html.escape
    benchmark = results.get("benchmark", {})
    platform_type = esc(str(results.get("platform", {}).get("name", "Unknown")))
    benchmark_name = esc(str(benchmark.get("name") or benchmark.get("id") or "Unknown"))
    scale_factor = esc(str(benchmark.get("scale_factor", "Unknown")))
    execution_id = esc(str(results.get("run", {}).get("id", "Unknown")))

    html_parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        f"<title>Benchmark Results: {benchmark_name}</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; }",
        "h1 { color: #333; }",
        "table { border-collapse: collapse; width: 100%; margin-top: 20px; }",
        "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
        "th { background-color: #4CAF50; color: white; }",
        "tr:nth-child(even) { background-color: #f2f2f2; }",
        ".summary { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }",
        "</style>",
        "</head><body>",
        f"<h1>Benchmark Results: {benchmark_name}</h1>",
        "<div class='summary'>",
        f"<p><strong>Platform:</strong> {platform_type}</p>",
        f"<p><strong>Scale Factor:</strong> {scale_factor}</p>",
        f"<p><strong>Execution ID:</strong> {execution_id}</p>",
    ]

    if "summary" in results:
        summary = results["summary"]
        queries_summary = summary.get("queries", {})
        timing = summary.get("timing", {})
        total_queries = esc(str(queries_summary.get("total", "N/A")))
        total_runtime = esc(str(timing.get("total_ms", "N/A")))
        html_parts.append(f"<p><strong>Total Queries:</strong> {total_queries}</p>")
        html_parts.append(f"<p><strong>Total Runtime:</strong> {total_runtime} ms</p>")

    html_parts.append("</div>")

    queries = results.get("queries", [])
    if queries:
        html_parts.extend(
            [
                "<h2>Query Results</h2>",
                "<table>",
                "<tr><th>Query</th><th>Runtime (ms)</th><th>Status</th></tr>",
            ]
        )
        for q in queries:
            q_id = esc(str(q.get("id", "")))
            q_runtime = esc(str(q.get("ms", "")))
            q_status = esc(str(q.get("status", "")))
            html_parts.append(f"<tr><td>{q_id}</td><td>{q_runtime}</td><td>{q_status}</td></tr>")
        html_parts.append("</table>")

    html_parts.extend(["</body></html>"])
    return "\n".join(html_parts)


def _export_summary_impl(results: dict[str, Any], format: str) -> dict[str, Any]:
    """Export formatted summary of benchmark results."""
    lines = []

    if format == "markdown":
        benchmark = results.get("benchmark", {})
        benchmark_name = benchmark.get("name") or benchmark.get("id") or "Unknown"
        lines.append(f"# Benchmark Results: {benchmark_name}")
        lines.append("")
        lines.append(f"**Platform**: {results.get('platform', {}).get('name', 'Unknown')}")
        lines.append(f"**Scale Factor**: {benchmark.get('scale_factor', 'Unknown')}")
        lines.append(f"**Execution ID**: {results.get('run', {}).get('id', 'Unknown')}")
        lines.append("")

        if "summary" in results:
            summary = results["summary"]
            queries = summary.get("queries", {})
            timing = summary.get("timing", {})
            lines.append("## Summary")
            lines.append("")
            lines.append(f"- Total Queries: {queries.get('total', 'N/A')}")
            lines.append(f"- Total Runtime: {timing.get('total_ms', 'N/A')} ms")
            lines.append("")

        if "queries" in results:
            lines.append("## Query Results")
            lines.append("")
            lines.append("| Query | Runtime (ms) | Status |")
            lines.append("|-------|-------------|--------|")
            for q in results.get("queries", [])[:20]:
                lines.append(f"| {q.get('id', 'N/A')} | {q.get('ms', 'N/A')} | {q.get('status', 'N/A')} |")
    else:
        # Plain text format
        benchmark = results.get("benchmark", {})
        benchmark_name = benchmark.get("name") or benchmark.get("id") or "Unknown"
        lines.append(f"Benchmark Results: {benchmark_name}")
        lines.append(f"Platform: {results.get('platform', {}).get('name', 'Unknown')}")
        lines.append(f"Scale Factor: {benchmark.get('scale_factor', 'Unknown')}")
        lines.append("")

        if "summary" in results:
            summary = results["summary"]
            queries = summary.get("queries", {})
            timing = summary.get("timing", {})
            lines.append("Summary:")
            lines.append(f"  Total Queries: {queries.get('total', 'N/A')}")
            lines.append(f"  Total Runtime: {timing.get('total_ms', 'N/A')} ms")

    return {"format": format, "content": "\n".join(lines)}
