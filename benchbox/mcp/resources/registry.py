"""Resource registration for BenchBox MCP server.

Provides read-only access to BenchBox metadata through MCP resources.

This module uses the core benchmark registry for all benchmark metadata.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from benchbox.core.benchmark_registry import (
    get_all_benchmarks,
    get_benchmark_default_scale,
    get_benchmark_metadata,
    get_benchmark_surface,
    get_public_benchmark_class,
    list_public_benchmark_ids,
)

logger = logging.getLogger(__name__)


def _build_benchmarks_list() -> str:
    """Build JSON response listing all available benchmarks."""
    all_benchmarks = get_all_benchmarks()
    benchmarks = [
        {
            "name": name,
            "display_name": meta.get("display_name", name),
            "description": meta.get("description", ""),
            "category": meta.get("category", "unknown"),
            "support_status": meta["support_status"],
            "query_count": meta.get("num_queries", 0),
        }
        for name, meta in all_benchmarks.items()
        if get_benchmark_surface(name) == "public"
    ]
    return json.dumps({"benchmarks": benchmarks, "count": len(benchmarks)}, indent=2)


def _get_benchmark_query_ids(benchmark_lower: str, name: str) -> list[str]:
    """Attempt to load query IDs for a benchmark."""
    query_ids: list[str] = []
    try:
        benchmark_class = get_public_benchmark_class(benchmark_lower)
        if benchmark_class is not None:
            bm = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_lower))
            if hasattr(bm, "query_manager") and hasattr(bm.query_manager, "get_all_queries"):
                queries_dict = bm.query_manager.get_all_queries()
                query_ids = list(queries_dict.keys())
            elif hasattr(bm, "get_query_ids"):
                query_ids = bm.get_query_ids()
    except Exception as e:
        logger.debug(f"Could not load benchmark {name}: {e}")
    return query_ids


def _build_benchmark_detail(name: str) -> str:
    """Build JSON response with detailed benchmark information."""
    benchmark_lower = name.lower()
    meta = get_benchmark_metadata(benchmark_lower)

    if meta is None or get_benchmark_surface(benchmark_lower) != "public":
        return json.dumps(
            {
                "error": f"Benchmark '{name}' not found",
                "available": list_public_benchmark_ids(),
            }
        )

    query_ids = _get_benchmark_query_ids(benchmark_lower, name)

    return json.dumps(
        {
            "name": benchmark_lower,
            "display_name": meta.get("display_name", benchmark_lower),
            "description": meta.get("description", ""),
            "category": meta.get("category", "unknown"),
            "support_status": meta["support_status"],
            "query_count": meta.get("num_queries", len(query_ids)),
            "query_ids": query_ids,
            "scale_factors": {
                "default": meta.get("default_scale", 0.01),
                "options": meta.get("scale_options", [0.01, 0.1, 1, 10]),
                "minimum": meta.get("min_scale", 0.01),
            },
            "complexity": meta.get("complexity", "Medium"),
            "estimated_time_minutes": meta.get("estimated_time_range", (1, 5)),
            "dataframe_support": meta.get("supports_dataframe", False),
        },
        indent=2,
    )


def _build_platforms_list() -> str:
    """Build JSON response listing all available platforms."""
    from benchbox.core.platform_registry import PlatformRegistry

    platforms = []
    all_metadata = PlatformRegistry.get_all_platform_metadata()

    for name, metadata in all_metadata.items():
        capabilities = metadata.get("capabilities", {})
        info = PlatformRegistry.get_platform_info(name)

        platforms.append(
            {
                "name": name,
                "display_name": metadata.get("display_name", name),
                "category": metadata.get("category", "unknown"),
                "available": info.available if info else False,
                "supports_sql": capabilities.get("supports_sql", False),
                "supports_dataframe": capabilities.get("supports_dataframe", False),
            }
        )

    return json.dumps({"platforms": platforms, "count": len(platforms)}, indent=2)


def _build_platform_detail(name: str) -> str:
    """Build JSON response with detailed platform information."""
    from benchbox.core.platform_registry import PlatformRegistry

    all_metadata = PlatformRegistry.get_all_platform_metadata()
    platform_lower = name.lower()

    if platform_lower not in all_metadata:
        return json.dumps(
            {
                "error": f"Platform '{name}' not found",
                "available": list(all_metadata.keys()),
            }
        )

    metadata = all_metadata[platform_lower]
    capabilities = metadata.get("capabilities", {})
    info = PlatformRegistry.get_platform_info(platform_lower)

    return json.dumps(
        {
            "name": platform_lower,
            "display_name": metadata.get("display_name", platform_lower),
            "description": metadata.get("description", ""),
            "category": metadata.get("category", "unknown"),
            "available": info.available if info else False,
            "adoption": metadata.get("adoption", "niche"),
            "installation_command": metadata.get("installation_command", ""),
            "capabilities": {
                "supports_sql": capabilities.get("supports_sql", False),
                "supports_dataframe": capabilities.get("supports_dataframe", False),
                "default_mode": capabilities.get("default_mode", "sql"),
            },
        },
        indent=2,
    )


def _parse_result_file_metadata(file_path: Path) -> dict | None:
    """Parse a single result file into run metadata, or None on failure."""
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        benchmark_block = data.get("benchmark", {}) if isinstance(data.get("benchmark"), dict) else {}
        return {
            "file": file_path.name,
            "platform": data.get("platform", {}).get("name", "unknown"),
            "benchmark": benchmark_block.get("id", "unknown"),
            "scale_factor": benchmark_block.get("scale_factor", "unknown"),
            "timestamp": data.get("run", {}).get("timestamp"),
            "execution_id": data.get("run", {}).get("id", "unknown"),
        }
    except Exception as e:
        logger.warning(f"Could not parse result file {file_path}: {e}")
        return None


def _build_recent_results(results_dir: Path) -> str:
    """Build JSON response listing recent benchmark results."""
    if not results_dir.exists():
        return json.dumps(
            {
                "runs": [],
                "count": 0,
                "message": f"No results directory found at {results_dir}",
            }
        )

    result_files = [
        path
        for path in results_dir.glob("*.json")
        if not path.name.endswith(".plans.json") and not path.name.endswith(".tuning.json")
    ]
    runs = []

    for file_path in sorted(result_files, key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        metadata = _parse_result_file_metadata(file_path)
        if metadata is not None:
            runs.append(metadata)

    return json.dumps({"runs": runs, "count": len(runs)}, indent=2)


def _build_system_profile() -> str:
    """Build JSON response with system profile information."""
    import platform

    import psutil

    import benchbox

    memory = psutil.virtual_memory()

    package_versions = {}
    for pkg in ["polars", "pandas", "duckdb", "pyarrow"]:
        try:
            mod = __import__(pkg)
            package_versions[pkg] = getattr(mod, "__version__", "unknown")
        except ImportError:
            package_versions[pkg] = "not installed"

    return json.dumps(
        {
            "cpu": {
                "cores": psutil.cpu_count(logical=False) or 1,
                "threads": psutil.cpu_count(logical=True) or 1,
                "architecture": platform.machine(),
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
            },
            "python": {
                "version": platform.python_version(),
            },
            "packages": package_versions,
            "benchbox_version": getattr(benchbox, "__version__", "unknown"),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
            },
        },
        indent=2,
    )


def register_all_resources(mcp: FastMCP, *, results_dir: Path) -> None:
    """Register all MCP resources with the server.

    Args:
        mcp: The FastMCP server instance to register resources with.
    """

    resolved_results_dir = Path(results_dir).expanduser()

    @mcp.resource("benchbox://benchmarks")
    def list_benchmarks_resource() -> str:
        """List all available benchmarks."""
        return _build_benchmarks_list()

    @mcp.resource("benchbox://benchmarks/{name}")
    def get_benchmark_resource(name: str) -> str:
        """Get detailed information about a specific benchmark."""
        return _build_benchmark_detail(name)

    @mcp.resource("benchbox://platforms")
    def list_platforms_resource() -> str:
        """List all available database platforms."""
        return _build_platforms_list()

    @mcp.resource("benchbox://platforms/{name}")
    def get_platform_resource(name: str) -> str:
        """Get detailed information about a specific platform."""
        return _build_platform_detail(name)

    @mcp.resource("benchbox://results/recent")
    def get_recent_results_resource() -> str:
        """Get list of recent benchmark results."""
        return _build_recent_results(resolved_results_dir)

    @mcp.resource("benchbox://system/profile")
    def get_system_profile_resource() -> str:
        """Get current system profile information."""
        return _build_system_profile()

    logger.info("Registered MCP resources")
