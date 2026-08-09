"""Query complexity hints — benchmark-owned metadata for MCP/CLI/analysis surfaces.

Previously in ``benchbox.mcp.tools.benchmark._get_query_complexity_hints``.
Moved to core so the hint table is a single source of truth owned by the
benchmark domain, not the MCP transport.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

_TPCH_HINTS: dict[str, dict[str, Any]] = {
    "1": {"type": "aggregation", "tables": ["lineitem"], "complexity": "simple", "joins": 0},
    "2": {
        "type": "correlated_subquery",
        "tables": ["part", "supplier", "partsupp", "nation", "region"],
        "complexity": "complex",
        "joins": 5,
    },
    "3": {
        "type": "join_aggregate",
        "tables": ["customer", "orders", "lineitem"],
        "complexity": "medium",
        "joins": 2,
    },
    "4": {"type": "exists_subquery", "tables": ["orders", "lineitem"], "complexity": "medium", "joins": 1},
    "5": {
        "type": "multi_join",
        "tables": ["customer", "orders", "lineitem", "supplier", "nation", "region"],
        "complexity": "complex",
        "joins": 5,
    },
    "6": {"type": "scan_filter", "tables": ["lineitem"], "complexity": "simple", "joins": 0},
    "7": {
        "type": "multi_join",
        "tables": ["supplier", "lineitem", "orders", "customer", "nation"],
        "complexity": "complex",
        "joins": 6,
    },
    "8": {
        "type": "multi_join",
        "tables": ["part", "supplier", "lineitem", "orders", "customer", "nation", "region"],
        "complexity": "complex",
        "joins": 7,
    },
    "9": {
        "type": "multi_join",
        "tables": ["part", "supplier", "lineitem", "partsupp", "orders", "nation"],
        "complexity": "complex",
        "joins": 5,
    },
    "10": {
        "type": "join_aggregate",
        "tables": ["customer", "orders", "lineitem", "nation"],
        "complexity": "medium",
        "joins": 3,
    },
    "11": {
        "type": "having_subquery",
        "tables": ["partsupp", "supplier", "nation"],
        "complexity": "medium",
        "joins": 2,
    },
    "12": {"type": "case_aggregate", "tables": ["orders", "lineitem"], "complexity": "medium", "joins": 1},
    "13": {"type": "outer_join", "tables": ["customer", "orders"], "complexity": "medium", "joins": 1},
    "14": {"type": "case_aggregate", "tables": ["lineitem", "part"], "complexity": "simple", "joins": 1},
    "15": {"type": "view_with_max", "tables": ["lineitem", "supplier"], "complexity": "medium", "joins": 1},
    "16": {
        "type": "distinct_aggregate",
        "tables": ["partsupp", "part", "supplier"],
        "complexity": "medium",
        "joins": 2,
    },
    "17": {"type": "correlated_subquery", "tables": ["lineitem", "part"], "complexity": "complex", "joins": 1},
    "18": {
        "type": "having_subquery",
        "tables": ["customer", "orders", "lineitem"],
        "complexity": "complex",
        "joins": 3,
    },
    "19": {"type": "or_predicates", "tables": ["lineitem", "part"], "complexity": "medium", "joins": 1},
    "20": {
        "type": "exists_subquery",
        "tables": ["supplier", "nation", "partsupp", "part", "lineitem"],
        "complexity": "complex",
        "joins": 4,
    },
    "21": {
        "type": "not_exists",
        "tables": ["supplier", "lineitem", "orders", "nation"],
        "complexity": "complex",
        "joins": 4,
    },
    "22": {"type": "not_exists", "tables": ["customer", "orders"], "complexity": "complex", "joins": 1},
}


def get_query_complexity_hints(benchmark: str, query_id: str) -> dict[str, Any]:
    """Get complexity hints for a specific query.

    Args:
        benchmark: Benchmark id (e.g. ``"tpch"``).
        query_id: Normalised query id without prefix (e.g. ``"1"``).

    Returns:
        Hint dict for known queries, or an ``unknown`` sentinel.
    """
    if benchmark == "tpch" and query_id in _TPCH_HINTS:
        return _TPCH_HINTS[query_id]

    return {
        "type": "unknown",
        "complexity": "unknown",
        "note": f"Complexity hints not available for {benchmark} query {query_id}",
    }
