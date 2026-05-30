"""Flight data benchmark queries.

20 OLAP queries across 5 categories covering US aviation on-time performance:
- On-time performance (5 queries)
- Delay analysis (4 queries)
- Route analytics (4 queries)
- Temporal patterns (4 queries)
- Carrier comparisons (3 queries)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any, Optional

import sqlglot
from sqlglot import exp

from benchbox.core.static_query_catalog import load_static_query_catalog
from benchbox.sql_compat.local_exemptions import compat_local

QUERIES: dict[str, dict[str, Any]] = load_static_query_catalog(__package__)["QUERIES"]


class FlightDataQueryManager:
    """Manages flight data benchmark queries with parameterization.

    Handles query retrieval, parameter injection, and metadata access
    for the 20 flight data OLAP queries.
    """

    def __init__(self, start_date: str, end_date: str) -> None:
        """Initialize query manager with date range.

        Args:
            start_date: Start date for queries (YYYY-MM-DD format)
            end_date: End date for queries (YYYY-MM-DD format)
        """
        self.start_date = start_date
        self.end_date = end_date

    @compat_local(
        kind="rendering",
        platform_specific=True,
        reason=(
            "Renders FlightData SQL for PostgreSQL-family engines by casting ROUND inputs "
            "to DECIMAL where PostgreSQL does not accept ROUND(double precision, integer)."
        ),
    )
    def get_query(
        self,
        query_key: str,
        params: Optional[dict[str, Any]] = None,
        dialect: str | None = None,
    ) -> str:
        """Get parameterized SQL for a specific query.

        Args:
            query_key: Query identifier (e.g., "ontime-by-carrier")
            params: Optional parameter overrides
            dialect: Optional target SQL dialect.

        Returns:
            Parameterized SQL string

        Raises:
            ValueError: If query_key is not found
        """
        if query_key not in QUERIES:
            # Try by numeric ID
            for key, qdef in QUERIES.items():
                if str(qdef.get("id")) == str(query_key):
                    query_key = key
                    break
            else:
                raise ValueError(f"Unknown query: {query_key!r}. Valid keys: {list(QUERIES.keys())}")

        query_def = QUERIES[query_key]
        sql = query_def["sql"].strip()

        # Apply date range parameters
        effective_params = {
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        if params:
            effective_params.update(params)

        try:
            rendered = sql.format(**effective_params)
        except KeyError as exc:
            raise ValueError(
                f"Query {query_key!r} requires parameter {exc} not found in: {list(effective_params)}"
            ) from exc

        if dialect in {"postgres", "postgresql"}:
            return _render_postgres_query(rendered)
        return rendered

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all queries with applied date parameters.

        Returns:
            Dictionary mapping query keys to parameterized SQL strings
        """
        return {key: self.get_query(key, dialect=dialect) for key in QUERIES}

    def get_query_count(self) -> int:
        """Get number of queries."""
        return len(QUERIES)

    def get_categories(self) -> list[str]:
        """Get list of query categories."""
        return sorted(set(q["category"] for q in QUERIES.values()))

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query keys for a specific category.

        Args:
            category: Category name (ontime, delay, routes, temporal, carriers)

        Returns:
            List of query keys in that category
        """
        return [key for key, q in QUERIES.items() if q["category"] == category]

    def get_query_info(self, query_key: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_key: Query identifier

        Returns:
            Dictionary with query metadata
        """
        if query_key not in QUERIES:
            raise ValueError(f"Unknown query: {query_key!r}")
        q = QUERIES[query_key]
        return {
            "id": q["id"],
            "name": q["name"],
            "description": q["description"],
            "category": q["category"],
            "key": query_key,
        }


def _render_postgres_query(sql: str) -> str:
    """Render FlightData SQL for PostgreSQL-family engines."""
    tree = sqlglot.parse_one(sql, read="duckdb")

    def cast_round_input(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Round):
            node = node.copy()
            node.set("this", exp.cast(node.this.copy(), "DECIMAL"))
        return node

    return tree.transform(cast_round_input).sql(dialect="postgres", identify=True)
