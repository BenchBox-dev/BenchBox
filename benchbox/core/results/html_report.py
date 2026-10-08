# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import html
from typing import Any


def generate_html_report(results: dict[str, Any]) -> str:
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


def generate_summary_content(results: dict[str, Any], format: str) -> dict[str, Any]:
    lines: list[str] = []

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
