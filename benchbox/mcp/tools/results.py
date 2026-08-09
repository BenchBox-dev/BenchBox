"""Results tools for BenchBox MCP server.

Provides tools for retrieving, comparing, and exporting benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from benchbox.core.constants import EXPORT_FORMATS, MCP_RESULT_FORMATS
from benchbox.core.results.loader import ResultLoadError, UnsupportedSchemaError, load_result_file
from benchbox.mcp.errors import ErrorCode, make_error
from benchbox.mcp.security import PathProvider, resolve_path_provider
from benchbox.mcp.tools.path_utils import resolve_result_file_path
from benchbox.validation.bundle import COMPANION_SUFFIXES

logger = logging.getLogger(__name__)

# Tool annotations for read-only results tools
RESULTS_READONLY_ANNOTATIONS = ToolAnnotations(
    title="Read benchmark results",
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

# Tool annotations for export (creates files)
EXPORT_ANNOTATIONS = ToolAnnotations(
    title="Export benchmark results",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def register_results_tools(mcp: MCPServer, *, results_dir: PathProvider) -> None:
    """Register results tools with the MCP server."""

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
            return _list_recent_runs_impl(limit, platform, benchmark, resolve_path_provider(results_dir))

        # Get results for specific file
        configured_results_dir = resolve_path_provider(results_dir)
        results = _get_results_impl(result_file, include_queries, results_dir=configured_results_dir)
        if "error" in results:
            return results

        # Handle different output formats
        format_lower = format.lower()
        if format_lower == "details":
            return results
        elif format_lower in EXPORT_FORMATS:
            return _export_results_impl(results, result_file, format_lower, output_path, configured_results_dir)
        elif format_lower in ("text", "markdown"):
            return _export_summary_impl(results, format_lower)
        else:
            return make_error(
                ErrorCode.VALIDATION_INVALID_FORMAT,
                f"Invalid format: {format}",
                details={"valid_formats": list(MCP_RESULT_FORMATS)},
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

    result_files = [path for path in results_dir.glob("*.json") if not path.name.endswith(COMPANION_SUFFIXES)]

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
            logger.warning("Could not parse result file %s (%s)", file_path.name, type(e).__name__)
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
        from benchbox.core.results.html_report import generate_html_report

        content = generate_html_report(results)

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


def _export_summary_impl(results: dict[str, Any], format: str) -> dict[str, Any]:
    """Export formatted summary of benchmark results (transport wrapper)."""
    from benchbox.core.results.html_report import generate_summary_content

    return generate_summary_content(results, format)
