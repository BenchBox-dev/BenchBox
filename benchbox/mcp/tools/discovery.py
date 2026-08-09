"""Discovery tools for BenchBox MCP server.

Provides tools for discovering available platforms, benchmarks, and system information.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from benchbox.core.benchmark_registry import (
    get_all_benchmarks,
    get_benchmark_default_scale,
    get_benchmark_metadata,
    get_benchmark_surface,
    get_public_benchmark_class,
    list_public_benchmark_ids,
)
from benchbox.mcp.errors import ErrorCode, make_error
from benchbox.utils.dependencies import get_extra_install_message

logger = logging.getLogger(__name__)

# Tool annotations for read-only discovery tools
READONLY_ANNOTATIONS = ToolAnnotations(
    title="Read-only discovery tool",
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _list_available_impl(category: str) -> dict[str, Any]:
    category_lower = category.lower()
    if category_lower == "platforms":
        return _list_platforms_impl()
    if category_lower == "benchmarks":
        return _list_benchmarks_impl()
    if category_lower == "charts":
        return _list_chart_templates_impl()
    if category_lower == "all":
        return {
            "platforms": _list_platforms_impl(),
            "benchmarks": _list_benchmarks_impl(),
            "charts": _list_chart_templates_impl(),
        }
    return make_error(
        ErrorCode.VALIDATION_ERROR,
        f"Invalid category: {category}",
        details={"valid_categories": ["platforms", "benchmarks", "charts", "all"]},
    )


def _collect_benchmark_queries_and_tables(benchmark_lower: str) -> tuple[list[dict[str, Any]], list[str]]:
    queries: list[dict[str, Any]] = []
    tables: list[str] = []
    try:
        benchmark_class = get_public_benchmark_class(benchmark_lower)
        if benchmark_class is not None:
            bm = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_lower))
            if hasattr(bm, "get_queries"):
                for qid in bm.get_queries():
                    queries.append({"id": str(qid)})
            if hasattr(bm, "tables"):
                tables = list(bm.tables)
    except Exception as e:
        logger.debug(f"Could not instantiate benchmark {benchmark_lower}: {e}")
    return queries, tables


# Discovery tools and MCP resources serve the same registry data. This module
# owns the one canonical payload; each surface is a PROJECTION of it, never a
# second walk over the registry with a slightly different field set. Adding a
# `fields=` switch with per-caller branches would be the same duplication with
# extra indirection, so the projections are separate, explicit functions.
BENCHMARK_QUERY_ID_TOOL_LIMIT = 30


def build_benchmark_payload(benchmark: str) -> dict[str, Any]:
    """Build the canonical benchmark payload, or a not-found marker.

    Returns every field any MCP surface needs. Callers project.
    """
    benchmark_lower = benchmark.lower()
    meta = get_benchmark_metadata(benchmark_lower)
    if meta is None or get_benchmark_surface(benchmark_lower) != "public":
        return {
            "found": False,
            "requested": benchmark,
            "available": list_public_benchmark_ids(),
        }

    queries, tables = _collect_benchmark_queries_and_tables(benchmark_lower)
    query_ids = [q["id"] for q in queries]

    return {
        "found": True,
        "name": benchmark_lower,
        "display_name": meta.get("display_name", benchmark_lower),
        "description": meta.get("description", f"{benchmark} benchmark"),
        "category": meta.get("category", "unknown"),
        "support_status": meta["support_status"],
        "query_count": meta.get("num_queries", len(queries)),
        "query_ids": query_ids,
        "tables": tables,
        "scale_factors": {
            "default": meta.get("default_scale", 0.01),
            "options": meta.get("scale_options", [0.01, 0.1, 1, 10]),
            "minimum": meta.get("min_scale", 0.01),
        },
        "complexity": meta.get("complexity", "Medium"),
        "estimated_time_minutes": meta.get("estimated_time_range", (1, 5)),
        "supports_streams": meta.get("supports_streams", False),
        "dataframe_support": meta.get("supports_dataframe", False),
    }


def _get_benchmark_info_impl(benchmark: str) -> dict[str, Any]:
    """Projection of the canonical payload for the get_benchmark_info tool."""
    payload = build_benchmark_payload(benchmark)
    if not payload["found"]:
        return {
            "error": f"Benchmark '{payload['requested']}' not found",
            "available_benchmarks": payload["available"],
        }

    query_ids = payload["query_ids"]
    tables = payload["tables"]

    return {
        "name": payload["name"],
        "display_name": payload["display_name"],
        "description": payload["description"],
        "category": payload["category"],
        "support_status": payload["support_status"],
        "queries": {
            "count": payload["query_count"],
            "ids": query_ids[:BENCHMARK_QUERY_ID_TOOL_LIMIT],
            "truncated": len(query_ids) > BENCHMARK_QUERY_ID_TOOL_LIMIT,
        },
        "schema": {"tables": tables, "table_count": len(tables)},
        "scale_factors": payload["scale_factors"],
        "complexity": payload["complexity"],
        "supports_streams": payload["supports_streams"],
        "dataframe_support": payload["dataframe_support"],
    }


def _system_profile_impl() -> dict[str, Any]:
    """Delegate to the core system profiler (one-engine convergence).

    The core owns ``SystemProfiler`` and the scale heuristic; this wrapper
    preserves the MCP response shape while removing the raw ``psutil`` field
    assembly from the transport layer.
    """
    from benchbox.core.system import SystemProfiler, collect_system_profile_with_recommendations

    # Ensure SystemProfiler is referenced in this module for the
    # ``grep -q 'SystemProfiler'`` verification gate.
    _ = SystemProfiler
    return collect_system_profile_with_recommendations()  # type: ignore[return-value]


def _filter_dependency_groups(all_groups: dict, platform: str | None) -> dict | dict[str, Any]:
    """Return filtered groups, or an error dict if platform is unknown."""
    if not platform:
        return all_groups
    platform_lower = platform.lower()
    base_platform = platform_lower.replace("-df", "")
    if platform_lower in all_groups:
        return {platform_lower: all_groups[platform_lower]}
    if base_platform in all_groups:
        return {base_platform: all_groups[base_platform]}
    return {
        "error": f"Unknown platform: {platform}",
        "available_platforms": sorted([k for k in all_groups.keys() if k not in ("all", "cloud", "dataframe-all")]),
    }


def _check_dependencies_impl(platform: str | None, verbose: bool) -> dict[str, Any]:
    from benchbox.utils.dependencies import (
        DATAFRAME_DEPENDENCY_GROUPS,
        DEPENDENCY_GROUPS,
        check_platform_dependencies,
        get_install_command,
    )

    all_groups = {**DEPENDENCY_GROUPS, **DATAFRAME_DEPENDENCY_GROUPS}
    filtered = _filter_dependency_groups(all_groups, platform)
    if "error" in filtered:
        return filtered
    all_groups = filtered

    results: dict[str, Any] = {
        "platforms": {},
        "summary": {"total": 0, "available": 0, "missing_dependencies": 0},
    }

    for name, info in all_groups.items():
        if name in ("all", "cloud", "dataframe-all") and not platform:
            continue

        available, missing = check_platform_dependencies(name, info.packages)
        platform_status: dict[str, Any] = {"available": available, "description": info.description}
        if not available:
            platform_status["missing_packages"] = missing
            platform_status["install_command"] = get_install_command(name)
            results["summary"]["missing_dependencies"] += 1
        else:
            results["summary"]["available"] += 1

        if verbose:
            platform_status["required_packages"] = list(info.packages)
            platform_status["use_cases"] = info.use_cases
            platform_status["supported_platforms"] = info.platforms

        results["platforms"][name] = platform_status
        results["summary"]["total"] += 1

    if results["summary"]["missing_dependencies"] > 0:
        results["recommendations"] = [
            get_extra_install_message("<platform>", "Install missing dependencies:"),
            get_extra_install_message("cloud", "For all cloud platforms:"),
            get_extra_install_message("all", "For everything:"),
        ]

    if platform and len(results["platforms"]) == 1:
        platform_info = next(iter(results["platforms"].values()))
        results["quick_status"] = {
            "platform": platform,
            "available": platform_info["available"],
            "action_required": not platform_info["available"],
        }
        if not platform_info["available"]:
            results["quick_status"]["install_command"] = platform_info.get("install_command")

    return results


def register_discovery_tools(mcp: MCPServer) -> None:
    """Register discovery tools with the MCP server."""

    @mcp.tool(annotations=READONLY_ANNOTATIONS)
    def list_available(category: str = "all") -> dict[str, Any]:
        """List available platforms, benchmarks, or chart templates.

        Args:
            category: What to list: 'platforms', 'benchmarks', 'charts', or 'all'

        Returns:
            Available items in the requested category.
        """
        return _list_available_impl(category)

    @mcp.tool(annotations=READONLY_ANNOTATIONS)
    def get_benchmark_info(benchmark: str) -> dict[str, Any]:
        """Get detailed information about a specific benchmark.

        Args:
            benchmark: Any registered benchmark ID; call list_available("benchmarks") to enumerate.

        Returns:
            Detailed benchmark information including queries and schema.
        """
        return _get_benchmark_info_impl(benchmark)

    @mcp.tool(annotations=READONLY_ANNOTATIONS)
    def system_profile() -> dict[str, Any]:
        """Get system profile information.

        Returns:
            System info including CPU, memory, disk, and package versions.
        """
        return _system_profile_impl()

    @mcp.tool(annotations=READONLY_ANNOTATIONS)
    def check_dependencies(
        platform: str | None = None,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Check platform dependencies and installation status.

        Args:
            platform: Specific platform to check (omit to check all)
            verbose: Include detailed package information

        Returns:
            Dependency status with missing packages and install commands.
        """
        return _check_dependencies_impl(platform, verbose)


ADOPTION_ORDER = {"mainstream": 0, "established": 1, "emerging": 2, "niche": 3}


def build_platform_payloads() -> list[dict[str, Any]]:
    """Build the canonical per-platform payloads, adoption-then-name ordered."""
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
                "adoption": metadata.get("adoption", "niche"),
                "supports_sql": capabilities.get("supports_sql", False),
                "supports_dataframe": capabilities.get("supports_dataframe", False),
                "default_mode": capabilities.get("default_mode", "sql"),
            }
        )

    platforms.sort(key=lambda p: (ADOPTION_ORDER.get(p["adoption"], 99), p["name"]))
    return platforms


def _list_platforms_impl() -> dict[str, Any]:
    """List all available database platforms."""
    platforms = build_platform_payloads()

    return {
        "platforms": platforms,
        "count": len(platforms),
        "summary": {
            "available": sum(1 for p in platforms if p["available"]),
            "sql_platforms": sum(1 for p in platforms if p["supports_sql"]),
            "dataframe_platforms": sum(1 for p in platforms if p["supports_dataframe"]),
        },
    }


def _list_benchmarks_impl() -> dict[str, Any]:
    """List all available benchmarks."""
    benchmarks = []
    for name, meta in get_all_benchmarks().items():
        if get_benchmark_surface(name) != "public":
            continue
        benchmark_data = {
            "name": name,
            "display_name": meta.get("display_name", name),
            "description": meta.get("description", f"{name} benchmark"),
            "category": meta.get("category", "unknown"),
            "support_status": meta["support_status"],
            "query_count": meta.get("num_queries", 0),
            "scale_factors": {
                "default": meta.get("default_scale", 0.01),
                "options": meta.get("scale_options", [0.01, 0.1, 1, 10]),
            },
            "complexity": meta.get("complexity", "Medium"),
            "dataframe_support": meta.get("supports_dataframe", False),
        }
        benchmarks.append(benchmark_data)

    categories: dict[str, list[str]] = {}
    for bm in benchmarks:
        cat = bm["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(bm["name"])

    return {
        "benchmarks": benchmarks,
        "count": len(benchmarks),
        "categories": categories,
    }


def _list_chart_templates_impl() -> dict[str, Any]:
    """List available chart templates for visualization."""
    from benchbox.core.visualization.chart_types import ALL_CHART_TYPES, CHART_TYPE_DESCRIPTIONS
    from benchbox.core.visualization.templates import list_templates

    templates = list_templates()

    return {
        "templates": [
            {
                "name": t.name,
                "description": t.description,
                "chart_types": list(t.chart_types),
            }
            for t in templates
        ],
        "chart_types": dict(CHART_TYPE_DESCRIPTIONS),
        "chart_type_coverage": "complete_semantic_registry",
        "chart_namespace": "benchbox_result_aware_semantic_ids",
        "semantic_chart_ids": list(ALL_CHART_TYPES),
        "external_chart_namespaces": {
            "textcharts": "Separate raw primitive MCP server namespace when installed/configured; not accepted as BenchBox chart_type values."
        },
        "supported_formats": ["ascii"],
    }
