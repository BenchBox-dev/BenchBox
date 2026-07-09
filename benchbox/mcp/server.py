"""BenchBox MCP Server implementation.

This module creates and configures the FastMCP server with all BenchBox
tools, resources, and prompts.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from benchbox.core.runtime_paths import resolve_runtime_paths
from benchbox.mcp.prompts import register_all_prompts
from benchbox.mcp.resources import register_all_resources
from benchbox.mcp.tools.analytics import register_analytics_tools
from benchbox.mcp.tools.benchmark import register_benchmark_tools
from benchbox.mcp.tools.discovery import register_discovery_tools
from benchbox.mcp.tools.results import register_results_tools
from benchbox.mcp.tools.visualization import register_visualization_tools

# Configure logging to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)


def _resolve_log_level(
    explicit_log_level: str | int | None,
    *,
    env: Mapping[str, str] | None = None,
) -> int:
    """Resolve MCP logging level with precedence explicit > env > INFO."""
    if isinstance(explicit_log_level, int):
        return explicit_log_level

    source = explicit_log_level
    if source is None:
        env_map = env if env is not None else os.environ
        source = env_map.get("BENCHBOX_LOG_LEVEL")

    if source is None:
        return logging.INFO

    if isinstance(source, str):
        stripped = source.strip()
        if stripped.isdigit():
            return int(stripped)
        resolved = logging.getLevelName(stripped.upper())
        if isinstance(resolved, int):
            return resolved

    return logging.INFO


def create_benchbox_server(
    *,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    log_level: str | int | None = None,
    env: Mapping[str, str] | None = None,
) -> FastMCP:
    """Create and configure the BenchBox MCP server.

    The server provides tools for:
    - Discovery: List platforms, benchmarks, and system info
    - Benchmark execution: Run benchmarks, validate configs, dry-run
    - Results: Get results, compare runs, export data

    Returns:
        Configured FastMCP server instance.
    """
    # Suppress all console output - MCP servers must not write to stdout
    # (stdout is reserved exclusively for JSON-RPC messages)
    from benchbox.utils.printing import set_quiet

    set_quiet(True)
    logging.getLogger().setLevel(_resolve_log_level(log_level, env=env))

    # Resolve paths only when not already provided (avoids double resolution
    # when called from cli.py which pre-resolves via resolve_runtime_paths).
    if results_dir is not None and charts_dir is not None:
        resolved_results_dir = Path(results_dir)
        resolved_charts_dir = Path(charts_dir)
    else:
        runtime_paths = resolve_runtime_paths(
            results_dir=results_dir,
            charts_dir=charts_dir,
            env=env,
        )
        resolved_results_dir = runtime_paths.results_dir
        resolved_charts_dir = runtime_paths.charts_dir

    # Create the FastMCP server
    mcp = FastMCP(
        name="benchbox",
        instructions="""BenchBox is a SQL benchmarking framework for OLAP databases.

Use these tools to:
1. **Discover** available platforms and benchmarks (list_available, get_benchmark_info)
2. **Run** benchmarks with specific configurations (run_benchmark with dry_run/validate_only flags)
3. **Analyze** results and compare runs (get_results, analyze_results)
4. **Visualize** results with BenchBox semantic charts (generate_chart, suggest_charts)

Start by listing available benchmarks or platforms to see what's possible.
For a quick test, try: run_benchmark(platform="duckdb", benchmark="tpch", scale_factor=0.01)
Then visualize: generate_chart(result_files="<result_file>", chart_type="performance_bar")
BenchBox chart IDs are result-aware semantic IDs such as performance_bar,
power_bar, and query_heatmap. They are separate from raw textcharts primitive
tool names such as textcharts_bar or textcharts_heatmap, which belong to the
external textcharts MCP server if that server is configured separately.

To capture query execution plans, use the capture_plans parameter:
  run_benchmark(platform="datafusion", benchmark="tpch", capture_plans=True)
Then inspect plans: get_query_plan(result_file="...", query_id="19")
""",
    )

    # Register all tools
    logger.info("Registering discovery tools...")
    register_discovery_tools(mcp)

    logger.info("Registering benchmark execution tools...")
    register_benchmark_tools(mcp, results_dir=resolved_results_dir)

    logger.info("Registering results tools...")
    register_results_tools(mcp, results_dir=resolved_results_dir)

    logger.info("Registering analytics tools...")
    register_analytics_tools(mcp, results_dir=resolved_results_dir)

    logger.info("Registering visualization tools...")
    register_visualization_tools(
        mcp,
        results_dir=resolved_results_dir,
        charts_dir=resolved_charts_dir,
    )

    logger.info("Registering resources...")
    register_all_resources(mcp, results_dir=resolved_results_dir)

    logger.info("Registering prompts...")
    register_all_prompts(mcp)

    # Path options are threaded through here and consumed by MCP modules.
    # They are logged for startup visibility.
    logger.info(
        "MCP path configuration: results_dir=%s charts_dir=%s",
        resolved_results_dir,
        resolved_charts_dir,
    )
    logger.info("BenchBox MCP server configured successfully")

    return mcp
